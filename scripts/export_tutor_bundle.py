#!/usr/bin/env python3
"""Convert a private read-only Anki extraction into the public tutor bundle."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CARDS_PER_SHARD = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
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
        "3. Use only exact stored Japanese sentences or literal contiguous chunks; do not compose Japanese from known words.",
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
    compact_policy["material_storage"] = {
        "location": "Each full card record in cards-NNNN.json has tutor_material.",
        "lexical_item_count": lexical_item_count,
        "sentence_pair_count": sentence_pair_count,
        "rule": "Load tutor_material from the selected card's shard before quoting or testing Japanese.",
    }
    policy_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": metadata["generated_at"],
        "lesson_mix": {
            "currently_active": 0.70,
            "previously_reviewed": 0.20,
            "strong_or_easy_review": 0.10,
        },
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
    atomic_write(output / "tutor-policy.json", json_text(policy_payload))
    atomic_write(output / "lesson-brief.md", brief(payload, cards))

    files = {}
    for name in ("card-index.json", "tutor-policy.json", "lesson-brief.md", *shard_files):
        path = output / name
        files[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    generation_id = files["card-index.json"]["sha256"][:16]
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
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
