import copy
import unittest
from scripts.focused_voice_session import build_session, session_text


def card(i, ratings=(2, 3), word=None):
    return {
        "card_id": i, "note_id": i + 100, "study_state": "currently_active",
        "note": {"fields": {k: {"text": v} for k, v in {
            "Word": word or f"word{i}", "Word Reading": f"reading{i}",
            "Word Meaning": "meaning", "Sentence": "exact example", "Sentence Meaning": "translation",
        }.items()}},
        "scheduling": {"lapses": 0, "interval_days": 1, "due_interpreted": {"days_from_today": -100}},
        "review_history": [{"review_id": 10000 + n * 100 + i, "reviewed_at": f"2026-10-{n+1:02}T00:00:00Z",
                            "rating": {"raw": v, "name": {1:"again",2:"hard",3:"good",4:"easy"}[v]},
                            "review_type": {"raw": 1}} for n, v in enumerate(ratings)]}


class FocusedSessionTests(unittest.TestCase):
    def build(self, cards, **kw):
        return build_session(cards, "generation", "2026-10-31T00:00:00Z", **kw)

    def test_default_three_explicit_max_five(self):
        cards = [card(i) for i in range(8)]
        self.assertEqual(len(self.build(cards)["targets"]), 3)
        self.assertEqual(len(self.build(cards, limit=5)["targets"]), 5)
        for size in (0, 2, 6, True):
            with self.assertRaises(ValueError): self.build(cards, limit=size)

    def test_normalized_duplicates_count_once(self):
        cards = [card(i) for i in range(6)]
        cards[1]["note"]["fields"]["Word"]["text"] = "ｗｏｒｄ0"
        cards[1]["note"]["fields"]["Word Reading"]["text"] = "reading0"
        pack = self.build(cards, limit=5)
        self.assertTrue(pack["ready"])
        self.assertEqual(len(pack["targets"]), 5)

    def test_actual_difficulty_beats_overdue_or_interval(self):
        cards = [card(1,(1,)), card(2,(1,2,3)), card(3,(2,2,3)), card(4,(3,3))]
        cards[3]["scheduling"]["due_interpreted"]["days_from_today"] = -9999
        pack = self.build(cards)
        self.assertEqual([t["card_id"] for t in pack["targets"]], [1,2,3])
        self.assertTrue(pack["ready"])  # no 21-day maturity requirement

    def test_export_clock_and_input_order_do_not_shuffle(self):
        cards = [card(i) for i in range(6)]
        before = copy.deepcopy(cards)
        first = self.build(cards)
        second = build_session(list(reversed(cards)), "new-generation", "2026-11-20T00:00:00Z")
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["targets"], second["targets"])
        self.assertEqual(cards, before)
        self.assertNotEqual(first["exported_at"], second["exported_at"])
        self.assertEqual(first["latest_recorded_review_at"], "2026-10-02T00:00:00Z")

    def test_new_difficulty_changes_session_identity(self):
        cards = [card(i) for i in range(6)]
        old = self.build(cards)
        cards[0]["review_history"][-1]["rating"] = {"raw":1,"name":"again"}
        self.assertNotEqual(old["session_id"], self.build(cards)["session_id"])

    def test_missing_fields_inactive_or_no_failure_not_filled(self):
        cards = [card(1),card(2),card(3,(3,)),card(4)]
        cards[1]["study_state"] = "previously_reviewed_inactive"
        del cards[3]["note"]["fields"]["Word Reading"]
        pack = self.build(cards)
        self.assertFalse(pack["ready"])
        self.assertEqual(len(pack["targets"]),1)
        self.assertIn("NOT READY",session_text(pack))

    def test_text_contains_complete_context_without_audio_or_history(self):
        pack = self.build([card(i) for i in range(3)])
        output = session_text(pack)
        for t in pack["targets"]:
            for field in ("word","reading","meaning","example","translation"):
                self.assertIn(t[field], output)
        self.assertIn("Latest recorded review",output)
        self.assertIn("SESSION RULES",output)
        self.assertNotIn("review_history",output)
