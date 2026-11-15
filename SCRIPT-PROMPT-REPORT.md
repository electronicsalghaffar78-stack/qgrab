# QGrab — "Video → Script + Prompt" Feature: Implementation Report

Built 2026-11-04 (local only — **NOT pushed, NOT deployed**). Implements
the owner-approved design: sample approved 2026-11-04 ~00:01 PKT
(`SCRIPT-PROMPT-TEST-SAMPLE.md`), Gemini free tier approved ~00:03,
click-only design rule ~00:04, homepage placement ~00:09, and the
permanent-usool rule block ~00:11. Both trees updated and md5-synced:
`~/workspace/downloader-site/` (master) and `~/workspace/qgrab-repo/`
(deploy).

## Owner rules baked in (hard requirements, not options)

1. **Click-only generation.** The endpoint is called ONLY by the
   tool's own Generate button (homepage section + dedicated page).
   Nothing fires on page load, on paste, or after /api/info. The
   download-result "Script + Prompts" button only scrolls to the
   section and pre-fills its input (platform pages: sessionStorage
   prefill + navigate to `/#script-prompt`); generation still waits
   for the visitor's own Generate press.
2. **Placement.** Homepage: link input → results → the tool as its
   OWN standalone section directly below the download area (own
   heading, own input + button, gradient-ring card), before Popular
   Downloaders. Dedicated SEO page kept: `/video-to-script-prompt`.
3. **Usool in every generated prompt.** The Gemini system instruction
   hard-requires all of the owner's permanent production rules in
   EVERY scene prompt: exact line spoken by the character himself in
   the line's own language, lips moving, ONCE slowly and clearly,
   never dubbed, no other/background voices, no music over dialogue;
   characters talk to each other, nobody looks at the camera;
   explicit camera angle + movement; photorealistic cinematic
   real-film look, never cartoon; an explicit facial-expression
   direction per character matched to the scene's emotion; identical
   character description blocks repeated verbatim across all scenes;
   silent scenes marked "Nobody speaks, mouths closed."; and the
   anti-text tail (no subtitles/captions/text/words/letters/numbers/
   watermark/logo anywhere in the frame).

## Files changed (md5-identical in both trees)

| File | Change |
|---|---|
| `app.py` | `POST /api/script-prompt`; Gemini client (model fallbacks, defensive JSON parse); `_vtt_timed_script`; caption-language chooser; per-IP soft rate limit (6 / rolling 24 h, in-memory); `GET /video-to-script-prompt`; sitemap +1 URL (9 total); SP strings added to `_js_strings` |
| `i18n.py` | +15 keys × 30 languages (193 total, strict parity re-verified; platform payloads intact) |
| `templates/_sptool.html` | NEW — the tool box (own URL input, Generate button, spinner, error area, Script + Prompts panes with Copy buttons) |
| `templates/_spjs.html` | NEW — tool logic; textContent-only rendering; prefill consumption; copy helpers |
| `templates/scriptprompt.html` | NEW — dedicated page (SEO title/meta/canonical/OG, 31 hreflang links, same tool) |
| `templates/index.html` | Standalone SP section below the download area; small scroll+prefill button appended to download results; `_spjs.html` included |
| `templates/platform.html` | Same result-area button (sessionStorage prefill → homepage section) |
| `templates/_extras.html` | SP CSS (panes, copy buttons, gradient-ring section card, small outline result button, RTL rules) |
| `templates/_footer.html` | Quick link to `/video-to-script-prompt` (label reuses `sp_h2`) |

Not changed: download cascade, Invidious fallback, PWA, ratings,
Dockerfiles, robots.txt. `_tools.html` deliberately NOT extended:
the All Tools list claims only verified-working tools, and this one
works only once `GEMINI_API_KEY` is set at deploy — add its entry
after the first live verification.

## Endpoint contract — POST /api/script-prompt {url, lang?}

