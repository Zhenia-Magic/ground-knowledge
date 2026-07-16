"""Tests for the deterministic position-merge guard (engine/merge._resolve_position /
_position_dup) and the discovery non-scholarly filter (ingest/pipeline.is_nonscholarly).

The guard must collapse condition/qualifier variants of ONE stance into a single camp, while
NEVER merging two genuinely opposite stances — even when their labels differ by a single word."""
import unittest

from engine.merge import merge_delta, _position_dup
from engine.schema import empty_kb
from engine.verify import apply_quote_verification
from ingest.pipeline import is_nonscholarly


def _delta(title, position):
    slug = title.replace(" ", "-")
    return {"source": {"title": title, "year": 2020, "url": "https://ex.org/" + slug,
                       "position": position, "evidence": "Observational", "restsOn": []}}


def _verified_factor(label, weight):
    quote = "This complete source sentence directly supports the factor claim."
    claim = {"factor": label, "weight": weight, "quote": quote, "rationale": "r"}
    apply_quote_verification(claim, quote, source_title="Different article title",
                             text_depth="full", source_url="https://ex.org/source")
    return claim


class PositionGuardTests(unittest.TestCase):
    def setUp(self):
        self.kb = empty_kb("t", "Does violent video game exposure increase aggression?")

    def _positions(self):
        return [p["label"] for p in self.kb["positions"]]

    def test_parenthetical_qualifier_folds_into_base(self):
        merge_delta(self.kb, _delta("A", "NEW:No clear effect"))
        merge_delta(self.kb, _delta("B", "NEW:No clear effect (after bias adjustment)"))
        self.assertEqual(len(self.kb["positions"]), 1)
        self.assertEqual(self._positions(), ["No clear effect"])

    def test_condition_variant_without_parens_folds_in(self):
        merge_delta(self.kb, _delta("A", "NEW:No clear effect"))
        merge_delta(self.kb, _delta("B", "NEW:No clear effect after bias adjustment"))
        self.assertEqual(len(self.kb["positions"]), 1)

    def test_opposite_stances_are_never_merged(self):
        merge_delta(self.kb, _delta("A", "NEW:Increases aggression"))
        merge_delta(self.kb, _delta("B", "NEW:Decreases aggression"))
        self.assertEqual(len(self.kb["positions"]), 2)

    def test_long_opposite_stances_differing_by_one_word_not_merged(self):
        # the Jaccard trap: these overlap ~0.67 by tokens but are opposite camps
        merge_delta(self.kb, _delta("A", "NEW:Moderate alcohol increases cardiovascular risk"))
        merge_delta(self.kb, _delta("B", "NEW:Moderate alcohol decreases cardiovascular risk"))
        self.assertEqual(len(self.kb["positions"]), 2)

    def test_negated_superset_is_not_folded_into_positive_stance(self):
        # Token-subset alone used to merge these because every positive label token appears in the
        # negated label. The polarity guard must keep the camps distinct.
        merge_delta(self.kb, _delta("A", "NEW:Increase cardiovascular risk"))
        merge_delta(self.kb, _delta("B", "NEW:No evidence of increase cardiovascular risk"))
        self.assertEqual(len(self.kb["positions"]), 2)

    def test_distinct_stances_stay_distinct(self):
        for i, lab in enumerate(("NEW:Increases aggression", "NEW:No clear effect",
                                 "NEW:Decreases aggression")):
            merge_delta(self.kb, _delta("paper %d" % i, lab))
        self.assertEqual(len(self.kb["positions"]), 3)

    def test_single_token_labels_not_over_merged(self):
        # 'safe' ⊆ 'safe in adults' but the >=2-token floor keeps a 1-token label from swallowing
        merge_delta(self.kb, _delta("A", "NEW:Safe"))
        merge_delta(self.kb, _delta("B", "NEW:Harmful"))
        self.assertEqual(len(self.kb["positions"]), 2)

    def test_exact_id_reference_still_resolves(self):
        merge_delta(self.kb, _delta("A", "NEW:Increases aggression"))
        pid = self.kb["positions"][0]["id"]
        merge_delta(self.kb, _delta("B", pid))
        self.assertEqual(len(self.kb["positions"]), 1)

    def test_position_dup_helper_direct(self):
        merge_delta(self.kb, _delta("A", "NEW:No clear effect"))
        self.assertIsNotNone(_position_dup(self.kb, "No clear effect (after adjustment)"))
        self.assertIsNone(_position_dup(self.kb, "Increases aggression"))


