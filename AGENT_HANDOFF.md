# Agent handoff: Nihongo Sensei Publisher

## Objective

Keep a public, current, machine-readable snapshot of the learner's reviewed Japanese Anki material so a ChatGPT Project can tutor from the exact learned corpus.

## Data flow

```text
Phone Anki (the learner's only review client)
  ↓ phone sync
AnkiWeb
  ↓ Anki desktop sync (AnkiConnect triggers sync and clean exit)
Mini-PC Anki profile (mirror/publisher only; no local reviewing)
  ↓ strict read-only SQLite extraction
work/current-session/corpus.json (private, gitignored)
  ↓ sanitizing/classifying exporter
tutor-data/current/* (intentional public learning data)
  + generated README status block (sanitized manifest statistics only)
  ↓ git commit + push
GitHub repository
  ↓ GitHub app or raw public files
ChatGPT Project voice/text tutor
```

Do not diagnose missing reviews by waiting for activity on the mini PC. The learner never reviews there. Confirm the phone has synced to AnkiWeb, then run the mini-PC sync before inspecting or publishing the local collection.

## Components

- `.agents/skills/nihongo-sensei/scripts/build_session.py`: source-of-truth extractor. It refuses live WAL/SHM/lock state, verifies the database signature, and never writes to Anki.
- `scripts/sync_anki.py`: finds and starts Anki on Windows/Linux when necessary, invokes AnkiConnect `sync`, then requests a clean Anki exit. It does not read or edit cards.
- `scripts/export_tutor_bundle.py`: adds study-state classifications, writes a compact card index plus full-data shards containing per-card `tutor_material`, and refreshes the marker-delimited README status block from the sanitized manifest.
- `scripts/publish_update.py`: cross-platform controller that locks the run, optionally pulls code, syncs, extracts in `historical` mode, exports, tests, commits only `tutor-data/current` plus `README.md`, and pushes. It refuses unrelated staged paths.
- `scripts/publish_update.sh` and `scripts/publish_update.ps1`: thin Linux and Windows entry points for the same controller.
- `scripts/install_systemd_user.sh`: installs an adjustable systemd user timer.
- `scripts/install_windows_task.ps1`: installs an adjustable interactive Windows Task Scheduler job.
- `CHATGPT_PROJECT_INSTRUCTIONS.md`: canonical copy-ready tutor behavior.

## Inclusion semantics

The publisher uses historical mode: effective deck is the configured Japanese root or a descendant, and `revlog` contains at least one entry. This includes current learning/review/relearning cards and any previously studied card that is now new, suspended, buried, or otherwise inactive. It excludes untouched cards.

The exporter adds a `study_state` rather than flattening these categories. Lesson priority is current active material first, then historical maintenance.

## Tutor progression semantics

Exact-card coverage is corpus-wide and grows with the active corpus. The tutor works in rotating batches, but must not mistake completion of one batch for completion of the active corpus. Each stored sentence requires two separate Phase 1 checks: meaning comprehension and exact Japanese recall. Only that sentence becomes eligible for controlled transfer after both checks pass.

Before half of the active sentence corpus has passed both checks, lessons are exact-card-only. From 50% through 79% coverage, controlled transfer is capped at 20% of exercises. At 80% or greater coverage, it is capped at 40%. Untested and newly active cards always take priority. Controlled transfer changes exactly one reviewed lexical item while preserving the source sentence's structure, particles, inflection, and politeness, and labels the result as generated rather than stored Anki material.

The bundle does not persist tutor-answer state. The ChatGPT Project maintains the coverage ledger in conversation/project context; when reliable prior coverage cannot be recovered, the tutor treats affected active sentences as unverified rather than assuming mastery.

## Public/private boundary

Private and ignored:

- `work/current-session/corpus.json`
- local Anki paths/signatures
- credentials, `.env`, profile preferences, media

Public by explicit design:

- note fields and tags for reviewed cards
- scheduling state and assessment scores
- review events
- exact tutor whitelists and sentence pairs

Do not weaken the manifest's privacy declaration or silently add new data classes.

## Testing

Run:

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/publish_update.sh scripts/install_systemd_user.sh
```

Windows defaults and PowerShell entry points have static regression coverage in `tests/test_platform_support.py`. If PowerShell is available in the development environment, also parse or run the scripts there.

The tests must not require Anki, AnkiConnect, GitHub credentials, or network access.
