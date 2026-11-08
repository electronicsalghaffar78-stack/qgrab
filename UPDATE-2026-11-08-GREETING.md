# Update 2026-11-08.9 — Assistant greets back (greeting fast-path)

**Owner's instruction:** when a visitor says "Hello" or "Hi" to the
Support Assistant, it should reply **in English** asking how it can
help — so the visitor then explains their problem and gets an AI
answer.

## What changed

**Backend only** (`app.py`, `POST /api/assistant`). Before any Gemini
call, the endpoint now checks whether the message is *only* a
greeting (`_assistant_is_greeting`). On a match it returns the
structured success response instantly, without touching the Gemini
cascade:

- answer (exact, owner's wording):
  "Hello! How can I help you? You can ask me anything about QGrab —
  how to download a video, search for videos, or use any tool on
  the site."
- `goto`: null, `support`: false.
- **Cap mechanics unchanged on purpose:** the daily slot is reserved
  before the branch and settled as a success, exactly like a
  Gemini-answered question — a greeting costs one of the day's 30
  Assistant questions. No special-casing.

**Greeting detection:** the message is trimmed, lowercased,
whitespace-collapsed and stripped of trailing punctuation
(`! . ? , ~`). It counts as a greeting when it is exactly one of:

hello, hi, hii, hiiii, hey, heyy, salam, assalamualaikum,
assalamu alaikum, aoa, good morning, good afternoon,
good evening, yo, hola

optionally followed by ONE trailing word: there, qgrab, assistant,
bot ("hello there", "hi qgrab").

**Not greetings:** anything with a real question or problem attached
("Hello, how do I download?", "hi my video is not downloading",
"salam, ek masla hai") goes through the normal AI flow untouched,
including its greeting prefix — no change there.

## Frontend

No change. Verified in `templates/_assistantjs.html`: the panel
renders whatever `answer` a 200 response carries (textContent),
clears its plain "Please wait" status on success, and has no
minimum-delay/typing timer — an instant answer renders exactly like
a slow one.

## Tests

- `test_assistant.py` — 23/23 (3 new):
  - `test_greeting_matcher_words_and_tails` — the matcher over the
    full greeting list, the allowed tails, and non-greetings
    (greeting + question, multi-word tails, "history", "high
    quality"…); also pins `ASSISTANT_GREETING_REPLY` to the owner's
    exact literal.
  - `test_greeting_fastpath_exact_no_transport_cap_counts` —
    "Hello", "hi", "Hey!", "salam", "Assalamualaikum",
    "hello there" each return the exact canned answer with
    goto null / support false, **zero** recorded transport calls,
    and the daily counter decremented by exactly one per greeting.
  - `test_greeting_with_question_uses_ai_path` —
    "Hello, how do I download a TikTok video?" and "hi, my
    download is stuck" return the stubbed AI answer (never the
    canned text) with exactly one transport call each.
  - One existing test updated for a legitimate premise change:
    `test_assistant_empty_answer_refunds` posted "hello?" — now a
    pure greeting that never reaches Gemini — so its message became
    a real question ("what does qgrab do?"); it still pins the
    empty-answer → 502 + refund behaviour.
- `test_app_version.py` — expected version bumped to 2026-11-08.9;
  the Assistant panel's static stamp in `templates/_assistant.html`
  follows (`test_widget_composer_inline_hardening` pins stamp ==
  APP_VERSION and stays green).

## Release discipline

`APP_VERSION` → **2026-11-08.9** (app.py + test expectation +
static Assistant stamp). No cap sizes changed. No push, no deploy
in this step — the parent ships it through the usual pipeline.

## Honest limitations

- The matcher is an exact word list, not language understanding:
  a greeting spelled outside the list ("helo", "hiiiii" with 5 i's,
  "selam") falls through to the AI path, where the model still
  greets back per its instructions — just slower and costlier.
- A greeting costs one daily Assistant slot, same as any answered
  question (deliberate: the cap accounting was kept identical).
- Emoji-bearing greetings ("Hello 👋") are not matched (the owner's
  spec was plain text); they take the normal AI path.
