"""Tests for the evidence-independence mechanism (engine/roots.py + engine/assess.py).

Mirrors the worked examples and adversarial cases in MECHANISM.md, so the spec and the code
can't drift apart silently.
"""
import hashlib
import unittest

from engine.assess import independence, method_audit, quote_audit, warnings, weighted_distribution
from engine.roots import resolve, tier_of


def _verified(quote):
    """A provenance record that could only have come from the strict verifier."""
    return {"quote": quote, "verifiedQuote": "exact", "quoteVerification": {
        "method": "verbatim-sentence-v2", "status": "exact", "textSha256": "a" * 64,
        "quoteSha256": hashlib.sha256(quote.strip().encode()).hexdigest()}}


def _kb(sources, positions=("X", "Y"), vocab_evidence=None):
    hues = ["#111", "#222", "#333"]
    return {"positions": [{"id": p, "label": p, "hue": hues[i % 3]} for i, p in enumerate(positions)],
            "datasets": [], "factors": [], "sources": sources,
            "vocab": {"evidence": vocab_evidence or []}}


def _s(sid, pos, evidence, rests, textDepth="full"):
    # Default full-text fixtures include a verified dependency quote when they name a root, so these
    # tests exercise confirmed collapse mechanics. Unknown-depth fixtures remain provisional even if
    # a quote field is present; explicit missing-edge cases override provenance below.
    admitted = {"status": "confirmed", "method": "curator", "by": "test-curator",
                "ts": "2026-07-14T00:00:00Z"}
    # Resolution fixtures model already-curated citation links. Dataset edges keep exercising the
    # verifier/confirmation path; source→source edges are explicitly admitted under the hardened
    # edge-specific trust model.
    trusted_rests = [({"ref": r, "admission": admitted} if isinstance(r, str)
                      and r.lower().startswith("src:") else r) for r in rests]
    s = {"id": sid, "position": pos, "evidence": evidence, "title": sid, "restsOn": trusted_rests,
         "funding": "Undisclosed", "population": "—", "confidence": "unstated", "textDepth": textDepth}
    s["provenance"] = {"position": _verified("verified position for " + sid)}
    if rests:
        s["provenance"]["restsOn"] = _verified("verified dependency for " + sid)
    return s


def _roots(res, sid):
    return sorted(res["source_roots"][sid])


