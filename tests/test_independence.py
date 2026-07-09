"""Tests for the evidence-independence mechanism (engine/roots.py + engine/assess.py).

Mirrors the worked examples and adversarial cases in MECHANISM.md, so the spec and the code
can't drift apart silently.
"""
import unittest

from engine.assess import independence, method_audit, quote_audit, warnings, weighted_distribution
from engine.roots import resolve, tier_of


def _kb(sources, positions=("X", "Y"), vocab_evidence=None):
    hues = ["#111", "#222", "#333"]
    return {"positions": [{"id": p, "label": p, "hue": hues[i % 3]} for i, p in enumerate(positions)],
            "datasets": [], "factors": [], "sources": sources,
            "vocab": {"evidence": vocab_evidence or []}}


def _s(sid, pos, evidence, rests):
    return {"id": sid, "position": pos, "evidence": evidence, "title": sid, "restsOn": rests,
            "funding": "Undisclosed", "population": "—", "confidence": "unstated"}


def _roots(res, sid):
    return sorted(res["source_roots"][sid])


class TierTests(unittest.TestCase):
    def test_punctuated_types_classify(self):
        kb = _kb([])
        self.assertEqual(tier_of(kb, {"evidence": "Narrative/Commentary"}), "secondary")
        self.assertEqual(tier_of(kb, {"evidence": "Experimental (RCT)"}), "primary")
        self.assertEqual(tier_of(kb, {"evidence": "Observational"}), "primary")

    def test_unknown_type_defaults_primary(self):
        self.assertEqual(tier_of(_kb([]), {"evidence": "Cliodynamic field survey"}), "primary")

    def test_meta_analysis_is_secondary(self):
        # an untagged meta-analysis is echo, not an independent primary look
        self.assertEqual(tier_of(_kb([]), {"evidence": "Meta-analysis"}), "secondary")

    def test_vocab_tier_override_wins(self):
        kb = _kb([], vocab_evidence=[{"label": "Observational", "aliases": [], "tier": "secondary"}])
        self.assertEqual(tier_of(kb, {"evidence": "Observational"}), "secondary")


class ResolutionTests(unittest.TestCase):
    def test_echo_collapses_to_one_voice(self):
        kb = _kb([_s("a", "X", "Observational", ["D"]),
                  _s("b", "X", "Narrative/Commentary", []),
                  _s("c", "X", "Evidence-synthesis", []),
                  _s("d", "X", "Expert advisory", [])])
        res = resolve(kb)
        self.assertEqual(_roots(res, "a"), ["ds:D"])
        for sid in ("b", "c", "d"):
            self.assertEqual(_roots(res, sid), ["secpool:X"])

    def test_well_tagged_review_collapses_into_the_dataset(self):
        # E2: a review that restsOn the study it summarises needs no tier rule
        kb = _kb([_s("study", "X", "Observational", ["D"]),
                  _s("review", "X", "Evidence-synthesis", ["src:study"])])
        res = resolve(kb)
        self.assertEqual(_roots(res, "review"), ["ds:D"])

    def test_chain_resolves_to_terminal_dataset(self):
        kb = _kb([_s("a", "X", "Narrative/Commentary", ["src:b"]),
                  _s("b", "X", "Narrative/Commentary", ["src:c"]),
                  _s("c", "X", "Evidence-synthesis", ["D"])])
        res = resolve(kb)
        self.assertEqual(_roots(res, "a"), ["ds:D"])

    def test_pure_circular_corroboration_is_flagged(self):
        kb = _kb([_s("a", "X", "Narrative/Commentary", ["src:b"]),
                  _s("b", "X", "Narrative/Commentary", ["src:a"])])
        res = resolve(kb)
        self.assertEqual(_roots(res, "a"), _roots(res, "b"))   # collapse to one loop root
        self.assertEqual(len(res["circular"]), 1)
        self.assertEqual(res["circular"][0]["sources"], ["a", "b"])

    def test_circular_but_grounded_is_not_flagged(self):
        kb = _kb([_s("a", "X", "Observational", ["src:b", "D"]),
                  _s("b", "X", "Narrative/Commentary", ["src:a"])])
        res = resolve(kb)
        self.assertEqual(res["circular"], [])
        self.assertEqual(_roots(res, "a"), ["ds:D"])
        self.assertEqual(_roots(res, "b"), ["ds:D"])

    def test_dataset_via_secondary_only_is_marked(self):
        kb = _kb([_s("rev", "X", "Evidence-synthesis", ["D"])])
        res = resolve(kb)
        self.assertIn("ds:D", res["secondary_only"])

    def test_dataset_with_a_primary_source_is_not_secondary_only(self):
        kb = _kb([_s("study", "X", "Observational", ["D"]),
                  _s("rev", "X", "Evidence-synthesis", ["D"])])
        res = resolve(kb)
        self.assertNotIn("ds:D", res["secondary_only"])

    def test_self_loop_is_ignored(self):
        kb = _kb([_s("a", "X", "Observational", ["src:a"])])
        res = resolve(kb)          # rests only on itself -> ungrounded primary -> own root
        self.assertEqual(_roots(res, "a"), ["prim:a"])

    def test_uppercase_src_prefix_is_still_a_source_edge_not_a_fake_dataset(self):
        # merge.py always stores restsOn edges lowercase, but a hand-authored/seed KB (SCHEMA.md)
        # bypasses that normalization -- "SRC:b" must not silently become dataset "SRC:b".
        kb = _kb([_s("a", "X", "Narrative/Commentary", ["SRC:b"]),
                  _s("b", "X", "Observational", ["D"])])
        res = resolve(kb)
        self.assertEqual(_roots(res, "a"), ["ds:D"])
        self.assertNotIn("ds:SRC:b", res["source_roots"]["a"])


