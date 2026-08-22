# Nihongo Sensei Windows mini-PC quick start

1. Install current Anki, sign in to AnkiWeb, complete one manual sync, and install AnkiConnect add-on `2055492159`.
2. Install Python 3 and Git, then clone `https://github.com/crnchwrpsupreem/nihongo-sensei.git`.
3. Authenticate Git pushes using GitHub CLI/Git Credential Manager or a write-enabled SSH key.
4. Copy `config.env.example` to `%APPDATA%\nihongo-sensei\config.env` and verify the profile name and deck root.
5. In PowerShell, run `powershell -ExecutionPolicy Bypass -File .\scripts\publish_update.ps1 -NoSync -NoPush`, then repeat without `-NoSync -NoPush`.
6. Install the timer with `powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -Interval 3h -RunNow`.
7. Paste `CHATGPT_PROJECT_INSTRUCTIONS.md` into a ChatGPT Project and connect its GitHub app to this repository.
8. In a project voice or text chat, say “Start Japanese tutor mode.”

Keep the Windows user signed in so the interactive scheduled task can open Anki; the screen may be locked.

The public bundle includes reviewed card content and review history. It excludes untouched cards, credentials, media, and machine paths.
