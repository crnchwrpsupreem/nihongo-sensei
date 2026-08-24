from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import export_tutor_bundle


def card(card_id: int, card_type: int, queue: int, word: str) -> dict:
    return {
        "card_id": card_id,
        "note_id": card_id + 100,
        "deck": {"id": 1, "name": "日本語::Example"},
        "note": {
            "guid": f"guid-{card_id}",
            "tags": [],
            "fields": {
                "Word": {"raw_html": word, "text": word},
                "Word Meaning": {"raw_html": "meaning", "text": "meaning"},
                "Sentence": {"raw_html": f"{word}です。", "text": f"{word}です。"},
                "Sentence Meaning": {"raw_html": "example", "text": "example"},
                "Word Audio": {"raw_html": "[sound:private.mp3]", "text": "[sound:private.mp3]"},
            },
        },
        "scheduling": {
            "card_type": {"raw": card_type, "name": "state"},
            "queue": {"raw": queue, "name": "queue"},
            "interval_days": 60,
            "repetitions": 10,
            "lapses": 0,
            "due_interpreted": {"kind": "day", "days_from_today": 5},
        },
        "review_history": [
            {
                "review_id": card_id * 1000,
                "reviewed_at": "2026-01-01T00:00:00Z",
                "rating": {"raw": 3, "name": "good"},
            }
        ],
        "assessment": {"weakness": float(card_id), "strength": 1.0},
    }


def fixture() -> dict:
    cards = [
        card(1, 2, 2, "本"),
        card(2, 0, 0, "兄"),
        card(3, 2, -1, "毎日"),
        card(4, 4, 4, "日本語"),
    ]
    sentence_pairs = [
        {
            "card_id": item["card_id"],
            "lexical_item": item["note"]["fields"]["Word"]["text"],
            "japanese": item["note"]["fields"]["Sentence"]["text"],
            "english": item["note"]["fields"]["Sentence Meaning"]["text"],
        }
        for item in cards
    ]
    sentences = [pair["japanese"] for pair in sentence_pairs]
    return {
        "metadata": {
            "generated_at": "2026-08-21T00:00:00+00:00",
            "deck_root": "日本語",
            "review_event_count": 4,
            "source_database": "/home/private/.local/share/Anki2/User 1/collection.anki2",
            "source_signature": {"size_bytes": 1, "mtime_ns": 2},
        },
        "tutor_policy": {
            "strict_lexical_gate": True,
            "japanese_composition_allowed": False,
            "allowed_exact_lexical_items": ["本", "兄", "毎日", "日本語"],
            "allowed_exact_example_sentences": sentences,
            "sentence_pairs": sentence_pairs,
        },
        "cards": cards,
    }


