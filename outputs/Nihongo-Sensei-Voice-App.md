# Nihongo Sensei Voice App — Local Quick Start

## Start without an API key

1. Sync Anki and close the desktop app.
2. Open a terminal in the Nihongo Sensei workspace.
3. Run:

   ```bash
   python3 run_voice_tutor.py
   ```

4. In the local page, select **Start session**.

The text interface and local spoken prompts work immediately. Nothing is deployed.

## Enable the microphone later

Launch the server with an OpenAI API key in its environment:

```bash
export OPENAI_API_KEY="your-api-key"
python3 run_voice_tutor.py
```

Then select **Connect microphone**. The key remains on the local backend. Only microphone audio goes to the OpenAI Realtime transcription session after you connect; your Anki collection is never sent.

## Why prompts cannot drift

The language model is not the tutor controller. A local state machine chooses from exact sentence pairs created by the existing read-only Anki extractor. Every response is structurally ordered as assessment first, then exactly one next exercise. Japanese output is accepted only when it is an exact stored sentence or a literal contiguous chunk. Realtime provides transcription only, and the browser reads the controller's approved output.

English speech uses normal speed. Japanese is natural, clear, and modestly slower. Use **Replay Japanese slower** for an explicit slower repeat; subsequent turns return to the default pace.