class FactorWeightDerivationTests(unittest.TestCase):
    """Factor cells are derived from the MODE of source claims, not last-writer-wins."""

    def _fw(self, title, w):
        return {"source": {"title": title, "year": 2020, "url": "https://x/" + title,
                           "position": "NEW:P", "evidence": "Observational", "restsOn": []},
                "factorWeights": [_verified_factor("A crux", w)]}

    def test_cell_is_mode_not_last_writer(self):
        kb = empty_kb("t", "q")
        for t, w in [("a", "high"), ("b", "high"), ("c", "low")]:
            merge_delta(kb, self._fw(t, w))
        f, pos = kb["factors"][0], kb["positions"][0]["id"]
        self.assertEqual(f["weights"][pos], "high")        # mode(high,high,low), NOT last-writer 'low'

    def test_dropping_a_source_re_derives_the_cell(self):
        from engine.merge import recompute_factor_weights
        kb = empty_kb("t", "q")
        for t, w in [("a", "low"), ("b", "low"), ("c", "high")]:
            merge_delta(kb, self._fw(t, w))
        f, pos = kb["factors"][0], kb["positions"][0]["id"]
        self.assertEqual(f["weights"][pos], "low")
        # remove the two 'low' sources -> only 'high' remains -> cell re-derives to 'high'
        keep = f["provenance"][-1]["source"]
        f["provenance"] = [pr for pr in f["provenance"] if pr["source"] == keep]
        recompute_factor_weights(kb)
        self.assertEqual(f["weights"][pos], "high")

    def test_unverified_factor_claim_is_auditable_but_cannot_create_a_cell(self):
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "a", "year": 2020, "url": "https://x/a",
                     "position": "NEW:P", "evidence": "Observational", "restsOn": []},
                     "factorWeights": [{"factor": "A crux", "weight": "high",
                                        "quote": "model-authored wording"}]})
        factor = kb["factors"][0]
        self.assertEqual(factor["weights"], {})
        self.assertEqual(factor["provenance"][0]["quote"], "model-authored wording")


class TwoPassRefTests(unittest.TestCase):
    """A NEW-SRC forward reference (citing a source not yet merged) used to be dropped, so a mutual
    A<->B citation ring could never form through ordinary ingestion. resolve_pending_refs closes it."""

    def test_forward_ref_resolves_and_the_cycle_is_flagged(self):
        from engine.merge import resolve_pending_refs
        from engine.roots import resolve
        from engine.assess import independence
        from engine.curate import confirm_edge
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Paper A", "year": 2020, "url": "https://x/a",
            "position": "NEW:P", "evidence": "Narrative/Commentary",
            "restsOn": [{"ref": "NEW-SRC:Paper B"}]}})
        merge_delta(kb, {"source": {"title": "Paper B", "year": 2021, "url": "https://x/b",
            "position": "NEW:P", "evidence": "Narrative/Commentary",
            "restsOn": [{"ref": "NEW-SRC:Paper A"}]}})
        a = next(s for s in kb["sources"] if s["title"] == "Paper A")
        self.assertEqual(a["restsOn"], [])                      # forward ref unresolved at merge time
        self.assertEqual(independence(kb)[0]["nEff"], 0)        # unsupported assertions have zero
        self.assertGreaterEqual(resolve_pending_refs(kb), 1)    # second pass wires A->B
        confirm_edge(kb, "Paper A", "src:" + next(s["id"] for s in kb["sources"]
                                                   if s["title"] == "Paper B"), by="ann")
        confirm_edge(kb, "Paper B", "src:" + next(s["id"] for s in kb["sources"]
                                                   if s["title"] == "Paper A"), by="ann")
        a = next(s for s in kb["sources"] if s["title"] == "Paper A")
        self.assertTrue(any((e.get("ref") if isinstance(e, dict) else e).startswith("src:")
                            for e in a["restsOn"]))
        self.assertEqual(len(resolve(kb)["circular"]), 1)       # the A<->B ring is now flagged
        self.assertEqual(independence(kb)[0]["nEff"], 0)        # correction removes false grounding