class TierTests(unittest.TestCase):
    def test_punctuated_types_classify(self):
        kb = _kb([])
        self.assertEqual(tier_of(kb, {"evidence": "Narrative/Commentary"}), "secondary")
        self.assertEqual(tier_of(kb, {"evidence": "Experimental (RCT)"}), "primary")
        self.assertEqual(tier_of(kb, {"evidence": "Observational"}), "primary")

    def test_unknown_type_defaults_secondary(self):
        # conservative: an unrecognised / coined evidence label must NOT mint a free primary root.
        # A case with a genuinely new primary DESIGN opts in via vocab tier="primary".
        self.assertEqual(tier_of(_kb([]), {"evidence": "Cliodynamic field survey"}), "secondary")

    def test_recognised_primary_design_synonyms_classify(self):
        for ev in ("Cohort study", "Case-control", "Cross-sectional",
                   "Randomized controlled trial", "Clinical trial"):
            self.assertEqual(tier_of(_kb([]), {"evidence": ev}), "primary", ev)

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
        ind = {p["id"]: p for p in independence(kb)}["X"]
        self.assertEqual(ind["nEff"], 0)                           # visible, but zero grounding
        self.assertEqual(ind["bases"][0]["strength"], 0)

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
        res = resolve(kb)   # rests only on itself -> ungrounded primary naming no data -> pooled voice
        self.assertEqual(_roots(res, "a"), ["primpool:X"])

    def test_ungrounded_primary_pools_named_primary_keeps_its_root(self):
        # THE echo-as-primary fix: a primary that names NO evidence base collapses to one 'unnamed
        # first-hand voice' per position; a primary that NAMES its data keeps a distinct root.
        kb = _kb([_s("anon", "X", "Observational", []),           # names nothing -> pooled
                  _s("named", "X", "Observational", ["D"])])       # names its dataset -> ds:D
        res = resolve(kb)
        self.assertEqual(_roots(res, "anon"), ["primpool:X"])
        self.assertEqual(_roots(res, "named"), ["ds:D"])

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
        # one real study + a flood of ungrounded reviews -> exactly 1 grounded base; unsupported
        # reviews remain one visible zero-strength marker.
        srcs = [_s("study", "X", "Observational", ["D"])]
        srcs += [_s("r%d" % i, "X", "Narrative/Commentary", []) for i in range(50)]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(ind["nEff"], 1.0, places=6)
        self.assertEqual(ind["collapsedSecondary"], 50)

    def test_echo_as_primary_flood_cannot_inflate_independence(self):
        # THE echo-as-primary attack: label a flood of ungrounded rehashes 'Observational' (primary)
        # with empty restsOn, trying to mint one distinct root each. They must all collapse to ONE
        # 'unnamed first-hand' marker -- one grounded study + 50 anonymous claims = 1 grounded base.
        srcs = [_s("study", "X", "Observational", ["D"])]
        srcs += [_s("r%d" % i, "X", "Observational", []) for i in range(50)]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(ind["nEff"], 1.0, places=6)   # NOT 51, and no assertion credit

    def test_named_primaries_each_earn_a_distinct_root(self):
        # the honest counterpart: real studies that each NAME their own evidence base keep full,
        # distinct credit -- three named datasets -> nEff 3 (naming, not the tier claim, buys a root)
        srcs = [_s("a", "X", "Observational", ["Da"]),
                _s("b", "X", "Experimental (RCT)", ["Db"]),
                _s("c", "X", "Cohort study", ["Dc"])]
        self.assertAlmostEqual(self._neff(srcs), 3.0, places=6)

    def test_unrecognized_label_flood_pools_as_secondary(self):
        # a coined evidence label can't mint roots either: ungrounded 'NEW:'-style types -> one voice
        srcs = [_s("q%d" % i, "X", "Cliodynamic survey", []) for i in range(30)]
        self.assertAlmostEqual(self._neff(srcs), 0.0, places=6)

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
        # ungrounded junk aimed at a rival adds no confirmed grounding
        srcs = [_s("p1", "X", "Observational", ["D1"]),
                _s("p2", "X", "Observational", ["D2"]),
                _s("p3", "X", "Observational", ["D3"])]
        base = self._neff(srcs)
        srcs += [_s("r%d" % i, "X", "Evidence-synthesis", []) for i in range(40)]
        self.assertAlmostEqual(self._neff(srcs), base, places=6)
        srcs += [_s("r2_%d" % i, "X", "Evidence-synthesis", []) for i in range(40)]
        self.assertAlmostEqual(self._neff(srcs), base, places=6)

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


class ProvisionalRootTests(unittest.TestCase):
    """Root admission: a dataset asserted only by UNVERIFIED input (textDepth unknown / paste-back)
    is PROVISIONAL and excluded from headline nEff until a real fetch or curator confirms it — so a
    public contributor cannot mint independent support by fabricating datasets."""

    def _neff(self, srcs, pos="X"):
        return {p["id"]: p for p in independence(_kb(srcs))}[pos]["nEff"]

    def test_unconfirmed_fabricated_roots_are_quarantined(self):
        # ten unverified sources each naming a distinct invented dataset -> visible, but zero headline
        srcs = [_s("f%d" % i, "X", "Observational", ["D%d" % i], textDepth="unknown") for i in range(10)]
        ind = {p["id"]: p for p in independence(_kb(srcs))}["X"]
        self.assertAlmostEqual(ind["nEff"], 0.0, places=6)
        self.assertEqual(ind["provisionalCount"], 10)
        self.assertAlmostEqual(ind["provisionalPotential"], 10.0, places=6)

    def test_a_real_fetch_confirms_the_root_to_full_strength(self):
        srcs = [_s("paste", "X", "Observational", ["D"], textDepth="unknown")]
        self.assertAlmostEqual(self._neff(srcs), 0.0, places=6)   # quarantined
        fetched = _s("fetched", "X", "Observational", ["D"], textDepth="full")
        fetched["provenance"] = {"restsOn": _verified("we used cohort D")}
        srcs.append(fetched)
        self.assertAlmostEqual(self._neff(srcs), 1.0, places=6)   # a fetched source confirms D

    def test_fetch_without_verified_dependency_quote_does_not_confirm_root(self):
        src = _s("fetched", "X", "Observational", ["D"], textDepth="full")
        src["provenance"] = {"position": _verified("supports X")}
        self.assertAlmostEqual(self._neff([src]), 0.0, places=6)

    def test_hand_authored_exact_flag_without_current_hash_does_not_confirm_root(self):
        src = _s("fetched", "X", "Observational", [], textDepth="full")
        src["restsOn"] = [{"ref": "D", "provenance": {
            "quote": "We used cohort D.", "verifiedQuote": "exact"}}]
        self.assertAlmostEqual(self._neff([src]), 0.0, places=6)

    def test_legacy_root_confirmation_does_not_admit_arbitrary_support_edge(self):
        kb = _kb([_s("paste", "X", "Observational", ["D"], textDepth="unknown")])
        kb["datasets"] = [{"id": "D", "label": "D", "aliases": [], "confirmed": True}]
        self.assertAlmostEqual({p["id"]: p for p in independence(kb)}["X"]["nEff"], 0.0, places=6)

    def test_confirming_a_root_never_lowers_neff(self):
        # confirmation is an UPGRADE (zero -> full); it can only raise nEff, preserving monotonicity
        base = self._neff([_s("a", "X", "Observational", ["D"], textDepth="unknown")])
        up = self._neff([_s("a", "X", "Observational", ["D"], textDepth="unknown"),
                         _s("b", "X", "Observational", ["D"], textDepth="full")])
        self.assertGreaterEqual(up, base)


