# Nihongo Sensei Publisher — agent rules

This repository is a mini-PC publisher and ChatGPT Project data source. It is not a local voice application.

Before changing behavior, read `.agents/skills/nihongo-sensei/SKILL.md`, `AGENT_HANDOFF.md`, and `CHATGPT_PROJECT_INSTRUCTIONS.md`.

Preserve these invariants:

- Anki sync is performed through Anki itself. Extraction opens `collection.anki2` strictly with SQLite read-only, immutable, and query-only settings.
- Never modify cards, scheduling, review history, media, or preferences from the extractor.
- Publish only cards in the configured Japanese deck hierarchy that have at least one review-log entry. Untouched cards are excluded.
- Preserve the distinction between currently active and previously studied cards.
- Strip source-machine paths and credentials from public outputs. Never publish Anki media or configuration databases.
- The public repository intentionally contains studied card text and review history. Keep the manifest privacy declaration accurate.
- The tutor must use English scaffolding and exact stored Japanese sentences/chunks only. A word whitelist never authorizes sentence composition.
- Each ordinary tutoring turn assesses the immediately preceding answer first, then gives exactly one next exercise.
- Do not add OpenAI API, Realtime, local microphone, local speech, or local chat-model code. Voice belongs to the ChatGPT Project.
- Add or update regression tests for extraction, classification, sanitization, and publishing behavior.
