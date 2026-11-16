# QGrab — Dahot-Features Upgrade — 2026-11-16

Owner's order (2026-11-16): study the friend's Dahot Tool backup
and bring its best features into QGrab's own stack — new
platforms, Eye Care mode, a referral system, manual
JazzCash/Easypaisa payment requests, ratings/reports polish,
and a real speed pass on Script+Prompt and AI Tools. Dahot
itself was **never deployed or copied** — only its ideas were
studied (study note: `dahot-tool-archive/DAHOT-STUDY-FOR-QGRAB.md`).
Built and tested locally, **not pushed, not deployed**.

## 1. New downloader platforms

`site_of()` + the impersonation-first attempt plan now cover
Reddit, Vimeo, Twitch, SoundCloud, Pinterest, X (Twitter),
Threads, Dailymotion, SnackVideo/Kwai, Telegram, Messenger.
New SEO platform pages (same `PLATFORM_PAGES` pattern, honest
English copy, personal-use note, in the sitemap):
`/pinterest-video-downloader`, `/twitter-video-downloader`,
`/reddit-video-downloader`, `/vimeo-video-downloader`,
`/twitch-video-downloader`, `/soundcloud-downloader`,
`/dailymotion-video-downloader`, `/telegram-video-downloader`.
Tools-grid cards added for the new pages.

### Per-platform test results (real public links, yt-dlp
2026.10.26, no cookies, from this datacenter IP — full log:
`dahot-tool-archive/PLATFORM-TESTS.md`)

| Platform | Result |
|---|---|
| Twitch (clips) | ✅ Works — full 15.5 MB MP4 download proof |
| Pinterest | ✅ Works — full 8.3 MB MP4 download proof |
| SoundCloud | ✅ Works — formats listed |
| X / Twitter | ✅ Works — formats listed |
| Telegram (public posts) | ✅ Works — public channel post only |
| Reddit | ❌ Blocked here — "Account authentication is required" on 3 posts |
| Vimeo | ❌ Blocked here — extractor demands login credentials |
| Dailymotion | ❌ Blocked here — "Access forbidden" / no formats on 4 videos |
| Threads | ❌ Impossible with stock yt-dlp — no Threads extractor exists |
| SnackVideo/Kwai | ❌ Impossible with stock yt-dlp — no extractor exists |
| WhatsApp | ❌ Impossible by design — WhatsApp has no public web post URLs at all |

Honesty handling: only the five verified platforms are
presented plainly. Reddit/Vimeo/Dailymotion pages carry a
"New — Still Being Improved" section stating the platform
restricts automated requests and some links may fail (they may
still work from the production host; retest after deploy).
Threads/Kwai/Messenger are detected by the allowlist but are
**not advertised anywhere**; WhatsApp was not added at all.

## 2. Eye Care mode