class PublisherTests(unittest.TestCase):
    def test_study_state_classification(self) -> None:
        states = [export_tutor_bundle.study_state(item) for item in fixture()["cards"]]
        self.assertEqual(
            states,
            [
                "currently_active",
                "previously_reviewed_currently_new",
                "previously_reviewed_inactive",
                "previously_reviewed",
            ],
        )

    def test_public_bundle_has_no_source_machine_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "corpus.json"
            output = root / "public"
            source.write_text(json.dumps(fixture(), ensure_ascii=False), encoding="utf-8")
            with patch.object(
                sys,
                "argv",
                [
                    "export_tutor_bundle.py",
                    "--corpus",
                    str(source),
                    "--output",
                    str(output),
                ],
            ):
                self.assertEqual(export_tutor_bundle.main(), 0)

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            published_cards = json.loads((output / "card-index.json").read_text(encoding="utf-8"))
            policy = json.loads((output / "tutor-policy.json").read_text(encoding="utf-8"))
            all_text = "\n".join(
                path.read_text(encoding="utf-8") for path in output.iterdir()
            )

            self.assertTrue(manifest["ready"])
            self.assertEqual(manifest["reviewed_card_count"], 4)
            self.assertEqual(manifest["current_active_card_count"], 1)
            self.assertNotIn("/home/private", all_text)
            self.assertEqual(len(published_cards["cards"]), 4)
            self.assertEqual(published_cards["shards"], ["cards-0001.json"])
            self.assertTrue((output / "cards-0001.json").is_file())
            shard = json.loads((output / "cards-0001.json").read_text(encoding="utf-8"))
            self.assertEqual(
                shard["cards"][0]["tutor_material"]["sentence_pairs"][0]["japanese"],
                "本です。",
            )
            self.assertNotIn("sentence_pairs", policy["tutor_policy"])
            self.assertEqual(
                policy["tutor_policy"]["material_storage"]["sentence_pair_count"], 4
            )
            self.assertEqual(policy["schema_version"], 3)
            self.assertEqual(
                policy["tutor_policy"]["japanese_composition_allowed"],
                "controlled-transfer-only",
            )
            self.assertEqual(
                policy["tutor_policy"]["required_checks_per_entry"],
                ["meaning", "exact_japanese_recall"],
            )
            self.assertTrue(policy["tutor_policy"]["one_exercise_cannot_pass_both_checks"])
            self.assertEqual(
                policy["tutor_policy"]["study_order"],
                ["FRESH", "REINFORCE", "MATURE"],
            )
            self.assertEqual(policy["lesson_sequence"], ["FRESH", "REINFORCE", "MATURE"])
            self.assertNotIn("lesson_mix", policy)
            self.assertIn(
                "voice-corpus.txt",
                policy["tutor_policy"]["material_storage"]["location"],
            )
            transfer = policy["tutor_policy"]["controlled_transfer"]
            self.assertEqual(transfer["maximum_changed_lexical_items"], 1)
            self.assertIn("file order", transfer["order"])

            voice = (output / "voice-corpus.txt").read_text(encoding="utf-8")
            self.assertIn("[FRESH]", voice)
            self.assertIn("[REINFORCE]", voice)
            self.assertIn("[MATURE]", voice)
            self.assertIn("[KNOWN WORDS]", voice)
            self.assertIn("本 — meaning | 本です。 — example", voice)
            self.assertNotIn("private.mp3", voice)
            self.assertEqual(manifest["voice_corpus"]["file"], "voice-corpus.txt")

            for name, expected in manifest["files"].items():
                published = (output / name).read_bytes()
                self.assertNotIn(b"\r\n", published)
                self.assertEqual(len(published), expected["bytes"])
                self.assertEqual(hashlib.sha256(published).hexdigest(), expected["sha256"])

    def test_project_instructions_name_every_bundle_file(self) -> None:
        instructions = Path("CHATGPT_PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8")
        for name in ("manifest.json", "voice-corpus.txt"):
            self.assertIn(name, instructions)

    def test_project_instructions_require_complete_text_bootstrap_and_order(self) -> None:
        instructions = Path("CHATGPT_PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8")
        self.assertIn("complete contents of voice-corpus.txt", instructions)
        self.assertIn("copied verbatim", instructions)
        self.assertIn("Give no lesson exercise in the bootstrap response", instructions)
        self.assertIn("Complete every FRESH entry before REINFORCE", instructions)
        self.assertIn("Complete every REINFORCE entry before MATURE", instructions)
        self.assertIn("every detailed FRESH, REINFORCE, and MATURE entry", instructions)

    def test_voice_selection_is_simple_bounded_and_deterministic(self) -> None:
        generated = export_tutor_bundle.parse_timestamp("2026-08-21T00:00:00+00:00")
        self.assertIsNotNone(generated)
        payload = fixture()
        cards = []
        for number in range(40):
            fresh = card(100 + number, 1, 1, f"新{number}")
            fresh["scheduling"]["interval_days"] = 1
            cards.append(fresh)
        for number in range(35):
            item = card(200 + number, 2, 2, f"補強{number}")
            item["scheduling"]["interval_days"] = 20
            item["assessment"]["weakness"] = float(35 - number)
            cards.append(item)
        for number in range(15):
            item = card(300 + number, 2, 2, f"成熟{number}")
            item["scheduling"]["interval_days"] = 90
            item["assessment"]["weakness"] = 0.0
            cards.append(item)
        historical = card(400, 2, -1, "昔")
        cards.append(historical)
        payload["cards"] = cards
        payload["tutor_policy"]["sentence_pairs"] = []
        public = export_tutor_bundle.public_cards(payload)
        first, known_first = export_tutor_bundle.select_voice_cards(public, generated)
        second, known_second = export_tutor_bundle.select_voice_cards(public, generated)
        self.assertEqual(len(first["FRESH"]), 40)
        self.assertEqual(len(first["REINFORCE"]), 30)
        self.assertEqual(len(first["MATURE"]), 10)
        self.assertEqual(
            [item["card_id"] for item in first["MATURE"]],
            [item["card_id"] for item in second["MATURE"]],
        )
        self.assertEqual(known_first, known_second)
        self.assertIn("昔", known_first)
        self.assertTrue(any(word.startswith("補強") for word in known_first))
        self.assertTrue(any(word.startswith("成熟") for word in known_first))

    def test_voice_corpus_keeps_per_card_sentence_fields_without_media(self) -> None:
        payload = fixture()
        first = card(500, 1, 1, "語一")
        second = card(501, 1, 1, "語二")
        for item in (first, second):
            item["note"]["fields"]["Sentence"]["text"] = "同じ文です。"
            item["note"]["fields"]["Sentence Meaning"]["text"] = "It is the same sentence."
        payload["cards"] = [first, second]
        payload["tutor_policy"]["sentence_pairs"] = []
        public = export_tutor_bundle.public_cards(payload)
        generated = export_tutor_bundle.parse_timestamp("2026-08-21T00:00:00+00:00")
        self.assertIsNotNone(generated)
        text, counts = export_tutor_bundle.voice_corpus_text("generation", public, generated)
        self.assertEqual(counts["fresh"], 2)
        self.assertIn("語一 — meaning | 同じ文です。 — It is the same sentence.", text)
        self.assertIn("語二 — meaning | 同じ文です。 — It is the same sentence.", text)
        self.assertNotIn("private.mp3", text)

    def test_readme_status_update_preserves_static_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            readme = Path(temporary) / "README.md"
            readme.write_text(
                "# Test\n\n## Current tutor status\n"
                f"{export_tutor_bundle.README_STATUS_START}\nold\n"
                f"{export_tutor_bundle.README_STATUS_END}\n\n"
                "## Agent quick navigation\n\nKEEP THIS STATIC\n",
                encoding="utf-8",
                newline="\n",
            )
            manifest = {
                "ready": True,
                "generated_at": "2026-08-22T01:00:00-04:00",
                "reviewed_card_count": 20,
                "current_active_card_count": 18,
                "review_event_count": 40,
                "generation_id": "example-generation",
            }

            export_tutor_bundle.update_readme_status(readme, manifest)
            updated = readme.read_text(encoding="utf-8")

            self.assertIn("KEEP THIS STATIC", updated)
            self.assertIn("| Status | **Ready** |", updated)
            self.assertIn("| Reviewed cards available to the tutor | **20** |", updated)
            self.assertIn("`example-generation`", updated)
            self.assertNotIn("\nold\n", updated)
            self.assertEqual(updated.count(export_tutor_bundle.README_STATUS_START), 1)
            self.assertEqual(updated.count(export_tutor_bundle.README_STATUS_END), 1)


if __name__ == "__main__":
    unittest.main()