class MetricTests(unittest.TestCase):
    """The gaming-resistance contract. Two ways to try to move nEff with worthless sources:
    UNGROUNDED junk (no restsOn) is absorbed by the one collapsed secondary voice; GROUNDED junk
    (resting on roots the KB already counts) is absorbed by presence-weighting — a root counts
    once no matter how many sources pile onto it. Both directions are covered: you can't inflate
    your own position, and you can't tank a rival by 'supporting' it with correlated junk. An
    earlier count-weighted formula passed the ungrounded tests below while failing the grounded
    ones (nEff 1.2 -> 2.0 under grounded echo; a rival's 5.0 -> 1.4 under grounded junk), so the
    grounded tests are the load-bearing ones — do not weaken them."""

    def _neff(self, srcs, pos="X"):
        return {p["id"]: p for p in independence(_kb(srcs))}[pos]["nEff"]

    def test_ungrounded_review_flood_cannot_inflate_independence(self):
        # one real study + a flood of ungrounded reviews -> exactly 2 bases (study + one voice)
        srcs = [_s("study", "X", "Observational", ["D"])]
        srcs += [_s("r%d" % i, "X", "Narrative/Commentary", []) for i in range(50)]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(ind["nEff"], 2.0, places=6)
        self.assertEqual(ind["collapsedSecondary"], 50)

    def test_grounded_echo_flood_cannot_inflate_independence(self):
        # THE attack the count-weighted formula failed: 10 sources on D1 + 1 on D2 reads as ~2
        # bases; echoing 9 more reviews onto the minority root D2 evens out the source shares but
        # adds no new root -- nEff must not move at all.
        srcs = [_s("d1_%d" % i, "X", "Observational", ["D1"]) for i in range(10)]
        srcs += [_s("d2", "X", "Observational", ["D2"])]
        base = self._neff(srcs)
        srcs += [_s("echo%d" % i, "X", "Systematic review", ["D2"]) for i in range(9)]
        self.assertAlmostEqual(self._neff(srcs), base, places=9)
        # ... and the same flood as primary 're-analyses' of D2 is just as inert
        srcs += [_s("re%d" % i, "X", "Observational", ["D2"]) for i in range(9)]
        self.assertAlmostEqual(self._neff(srcs), base, places=9)

    def test_grounded_junk_cannot_tank_a_rivals_independence(self):
        # Poisoning-by-agreement: pile junk 'support' onto one of a rival's roots. The rival's
        # nEff must hold at 5; the pile-up may only surface as CONCENTRATION rising.
        srcs = [_s("p%d" % i, "X", "Observational", ["D%d" % i]) for i in range(5)]
        base = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(base["nEff"], 5.0, places=6)
        srcs += [_s("junk%d" % i, "X", "Observational", ["D0"]) for i in range(20)]
        after = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(after["nEff"], 5.0, places=6)
        self.assertGreater(after["concentration"], base["concentration"])

    def test_ungrounded_review_flood_cannot_tank_a_rivals_independence(self):
        # ungrounded junk aimed at a rival adds exactly the one collapsed voice, then nothing
        srcs = [_s("p1", "X", "Observational", ["D1"]),
                _s("p2", "X", "Observational", ["D2"]),
                _s("p3", "X", "Observational", ["D3"])]
        base = self._neff(srcs)
        srcs += [_s("r%d" % i, "X", "Evidence-synthesis", []) for i in range(40)]
        self.assertAlmostEqual(self._neff(srcs), base + 1.0, places=6)  # + one voice, once
        srcs += [_s("r2_%d" % i, "X", "Evidence-synthesis", []) for i in range(40)]
        self.assertAlmostEqual(self._neff(srcs), base + 1.0, places=6)  # a second wave adds 0

    def test_new_root_raises_neff(self):
        # the ONLY honest way up: bring genuinely new evidence
        srcs = [_s("a", "X", "Observational", ["D1"])]
        self.assertAlmostEqual(self._neff(srcs), 1.0, places=6)
        srcs += [_s("b", "X", "Observational", ["D2"])]
        self.assertAlmostEqual(self._neff(srcs), 2.0, places=6)

    def test_primary_grounding_upgrades_a_review_only_root(self):
        # the other honest way up: a dataset known only via a review counts at half until a
        # primary source actually instantiates it
        srcs = [_s("rev", "X", "Systematic review", ["D"])]
        self.assertAlmostEqual(self._neff(srcs), 0.5, places=6)
        srcs += [_s("prim", "X", "Observational", ["D"])]
        self.assertAlmostEqual(self._neff(srcs), 1.0, places=6)

    def test_cohort_reuse_still_concentrates(self):
        srcs = [_s("p%d" % i, "X", "Observational", ["D"]) for i in range(8)]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(ind["nEff"], 1.0, places=6)   # 8 papers, one dataset = one look

    def test_bases_strengths_sum_to_neff(self):
        # the 'show your work' contract: the visible per-root strengths reproduce the headline
        srcs = [_s("a", "X", "Observational", ["D1", "D2"]),
                _s("b", "X", "Systematic review", ["D3"]),
                _s("c", "X", "Narrative/Commentary", [])]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(sum(b["strength"] for b in ind["bases"]), ind["nEff"], places=2)

    def test_weighted_distribution_sums_to_about_100(self):
        kb = _kb([_s("a", "X", "Observational", ["D1"]),
                  _s("b", "Y", "Narrative/Commentary", [])])
        self.assertEqual(sum(d["pct"] for d in weighted_distribution(kb)), 100)


