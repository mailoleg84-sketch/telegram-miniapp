# Voice Tutor Architecture

## Product behavior

The voice tutor is a structured English lesson, not an open-ended chatbot.
Every voice turn should:

1. Respond to what the child actually said.
2. Preserve the current topic and lesson phase.
3. Add one small learning step.
4. Ask at most one question or give one tiny task.
5. Adapt language, length, and correction style to age and level.

Russian is used as support when a child speaks Russian or is confused. The
tutor returns to English gradually, without forcing an English-only answer.

## Runtime architecture

- `webapp/lesson_engine.py` is the deterministic lesson state machine.
- `voice_lesson_state` in PostgreSQL stores the active lesson between requests
  and Realtime reconnects.
- `voice_lesson_sessions` stores a compact summary when a lesson reaches its
  wrap-up phase.
- `webapp/server.py` advances the same state for chat voice, hybrid voice, and
  Realtime logs.
- `webapp/openai_service.py` injects the authoritative state into normal and
  Realtime prompts.
- `webapp/static/app.js` displays lesson topic, phase, progress, and voice
  states.

The model is responsible for natural wording. The lesson engine is responsible
for continuity, topic selection, phase order, and compact progress data.

## Lesson state machine

`welcome -> choose_topic -> mini_lesson -> dialogue -> challenge -> wrapup`

- `welcome`: warm start and readiness check.
- `choose_topic`: offer exactly three age-relevant choices.
- `mini_lesson`: introduce a target phrase and a few useful words.
- `dialogue`: practice the phrase in a natural conversation.
- `challenge`: give one short final task.
- `wrapup`: name one success and one gentle growth point.

The active topic never changes merely because time passed, another topic was
mentioned, or Realtime reconnected. It changes only after an explicit request
from the child or a reset.

## Age adaptation

| Age | Tutor behavior | Typical topics |
| --- | --- | --- |
| 5-7 | Very short, playful, choices of two, no direct criticism | animals, colors, toys, family |
| 8-10 | Simple dialogue, mini-stories, gentle grammar | school, games, food, sports |
| 11-13 | Natural pre-teen tone, more independent answers | hobbies, video games, music, technology |
| 14-18 | Respectful adult-like tone, real-life scenarios | travel, interviews, exams, career |

Each topic plan contains a lesson goal, target phrase, target words, and aliases
used to recognize a child's choice in Russian or English.

## Emotional support and corrections

- Confusion keeps the current topic but switches to simple Russian support and
  a choice of two.
- Tiredness keeps the topic but changes the next step to a very easy game or a
  short ending.
- A common English mistake increments the session correction counter and the
  prompt requests only one gentle correction.
- Mentioning an unrelated word does not change the lesson topic.
- Unsafe or personal-data requests are handled by the existing safety guard.

## Voice modes and fallback

Realtime WebRTC is the preferred live mode. Hybrid voice remains the reliable
fallback:

1. Transcribe the child's audio.
2. Generate a short structured tutor response.
3. Synthesize the full response.
4. Continue listening after playback finishes.

Both modes use the same persistent lesson state. This prevents a fallback or
reconnect from restarting the lesson.

## How to test

Run the automated checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile database.py webapp\server.py webapp\openai_service.py webapp\lesson_engine.py config.py
node --check webapp\static\app.js
git diff --check
```

Manual voice scenarios:

1. Age 5, Beginner: choose animals, answer with one word, then say "не знаю".
2. Age 8, Beginner: choose food, mention a dog, confirm that topic stays food.
3. Age 10, Elementary: choose school, make one simple grammar mistake.
4. Age 13, Pre-Intermediate: choose games and ask a question in Russian.
5. Age 16, Intermediate: choose travel and request a role-play.
6. Ask to change topic and confirm that the new topic starts at mini-lesson.
7. Stop and reconnect Realtime; confirm topic and phase remain visible.
8. Clear the conversation; confirm the lesson returns to the start.

## Example lesson flow

Age 8, food:

- Tutor: "Выбираем тему. Еда, школа или игры?"
- Child: "Еда."
- Tutor: "Отлично. Can I have a pizza, please? Это вежливый заказ. Что выберешь: pizza или juice?"
- Child: "Pizza."
- Tutor: "Хороший выбор. Представим, что я в кафе: What would you like?"

Age 16, travel:

- Tutor: "Let's practice a real travel situation. You need to find the station. What would you ask?"
- Child: "Where station?"
- Tutor: "Good start. A natural version is: Where is the station? Now ask me once more."

## Next useful improvements

- Save completed voice-session summaries into a dedicated lesson history table.
- Use accumulated mistakes and mastered phrases when creating the next lesson.
- Add an optional parent-facing speaking progress report.
- Add end-to-end browser and live-audio telemetry for latency and fallback rate.