class PerEdgeConfirmationTests(unittest.TestCase):
    """Confirmation is auditable PER EDGE: one verified dependency quote admits only the dataset it
    annotates — never a sibling on the same source, never a root reached only by a citation edge.
    This closes the old whitewash where a single source-level verifiedQuote confirmed everything a
    source touched (the ten-datasets-one-quote / inherited-root holes, MECHANISM.md §8)."""

    def _src(self, sid, pos, rests, depth="full", provenance=None):
        s = {"id": sid, "position": pos, "evidence": "Observational", "title": sid,
             "restsOn": rests, "funding": "Undisclosed", "population": "—",
             "confidence": "unstated", "textDepth": depth}
        if provenance is not None:
            s["provenance"] = provenance
        return s

    def test_edge_object_confirms_only_its_own_dataset(self):
        # D1 carries a verified per-edge quote; D2 is a bare sibling edge on the SAME fetched source.
        # Only D1 is admitted; D2 stays provisional — one quote no longer admits ten datasets.
        s = self._src("a", "X",
                      [{"ref": "D1", "provenance": _verified("we analysed cohort D1")},
                       "D2"])
        kb = _kb([s])
        kb["datasets"] = [{"id": "D1", "label": "D1", "aliases": []},
                          {"id": "D2", "label": "D2", "aliases": []}]
        res = resolve(kb)
        self.assertNotIn("ds:D1", res["provisional"])
        self.assertIn("ds:D2", res["provisional"])
        self.assertEqual(res["confirmed_by"]["ds:D1"]["method"], "verified-edge")
        self.assertEqual(res["confirmed_by"]["ds:D1"]["source"], "a")
        ind = {p["id"]: p for p in independence(kb)}["X"]
        self.assertAlmostEqual(ind["nEff"], 1.0, places=6)          # D1 only

    def test_one_real_quote_copied_to_sibling_edges_confirms_only_named_dataset(self):
        # Quote presence is not edge entailment. The fetched sentence really exists, but it names D1;
        # copying it onto D2 must not admit D2 merely because the sentence is verbatim text.
        q = "We analysed the D1 cohort."
        s = self._src("a", "X", [
            {"ref": "D1", "provenance": _verified(q)},
            {"ref": "D2", "provenance": _verified(q)},
        ])
        kb = _kb([s])
        kb["datasets"] = [{"id": "D1", "label": "D1", "aliases": []},
                          {"id": "D2", "label": "D2", "aliases": []}]
        res = resolve(kb)
        self.assertNotIn("ds:D1", res["provisional"])
        self.assertIn("ds:D2", res["provisional"])

    def test_generic_methods_word_cannot_name_a_new_root(self):
        q = "This cohort included 400 adults."
        s = self._src("a", "X", [{"ref": "D", "provenance": _verified(q)}])
        kb = _kb([s])
        kb["datasets"] = [{"id": "D", "label": "Cohort", "aliases": []}]
        self.assertEqual(independence(kb)[0]["nEff"], 0)
        self.assertIn("ds:D", resolve(kb)["provisional"])

    def test_synthesized_two_letter_acronym_cannot_bind_ordinary_prose(self):
        q = "Mr. Smith reported no adverse events."
        s = self._src("a", "X", [{"ref": "D", "provenance": _verified(q)}])
        kb = _kb([s])
        kb["datasets"] = [{"id": "D", "label": "Medical Review", "aliases": []}]
        self.assertEqual(independence(kb)[0]["nEff"], 0)

    def test_unlearned_acronym_split_admits_at_most_one_root(self):
        q = "We analyzed the Nurses Health Study (NHS) cohort."
        s = self._src("a", "X", [
            {"ref": "full", "provenance": _verified(q)},
            {"ref": "short", "provenance": _verified(q)},
        ])
        kb = _kb([s])
        kb["datasets"] = [{"id": "full", "label": "Nurses Health Study", "aliases": []},
                          {"id": "short", "label": "NHS", "aliases": []}]
        res = resolve(kb)
        self.assertEqual(independence(kb, res)[0]["nEff"], 1)
        self.assertEqual(res["alias_suspects"], {"ds:short"})

    def test_legacy_source_level_quote_cannot_confirm_sibling_datasets(self):
        # Back-compat source-level dependency provenance is safe only for ONE direct dataset. With
        # siblings it is ambiguous, so neither root is admitted; new ingestion uses edge objects.
        s = self._src("a", "X", ["D1", "D2"], provenance={
            "restsOn": _verified("one generic dependency sentence")})
        res = resolve(_kb([s]))
        self.assertEqual(res["provisional"], {"ds:D1", "ds:D2"})
        self.assertAlmostEqual({p["id"]: p for p in independence(_kb([s]))}["X"]["nEff"], 0.0)

    def test_legacy_source_level_quote_still_confirms_one_direct_dataset(self):
        s = self._src("a", "X", ["D"], provenance={
            "restsOn": _verified("we used D")})
        res = resolve(_kb([s]))
        self.assertNotIn("ds:D", res["provisional"])
        self.assertEqual(res["confirmed_by"]["ds:D"]["method"], "verified-edge-legacy-single")

    def test_inherited_root_not_confirmed_by_citing_source_quote(self):
        # a review that only CITES the study (src: edge) cannot confirm the study's dataset with its
        # own quote — only a source that DIRECTLY names the dataset can. Study is unknown-depth, so D
        # has no direct verified edge and must stay quarantined.
        study = self._src("study", "X", ["D"], depth="unknown")
        review = self._src("review", "X",
                           [{"ref": "src:study", "provenance": _verified("as the study showed")}],
                           depth="full")
        res = resolve(_kb([study, review]))
        self.assertIn("ds:D", res["provisional"])                   # NOT confirmed via the citation
        ind = {p["id"]: p for p in independence(_kb([study, review]))}["X"]
        self.assertAlmostEqual(ind["nEff"], 0.0, places=6)

    def test_curator_confirmation_object_tied_to_source_admits_root_and_support_edge(self):
        s = self._src("paste", "X", ["D"], depth="unknown")
        kb = _kb([s])
        kb["datasets"] = [{"id": "D", "label": "D", "aliases": [],
                           "confirmation": {"status": "confirmed", "method": "curator", "by": "ann",
                                            "source": "paste", "ts": "2026-07-11T00:00:00Z"}}]
        ind = {p["id"]: p for p in independence(kb)}["X"]
        self.assertAlmostEqual(ind["nEff"], 1.0, places=6)
        self.assertEqual(ind["bases"][0]["confirmedBy"]["method"], "curator")
        self.assertEqual(ind["bases"][0]["confirmedBy"]["by"], "ann")

    def test_confirmed_root_cannot_be_laundered_across_positions_by_unreviewed_edge(self):
        admission = {"status": "confirmed", "method": "curator", "by": "ann",
                     "ts": "2026-07-11T00:00:00Z"}
        legit = self._src("legit", "X", [{"ref": "D", "admission": admission}], depth="unknown")
        attacker = self._src("attacker", "Y", ["D"], depth="unknown")
        kb = _kb([legit, attacker])
        kb["datasets"] = [{"id": "D", "label": "D", "aliases": [],
                           "confirmation": {"status": "confirmed", "method": "curator", "by": "ann",
                                            "ts": "2026-07-11T00:00:00Z"}}]
        ind = {p["id"]: p for p in independence(kb)}
        self.assertEqual(ind["X"]["nEff"], 1.0)
        self.assertEqual(ind["Y"]["nEff"], 0.0)
        self.assertTrue(any(b["supportUnconfirmed"] for b in ind["Y"]["bases"]))

    def test_confirmation_object_with_nonconfirmed_status_does_not_admit(self):
        s = self._src("paste", "X", ["D"], depth="unknown")
        kb = _kb([s])
        kb["datasets"] = [{"id": "D", "label": "D", "aliases": [],
                           "confirmation": {"status": "provisional"}}]
        ind = {p["id"]: p for p in independence(kb)}["X"]
        self.assertAlmostEqual(ind["nEff"], 0.0, places=6)