Pipeline: `clean_url` → key check → rate check → `extract_info` →
caption track choice (requested lang, else Urdu, else English, else
first listed) → `_fetch_caption_vtt` → timed script (rolling-caption
dedupe, `[M:SS-M:SS]` lines) → 24,000-char cap (line-boundary cut,
`"truncated": true`) → Gemini → defensive parse (fences stripped;
unparseable → raw text as script, empty prompts, `"partial": true`).

Errors (UI maps each code to a clear localized message — this
replaces the generic download error for this tool):
400 `invalid_url` · 503 `not_configured` (no GEMINI_API_KEY) ·
429 `rate_limited` · 422 `no_subtitles` · 502 `ai_unavailable`.
Success: `{title, lang, script, prompts[], truncated, partial,
model}`. The API key travels only in the `x-goog-api-key` header —
never in a URL, log line, response or the repo.

## Gemini choice (verified at ai.google.dev, 2026-11-03)

- Shape (official API reference, ai.google.dev/api/generate-content):
  `POST https://generativelanguage.googleapis.com/v1beta/models/
  {model}:generateContent`, header `x-goog-api-key`, body
  `system_instruction` + `contents` + `generationConfig`
  (`responseMimeType: application/json`, temperature 0.4,
  maxOutputTokens 8192); reply text at
  `candidates[0].content.parts[].text`. Timeout 100 s per attempt.
