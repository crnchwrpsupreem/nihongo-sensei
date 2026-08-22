"""Deterministic sentence-first tutoring controller.

The controller is the only component allowed to choose exercises or emit Japanese.
Every Japanese string is copied verbatim from the refreshed active-card corpus, or
is a literal contiguous chunk of one such sentence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


EXERCISE_TYPES = (
    "japanese_to_english",
    "english_to_japanese",
    "contextual_selection",
    "partial_cue_reconstruction",
)


class ControllerError(ValueError):
    """Raised when corpus or state violates the deterministic controller contract."""


@dataclass(frozen=True)
class SentencePair:
    card_id: int
    lexical_item: str
    japanese: str
    english: str


def _normalize_japanese(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"[\s。、！？!?「」『』（）()\[\]]+", "", value).casefold()


def _normalize_english(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[a-z0-9']+", value))


def _english_similarity(actual: str, expected: str) -> float:
    left = _normalize_english(actual)
    right = _normalize_english(expected)
    if not left or not right:
        return 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    left_words = set(left.split())
    right_words = set(right.split())
    union = left_words | right_words
    jaccard = len(left_words & right_words) / len(union) if union else 0.0
    return max(sequence, jaccard)


def _literal_opening_chunk(sentence: str) -> str:
    if "、" in sentence:
        return sentence[: sentence.index("、") + 1]
    visible = sentence.rstrip("。！？!?")
    length = max(1, min(len(visible), round(len(visible) * 0.45)))
    return visible[:length]


class TutorController:
    """State machine that returns assessment first and exactly one next exercise."""

    def __init__(self, corpus: dict[str, Any]):
        policy = corpus.get("tutor_policy") or {}
        if policy.get("strict_lexical_gate") is not True:
            raise ControllerError("Corpus is missing the strict lexical gate")
        if policy.get("japanese_composition_allowed") is not False:
            raise ControllerError("Corpus does not explicitly prohibit Japanese composition")

        raw_pairs = policy.get("sentence_pairs") or []
        pairs = [
            SentencePair(
                card_id=int(item["card_id"]),
                lexical_item=str(item.get("lexical_item", "")),
                japanese=str(item["japanese"]).strip(),
                english=str(item["english"]).strip(),
            )
            for item in raw_pairs
            if str(item.get("japanese", "")).strip()
            and str(item.get("english", "")).strip()
        ]
        if not pairs:
            raise ControllerError("No exact Japanese/English sentence pairs are available")

        allowed = set(policy.get("allowed_exact_example_sentences") or [])
        if any(pair.japanese not in allowed for pair in pairs):
            raise ControllerError("A sentence pair is outside the exact-sentence whitelist")

        recommended = (policy.get("recommended_initial_drill") or {}).get(
            "target_japanese"
        )
        if recommended:
            pairs.sort(key=lambda pair: pair.japanese != recommended)

        self._pairs = pairs
        self._allowed_sentences = {pair.japanese for pair in pairs}
        self._metadata = corpus.get("metadata") or {}
        self._state = "ready"
        self._turn = 0
        self._current: dict[str, Any] | None = None

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> dict[str, Any]:
        self._state = "awaiting_answer"
        self._turn = 0
        self._current = self._build_exercise(self._turn)
        response = {
            "assessment": None,
            "exercise": self._public_exercise(self._current),
            "session": self._session_summary(),
        }
        self._validate_response(response)
        return response

    def submit_answer(self, answer: str) -> dict[str, Any]:
        if self._state != "awaiting_answer" or self._current is None:
            raise ControllerError("Start a session before submitting an answer")
        answer = answer.strip()
        if not answer:
            raise ControllerError("Answer cannot be empty")

        assessment = self._assess(answer, self._current)
        self._turn += 1
        self._current = self._build_exercise(self._turn)
        response = {
            "assessment": assessment,
            "exercise": self._public_exercise(self._current),
            "session": self._session_summary(),
        }
        self._validate_response(response)
        return response

    def current(self) -> dict[str, Any]:
        return {
            "assessment": None,
            "exercise": self._public_exercise(self._current)
            if self._current
            else None,
            "session": self._session_summary(),
        }

    def _session_summary(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "turn": self._turn,
            "active_card_count": int(
                self._metadata.get("current_active_card_count", len(self._pairs))
            ),
            "sentence_pair_count": len(self._pairs),
            "policy": {
                "sentence_first": True,
                "strict_lexical_gate": True,
                "japanese_composition_allowed": False,
                "english_speed": "normal conversational speed",
                "japanese_speed": "natural, clear, and modestly slower than English",
                "response_order": "assessment first, then exactly one next exercise",
            },
        }

    def _pair_for_turn(self, turn: int) -> SentencePair:
        return self._pairs[turn % len(self._pairs)]

    def _build_exercise(self, turn: int) -> dict[str, Any]:
        pair = self._pair_for_turn(turn)
        exercise_type = EXERCISE_TYPES[turn % len(EXERCISE_TYPES)]
        base: dict[str, Any] = {
            "id": f"turn-{turn + 1}",
            "type": exercise_type,
            "card_id": pair.card_id,
            "expected_japanese": pair.japanese,
            "expected_english": pair.english,
            "options": [],
            "japanese_segments": [],
        }

        if exercise_type == "japanese_to_english":
            base.update(
                instruction_en="What does this exact active-card sentence mean in English?",
                japanese_segments=[pair.japanese],
                answer_kind="english_meaning",
            )
        elif exercise_type == "english_to_japanese":
            base.update(
                instruction_en=(
                    "Say the exact stored Japanese sentence for this card meaning: "
                    f"{pair.english}"
                ),
                answer_kind="exact_japanese",
            )
        elif exercise_type == "contextual_selection":
            candidates = [pair]
            offset = 1
            while len(candidates) < min(3, len(self._pairs)):
                candidate = self._pairs[(turn + offset) % len(self._pairs)]
                if candidate.japanese not in {item.japanese for item in candidates}:
                    candidates.append(candidate)
                offset += 1
            correct_position = turn % len(candidates)
            candidates[0], candidates[correct_position] = (
                candidates[correct_position],
                candidates[0],
            )
            options = [item.japanese for item in candidates]
            base.update(
                instruction_en=(
                    "Which exact active-card sentence matches this stored meaning: "
                    f"{pair.english} Answer with the option number or exact sentence."
                ),
                options=options,
                japanese_segments=options,
                correct_option=correct_position + 1,
                answer_kind="selection",
            )
        else:
            chunk = _literal_opening_chunk(pair.japanese)
            if chunk not in pair.japanese:
                raise ControllerError("Partial cue is not a literal sentence chunk")
            base.update(
                instruction_en=(
                    "Reconstruct the full exact active-card sentence from this literal "
                    "opening chunk."
                ),
                japanese_segments=[chunk],
                literal_chunk=chunk,
                answer_kind="exact_japanese",
            )
        return base

    @staticmethod
    def _public_exercise(exercise: dict[str, Any] | None) -> dict[str, Any] | None:
        if exercise is None:
            return None
        public_keys = (
            "id",
            "type",
            "instruction_en",
            "options",
            "japanese_segments",
            "literal_chunk",
        )
        return {key: exercise[key] for key in public_keys if key in exercise}

    def _assess(self, answer: str, exercise: dict[str, Any]) -> dict[str, Any]:
        kind = exercise["answer_kind"]
        expected_ja = exercise["expected_japanese"]
        expected_en = exercise["expected_english"]

        if kind == "english_meaning":
            score = _english_similarity(answer, expected_en)
            if score >= 0.82:
                rating = "correct"
                feedback = "Correct."
                correction = None
            elif score >= 0.48:
                rating = "partially_correct"
                feedback = f"Partially correct. The stored meaning is: {expected_en}"
                correction = None
            else:
                rating = "incorrect"
                feedback = f"Incorrect. The stored meaning is: {expected_en}"
                correction = None
        elif kind == "selection":
            normalized = _normalize_japanese(answer)
            option_text = str(exercise["correct_option"])
            correct = answer.strip() == option_text or normalized == _normalize_japanese(
                expected_ja
            )
            rating = "correct" if correct else "incorrect"
            feedback = (
                "Correct."
                if correct
                else f"Incorrect. The correct option is {exercise['correct_option']}."
            )
            correction = None if correct else expected_ja
        else:
            actual = _normalize_japanese(answer)
            expected = _normalize_japanese(expected_ja)
            similarity = SequenceMatcher(None, actual, expected).ratio() if actual else 0.0
            if actual == expected:
                rating = "correct"
                feedback = "Correct."
                correction = None
            elif actual and (actual in expected or similarity >= 0.62):
                rating = "partially_correct"
                feedback = "Partially correct. Use the exact stored sentence."
                correction = expected_ja
            else:
                rating = "incorrect"
                feedback = "Incorrect. The exact stored sentence is shown below."
                correction = expected_ja

        return {
            "rating": rating,
            "feedback_en": feedback,
            "correction_japanese": correction,
        }

    def _validate_response(self, response: dict[str, Any]) -> None:
        exercise = response.get("exercise") or {}
        for segment in exercise.get("japanese_segments") or []:
            if segment in self._allowed_sentences:
                continue
            if not any(segment and segment in sentence for sentence in self._allowed_sentences):
                raise ControllerError("Controller attempted to emit unapproved Japanese")
        for option in exercise.get("options") or []:
            if option not in self._allowed_sentences:
                raise ControllerError("Controller attempted to emit an unapproved option")

        assessment = response.get("assessment")
        if assessment and assessment.get("correction_japanese"):
            if assessment["correction_japanese"] not in self._allowed_sentences:
                raise ControllerError("Controller attempted to emit an unapproved correction")


def load_controller(corpus: dict[str, Any]) -> TutorController:
    """Create a validated controller from a freshly generated corpus."""

    return TutorController(corpus)