class MonotonicityPropertyTests(unittest.TestCase):
    """Randomized check of the independence invariant: adding a source through the merge path
    (a new node with only OUTGOING restsOn edges — merge_delta can never create incoming edges
    or cycles) never lowers ANY position's nEff. Not just the flooded position's: a new primary
    source can shrink the global secondary_only / nonhuman_only sets, which only ever RAISES
    other positions' root strengths. A fixed seed keeps the run deterministic; the generator
    mixes grounded/ungrounded sources, primary/secondary/unknown evidence types, animal and
    human populations, shared and fresh datasets, and source->source derivation chains."""

    EVIDENCE = ["Observational", "Experimental (RCT)", "Systematic review",
                "Narrative/Commentary", "Meta-analysis", "Mechanistic", "Unclassified type"]
    POPULATION = ["—", "Adults", "Older adults", "Mice", "In vitro / cell culture"]

    def _rand_source(self, rng, sid, kb):
        pos = rng.choice([p["id"] for p in kb["positions"]])
        rests = []
        for _ in range(rng.randint(0, 3)):
            kind = rng.random()
            if kind < 0.45:                                    # an existing or fresh dataset
                rests.append("D%d" % rng.randint(0, 7))
            elif kind < 0.75 and kb["sources"]:                # derive from an existing source
                rests.append("src:" + rng.choice(kb["sources"])["id"])
            # else: leave this slot empty (contributes to ungrounded sources)
        return {"id": sid, "position": pos, "title": sid,
                "evidence": rng.choice(self.EVIDENCE),
                "population": rng.choice(self.POPULATION),
                "restsOn": rests, "funding": "Undisclosed", "confidence": "unstated"}

    def test_adding_a_source_never_lowers_any_positions_neff(self):
        import random
        rng = random.Random(20260707)
        for trial in range(12):
            kb = _kb([], positions=("X", "Y", "Z"))
            for i in range(2 + rng.randint(0, 3)):             # small seed KB
                kb["sources"].append(self._rand_source(rng, "seed%d_%d" % (trial, i), kb))
            for i in range(25):                                # then grow it one source at a time
                before = {p["id"]: p["nEff"] for p in independence(kb)}
                new = self._rand_source(rng, "s%d_%d" % (trial, i), kb)
                kb["sources"].append(new)
                after = {p["id"]: p["nEff"] for p in independence(kb)}
                for pid in before:
                    self.assertGreaterEqual(
                        after[pid], before[pid] - 1e-9,
                        "trial %d step %d: position %s nEff fell %.4f -> %.4f after adding %r"
                        % (trial, i, pid, before[pid], after[pid], new))


