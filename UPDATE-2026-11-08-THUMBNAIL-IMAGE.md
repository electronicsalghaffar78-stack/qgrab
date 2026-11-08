# Update 2026-11-08.8 — the AI Thumbnail tool now creates a REAL image

**Owner's request:** testing the AI Tools on his phone, the owner
typed "Cat" into the AI Thumbnail Idea Generator and got text
concepts only. His words: the thumbnail itself should have come —
fix it so a real thumbnail image appears.

## What shipped

### New endpoint: `POST /api/ai-tools/thumbnail-image`

Body: `{"input": "<topic, 1..300 chars>"}`. Answers:

| Status | Body | Meaning |
|---|---|---|
| 200 | `{"ok": true, "image": "data:<mime>;base64,…", "left": N, "max": 10}` | image created |
| 400 | `{"error": "invalid_request"}` | missing/empty/over-long input |
| 429 | `{"error": "daily_limit"}` | the shared AI day is full |
| 502 | `{"error": "ai_unavailable"}` | both generators failed |
| 503 | `{"error": "not_configured"}` | no Gemini key configured |

It draws on the **same shared AI daily cap** as the text tools
(10/day, America/Los_Angeles quota day): a slot is reserved on
POST and refunded on any failure — the exact `_ai_quota_reserve` /
`_ai_quota_settle` mechanics of `/api/ai-tools/generate`. A
Thumbnail Generate therefore uses two slots on success (one for
the concepts, one for the image), which the "left today" counter
reflects honestly.

### The image prompt

`_ai_thumbnail_prompt(topic)` builds one English prompt from the
topic (English regardless of the topic's language): a vivid
16:9 YouTube-thumbnail scene — one large expressive subject,
bright saturated colours, high contrast, clean background — with
an explicit instruction that the image contain **absolutely NO
text** (no words, letters, numbers, logos or watermarks).
AI-rendered lettering comes out garbled; the concepts above the
image carry the text suggestions and the visitor adds their own
text with any editor.

### Generation chain (each attempt bounded by 30 s)

1. **Gemini image model** — `gemini-2.5-flash-image`, through
   the existing key rotation (`_gemini_api_keys()` order). A
   dedicated call, not `_gemini_call` (that helper forces a JSON
   text response): POST to the standard
   `…/v1beta/models/gemini-2.5-flash-image:generateContent`
   with `generationConfig.responseModalities: ["TEXT", "IMAGE"]`,
   the key in the `x-goog-api-key` header, and the image read
   back from the response's `inlineData` part. Payload guard:
   anything over ~2.5 MB is rejected (checked on the base64
   length before decoding, and again on the decoded bytes).
2. **Pollinations fallback** — `GET
   https://image.pollinations.ai/prompt/<urlencoded
   prompt>?width=1280&height=720&nologo=true` with a browser
   User-Agent; only an `image/*` content type with a non-empty,
   ≤2.5 MB body is accepted.
3. Both fail → **502** (slot refunded).

### Frontend (AI Tools section)

With **thumbnail_ideas** selected, pressing Generate keeps the
existing concepts flow exactly as before **and** fires the image
request in parallel. The new `#aiThumbBox` under the results
shows a plain `Creating your thumbnail image…` note (no
countdown); on success it renders the image (16:9,
`object-fit: cover`, full panel width) with a **Download
Thumbnail** button (an anchor downloading the data URL as
`qgrab-thumbnail.jpg` / `.png` by mime); on failure it shows one
honest line — *"The image could not be created right now — the
ideas above still work."* Switching tools or generating again
resets the box; the concepts are never blocked or broken by the
image leg.

### Copy updates (the site tells the new truth)

- The thumbnail tool's note under the panel no longer says
  "This tool creates concepts, not images"; it now reads:
  *"AI-generated concepts — big text, colors and layout ideas.
  You also get one real thumbnail image below the ideas — add
  your text with any editor."*
- The Assistant knowledge base line was updated the same way
  (concepts **and** one real image, Download Thumbnail button,
  image carries no text) and `tests/test_assistant.py` pins the
  new wording.
- The Assistant panel's static version stamp moved to
  v2026-11-08.8 with the release (the stamp tracks
  `APP_VERSION`; the test suite pins them together).

## Evidence

- **Pollinations, tested live from the build sandbox:**
  `GET https://image.pollinations.ai/prompt/<cat thumbnail
  prompt>?width=1280&height=720&nologo=true` → **HTTP 200,
  Content-Type image/jpeg, 64,552 bytes in 6.45 s**; the body
  verified as a real JPEG (1024×576). The fallback leg works.
- **Gemini image leg — honest limitation:** there are no Gemini
  keys in the build sandbox, so this leg could not be exercised
  here. It is written defensively to the documented
  generateContent shape (model in the URL, key in the header,
  `responseModalities` requesting IMAGE, image extracted from
  `inlineData`), unit-tested against that shape with stubbed
  transports, and **must be live-verified after deploy** — if
  Google's answer differs, every request simply falls through to
  the proven Pollinations leg and the endpoint still answers 200.

## Tests

- `tests/test_thumbnail_image.py` (new, **10/10**): prompt
  builder (16:9 + no-text + topic); Gemini success (data URL,
  counter decrement, request carries the image model +
  `responseModalities` + built prompt); Gemini fail →
  Pollinations success (URL carries prompt + 1280×720 +
  nologo); both fail → 502 with refund; oversized Gemini image
  → falls through; oversized / non-image Pollinations answer →
  502 with refund; 400s reserve nothing and call no transport;
  429 at the cap calls nothing; 503 without a key.
- `tests/test_homepage_js.js`: the Thumbnail tool's note pins
  the new promise; a Generate renders the image + Download
  Thumbnail anchor (correct data URL + `qgrab-thumbnail.png`)
  under intact concepts; a failed image leg shows the honest
  line with the concepts untouched.
- `tests/test_aitools.py` 17/17, `tests/test_assistant.py`
  20/20, `tests/test_app_version.py` 2/2 (expects
  **2026-11-08.8**). Full suites: see the release report.

## Release discipline

`APP_VERSION` → **2026-11-08.8** (endpoint + `/api/version`
test updated; the Assistant panel's static stamp bumped to
match, as its pin requires). No cap sizes changed, no other
tool touched, nothing pushed or deployed from the build step.
