# Nihongo Sensei Publisher

This repository turns a dedicated Linux mini PC with Anki into the source of truth for a ChatGPT Japanese tutor.

The mini PC periodically:

1. Opens the configured Anki profile and synchronizes it with AnkiWeb.
2. Closes Anki cleanly.
3. Reads the local SQLite collection in strict read-only mode.
4. Selects every card in the configured Japanese deck hierarchy that has been reviewed at least once.
5. Classifies cards as currently active or previously studied.
6. Generates a machine-readable tutor bundle under `tutor-data/current/`.
7. Commits and pushes that bundle to this public repository.

A ChatGPT Project uses the GitHub app to read that bundle before tutoring. Voice, conversation, and lesson delivery happen in ChatGPT itself. This repository contains **no local OpenAI API or Realtime voice application**.

## Published repository

`https://github.com/crnchwrpsupreem/nihongo-sensei`

## Privacy warning

This is a public repository. After the first successful publisher run, anyone can read the published card text, example sentences, tags, scheduling state, and review history. The publisher excludes credentials, source-machine paths, Anki media, and untouched cards, but it intentionally publishes the studied learning content.

If that is ever undesirable, make the repository private before running the publisher again.

## Mini-PC requirements

- A systemd-based Linux distribution.
- Python 3.11+.
- Git.
- `flock` (normally provided by `util-linux`).
- Current desktop Anki installed from the official Anki package.
- The AnkiConnect add-on (`2055492159`) for scripted sync and clean shutdown.
- `xvfb-run` when the mini PC has no desktop display.
- GitHub write authentication, preferably an SSH key.

AnkiConnect is used only to ask Anki to synchronize and exit. Card extraction never uses AnkiConnect and never writes to Anki.

## One-time setup

### 1. Install and initialize Anki

Install current Anki from `https://apps.ankiweb.net/`. Open it once, select the correct profile, sign in to AnkiWeb, complete the first sync, and verify the Japanese deck is present.

In Anki, install AnkiConnect:

1. **Tools → Add-ons → Get Add-ons**.
2. Enter code `2055492159`.
3. Restart Anki and confirm `http://127.0.0.1:8765` is reachable while Anki is open.

On a headless Debian/Ubuntu machine:

```bash
sudo apt install xvfb git python3 util-linux
```

### 2. Clone the repository

```bash
git clone https://github.com/crnchwrpsupreem/nihongo-sensei.git
cd nihongo-sensei
```

### 3. Configure GitHub publishing

Create an SSH key on the mini PC and add the public key to the GitHub account or as a write-enabled deploy key for this repository. Then switch the remote to SSH:

```bash
git remote set-url origin git@github.com:crnchwrpsupreem/nihongo-sensei.git
ssh -T git@github.com
git config user.name "Nihongo Sensei Publisher"
git config user.email "nihongo-sensei@localhost"
```

No GitHub credential is stored in this repository.

### 4. Configure the Anki profile

```bash
mkdir -p "$HOME/.config/nihongo-sensei"
cp config.env.example "$HOME/.config/nihongo-sensei/config.env"
chmod 600 "$HOME/.config/nihongo-sensei/config.env"
```

Edit the file if your profile or deck differs. Recent Anki versions normally store Linux profiles under:

```text
~/.local/share/Anki2/User 1
```

If `$XDG_DATA_HOME` is set, the base is `$XDG_DATA_HOME/Anki2` instead.

### 5. Test once without pushing

Close Anki, then run:

```bash
./scripts/publish_update.sh --no-sync --no-push
```

That verifies extraction against the existing local collection. Then test the complete sync-and-publish path:

```bash
./scripts/publish_update.sh
```

### 6. Install the adjustable schedule

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
4. Start a project chat—voice or text—and say **“Start Japanese tutor mode.”**

The tutor must report the loaded `generation_id` and card counts before the first exercise. If the GitHub app is unavailable, the instructions include public raw-file fallbacks.

## For maintainers and coding agents

Read [`AGENT_HANDOFF.md`](AGENT_HANDOFF.md), [`AGENTS.md`](AGENTS.md), and [`.agents/skills/nihongo-sensei/SKILL.md`](.agents/skills/nihongo-sensei/SKILL.md) before changing behavior.

Verify changes with:

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/publish_update.sh scripts/install_systemd_user.sh
```

The generated private extraction in `work/current-session/` is ignored by Git. Credentials and `.env` files are ignored. Only the intentionally public bundle is staged by the publishing script.