class MethodAuditTests(unittest.TestCase):
    def test_observational_default_flags_method_monoculture(self):
        kb = _kb([_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(4)])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["classed"], 4)
        self.assertEqual(m["top"]["method"], "confounding")
        self.assertTrue(m["monoculture"])

    def test_vocab_method_class_override_wins(self):
        kb = _kb([_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(3)],
                 vocab_evidence=[{"label": "Observational", "aliases": [],
                                  "methodClass": "measurement"}])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["top"]["method"], "measurement")

    def test_explicit_vocab_opt_out(self):
        kb = _kb([_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(3)],
                 vocab_evidence=[{"label": "Observational", "aliases": [],
                                  "methodClass": ""}])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["classed"], 0)
        self.assertFalse(m["monoculture"])

    def test_source_method_class_override_and_opt_out(self):
        a = _s("a", "X", "Observational", ["D1"])
        a["methodClass"] = "measurement"
        b = _s("b", "X", "Observational", ["D2"])
        b["methodClass"] = ""
        kb = _kb([a, b])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["classed"], 1)
        self.assertEqual(m["top"]["method"], "measurement")

    def test_secondary_sources_are_not_guessed(self):
        kb = _kb([_s("r%d" % i, "X", "Meta-analysis", ["D%d" % i]) for i in range(4)])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["classed"], 0)
        self.assertFalse(m["monoculture"])

    def test_method_monoculture_requires_position_coverage(self):
        srcs = [_s("o%d" % i, "X", "Observational", ["D%d" % i]) for i in range(3)]
        srcs += [_s("u%d" % i, "X", "Unspecified", ["U%d" % i]) for i in range(10)]
        m = {p["id"]: p for p in method_audit(_kb(srcs))}["X"]
        self.assertEqual(m["classed"], 3)
        self.assertLess(m["coverage"], 0.30)
        self.assertFalse(m["monoculture"])

    def test_rcts_do_not_share_a_default_method_root(self):
        kb = _kb([_s("rct%d" % i, "X", "Experimental (RCT)", ["D%d" % i]) for i in range(4)])
        m = {p["id"]: p for p in method_audit(kb)}["X"]
        self.assertEqual(m["classed"], 0)


