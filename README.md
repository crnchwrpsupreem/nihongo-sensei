# Nihongo Sensei Publisher

This repository turns a dedicated Windows or Linux mini PC with Anki into the source of truth for a ChatGPT Japanese tutor.

The learner reviews exclusively on their phone. The mini PC is not a study device: it mirrors the phone's progress through AnkiWeb, extracts the synced collection read-only, and publishes the tutor bundle.

## Current tutor status

<!-- nihongo-sensei-status:start -->
_Automatically refreshed by the mini-PC publisher. Do not edit inside these markers._

| Field | Current value |
| --- | --- |
| Status | **Ready** |
| Last generated | `2026-09-02T19:23:07.807856-04:00` |
| Reviewed cards available to the tutor | **100** |
| Currently active cards | **100** |
| Review events | **298** |
| Generation | `d55a900161bccf36` |
| Current bundle | [`tutor-data/current/`](tutor-data/current/) |
<!-- nihongo-sensei-status:end -->

The mini PC periodically:

1. Opens the configured Anki profile and downloads review activity that the phone has synced to AnkiWeb.
2. Closes Anki cleanly.
3. Reads the local SQLite collection in strict read-only mode.
4. Selects every card in the configured Japanese deck hierarchy that has been reviewed at least once.
5. Classifies cards as currently active or previously studied.
6. Generates a machine-readable tutor bundle under `tutor-data/current/`.
7. Refreshes the generated status block in this README.
8. Commits and pushes the bundle plus that status block to this public repository.

A ChatGPT Project uses the GitHub app to read that bundle before tutoring. Voice, conversation, and lesson delivery happen in ChatGPT itself. This repository contains **no local OpenAI API or Realtime voice application**.

## Published repository

`https://github.com/crnchwrpsupreem/nihongo-sensei`

## Privacy warning

This is a public repository. After the first successful publisher run, anyone can read the published card text, example sentences, tags, scheduling state, and review history. The publisher excludes credentials, source-machine paths, Anki media, and untouched cards, but it intentionally publishes the studied learning content.

If that is ever undesirable, make the repository private before running the publisher again.

## Common mini-PC requirements

- Python 3.11+.
- Git.
- Current desktop Anki installed from the official Anki package.
- The AnkiConnect add-on (`2055492159`) for scripted sync and clean shutdown.
- GitHub write authentication, preferably an SSH key.

AnkiConnect is used only to ask Anki to synchronize and exit. Card extraction never uses AnkiConnect and never writes to Anki.

Windows 10/11 is supported natively through PowerShell and Task Scheduler. The scheduled task runs in the user's interactive desktop session because Anki must be able to open. Keep that Windows account signed in (locking the screen is fine).

Linux remains supported through Bash and a systemd user timer. A headless Linux machine also needs `xvfb-run`.

## One-time setup

### 1. Install and initialize Anki

Install current Anki from `https://apps.ankiweb.net/`. Open it once, select the correct profile, sign in to AnkiWeb, complete the first sync, and verify the Japanese deck is present.

In Anki, install AnkiConnect:

1. **Tools → Add-ons → Get Add-ons**.
2. Enter code `2055492159`.
3. Restart Anki and confirm `http://127.0.0.1:8765` is reachable while Anki is open.

### 2. Clone and authenticate GitHub

```bash
git clone https://github.com/crnchwrpsupreem/nihongo-sensei.git
cd nihongo-sensei
```

The publisher must be able to push. Either authenticate GitHub CLI/Git Credential Manager on the mini PC, or create an SSH key and add it to GitHub as a write-enabled deploy key. For SSH:

```bash
git remote set-url origin git@github.com:crnchwrpsupreem/nihongo-sensei.git
ssh -T git@github.com
```

Set a commit identity regardless of the authentication method:

```bash
git config user.name "Nihongo Sensei Publisher"
git config user.email "nihongo-sensei@localhost"
```

No GitHub credential is stored in this repository. If GitHub CLI is installed, `gh auth login` followed by `gh auth setup-git` is also sufficient.

## Windows setup

Anki's profile is detected automatically under `%APPDATA%\Anki2\User 1`, and standard Anki installations are detected under `%LOCALAPPDATA%`.

### 3W. Create the Windows configuration

Open PowerShell in the cloned repository:

```powershell
$ConfigDir = Join-Path $env:APPDATA "nihongo-sensei"
New-Item -ItemType Directory -Force $ConfigDir
Copy-Item .\config.env.example (Join-Path $ConfigDir "config.env")
notepad (Join-Path $ConfigDir "config.env")
```

Normally only `NIHONGO_ANKI_PROFILE_NAME` and `NIHONGO_DECK_ROOT` need checking. Leave the profile and executable overrides commented unless Anki is installed somewhere unusual.

### 4W. Test Windows publishing

Close Anki and test extraction without syncing or pushing:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1 -NoSync -NoPush
```

Then test the complete AnkiWeb sync, extraction, and GitHub push:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1
```

### 5W. Install the adjustable Windows schedule

