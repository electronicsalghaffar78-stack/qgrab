# QGrab Update — 2026-11-08: Support Assistant (chat + Talk to Support)

Owner-approved design, built 2026-11-08. Ships with APP_VERSION
**2026-11-08.3**. Not pushed/deployed by the builder — the parent
agent reviews, pushes and deploys.

## What visitors get

A floating button on the main pages (home, platform pages and the
Script+Prompt page): a circle/pill with a **🤖 robot face and the
readable word "Assistant"** — deliberately NOT a chat-dots icon,
per the owner's instruction, so every visitor understands what it
is. Tapping it opens the **QGrab Assistant** panel:

- **Chat** — type a question, get an answer grounded only in a
  factual knowledge base about QGrab (see below). If the answer
  names a homepage section, a **"Take me there →"** button under
  the answer closes the panel and smooth-scrolls to that section
  (from another page it hops to the homepage anchor instead).
  If the visitor reports a problem the assistant cannot fix, the
  **Talk to Support** button pulses to draw attention.
- **Talk to Support** — a form (email + problem description).
  On success the visitor sees the owner's exact confirmation
  (below). There is deliberately **no instant reply**: a real
  person reads the message, fixes any site problem first, and
  replies by email within **24–48 hours**.

## POST /api/assistant

Body: `{"message": "1..500 chars", "history": [{"role":
"user"|"assistant", "text": "..."}]}` — history is optional;
only the last 6 well-formed turns are honoured, junk turns are
dropped server-side.

Answers: `200 {"ok", "answer", "goto", "support", "left",
"max"}` · `400 invalid_request` · `429 daily_limit` ·
`502 ai_unavailable` · `503 not_configured`.

- Runs on the **shared Gemini cascade** (`_gemini_call`) with the
  AI Tools settings (`AI_GEMINI_TIMEOUT`,
  `AI_SLOW_MAX_ATTEMPTS`) — same keys, no new env vars.
- **Daily cap: `ASSISTANT_DAILY_CAP = 30`**, shared across all
  visitors, America/Los_Angeles quota day, reserved on POST and
  refunded on any failure — the AI Tools mechanics exactly.
- The system prompt carries a compact knowledge base written from
  the site itself: what QGrab is; supported download platforms
  (YouTube, TikTok, Facebook, Instagram, Pinterest, X, VK) and
  the NOT supported ones (Threads, Vimeo, Reddit, Dailymotion);
  how to download; public videos only; Search Videos; Video
  Toolkit; the 6 AI Tools and their shared 10/day cap (keyword
  results are AI ideas, thumbnail tool makes concepts, not
  images); Video → Script + Prompt (10/day each, ~2–3 minutes);
  Plans (Basic free; Premium Coming Soon — cannot be bought yet,
  $10 first month for new users then $20/month, 3-day free trial,
  cancel anytime, full refund on cancel, the automatic-billing
  note); the footer Update App button; PWA install; 30 languages;
  star reviews; and the Talk to Support 24–48-hour reply fact.
  The model must answer ONLY from these facts and must answer in
  the visitor's own language/script.
- The model is asked for strict JSON `{"answer", "goto",
  "support"}`. `goto` is validated server-side against the real
  homepage section ids — **`download`, `search-videos`,
  `video-toolkit`, `ai-tools`, `script-prompt`, `plans`** —
  anything else becomes null. If the reply is not usable JSON,
  the raw text is served as the answer with `goto: null`.

## POST /api/support + GET /api/support/inbox

- `POST /api/support {"email", "message" (10..2000 chars)}` →
  `200 {"ok", "message"}` where `message` is the confirmation,
  rendered verbatim by the frontend:
  *"Thank you! Your message has been received. We will look into
  it and reply to your email within 24–48 hours. If it is a
  problem with the site, we aim to fix it within 24–48 hours —
  please try again after that."*
  Errors: `400 invalid_request` (bad email/message — validation
  runs first and never burns allowance), `429 rate_limited`
  (per-IP soft limit: **3 stored messages per rolling 24
  hours**), `500 save_failed`.
- Messages append to **`data/support.json`** (same pattern as
  `data/ratings.json`): `{ts (UTC ISO), email, message}`, file
  capped at the latest **200**.
- `GET /api/support/inbox` is the **only** read path and is
  never linked anywhere: it requires header `X-Support-Key`
  equal to the **`SUPPORT_INBOX_KEY`** env var. Env var unset →
  **404** (endpoint disabled); missing/wrong key → **401**;
  correct → `200 {"ok", "count", "messages"}` newest first.
  Operation: set `SUPPORT_INBOX_KEY` in the Render environment
  to a long random value, keep it secret, and read the inbox
  with that header.

## Storage caveat (same as ratings)

`data/support.json` lives on the server disk: it **survives
restarts but NOT redeploys** (Render free tier's ephemeral disk).
The owner-side routine is therefore a **daily inbox check** —
read (and act on) new messages every day, before the next deploy
can wipe them. Fixing a reported site problem before replying is
the owner's standing workflow: reply only after the fix, quoting
the 24–48-hour window.

## Files

- `app.py` — endpoints, cap, knowledge base, support storage +
  inbox; `APP_VERSION` bumped to `2026-11-08.3`.
- `templates/_assistant.html` (new) — button + panel markup.
- `templates/_assistantjs.html` (new) — widget logic
  (textContent-only rendering; no countdown).
- `templates/_extras.html` — `.asst-*` styles (z-index 40/45:
  above content, below the toast/modal/install backdrop, so the
  widget never covers the install sheet's buttons; RTL-aware).
- `templates/index.html`, `templates/platform.html`,
  `templates/scriptprompt.html` — the two includes.
- `tests/test_assistant.py` (new), `tests/test_homepage_js.js`
  (assistant flows), `tests/test_app_version.py` (expectation).