class WarningsTests(unittest.TestCase):
    """warnings() unifies the concentration / method-bias / quote signals that used to be three
    separately-computed, separately-rendered fields (worstConcentration, methodMonoculture,
    quoteAudit["flagged"]). These tests pin the wording and selection so the consolidation is a
    pure refactor -- same information, one mechanism."""

    def test_no_warnings_on_a_clean_kb(self):
        srcs = [_s("p1", "X", "Observational", ["D1"]),
                _s("p2", "X", "Experimental (RCT)", ["D2"])]
        self.assertEqual(warnings(_kb(srcs)), [])

    def test_concentration_warning_names_the_worst_position(self):
        srcs = [_s("p%d" % i, "X", "Observational", ["D"]) for i in range(8)]
        ws = warnings(_kb(srcs))
        conc = [w for w in ws if w["kind"] == "concentration"]
        self.assertEqual(len(conc), 1)
        self.assertEqual(conc[0]["positionId"], "X")
        self.assertIn("Apparent consensus is correlated", conc[0]["headline"])
        self.assertIn("closer to", conc[0]["detail"])

    def test_method_monoculture_warning(self):
        srcs = [_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(4)]
        ws = warnings(_kb(srcs))
        mono = [w for w in ws if w["kind"] == "method-monoculture"]
        self.assertEqual(len(mono), 1)
        self.assertEqual(mono[0]["positionId"], "X")
        self.assertIn("observational confounding risk", mono[0]["detail"])

    def test_quote_warning_reports_first_flagged_source(self):
        s = _s("s1", "X", "Observational", ["D1"])
        s["textDepth"] = "full"
        s["provenance"] = {"position": {"quote": "x", "verifiedQuote": "missing"}}
        kb = _kb([s])
        ws = warnings(kb)
        quote = [w for w in ws if w["kind"] == "quote"]
        self.assertEqual(len(quote), 1)
        self.assertEqual(quote[0]["positionId"], "X")
        self.assertIn("s1", quote[0]["detail"])

    def test_low_confidence_warning_fires_on_weak_quote_grounding(self):
        srcs = [_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(3)]
        for s in srcs:
            s["provenance"] = {"position": {"quote": "q", "extractionConfidence": 0.2}}
        ws = warnings(_kb(srcs))
        weak = [w for w in ws if w["kind"] == "low-confidence"]
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["positionId"], "X")
        self.assertIn("weak quote", weak[0]["badge"])


    def test_model_disagreement_warning_carries_sources_and_votes(self):
        kb = _kb([_s("a", "X", "Observational", ["D1"])])
        kb["sources"][0]["title"] = "Contested paper"
        kb["sources"][0]["modelAgreement"] = {
            "models": 2, "flagged": True, "disagreedFields": ["position"],
            "positionVote": {"NEW:Increases": 1, "NEW:No effect": 1}}
        w = [x for x in warnings(kb) if x["kind"] == "model-disagreement"][0]
        self.assertEqual(w["label"], "1 source to review")
        self.assertEqual(len(w["sources"]), 1)
        self.assertEqual(w["sources"][0]["title"], "Contested paper")
        self.assertIn("NEW:Increases", w["sources"][0]["vote"])

    def test_precomputed_audits_can_be_passed_in_without_recomputing(self):
        from engine.assess import confidence_audit
        srcs = [_s("p%d" % i, "X", "Observational", ["D"]) for i in range(8)]
        kb = _kb(srcs)
        ind, ma, qa, ca = independence(kb), method_audit(kb), quote_audit(kb), confidence_audit(kb)
        self.assertEqual(warnings(kb, ind, ma, qa, ca), warnings(kb))


class GapTests(unittest.TestCase):
    def test_thin_position_with_no_primary_is_flagged_severe(self):
        from engine.gaps import find_gaps
        kb = _kb([_s("a", "X", "Narrative/Commentary", []),
                  _s("b", "X", "Expert advisory", []),
                  _s("c", "Y", "Observational", ["D1"]),
                  _s("d", "Y", "Observational", ["D2"])])
        gaps = find_gaps(kb)
        thin = [g for g in gaps if g["kind"] == "thin-position"]
        self.assertTrue(any(g["positionId"] == "X" and g["severity"] == 3 for g in thin))
        self.assertFalse(any(g["positionId"] == "Y" for g in thin))   # Y has 2 primary bases

    def test_secondary_only_dataset_becomes_a_gap(self):
        from engine.gaps import find_gaps
        kb = _kb([_s("rev", "X", "Evidence-synthesis", ["D"])])
        self.assertTrue(any(g["kind"] == "unsourced-dataset" and g["datasetId"] == "D"
                            for g in find_gaps(kb)))

    def test_gap_queries_are_nonempty_strings(self):
        from engine.gaps import find_gaps, gap_queries
        kb = _kb([_s("a", "X", "Narrative/Commentary", [])])
        kb["meta"] = {"question": "Does X cause Y?"}
        for q in gap_queries(kb, find_gaps(kb)):
            self.assertTrue(q["query"].strip())


if __name__ == "__main__":
    unittest.main()


