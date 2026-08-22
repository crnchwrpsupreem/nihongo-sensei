# Nihongo Sensei

Nihongo Sensei is a **local-first, deterministic Japanese tutor** that reads your Anki collection safely and turns only your currently active card sentences into voice or text exercises.

It exists to solve a specific reliability problem: a general chat/voice model can forget a tutoring rule or invent a prompt. Here, a local state machine—not an LLM—chooses every exercise, evaluates each answer, and emits the next one.

## What it guarantees

- Reads Anki **read-only**; it never changes cards, scheduling, review history, media, or settings.
- Refreshes from Anki at every session start, after you sync and close Anki.
- Includes cards Anki currently schedules as learning, review, or relearning; cards currently marked **new** stay out by default, even if they have old review history.
- Is sentence-first: exercises use exact stored Japanese/English sentence pairs from active cards.
- Never composes or transforms Japanese. Any Japanese it displays or speaks is either an exact active-card sentence or a literal contiguous chunk of one.
- After every answer, provides an assessment first, then **exactly one** next exercise.
- Runs entirely locally in text mode. Optional microphone transcription sends only microphone audio to OpenAI Realtime; it never sends your Anki corpus or generates tutor prompts.

## Quick start on a mini PC

1. Install [Anki](https://apps.ankiweb.net/) and sync your collection through AnkiWeb.
2. Sync in Anki, then fully close Anki.
3. Clone this repository and enter it:

   ```bash
   git clone https://github.com/crnchwrpsupreem/nihongo-sensei.git
   cd nihongo-sensei
   ```

4. Point the app at your Anki profile. On Linux, the usual location is shown below; adjust the profile name/path if yours differs:

   ```bash
   export NIHONGO_ANKI_PROFILE="$HOME/.local/share/Anki2/User 1"
   ```

   On macOS, use:

   ```bash
   export NIHONGO_ANKI_PROFILE="$HOME/Library/Application Support/Anki2/User 1"
   ```

5. Start the app:

   ```bash
   python3 run_voice_tutor.py
   ```

6. Open `http://127.0.0.1:8765`, choose **Start session**, and answer the one displayed exercise at a time.

Python 3.11+ and a modern browser are the only requirements for text mode. No packages need to be installed.

## Optional microphone transcription

Text mode and browser text-to-speech work without an API key. To use the **Connect microphone** button, configure an OpenAI API key only in the local server process:

```bash
export OPENAI_API_KEY="your-api-key"
python3 run_voice_tutor.py
```

The browser never receives that key. The Realtime connection is transcription-only: it sends microphone audio after you click Connect microphone, then returns a transcript for the local controller to assess. Browser speech synthesis speaks the controller's already-approved text at a normal English pace and a modestly slower Japanese pace.

See [the official OpenAI Realtime WebRTC guide](https://developers.openai.com/api/docs/guides/realtime-webrtc) and [Realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription) for API account setup and current service details.

## Anki setup assumptions

The default deck root is `日本語`, and the default profile name is `User 1`. You can override either without editing code:

```bash
python3 .agents/skills/nihongo-sensei/scripts/build_session.py \
  --profile "/path/to/Anki2/My Profile" \
  --deck-root "日本語"
```

At session start the app calls the same extractor. It refuses to read if Anki's SQLite database has an active lock/WAL/SHM sidecar, which protects against an inconsistent or live database snapshot. Sync and close Anki, then retry.

## How a lesson works

1. The app safely rebuilds `work/current-session/corpus.json` from the active Anki cards.
2. The controller validates the strict policy and starts one sentence-focused exercise.
3. You answer by typing or speaking.
4. The controller returns: **assessment of that answer → exactly one next approved exercise**.
5. Exercise types rotate through Japanese-to-English meaning, English-to-exact-Japanese recall, choice among stored sentences, and reconstruction from a literal stored chunk.

The generated corpus is private learning data and is ignored by Git. It remains only on the machine that runs the app.

## For another GPT/Codex agent

Read these files before changing behavior:

- [`AGENTS.md`](AGENTS.md): permanent tutor rules and tone constraints.
- [`.agents/skills/nihongo-sensei/SKILL.md`](.agents/skills/nihongo-sensei/SKILL.md): full Anki extraction, lexical gate, and lesson-policy specification.
- [`voice_app/controller.py`](voice_app/controller.py): the deterministic authority for exercise selection and answer assessment.
- [`voice_app/server.py`](voice_app/server.py): loopback-only HTTP server, safe refresh, and optional transcription bridge.
- [`tests/test_voice_controller.py`](tests/test_voice_controller.py): behavioral and safety regression tests.

Do not replace the controller with free-form model generation. Changes must preserve the safety invariants above and add a regression test when altering exercise flow or allowed Japanese content.

## Verify

```bash
python3 -m unittest discover -s tests -v
node --check voice_app/static/app.js
```

For deeper architecture and troubleshooting, see [voice_app/README.md](voice_app/README.md).

## Privacy and network boundary

- The server listens only on loopback (`127.0.0.1` / `localhost` / `::1`), never the LAN.
- No Anki collection, note fields, review history, or generated corpus leaves the machine.
- Optional Realtime use sends microphone audio only after an explicit button press.
- API keys stay in the local server environment and are neither stored by the app nor returned to the browser.