class DuplicateSuggestionTests(unittest.TestCase):
    def test_acronym_and_full_dataset_name_are_suggested(self):
        from engine.curate import suggest_duplicates
        kb = empty_kb("t", "q")
        kb["datasets"] = [
            {"id": "nhs", "label": "NHS", "aliases": []},
            {"id": "nurses", "label": "Nurses Health Study", "aliases": []},
        ]
        pairs = suggest_duplicates(kb).get("dataset", [])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["reason"], "acronym")

    def test_large_generic_inventory_uses_blocked_candidates_not_all_pairs(self):
        from engine import curate
        from unittest import mock
        kb = empty_kb("t", "q")
        kb["datasets"] = [{"id": "d{}".format(i),
                           "label": "Registry Common Unique{}".format(i), "aliases": []}
                          for i in range(1500)]
        with mock.patch("engine.curate._similarity", wraps=curate._similarity) as similarity:
            curate.suggest_duplicates(kb)
        self.assertLess(similarity.call_count, 20)


class DatasetEdgeObjectCurationTests(unittest.TestCase):
    def test_merge_datasets_repoints_and_dedupes_object_edges_without_losing_quote(self):
        from engine.curate import merge_datasets
        from engine.migrate import validation_errors
        from ui.server import _counts
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Paper", "position": "NEW:Yes",
            "evidence": "Observational", "funding": "Undisclosed", "population": "—",
            "restsOn": [
                {"ref": "NEW:NHS", "provenance": {"quote": "NHS quote"}},
                {"ref": "NEW:Nurses Health Study", "provenance": {"quote": "full quote"}},
            ]}})
        merge_datasets(kb, "NHS", "Nurses Health Study")
        edges = kb["sources"][0]["restsOn"]
        self.assertEqual(len(edges), 1)
        self.assertIsInstance(edges[0], dict)
        self.assertEqual(edges[0]["provenance"]["quote"], "NHS quote")
        self.assertEqual(validation_errors(kb), [])
        self.assertEqual(sum(_counts(kb)[1].values()), 1)          # object edge is countable, not unhashable

    def test_confirmation_blocks_likely_alias_without_explicit_explanation(self):
        from engine.curate import confirm_dataset
        kb = empty_kb("t", "q")
        kb["datasets"] = [
            {"id": "nhs", "label": "NHS", "aliases": []},
            {"id": "nurses", "label": "Nurses Health Study", "aliases": []},
        ]
        with self.assertRaises(ValueError):
            confirm_dataset(kb, "nhs", by="ann")
        with self.assertRaises(ValueError):
            confirm_dataset(kb, "nhs", by="ann", allow_similar=True)
        confirm_dataset(kb, "nhs", by="ann", allow_similar=True,
                        note="Distinct registry sharing an acronym; manually checked")
        rec = kb["datasets"][0]["confirmation"]
        self.assertEqual(rec["by"], "ann")
        self.assertTrue(rec["ts"])
        self.assertTrue(rec["similarityOverride"])

    def test_confirm_edge_is_auditable_and_controls_support_credit(self):
        from engine.curate import confirm_dataset, confirm_edge
        from engine.assess import independence
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Paper", "position": "NEW:Yes",
            "evidence": "Observational", "funding": "Undisclosed", "population": "—",
            "restsOn": ["NEW:Registry"], "textDepth": "unknown"}})
        sid, did = kb["sources"][0]["id"], kb["datasets"][0]["id"]
        confirm_dataset(kb, did, by="ann")
        self.assertEqual(independence(kb)[0]["nEff"], 0)
        confirm_edge(kb, sid, did, by="ann", note="methods section names the registry")
        self.assertEqual(independence(kb)[0]["nEff"], 1)
        rec = kb["sources"][0]["restsOn"][0]["admission"]
        self.assertEqual(rec["method"], "curator")
        self.assertEqual(rec["by"], "ann")
        confirm_edge(kb, sid, did, confirmed=False, by="ann")
        self.assertEqual(independence(kb)[0]["nEff"], 0)