The existing Day/Night toggle becomes a 3-mode cycle
(light → dark → eyecare) in `templates/_themehead.html`;
saved light/dark behaviour is untouched. Eye Care is a warm
parchment palette (adapted from Dahot's CSS-variable idea,
fitted to QGrab's variables): `--bg #f7ead1`, `--card #fdf6e9`,
`--text #3d2f1d`, `--accent #c2410c`, applied on the homepage,
platform pages, and (reduced blocks) privacy/terms/dmca/
script-prompt pages. One difference from Dahot, kept
deliberately: Dahot uses a 3-button segmented control; QGrab
keeps its single cycling toggle so the header does not change
shape.

## 3. Referral system (adapted from Dahot)

Design (QGrab has no accounts, so identity is the browser
token already used by the frontend; the server stores only
its SHA-256 hash):

- Every visitor gets a referral code = first 8 hex chars of
  their token hash, upper-cased; link
  `https://qgrab.onrender.com/?ref=CODE`, shown in the Plans
  section with Copy + WhatsApp/Telegram share buttons.
- A first-time visitor arriving with `?ref=` claims the
  **welcome trial: 3 days of Premium**, once per visitor AND
  once per source-IP fingerprint — Dahot's anti-abuse shape
  (its `trial_used` flag + IP-fingerprint grant log).
- The inviter earns **+1 day of Premium per referred signup,
  unlimited**, stacked as `premium_until = max(existing, now)
  + days` (Dahot's stacking formula).
- No self-referral; a visitor can be referred only once.
- ⚠️ Dahot has a latent double-credit race (two claim paths);
  QGrab uses **one** claim function under one lock.
- Endpoints: `GET /api/premium/config`, `GET
  /api/premium/status`, `POST /api/premium/claim-welcome`.
  Storage: `DATA_DIR/premium.json` (same JSON pattern as
  ratings/support). Premium's effect today: it bypasses the
  Script+Prompt **per-IP** rate limit; the site-wide daily
  Gemini caps are shared infrastructure and are **not**
  bypassed (documented in code).

## 4. Manual payment requests (Dahot-style)

The Plans section keeps QGrab's own pricing — **$10 first
month, then $20/month, 3-day free trial, full refund if you
cancel within 3 days of paying** — and gains Dahot's 3-step
manual flow:

1. Pick a plan and JazzCash or Easypaisa.
2. See the receiving number and the exact amount.
3. Pay, then submit sender number (7–15 digits) + optional
   transaction ID → request stored as `pending`.

The owner approves/rejects via `GET /api/premium/inbox`,
`POST /api/premium/approve` (+30 days, stacking; a second
decision returns 409), `POST /api/premium/reject` — gated by
the existing `SUPPORT_INBOX_KEY` mechanism (404 when the env
var is unset, 401 on a wrong key). Amounts are computed
server-side only. Dahot itself has no approval step (its
owner edits the database by hand); the approve flow is
QGrab's, per the owner's order. Dahot only lists
easypaisa/sadapay as receiving methods; QGrab offers JazzCash
+ Easypaisa as ordered.

**PKR display:** single config constant `USD_PKR_RATE =
276.61` (verified 2026-11-15). Prices display as
$10 ≈ **Rs 2,770** and $20 ≈ **Rs 5,530** (rounded to the
nearest Rs 10), with the on-page note that the PKR amount
follows the current dollar conversion rate and can change.

**⚠️ INPUT NEEDED FROM THE OWNER:** the receiving numbers are
**not known** and were **not invented**. They are env config
`PAYMENT_JAZZCASH_NUMBER` / `PAYMENT_EASYPAISA_NUMBER`
(default empty). Until they are set on Render, that method
honestly shows "not available yet" in step 2 and
`POST /api/premium/request` returns 503
`method_not_configured`.

## 5. Ratings + Reports

- Ratings summary now includes a real per-star
  **distribution** {1–5}; the Reviews section renders
  distribution bars from the real stored ratings.
- New **Reports**: `POST /api/report` (categories
  broken_download / wrong_content / bug / other, optional
  message + page URL auto-context, same rate limiter as
  support), stored in `DATA_DIR/reports.json`, readable by
  the owner at `GET /api/reports/inbox` (same key gating).
  A "Report a problem" form sits in the Reviews section.

## 6. Script+Prompt speed + auto-start

Profile findings: the cascade's fast path was already sound
(model chain fastest-first, key rotation); the slowness came
from (a) a 100 s per-attempt timeout on the SP text route,
(b) Gemini "thinking" left enabled on text calls, (c) every
repeat request paying full price, (d) a 3 s result poll.

Changes:
- `SP_GEMINI_TIMEOUT` **100 → 40 s**. The slow-failure budget
  of 6 attempts was **kept** — it was set on 2026-11-05
  production evidence (see UPDATE-2026-11-05), and cutting it
  would trade reliability for speed.
- `thinking_budget=0` (Dahot's main trick) on the SP text
  route, the transcript stage, AI Tools and the Assistant —
  the audio-transcription route is untouched.
- **SP result cache** (in-memory, 6 h TTL, max 50): a repeat
  POST for the same URL+mode+language returns an
  instantly-done job and consumes **no** quota and **no**
  rate-limit slot.
- Poll interval **3 s → 1.5 s**.
- **Auto-start:** when a visitor starts a download from the
  format list, the homepage now also kicks off Script+Prompt
  (mode "script") for that video through the **same**
  endpoint — same daily cap, same rate limit, nothing
  bypassed — once per video per session, rendering into the
  Script+Prompt section with a small "started automatically"
  note; failures stay silent so a download never looks broken.
  (Finding: Dahot's in-card script/prompt is hard-coded fake
  sample text — it does not really generate on download.
  QGrab's auto-start is real generation, per the owner's
  order.)

### Measured locally (stubbed Gemini — no real key exists in
this environment; `tests/bench_gemini_speed.py`)

| Measure | Before | After |
|---|---|---|
| SP text-route per-attempt timeout | 100 s | 40 s |
| Worst-case slow-failure bound (text route) | 6 × 100 = 600 s | 6 × 40 = 240 s |
| Typical mixed path (1 slow fail → success, stub schedule 2.0 s + 0.4 s) | 2.40 s | 2.40 s (fast path unchanged) |
| Repeat AI Tools generation | 0.404 s (stub call) | **0.001 s** (cache) |
| Repeat Script+Prompt POST | full job | **~0.001 s**, instantly done |
| Result poll gap | 3 s | 1.5 s |

These are local stub numbers, not live Gemini timings; the
live improvement to verify after deploy is the timeout bound
and the cache behaviour.

## 7. AI Tools speed

Dahot's edge functions and QGrab both call Gemini with a
25 s-class timeout; Dahot's real edges are `thinkingBudget:
0`, small token caps, and silent local fallbacks — there is
**no caching on either side**. QGrab adopts the thinking-off
fix and adds an **AI Tools result cache** (tool + normalized
topic, 6 h TTL, max 100; response carries `"cached": true`;
a hit consumes no daily quota). Pattern verdict: neither
codebase was structurally faster; the wins are the shared
fixes above, applied to both surfaces.

## Tests

- New: `tests/test_dahot_features.py` — **53/53 pass**
  (platform detection/plans, all new pages, eyecare assets,
  config math 2770/5530, welcome/referral once-rules,
  self-referral, payment flow incl. 503-unconfigured and
  approve-409, report gating 404/401/200, ratings
  distribution, AI cache single-call).
- Updated: `tests/test_plans.py` — the 2026-11-08
  announcement-only contract (no form, disabled buttons) is
  **superseded by the owner's 2026-11-16 order**; the test
  now asserts the manual-payment contract, PKR figures and
  the referral box. Prices/trial/refund facts unchanged.
- Cache resets added to `test_aitools.py`, `test_sp_quota.py`,
  `test_sp_jobs.py` via the new `_ai_cache_clear()` /
  `_sp_cache_clear()` helpers (same pattern as the existing
  `_info_cache_clear()`); one stub in
  `test_site_hardening.py` now accepts the cascade's
  `thinking_budget` kwarg.
- **Full suite: all 22 Python test files + 3 JS test files
  pass** (regressions found and fixed during the build:
  missing `import hashlib`; cache leakage across test cases).

## Open items

1. **Owner input needed:** real JazzCash + Easypaisa
   receiving numbers → set `PAYMENT_JAZZCASH_NUMBER` /
   `PAYMENT_EASYPAISA_NUMBER` on Render (and confirm
   `SUPPORT_INBOX_KEY` is set, or the owner inbox/approve/
   reports routes stay hidden by design).
2. Retest Reddit/Vimeo/Dailymotion from the production host
   after deploy; only then upgrade their page wording.
3. New tools-grid cards for the new platforms are English
   only for now (the grid's existing cards use the i18n
   dictionary); Urdu strings can be added with the next i18n
   pass.
4. Nothing was pushed or deployed. Both mirrors
   (`downloader-site`, `qgrab-repo`) are identical; the QGrab
   backup ZIP was refreshed after this build.

---

# ROUND 2 — Dahot-shaped header/hero, Download History, rebuilt Assistant (2026-11-16)

Owner's orders after visiting Dahot Tool (annotated screenshot). APP_VERSION 2026-11-16.14 → (round 3) .16. Nothing deployed live.

## 1. Header (Dahot's shape, QGrab's own identity)
- Logo + wordmark + tagline under the name: **"All Platform Downloads in One Place"**. NOTE: the owner dictated the singular "All Platform Download in One Place"; the grammatically correct plural "Downloads" was shipped, per the build brief.
- Nav: Home · Tools · **Download History** · FAQ · (round 3 adds Telegram Proxies + Invite). Right side keeps the Day/Night/Eye Care toggle + three-dot menu; where Dahot has Login, QGrab showed ⭐ Plans (round 2) — round 3 removed it with the Plans section (see below). No fake login anywhere.
- Hero title in Dahot's shape with QGrab's name: **"Free Video Downloader & Social Media Tools — QGrab"**. Dahot's name appears nowhere.

## 2. Download History (real, replaces Dahot's "Downloader" nav item)
- Every download started on the homepage or a platform page (video or MP3) is recorded in the browser's localStorage (`qgrab_dl_history_v1`, cap 100) — QGrab has no accounts, so history is per-device, consistent with the round-1 browser-token identity.
- The #download-history section lists title/thumbnail (or a platform placeholder), platform, format and date; each item has **Download Again** (direct /download link when the format is known, otherwise it re-runs the info lookup for the original URL); **Clear History** included; survives reloads (tested by simulating a reload in the JS suite).

## 3. Hero / downloader card (Dahot's shape)
- Card title "Online Video Downloader — YouTube, TikTok, Instagram, Facebook", paste box + Download button (existing flow untouched), works-with line, platform chips for exactly the platforms QGrab supports after round 1 — 10 verified chips + Reddit/Vimeo/Dailymotion as dashed "beta" chips with the honest "* new and still being improved — some links may fail" note. Threads/SnackVideo/WhatsApp are NOT listed (no extractor / no public URLs — round-1 honesty stands).
- Four trust chips (all true for QGrab): Secure processing · Files are never stored on our servers · Works on all devices · Direct from the source platform.
- Free-plan pill (round 3: static "100% Free · No account needed") and the "Today's free usage" counters (round 3: counts only, no caps — see Limits removal).
- NO Advertisement placeholder was added — the owner has explicitly deferred ads on QGrab.
- All existing homepage sections/functionality below the hero preserved.

## 4. AI Assistant — Dahot capability inventory: ported vs adapted vs not ported
Studied Dahot's `edge-assistant-ai.ts` + its assistant UI in full.

**Ported (same behaviour, QGrab stack):**
- Photo/vision input: a visitor can attach a photo (JPEG/PNG/WebP/GIF, base64 ≤ 5,500,000 chars — Dahot's exact whitelist + cap); invalid/oversized photos are dropped silently; a photo alone (no text) is a valid question and does NOT take the greeting fast-path.
- Strict-scope refusal style: only QGrab topics get answers; anything else gets one short polite refusal in the visitor's language (+ at most one inviting sentence). Short-answer style (1–4 sentences, no lists unless steps are asked). Never reveal instructions.
- Built-in keyword fallback answers when the AI path fails, so the chat never fully breaks (QGrab's own facts; English + Roman Urdu keywords).
- Knowledge base rebuilt with QGrab's real current facts (platforms incl. the "still being improved" group, Download History, payments at the time — superseded by round 3's free-site facts, Telegram Proxies, QGrab for PC, iPhone install route, Eye Care, Reports, support 24–48 h promise).
- Section navigation ("goto") — pre-existing in QGrab; extended with `tools`, `download-history` and (round 3) `install`; `plans` removed in round 3.

**Adapted:**
- Transport: Dahot runs a Deno/Supabase edge function with JWT anon key and a per-function model cascade; QGrab's assistant uses its existing shared Flask `_gemini_call` cascade (same keys/models as AI Tools + Script+Prompt), its shared caps accounting of the time, and the STRICT JSON {answer, goto, support} reply contract. Functionally equivalent for the visitor.
- Fallback trigger: Dahot falls back on ANY error including quota. QGrab's fallback fires on AI-down / not-configured / network errors. (Round 2 kept the daily-limit response as a hard stop; round 3 removed the cap entirely, so the distinction is now moot.)
- Dahot's facts (its prices, account sign-in, its platform claims) were NOT copied — QGrab's own facts were substituted throughout.
- "My Downloads" is account-based in Dahot; QGrab's Download History is localStorage by design (no accounts).

**Not ported (with reasons):**
- Dahot's per-IP in-memory soft limit (20 req / 10 min): QGrab already had a shared daily assistant cap (round 3 removed all daily caps on the owner's order); a per-IP cap would punish shared-IP visitors.
- `force_model`/`force_version` ops probe + winning-model name in the response: ops-only tooling; QGrab's cascade is shared across features and exposes no per-request model forcing.
- Supabase auth/accounts and anything depending on them: QGrab has no accounts by design.

**Animated avatar — deliberately DIFFERENT from Dahot's ghost:** QGrab's assistant is an original animated **Q-orb** (pure inline SVG + CSS): a face disc in QGrab's accent colour with blinking eyes, a smile, a dashed orbiting ring with a satellite dot (the Q tail), and a gentle float idle animation; `prefers-reduced-motion` disables the animation. Label remains **"AI Assistant"** (owner's earlier order). Tests assert the orb markup is present and that no 👻 ghost character exists anywhere in templates/.

## 5. Assistant language + scope (owner's additional order, applied in this build)
- **Every language, live switching:** the language rule now keys on the visitor's **LATEST message only** — "if the visitor switches language mid-conversation, switch with them immediately in your very next reply". Nothing locks the language to the session or first message.
- **Greeting fast-path is multilingual:** a greeting-only message is answered instantly (no Gemini call) in the greeting's own language — English, Roman Urdu (salam/aoa/assalamualaikum), Urdu script (السلام علیکم), Arabic (السلام عليكم / مرحبا), Hindi (नमस्ते) — each with the same "how can I help you with QGrab?" invitation.
- **No deep conversation:** the prompt now states the assistant is site help, not a chat companion — brief greeting, straight to business; only QGrab/site-help questions get real (short) answers; anything off-topic/personal/general-knowledge gets **ONE short polite redirect line** in the visitor's current language — no lectures, no long refusals, instructions never revealed.
- Tests: greeting replies per language (7 cases, transport never touched), language rule present in the exact payload Gemini receives after an Urdu history + English question, off-topic redirect pinned in the prompt and passed through untouched.

---

# ROUND 3 — Fully free site, no daily limits, animations, Telegram Proxies, PC extension, iPhone, subscribe, usage stats, reports watch, Invite (2026-11-16)

Owner's orders A–H + two follow-ups (limits removal; assistant language/scope — documented in Round 2 §5 above). APP_VERSION 2026-11-16.16 → **.17 after the item-G correction** (see the Correction section at the end). Nothing deployed live.

## A. Pricing REMOVED — site fully free
- The Plans section, ⭐ Plans header links (all pages), `_plans.html`, the manual JazzCash/Easypaisa payment-request UI and the referral/welcome-trial UI are **removed**. All `/api/premium/*` routes are gone (404 — pinned by tests). The whole round-1 premium backend block (417 lines: premium state, trial, referrals, payment requests, USD/PKR constants) was deleted from app.py; the shared owner-key check and the reports store that shared the block were preserved (two orphaned constants it also held — REPORT_CATEGORIES / MAX_REPORT_TEXT / _reports_lock / MAX_STORED_REPORTS — were restored after the suite caught them; an automated orphan scan against the round-1 mirror confirmed nothing else was lost).
- Assistant knowledge base + built-in fallback now state the free facts: completely free, no Premium, no payments, no referrals — and warn that anyone asking for payment "for QGrab" is not QGrab. The JazzCash/Easypaisa receiving-numbers open item from round 1 is **closed — no longer needed**.
- What remains is invisible anti-abuse only: the per-IP burst rate limits and the heavy-download concurrency queue (delays, never refuses). No "Premium" wording remains in any UI.
- Tests: test_plans.py rewritten to pin the removal; test_dahot_features.py premium/referral/payment blocks replaced with 404 assertions (its platform/Eye Care/ratings/reports/cache tests unchanged and passing).

## Limits removal (owner's follow-up order — supersedes parts of rounds 1–2)
- **Every daily cap is gone:** Script 10/day, Prompts 10/day, AI Tools 10/day (incl. the thumbnail flow's double slot), Assistant 30/day. The counters now only COUNT (they feed the homepage usage card and owner stats); reserve functions always succeed; no endpoint returns `daily_limit` anymore, and no "left/max" fields exist in any quota response.
- UI: hero usage card shows counts only ("N today · Unlimited", no cap bars/text); Script+Prompt quota lines read "Scripts/Prompts: free & unlimited — no daily limit"; the AI Tools note reads "Free & unlimited — no daily limit"; assistant replies carry no left/max.
- Upstream Gemini quota/rate failures now surface as friendly busy messages — Assistant: "The AI is busy right now — please try again in a few minutes."; AI Tools likewise; never a "daily limit reached" message.
- Kept (not usage limits): heavy-download concurrency queue; per-IP burst throttles with "please wait" semantics; support/report per-IP abuse limits.
- Tests rewritten: test_sp_quota.py + test_sp_quota_js.js (jobs run past the old cap; failures count nothing), test_aitools.py + test_thumbnail_image.py (generation beyond the old cap works; responses carry used/unlimited), test_assistant.py (no cap; failure = friendly 502), test_tiktok_robustness.py + test_homepage_js.js expectations updated.

## B. Tools animated reveal
- Clicking the nav **Tools** item smooth-scrolls to the AI Tools section and plays a staggered animated reveal of all six AI tool cards (alternating from left/right/top via nth-child keyframes, 90 ms stagger, replays on re-click). Pure CSS/JS, `prefers-reduced-motion` disables it.

## C. Scroll animations site-wide
- IntersectionObserver adds a rise-from-below reveal (`.rv` → `.inview`, small per-element stagger) to sections/cards on all main pages. The `.rv` class is only ever added by JS, so no-JS/no-IO visitors see the page exactly as before; reduced-motion disables the effect. Existing layout/tests unaffected (homepage JS harness passes).

## D. Telegram Proxies page
- New page **/telegram-proxies** (nav link on every page + a Tools-section card on the homepage): heading "Telegram Proxies — Add your Telegram proxy and run without VPN", honest description, "last updated" date, and the note that free public proxies can stop working and the list is refreshed.
- **100 proxies, all real**: sourced during this build from public GitHub MTProto lists (SoliSpirit/mtproto, ALIILAPRO/MTProtoProxy, aviamastersgh/mtproto-free-russia — full sourcing note in `data/PROXIES-SOURCE-NOTE.md`): 933 links found → 370 valid → 134 unique → 100 kept. **Zero invented server/port/secret values.** Each entry is a `https://t.me/proxy?server=…&port=…&secret=…` connect link that opens Telegram's connect prompt. The route re-validates and rebuilds every link server-side; tests round-trip all 100 links (server/port/secret) and pin the 50–100 count.
- Note: ~458 further real links exist in the same sources with base64-format secrets; they were excluded by the hex-format validation rule and can be added later if wanted.

## E. QGrab for PC — IDM-style browser extension
- Chrome/Edge **Manifest V3** extension in `extension/`: a floating QGrab panel on YouTube and Facebook video pages (floating, not injected into Facebook's DOM, so redesigns hurt less); the background service worker calls QGrab's real `/api/info` and the panel lists real format choices linking to QGrab's `/download`, plus an "Open in QGrab" handoff (the homepage now honours `?url=` prefill). Popup + README with honest manual install steps (chrome://extensions → Developer mode → Load unpacked).
- Packaged as `static/downloads/qgrab-extension.zip` (manifest.json at the zip root) and offered from the new homepage section **"QGrab for PC — IDM-style downloader"**, whose copy is explicit that it is a browser extension and **not on the Chrome Web Store yet**.
- Tested locally: URL-detection logic 17/17 unit tests (YouTube watch/Shorts/youtu.be, Facebook watch/reel/videos, nulls for non-video pages), all JS syntax-checked, zip contents verified. Limits: cannot be click-tested in a real browser from this build environment; Facebook DOM changes may affect page detection (URL-based, so risk is low); no Web Store listing/signing yet.

## F. iPhone option
- The Install section now carries an **iPhone / iOS card** with the real PWA route — Safari → Share → **Add to Home Screen** — and states plainly that QGrab is **not on the App Store**; the installed web app opens like a normal app. The assistant's knowledge base teaches the same route.

## Email subscribe system (owner's follow-up order)
- **Subscribe forms** in the footer (every page) and a homepage section, each with the privacy line "One email a day with QGrab updates. Unsubscribe anytime." No accounts — email only.
- **Auto-prompt:** when a visitor's Download History reaches their **3rd download**, a friendly popup offers the daily-updates subscription (email field + Subscribe + "Not now"). Once per visitor: subscribed → never again; dismissed → re-show only after 7 days. Decision logic is a pure, unit-tested function.
- **Backend:** `POST /api/subscribe` (format-validated, deduped case-insensitively, per-IP daily abuse cap; stores email + source + timestamp + a random unsubscribe token in `data/subscribers.json`, the reports/ratings pattern). Owner list + CSV export at `GET /api/subscribe/inbox` behind the shared owner key; tokens never exposed. `GET /api/unsubscribe?token=…` removes exactly that subscriber (friendly HTML confirmation; bad token = 404).
- **Daily digest:** `_build_digest_html()` produces the branded "What's new on QGrab" HTML email (updates list + tip + per-subscriber unsubscribe link). `_send_digest()` sends via **Resend only when `RESEND_API_KEY` is set in the environment** (sender overridable via `QGRAB_DIGEST_FROM`); unconfigured it safely no-ops and logs — no key is hardcoded anywhere. Sending is owner-triggered (`POST /api/subscribe/send-digest`, owner key). **Nothing was sent to anyone in this build**; tests stub the transport. The owner switches daily sending on after go-live.

## Per-feature usage tracking (owner's follow-up order)
- Daily aggregate counters only ({date → event → count} in `data/stats.json`, pruned at ~400 days) — no personal data, no per-user profiles. GA4 tag untouched.
- Server-side counts (in the real handlers): downloads by platform (in the /download gate), Script/Prompt generations, each AI Tool + thumbnail image, Assistant questions, searches by platform, subscribes, low ratings, report submissions.
- Client-side counts via `POST /api/event` (fire-and-forget `qgStat()`, whitelisted names, can never break the feature): proxy connects, Download History view / Download Again / Clear, extension ZIP downloads, iOS card clicks, app-install clicks, Invite opens and every share channel.
- Owner view: `GET /api/stats` (shared owner key) returns all-time totals + last-7-days + last-30-days as most-used-first pair lists (lists, because Flask's jsonify sorts object keys alphabetically — caught by tests).
- Tests: event increments, unknown-event 400, owner gating, window math, sorted output, and features working immediately after a garbage event call.

## G. Reports & low-rating watch — AS CORRECTED by the owner (see the Correction section at the end; the original "ask why" part of G was cancelled)
- **Ratings are stars-only, exactly as before round 3.** Visitors are NEVER asked why they rated low: no prompt, no reason chips, no reason field — and the server ignores any reason fields a client still sends (never stored). *(The originally-built "What went wrong?" prompt was fully removed by the owner's correction — details in the Correction section below.)*
- **Reports form:** unchanged from round 1 apart from the prominent detail field ("What exactly is not working?" label, larger box — this is the visitor's own voluntary form, not a follow-up question); round-1 categories unchanged. Whatever a visitor voluntarily writes is read by the owner/Archer only.
- **Owner digest:** `GET /api/attention` (owner key) returns the combined **"Needs attention"** summary — reports from the last 7 days (count + latest 20) and low-rating **counts** + newest-first entries (stars/text/date only, no reasons). The same summary is embedded in the reports inbox and support inbox responses.
- report_submitted + rating_low are counted in the usage stats. (Standing workflow after go-live: Archer reads reports himself, fixes the site silently, and reports aggregate summaries to the owner — no visitor is ever contacted about a complaint.)

## H. Invite / Share section
- **Invite** nav item on every page + a homepage **Invite** section. Clicking opens `navigator.share` where available; otherwise QGrab's own share popup with: **WhatsApp** (wa.me), **Telegram** (t.me/share), **Facebook** (sharer), **X** (intent/tweet), **Email** (mailto:) — all with the friendly prefilled text "Download videos from YouTube, TikTok, Instagram & more — free, no limits: QGrab" + the site link — plus **Copy Link** (clipboard, "Copied ✓" feedback) and a **Download / Install App** option inside the same popup (fires the existing PWA install prompt when available, else scrolls to the Install section).
- Analytics: invite_click + share_native / share_whatsapp / share_telegram / share_facebook / share_x / share_email / share_copy / invite_install_click are all counted.
- Tests: the pure link builder's URLs are asserted character-for-character (encoding included), the popup renders all seven options, and invite clicks fire their events.

## Test results (full suite, final)
- Python: 27 test files — ALL PASS (incl. new test_round2, test_round3, test_subscribe, test_stats, test_attention; test_plans / test_sp_quota / test_aitools / test_assistant / test_thumbnail_image / test_remove_sections / test_app_version / test_tiktok_robustness updated where rounds 2–3 superseded the old contracts — each such change is noted in the test file itself).
- JS: 6 suites — ALL PASS (homepage harness, SP jobs, SP quota, history, subscribe popup logic, invite/share).
- Extension: 17/17 logic tests + syntax checks.
- Fixed during this build (caught by the suite): two groups of orphaned names from the removed premium block (REPORT_CATEGORIES, MAX_REPORT_TEXT, _reports_lock, MAX_STORED_REPORTS) restored; Flask's alphabetical jsonify key order defeating the stats sort (switched to pair lists).

## Not deployed
Nothing in rounds 2–3 is live. Deploy still needs only the owner's "live kar do" — the round-1 blocker (JazzCash/Easypaisa numbers) no longer exists. Reddit/Vimeo/Dailymotion still need their production-host retest after deploy. Optional owner follow-ups: set RESEND_API_KEY (+ QGRAB_DIGEST_FROM) on Render to enable digest sending; decide whether base64-secret proxies should join the Telegram list.

---

# CORRECTION — Item G override (owner, 2026-11-16): DO NOT ask visitors anything

The owner cancelled the "ask why" part of item G after it was built: **never ask any visitor why they rated low or why they complained, and never message public/anonymous visitors about their complaints.** Applied in this same pass (APP_VERSION **2026-11-16.17**):

- **Removed from the UI** (`templates/_reviews.html`): the entire "What went wrong?" block — the prompt, the five reason chips (Download failed / Too slow / Wrong result / Hard to use / Other) and the optional reason text field — plus all its JS (chip selection, show-on-low-rating toggle, reason payload). Ratings are back to **stars + optional name + optional free text only**, exactly as before round 3.
- **Removed from the backend** (`app.py`): the `RATING_REASONS` constant and all reason/reason_text handling in `POST /api/rate` — any reason fields a stale or crafted client still sends are now **ignored, never stored**. `_needs_attention()` no longer emits reason fields; its `low_ratings` entries carry stars/text/name/date only.
- **Removed CSS** (`templates/_extras.html`): the `.reason-chips` / `.reason-chip` styles.
- **What stays from G:** the Reports form as it is (categories + prominent voluntary detail field — read by the owner/Archer only); the owner-only "Needs attention" digest (`GET /api/attention` + embedded in the reports and support inboxes) with **counts** — `reports_total`, `new_reports_7d`, `low_ratings_total` — and newest-first entries; the `rating_low` / `report_submitted` analytics counts. There is **no visitor-facing follow-up, questioning, or apology flow anywhere** in the build.
- **Tests updated:** `tests/test_attention.py` rewritten to the corrected contract — low rating stores stars only even when reason fields are sent, high rating stores no reason, the UI contains no prompt/chips/fields, `RATING_REASONS` no longer exists, the digest shows counts with NO reason fields, inboxes carry the summary, analytics still counted. **Full suite re-run after the correction: 27 Python files + 6 JS suites + extension 17/17 — ALL PASS.** Mirrors re-synced and the backup ZIP refreshed. Still **no live deploy**.

---

# SEO PASS (owner, 2026-11-16) — APP_VERSION 2026-11-16.18

Owner's goal: when anyone searches Google for "video download", "video downloader", "video download without watermark", "download TikTok video without watermark", "YouTube video download" and the like, QGrab should be able to appear — with the words "without watermark" carried on the site. Built on top of rounds 2–3 + the Item-G correction. **Nothing deployed live.**

## What was weak (audit findings)
- **`/telegram-proxies` was missing from the sitemap** (the only indexable page not listed) and its template had **no hreflang alternates and no FAQ/structured data**.
- **The legal pages (Terms / Privacy / DMCA) had no Open Graph / Twitter tags at all.**
- **Platform pages carried only FAQPage JSON-LD** — no WebApplication block; the Script+Prompt tool page had no JSON-LD at all.
- **Homepage title/description** led with the brand and never used "online" or "without watermark"; the keywords meta lacked the exact phrases people type ("video download without watermark", "download tiktok video without watermark", "online video downloader"...).
- **The homepage FAQ never answered the two questions this pass targets** — "How do I download a video without a watermark?" and "Does QGrab work on iPhone?" (the phones answer mentioned iPhone only in passing).
- **Non-TikTok platform pages never mentioned watermarks at all**, so they could not match "without watermark" searches even though the honest claim exists (QGrab never adds one).
- **Internal linking was thin**: the hero platform chips were plain `<span>`s (no links), the "supported platforms" grid items were `<div>`s, Telegram was missing from that grid, and the footer linked only 4 of the 12 downloader pages and none of the tool landing pages.
- **Title suffixes were inconsistent** — platform/tool titles ended "| QGrab" while the rest of the site uses "— QGrab".
- **robots.txt** let crawlers wander into `/api/` and `/download`.

## What changed
- **Homepage** (`templates/index.html`): title is now "QGrab — Free Online Video Downloader | Download Videos Without Watermark"; description rewritten around "download videos free online … TikTok downloads without a watermark"; keywords meta extended with the exact search phrases; OG/Twitter mirror the new title/description; the WebApplication JSON-LD description now says "no watermark on supported platforms like TikTok" and its featureList covers the new platform downloaders.
- **Homepage FAQ** (`i18n.py`): two new entries — "How do I download a video without a watermark?" (honest answer: QGrab saves the original file and never adds a watermark; TikTok comes out completely clean; a watermark burned in by the creator is part of the picture) and "Does QGrab work on iPhone?" — wired into `HOME_FAQ_KEYS`, so they render visibly AND in the FAQPage JSON-LD. They are English-only for now: `get_strings()` merges over English, so the other 29 languages show these two Q&As in English until translated (the site's established fallback pattern).
- **Platform pages** (`app.py` PLATFORM_PAGES): every title suffix unified to "— QGrab"; descriptions for YouTube, Facebook, Instagram, Pinterest, X, Reddit, Vimeo, Twitch, Dailymotion and Telegram strengthened with "free online" + the precise claim "QGrab never adds a watermark". A shared FAQ — "Does QGrab add a watermark to downloads?" — is appended to all ten video downloader pages; TikTok additionally gets the exact-match "How do I download a TikTok video without a watermark?"; SoundCloud gets the audio-honest variant "Does QGrab change or brand the audio?". Every platform page now also emits a **WebApplication JSON-LD** block (built in `_platform_view` from the page's own title/description, so it cannot drift).
- **Script+Prompt tool page** (`templates/scriptprompt.html`): title suffix unified; a WebApplication JSON-LD block added.
- **Telegram Proxies page** (`templates/proxies.html` + route): title is now "Telegram Proxies — Free MTProto Proxy List, No VPN Needed — QGrab" (OG/Twitter match), description targets "telegram proxy list", hreflang alternates added, and a visible FAQ section (how to connect, using Telegram without a VPN, free?, why a proxy stopped working) renders with matching **FAQPage JSON-LD** built from the same pairs.
- **Legal pages**: full OG/Twitter meta added to Terms, Privacy and DMCA.
- **Sitemap**: `/telegram-proxies` added at priority 0.7 (20 URLs total: home 1.0, 14 platform/tool landings 0.9, Script+Prompt tool 0.8, proxies 0.7, legal 0.3). **robots.txt** now also has `Disallow: /api/` and `Disallow: /download`.
- **Internal linking**: hero chips are now real anchors to their downloader pages (VK stays a span — it has no page; the beta chips link too, honesty note kept); the supported-platforms grid items became links and a Telegram item was added; the footer now links **all 12 downloader pages** plus the Video Script Generator, AI Video Prompt Generator and Telegram Proxies pages with descriptive anchor text. `tests/test_round2.py` chip assertions were updated to the anchor markup (same intent — chips present, beta honesty, no Threads/SnackVideo/WhatsApp).
- **Brand signals verified intact**: favicon + apple-touch-icon links, theme-color metas, manifest reference and the "— QGrab" suffix pattern are consistent across all templates after the rounds 2–3 changes. The assistant panel's hardcoded version label was bumped with APP_VERSION (it is a static fallback the JS refreshes from /api/version).

## Tests
- **New `tests/test_seo.py` — 224 checks, ALL PASS**: every indexable page serves 200 with a unique branded title and a unique sane-length description; canonical + og:title correct everywhere; sitemap lists all 20 routes and every listed URL serves 200; robots contents; every JSON-LD block on every page parses and the expected types sit on the right pages; the targeted FAQ questions are present in the visible FAQ and the FAQPage JSON-LD (homepage watermark + iPhone, TikTok exact-match, per-platform watermark, SoundCloud, proxies no-VPN); hero chips and footer links are real anchors to every downloader/tool page.
- **Full suite re-run: 28 Python files + 6 JS suites — ALL PASS** (test_assistant's version-label assertion caught the APP_VERSION bump; the static label in `_assistant.html` was updated to match, per the codebase pattern).

## Honest expectations
This pass only makes the pages *eligible* and well-matched — it does not buy rankings. After the owner says "live kar do" and this build deploys, the updated sitemap needs **resubmitting in Google Search Console** (the owner's chosen route — no manual per-URL indexing requests), and rankings for competitive phrases like "video downloader" take weeks to months of Google re-crawling, judging and comparing against long-established downloader sites. Expect the long-tail, exact-phrase pages (TikTok without watermark, the per-platform pages, Telegram proxies) to surface first; the homepage's generic phrases are the slowest. Nothing here guarantees a position — anyone who promises one is guessing.

---

# Release 2026-11-16.19 — Tagline correction (owner's exact words) + GO LIVE

- **Tagline fixed (owner's correction, 2026-11-16):** the header tagline
  shipped in rounds 2–3 as "All Platform Downloads in One Place". The
  owner corrected it: QGrab does not offer *platform* downloads, it
  offers each platform's **Video** download in one place. The tagline
  now reads, exactly as dictated — **"All Platform Video Download in
  One Place"** (singular "Download", with "Video") — in all four
  templates that carry the header (index, platform, scriptprompt,
  proxies) and in the round-2 tests that pin it.
- **APP_VERSION bumped 2026-11-16.18 → 2026-11-16.19** per the
  documented procedure (app.py + tests/test_app_version.py + the
  Assistant panel's static version label).
- **Full suite re-run after the fix: 28 Python files + 6 JS suites +
  extension logic 17/17 — ALL PASS.**
- This release is the one the owner authorized with "jab sab clear ho
  jaye to live kar dena, main check karunga" — rounds 1–3, the item-G
  correction, the SEO pass and this tagline fix go live together.

---

# Release 2026-11-16.20 — Assistant attach-button preview chip (owner's Dahot screenshot)

- The owner screenshotted Dahot's assistant and circled the 📎
  paperclip: a visitor attaches a SCREENSHOT of their issue and
  asks about it. QGrab's round-2 port already had the visible
  📎 button in the composer strip and the full photo/vision
  flow (photo-only questions included). The one missing piece
  was visual confirmation of WHAT was attached.
- **Added: preview chip** above the composer — thumbnail of the
  attached photo + its file name + a ✕ remove button
  (`#asstChip` in `_assistant.html`, wiring in
  `_assistantjs.html`, styles in `_extras.html`). Removing the
  photo before Send is now possible; the chip clears itself on
  a successful/fallback send and stays (with the photo) after a
  hard error so the visitor can retry. Unchanged: 4 MB client
  cap under the server's base64 cap, whitelisted mimes,
  silent-drop of invalid photos, site-help scope, and the
  latest-message language rule for answers about the screenshot.
- **Tests:** `tests/test_assistant.py` 26 → 29 — new
  `test_widget_attach_button_and_preview_chip` (button inside
  the composer form on all three widget pages, accept list,
  chip markup/CSS/JS wiring), `test_assistant_photo_only_question`
  (empty message + photo reaches Gemini as an inline part with
  the explicit no-question line), and
  `test_assistant_photo_with_text_and_invalid_dropped`.
  Full suite re-run: 28 Python files + 6 JS suites + extension
  17/17 — ALL PASS. APP_VERSION .19 → .20.

---

# Release 2026-11-16.21 — Telegram Proxies page empty on live: deploy-proof fix

- **Symptom:** after .20 went live, /telegram-proxies rendered
  **0 proxies** ("list is being refreshed") although the round-3
  snapshot (100 real MTProto proxies, updated 2026-11-16) existed
  locally and had been pushed to GitHub in the .19 batches.
- **Root cause (two layers):** the route read ONLY
  `data/proxies.json`. (1) `data/` is git-ignored runtime state,
  so the file's presence in the repo was incidental, never
  guaranteed; (2) decisively, `deploy/Dockerfile` copies only
  `app.py`, `i18n.py`, `templates/` and `static/` into the image
  and creates an EMPTY `/app/data` — the proxy list never entered
  the production image at all, so the open() failed and the
  route honestly served its empty fallback.
- **Fix:** the snapshot now ships WITH the code in two places —
  `bundled_data/proxies.json` (new top-level folder, not
  git-ignored; the Dockerfile gained `COPY bundled_data
  ./bundled_data`) and `static/bundled/proxies.json` (static/ is
  copied into the image unconditionally, so this copy survives
  even a Dockerfile regression). `_load_proxy_list()` tries, in
  order: runtime `data/proxies.json` (a future refreshed list
  still wins), then `bundled_data/`, then `static/bundled/` —
  first file yielding ≥1 valid entry wins; entry validation is
  unchanged, and if every candidate is missing the page still
  serves the honest empty state rather than inventing data.
  Both bundled copies are byte-identical to the round-3
  snapshot (100 proxies, "updated": 2026-11-16), and the
  sourcing note ships alongside as
  `bundled_data/PROXIES-SOURCE-NOTE.md`.
- **Tests:** new `tests/test_proxies_fallback.py` (12 checks):
  bundled copies complete/identical/dated, Dockerfile COPY
  present, loader order, fallback when the runtime file is
  missing, honest empty when all are missing, and the route
  rendering all 100 from the fallback alone. A production
  simulation (clean repo copy with `data/proxies.json` deleted,
  i.e. the live image's exact condition) renders 100 proxies.
  **Full suite: 29 Python files + 6 JS suites + extension
  17/17 — ALL PASS.** APP_VERSION .20 → .21. Mirrors re-synced,
  backup ZIP refreshed.

---

# Release 2026-11-16.22 — HLS downloads remuxed (Dailymotion fix) + Vimeo graduated

- **Production retest of .21 (parent, live):** Vimeo FULLY works
  (info + a real MP4 download verified); Reddit still fails from
  the production host (the platform limits the server IP — its
  honesty note stays); Dailymotion /api/info works (2 HLS
  formats) but /download delivered the raw .m3u8 playlist
  (375 bytes) instead of a video.
- **HLS fix (app.py):** `_download_impl` now detects an HLS
  format up front (`_is_hls_target`: protocol m3u8*, ext m3u8,
  or a URL ending in .m3u8) and routes it to `_download_hls`
  instead of the byte proxy: ffmpeg reads the playlist and
  writes ONE real MP4 (`-c copy`, no re-encode;
  `_ffmpeg_remux_url`, 300 s timeout, and the output is
  rejected if it is itself a playlist). If ffmpeg is
  missing/fails, yt-dlp's native HLS download
  (`_download_via_ytdlp`) is the fallback; if that fails too,
  the visitor gets the site's friendly error (502 +
  FRIENDLY_ERROR) — the raw playlist is never served. The
  remux runs inside the existing heavy-download slot (queue
  behaviour unchanged) and its temp dir is removed when the
  response closes, so disk use stays bounded to one file per
  download. Dailymotion's "still being improved" note STAYS in
  this release — it comes off only after the parent verifies
  this fix live.
- **Vimeo graduated:** the "New — Still Being Improved"
  section is removed from the Vimeo platform page, the
  homepage works-note now names only Reddit and Dailymotion,
  Vimeo's hero chip lost its beta asterisk, and the Assistant
  knowledge base lists Vimeo with the working platforms.
  Reddit's and Dailymotion's notes are unchanged.
- **Tests:** new `tests/test_hls_download.py` (7 tests): HLS
  detection variants; a simulated m3u8 format through
  /download asserting the video/mp4 content type, the exact
  remuxed bytes and an .mp4 filename (with the raw proxy
  rigged to fail the test if it is used); the yt-dlp fallback
  path; the failure path asserting 502 + the friendly error
  and no playlist bytes; a non-HLS regression (a plain MP4
  format is still proxied, with the remux rigged to fail if
  used); and the remux guard exercised end-to-end against
  fake ffmpeg executables (playlist output rejected, real
  MP4 accepted). The real ffmpeg remux was also smoke-tested
  locally against a generated HLS stream (valid MP4,
  h264 + aac). Pinned KB/chip expectations updated in
  test_assistant.py and test_round2.py. **Full suite:
  30 Python files + 6 JS suites + extension 17/17 — ALL
  PASS.** APP_VERSION .21 → .22. Mirrors re-synced, backup
  ZIP refreshed.

# Release 2026-11-16.23 — Dailymotion graduated (note cleanup only)

- **Dailymotion graduated:** the parent live-verified the .22
  HLS fix on production — a Dailymotion download now delivers
  a real MP4 (video/mp4, ~12.4 MB, ftyp header) instead of
  the 375-byte playlist — so Dailymotion leaves the "new and
  still being improved" group everywhere, with exactly the
  treatment Vimeo got in .22: the "New — Still Being
  Improved" section is removed from the Dailymotion platform
  page, the homepage works-note now names Reddit only
  ("* Reddit is new and still being improved — some links
  may fail."), Dailymotion's hero chip lost its beta class
  and asterisk, and the Assistant knowledge base lists
  Dailymotion with the working platforms.
- **Reddit unchanged:** Reddit still fails from the
  production host (platform-side limit), so its platform-page
  note, beta chip and KB mention stay exactly as they were —
  it is now the only platform in the improving group.
- **Tests:** pinned KB/chip expectations updated in
  test_assistant.py and test_round2.py; version stamps in
  test_app_version.py and test_seo.py. **Full suite:
  30 Python files + 6 JS suites + extension 17/17 — ALL
  PASS.** APP_VERSION .22 → .23. Mirrors re-synced, backup
  ZIP refreshed. Push + manual Render deploy + live check
  are the parent's steps (auto-deploy webhook still broken).

# Release 2026-11-16.24 — Owner-verdict fixes: layout root cause, Tools Hub, subscribe proportions, header lockup, platform logos

The owner checked the live site and reported: content squeezed
with run-on chips overflowing the hero card, trust lines run
together, "Tool uses0 today", a broken-looking Subscribe form,
the header showing name + tagline as one big line, the Tools
nav landing on a single tool, weak animations, and platforms
shown as plain text names. All fixed:

- **ROOT CAUSE (one bug behind most of it):** the Round-2
  comment at the top of the Round-2 block in
  templates/_extras.html was never closed (`/* ===== Round 2
  ... =====` with no `*/`). It swallowed the ENTIRE Round-2
  CSS block — .logo .brand-text, .tagline, .hnav .nav-link,
  .pchip-row/.pchip, .tchip, .plan-pill, .usage-card/
  .usage-row, .hist-* — on every page (30 `/*` vs 29 `*/`).
  The markup was always correct; the styles were commented
  out, so chips/trust/counters rendered as unstyled run-on
  text. The comment is closed, and tests/test_round4.py now
  pins comment balance for every template so this class of
  bug can never ship silently again.
- **Header lockup:** with the CSS revived, the header is the
  intended lockup — logo + big "QGrab" with "All Platform
  Video Download in One Place" as a small muted subtitle
  UNDER the name (.tagline display:block, .68rem). SEO
  <title> tags untouched.
- **Subscribe proportions (owner: they were inverted):** the
  email input is now the wide element and the button compact.
  Two leaks fixed: the pages' global @media (max-width:560px)
  .btn{width:100%} rule used to hit .sub-row .btn (flex:none +
  width:100% claimed the row and squeezed the flex:1 input
  to a sliver — the same leak the assistant composer was
  hardened against in 2026-11-08.7); .sub-row .btn is now
  {flex:0 0 auto;width:auto} (higher specificity), the row
  wraps, and on mobile the input takes its own full-width
  line with the button compact beneath. Verified by
  measurement: desktop input 391px / button 121px; mobile
  input 312px / button 121px (footer form likewise).
- **Tools Hub (the owner's original instruction):** nav
  "Tools" now opens #tools-hub on the homepage — a chooser
  listing EVERY tool in the app, grouped: AI Tools (Title,
  Tags, Hashtag, Channel Name, Keyword Suggestions,
  Thumbnail Idea), Video Toolkit (Video Details, Thumbnail
  Downloader, Hashtag Extractor, Video Tags Extractor),
  Script + Prompt. 11 cards, each icon + name + one-liner;
  AI cards also pre-select their generator. All pages' nav
  (and the footer link) point to the hub.
- **Animations enhanced:** hub cards pop in with the
  staggered L/R/U entrances (alternating by column, 90ms
  stagger) replaying on every nav-Tools click; cards and
  buttons gained lift + glow hovers; all transform/opacity,
  prefers-reduced-motion safe.
- **Platform logos:** hero chips and the supported-platforms
  grid now carry real brand icons next to every name
  (YouTube play, TikTok note, Instagram camera, Facebook f,
  X, Pinterest P, SoundCloud cloud+bars, Twitch glyph,
  Telegram plane, VK badge, Reddit Snoo, Vimeo V,
  Dailymotion D). Also fixed a garbled grid pair: the VK
  pill's markup was inside the Pinterest link and vice
  versa — Pinterest now has its own icon/link, VK its own
  pill.
- **Overflow audit (same class of bug):** the footer grid
  pushed the whole page ~93px sideways at 390px (1fr tracks
  can't shrink below the longest unbreakable link). Fixed
  with .foot-grid>*{min-width:0} + link overflow-wrap.
  Measured horizontal overflow after the fix: 0px at 1280
  and 0px at 390 (homepage and platform page).
- **Verification (the new gate):** local build rendered and
  screenshotted at 1280 AND 390 — homepage top (header,
  hero card + icon chips, usage counters), the Tools Hub,
  both Subscribe forms, the platforms grid and a platform
  page — eyeballed clean; nav-Tools click, hub pop replay
  and AI pre-select exercised in a real headless browser.
- **Tests:** new tests/test_round4.py (comment balance,
  live-CSS pins, hub completeness cross-checked against the
  real tool grids, nav destinations, chip icons, grid
  un-garbling); pinned chip-markup expectations updated in
  test_round2.py / test_seo.py for the icon-carrying chips.
  **Full suite: 31 Python files + 6 JS suites + extension
  17/17 — ALL PASS.** APP_VERSION .23 → .24. Mirrors
  re-synced, backup ZIP refreshed. Push + manual Render
  deploy + live check are the parent's steps.
