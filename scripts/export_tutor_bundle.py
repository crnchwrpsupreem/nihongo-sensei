#!/usr/bin/env python3
"""Convert a private read-only Anki extraction into the public tutor bundle."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
CARDS_PER_SHARD = 100
VOICE_REINFORCE_LIMIT = 30
VOICE_MATURE_LIMIT = 10
README_STATUS_START = "<!-- nihongo-sensei-status:start -->"
README_STATUS_END = "<!-- nihongo-sensei-status:end -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--readme", type=Path)
    return parser.parse_args()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        # Force LF on Windows so Git's text normalization cannot change the
        # bytes after their sizes and hashes are recorded in manifest.json.
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def update_readme_status(path: Path, manifest: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(README_STATUS_START) != 1 or text.count(README_STATUS_END) != 1:
        raise RuntimeError("README must contain exactly one generated status marker pair")
    before, remainder = text.split(README_STATUS_START, 1)
    _, after = remainder.split(README_STATUS_END, 1)
    state = "Ready" if manifest["ready"] else "Not ready"
    body = "\n".join(
        [
            README_STATUS_START,
            "_Automatically refreshed by the mini-PC publisher. Do not edit inside these markers._",
            "",
            "| Field | Current value |",
            "| --- | --- |",
            f"| Status | **{state}** |",
            f"| Last generated | `{manifest['generated_at']}` |",
            f"| Reviewed cards available to the tutor | **{manifest['reviewed_card_count']}** |",
            f"| Currently active cards | **{manifest['current_active_card_count']}** |",
            f"| Review events | **{manifest['review_event_count']}** |",
            f"| Generation | `{manifest['generation_id']}` |",
            "| Current bundle | [`tutor-data/current/`](tutor-data/current/) |",
            README_STATUS_END,
        ]
    )
    atomic_write(path, before + body + after)


def study_state(card: dict[str, Any]) -> str:
    scheduling = card["scheduling"]
    card_type = int(scheduling["card_type"]["raw"])
    queue = int(scheduling["queue"]["raw"])
    if card_type == 0:
        return "previously_reviewed_currently_new"
    if queue < 0:
        return "previously_reviewed_inactive"
    if card_type in (1, 2, 3) and queue in (1, 2, 3, 4):
        return "currently_active"
    return "previously_reviewed"


def public_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pairs_by_card: dict[int, list[dict[str, Any]]] = {}
    for pair in payload["tutor_policy"].get("sentence_pairs", []):
        pairs_by_card.setdefault(int(pair["card_id"]), []).append(copy.deepcopy(pair))

    result: list[dict[str, Any]] = []
    for original in payload["cards"]:
        card = copy.deepcopy(original)
        card["study_state"] = study_state(card)
        history = card.get("review_history") or []
        card["review_summary"] = {
            "review_count": len(history),
            "first_reviewed_at": history[0]["reviewed_at"] if history else None,
            "last_reviewed_at": history[-1]["reviewed_at"] if history else None,
        }
        pairs = pairs_by_card.get(int(card["card_id"]), [])
        card["tutor_material"] = {
            "allowed_exact_lexical_item": card_label(card),
            "sentence_pairs": pairs,
            "allowed_exact_example_sentences": [pair["japanese"] for pair in pairs],
        }
        result.append(card)
    return result


def top_labels(cards: list[dict[str, Any]], state: str, limit: int = 12) -> list[str]:
    matching = [card for card in cards if card["study_state"] == state]
    matching.sort(
        key=lambda item: (item["assessment"]["weakness"], item["card_id"]),
        reverse=True,
    )
    labels: list[str] = []
    for card in matching[:limit]:
        fields = card["note"]["fields"]
        label = next(
            (
                fields[name]["text"]
                for name in ("Word", "Expression", "Vocabulary", "Front", "Sentence")
                if name in fields and fields[name]["text"]
            ),
            str(card["card_id"]),
        )
        labels.append(label.replace("\n", " ")[:100])
    return labels


def card_label(card: dict[str, Any]) -> str:
    fields = card["note"]["fields"]
    return next(
        (
            fields[name]["text"]
            for name in ("Word", "Expression", "Vocabulary", "Front", "Sentence")
            if name in fields and fields[name]["text"]
        ),
        str(card["card_id"]),
    ).replace("\n", " ")[:160]


def parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def field_text(card: dict[str, Any], *names: str) -> str:
    fields = card["note"]["fields"]
    for name in names:
        value = fields.get(name, {}).get("text", "").strip()
        if value:
            return value
    return ""


def inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().replace(" | ", " / ")


def recent_difficulty(card: dict[str, Any]) -> bool:
    history = card.get("review_history") or []
    return bool(history and int(history[-1]["rating"]["raw"]) in (1, 2))


def voice_category(card: dict[str, Any], generated_at: dt.datetime) -> str | None:
    if card["study_state"] != "currently_active":
        return None
    scheduling = card["scheduling"]
    card_type = int(scheduling["card_type"]["raw"])
    queue = int(scheduling["queue"]["raw"])
    interval = max(int(scheduling.get("interval_days") or 0), 0)
    repetitions = max(int(scheduling.get("repetitions") or 0), 0)
    first_review = parse_timestamp(card["review_summary"].get("first_reviewed_at"))
    age_days = None
    if first_review is not None:
        age_days = max(0, (generated_at.date() - first_review.date()).days)
    if card_type in (1, 3) or queue in (1, 3, 4):
        return "FRESH"
    if age_days is not None and age_days <= 14:
        return "FRESH"
    if repetitions <= 3 or interval <= 7:
        return "FRESH"
    due = scheduling.get("due_interpreted") or {}
    overdue = int(due.get("days_from_today") or 0) < 0
    lapses = max(int(scheduling.get("lapses") or 0), 0)
    weakness = float(card.get("assessment", {}).get("weakness") or 0)
    if interval <= 30 or overdue or recent_difficulty(card) or lapses > 0 or weakness >= 10:
        return "REINFORCE"
    return "MATURE"


def voice_line(card: dict[str, Any]) -> str | None:
    word = inline_text(field_text(card, "Word", "Expression", "Vocabulary", "Front"))
    meaning = inline_text(field_text(card, "Word Meaning", "Meaning", "Definition", "English"))
    japanese = inline_text(field_text(card, "Sentence"))
    english = inline_text(field_text(card, "Sentence Meaning", "Sentence Translation"))
    if not word or not japanese or not english:
        return None
    return f"{word} — {meaning} | {japanese} — {english}" if meaning else f"{word} | {japanese} — {english}"


def select_voice_cards(
    cards: list[dict[str, Any]], generated_at: dt.datetime
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    categorized: dict[str, list[dict[str, Any]]] = {
        "FRESH": [],
        "REINFORCE": [],
        "MATURE": [],
    }
    for card in cards:
        category = voice_category(card, generated_at)
        if category and voice_line(card):
            categorized[category].append(card)

    def first_review_key(card: dict[str, Any]) -> float:
        parsed = parse_timestamp(card["review_summary"].get("first_reviewed_at"))
        return parsed.timestamp() if parsed else 0.0

    categorized["FRESH"].sort(
        key=lambda card: (
            int(card["scheduling"]["card_type"]["raw"]) not in (1, 3),
            -first_review_key(card),
            int(card["card_id"]),
        )
    )
    categorized["REINFORCE"].sort(
        key=lambda card: (
            not recent_difficulty(card),
            int((card["scheduling"].get("due_interpreted") or {}).get("days_from_today") or 0),
            -float(card["assessment"]["weakness"]),
            int(card["scheduling"].get("interval_days") or 0),
            int(card["card_id"]),
        )
    )
    categorized["REINFORCE"] = categorized["REINFORCE"][:VOICE_REINFORCE_LIMIT]

    mature_pool = sorted(categorized["MATURE"], key=lambda card: int(card["card_id"]))
    mature_selection: list[dict[str, Any]] = []
    if mature_pool:
        cycle = generated_at.date().toordinal() // 7
        offset = (cycle * VOICE_MATURE_LIMIT) % len(mature_pool)
        for index in range(min(VOICE_MATURE_LIMIT, len(mature_pool))):
            mature_selection.append(mature_pool[(offset + index) % len(mature_pool)])
    categorized["MATURE"] = mature_selection

    selected_ids = {
        int(card["card_id"])
        for category in categorized.values()
        for card in category
    }
    known_words: list[str] = []
    seen_words: set[str] = set()
    for card in cards:
        if int(card["card_id"]) in selected_ids:
            continue
        word = inline_text(field_text(card, "Word", "Expression", "Vocabulary", "Front"))
        if word and word not in seen_words:
            seen_words.add(word)
            known_words.append(word)
    return categorized, known_words


def voice_corpus_text(
    generation_id: str,
    cards: list[dict[str, Any]],
    generated_at: dt.datetime,
) -> tuple[str, dict[str, int]]:
    categorized, known_words = select_voice_cards(cards, generated_at)
    lines = [f"Generation: {generation_id}"]
    for category in ("FRESH", "REINFORCE", "MATURE"):
        lines += ["", f"[{category}]"]
        lines.extend(voice_line(card) or "" for card in categorized[category])
    lines += ["", "[KNOWN WORDS]", "、".join(known_words), ""]
    counts = {
        "fresh": len(categorized["FRESH"]),
        "reinforce": len(categorized["REINFORCE"]),
        "mature": len(categorized["MATURE"]),
        "known_words": len(known_words),
    }
    return "\n".join(lines), counts


def progression_policy() -> dict[str, Any]:
    """Return the canonical tutor progression, independent of extractor age."""
    return {
        "japanese_composition_allowed": "controlled-transfer-only",
        "novel_japanese_mode": "controlled-transfer-after-exact-mastery-or-explicit-user-approved-preview-teach",
        "lesson_priority": "linear exact practice through FRESH, REINFORCE, and MATURE before controlled transfer",
        "allowed_exercise_types": [
            "Japanese-to-English meaning of one exact compact-corpus sentence",
            "English-to-exact-Japanese recall using the same compact-corpus entry",
        ],
        "voice_source": "voice-corpus.txt",
        "text_bootstrap": "Before Voice begins, reproduce the complete current voice-corpus.txt verbatim in one text response, then stop without an exercise.",
        "study_order": ["FRESH", "REINFORCE", "MATURE"],
        "required_checks_per_entry": ["meaning", "exact_japanese_recall"],
        "one_exercise_cannot_pass_both_checks": True,
        "controlled_transfer": {
            "eligibility": "every detailed FRESH, REINFORCE, and MATURE entry has passed separate meaning and exact-Japanese-recall checks",
            "label": "generated variation",
            "maximum_changed_lexical_items": 1,
            "replacement_source": "any reviewed lexical item appearing in the current compact corpus",
            "must_preserve": ["sentence structure", "particles", "inflection", "politeness"],
            "must_not_introduce": ["new grammar", "new particles", "new inflections", "new register"],
            "unsafe_or_uncertain_substitution": "do not generate; continue exact-card practice",
            "failed_variation": "return to the exact source sentence before another variation",
            "order": "After exact coverage is complete, revisit eligible detailed entries in file order.",
        },
        "controlled_conversation_rule": "Process every detailed entry in FRESH, then REINFORCE, then MATURE; only afterward revisit them in file order for controlled transfer",
        "prohibitions": [
            "No controlled variation before every detailed FRESH, REINFORCE, and MATURE entry passes separate meaning and exact-recall checks.",
            "No more than one lexical substitution in a controlled variation.",
            "No conjugation, question conversion, particle changes, politeness changes, structural changes, or new grammar in controlled transfer.",
            "No generated variation presented as stored Anki material.",
            "No new Japanese outside controlled transfer or explicit user-approved preview/teach mode.",
        ],
    }


def brief(payload: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["study_state"]] = counts.get(card["study_state"], 0) + 1
    active_labels = top_labels(cards, "currently_active")
    historical_labels = top_labels(cards, "previously_reviewed_currently_new")
    lines = [
        "# Current Nihongo Sensei tutor context",
        "",
        f"Generated: {payload['metadata']['generated_at']}",
        f"Deck root: `{payload['metadata']['deck_root']}`",
        f"Reviewed cards published: **{len(cards)}**",
        f"Currently active: **{counts.get('currently_active', 0)}**",
        f"Previously reviewed and currently new: **{counts.get('previously_reviewed_currently_new', 0)}**",
        f"Previously reviewed but inactive: **{counts.get('previously_reviewed_inactive', 0)}**",
        f"Review events: **{payload['metadata']['review_event_count']}**",
        "",
        "Untouched cards are excluded. The `cards-NNNN.json` shards contain exact note fields, scheduling state, and review history for every published card.",
        "",
        "## Lesson priority",
        "",
        "1. Prioritize currently active cards, especially weak, lapsed, or overdue material.",
        "2. Use previously reviewed cards for maintenance and context, never as unseen/new material.",
        "3. Use `voice-corpus.txt` for tutoring and process FRESH, then REINFORCE, then MATURE in file order.",
        "4. Complete separate meaning and exact-recall checks for every detailed entry before controlled variations.",
        "",
        "## Weak active items",
        "",
    ]
    lines.extend(f"- {label}" for label in active_labels)
    lines += ["", "## Historical items most worth revisiting", ""]
    lines.extend(f"- {label}" for label in historical_labels)
    lines.append("")
    return "\n".join(lines)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.corpus.read_text(encoding="utf-8"))
    cards = public_cards(payload)
    if not cards:
        raise RuntimeError("The reviewed-card corpus is empty; refusing to publish")

    metadata = payload["metadata"]
    counts: dict[str, int] = {}
    for card in cards:
        counts[card["study_state"]] = counts.get(card["study_state"], 0) + 1

    compact_policy = copy.deepcopy(payload["tutor_policy"])
    sentence_pair_count = len(compact_policy.get("sentence_pairs", []))
    lexical_item_count = len(compact_policy.get("allowed_exact_lexical_items", []))
    compact_policy.pop("sentence_pairs", None)
    compact_policy.pop("allowed_exact_lexical_items", None)
    compact_policy.pop("allowed_exact_example_sentences", None)
    compact_policy.pop("coverage_policy", None)
    compact_policy.pop("recommended_initial_drill", None)
    compact_policy.update(progression_policy())
    compact_policy["material_storage"] = {
        "location": "Ordinary Voice material is in voice-corpus.txt; cards-NNNN.json remains the comprehensive archive.",
        "lexical_item_count": lexical_item_count,
        "sentence_pair_count": sentence_pair_count,
        "rule": "After the mandatory text bootstrap, ordinary Voice tutoring uses the reproduced compact corpus and does not require a shard.",
    }
    policy_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": metadata["generated_at"],
        "lesson_sequence": ["FRESH", "REINFORCE", "MATURE"],
        "tutor_policy": compact_policy,
    }

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    legacy_cards = output / "cards.json"
    if legacy_cards.exists():
        legacy_cards.unlink()
    for stale in output.glob("cards-*.json"):
        stale.unlink()

    shard_files: list[str] = []
    index_cards: list[dict[str, Any]] = []
    for start in range(0, len(cards), CARDS_PER_SHARD):
        number = start // CARDS_PER_SHARD + 1
        filename = f"cards-{number:04d}.json"
        shard = cards[start : start + CARDS_PER_SHARD]
        shard_files.append(filename)
        atomic_write(
            output / filename,
            json_text(
                {
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": metadata["generated_at"],
                    "shard_number": number,
                    "cards": shard,
                }
            ),
        )
        for card in shard:
            scheduling = card["scheduling"]
            index_cards.append(
                {
                    "card_id": card["card_id"],
                    "note_id": card["note_id"],
                    "label": card_label(card),
                    "deck": card["deck"]["name"],
                    "study_state": card["study_state"],
                    "shard": filename,
                    "scheduling": {
                        "card_type": scheduling["card_type"],
                        "queue": scheduling["queue"],
                        "due_interpreted": scheduling.get("due_interpreted"),
                        "interval_days": scheduling.get("interval_days"),
                        "repetitions": scheduling.get("repetitions"),
                        "lapses": scheduling.get("lapses"),
                    },
                    "assessment": card["assessment"],
                    "review_summary": card["review_summary"],
                }
            )

    index_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": metadata["generated_at"],
        "deck_root": metadata["deck_root"],
        "inclusion_rule": "Effective deck is in the configured Japanese hierarchy and the card has at least one review-log entry. Untouched cards are excluded.",
        "study_state_counts": counts,
        "cards_per_shard": CARDS_PER_SHARD,
        "shards": shard_files,
        "cards": index_cards,
    }
    atomic_write(output / "card-index.json", json_text(index_payload))
    generation_id = sha256(output / "card-index.json")[:16]
    generated_at = parse_timestamp(metadata["generated_at"])
    if generated_at is None:
        raise RuntimeError("metadata.generated_at must be an ISO-8601 timestamp")
    voice_text, voice_counts = voice_corpus_text(generation_id, cards, generated_at)
    atomic_write(output / "voice-corpus.txt", voice_text)
    atomic_write(output / "tutor-policy.json", json_text(policy_payload))
    atomic_write(output / "lesson-brief.md", brief(payload, cards))

    files = {}
    for name in (
        "card-index.json",
        "voice-corpus.txt",
        "tutor-policy.json",
        "lesson-brief.md",
        *shard_files,
    ):
        path = output / name
        files[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ready": True,
        "generation_id": generation_id,
        "generated_at": metadata["generated_at"],
        "published_at": dt.datetime.now().astimezone().isoformat(),
        "deck_root": metadata["deck_root"],
        "reviewed_card_count": len(cards),
        "current_active_card_count": counts.get("currently_active", 0),
        "review_event_count": metadata["review_event_count"],
        "voice_corpus": {
            "file": "voice-corpus.txt",
            **voice_counts,
        },
        "card_shards": shard_files,
        "files": files,
        "privacy": {
            "public_repository": True,
            "contains_card_text": True,
            "contains_review_history": True,
            "contains_anki_media": False,
            "contains_credentials": False,
            "contains_source_machine_paths": False,
        },
    }
    atomic_write(output / "manifest.json", json_text(manifest))
    if args.readme:
        update_readme_status(args.readme, manifest)
    # Keep redirected Windows consoles safe even when their legacy code page is active.
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
