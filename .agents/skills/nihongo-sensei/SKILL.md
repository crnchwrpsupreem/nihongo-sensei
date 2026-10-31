---
name: nihongo-sensei
description: Maintain or consume the Nihongo Sensei Windows/Linux mini-PC Anki publisher and run sentence-first Japanese tutoring from its current public GitHub tutor bundle. Use when asked to refresh/publish Anki tutor data, configure the mini-PC schedule, inspect the reviewed Japanese corpus, or start Japanese tutor mode.
---

# Nihongo Sensei Publisher and Tutor

## Choose the workflow

- On the mini PC or in repository-maintenance work, follow **Publisher workflow**.
- In a ChatGPT/Codex tutoring conversation, follow **Tutor workflow**.
- Never add a local OpenAI API, Realtime, microphone, speech, or model-driven lesson application. Voice belongs to ChatGPT Project voice.

## Publisher workflow

The learner reviews exclusively on their phone. Treat the mini PC as a non-interactive AnkiWeb mirror and publishing appliance: never expect or request local reviews. New review activity reaches the publisher only after the phone syncs to AnkiWeb and the mini PC completes step 1 below.

1. Synchronize through Anki itself using `scripts/sync_anki.py`. AnkiConnect may trigger only `sync`, `version`, and `guiExitAnki`; do not use it to read or edit cards.
2. After Anki closes, run the extractor in historical mode:

   ```bash
   python3 .agents/skills/nihongo-sensei/scripts/build_session.py \
     --profile "$NIHONGO_ANKI_PROFILE" \
     --deck-root "${NIHONGO_DECK_ROOT:-日本語}" \
     --inclusion-mode historical \
     --output-dir work/current-session
   ```

3. The extractor must keep SQLite `mode=ro&immutable=1` and `query_only=ON`, refuse live WAL/SHM/lock state, and verify the source signature did not change.
4. Run `scripts/export_tutor_bundle.py` to sanitize machine-specific metadata, classify every reviewed card, and refresh only the marker-delimited generated status block in `README.md`.
5. Publish only `tutor-data/current/` and `README.md`. The controller must refuse unrelated staged paths. Never stage `work/current-session`, Anki files, media, configuration databases, credentials, or environment files.
6. `scripts/publish_update.py` is the canonical cross-platform controller. Use `scripts/publish_update.ps1` on Windows or `scripts/publish_update.sh` on Linux.
7. Windows scheduling uses `scripts/install_windows_task.ps1 -Interval 3h` in an interactive logged-in user session. Linux scheduling uses `scripts/install_systemd_user.sh --interval 3h`.

### Complete game catalog exception

Explicitly authorized public kaishi-game-catalog.json contains all 1500 cards from exactly 日本語::Kaishi 1.5k, one-to-one by stable card ID. Include only word/reading/meaning/example/translation and minimal eligibility; never media or other decks. Its own manifest covers hashes and counts. Reviewed tutor export behavior and full Voice workflow are unchanged.

### Inclusion rule

Publish a card only when its effective deck is the configured Japanese root or a descendant and it has at least one `revlog` row. This includes current learning/review/relearning cards and previously studied cards that are now new, suspended, buried, or otherwise inactive. Exclude untouched cards.

Preserve `study_state`:

- `currently_active`
- `previously_reviewed_currently_new`
- `previously_reviewed_inactive`
- `previously_reviewed`

### Public-data boundary

The repository is intentionally public and may contain exact reviewed-card text, tags, scheduling state, and review history. It must not contain credentials, source-machine paths, Anki media, or untouched cards. Keep `manifest.json` privacy flags truthful.

## Tutor workflow

Follow `CHATGPT_PROJECT_INSTRUCTIONS.md`, the canonical focused-session instructions.
Read the manifest and `voice-session.txt` only for ordinary Voice lessons. Verify readiness and print the complete focused TXT verbatim in the initial TEXT reply before Voice, including all targets, kana readings, meanings, examples, translations and session rules. Stop without an exercise until the learner says Begin in Voice. Do not substitute a link or retrieval confirmation.

Freeze the session ID and three targets (maximum five only by explicit configuration). Lead calm audio-only coaching, assess each answer before one next prompt, and allow repeat/explain/easier/recap/pause, silence and interruptions. Recap automatically after interruption or drift. No generated Japanese variations, target expansion, exact whole-sentence production requirement, timers, scores or rewards. Use English explanations and kana; romaji only on request. Stop rather than invent missing session context.

The full card shards, index, and legacy voice-corpus remain intact for other consumers; do not load their broad vocabulary into this focused lesson.
