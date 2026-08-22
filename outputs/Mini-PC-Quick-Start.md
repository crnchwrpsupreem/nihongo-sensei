# Nihongo Sensei mini-PC quick start

1. Install current Anki, sign in to AnkiWeb, complete one manual sync, and install AnkiConnect add-on `2055492159`.
2. Clone `https://github.com/crnchwrpsupreem/nihongo-sensei.git` on the mini PC.
3. Configure a write-capable GitHub SSH key and set the repository remote to SSH.
4. Copy `config.env.example` to `~/.config/nihongo-sensei/config.env` and verify the profile/deck paths.
5. Run `./scripts/publish_update.sh --no-sync --no-push` once, then `./scripts/publish_update.sh`.
6. Install the timer with `./scripts/install_systemd_user.sh --interval 3h`.
7. Paste `CHATGPT_PROJECT_INSTRUCTIONS.md` into a ChatGPT Project and connect its GitHub app to this repository.
8. In a project voice or text chat, say “Start Japanese tutor mode.”

The public bundle includes reviewed card content and review history. It excludes untouched cards, credentials, media, and machine paths.
