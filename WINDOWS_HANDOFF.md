# Nihongo Sensei — Windows mini-PC handoff

This document contains everything needed to move the Nihongo Sensei publisher to the Windows mini PC and connect it to a ChatGPT Project.

## What this system does

The Windows mini PC becomes the source of truth for Japanese tutoring:

1. It opens the configured Anki profile.
2. It asks Anki to synchronize with AnkiWeb through AnkiConnect.
3. It closes Anki cleanly.
4. It opens `collection.anki2` with strict read-only SQLite settings.
5. It selects Japanese-deck cards that have at least one review-history entry.
6. It excludes cards that have never been studied.
7. It distinguishes currently active cards from previously studied cards.
8. It generates a sanitized tutor bundle.
9. It commits and pushes that bundle to the public GitHub repository.
10. A ChatGPT Project reads the current bundle before starting a lesson.

The repository does not contain a local OpenAI API client, Realtime voice server, microphone application, or API key. Voice tutoring happens inside ChatGPT.

## Important links

- Repository: https://github.com/crnchwrpsupreem/nihongo-sensei
- Main setup guide: https://github.com/crnchwrpsupreem/nihongo-sensei#readme
- ChatGPT Project instructions: https://github.com/crnchwrpsupreem/nihongo-sensei/blob/main/CHATGPT_PROJECT_INSTRUCTIONS.md
- Windows/Linux CI: https://github.com/crnchwrpsupreem/nihongo-sensei/actions
- Verified Windows-support commit: https://github.com/crnchwrpsupreem/nihongo-sensei/commit/18ede53a49d950b9db88a3e19d990e999fa700cf

## Public-data warning

The repository is public. After the first successful publisher run, it will intentionally expose:

- Studied card text and tags
- Example sentences and stored meanings
- Current scheduling state
- Review history
- Tutor whitelists and lesson metadata

It excludes:

- Untouched cards
- Anki media
- Anki configuration databases
- Source-machine paths
- GitHub credentials
- AnkiWeb credentials
- OpenAI credentials

If this learning data should not be public, make the repository private before the first publisher run.

## Windows mini-PC requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Git for Windows
- Current desktop Anki
- AnkiConnect add-on `2055492159`
- GitHub authentication that permits pushes to `crnchwrpsupreem/nihongo-sensei`
- A Windows user account that remains signed in

The screen may be locked, but the user must remain signed in. The scheduled task uses an interactive desktop session because Anki is a GUI application.

## Step 1: Install and prepare Anki

1. Install Anki from https://apps.ankiweb.net/.
2. Open Anki normally.
3. Select or create the correct profile—normally `User 1`.
4. Sign in to AnkiWeb.
5. Perform one complete manual synchronization.
6. Confirm the Japanese deck is present.
7. In Anki, open **Tools → Add-ons → Get Add-ons**.
8. Enter AnkiConnect code `2055492159`.
9. Restart Anki.

The publisher expects AnkiConnect at `http://127.0.0.1:8765` while Anki is running.

Anki's standard Windows profile path is detected automatically:

```text
%APPDATA%\Anki2\User 1
```

## Step 2: Install Python, Git, and optionally GitHub CLI

Install Python 3 and Git for Windows. During Python installation, enable the option that makes Python available from the command line.

GitHub CLI is optional but convenient. If it is installed, authenticate with:

```powershell
gh auth login
gh auth setup-git
```

Alternatively, use Git Credential Manager or a write-enabled SSH key.

## Step 3: Clone the repository

Open PowerShell in the directory where the project should live:

```powershell
git clone https://github.com/crnchwrpsupreem/nihongo-sensei.git
cd nihongo-sensei
git config user.name "Nihongo Sensei Publisher"
git config user.email "nihongo-sensei@localhost"
```

Confirm that Git can reach the repository:

```powershell
git pull
```

## Step 4: Create the local configuration

From the repository directory:

```powershell
$ConfigDir = Join-Path $env:APPDATA "nihongo-sensei"
New-Item -ItemType Directory -Force $ConfigDir
Copy-Item .\config.env.example (Join-Path $ConfigDir "config.env")
notepad (Join-Path $ConfigDir "config.env")
```

The defaults normally need no path changes. Check these values:

```text
NIHONGO_ANKI_PROFILE_NAME="User 1"
NIHONGO_DECK_ROOT="日本語"
NIHONGO_ANKI_CONNECT_URL="http://127.0.0.1:8765"
NIHONGO_SYNC_TIMEOUT="300"
NIHONGO_CLOSE_ANKI_AFTER_SYNC="true"
NIHONGO_GIT_REMOTE="origin"
NIHONGO_GIT_BRANCH="main"
```

Leave `NIHONGO_ANKI_PROFILE` and `NIHONGO_ANKI_COMMAND` commented out unless the profile or Anki installation is in a nonstandard location.

Example overrides:

```text
NIHONGO_ANKI_PROFILE="C:/Users/your-name/AppData/Roaming/Anki2/User 1"
NIHONGO_ANKI_COMMAND="C:/Users/your-name/AppData/Local/Programs/Anki/anki.exe"
```

Use forward slashes in paths inside `config.env`.

## Step 5: Test read-only extraction

First synchronize Anki manually and close it. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1 -NoSync -NoPush
```

This test must:

- Locate the Anki collection
- Refuse to continue if Anki still has a live database lock or SQLite sidecar
- Read the collection without modifying it
- Include reviewed Japanese cards
- Exclude untouched cards
- Generate local tutor data
- Pass the test suite
- Avoid pushing anything to GitHub

If this fails because Anki is open, close Anki completely and retry.

## Step 6: Test the complete pipeline

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1
```

The complete pipeline should:

1. Pull the latest repository version.
2. Open Anki if necessary.
3. Synchronize through AnkiConnect.
4. Close Anki.
5. Extract the reviewed Japanese corpus read-only.
6. Generate `tutor-data/current/`.
7. Run tests.
8. Commit only the generated public tutor data.
9. Push the new generation to GitHub.

After this first successful run, `tutor-data/current/manifest.json` should change from `"ready": false` to `"ready": true`.

## Step 7: Install the adjustable schedule

Install the default three-hour schedule:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 3h -RunNow
```

Other examples:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 30min
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 6h
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 1d
```

Re-running the installer replaces the existing task with the new interval.

Inspect or run the task manually:

```powershell
Get-ScheduledTask -TaskName "Nihongo Sensei Publisher"
Get-ScheduledTaskInfo -TaskName "Nihongo Sensei Publisher"
Start-ScheduledTask -TaskName "Nihongo Sensei Publisher"
```

The task name is `Nihongo Sensei Publisher`.

## What the repository publishes

The current generation is stored under `tutor-data/current/`:

- `manifest.json`: generation ID, timestamps, counts, hashes, and privacy declarations
- `lesson-brief.md`: compact lesson priorities and corpus counts
- `tutor-policy.json`: tutoring rules, pacing, and turn-taking behavior
- `card-index.json`: compact index of all published reviewed cards
- `cards-NNNN.json`: on-demand shards containing full reviewed-card data and exact tutor material

The tutor loads the compact files first and retrieves only the card shards required for the current lesson.

Card states are classified as:

- `currently_active`: learning, review, or relearning cards that Anki currently schedules
- `previously_reviewed_currently_new`: reviewed cards that are now reset or marked new
- `previously_reviewed_inactive`: reviewed cards that are suspended or buried
- `previously_reviewed`: other cards with review history

All four categories are previously studied. Cards with no review-history entry are excluded.

## ChatGPT Project setup

1. Create a private ChatGPT Project named **Nihongo Sensei**.
2. Connect the GitHub app to `crnchwrpsupreem/nihongo-sensei`.
3. Open this repository file:
   `CHATGPT_PROJECT_INSTRUCTIONS.md`
4. Copy its complete contents into the Project's custom instructions.
5. Start a text or voice chat inside that Project.
6. Say: **Start Japanese tutor mode**.

The Project instructions require the tutor to:

- Refresh the GitHub tutor bundle first
- Report the generation ID and card counts before teaching
- Refuse to invent a lesson if the bundle is unavailable or not ready
- Prioritize currently active cards
- Use historical material for maintenance
- Keep instructions and corrections in English
- Quote only exact stored Japanese words, sentences, or literal sentence chunks
- Never compose new Japanese from individually known words
- Use sentence-first active recall
- Assess each answer before immediately giving exactly one next exercise
- Speak Japanese modestly slower than English

## Manual refresh command

To refresh Anki and publish immediately instead of waiting for Task Scheduler:

```powershell
cd path\to\nihongo-sensei
powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1
```

Then tell the ChatGPT Project:

```text
Refresh tutor data
```

## Troubleshooting

### Python is not found

Install Python 3 and make sure either `py -3` or `python` works in PowerShell:

```powershell
py -3 --version
python --version
```

### AnkiConnect does not respond

- Confirm add-on `2055492159` is installed.
- Restart Anki.
- Confirm the correct Anki profile opens.
- Verify that no firewall or AnkiConnect configuration blocks `127.0.0.1:8765`.

### The collection is locked

The extractor deliberately refuses to read the database while Anki is using it. Let the sync script close Anki, or close it manually before a `-NoSync` test.

### Anki cannot be found

Uncomment `NIHONGO_ANKI_COMMAND` in `%APPDATA%\nihongo-sensei\config.env` and give it the full path to `anki.exe`.

### The wrong profile or deck is selected

Update these fields in the configuration:

```text
NIHONGO_ANKI_PROFILE_NAME="User 1"
NIHONGO_DECK_ROOT="日本語"
```

If necessary, also set the full `NIHONGO_ANKI_PROFILE` path.

### Git cannot push

Check authentication and commit identity:

```powershell
gh auth status
git remote -v
git config user.name
git config user.email
git push
```

### The scheduled task does not run

- Keep the Windows user signed in.
- Check Task Scheduler history.
- Run `Get-ScheduledTaskInfo -TaskName "Nihongo Sensei Publisher"`.
- Run the PowerShell publisher manually and resolve any displayed error.
- Confirm Git credentials are available to the same Windows user.

### The ChatGPT tutor says the bundle is not ready

Run the publisher on the mini PC and confirm that the public `manifest.json` contains `"ready": true`.

## Safety invariants for another coding agent

If another agent modifies this system, it must preserve these rules:

1. The extractor never writes to Anki.
2. SQLite remains `mode=ro`, `immutable=1`, and `query_only=ON`.
3. The extractor refuses live WAL, SHM, or lock state.
4. Untouched cards remain excluded.
5. Currently active and previously studied cards remain distinguishable.
6. Public outputs exclude credentials, media, and source-machine paths.
7. Only `tutor-data/current/` is automatically staged by the publisher.
8. Windows and Linux wrappers use the same `scripts/publish_update.py` controller.
9. Windows scheduling stays interactive so Anki can open safely.
10. No local OpenAI API, Realtime, microphone, or voice application is added.

Before changing repository behavior, an agent should read:

- `AGENTS.md`
- `AGENT_HANDOFF.md`
- `.agents/skills/nihongo-sensei/SKILL.md`
- `CHATGPT_PROJECT_INSTRUCTIONS.md`

Run verification with:

```powershell
python -m unittest discover -s tests -v
```

The repository's GitHub Actions workflow also tests Windows and Linux on every push and pull request.
