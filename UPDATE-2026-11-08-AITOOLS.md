# QGrab — AI Tools (Toolkit Phase 2) — 2026-11-08

Six Gemini-powered generators in a new **AI Tools** section on the
homepage, directly below the Video Toolkit: **AI Title Generator,
AI Tags Generator, AI Hashtag Generator, AI Channel Name
Generator, Keyword Suggestions, AI Thumbnail Idea Generator**.
One shared panel: pick a tool card, type a topic (≤300 chars),
tap Generate, get a clean list where every row has its own Copy
button plus a Copy All for the whole set. Built locally, **not
pushed, not deployed** — it ships together with the phase-1 Video
Toolkit and the Update App button in this release.

## Backend — `POST /api/ai-tools/generate`

Body `{"tool": ..., "input": ...}`; `tool` is whitelisted to
`titles | tags | hashtags | channel_names | keywords |
thumbnail_ideas` and `input` must be a non-empty string of at
most 300 chars. Answers:

| Status | Body | Meaning |
|---|---|---|
| 200 | `{"ok", "tool", "items", "left", "max"}` | cleaned item list |
| 400 | `{"error": "invalid_request"}` | bad tool / bad input — nothing reserved |
| 429 | `{"error": "daily_limit"}` | the shared day is full — Gemini never called |
| 502 | `{"error": "ai_unavailable"}` | cascade failed or returned nothing usable — slot refunded |
| 503 | `{"error": "not_configured"}` | no Gemini key configured |

`GET /api/ai-tools/quota` is the read-only counter:
`{"left", "max", "resets_at"}` (next Pacific midnight as a UTC
epoch, like the Script+Prompt quota).

### Gemini reuse — no new keys, no new env vars

Generation runs through the **existing** `_gemini_call`
cascade: same `SP_MODEL_CHAIN` (+ `GEMINI_MODEL` override), same
`GEMINI_API_KEY` / `_2` / `_3` rotation, same header-only key
handling. A per-tool server-side system prompt asks for strict
JSON `{"items": [...]}` (the cascade already requests
`responseMimeType: application/json`) and carries a shared
LANGUAGE rule: the answer comes back in the **same language and
script as the topic** — English topic → English, Urdu-script →
Urdu script, Roman Urdu → Roman Urdu.

### Per-tool prompts (summary)

- **titles** — exactly 10 catchy, honest titles, no hashtags inside.
- **tags** — 15–20 items, one lowercase search phrase per item, no `#`, most important first.
- **hashtags** — 15–20 items, one hashtag per item, `#` first, no spaces, broad + specific mix.
- **channel_names** — exactly 12 unique, memorable names, easy to spell/say.
- **keywords** — exactly 15 related keyword/search-phrase ideas, most relevant first. (Ideas only — see the honesty note below.)
- **thumbnail_ideas** — exactly 5 concepts; each item is one string of 3 lines: `Text: ` (≤4 big words), `Colors: `, `Layout: `.

### Parsing (`_ai_parse_items`)

Primary path is the strict JSON (a bare list, or a list under
`items`/`results`/`tags`/… keys, is also accepted). Fallback for
a plain-text reply: line-based cleaning — markdown fences,
leading numbering (`1.` / `2)`), bullets and `**bold**` stripped;
a tags reply that arrives as ONE comma-separated line is split.
A structured JSON reply with no usable list is treated as
unusable (never as raw text). Hashtags are normalised to start
with `#` and lose their spaces. Duplicates drop (case-insensitive
for tags/hashtags), order is preserved, and each list is trimmed
to its tool cap (10 / 20 / 20 / 12 / 15 / 5).

### Quota — one shared cap of 10/day

`AI_TOOLS_DAILY_CAP = 10` successful generations per day across
ALL six tools, on the same America/Los_Angeles quota day as the
Script+Prompt counters, with the same mechanics: **reserve on
POST, settle on success, refund on any failure** (cascade error
or empty parse). State is in memory, like the SP counters — a
restart starts a fresh day early, never a stricter one. The cap
is deliberate (it protects the stacked free Gemini quotas) and
is separate from the SP caps, which are untouched.

### Synchronous, deliberately — with the timing evidence

