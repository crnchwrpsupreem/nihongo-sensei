from __future__ import annotations

import unittest
from unittest.mock import patch

from voice_app.controller import ControllerError, TutorController
from voice_app.server import SessionManager, _multipart_body, create_server


SENTENCES = (
    (1, "毎日", "毎日、日本語を勉強します。", "I study Japanese every day."),
    (2, "兄", "兄がいます。", "I have an older brother."),
    (3, "本", "これは日本語の本です。", "This is a Japanese book."),
    (4, "好き", "私はワインが好きです。", "I like wine."),
)


def fixture_corpus() -> dict:
    pairs = [
        {
            "card_id": card_id,
            "lexical_item": word,
            "japanese": japanese,
            "english": english,
        }
        for card_id, word, japanese, english in SENTENCES
    ]
    return {
        "metadata": {"current_active_card_count": len(SENTENCES)},
        "tutor_policy": {
            "strict_lexical_gate": True,
            "japanese_composition_allowed": False,
            "allowed_exact_example_sentences": [item[2] for item in SENTENCES],
            "sentence_pairs": pairs,
            "recommended_initial_drill": {
                "target_japanese": "毎日、日本語を勉強します。"
            },
        },
    }


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = TutorController(fixture_corpus())

    def test_start_returns_one_approved_sentence_exercise(self) -> None:
        response = self.controller.start()
        self.assertIsNone(response["assessment"])
        self.assertEqual(response["exercise"]["type"], "japanese_to_english")
        self.assertEqual(
            response["exercise"]["japanese_segments"],
            ["毎日、日本語を勉強します。"],
        )
        self.assertEqual(response["session"]["sentence_pair_count"], 4)
        self.assertFalse(
            response["session"]["policy"]["japanese_composition_allowed"]
        )

    def test_answer_response_is_assessment_first_then_one_exercise(self) -> None:
        self.controller.start()
        response = self.controller.submit_answer("I study Japanese every day")
        self.assertEqual(list(response)[:2], ["assessment", "exercise"])
        self.assertEqual(response["assessment"]["rating"], "correct")
        self.assertEqual(response["exercise"]["type"], "english_to_japanese")
        self.assertNotIn("expected_japanese", response["exercise"])
        self.assertIsInstance(response["exercise"], dict)

    def test_incorrect_japanese_correction_is_exact_stored_sentence(self) -> None:
        self.controller.start()
        self.controller.submit_answer("I study Japanese every day")
        response = self.controller.submit_answer("猫")
        self.assertEqual(response["assessment"]["rating"], "incorrect")
        self.assertEqual(response["assessment"]["correction_japanese"], "兄がいます。")
        self.assertIn(
            response["assessment"]["correction_japanese"],
            {item[2] for item in SENTENCES},
        )

    def test_selection_options_are_only_stored_sentences(self) -> None:
        self.controller.start()
        self.controller.submit_answer("I study Japanese every day")
        response = self.controller.submit_answer("兄がいます。")
        options = response["exercise"]["options"]
        self.assertEqual(response["exercise"]["type"], "contextual_selection")
        self.assertTrue(options)
        self.assertTrue(set(options).issubset({item[2] for item in SENTENCES}))

    def test_partial_cue_is_literal_contiguous_chunk(self) -> None:
        self.controller.start()
        self.controller.submit_answer("I study Japanese every day")
        self.controller.submit_answer("兄がいます。")
        selection = self.controller.current()["exercise"]
        correct = str(selection["options"].index("これは日本語の本です。") + 1)
        response = self.controller.submit_answer(correct)
        exercise = response["exercise"]
        self.assertEqual(exercise["type"], "partial_cue_reconstruction")
        chunk = exercise["literal_chunk"]
        self.assertIn(chunk, "私はワインが好きです。")

    def test_rejects_corpus_that_allows_composition(self) -> None:
        corpus = fixture_corpus()
        corpus["tutor_policy"]["japanese_composition_allowed"] = True
        with self.assertRaises(ControllerError):
            TutorController(corpus)


class ServerSafetyTests(unittest.TestCase):
    def test_rejects_non_loopback_bind(self) -> None:
        with self.assertRaises(ValueError):
            create_server("0.0.0.0", 0)

    def test_no_key_keeps_text_mode_and_blocks_realtime(self) -> None:
        manager = SessionManager()
        original = manager.api_key
        if original:
            self.skipTest("Environment already has an API key")
        self.assertEqual(manager.status()["mode"], "text/mock")
        with self.assertRaises(ControllerError):
            manager.connect_realtime("v=0\r\n")

    def test_multipart_contains_sdp_and_session_without_api_key(self) -> None:
        body = _multipart_body(
            "boundary",
            (("sdp", "v=0", "application/sdp"), ("session", "{}", "application/json")),
        )
        self.assertIn(b'name="sdp"', body)
        self.assertIn(b'name="session"', body)
        self.assertTrue(body.endswith(b"--boundary--\r\n"))

    def test_realtime_bridge_sends_transcription_config_not_corpus(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/sdp"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read() -> bytes:
                return b"v=0\r\nanswer"

        manager = SessionManager()
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch(
                "voice_app.server.urllib.request.urlopen",
                return_value=FakeResponse(),
            ) as mocked:
                status, content_type, answer = manager.connect_realtime("v=0\r\noffer")
        request = mocked.call_args.args[0]
        body = request.data
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/sdp")
        self.assertEqual(answer, "v=0\r\nanswer")
        self.assertIn(b'"type": "transcription"', body)
        self.assertIn(b'"model": "gpt-live-transcribe"', body)
        self.assertNotIn("毎日、日本語を勉強します。".encode(), body)
        self.assertNotIn(b"sentence_pairs", body)


if __name__ == "__main__":
    unittest.main()
