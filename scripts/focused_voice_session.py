"""Small, deterministic Voice session; independent of the full game export."""
from __future__ import annotations

import hashlib
import json
import unicodedata


def text(card, name):
    return card.get("note", {}).get("fields", {}).get(name, {}).get("text", "").strip()


def reviews(card):
    return sorted((h for h in card.get("review_history", [])
                   if h.get("rating", {}).get("raw") in (1, 2, 3, 4)
                   and h.get("review_type", {}).get("raw", 1) in (0, 1, 2, 3)),
                  key=lambda h: int(h["review_id"]))


def rank(card):
    history = reviews(card)
    tail = history[-5:]
    return (history[-1]["rating"]["raw"] == 1,
            sum(h["rating"]["raw"] == 1 for h in tail),
            sum(h["rating"]["raw"] == 2 for h in tail),
            int(card["scheduling"].get("lapses", 0)),
            int(history[-1]["review_id"]), -int(card["card_id"]))


COACHING = (
    "Freeze these targets for the entire call. Lead calm audio-only coaching for roughly "
    "20–30 minutes of useful practice; do not time, pad, score, or check rewards. "
    "Use English explanations and clear Japanese; kana readings, no romaji unless requested. "
    "Assess the previous answer, explain the specific misunderstanding, then give one next "
    "spoken prompt and wait. Alternate target meaning, recall, pronunciation, and supported "
    "listening. Translate incidental words in the exact examples without adding targets. "
    "Do not require exact whole-sentence production or generate Japanese variations. "
    "Repeat = slower same prompt; explain = brief English help; easier = hint or two spoken "
    "options; recap = targets and current point; pause = stop questions until resumed. "
    "Allow silence and interruptions. On resumption or drift, recap these targets and the "
    "last unresolved point automatically. Do not require a screen or learner direction. "
    "If this printed pack is unavailable, stop rather than invent. End with progress and "
    "remaining confusion, not a claim of lasting mastery."
)


def build_session(cards, source_generation, exported_at, limit=3):
    if type(limit) is not int or not 3 <= limit <= 5:
        raise ValueError("Voice session size must be 3–5 (default 3)")
    required = ("Word", "Word Reading", "Word Meaning", "Sentence", "Sentence Meaning")
    candidates = [c for c in cards if c.get("study_state") == "currently_active"
                  and reviews(c) and all(text(c, f) for f in required)]
    targets, seen = [], set()
    for card in sorted(candidates, key=rank, reverse=True):
        key = tuple(unicodedata.normalize("NFKC", text(card, f)).strip()
                    for f in ("Word", "Word Reading"))
        if key in seen:
            continue
        seen.add(key)
        history = reviews(card)
        tail = history[-5:]
        again, hard = (sum(h["rating"]["raw"] == rating for h in tail) for rating in (1, 2))
        lapses = int(card["scheduling"].get("lapses", 0))
        if not (again or hard or lapses):
            continue
        targets.append({
            "card_id": card["card_id"], "note_id": card["note_id"],
            "word": text(card, "Word"), "reading": text(card, "Word Reading"),
            "meaning": text(card, "Word Meaning"),
            "example": text(card, "Sentence"), "translation": text(card, "Sentence Meaning"),
            "reason": {"attempts_counted": len(tail), "again": again, "hard": hard,
                       "lapses": lapses, "last_rating": history[-1]["rating"]["name"],
                       "last_reviewed_at": history[-1]["reviewed_at"]},
        })
        if len(targets) == limit:
            break
    all_reviews = [h for c in cards for h in reviews(c)]
    latest = max(all_reviews, key=lambda h: int(h["review_id"]))["reviewed_at"] if all_reviews else None
    identity = {"selection_version": 1, "requested_targets": limit, "targets": targets,
                "coaching": COACHING}
    session_id = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {"schema_version": 1, "ready": len(targets) == limit,
            "session_id": session_id, "source_generation": source_generation,
            "exported_at": exported_at, "latest_recorded_review_at": latest,
            **identity}


def session_text(session):
    lines = ["FOCUSED VOICE SESSION", f"Session: {session['session_id']}",
             f"Source generation: {session['source_generation']}",
             f"Exported: {session['exported_at']}",
             f"Latest recorded review in source: {session['latest_recorded_review_at']}",
             "Export freshness is not the date of study; difficulty describes recorded attempts."]
    if not session["ready"]:
        lines += ["NOT READY: insufficient complete, distinct difficulty targets. Do not start or invent a lesson."]
    for i, t in enumerate(session["targets"], 1):
        r = t["reason"]
        lines += ["", f"{i}. {t['word']} — {t['reading']} — {t['meaning']}",
                  f"Exact example: {t['example']}", f"English: {t['translation']}",
                  f"Recorded evidence: {r['again']} Again and {r['hard']} Hard in last {r['attempts_counted']} attempts; "
                  f"{r['lapses']} lapses. Last answer {r['last_rating']} on {r['last_reviewed_at']}."]
    lines += ["", "SESSION RULES", session["coaching"]]
    return "\n".join(lines) + "\n"