- Models (models page + pricing page Free Tier column, all "Free of
  charge"): primary **`gemini-3.8-flash`** (env `GEMINI_MODEL` can
  override), fallbacks **`gemini-3.6-flash`**,
  **`gemini-3.5-flash-lite`** — tried on 404/429/5xx and network
  errors only (so a bad key's 400 fails fast and clean).

## Verification evidence (local, this machine)

- Pages: `/`, `/video-to-script-prompt`, both platform pages, legal
  pages — 200 from BOTH trees; homepage element order verified
  (download box → SP section → Popular Downloaders); dedicated page
  title/canonical/OG/31 hreflangs present; Urdu (`?lang=ur`) renders
  the SP section translated + RTL on both pages.
- No key: endpoint → 503 `not_configured`; bad URL → 400.
- 29 unit/integration checks (Flask test client, monkeypatched
  network): timed-script builder (roll-up merge, tag strip, hour
  format), caption chooser (5 cases), output parser (plain/fenced/
  garbage/missing-field), rate limiter units (limit, isolation,
  window pruning), happy path 200 with exact fields, requested-lang
  honoured, partial fallback, no-captions 422, endpoint rate limit
  (6×200 then 429), key absent from responses — **all pass**.
- All rendered `<script>` blocks from `/` and
  `/video-to-script-prompt` pass `node --check`.
- Real network, FAKE key: Aakhri Roti (`ktiJ9GSuPfY`) — captions
  fetched (Urdu track via the Invidious fallback after the sandbox
  proxy broke yt-dlp's TLS, the known sandbox artifact), the request
  reached the real Gemini API and was rejected **HTTP 400** (fake
  key) → endpoint answered a clean **502 `ai_unavailable`**, no
  stack trace. Big Buck Bunny (captions: []) → **422
  `no_subtitles`**; a caption-less TikTok URL → **422** as well.
- i18n parity: 30 languages × 193 keys, zero failures; 29 platform
  payloads intact. Test artifacts removed (`data/` dirs from test
  boots deleted; no test ratings were ever written).

### What could NOT be tested without the real key (honest)

The final successful Gemini generation (a real 200 with a real
script + prompt pack) needs the real `GEMINI_API_KEY` — everything
up to Google's front door is verified (endpoint, header, payload
shape, caption pipeline, error mapping), and Google's own 400 for
the fake key proves the request format reaches the API. First thing
after the key is set on Render: run Aakhri Roti through the live
tool and eyeball the pack against the approved sample. Until that
passes, keep the tool's All-Tools entry unlisted (see above).

## Go-live steps (unchanged flow)

1. Worker (with the owner's login-warning rules): create the Gemini
   API key in AI Studio on the electronics account → set
   `GEMINI_API_KEY` in the Render service env (never via chat/repo).
2. Snapshot push (owner's approval) → Render Manual Deploy.
3. Live check: Aakhri Roti end-to-end + one caption-less video for
   the clear message; then optionally add the All Tools entry.

---

# V2 UPGRADE (built 2026-11-04, local only — NOT pushed/deployed)

Owner's orders after his own live test with a subtitle-less TikTok
video: (1) no-subtitle videos must work too — an audio route;
(2) Script and Prompts are separate jobs — two buttons; (3) the
waiting text is ONLY "Please wait"; (4) the helper line "Works with
videos that have subtitles or captions." is REMOVED entirely (not
reworded) — the click-only line "Nothing is created until you press
the button." stays exactly; (5) a preview + approve/change flow
(editable script, prompts from the edited script, Download (.txt),
Regenerate).

## What changed

**Audio route (`POST /api/script-prompt`, new fallback).** When the
caption path yields nothing (no track, fetch failure, or empty
timed script), the endpoint falls back instead of answering
`no_subtitles`: duration pre-check from the extracted info —
`duration > 1200` s → 422 `too_long` BEFORE any media download
(caption-route videos have no such limit). `_sp_download_audio_mp3`
walks the usual attempt cascade with format `bestaudio/best`,
then ffmpeg converts to **mono 64 kbps MP3** (20 min ≈ 9.6 MB);
a converted file over **18 MB** → 422 `audio_too_big`. The MP3 is
sent to Gemini as an `inline_data` part with a transcription
instruction: verbatim transcription in the ORIGINAL language and
script, scene segmentation with APPROXIMATE time ranges, speaker
labels inferred from the words; then the mode's normal output in
the same JSON contract. The model answers `{"error": "no_speech"}`
when nothing intelligible is heard → 422 `no_speech`. Gemini
timeout on this route: **240 s** per attempt. Total download/
convert failure → the legacy 422 `no_subtitles` catch-all. Temp
files are removed in a `finally` on every path. Gunicorn finding:
`deploy/Dockerfile` (both trees) already runs `--timeout 600` —
≥ the required 360 s, no change needed.

**Two modes.** The endpoint accepts `"mode": "script" | "prompts"`
(missing/invalid → "script"). Each mode returns ONLY its half:
script mode → `{script}` (prompts `[]`), prompts mode →
`{prompts}` (script `""`), plus `mode` and `route`
(`captions`/`audio`/`script`) fields. The system instructions were
recomposed per mode from the SAME verbatim blocks — the 8-rule
usool PROMPT block is byte-identical to v1 in every instruction
that produces prompts; the SCRIPT rules are verbatim too (the
audio variant changes only "as captioned" → "as transcribed").
UI: the single Generate button became **two buttons** —
"Create Script" / "Create Prompts" — under the link box; each
fills only its own pane; the other pane keeps its content.

**Preview + approve/change flow.** The script pane is now an
**editable textarea** in the pane's style, with a localized hint:
the visitor can edit the script, and prompts will be made from
their edited script. Prompts mode accepts an optional `"script"`
field: non-empty and ≤ 24,000 chars → that text is the source
(new generator `_gemini_generate_prompts_from_script`, route
`"script"`), skipping the caption/audio fetch entirely — still
one rate-limited generation, same usool instruction; over-cap or
empty → the normal flow. The frontend sends the box's content
with Create Prompts whenever it is non-empty. Under the prompts
pane: **Download (.txt)** (client-side Blob download) and
**Regenerate** (a fresh prompts-mode call; counts against the
rate limit like any generation). The script pane has its own
**Download (.txt)** too. Copy buttons kept.

**Waiting text.** `sp_working_script` + `sp_working_prompt` were
replaced by a single `sp_working` = exactly "Please wait" (and
its bare equivalent) in all 30 languages; the 25-second
alternating-label timer in `_spjs.html` is gone — the pressed
button shows `sp_working` with the spinner, nothing more.

**Helper line removal.** `sp_note` in all 30 languages lost its
first sentence ("Works with videos that have subtitles or
captions.") entirely — the key now carries ONLY the click-only
sentence, verbatim as previously translated (EN: "Nothing is
created until you press the button."). Rendered pages verified:
the subtitles sentence is absent in EN and UR; the click-only
line is present.

**i18n.** Key deltas: removed `sp_btn`, `sp_working_script`,
`sp_working_prompt`; added `sp_working`, `sp_btn_script`,
`sp_btn_prompts`, `sp_err_toolong`, `sp_err_audiobig`,
`sp_err_nospeech`, `sp_edit_hint`, `sp_download`, `sp_regenerate`
— **200 keys × 30 languages, strict parity re-verified**; platform
payloads intact.

**Files changed (md5-identical in both trees):** `app.py`,
`i18n.py`, `templates/_sptool.html`, `templates/_spjs.html`,
`templates/_extras.html` (two-button row, editable-textarea and
actions-row CSS). Dockerfiles untouched (see the timeout finding
above; the repo Dockerfile's extra pillow/make_icons steps are a
pre-existing, intentional difference).

## V2 verification evidence (local, this machine)

- **Endpoint suite, 30 checks, all pass.** Real network + FAKE key:
  (a) Aakhri Roti `mode=script` → Gemini reached with the timed
  captions and a script-only instruction → graceful 502;
  (b) `mode=prompts` → 502, prompts-only instruction, usool block
  verified present; (c) **the owner's own link**
  `https://vm.tiktok.com/ZN8yX4Q3F/` → took the AUDIO route: the
  ~950 KB audio was downloaded and converted, the intercepted
  Gemini request contained exactly one `inline_data` audio/mp3
  part (>10 KB of base64) plus the transcription instruction, and
  the endpoint answered 502 (fake key) — **not** `no_subtitles`;
  the temp dir was verified cleaned up afterwards.
- Monkeypatched cases: (d) 25-min caption-less video → 422
  `too_long` with the media download stubbed to explode if called
  (it wasn't); (h) audio route → `{"error":"no_speech"}` maps to
  422 `no_speech`, and a canned script JSON returns 200 with
  `route: "audio"`; (i) `_SpAudioTooBig` → 422 `audio_too_big`,
  `_SpAudioFailed` → 422 `no_subtitles`; (f) **script override**:
  with `extract_info`, `_fetch_caption_vtt` and the audio download
  all stubbed to explode, POST prompts + a custom script returned
  200 `route: "script"` with the canned prompts, and the captured
  Gemini request body contained the custom script verbatim and
  the usool block — no fetch occurred; (g) a 24,001-char script
  field is ignored and the normal caption flow runs
  (`route: "captions"`); (e) rate limit across mixed modes:
  6 × 200 then 429, missing mode defaults to "script", per-mode
  response shapes verified; parser units for `no_speech` and the
  combined JSON.
- **Rendering, both trees:** `/` and `/video-to-script-prompt`
  boot 200 in EN and UR; two localized buttons, editable textarea,
  edit hint, Download/Regenerate buttons present; the combined
  button and both phase strings absent; helper-line assertions as
  above; the UR `sp_working` value verified by decoding the
  rendered I18N JSON (it is `\u`-escaped in the page source);
  every inline `<script>` block passes `node --check`.
- md5 parity for the 5 changed files in both trees; templates
  tree-identical; grep sweep confirms zero dangling references to
  the removed keys in either tree.

### What only the live key can prove (honest)

The first REAL transcription: that Gemini's free-tier models
accept the inline MP3 and return a usable verbatim transcript +
scene split for a real subtitle-less video (everything up to
Google's front door is proven — payload shape, route selection,
caps, error mapping). After deploy, the first checks should be:
the owner's TikTok link (script + prompts), one no-speech video
(music only) for the `no_speech` message, and one 20+ minute
caption-less video for `too_long`.

## Speed pass — audio route (2026-11-04)

Measured baseline (production, before this change): a 60-second
no-caption TikTok took ~28 s end-to-end for mode=script via the
audio route; a 105 s one took ~61 s. The owner flagged the wait as
a bounce risk, so the audio route's three slow paths were bounded
WITHOUT touching its correctness rules (the duration guard and the
muxed fallback exist because TikTok's standalone "bestaudio" can
be a wrong, longer music asset — see the v2 fix above):

1. **Duration-aware strategy order** (`_sp_audio_strategies`).
   When the video's duration is known, the audio-only selector
   (`bestaudio[acodec!=none]/bestaudio`) is tried FIRST — a
   matching track is a fraction of the video's size, and the
   existing duration guard still rejects a mismatched candidate
   (the 164 s-vs-105 s trap) and moves on to the muxed format,
   then to `bestaudio/best`. When the duration is unknown the
   guard is blind, so the safe order is unchanged: muxed first,
   then bestaudio.
2. **Bounded Gemini worst case (audio route only).**
   `SP_AUDIO_GEMINI_TIMEOUT` 240 s → 150 s per model, and the
   audio route now passes `max_models=SP_AUDIO_MAX_MODELS` (2) to
   `_gemini_call` — a new optional parameter; the text/caption
   routes keep their 100 s timeout and the full 3-model chain.
3. **Bounded fetch cascade (audio route only).** The audio
   download walks at most the first `SP_AUDIO_MAX_ATTEMPTS` (2)
   attempts of `_ordered_attempts`; the download endpoints keep
   the full cascade. All caps (1200 s, 18 MB), the mono 64 kbps
   transcode and the error contract are unchanged.

Tests: `tests/test_sp_audio.py` extended to 9 tests — audio-first
win with no vcodec download when the duration is known and the
track matches; the mismatched-audio trap still rejected and the
muxed format used; unknown duration still muxed-first; cascade
bounded to 2 attempts; `_gemini_call` model cap (2 capped vs 3
uncapped) via a stubbed urlopen; all previous assertions intact.
`tests/test_formats_audio_rule.py` still 8/8. Homepage + tool page
render 200 in EN and UR (RTL confirmed); all 18 rendered inline
script blocks pass `node --check`.

## Addendum — 2026-11-04 ~03:50 PKT: 24/7 stack (commits 31fff72, 7450c13, 0179855)
- Waiting UI: "Please wait" + a ticking time only (countdown from a duration-based estimate, counts up if it overruns). The timer is purely a holding aid — generation never depends on it and results render the moment they are ready.
- Generation runs as a background job: POST returns 202 + job_id at once; the page polls /api/script-prompt/status and resumes from sessionStorage after a reload/connection drop, so a visitor's flaky net no longer loses the result.
- Capacity: 3 Gemini API keys (projects under the personal, electronics and Larkana accounts) x a 6-model cascade (3.8/3.6/3.5/3.7 flash, 3.5-flash-lite, 3.1-flash-lite). Fast (quota-signature) failures walk all key x model pairs; slow failures cap at 2 attempts. Keys live in Render env GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3 — never in code or this report.
- Daily counters (TAAFT-style): Script 150/day, Prompts 150/day — derived from 3 keys x 6 models x ~20 free requests/day/model = ~360 pool, capped at 300 for safety. Reserve on POST, refund on job error, Pacific-midnight reset; the SP box shows both counters plus the refresh time rendered in each visitor's local time. GET /api/script-prompt/quota is a pure read.
- Production-verified 2026-11-04 ~03:56 PKT: two back-to-back script generations succeeded via key rotation while the original key's daily quota was exhausted; counter moved 150 -> 148 accordingly.