class MonotonicityPropertyTests(unittest.TestCase):
    """Randomized check of the fixed-graph independence invariant: adding a source through the merge path
    (a new node with only OUTGOING restsOn edges — merge_delta can never create incoming edges
    or cycles) never lowers ANY position's nEff. Resolving pending refs or merging root aliases is a
    graph correction and may intentionally lower nEff; that distinct operation is out of scope here.
    Not just the flooded position's: a new primary
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
                "textDepth": rng.choice(["unknown", "abstract", "partial", "full"]),  # confirm/provisional mix
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
        self.assertIn("confirmed-root coverage", conc[0]["detail"])

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

    def test_unadmitted_primary_assertion_does_not_fill_a_gap(self):
        from engine.gaps import find_gaps
        srcs = [_s("p1", "X", "Observational", ["D1"], textDepth="unknown"),
                _s("p2", "X", "Observational", ["D2"], textDepth="unknown")]
        thin = [g for g in find_gaps(_kb(srcs)) if g["kind"] == "thin-position"]
        self.assertTrue(any(g["positionId"] == "X" and g["severity"] == 3 for g in thin))

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

    def test_argument_kind_root_is_exempt_from_empirical_nonhuman_halving(self):
        # a theoretical argument/model root has no 'population'; the animal / in-vitro discount that
        # would halve an EMPIRICAL dataset must never touch it (schema-v3 evidence-base kinds).
        from engine.roots import resolve, root_strength
        kb = _kb([self._s2("m", "X", "Mechanistic", ["Darg"], "Mice")])
        kb["datasets"] = [{"id": "Darg", "label": "Darg", "aliases": [], "kind": "argument",
                           "confirmation": {"status": "confirmed", "method": "curator", "by": "ann",
                                            "ts": "2026-07-11T00:00:00Z"}}]
        res = resolve(kb)
        self.assertNotIn("ds:Darg", res["nonhuman_only"])
        self.assertEqual(res["base_kind"]["ds:Darg"], "argument")
        self.assertEqual(root_strength("ds:Darg", res["secondary_only"], res["nonhuman_only"],
                                       res["provisional"]), 1.0)

    def test_population_word_does_not_falsematch(self):
        from engine.roots import _is_nonhuman
        self.assertFalse(_is_nonhuman({"population": "moderate-risk adults"}))   # 'rat' in 'moderate'
        self.assertTrue(_is_nonhuman({"population": "Rats"}))
        self.assertTrue(_is_nonhuman({"population": "In vitro / cell"}))


class BudgetAndFundingTests(unittest.TestCase):
    def test_funding_skew_exposes_a_tie_instead_of_using_position_order(self):
        from engine.assess import funding_skew
        srcs = [_s("a", "X", "Observational", []), _s("b", "Y", "Observational", [])]
        for s in srcs:
            s["funding"] = "Industry"
        fs = funding_skew(_kb(srcs))
        self.assertIsNone(fs["top"])
        self.assertTrue(fs["tied"])
        self.assertEqual({x["label"] for x in fs["leaders"]}, {"X", "Y"})

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


class CruxTaxonomyTests(unittest.TestCase):
    """The crux detector surfaces WHAT KIND of decision-relevant factor each one is, instead of a
    single spread>=2 test that missed most hand-picked cruxes. The headline isCrux stays tight so it
    does not balloon to every factor (see the minor-factor test)."""

    def _kbf(self, positions, factors):
        hues = ["#111", "#222", "#333"]
        return {"positions": [{"id": p, "label": p, "hue": hues[i % 3]} for i, p in enumerate(positions)],
                "datasets": [], "factors": factors, "sources": [], "vocab": {"evidence": []}}

    def _f(self, fid, weights):
        return {"id": fid, "label": fid, "weights": weights, "rationale": "", "provenance": []}

    def test_cross_camp_disagreement_is_headline_crux(self):
        from engine.assess import cruxes
        c = cruxes(self._kbf(["A", "B"], [self._f("f", {"A": "high", "B": "low"})]))[0]
        self.assertTrue(c["crossCampCrux"])
        self.assertTrue(c["isCrux"])

    def test_shared_high_is_a_pivot_crux_despite_zero_spread(self):
        # both camps rate it decisive -> a genuine crux the spread test (0) used to miss
        from engine.assess import cruxes
        c = cruxes(self._kbf(["A", "B"], [self._f("f", {"A": "high", "B": "high"})]))[0]
        self.assertEqual(c["spread"], 0)
        self.assertTrue(c["sharedPivot"])
        self.assertTrue(c["isCrux"])

    def test_one_sided_load_bearing_is_flagged_but_not_a_headline_crux(self):
        from engine.assess import cruxes
        c = cruxes(self._kbf(["A", "B"], [self._f("f", {"A": "high"})]))[0]
        self.assertTrue(c["oneSidedLoadBearing"])
        self.assertFalse(c["isCrux"])              # a lone assumption is not a disagreement
        self.assertTrue(c["loadBearing"])

    def test_missing_counterassessment_when_a_camp_is_silent_on_a_decisive_factor(self):
        from engine.assess import cruxes
        c = cruxes(self._kbf(["A", "B", "C"], [self._f("f", {"A": "high", "B": "med"})]))[0]
        self.assertTrue(c["missingCounterassessment"])   # C never weighed a factor A calls decisive
        self.assertTrue(c["loadBearing"])

    def test_minor_factor_both_rate_low_is_not_load_bearing(self):
        # the anti-"everything is a crux" floor: no camp leans on it, no disagreement -> nothing fires
        from engine.assess import cruxes
        c = cruxes(self._kbf(["A", "B"], [self._f("f", {"A": "low", "B": "low"})]))[0]
        self.assertFalse(c["isCrux"])
        self.assertFalse(c["loadBearing"])
        self.assertFalse(c["oneSidedLoadBearing"])


class SemanticSuggestTests(unittest.TestCase):
    """Embedding-assisted entity-resolution SUGGESTIONS (engine/curate.suggest_duplicates): surface
    paraphrases lexical overlap misses, tagged 'embedding' — but NEVER auto-merge (item 10)."""

    def _kb_ds(self, labels):
        return {"positions": [], "datasets": [{"id": "d%d" % i, "label": l, "aliases": []}
                                              for i, l in enumerate(labels)],
                "factors": [], "sources": [], "vocab": {"population": [], "evidence": []}}

    def test_embedding_surfaces_a_paraphrase_lexical_overlap_misses(self):
        from engine.curate import suggest_duplicates
        kb = self._kb_ds(["Huanan market environmental swabs", "Wuhan seafood-market samples"])
        self.assertEqual(suggest_duplicates(kb), {})                 # lexical: no overlap, no suggestion
        vecs = {"Huanan market environmental swabs": [1.0, 0.02],
                "Wuhan seafood-market samples": [0.98, 0.05]}        # near-identical embeddings
        sug = suggest_duplicates(kb, embed=lambda l: vecs.get(l, [0.0, 1.0]))
        self.assertEqual(sug["dataset"][0]["reason"], "embedding")

    def test_suggestion_never_mutates_the_kb(self):
        from engine.curate import suggest_duplicates
        kb = self._kb_ds(["Foo", "Bar"])
        sug = suggest_duplicates(kb, embed=lambda l: [1.0, 0.0])     # identical vectors -> cosine 1.0
        self.assertTrue(sug)                                          # surfaced as a candidate
        self.assertEqual(len(kb["datasets"]), 2)                      # but nothing merged

    def test_embed_none_is_identical_to_lexical_only(self):
        from engine.curate import suggest_duplicates
        kb = self._kb_ds(["Nurses Health Study", "Nurses Health Study cohort women"])
        self.assertEqual(suggest_duplicates(kb), suggest_duplicates(kb, embed=None))