class SourceRemovalTests(unittest.TestCase):
    def _kb(self):
        kb = empty_kb("t", "q")
        first = {"source": {"title": "Irrelevant paper", "year": 2020,
                 "url": "https://x/irrelevant", "position": "NEW:Yes",
                 "evidence": "Observational", "funding": "Undisclosed", "population": "—",
                 "restsOn": ["NEW:Only dataset"]},
                 "factorWeights": [_verified_factor("Crux", "low")]}
        merge_delta(kb, first)
        sid = kb["sources"][0]["id"]
        merge_delta(kb, {"source": {"title": "Commentary", "year": 2021,
                    "url": "https://x/commentary", "position": kb["positions"][0]["id"],
                    "evidence": "Narrative/Commentary", "funding": "Undisclosed",
                    "population": "—", "restsOn": ["src:" + sid]}})
        return kb, sid

    def test_remove_requires_editorial_audit_fields(self):
        from engine.curate import remove_source
        kb, sid = self._kb()
        with self.assertRaises(ValueError):
            remove_source(kb, sid, "", "curator")
        with self.assertRaises(ValueError):
            remove_source(kb, sid, "wrong outcome", "")

    def test_remove_repairs_edges_factors_and_orphan_dataset(self):
        from engine.curate import remove_source
        from engine.migrate import validation_errors
        kb, sid = self._kb()
        report = remove_source(kb, sid, "measures another outcome", "source-audit-2026-07")
        self.assertEqual(len(kb["sources"]), 1)
        self.assertEqual(kb["sources"][0]["restsOn"], [])
        self.assertEqual(kb["datasets"], [])
        self.assertEqual(kb["factors"][0]["weights"], {})
        self.assertEqual(kb["factors"][0]["provenance"], [])
        self.assertEqual(report["prunedDatasets"], ["ds_only_dataset"])
        self.assertEqual(kb["log"][-1]["reason"], "measures another outcome")
        self.assertEqual(validation_errors(kb), [])

    def test_duplicate_removal_repoints_source_edges(self):
        from engine.curate import remove_source
        kb, sid = self._kb()
        retained = kb["sources"][1]["id"]
        # Make a third paper cite the duplicate so replacement has an observable edge.
        kb["sources"].append(dict(kb["sources"][1], id="third", title="Third",
                                  url="https://x/third", restsOn=["src:" + sid]))
        remove_source(kb, sid, "duplicate record", "source-audit-2026-07", retained)
        kept = next(s for s in kb["sources"] if s["id"] == retained)
        third = next(s for s in kb["sources"] if s["id"] == "third")
        self.assertEqual(kept["restsOn"], [])
        self.assertEqual(third["restsOn"], ["src:" + retained])

    def test_move_source_updates_factor_claim_and_logs_reason(self):
        from engine.curate import move_source
        kb, sid = self._kb()
        kb["positions"].append({"id": "p2", "label": "Mixed", "hue": "#123"})
        report = move_source(kb, sid, "Mixed", "finding is bidirectional", "source-audit-2026-07")
        self.assertEqual(kb["sources"][0]["position"], "p2")
        self.assertEqual(kb["factors"][0]["provenance"][0]["pos"], "p2")
        self.assertEqual(kb["factors"][0]["weights"], {"p2": "low"})
        self.assertEqual(report["to"], "p2")
        self.assertEqual(kb["log"][-1]["reason"], "finding is bidirectional")

    def test_merge_preserves_named_funding_details(self):
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Funded study", "year": 2024,
                    "url": "https://x/funded", "position": "NEW:Yes",
                    "evidence": "Observational", "funding": "Government/public",
                    "fundingDetails": ["National Science Foundation grant 123"],
                    "population": "Adults", "restsOn": []}})
        self.assertEqual(kb["sources"][0]["fundingDetails"],
                         ["National Science Foundation grant 123"])

    def test_merge_dataset_preserves_confirmed_root_and_audit_record(self):
        from engine.curate import merge_datasets
        from engine.assess import independence
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Paper", "position": "NEW:Yes",
            "evidence": "Observational", "funding": "Undisclosed", "population": "—",
            "restsOn": ["NEW:Confirmed cohort"]}})
        src_id = kb["datasets"][0]["id"]
        kb["datasets"][0]["confirmation"] = {
            "status": "confirmed", "method": "curator", "by": "ann",
            "ts": "2026-07-11T00:00:00Z", "source": kb["sources"][0]["id"]}
        kb["datasets"].append({"id": "target", "label": "Target cohort", "aliases": [],
                               "confirmation": {"status": "provisional"}})
        self.assertEqual(independence(kb)[0]["nEff"], 1)
        merge_datasets(kb, src_id, "target")
        self.assertEqual(independence(kb)[0]["nEff"], 1)
        rec = next(d for d in kb["datasets"] if d["id"] == "target")["confirmation"]
        self.assertEqual(rec["by"], "ann")
        self.assertEqual(rec["mergedFrom"][0]["dataset"], src_id)

    def test_source_dedupe_repoints_confirmation_support(self):
        from engine.curate import dedupe_sources
        from engine.migrate import validation_errors
        kb = empty_kb("t", "q")
        kb["positions"] = [{"id": "p", "label": "P", "hue": "#000"}]
        base = {"position": "p", "evidence": "Observational", "funding": "Undisclosed",
                "population": "—", "restsOn": [], "textDepth": "unknown"}
        old = dict(base, id="old", title="Same paper", year=2020,
                   url="https://doi.org/10.1234/same", provenance={})
        new = dict(base, id="new", title="Same paper", year=2020,
                   url="https://publisher.example/10.1234/same",
                   provenance={"position": {"quote": "q"}})
        referrer = dict(base, id="ref", title="A later commentary", year=2021,
                        url="https://example.org/ref", provenance={}, restsOn=["src:old"])
        kb["sources"] = [old, new, referrer]
        kb["datasets"] = [{"id": "d", "label": "D", "aliases": [], "confirmation": {
            "status": "confirmed", "method": "curator", "by": "ann",
            "ts": "2026-07-11T00:00:00Z", "source": "old"}}]
        kb["factors"] = [{"id": "f", "label": "Factor", "weights": {"p": "low"},
                           "rationale": "", "provenance": [
                               {"source": "old", "pos": "p", "quote": "short"},
                               {"source": "new", "pos": "p", "quote": "a richer claim"}]}]
        dedupe_sources(kb)
        self.assertEqual(kb["datasets"][0]["confirmation"]["source"], "new")
        self.assertEqual(next(s for s in kb["sources"] if s["id"] == "ref")["restsOn"],
                         ["src:new"])
        self.assertEqual(kb["factors"][0]["provenance"][0]["source"], "new")
        self.assertEqual(len(kb["factors"][0]["provenance"]), 1)
        self.assertEqual(validation_errors(kb), [])


