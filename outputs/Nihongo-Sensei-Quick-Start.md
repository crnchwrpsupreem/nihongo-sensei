# Nihongo Sensei — Quick Start

## Recommended live tutor

For deterministic voice or text practice, run the local app from this workspace:

```bash
python3 run_voice_tutor.py
```

It refreshes the same safe read-only corpus and makes the local controller—not a voice model—the sole authority for assessments and exercises. See `outputs/Nihongo-Sensei-Voice-App.md` for microphone setup.

## Before each session

1. Sync Anki on your phone or laptop.
2. Close the Anki desktop app.
3. Open this Nihongo Sensei workspace in Codex.
4. Say: **“Start Japanese tutor mode.”**

Codex will read the local `User 1` collection directly and build a fresh lesson from cards that Anki currently schedules as learning, review, or relearning in `日本語`, including `Kaishi 1.5k` and `Mining`. Cards currently marked new are excluded by default, even if they retain older review history.

## Strict language boundary

- Instructions and explanations are in English by default.
- Japanese is limited to exact words, forms, particles, constructions, and complete expressions already present in the active cards.
- Nihongo Sensei will not conjugate, add a question ending, change politeness, vary a sentence, or combine familiar pieces into a new Japanese expression.
- If the active set is too small for natural conversation, practice uses English prompts followed by exact Japanese recall or repetition.
- To learn something new, explicitly ask to enter **preview/teach mode** for that item. New Japanese is introduced only after that approval.

## Lesson rhythm

After each ordinary answer, Nihongo Sensei gives brief feedback and immediately asks one next practice prompt. It will not ask whether you want to continue or leave the lesson hanging after praise or correction. After that single prompt it waits, leaving room for you to answer, interrupt, ask a question, request a pause, or end the lesson.

Each ordinary tutor turn is one coherent response in a fixed order: first, it assesses only your immediately preceding answer as **correct**, **partially correct**, or **incorrect** and gives the essential correction; second, it immediately presents exactly one next exercise and waits. It will not use a “next one” preamble before assessing, split feedback and the prompt into separate messages, add delayed praise, repeat the prompt, or send a contradictory follow-up.

## Sentence-first practice

The main practice unit is a verbatim example, practice, or sentence field from an active card—not an isolated word. Default exercises are:

- Translate an exact Japanese card sentence into English.
- Recall the exact stored Japanese sentence from its English meaning.
- Choose the appropriate sentence from verbatim active-card options.
- Reconstruct an exact sentence from a literal chunk copied from that sentence.

Individual words appear only as warm-ups, remediation, or hints. The word list is never permission to compose Japanese. Nihongo Sensei does not generate new Japanese sentences or conversational turns by combining known pieces; controlled conversation uses English scaffolding and literal active-card sentence chunks only.

## Speaking pace

English is spoken at normal conversational speed. Japanese words and exact card sentences are spoken clearly and naturally, only modestly slower than the English. Nihongo Sensei will not use exaggerated pauses or syllable-by-syllable delivery unless you explicitly ask for a slower repeat; afterward it returns to the modestly slowed default.

## Safety and permissions

- Grant **read-only** access to `~/Library/Application Support/Anki2/User 1` if macOS asks.
- Nihongo Sensei never writes to Anki cards, scheduling, review history, media, or settings.
- Generated session files stay inside this workspace under `work/current-session/`.

## Optional manual check

From this workspace, run:

```bash
python3 .agents/skills/nihongo-sensei/scripts/build_session.py --summary-only
```

This prints corpus counts without creating session files.