class NonHumanTests(unittest.TestCase):
    def _s2(self, sid, pos, ev, rests, pop):
        d = _s(sid, pos, ev, rests); d["population"] = pop; return d

    def test_animal_only_root_is_halved(self):
        from engine.roots import resolve, root_strength
        kb = _kb([self._s2("m", "X", "Mechanistic", ["Dmouse"], "Mice")])
        res = resolve(kb)
        self.assertIn("ds:Dmouse", res["nonhuman_only"])
        self.assertEqual(root_strength("ds:Dmouse", res["secondary_only"], res["nonhuman_only"]), 0.5)

    def test_human_source_on_root_keeps_full_weight(self):
        from engine.roots import resolve, root_strength
        kb = _kb([self._s2("h", "X", "Observational", ["D"], "US adults"),
                  self._s2("m", "X", "Mechanistic", ["D"], "Mice")])
        res = resolve(kb)
        self.assertNotIn("ds:D", res["nonhuman_only"])
        self.assertEqual(root_strength("ds:D", res["secondary_only"], res["nonhuman_only"]), 1.0)

    def test_population_word_does_not_falsematch(self):
        from engine.roots import _is_nonhuman
        self.assertFalse(_is_nonhuman({"population": "moderate-risk adults"}))   # 'rat' in 'moderate'
        self.assertTrue(_is_nonhuman({"population": "Rats"}))
        self.assertTrue(_is_nonhuman({"population": "In vitro / cell"}))


class BudgetAndFundingTests(unittest.TestCase):
    def test_funding_blindspot_gap_fires_when_all_undisclosed(self):
        from engine.gaps import find_gaps
        srcs = [_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(5)]
        for s in srcs:
            s["funding"] = "Undisclosed"
        self.assertTrue(any(g["kind"] == "funding-blindspot" for g in find_gaps(_kb(srcs))))

    def test_funding_blindspot_silent_when_interested_funding_present(self):
        from engine.gaps import find_gaps
        srcs = [_s("s%d" % i, "X", "Observational", ["D%d" % i]) for i in range(5)]
        srcs[0]["funding"] = "Industry"
        self.assertFalse(any(g["kind"] == "funding-blindspot" for g in find_gaps(_kb(srcs))))

    def test_usage_accumulates_and_prices(self):
        from ingest import llm
        llm.reset_usage()
        llm._record_usage("claude-sonnet-5", {"usage": {"input_tokens": 1_000_000, "output_tokens": 0}})
        self.assertAlmostEqual(llm.usage()["usd"], 3.0, places=4)   # $3 / 1M input on sonnet

    def test_price_lookup_picks_longest_match_regardless_of_dict_order(self):
        # gemini-2.0-flash must get its own, more specific price rather than falling through to
        # the general "gemini" row -- this must hold no matter which row is defined first.
        from ingest import llm
        self.assertEqual(llm._price_for("gemini-2.0-flash"), llm._PRICE["gemini-2.0-flash"])
        self.assertNotEqual(llm._price_for("gemini-2.0-flash"), llm._PRICE["gemini"])
        self.assertEqual(llm._price_for("gemini-1.5-pro"), llm._PRICE["gemini"])
        self.assertEqual(llm._price_for("gpt-4o-mini"), llm._PRICE["gpt-4o-mini"])
        self.assertEqual(llm._price_for("totally-unknown-model"), llm._PRICE_DEFAULT)


class DedupTests(unittest.TestCase):
    def test_same_paper_two_urls_is_a_duplicate(self):
        from engine.schema import empty_kb
        from engine.merge import merge_delta
        kb = empty_kb("t", "Q?")
        merge_delta(kb, {"source": {"title": "Alcohol and CVD", "year": 2020,
                                    "url": "https://doi.org/10.1161/X", "position": "NEW:Decreases",
                                    "evidence": "Observational", "relevant": True}})
        rep = merge_delta(kb, {"source": {"title": "Alcohol and CVD: the full subtitle", "year": 2020,
                                          "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/?doi=10.1161/X",
                                          "position": "Decreases", "evidence": "Observational", "relevant": True}})
        self.assertTrue(rep.get("duplicate"))
        self.assertEqual(len(kb["sources"]), 1)

    def test_dedupe_sources_removes_title_truncation_dups(self):
        from engine import curate
        kb = _kb([_s("a", "X", "Observational", ["D1"]),
                  _s("b", "X", "Observational", ["D2"])])
        kb["sources"][0].update(title="Alcohol consumption and cardiovascular disease", year=2017)
        kb["sources"][1].update(title="Alcohol consumption and cardiovascular disease: an update", year=2017)
        kb["meta"] = {"version": 1}
        rep = curate.dedupe_sources(kb)
        self.assertEqual(len(rep["removed"]), 1)
        self.assertEqual(len(kb["sources"]), 1)