class OffTopicRefusalTests(unittest.TestCase):
    def setUp(self):
        self.kb = empty_kb("t", "Does violent video game exposure increase aggression?")

    def _off(self, title, reason="about a different topic"):
        d = _delta(title, "NEW:Increases aggression")
        d["source"]["relevant"] = False
        d["source"]["offTopicReason"] = reason
        return d

    def test_off_topic_is_refused_recorded_and_uncounted(self):
        rep = merge_delta(self.kb, self._off("A rice genome map"))
        self.assertTrue(rep["offTopic"])
        self.assertEqual(len(self.kb["sources"]), 0)          # never enters the metrics
        self.assertEqual(len(self.kb.get("refused", [])), 1)  # but IS recorded, not silently gone
        self.assertEqual(self.kb["refused"][0]["reason"], "about a different topic")
        self.assertTrue(any(e.get("action") == "refused-offtopic" for e in self.kb.get("log", [])))

    def test_same_refusal_is_not_double_logged(self):
        self.kb = empty_kb("t", "q")
        d = self._off("Duplicate off-topic paper")
        merge_delta(self.kb, dict(source=dict(d["source"])))
        merge_delta(self.kb, dict(source=dict(d["source"])))
        self.assertEqual(len(self.kb["refused"]), 1)          # re-runs don't re-log the same refusal