The default is every three hours:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 3h -RunNow
```

Other valid examples are `30min`, `6h`, and `1d`. Re-running the installer replaces the existing task with the new interval.

Inspect or manually run it with:

```powershell
Get-ScheduledTask -TaskName "Nihongo Sensei Publisher"
Get-ScheduledTaskInfo -TaskName "Nihongo Sensei Publisher"
Start-ScheduledTask -TaskName "Nihongo Sensei Publisher"
```

The Windows task deliberately uses `Interactive` logon type. It will not start Anki while the user is fully signed out.

## Linux setup

On a headless Debian/Ubuntu machine, install:

```bash
sudo apt install xvfb git python3 util-linux
```

### 3L. Configure the Linux Anki profile

```bash
mkdir -p "$HOME/.config/nihongo-sensei"
cp config.env.example "$HOME/.config/nihongo-sensei/config.env"
chmod 600 "$HOME/.config/nihongo-sensei/config.env"
```

Edit the file only if your profile or deck differs. Recent Anki versions normally store Linux profiles under:

```text
~/.local/share/Anki2/User 1
```

If `$XDG_DATA_HOME` is set, the base is `$XDG_DATA_HOME/Anki2` instead.

### 4L. Test once without pushing

Close Anki, then run:

```bash
./scripts/publish_update.sh --no-sync --no-push
```

That verifies extraction against the existing local collection. Then test the complete sync-and-publish path:

```bash
./scripts/publish_update.sh
```

### 5L. Install the adjustable schedule

The default is every three hours:

```bash
./scripts/install_systemd_user.sh --interval 3h
```

Other examples:

```bash
./scripts/install_systemd_user.sh --interval 30min
./scripts/install_systemd_user.sh --interval 6h
./scripts/install_systemd_user.sh --interval 1d
```

Run immediately or inspect status:

```bash
systemctl --user start nihongo-sensei.service
systemctl --user status nihongo-sensei.service
systemctl --user list-timers nihongo-sensei.timer
journalctl --user -u nihongo-sensei.service
```

For schedules to run while the user is logged out, the machine administrator may need to enable user lingering:

```bash
sudo loginctl enable-linger "$USER"
```

## What gets published

`tutor-data/current/manifest.json`
: Generation ID, timestamp, counts, hashes, and explicit privacy flags.

`tutor-data/current/voice-corpus.txt`
: Compact ordinary Voice source. It contains ordered FRESH, REINFORCE, and MATURE sentence entries plus a word-only inventory of other reviewed material. A text bootstrap reproduces this complete file into chat context before Voice begins.

`tutor-data/current/card-index.json`
: Compact index for every reviewed card, including current study state, scheduling summary, assessment scores, and the full-data shard name.

`tutor-data/current/cards-NNNN.json`
: Sharded complete card records: exact note fields, per-card allowed lexical/sentence material, current scheduling, assessment scores, and full review history. Untouched cards are excluded. Sharding lets the tutor fetch only the full records needed for a lesson.

`tutor-data/current/tutor-policy.json`
: Compact exercise rules, pacing, and turn-taking behavior. Exact allowed words and stored Japanese/English sentence pairs live with their cards in the shards.

`tutor-data/current/lesson-brief.md`
: Compact current counts and lesson priorities.

Cards are classified as:

- `currently_active`: Anki currently schedules the card as learning, review, or relearning.
- `previously_reviewed_currently_new`: The card has review history but is currently reset/marked new.
- `previously_reviewed_inactive`: The card has review history but is suspended or buried.
- `previously_reviewed`: Any other reviewed state.

This phrasing captures “currently studying or previously studied” while still excluding every untouched card.

## ChatGPT Project setup

1. Create a private ChatGPT Project named **Nihongo Sensei**.
2. Connect the GitHub app in ChatGPT and ensure it can access `crnchwrpsupreem/nihongo-sensei`.
3. Open Project settings and paste the complete contents of [`CHATGPT_PROJECT_INSTRUCTIONS.md`](CHATGPT_PROJECT_INSTRUCTIONS.md).
4. Start a project chat in text and say **“Load tutor corpus for voice.”**
5. Wait for the complete compact corpus to be reproduced into the chat, then switch to Voice and say **“Begin practice.”**

The tutor must report the loaded `generation_id` and card counts before the first exercise. If the GitHub app is unavailable, the instructions include public raw-file fallbacks.

## For maintainers and coding agents

### Agent quick navigation

- Start with [`AGENTS.md`](AGENTS.md) for repository invariants and safety boundaries.
- Follow [`.agents/skills/nihongo-sensei/SKILL.md`](.agents/skills/nihongo-sensei/SKILL.md) for publisher or tutor workflows.
- Use [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md) for architecture, data flow, and component ownership.
- Use [`CHATGPT_PROJECT_INSTRUCTIONS.md`](CHATGPT_PROJECT_INSTRUCTIONS.md) for the copy-ready tutor contract.
- Inspect [`tutor-data/current/manifest.json`](tutor-data/current/manifest.json) first for live readiness, counts, generation identity, and bundle hashes.
- Use [`tutor-data/current/voice-corpus.txt`](tutor-data/current/voice-corpus.txt) as the ordinary Voice tutoring source.
- Run or modify orchestration through [`scripts/publish_update.py`](scripts/publish_update.py); the PowerShell and Bash files are thin platform wrappers.

The status table near the top of this README is generated. Its marker-delimited body may change on every publisher run; this navigation section is static and should be maintained manually.

Read [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md), [`AGENTS.md`](AGENTS.md), and [`.agents/skills/nihongo-sensei/SKILL.md`](.agents/skills/nihongo-sensei/SKILL.md) before changing behavior.

Verify changes with:

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/publish_update.sh scripts/install_systemd_user.sh
```

On Windows, the equivalent publisher entry point is `scripts\publish_update.ps1`, and scheduling is installed by `scripts\install_windows_task.ps1`. Both wrappers invoke the same cross-platform `scripts/publish_update.py` controller.

The generated private extraction in `work/current-session/` is ignored by Git. Credentials and `.env` files are ignored. Only the intentionally public bundle and the generated README status block are staged by the publishing script.

GitHub Actions runs the Python suite on both Windows and Linux and validates the native PowerShell/Bash entry points on every push and pull request.
