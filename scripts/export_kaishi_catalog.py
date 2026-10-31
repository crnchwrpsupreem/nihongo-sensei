"""Read-only, one-card/one-question Kaishi catalog, separate from tutor data."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
from pathlib import Path
try:
    from .export_tutor_bundle import atomic_write, json_text
except ImportError:
    from export_tutor_bundle import atomic_write, json_text

DECK = "日本語::Kaishi 1.5k"
FIELDS = {"Word": "word", "Word Reading": "reading", "Word Meaning": "meaning",
          "Sentence": "sentence", "Sentence Meaning": "sentence_meaning"}


def plain(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def signature(path):
    return (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


def build_catalog(database, deck=DECK):
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(database) + suffix).exists():
            raise RuntimeError("Live SQLite sidecar present; refusing extraction")
    before = signature(database)
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    try:
        matches = [r["id"] for r in conn.execute("SELECT id,name FROM decks")
                   if r["name"].replace("\x1f", "::") == deck]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one configured Kaishi deck")
        fields = {}
        for r in conn.execute("SELECT ntid,ord,name FROM fields"):
            fields.setdefault(r["ntid"], {})[r["ord"]] = r["name"]
        rows = conn.execute("""SELECT c.id,c.nid,c.ord,c.type,c.queue,c.ivl,n.mid,n.flds
            FROM cards c JOIN notes n ON n.id=c.nid
            WHERE CASE WHEN c.odid>0 THEN c.odid ELSE c.did END=? ORDER BY c.id""", (matches[0],)).fetchall()
        if len(rows) != 1500:
            raise RuntimeError(f"Expected 1500 Kaishi cards; found {len(rows)}")
        cards = []
        for position, row in enumerate(rows, 1):
            values = {fields[row["mid"]][i]: plain(value)
                      for i, value in enumerate(row["flds"].split("\x1f")) if i in fields[row["mid"]]}
            if any(not values.get(name) for name in FIELDS):
                raise RuntimeError(f"Missing required text for card {row['id']}")
            last = conn.execute("""SELECT ease FROM revlog WHERE cid=? AND type IN (0,1,2,3)
                AND ease IN (1,2,3,4) ORDER BY id DESC LIMIT 1""", (row["id"],)).fetchone()
            rating = last[0] if last else None
            cards.append({"card_id": row["id"], "note_id": row["nid"], "template_ordinal": row["ord"],
                          "ordinal": position, "position": position, "test_number": (position - 1) // 100 + 1,
                          **{key: values[name] for name, key in FIELDS.items()},
                          "eligibility": {"eligible": row["type"] == 2 and row["queue"] == 2
                                          and row["ivl"] >= 21 and rating in (2,3,4),
                                          "card_type": row["type"], "queue": row["queue"],
                                          "interval_days": row["ivl"], "last_scheduled_rating": rating}})
    finally:
        conn.close()
    if signature(database) != before:
        raise RuntimeError("Collection changed during read-only extraction")
    blocks = []
    for number in range(1, 16):
        subset = cards[(number-1)*100:number*100]
        blocks.append({"test_number": number, "first_position": (number-1)*100+1,
                       "last_position": number*100, "card_count": 100,
                       "eligible_count": sum(c["eligibility"]["eligible"] for c in subset),
                       "all_cards_eligible": all(c["eligibility"]["eligible"] for c in subset),
                       "previous_test_required": number-1 if number>1 else None})
    return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "deck": deck, "card_count": len(cards), "deduplicated": False,
            "order": "Ascending stable Anki card ID (creation/import sequence), never current due-date order",
            "eligible_card_count": sum(c["eligibility"]["eligible"] for c in cards),
            "eligibility_rule": "Active review card, interval >=21 days, latest scheduled rating Hard/Good/Easy",
            "unlock_rule": "All 100 cards in a block eligible AND previous test passed; first block has no predecessor. Pass state belongs to the game, not this catalog.",
            "attribution": {"title": "Kaishi 1.5k", "source": "https://github.com/donkuri/Kaishi",
                            "credits": "https://github.com/donkuri/Kaishi#credits",
                            "authors": "Kaishi contributors, including 栗 and Tyogin; see source credits",
                            "upstream_sentence_sources": "Various Core decks on AnkiWeb, as credited by Kaishi",
                            "affiliation": "Independent personal game catalog; not affiliated with or endorsed by Kaishi creators",
                            "license_note": "No explicit license was identified in the upstream repository README/tree; no license grant is asserted here."},
            "privacy": {"contains_all_kaishi_card_text": True, "contains_other_decks": False,
                        "contains_media": False, "contains_review_history": False,
                        "contains_minimal_scheduling_eligibility": True},
            "blocks": blocks, "cards": cards}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = build_catalog(args.profile / "collection.anki2")
    path = args.output / "kaishi-game-catalog.json"
    atomic_write(path, json_text(catalog))
    manifest = {"schema_version": 1, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size, "generated_at": catalog["generated_at"],
                "card_count": catalog["card_count"], "eligible_card_count": catalog["eligible_card_count"],
                "test_count": 15, "cards_per_test": 100}
    atomic_write(args.output / "kaishi-game-manifest.json", json_text(manifest))
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