class NonScholarlyFilterTests(unittest.TestCase):
    def test_drops_encyclopedias_news_press_social_courts(self):
        for u in ("https://en.wikipedia.org/wiki/X", "https://www.scotusblog.com/cases/x",
                  "https://www.ox.ac.uk/news/2019-02-13-x", "https://site.org/press-release/x",
                  "https://uni.edu/newsroom/x", "https://blog.site.com/blog/x",
                  "https://reddit.com/r/x", "https://medium.com/@a/x"):
            self.assertTrue(is_nonscholarly(u), u)

    def test_keeps_scholarly_links(self):
        for u in ("https://doi.org/10.1073/pnas.1611617114",
                  "https://pmc.ncbi.nlm.nih.gov/articles/PMC6176643/",
                  "https://arxiv.org/abs/2401.12345",
                  "https://www.nature.com/articles/s41562-018-0332-5",
                  "https://pubmed.ncbi.nlm.nih.gov/28448257/"):
            self.assertFalse(is_nonscholarly(u), u)

    def test_empty_url_is_not_flagged(self):
        self.assertFalse(is_nonscholarly(""))
        self.assertFalse(is_nonscholarly(None))


if __name__ == "__main__":
    unittest.main()


class PrettifyLabelTests(unittest.TestCase):
    def test_capitalizes_and_splits_ugly_labels(self):
        from engine.merge import prettify_label as p
        self.assertEqual(p("researcher-expectancy effects"), "Researcher-expectancy effects")
        self.assertEqual(p("AngryBirdsMeta Ferguson2015"), "Angry Birds Meta Ferguson 2015")
        self.assertEqual(p("Przybylski2019 adolescent dataset"), "Przybylski 2019 adolescent dataset")

    def test_leaves_proper_nouns_and_acronyms_alone(self):
        from engine.merge import prettify_label as p
        self.assertEqual(p("McGill cohort"), "McGill cohort")
        self.assertEqual(p("UK Biobank"), "UK Biobank")
        self.assertEqual(p("SARS-CoV-2 wastewater data"), "SARS-CoV-2 wastewater data")


