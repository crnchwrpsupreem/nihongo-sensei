# Agent handoff: Nihongo Sensei Publisher

## Objective

Keep a public, current, machine-readable snapshot of the learner's reviewed Japanese Anki material so a ChatGPT Project can tutor from the exact learned corpus.

## Data flow

```text
AnkiWeb
  ↓ Anki desktop sync (AnkiConnect triggers sync and clean exit)
Mini-PC Anki profile
  ↓ strict read-only SQLite extraction
work/current-session/corpus.json (private, gitignored)
  ↓ sanitizing/classifying exporter
tutor-data/current/* (intentional public learning data)
  ↓ git commit + push
GitHub repository
  ↓ GitHub app or raw public files
ChatGPT Project voice/text tutor
```

## Components

- `.agents/skills/nihongo-sensei/scripts/build_session.py`: source-of-truth extractor. It refuses live WAL/SHM/lock state, verifies the database signature, and never writes to Anki.
- `scripts/sync_anki.py`: finds and starts Anki on Windows/Linux when necessary, invokes AnkiConnect `sync`, then requests a clean Anki exit. It does not read or edit cards.
- `scripts/export_tutor_bundle.py`: adds study-state classifications, writes a compact card index plus full-data shards containing per-card `tutor_material`, and publishes only machine-independent learning data.
- `scripts/publish_update.py`: cross-platform controller that locks the run, optionally pulls code, syncs, extracts in `historical` mode, exports, tests, commits only `tutor-data/current`, and pushes.
- `scripts/publish_update.sh` and `scripts/publish_update.ps1`: thin Linux and Windows entry points for the same controller.
- `scripts/install_systemd_user.sh`: installs an adjustable systemd user timer.
- `scripts/install_windows_task.ps1`: installs an adjustable interactive Windows Task Scheduler job.
- `CHATGPT_PROJECT_INSTRUCTIONS.md`: canonical copy-ready tutor behavior.

## Inclusion semantics

The publisher uses historical mode: effective deck is the configured Japanese root or a descendant, and `revlog` contains at least one entry. This includes current learning/review/relearning cards and any previously studied card that is now new, suspended, buried, or otherwise inactive. It excludes untouched cards.

The exporter adds a `study_state` rather than flattening these categories. Lesson priority is current active material first, then historical maintenance.

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
