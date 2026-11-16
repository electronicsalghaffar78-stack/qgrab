# QGrab Speed Build — Ant Ling (2026-11-17, release 2026-11-17.28, PREPARED — NOT YET DEPLOYED)

Owner's order (2026-11-17 ~00:58 PKT): "Hamari QGrab website me module slow hai —
Ant Ling se ya mere dost wale module ya kahin aur se fastest module lagao."

## Step 1 — Live measurements BEFORE (current Gemini route, qgrab.onrender.com, 2026-11-17 ~01:15–01:35 PKT)

| Feature | Measured time | Notes |
|---|---|---|
| AI Title Generator (fresh topic) | **30.15 s** | repeat of the same topic: 0.66 s (cache) |
| Support Assistant (real question) | **34.21 s** and **44.23 s** | greeting fast-path: 0.51 s (no AI call) |
| Script+Prompt (19-second YouTube video, script mode) | **never finished** | job still "running" at 63 s; the site then stopped answering polls for ~100 s (auto-heal recovered it); the job was lost (404 on later check) |

## Step 2 — The three candidates, same tasks

### (a) Current Gemini route
Numbers above. Root cause found in the code: the cascade STARTS with
`gemini-3.8-flash` (SP_DEFAULT_MODEL / SP_MODEL_CHAIN[0]).

### (b) Ant Ling (local tests through the connected API, exact QGrab prompts)
| Task | Model | Time | Quality |
|---|---|---|---|
| 10 titles (English) | Ling-3.1-flash | 4.49 s simple prompt / 6.58 s exact prompt | strict JSON OK, 10 items |
| 10 titles (Roman Urdu topic) | Ling-3.1-flash | 15.92 s thinking ON → **4.00 s thinking OFF** | strict JSON OK |
| Assistant answer | Ling-3.1-flash | 4.16 s → **2.34 s thinking OFF** | QGrab's own parser accepts it, goto validated |
| Script from timed captions | Ling-3.1-flash | 9.61 s → **2.47 s thinking OFF** | scene format correct |
| Prompts (usool rules) | Ling-3.1-flash | 58.09 s thinking ON → **7.43 s thinking OFF** | all 8 usool rules present, partial=False |
| Transcription, 33 s of speech | Ming-3.0-asr-tiny | **4.40 s** | transcript word-perfect (Harvard sentences) |
| Transcript → script | Ling-3.1-flash | **2.77 s thinking OFF** | correct format |
| Titles | Ling-3.2-flash | 35.28 s | REJECTED — as slow as Gemini |

Critical discovery: the Ling flash models are hybrid reasoning models. Left alone,
the hidden reasoning pass ate 5,251 of 5,871 completion tokens on the Prompts
instruction (58 s). Sending `"thinking": {"type": "disabled"}` turns it off
(reasoning_tokens = 0) with the output format and usool rules intact.

### (c) Dahot approach
Dahot uses the SAME Gemini API — no different provider. Its one real speed secret
(edge-assistant-ai.ts / edge-ai-tools.ts, probed by Dahot on 2026-11-09):
**gemini-3.5-flash answers in ~2 s on v1beta and is the primary; gemini-3.8-flash
HANGS on generateContent and is only a last-resort fallback**, plus a short
per-attempt timeout and thinkingBudget 0 (QGrab already copied that last trick on
2026-11-16). Dahot has no transcription / Script+Prompt equivalent at all.

## Step 3 — Decision (numbers par faisla)

**Winner: Ant Ling** — roughly 7–19× faster on every text task, and its ASR turns
the slowest route (audio transcription) from 60 s+/failure into ~4–7 s.
Adopted as the DEFAULT for: AI Tools (all 6 text generators), Support Assistant
(text questions; photo questions stay on Gemini vision), Script+Prompt captions
route, prompts-from-script, and the audio route (Ming ASR → transcript → Ling
script/prompts). **Gemini stays as the automatic fallback** for every route, with
the Dahot lesson applied to it: the chain now starts with gemini-3.5-flash and
gemini-3.8-flash moved to last resort (SP_DEFAULT_MODEL changed too).
Download par Script+Prompt auto-start wala behaviour bilkul waisa hi hai —
sirf andar ka engine badla hai.

Quota note: Ant Ling free quota is 500,000 tokens/day on the owner's account
(assistant ≈1,900 tokens/question because of its long system prompt; titles
≈700; script ≈1,000–7,000). If the daily quota ends, Ant Ling errors and the
Gemini fallback answers instead — the visitor never sees a quota failure.

## Code changes (app.py, both mirrors identical; version 2026-11-17.28)

- New Ant Ling provider block: `_antling_api_key` (env `ANT_LING_API_KEY` only,
  header-only, never logged), `_antling_chat` (Ling-3.1-flash, thinking
  disabled, 30 s timeout), `_antling_transcribe_file` (Ming-3.0-asr-tiny,
  multipart, 60 s timeout), `_ai_text_call` (Ant Ling first, Gemini fallback;
  inline_data parts go straight to Gemini), `_antling_generate_audio`
  (chunked ASR → stitched transcript → script/prompts; no-speech answer
  identical to the Gemini route's).
- Call sites swapped to `_ai_text_call`: AI Tools generate, Assistant ask,
  Script+Prompt text route, transcript route, prompts-from-script.
  `_gemini_generate_audio` tries the Ant Ling audio route first when configured.
- `not_configured` gates (AI Tools, Assistant, Script+Prompt) now accept
  "Gemini keys OR Ant Ling key". Thumbnail IMAGE generation stays Gemini-only.
- Gemini chain reordered (Dahot): `["gemini-3.5-flash", "gemini-3.6-flash",
  "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
  "gemini-3.8-flash"]`, SP_DEFAULT_MODEL = "gemini-3.5-flash".
- Assistant version label in templates/_assistant.html bumped to v2026-11-17.28.

## Tests

- New `tests/test_antling_speed.py`: 7/7 pass (request shape + thinking-off,
  preference, Gemini fallback, inline_data routing, ASR multipart, audio
  route + no_speech, endpoints answering 200 with ONLY an Ant Ling key).
- Full suite: all 27 Python test files pass (incl. test_assistant 29/29 after
  the version-label bump) and all 6 JS suites pass.
- Local end-to-end with the REAL Ant Ling API through the patched Flask app:
  AI Titles endpoint **4.85 s** (10 items), Assistant **2.78 s**,
  Script+Prompt prompts job **7.51 s** (model: Ling-3.1-flash),
  audio route for 33 s of speech **6.63 s** end to end.

## ⛔ DEPLOY BLOCKER — isi liye ye build abhi LIVE nahi hai

Render par chalne ke liye QGrab ke server ko Ant Ling ki key chahiye:
Render Dashboard → qgrab service → Environment → `ANT_LING_API_KEY` add karna
hoga. Key ki value sirf secure vault me hai — Archer use nikaal nahi sakta aur
nikaalne ki koshish bhi nahi ki. Qudoos ko key dalne ka secure tareeqa main chat
se bataya jayega. Key lagte hi: GitHub push → Render Manual Deploy → live
timings dobara measure → desktop (1280px) + mobile (390px) screenshot verify →
backup ZIP refresh. Push/deploy se pehle approval card ki warning Roman Urdu
me di jayegi — koi surprise card nahi ayega.