class EvidenceBaseKindTests(unittest.TestCase):
    """kind (dataset|document|argument|model) is set by the labeller (datasetKind on a restsOn edge)
    or a curator (curate.set_kind); it is never inferred. 'dataset' is the empirical default and is
    stored implicitly. See scripts/source_inventory.kind_mismatches for the drift guard."""

    def test_labeller_datasetKind_creates_a_typed_root(self):
        kb = empty_kb("k", "Q?")
        merge_delta(kb, {"source": {"title": "Analysis", "year": 2023, "url": "https://ex.org/a",
            "position": "NEW:Yes", "evidence": "Narrative/Commentary",
            "restsOn": [{"ref": "NEW:The DEFUSE proposal", "datasetKind": "document",
                         "provenance": {"quote": "x"}}]}})
        doc = next(d for d in kb["datasets"] if "DEFUSE" in d["label"])
        self.assertEqual(doc.get("kind"), "document")

    def test_empirical_base_stays_implicit_and_invalid_kind_is_rejected(self):
        kb = empty_kb("k", "Q?")
        merge_delta(kb, {"source": {"title": "Cohort", "year": 2023, "url": "https://ex.org/c",
            "position": "NEW:Yes", "evidence": "Observational",
            "restsOn": [{"ref": "NEW:Framingham cohort", "provenance": {"quote": "y"}}]}})
        with self.assertRaises(ValueError):
            merge_delta(kb, {"source": {"title": "Weird", "year": 2023, "url": "https://ex.org/w",
                "position": "NEW:Yes", "evidence": "Observational",
                "restsOn": [{"ref": "NEW:Weird base", "datasetKind": "nonsense",
                             "provenance": {"quote": "z"}}]}})
        d = next(x for x in kb["datasets"] if "ramingham" in x["label"])
        self.assertNotIn("kind", d)
        self.assertFalse(any("Weird" in x["label"] for x in kb["datasets"]))

    def test_curate_set_kind_sets_resets_and_rejects(self):
        from engine import curate
        kb = empty_kb("k", "Q?")
        kb["datasets"].append({"id": "ds_x", "label": "X proposal", "aliases": []})
        curate.set_kind(kb, "ds_x", "document")
        self.assertEqual(kb["datasets"][0]["kind"], "document")
        curate.set_kind(kb, "ds_x", "dataset")          # default -> stored implicitly (key removed)
        self.assertNotIn("kind", kb["datasets"][0])
        with self.assertRaises(ValueError):
            curate.set_kind(kb, "ds_x", "bogus")

    def test_audit_flags_a_document_labelled_dataset_and_is_clean_on_shipped_cases(self):
        from scripts import source_inventory as si
        self.assertTrue(si._DOC_SIGNAL.search("DEFUSE grant proposal document (2018)"))
        self.assertFalse(si._DOC_SIGNAL.search("Nurses' Health Study cohort"))
        # every shipped case must have its document/argument roots typed correctly (no mismatch)
        self.assertEqual(si.kind_mismatches(), [])


class IngestBatchResilienceTests(unittest.TestCase):
    """A harvest fetches + labels many sources; one bad fetch or one malformed LLM response must
    skip THAT source, never abort the whole batch (which would discard everything already done and
    waste the discovery spend). See ingest/pipeline.ingest_batch."""

    def test_a_dropped_connection_skips_that_source_not_the_batch(self):
        import http.client
        from ingest import pipeline as P
        good = {"url": "good", "kind": "abstract", "text": "s", "title": "Good", "abstract": "s"}
        def fake_extract(t):
            if t == "bad":
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            return good
        oe = P.extract_text
        P.extract_text = fake_extract
        try:
            prompts = P.ingest_batch(["bad", "good"], empty_kb("k", "Q?"), dry_run=True, batch=1)
        finally:
            P.extract_text = oe
        self.assertEqual(len(prompts), 1)   # the bad fetch is skipped; the good one still produces work

    def test_a_malformed_label_response_is_retried_once_then_skipped(self):
        from ingest import pipeline as P
        calls = {"n": 0}
        def fake_extract(t):
            return {"url": t, "kind": "abstract", "text": "s", "title": t, "abstract": "s"}
        def fake_label(kb, group, max_text):
            calls["n"] += 1
            raise SystemExit("Could not parse model JSON")
        oe, ol = P.extract_text, P.label_batch
        P.extract_text, P.label_batch = fake_extract, fake_label
        try:
            out = P.ingest_batch(["a"], empty_kb("k", "Q?"), batch=1)
        finally:
            P.extract_text, P.label_batch = oe, ol
        self.assertEqual(out, [])            # group skipped, harvest survives
        self.assertEqual(calls["n"], 2)      # tried once, retried once
