"""Tests for the deterministic position-merge guard (engine/merge._resolve_position /
_position_dup) and the discovery non-scholarly filter (ingest/pipeline.is_nonscholarly).

The guard must collapse condition/qualifier variants of ONE stance into a single camp, while
NEVER merging two genuinely opposite stances — even when their labels differ by a single word."""
import unittest

from engine.merge import merge_delta, _position_dup
from engine.schema import empty_kb
from ingest.pipeline import is_nonscholarly


def _delta(title, position):
    slug = title.replace(" ", "-")
    return {"source": {"title": title, "year": 2020, "url": "https://ex.org/" + slug,
                       "position": position, "evidence": "Observational", "restsOn": []}}


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
                "factorWeights": [{"factor": "A crux", "weight": w, "quote": "q", "rationale": "r"}]}

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


class TwoPassRefTests(unittest.TestCase):
    """A NEW-SRC forward reference (citing a source not yet merged) used to be dropped, so a mutual
    A<->B citation ring could never form through ordinary ingestion. resolve_pending_refs closes it."""

    def test_forward_ref_resolves_and_the_cycle_is_flagged(self):
        from engine.merge import resolve_pending_refs
        from engine.roots import resolve
        from engine.assess import independence
        kb = empty_kb("t", "q")
        merge_delta(kb, {"source": {"title": "Paper A", "year": 2020, "url": "https://x/a",
            "position": "NEW:P", "evidence": "Narrative/Commentary", "restsOn": ["NEW-SRC:Paper B"]}})
        merge_delta(kb, {"source": {"title": "Paper B", "year": 2021, "url": "https://x/b",
            "position": "NEW:P", "evidence": "Narrative/Commentary", "restsOn": ["NEW-SRC:Paper A"]}})
        a = next(s for s in kb["sources"] if s["title"] == "Paper A")
        self.assertEqual(a["restsOn"], [])                      # forward ref unresolved at merge time
        self.assertEqual(independence(kb)[0]["nEff"], 1)        # unresolved graph: one secondary voice
        self.assertGreaterEqual(resolve_pending_refs(kb), 1)    # second pass wires A->B
        a = next(s for s in kb["sources"] if s["title"] == "Paper A")
        self.assertTrue(any(str(e).startswith("src:") for e in a["restsOn"]))
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


class SourceRemovalTests(unittest.TestCase):
    def _kb(self):
        kb = empty_kb("t", "q")
        first = {"source": {"title": "Irrelevant paper", "year": 2020,
                 "url": "https://x/irrelevant", "position": "NEW:Yes",
                 "evidence": "Observational", "funding": "Undisclosed", "population": "—",
                 "restsOn": ["NEW:Only dataset"]},
                 "factorWeights": [{"factor": "Crux", "weight": "low", "quote": "q"}]}
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
        third = next(s for s in kb["sources"] if s["id"] == "third")
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
        kb["sources"] = [old, new]
        kb["datasets"] = [{"id": "d", "label": "D", "aliases": [], "confirmation": {
            "status": "confirmed", "method": "curator", "by": "ann",
            "ts": "2026-07-11T00:00:00Z", "source": "old"}}]
        dedupe_sources(kb)
        self.assertEqual(kb["datasets"][0]["confirmation"]["source"], "new")
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
