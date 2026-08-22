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
                "Sentence": {"raw_html": f"{word}です。", "text": f"{word}です。"},
                "Sentence Meaning": {"raw_html": "example", "text": "example"},
            },
        },
        "scheduling": {
            "card_type": {"raw": card_type, "name": "state"},
            "queue": {"raw": queue, "name": "queue"},
        },
        "review_history": [
            {"review_id": card_id * 1000, "reviewed_at": "2026-01-01T00:00:00Z"}
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
            self.assertFalse(policy["tutor_policy"]["japanese_composition_allowed"])

            for name, expected in manifest["files"].items():
                published = (output / name).read_bytes()
                self.assertNotIn(b"\r\n", published)
                self.assertEqual(len(published), expected["bytes"])
                self.assertEqual(hashlib.sha256(published).hexdigest(), expected["sha256"])

    def test_project_instructions_name_every_bundle_file(self) -> None:
        instructions = Path("CHATGPT_PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8")
        for name in ("manifest.json", "lesson-brief.md", "tutor-policy.json", "card-index.json"):
            self.assertIn(name, instructions)


if __name__ == "__main__":
    unittest.main()