Script+Prompt is async because its outputs are huge (an
8192-token script from a whole video's captions/audio). An AI
Tools answer is 5–20 short lines — a few hundred output tokens —
so this endpoint answers synchronously with a **bounded**
cascade: `AI_GEMINI_TIMEOUT = 25` s per attempt and
`AI_SLOW_MAX_ATTEMPTS = 2`. Measured against the real
`_gemini_call` with the network stubbed (1 key = 6 pairs):

- healthy first pair: **1 attempt** (real-world time is then
  just that call's round-trip — a few seconds for a small list);
- every pair failing FAST (instant 429, the quota signature):
  all 6 pairs walked with ~0.001 s of local overhead — the real
  cost is only the sub-second 429 round-trips;
- SLOW failures (timeouts/overloads): the walk stops at exactly
  **2 attempts**, so the worst case is ≈ 2 × 25 s = **~50 s**,
  plus at most a handful of fast round-trips before it.

Gunicorn runs with `--timeout 600`, so even the pathological
case finishes as a clean `ai_unavailable` long before the
worker is touched. The page shows a plain "Please wait" state
while generating — no countdown or timer anywhere, per the
standing site rule. If production logs ever show the bound
being hit regularly, the fix is the SP job pattern — say so
from evidence, don't pre-build it.

## Frontend

`templates/_aitools.html` (included from `index.html` right
after `_toolkit.html`) + CSS beside the Toolkit CSS + a JS IIFE
after the Toolkit IIFE, all following the phase-1 patterns:
cards (`.ai-tool`, the selected one gets the accent border), one
panel (`.ai-panel`) with input + Generate, a per-tool hint note,
the remaining-today line (from the quota endpoint on load, from
each generate response afterwards), results as `.ai-row`s
(text via `textContent` only; multi-line thumbnail concepts keep
their line breaks via `white-space: pre-wrap`), per-row Copy and
a Copy All (tags join with `, `, hashtags with a space,
everything else with newlines). Clipboard uses
`navigator.clipboard` with the same textarea fallback as the
Toolkit.

**Honesty rules, enforced in the panel notes:** the Keyword
panel says its results are *AI-generated ideas — suggestions
only, not real search-volume data* (no volumes are shown
anywhere, ever); the Thumbnail panel says it *creates concepts,
not images* (text, colors, layout only). Error codes map to
plain messages (`daily_limit` → try again tomorrow,
`not_configured` → being set up, `ai_unavailable` → AI busy).

## Tests

- `tests/test_aitools.py` — **17/17 pass**: parser (JSON path,
  fences, dirty items, line fallback, comma-split tags, hashtag
  normalisation/dedupe, per-tool caps, multi-line concepts,
  unusable replies), prompt construction (tool instruction +
  SAME-language rule + verbatim topic reach the request body,
  incl. a Roman Urdu topic), and the endpoint contract (200 +
  counter decrement, all-six-tools, 400s reserve nothing and
  never call Gemini, 429 at the cap with Gemini uncalled, 502 +
  refund on cascade failure and on empty items, 503 without a
  key, quota shape + Pacific-midnight reset + date rollover).
- `tests/test_homepage_js.js` — extended (fetch stubs for the
  quota + generate endpoints): quota note renders, a generation
  renders one row per item and updates the left count. Full
  suite passes.
- Full suites, master tree: **15/15 Python + 4/4 Node pass**
  (incl. the new `test_app_version.py`). Mirror tree: identical
  except the known pre-existing `test_install_button.py`
  failure (generated PNG icons absent from the repo snapshot —
  unrelated, not chased).

## Limitations / notes

- The daily cap counts **successful** generations only and is
  global (not per visitor) — the same trade-off the owner
  accepted for Script+Prompt's counters, and the real guard for
  the free quota.
- Counts the model returns are requests, not guarantees: the
  parser trims over-delivery and the endpoint refuses an empty
  result, but a model that returns 7 titles instead of 10 ships
  7 titles.
- Keyword ideas are the model's judgement — there is no search
  data behind them, and the UI says so.
- No changes to `/api/search`, `/api/video-details`,
  Script+Prompt (caps included), or `sw.js`.

## Plans header link + section (same release)

- **Placement:** a gold pill link "⭐ Plans" sits immediately
  beside the QGrab logo in the top header (inside a new
  `.brand-side` flex group at the left of the header bar) and
  anchors to `#plans`. It is a direct, always-visible header
  element — never inside the three-dot menu — and stays
  visible on mobile (compact padding/font under 560px; the
  desktop layout is logo + pill on the left, Install / theme /
  menu on the right).
- **Section:** new `#plans` section (`templates/_plans.html`,
  included right after AI Tools) with two cards — side by side
  on desktop, stacked on mobile. BASIC — Free: "All tools
  included", "AI features limited to 10 uses per day", "Free
  forever"; disabled "Current plan" button. PREMIUM: "$10
  first month for new users, then $20/month"; "Everything
  unlimited", "3-day free trial included", "Cancel anytime",
  "Full refund if you cancel"; gold "Coming Soon" badge and a
  disabled "Coming Soon" button. No download cap was invented
  for Basic and no launch date is promised for Premium.
- **Announcement only:** no checkout, no card/bank fields, no
  working buy button, no email capture. Checkout + user
  accounts are a later phase — no payment processor or
  account system exists on the site yet.
- **Tests:** `tests/test_plans.py` (new) asserts the header
  link's placement after the logo and outside the menu panel,
  the section's position after AI Tools, both cards' exact
  facts, disabled buttons, and that `#plans` contains no form
  elements at all. Full suites: master 16/16 Python + 4/4 Node
  pass; mirror identical except the known pre-existing
  `test_install_button.py` failure (unrelated).
