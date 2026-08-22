# Nihongo Sensei local voice tutor

This is a local-only web application. A deterministic Python controller owns every exercise and assessment; no language model can create tutor prompts or Japanese content.

## Run in text/mock mode

Requirements: Python 3.11+ and a modern browser. There are no third-party Python packages.

1. Sync Anki and close the desktop app.
2. From the workspace root, run:

   ```bash
   python3 run_voice_tutor.py
   ```

3. Open `http://127.0.0.1:8765` if the browser does not open automatically.
4. Select **Start session**. This refreshes the corpus with the existing read-only extractor.

Text answers and local browser speech synthesis work without an OpenAI API key.

## Enable Realtime microphone transcription

Set the API key only in the server process environment, then launch the app:

```bash
export OPENAI_API_KEY="your-api-key"
python3 run_voice_tutor.py
```

The key stays in the local Python process and is never returned to the browser. `NIHONGO_SENSEI_API_KEY` is accepted as an alternative. To override the default transcription model:

```bash
export NIHONGO_TRANSCRIBE_MODEL="gpt-live-transcribe"
```

Select **Connect microphone** in the app and grant browser microphone permission. The browser establishes a WebRTC transcription session through the local backend. Microphone audio is sent to the OpenAI Realtime API only after this explicit action. The Anki corpus is never included in that session or transmitted to OpenAI.

The microphone track is temporarily muted while the tutor speaks to prevent its exact prompt from being transcribed as the learner's answer. It is re-enabled immediately after the single exercise prompt finishes.

The implementation follows OpenAI's official [Realtime WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc) and [Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription) architecture. Realtime is used only to produce a transcript; browser speech synthesis reads the deterministic controller response exactly.

## Controller protocol

At session start:

1. Run the safe read-only Anki refresh.
2. Validate that strict lexical gating is enabled and Japanese composition is disabled.
3. Select exactly one stored active-card sentence exercise.

After every learner answer, return one structured response in this order:

1. `assessment`: `correct`, `partially_correct`, or `incorrect`, plus an English explanation and—only when needed—an exact stored Japanese correction.
2. `exercise`: exactly one next exercise selected by the state machine.
3. `session`: non-generative status metadata.

Exercise types rotate deterministically through Japanese→English meaning, English→exact Japanese recall, selection among exact sentences, and reconstruction from a literal sentence chunk. Every Japanese segment is checked against the exact active sentence whitelist or verified as a contiguous substring. The controller rejects any response outside that boundary.

English is spoken at browser rate `1.0`; exact Japanese is spoken naturally at `0.88`. **Replay Japanese slower** is an explicit one-time slower repeat at `0.72`, after which normal turns return to the default. No generated Japanese or arbitrary prompt path exists.

## Safety

- The backend binds only to `127.0.0.1`, `localhost`, or `::1` and rejects non-local Host headers.
- The Anki extractor opens `collection.anki2` with SQLite read-only, immutable, and query-only settings and refuses active WAL/SHM state.
- The app writes generated session files only under this workspace.
- It never opens Anki, uses AnkiConnect, edits cards, modifies scheduling, reads media, or changes settings.
- It never deploys or hosts the application externally.
- The API key is not logged, stored in source, or exposed by status endpoints.

## Verify

Run the controller and server-safety tests:

```bash
python3 -m unittest discover -s tests -v
```

Check the browser JavaScript syntax when Node.js is available:

```bash
node --check voice_app/static/app.js
```

Run without opening a browser for a manual API check:

```bash
python3 run_voice_tutor.py --no-open
```
