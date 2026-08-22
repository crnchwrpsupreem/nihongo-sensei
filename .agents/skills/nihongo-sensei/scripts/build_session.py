#!/usr/bin/env python3
"""Build a read-only active Anki corpus and Japanese lesson planning brief."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


FIELD_SEPARATOR = "\x1f"
DECK_SEPARATORS = ("\x1f", "::")
QUEUE_NAMES = {
    -3: "user-buried",
    -2: "scheduler-buried",
    -1: "suspended",
    0: "new",
    1: "learning",
    2: "review",
    3: "day-learning",
    4: "preview",
}
CARD_TYPE_NAMES = {0: "new", 1: "learning", 2: "review", 3: "relearning"}
REVIEW_TYPE_NAMES = {
    0: "learning",
    1: "review",
    2: "relearning",
    3: "filtered",
    4: "manual",
    5: "rescheduled",
}
RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}
SENTENCE_FIELD_RE = re.compile(r"(?:sentence|example|practice)", re.I)
NON_SPOKEN_FIELD_RE = re.compile(
    r"(?:meaning|translation|furigana|reading|audio|sound|picture|image|glossary|definition|note)",
    re.I,
)


def default_profile_path(
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if platform.startswith("win"):
        appdata = Path(env.get("APPDATA", user_home / "AppData/Roaming"))
        return appdata / "Anki2/User 1"
    if platform.startswith("linux"):
        data_home = Path(env.get("XDG_DATA_HOME", user_home / ".local/share"))
        return data_home / "Anki2/User 1"
    return user_home / "Library/Application Support/Anki2/User 1"


def parse_args() -> argparse.Namespace:
    workspace = Path(__file__).resolve().parents[4]
    platform_default = default_profile_path()
    default_profile = Path(
        os.environ.get(
            "NIHONGO_ANKI_PROFILE",
            str(platform_default),
        )
    ).expanduser()
    parser = argparse.ArgumentParser(
        description="Build a read-only tutoring corpus from currently active Japanese Anki cards."
    )
    parser.add_argument("--profile", type=Path, default=default_profile)
    parser.add_argument("--deck-root", default="日本語")
    parser.add_argument(
        "--output-dir", type=Path, default=workspace / "work/current-session"
    )
    parser.add_argument("--lesson-size", type=int, default=24)
    parser.add_argument(
        "--inclusion-mode",
        choices=("active", "historical"),
        default="active",
        help="active (default) excludes cards Anki currently marks new; historical includes every card with revlog history",
    )
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def normalized_deck_name(name: str) -> str:
    return name.replace("\x1f", "::")


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(?:script|style)\b.*?>.*?</(?:script|style)>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:div|p|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def iso_from_seconds(value: int | float | None) -> str | None:
    if not value:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).astimezone().isoformat()


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def refuse_live_sqlite(profile: Path, database: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise RuntimeError(
                f"Found active SQLite sidecar {sidecar.name}. Sync and close Anki, then retry."
            )
    lock_candidates = (profile / "collection.anki2.lock", profile / ".lock")
    for lock in lock_candidates:
        if lock.exists():
            raise RuntimeError(f"Found {lock.name}; close Anki, then retry.")


def connect_read_only(database: Path) -> sqlite3.Connection:
    uri = database.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.create_collation(
        "unicase",
        lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()),
    )
    connection.execute("PRAGMA query_only=ON")
    return connection


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def load_decks(connection: sqlite3.Connection) -> dict[int, str]:
    if table_exists(connection, "decks"):
        return {int(row["id"]): row["name"] for row in connection.execute("SELECT id,name FROM decks")}
    row = connection.execute("SELECT decks FROM col LIMIT 1").fetchone()
    return {int(deck_id): data["name"] for deck_id, data in json.loads(row[0]).items()}


def load_note_types(
    connection: sqlite3.Connection,
) -> tuple[dict[int, str], dict[int, list[str]]]:
    if table_exists(connection, "notetypes") and table_exists(connection, "fields"):
        names = {
            int(row["id"]): row["name"]
            for row in connection.execute("SELECT id,name FROM notetypes")
        }
        fields: dict[int, list[str]] = {}
        for row in connection.execute("SELECT ntid,ord,name FROM fields ORDER BY ntid,ord"):
            fields.setdefault(int(row["ntid"]), []).append(row["name"])
        return names, fields
    row = connection.execute("SELECT models FROM col LIMIT 1").fetchone()
    models = json.loads(row[0])
    names = {int(mid): model["name"] for mid, model in models.items()}
    fields = {
        int(mid): [item["name"] for item in sorted(model["flds"], key=lambda x: x["ord"])]
        for mid, model in models.items()
    }
    return names, fields


def due_description(queue: int, due: int, creation_seconds: int) -> dict[str, Any]:
    if queue in (1, 4):
        return {"kind": "timestamp", "at": iso_from_seconds(due)}
    if queue in (2, 3):
        due_date = dt.datetime.fromtimestamp(
            creation_seconds + due * 86400, tz=dt.timezone.utc
        ).date()
        today = dt.datetime.now().astimezone().date()
        return {"kind": "day", "date": due_date.isoformat(), "days_from_today": (due_date - today).days}
    if queue == 0:
        return {"kind": "new-position", "position": due}
    return {"kind": "raw", "value": due}


def review_entry(row: sqlite3.Row) -> dict[str, Any]:
    ease = int(row["ease"])
    review_type = int(row["type"])
    return {
        "review_id": int(row["id"]),
        "reviewed_at": iso_from_seconds(int(row["id"]) / 1000),
        "rating": {"raw": ease, "name": RATING_NAMES.get(ease, "unknown")},
        "interval": int(row["ivl"]),
        "previous_interval": int(row["lastIvl"]),
        "ease_factor": int(row["factor"]),
        "answer_time_ms": int(row["time"]),
        "review_type": {"raw": review_type, "name": REVIEW_TYPE_NAMES.get(review_type, "unknown")},
        "sync_sequence": int(row["usn"]),
    }


def scores(card: sqlite3.Row, history: list[dict[str, Any]]) -> dict[str, float]:
    recent = history[-10:]
    again = sum(item["rating"]["raw"] == 1 for item in recent)
    hard = sum(item["rating"]["raw"] == 2 for item in recent)
    good_easy = sum(item["rating"]["raw"] in (3, 4) for item in recent)
    interval = max(int(card["ivl"]), 0)
    lapses = max(int(card["lapses"]), 0)
    due = due_description(int(card["queue"]), int(card["due"]), int(card["crt"]))
    overdue = max(0, -int(due.get("days_from_today", 0)))
    weak = lapses * 8 + again * 6 + hard * 2 + min(overdue, 60) / 5
    if interval <= 3:
        weak += 4
    if recent and recent[-1]["rating"]["raw"] == 1:
        weak += 8
    strong = math.log2(interval + 1) * 6 + min(int(card["reps"]), 40) * 0.35
    strong += good_easy * 1.5 - lapses * 3 - again * 2
    return {"weakness": round(weak, 2), "strength": round(max(strong, 0), 2)}


def card_record(
    row: sqlite3.Row,
    deck_names: dict[int, str],
    note_type_names: dict[int, str],
    field_names: dict[int, list[str]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    mid = int(row["mid"])
    values = row["flds"].split(FIELD_SEPARATOR)
    names = field_names.get(mid, [])
    fields: dict[str, dict[str, str]] = {}
    for index, value in enumerate(values):
        name = names[index] if index < len(names) else f"Field {index + 1}"
        fields[name] = {"raw_html": value, "text": html_to_text(value)}
    effective_deck_id = int(row["odid"]) if int(row["odid"]) > 0 else int(row["did"])
    scheduling = {
        "card_type": {"raw": int(row["card_type"]), "name": CARD_TYPE_NAMES.get(int(row["card_type"]), "unknown")},
        "queue": {"raw": int(row["queue"]), "name": QUEUE_NAMES.get(int(row["queue"]), "unknown")},
        "due_raw": int(row["due"]),
        "due_interpreted": due_description(int(row["queue"]), int(row["due"]), int(row["crt"])),
        "interval_days": int(row["ivl"]),
        "ease_factor_raw": int(row["factor"]),
        "repetitions": int(row["reps"]),
        "lapses": int(row["lapses"]),
        "remaining_steps_raw": int(row["left"]),
        "original_due_raw": int(row["odue"]),
        "original_deck_id": int(row["odid"]),
        "flags": int(row["card_flags"]),
        "data": row["card_data"],
        "modified_at": iso_from_seconds(int(row["card_mod"])),
    }
    return {
        "card_id": int(row["card_id"]),
        "note_id": int(row["note_id"]),
        "template_ordinal": int(row["ord"]),
        "deck": {"id": effective_deck_id, "name": normalized_deck_name(deck_names[effective_deck_id])},
        "current_deck": {"id": int(row["did"]), "name": normalized_deck_name(deck_names.get(int(row["did"]), "Unknown"))},
        "note": {
            "note_type_id": mid,
            "note_type": note_type_names.get(mid, "Unknown"),
            "guid": row["guid"],
            "tags": row["tags"].split(),
            "fields": fields,
            "flags": int(row["note_flags"]),
            "data": row["note_data"],
            "modified_at": iso_from_seconds(int(row["note_mod"])),
        },
        "scheduling": scheduling,
        "review_history": history,
        "assessment": scores(row, history),
    }


def select_lesson_cards(cards: list[dict[str, Any]], lesson_size: int) -> list[dict[str, Any]]:
    size = min(max(lesson_size, 1), len(cards))
    weak_count = math.ceil(size * 0.5)
    strong_count = math.floor(size * 0.35)
    weak = sorted(cards, key=lambda c: (c["assessment"]["weakness"], c["card_id"]), reverse=True)
    strong = sorted(cards, key=lambda c: (c["assessment"]["strength"], c["card_id"]), reverse=True)
    chosen: list[dict[str, Any]] = []
    seen: set[int] = set()
    for group, count, label in ((weak, weak_count, "weak/revisit"), (strong, strong_count, "strong/activate")):
        added = 0
        for card in group:
            if card["card_id"] in seen:
                continue
            item = dict(card)
            item["lesson_role"] = label
            chosen.append(item)
            seen.add(card["card_id"])
            added += 1
            if added >= count:
                break
    for card in sorted(cards, key=lambda c: c["review_history"][-1]["review_id"]):
        if len(chosen) >= size:
            break
        if card["card_id"] not in seen:
            item = dict(card)
            item["lesson_role"] = "older/context"
            chosen.append(item)
            seen.add(card["card_id"])
    return chosen


def best_label(card: dict[str, Any]) -> str:
    fields = card["note"]["fields"]
    preferred = ("Word", "Expression", "Vocabulary", "Front", "Sentence")
    for name in preferred:
        if name in fields and fields[name]["text"]:
            return fields[name]["text"]
    return next((value["text"] for value in fields.values() if value["text"]), f"Card {card['card_id']}")


def sentence_examples(card: dict[str, Any]) -> list[str]:
    return [
        value["text"]
        for name, value in card["note"]["fields"].items()
        if SENTENCE_FIELD_RE.search(name)
        and not NON_SPOKEN_FIELD_RE.search(name)
        and value["text"]
    ]


def sentence_meanings(card: dict[str, Any]) -> list[str]:
    return [
        value["text"]
        for name, value in card["note"]["fields"].items()
        if SENTENCE_FIELD_RE.search(name)
        and re.search(r"(?:meaning|translation)", name, re.I)
        and value["text"]
    ]


def unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def build_lexical_gate(
    cards: list[dict[str, Any]], chosen: list[dict[str, Any]]
) -> dict[str, Any]:
    chosen_ids = {card["card_id"] for card in chosen}
    ordered_cards = chosen + [card for card in cards if card["card_id"] not in chosen_ids]
    lexical_items = unique_nonempty([best_label(card) for card in ordered_cards])
    sentence_pairs: list[dict[str, Any]] = []
    seen_sentences: set[str] = set()
    for card in ordered_cards:
        examples = sentence_examples(card)
        meanings = sentence_meanings(card)
        for index, example in enumerate(examples):
            if example in seen_sentences:
                continue
            sentence_pairs.append(
                {
                    "card_id": card["card_id"],
                    "lexical_item": best_label(card),
                    "japanese": example,
                    "english": meanings[index] if index < len(meanings) else "",
                }
            )
            seen_sentences.add(example)
    exact_sentences = [pair["japanese"] for pair in sentence_pairs]
    drill_pair = next(
        (pair for pair in sentence_pairs if pair["lexical_item"] == "毎日"),
        sentence_pairs[0] if sentence_pairs else None,
    )
    return {
        "strict_lexical_gate": True,
        "english_scaffolding_default": True,
        "lesson_priority": "sentence-first and translation-focused",
        "novel_japanese_mode": "explicit-user-approved-preview-teach-only",
        "allowed_exact_lexical_items": lexical_items,
        "allowed_exact_example_sentences": exact_sentences,
        "sentence_pairs": sentence_pairs,
        "allowed_exercise_types": [
            "Japanese-to-English meaning of one verbatim active-card sentence",
            "English-to-exact-Japanese recall using a stored sentence pair",
            "contextual selection among verbatim active-card sentences",
            "partial-cue reconstruction from a literal contiguous active-card sentence chunk",
        ],
        "word_recall_role": "warm-up, remediation, or hint only",
        "japanese_composition_allowed": False,
        "controlled_conversation_rule": "English scaffolding plus literal active-card sentences or contiguous chunks only; never invented Japanese",
        "speech_delivery": {
            "english_speed": "normal conversational speed",
            "japanese_speed": "natural, clear, and modestly slower than English",
            "japanese_default_style": "connected natural phrasing; never exaggerated or syllable-by-syllable",
            "slower_repeat_rule": "slow further or break down only when the user explicitly requests a slower repeat, then return to the default",
        },
        "recommended_initial_drill": {
            "instruction_language": "English",
            "exercise_type": "Japanese-to-English meaning",
            "instruction": "What does this exact active-card sentence mean in English?",
            "target_japanese": drill_pair["japanese"] if drill_pair else "",
            "expected_english": drill_pair["english"] if drill_pair else "",
        },
        "prohibitions": [
            "No new lexical items, inflections, polite forms, particles, greetings, fillers, or grammar constructions.",
            "No conjugation, question conversion, particle changes, or recombination of known pieces.",
            "No generated Japanese sentence, even when every component is individually whitelisted.",
            "No generated Japanese conversation material.",
            "No new Japanese outside explicit user-approved preview/teach mode.",
        ],
        "turn_taking": {
            "default_loop": "present one sentence-focused exercise; wait; send one coherent response containing direct assessment and essential correction first, then exactly one next sentence-focused exercise; wait",
            "response_order": [
                "Assess only the immediately preceding learner answer as correct, partially correct, or incorrect; give the essential correction immediately.",
                "Immediately present exactly one next active-practice exercise.",
            ],
            "applies_to": [
                "word recall",
                "sentence comprehension",
                "English-to-Japanese recall",
                "conversation tasks",
            ],
            "never_ask_whether_to_continue": True,
            "never_end_on_feedback_alone": True,
            "leave_space_after_one_prompt": True,
            "single_coherent_response": True,
            "no_preamble_before_assessment": True,
            "no_split_assessment_and_prompt": True,
            "no_delayed_praise_or_backtracking": True,
            "no_repeated_next_prompt": True,
            "no_contradictory_followup_response": True,
            "feedback_scope": "immediately preceding learner answer only",
            "pause_for": [
                "learner interruption",
                "meta question",
                "pause request",
                "lesson end",
            ],
        },
    }


def brief_markdown(payload: dict[str, Any], chosen: list[dict[str, Any]]) -> str:
    meta = payload["metadata"]
    gate = payload["tutor_policy"]
    drill = gate["recommended_initial_drill"]
    lines = [
        "# Nihongo Sensei — current session",
        "",
        f"Generated: {meta['generated_at']}",
        f"Source: read-only `{meta['source_database']}`",
        f"Deck hierarchy: `{meta['deck_root']}` ({', '.join(meta['included_decks'])})",
        f"Inclusion mode: **{meta['inclusion_mode']}**",
        f"{meta['corpus_label']}: **{meta['included_card_count']} cards** / **{meta['note_count']} notes** / **{meta['review_event_count']} review events**",
        f"Cards currently marked new despite historical reviews: {meta['currently_new_with_history_count']} total ({meta['currently_new_with_history_excluded']} excluded in this mode)",
        f"Cards with no review history: {meta['never_reviewed_card_count']} excluded",
        "",
        "The companion `corpus.json` contains every included card, every note field, current scheduling, and complete review history. This brief's lesson set was scored from that full corpus.",
        "",
        "## Strict lexical gate",
        "",
        "Use English for all instructions, questions, explanations, praise, and corrections unless the exact Japanese utterance is whitelisted below.",
        "Do not inflect, conjugate, add particles, form questions, change politeness, or recombine these items. New Japanese requires explicit user-approved preview/teach mode.",
        "",
        "Allowed exact lexical items: " + "、".join(gate["allowed_exact_lexical_items"]),
        "These individual items are for warm-up, remediation, or hints only. They are never building blocks for composition.",
        "",
        "Allowed exact example expressions:",
        "",
    ]
    lines.extend(
        f"{index}. {expression.replace(chr(10), ' ')}"
        for index, expression in enumerate(gate["allowed_exact_example_sentences"], 1)
    )
    lines += [
        "",
        "### Initial spoken drill",
        "",
        f"Ask in English: “{drill['instruction']}”",
        f"Then speak only this exact active-card expression: 「{drill['target_japanese'].replace(chr(10), ' ')}」",
        f"Expected English meaning: {drill['expected_english']}",
        "",
        "## Sentence-first exercise policy",
        "",
        "Primary unit: a verbatim active-card sentence/example/practice field paired with its stored English meaning when available.",
        "Allowed exercises: Japanese→English meaning; English→exact Japanese recall; contextual selection among verbatim active-card sentences; partial-cue reconstruction using only a literal contiguous chunk.",
        "Individual words are warm-up, remediation, or hints only. Never compose, vary, paraphrase, transform, or recombine Japanese. Controlled conversation uses English scaffolding and literal active-card sentence chunks only.",
        "",
        "## Speaking pace",
        "",
        "Speak English at normal conversational speed. Speak exact Japanese words, chunks, and card sentences clearly and naturally at a pace only modestly slower than the English.",
        "Do not exaggerate, stretch sounds, add dramatic pauses, or speak syllable-by-syllable unless the learner explicitly asks for a slower repeat. After that requested repeat, return to the modestly slowed Japanese default.",
        "",
        "## Continuous turn-taking",
        "",
        "After every ordinary learner answer, send one coherent response in this exact order: (1) directly assess only that answer as correct, partially correct, or incorrect and give the essential correction; (2) immediately give exactly one next active-practice prompt.",
        "Do not put a placeholder or preamble before the assessment. Do not split assessment and prompt across messages, backtrack with delayed praise, repeat the next prompt, or send a contradictory/reordered follow-up.",
        "After that one prompt, stop speaking so the learner can answer or interrupt. Suspend the loop for an interruption, meta question, pause request, or lesson ending.",
        "Apply this to word recall, sentence comprehension, English-to-Japanese recall, and conversation tasks. Keep feedback concise and scoped to the immediately preceding answer. Speak English normally and exact Japanese only modestly slower.",
        "",
        "## Suggested lesson set",
        "",
    ]
    for index, card in enumerate(chosen, 1):
        label = best_label(card).replace("\n", " ")[:100]
        assessment = card["assessment"]
        scheduling = card["scheduling"]
        lines.append(
            f"{index}. **{label}** — {card['lesson_role']}; deck {card['deck']['name']}; "
            f"interval {scheduling['interval_days']}d, reps {scheduling['repetitions']}, "
            f"lapses {scheduling['lapses']}; weakness {assessment['weakness']}, strength {assessment['strength']}"
        )
        examples = sentence_examples(card)
        if examples:
            lines.append(f"   - Card example: {examples[0].replace(chr(10), ' ')[:240]}")
    lines += [
        "",
        "## Teaching flow",
        "",
        "1. Present one sentence-focused exercise using a stored sentence pair; then wait.",
        "2. In one response, first assess only that answer as correct, partially correct, or incorrect and give the essential English correction, quoting only the exact stored Japanese when needed.",
        "3. In that same response, immediately present exactly one next sentence-focused exercise, rotating among the four allowed types; then wait.",
        "4. Use isolated word recall only for warm-up, remediation, or a hint. Offer preview/teach mode in English and wait for approval before any new Japanese.",
        "",
        "Never write session results to Anki. Keep any temporary observations in the conversation only.",
        "",
    ]
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def build(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    database = args.profile / "collection.anki2"
    if not database.is_file():
        raise FileNotFoundError(f"Anki collection not found: {database}")
    refuse_live_sqlite(args.profile, database)
    signature_before = file_signature(database)
    connection = connect_read_only(database)
    try:
        deck_names = load_decks(connection)
        matching_decks = {
            deck_id
            for deck_id, name in deck_names.items()
            if normalized_deck_name(name) == args.deck_root
            or normalized_deck_name(name).startswith(args.deck_root + "::")
        }
        if not matching_decks:
            raise RuntimeError(f"No deck hierarchy found for {args.deck_root!r}")
        note_type_names, field_names = load_note_types(connection)
        creation_seconds = int(connection.execute("SELECT crt FROM col LIMIT 1").fetchone()[0])
        placeholders = ",".join("?" for _ in matching_decks)
        inclusion_predicate = (
            "AND c.type IN (1,2,3) AND c.queue IN (1,2,3,4)"
            if args.inclusion_mode == "active"
            else ""
        )
        base_sql = f"""
            SELECT c.id card_id,c.nid note_id,c.did,c.odid,c.ord,c.mod card_mod,
                   c.type card_type,c.queue,c.due,c.ivl,c.factor,c.reps,c.lapses,
                   c.left,c.odue,c.flags card_flags,c.data card_data,
                   n.guid,n.mid,n.mod note_mod,n.tags,n.flds,n.flags note_flags,
                   n.data note_data,? crt
              FROM cards c JOIN notes n ON n.id=c.nid
             WHERE (CASE WHEN c.odid>0 THEN c.odid ELSE c.did END) IN ({placeholders})
               AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id)
               {inclusion_predicate}
             ORDER BY c.id
        """
        rows = list(connection.execute(base_sql, (creation_seconds, *sorted(matching_decks))))
        history_by_card: dict[int, list[dict[str, Any]]] = {int(row["card_id"]): [] for row in rows}
        if history_by_card:
            ids = sorted(history_by_card)
            chunk_size = 800
            for start in range(0, len(ids), chunk_size):
                chunk = ids[start : start + chunk_size]
                markers = ",".join("?" for _ in chunk)
                for review in connection.execute(
                    f"SELECT id,cid,usn,ease,ivl,lastIvl,factor,time,type FROM revlog WHERE cid IN ({markers}) ORDER BY id",
                    chunk,
                ):
                    history_by_card[int(review["cid"])].append(review_entry(review))
        cards = [
            card_record(row, deck_names, note_type_names, field_names, history_by_card[int(row["card_id"])])
            for row in rows
        ]
        all_in_hierarchy = connection.execute(
            f"SELECT COUNT(*) FROM cards WHERE (CASE WHEN odid>0 THEN odid ELSE did END) IN ({placeholders})",
            tuple(sorted(matching_decks)),
        ).fetchone()[0]
        historical_reviewed_count = connection.execute(
            f"SELECT COUNT(*) FROM cards c WHERE (CASE WHEN c.odid>0 THEN c.odid ELSE c.did END) IN ({placeholders}) AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id)",
            tuple(sorted(matching_decks)),
        ).fetchone()[0]
        current_active_count = connection.execute(
            f"SELECT COUNT(*) FROM cards c WHERE (CASE WHEN c.odid>0 THEN c.odid ELSE c.did END) IN ({placeholders}) AND c.type IN (1,2,3) AND c.queue IN (1,2,3,4) AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid=c.id)",
            tuple(sorted(matching_decks)),
        ).fetchone()[0]
    finally:
        connection.close()
    if signature_before != file_signature(database):
        raise RuntimeError("The Anki collection changed during extraction. Close Anki and retry.")
    chosen = select_lesson_cards(cards, args.lesson_size) if cards else []
    tutor_policy = build_lexical_gate(cards, chosen)
    generated_at = dt.datetime.now().astimezone().isoformat()
    payload = {
        "metadata": {
            "workspace": "Nihongo Sensei",
            "generated_at": generated_at,
            "source_database": str(database),
            "source_access": "SQLite mode=ro, immutable=1, query_only=ON",
            "source_signature": {"size_bytes": signature_before[0], "mtime_ns": signature_before[1]},
            "deck_root": args.deck_root,
            "included_decks": sorted(normalized_deck_name(deck_names[did]) for did in matching_decks),
            "inclusion_mode": args.inclusion_mode,
            "corpus_label": "Current active-card corpus" if args.inclusion_mode == "active" else "Historical reviewed-card corpus",
            "included_card_count": len(cards),
            "reviewed_card_count": len(cards),
            "note_count": len({card["note_id"] for card in cards}),
            "review_event_count": sum(len(card["review_history"]) for card in cards),
            "current_active_card_count": int(current_active_count),
            "historical_reviewed_card_count": int(historical_reviewed_count),
            "currently_new_with_history_count": int(historical_reviewed_count) - int(current_active_count),
            "currently_new_with_history_excluded": (int(historical_reviewed_count) - int(current_active_count)) if args.inclusion_mode == "active" else 0,
            "never_reviewed_card_count": int(all_in_hierarchy) - int(historical_reviewed_count),
            "inclusion_rule": (
                "Effective deck is in hierarchy, revlog contains at least one row, current Anki card type is learning, review, or relearning, and the queue is a positive scheduled queue (not new, suspended, or buried)."
                if args.inclusion_mode == "active"
                else "Effective deck is in hierarchy and revlog contains at least one row, regardless of current Anki card type."
            ),
        },
        "planning_index": {
            "lesson_card_ids": [card["card_id"] for card in chosen],
            "weak_card_ids": [card["card_id"] for card in sorted(cards, key=lambda c: c["assessment"]["weakness"], reverse=True)],
            "strong_card_ids": [card["card_id"] for card in sorted(cards, key=lambda c: c["assessment"]["strength"], reverse=True)],
        },
        "tutor_policy": tutor_policy,
        "cards": cards,
    }
    return payload, chosen


def main() -> int:
    args = parse_args()
    try:
        payload, chosen = build(args)
        metadata = payload["metadata"]
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        if not args.summary_only:
            atomic_write(
                args.output_dir / "corpus.json",
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )
            atomic_write(args.output_dir / "lesson-brief.md", brief_markdown(payload, chosen))
            print(f"Wrote {args.output_dir / 'corpus.json'}")
            print(f"Wrote {args.output_dir / 'lesson-brief.md'}")
        return 0
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"Nihongo Sensei could not start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
