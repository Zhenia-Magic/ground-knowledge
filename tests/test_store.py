import os
import tempfile
import unittest
from unittest import mock

from app import store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (store.DATABASE_URL, store._IS_PG, store._SQLITE_PATH, store._KB_COL)
        store.DATABASE_URL = None
        store._IS_PG = False
        store._SQLITE_PATH = os.path.join(self.tmp.name, "app.db")
        store._KB_COL = "TEXT"
        store.init_db()

    def tearDown(self):
        store.DATABASE_URL, store._IS_PG, store._SQLITE_PATH, store._KB_COL = self.old
        self.tmp.cleanup()


class StoreRevisionTests(StoreTestCase):

    def test_every_write_advances_server_revision_and_rejects_stale_writer(self):
        question = store.create_question("Does it work?")
        kb = question["kb"]
        first = store.save_kb(question["id"], kb, 0,
                              {"contributor": "a", "action": "queue", "summary": "one"})
        self.assertEqual(first, 1)
        with self.assertRaises(store.Conflict):
            store.save_kb(question["id"], kb, 0)
        self.assertEqual(len(store.contributions(question["id"])), 2)  # create + atomic update audit

    def test_question_cards_do_not_parse_full_kb_documents(self):
        question = store.create_question("A question")
        with mock.patch("app.store._load", side_effect=AssertionError("KB parsed")):
            cards = store.list_questions()
        self.assertEqual(cards[0]["id"], question["id"])
        self.assertEqual(cards[0]["counts"]["sources"], 0)

    def test_curated_flag_round_trips_from_meta_to_the_card(self):
        from engine import curate
        question = store.create_question("A curated question")
        qid, kb = question["id"], question["kb"]
        # a brand-new question is not curated
        self.assertFalse(store.list_questions()[0]["curated"])
        # marking it (on the KB meta) and saving must surface on the card WITHOUT parsing the KB
        curate.set_curated(kb, by="admin")
        v = store.save_kb(qid, kb, 0)
        with mock.patch("app.store._load", side_effect=AssertionError("KB parsed")):
            card = store.list_questions()[0]
        self.assertTrue(card["curated"])
        # un-marking clears the card flag
        curate.set_curated(kb, curated=False)
        store.save_kb(qid, kb, v)
        self.assertFalse(store.list_questions()[0]["curated"])

    def test_failed_audit_rolls_back_the_kb_write(self):
        question = store.create_question("Atomic update?")
        with mock.patch("app.store._insert_contribution", side_effect=RuntimeError("audit failed")), \
             self.assertRaises(RuntimeError):
            store.save_kb(question["id"], question["kb"], 0,
                          {"action": "update", "summary": "must be atomic"})
        self.assertEqual(store.get_question(question["id"])["version"], 0)


class StudyAssignmentStoreTests(StoreTestCase):
    def test_assignment_is_single_use(self):
        assignment = store.new_study_assignment()
        store.save_study_response(assignment["id"], "p", {"cases": []}, [])
        with self.assertRaises(store.Conflict):
            store.save_study_response(assignment["id"], "p", {"cases": []}, [])


if __name__ == "__main__":
    unittest.main()
