# QGrab — Search Videos Feature + SP Daily Caps 10 (Build Report)

Date: 2026-11-08 (PKT). Status: **BUILT + TESTED LOCALLY ONLY.**
Nothing pushed to GitHub, nothing deployed to Render, no account/login touched.
Parent: push + deploy after warning the owner about the approval card.

---

## 1. What was built — "Search Videos" (owner's exact design)

Homepage section `#search-videos`, placed immediately below the main hero
downloader tool (`.grab`), before the Script+Prompt section:

- Heading **"Search Videos"** (English — see i18n note §5).
- **Four platform tabs, owner's order: YouTube, Facebook, TikTok, Instagram**
  — brand icons/colours, clear active state. Clicking a tab only selects the
  search target; there is **no paste-link mode on any tab**.
- **One search bar + Search button** below the tabs.
- **Results grid**: card per video = thumbnail (or a clean platform-name
  placeholder when the source gives none), title, author/channel,
  duration/views/published when available.
- **Two buttons under every card:**
  - **Watch** — on-site player modal: YouTube `youtube-nocookie.com/embed/<id>`,
    TikTok `tiktok.com/embed/v2/<id>`, Facebook
    `facebook.com/plugins/video.php?href=<url>`, Instagram
    `instagram.com/reel/<code>/embed` (or `/p/`). Close button, backdrop
    click and Escape all stop playback (iframe src cleared).
  - **Download** — reuses the existing flow exactly: the video's URL is put
    into the main downloader's input, the page scrolls to it, and the main
    form is submitted → existing `/api/info` lookup → existing format list →
    existing `/download` proxy. No parallel download path was invented.
- All result titles/authors are injected with `textContent`
  (search results are untrusted text; nothing is concatenated into HTML).
- Responsive (tabs 4-across → 2-across, grid auto-fill), dark/light theme via
  the page's existing CSS variables, vanilla JS only, no external libraries.

### Backend — new endpoint `GET /api/search?platform=<p>&q=<text>`

- `platform` validated against {youtube, facebook, tiktok, instagram}
  (else 400); `q` required (else 400), stripped, capped at 100 chars.
- Max **12 results**; per-source timeout **≤15 s**; in-memory cache
  (key `platform|q.lower()`, ~5 min, successes only) in the style of the
  existing info cache.
- **Public sources only — no logins, no cookies, no accounts, ever.**
- A platform whose source answers nothing usable returns HTTP 200
  `{"ok": false, "platform": <p>, "reason": "unavailable", "results": []}`;
  the UI then shows, in plain English: *"Search is not available for
  <Platform> yet — paste the video link in the downloader above to download it."*

---

## 2. Per-platform source + live-smoke evidence

Smoke method: Flask `test_client` against the real endpoint code, run from
the sandbox on 2026-11-08 ~03:00 PKT. **Sandbox network ≠ Render** — verdicts
below are what the sandbox saw; TikTok in particular may behave differently
from Render's IP (the existing tikwm single-video resolver works live on
Render today).

### YouTube — ✅ WORKS
- Source: each `INVIDIOUS_INSTANCES` base, `GET <base>/api/v1/search?q=<q>&type=video`
  (default instance `https://yt.chocolatemoo53.com`).
- Smoke: `q="funny cat"` → **HTTP 200, ok:true, 12 real results**, e.g.
  "The Funniest CATS of 2026...So Far 😂 TOP Funny Cats Video" —
  `https://www.youtube.com/watch?v=MIW2VPprnLw`. Thumbnails use
  `i.ytimg.com/vi/<id>/hqdefault.jpg`.

### Instagram — ✅ WORKS (via Bing)
- Sources tried, in order: (a) DuckDuckGo html `site:instagram.com/reel <q>`;
  (b) Bing web search `site:instagram.com/reel OR site:instagram.com/p <q>`.
- DuckDuckGo html: returned a ~14 KB **bot-anomaly page** (`result__a` count 0)
  from the sandbox — route dead here.
- Bing: works **after unwrapping Bing's `/ck/a?u=a1<base64>` redirect links**
  (the parser now unwraps them — without that, zero results pass the filter).
- Smoke (final code): `q="funny cat reel"` → **10 real results**, e.g.
  `https://www.instagram.com/reel/DLpBXhHIf6H/`,
  `https://www.instagram.com/reel/DN5kN0fCU8V/`; `q="dance"` → **10 results**,
  e.g. `https://www.instagram.com/reel/DfKD26Vvj_A/`. No thumbnails from this
  source → UI shows the platform placeholder, as designed.
- Note: Bing's site:-scoping is inconsistent — some query phrasings returned
  0 in earlier probes; the shipped template + unwrap is what produced the
  results above.

### Facebook — ✅ WORKED in final smoke (flaky source)
- Sources tried, in order: (a) DuckDuckGo html `site:facebook.com <q> video`
  — same bot-anomaly page as Instagram, 0 results; (b) Bing web search
  `site:facebook.com/watch OR site:facebook.com/reel <q>` (with the ck/a
  unwrap); (c) additionally probed: Bing **Videos** search
  (`bing.com/videos/search`) — page loads (~395 KB) but contains **no**
  facebook.com/watch or /reel URLs at all; not shipped.
- Earlier probes (several query phrasings, pre-unwrap parser) returned 0.
- **Final smoke with shipped code**: `q="funny cat"` → **ok:true, 5 real
  results**, e.g. `https://www.facebook.com/AFV/videos/funny-cat-videos/2469165776719008/`
  and `https://www.facebook.com/reel/765251826259677/`.
- Honest limit: this source is **inconsistent** — expect occasional
  "unavailable" answers on Facebook even after deploy; the UI message covers
  that case truthfully. No thumbnails (placeholder), as designed.

### TikTok — ❌ UNAVAILABLE from the sandbox (403)
- Source: `GET https://www.tikwm.com/api/feed/search?keywords=<q>&count=12&cursor=0&web=1&hd=1`,
  fetched with the app's impersonated `_http_get_text` (curl_cffi
  `impersonate="chrome"` first), exactly as specified.
- Smoke: **every query tried ("funny cat", "dance", "comedy") raised
  `HTTPError 403: Forbidden`** — tikwm answered with its Cloudflare block
  rather than JSON. The endpoint therefore returns the structured
  `ok:false / reason:"unavailable"` for TikTok and the UI shows the friendly
  note. The shaper + endpoint path are fully built and unit-tested with
  canned tikwm JSON, so if tikwm answers from Render's IP (its single-video
  resolver does work there today), TikTok search will light up with **no
  further code change**. Do not promise the owner TikTok search works until
  it is re-smoked on the live deploy.

---

## 3. Script+Prompt daily caps: 150 → 10 (owner order 2026-11-08)

Folded into this same build, per the owner's additional order:

- `app.py`: `SP_DAILY_CAP_SCRIPT = 10`, `SP_DAILY_CAP_PROMPTS = 10`.
  The adjacent derivation comment now records the decision (originally
  150/mode from the ~360/day stacked free-quota floor; **deliberately
  lowered to 10/day each by owner order 2026-11-08**).
- Everything else about the quota system is unchanged: reserve-on-POST,
  refund on error, in-memory counters, Google-quota-day (America/Los_Angeles)
  rollover, 429 `daily_limit` behaviour. The separate per-IP audio soft
  limit was **not** touched.
- Homepage counters verified **dynamic**: `templates/_sptool.html` renders
  empty counter divs filled from `GET /api/script-prompt/quota` — no static
  "150" text existed anywhere in templates; nothing to fix there. Live
  check after the change: quota endpoint returns
  `script_left 10, prompts_left 10, script_max 10, prompts_max 10`.
- Tests updated: `tests/test_sp_quota.py` (150→10, 149→9; the rollover
  test's seed counts 40/55 → 4/5 with left 6/5 so they stay under the new
  cap) and the JS fixtures `tests/test_sp_quota_js.js` +
  `tests/test_homepage_js.js` (stub quota values 150/149 → 10/9 so the
  fixtures match production caps).

---

## 4. Tests — all passing

- **New** `tests/test_search.py` — **9 tests pass** (master + mirror):
  YouTube shaper (+12-result cap), TikTok shaper, FB/IG web-search shaper
  (filtering, dedupe, embed URLs), DDG unwrap, endpoint validation
  (missing q → 400, bad platform → 400, failing source → structured 200
  `ok:false`), success + cache behaviour. No live network in tests
  (sources monkeypatched).
- **Full existing Python suite** — all files pass, including
  `test_sp_quota.py` (**ALL SP QUOTA TESTS PASS** with the new caps),
  `test_audit_regressions.py`, `test_lang_switch.py`,
  `test_install_button.py`, `test_tiktok_robustness.py`, `test_sp_jobs.py`,
  `test_site_hardening.py`, `test_formats_audio_rule.py`, `test_sp_audio.py`,
  `test_sp_gemini_cascade.py`, `test_sp_gemini_keys.py`.
- **Node JS suites** — all pass: `test_homepage_js.js` (this also executes
  the new Search Videos inline script against the stub DOM),
  `test_sp_quota_js.js`, `test_sp_jobs_js.js`, `test_install_sheet_js.js`.

## 5. Known limits

- New section ships in **English** ("Search Videos", Search/Watch/Download).
  The site's i18n is a server-side dict per language (30 languages); wiring
  the new strings into all 30 was disproportionate for this build. The three
  action words are near-universal; translating the section later only needs
  new keys in `i18n.py` + `t.` references.
- Facebook search source (Bing) is flaky — see §2. Instagram also depends on
  Bing honouring `site:`; both degrade to the honest unavailable message,
  never to fake results.
- TikTok verdict is sandbox-only until re-smoked on Render (see §2).

## 6. Files changed (BOTH copies, md5 parity verified)

| File | md5 |
|---|---|
| `app.py` | `06b9facdcdfecfaf8e5b1aae4aa96f16` |
| `templates/index.html` | `7855b8da62d1ceb7c5f92dc572be8b41` |
| `tests/test_search.py` (new) | `1f217a2eb0f5e3d7e00caad10a08a55c` |
| `tests/test_sp_quota.py` | `a793565bc55b6bc15996943ed2d4295a` |
| `tests/test_sp_quota_js.js` | `d27cd62937343fe409191604a1b7872f` |
| `tests/test_homepage_js.js` | `8e9b2fa0ef7136841dd3699c47185741` |

`static/sw.js` **untouched** in both copies — still the pending local fix,
md5 `7d7af1373fc13fa3c386d8165c7fd656`. (The parent's pending sw.js push and
this change can ride the same push/deploy if the parent so decides;
`app.py`/`index.html` and `static/sw.js` are independent files.)

## 7. Push / deploy notes for the parent

1. Pre-warn the owner about the GitHub approval card (standing rule), then
   push the 6 files above (master `~/workspace/downloader-site` ↔ mirror
   `~/workspace/qgrab-repo` are in parity; push from the repo copy as usual).
2. Render: Manual Deploy → Deploy latest commit.
3. Post-deploy live smoke (important — sandbox ≠ Render):
   `GET https://qgrab.onrender.com/api/search?platform=youtube&q=funny+cat`
   (expect ok:true, 12), `platform=instagram&q=funny+cat+reel` (expect
   ok:true), `platform=facebook&q=funny+cat` (ok:true expected but flaky),
   `platform=tiktok&q=funny+cat` (**the open question** — record the result
   and report it to the owner either way), and
   `GET /api/script-prompt/quota` (expect max 10/10; note a deploy/restart
   resets the in-memory counters to a fresh 10/10, as the owner already
   knows from the 150 era).
4. Refresh the QGrab backup ZIP after the deploy verifies (standing rule).


---

## 8. Hardening — 2026-11-08 (owner: "Facebook fix karo, TikTok lazmi check karo")

Status: **BUILT + TESTED LOCALLY ONLY** (same rule as above — no push,
no deploy). All measurements below are from the dev sandbox on
2026-11-08 ~03:10–03:35 PKT. **Sandbox ≠ Render** — the post-deploy
checklist at the end is part of the deliverable.

### 8.1 What changed in code

- **Facebook is now an aggregating fallback chain** (`_run_web_chain`):
  sources run in measured order and results are **pooled and deduped
  across sources**, stopping once ≥5 valid results are collected.
  Per-source timeout 8 s; a block/anomaly page parses to zero pairs,
  so a blocked engine fails fast and the chain moves on. If the whole
  first pass yields 0, the best source is **retried once after a 1 s
  pause** (engines rate-limit in bursts).
- **URL filter tightened** (`_is_platform_video_url`): `fb.watch`
  short links are now accepted; bare `/watch` counts only with a
  `v=` id; `/watch/explore`, `/watch/hashtag` and `apps.facebook.com`
  junk is rejected. An fb.watch result with no known title is titled
  "Facebook video".
- **Instagram uses the same chain machinery**, reordered by the new
  measurements: **Brave → Bing → DuckDuckGo html** (Brave returned
  19–20 reel hits per query, vs ~10 for the previously shipped Bing
  route on the same queries).
- **Caches**: fresh success cache is now **30 min** for facebook /
  instagram / tiktok (YouTube unchanged at 5 min), plus
  **stale-while-error**: a last-good copy is kept 24 h per
  (platform, query); if every source fails but a stale entry exists,
  it is served with `"cached": true` instead of `unavailable`.
- **TikTok**: tikwm feed/search stays first (rich cards; its host
  answers this app's single-video resolver from Render), backed by a
  measured engine chain **Brave → DuckDuckGo html → Bing**
  (site:tiktok.com) whose results are shaped from the canonical
  `/@user/video/<id>` URLs (author = handle, Watch = embed/v2,
  Download = canonical webpage_url, as before).

### 8.2 Facebook — per-source live matrix (real FB video URLs)

Queries: "funny cat" / "dance" / "cricket highlights". Counts are
what each source returned on its own (pre-chain parsers; the two
Bing/Yahoo rows marked * included Facebook browse pages in the raw
count — the shipped filter now rejects those, so their real-video
yield is lower than the raw number).

| Source | funny cat | dance | cricket highlights | Verdict |
|---|---|---|---|---|
| (a) Bing `site:facebook.com/watch <q>` | 0 | 0 | 0 | **dropped** — 10 result links parsed per query, none a video URL |
| (b) Bing `site:facebook.com/reel <q>` | 0 | 0 | 0 | **dropped** — same |
| (c) Bing `<q> facebook video` | 1 | 3* | 0 | kept (3rd) |
| (d) DuckDuckGo html `site:facebook.com <q> video` | 5 | 8* | 0 (anomaly page) | kept (2nd) — big counts when DDG doesn't serve its bot-anomaly page |
| (e) DuckDuckGo Lite `site:facebook.com <q>` | 0 | 0 | 0 | **dropped** — anomaly page every time |
| (f) Brave `site:facebook.com <q>` | 4 | 4 | 2 | kept (**1st**) — the only source with real /videos/ URLs on **every** query |
| (g) Yahoo `site:facebook.com <q>` | 0 | 1* (junk) | 4* (~3 real) | kept (4th, last-resort) |

Final FB chain: **Brave → DDG html → Bing generic → Yahoo**,
aggregate-until-5, one Brave retry on a total-zero pass.

### 8.3 TikTok — exhaustive route check (live, sandbox)

| Route | funny cat | dance | cricket highlights |
|---|---|---|---|
| 1. tikwm `feed/search` **POST** form body (impersonated fetch) | HTTP 403, Cloudflare "Just a moment" page | 403, same | 403, same |
| 2. tikwm `feed/search` **GET** + full browser headers incl. Referer | HTTP 403 | HTTP 403 | connection closed |
| 3a. tikwm GET via bare host `tikwm.com` | HTTP 403 | HTTP 403 | HTTP 403 |
| 3b. tikwm POST via bare host | HTTP 403 | HTTP 403 | HTTP 403 |
| 4. `api.tikwm.com` GET / POST | connection closed ×3 | proxy abort ×3 | dead host from here |
| 5. urlebird search (`/search/<slug>/`; real form is `/search/?q=`) | 404 | 404 / then 403 + connection closed | dropped — hostile to this client |
| 6. **Brave** `site:tiktok.com <q>` | **8 real videos** | 1 | 3 |
| 7. **DuckDuckGo html** `site:tiktok.com <q>` | 0 (anomaly) | 0 (anomaly) | **10 real videos** |
| 8. **Bing** `site:tiktok.com <q>` | 1 | 0 | 0 |

Samples (route 6/7): `https://www.tiktok.com/@funnycats0ftiktok/video/7502102932712623390`,
`https://www.tiktok.com/@cricket.highlights64/video/7689346341222337813`.
No key-required services, no login/cookies, and no signed TikTok
endpoints (msToken/X-Bogus) were used — per the standing rules.

Final TikTok order shipped: **tikwm → Brave → DDG html → Bing**.
tikwm is first on plausibility (richest data, fails fast at ~0.5 s,
and its host provably answers this app from Render for single
videos); the engines are the measured-working backstop — from the
sandbox they are what actually serves TikTok results today.

### 8.4 Shipped-code live smoke (endpoint, sandbox, after hardening)

| Platform | funny cat | dance | cricket highlights |
|---|---|---|---|
| Facebook | ok, **4** | ok, **10** | ok, **9** |
| TikTok | ok, **8** | ok, 1 | ok, 3 |
| Instagram | ok, **12** | ok, **12** | ok, **12** |
| YouTube | ok, 12 | ok, 12 | ok, 12 |

Facebook sample: `facebook.com/englandcricket/videos/10-great-test-match-catches-.../16306488...`;
TikTok sample: `tiktok.com/@qca.qtr/video/7630419964154940693`.
Compare pre-hardening Facebook: worked once (5), flaky elsewhere —
now all three queries return real results in 1.6–3.2 s.

### 8.5 Tests after hardening

- `tests/test_search.py`: **15/15 pass in BOTH copies** (6 new:
  Brave/Yahoo parsers, hardened FB URL filter + fb.watch title,
  TikTok engine shaper, chain aggregation/dedupe/stop-early, chain
  retry of best source, stale-cache serving via the endpoint).
- Full Python suite: all 11 test files pass (incl. SP quota at the
  new caps of 10 — untouched by this work).
- Node suites: all 4 pass (homepage JS incl. the search script,
  quota JS, jobs JS, install sheet JS).
- Files changed in this hardening (both copies, md5 parity):
  `app.py` → `5835e50d1a57e3e0fb4770cefb36f741`;
  `tests/test_search.py` → `cc0b07e8bb618af7cc16d25fda2d7dd0`.
  `templates/index.html` unchanged (`7855b8da…`); `static/sw.js`
  **untouched** (`7d7af137…`).

### 8.6 Post-deploy live-smoke checklist (parent — sandbox ≠ Render)

1. `GET https://qgrab.onrender.com/api/search?platform=tiktok&q=funny+cat`
   — **the key question**: does tikwm answer from Render's IP
   (rich results with thumbnails) or does the engine chain serve
   (results without thumbnails)? Record which; both are ok:true.
   Repeat with `q=dance` (sandbox engines gave only 1 — check
   Render does better).
2. `GET /api/search?platform=facebook&q=funny+cat`, `&q=dance`,
   `&q=cricket+highlights` — expect ok:true on all three; if one
   returns `ok:false`, retry it once after a minute (engine burst
   block) and record; a repeat search for the same query within
   24 h of any success should serve stale with `"cached": true`
   rather than fail.
3. `GET /api/search?platform=instagram&q=funny+cat+reel` — expect
   ok:true, 12.
4. `GET /api/search?platform=youtube&q=funny+cat` — expect ok:true,
   12 (regression check).
5. `GET /api/script-prompt/quota` — expect max 10/10 (unchanged).
6. Homepage: open the Search Videos section, run one search per
   tab, check Watch opens the modal player and Download lands in
   the main downloader's format list.

---

## 9. Serper — official Google search API as PRIMARY source (2026-11-08)

Status: **BUILT + TESTED LOCALLY ONLY** (no push, no deploy, no key
handled — the key will exist only as a Render env var at runtime).
Owner approved the official-API fix on 2026-11-08 after the
production smoke showed the scraping chain blocked from Render's
datacenter IP (all three engine-fed platforms `ok:false` live,
while identical code worked from the sandbox).

### 9.1 Design

- **Env var: `QGRAB_SERPER_API_KEY`** — read via `os.environ` at
  call time in `_search_serper()` (same host-only pattern as
  `QGRAB_INVIDIOUS_INSTANCES` / `QGRAB_YT_COOKIES_B64`). Never
  written to any file, never committed, **never logged** (failure
  logs carry platform + HTTP status only). Unset/empty → Serper
  is skipped silently — **zero requests, zero behaviour change**
  (unit-tested).
- **Request**: `POST https://google.serper.dev/search`, headers
  `X-API-KEY: <key>` + `Content-Type: application/json`, body
  `{"q": "<user q> site:<platform>.com", "num": 10}` — exactly
  **ONE Serper query per user search** per platform. New helper
  `_http_post_json()` (curl_cffi impersonation first, urllib
  fallback, ~15 s timeout) sits next to `_http_get_text`.
- **Shaping**: `organic[].link` + `organic[].title` become
  (title, url) pairs fed into the EXISTING `_shape_web_search_results`
  — so the hardened FB URL filter (watch?v=, /reel/, /videos/,
  fb.watch), the Instagram /reel/+/p/ filter, and the TikTok
  /@user/video/<id> shaping (author = @handle parsed from the
  URL, embed = tiktok.com/embed/v2/<id>, thumbnail = "" →
  UI placeholder; Serper offers no thumbnails) all apply
  unchanged. **Response JSON shape is identical** (ok / platform /
  q / results[] / cached) — `templates/index.html` needed **NO
  changes** (verified: the search JS consumes only
  embed_url / webpage_url / duration_h / title / author, all
  produced by the shared shaper).
- **Order per platform** (in `_search_facebook/_search_instagram/
  _search_tiktok`):
  1. **Serper** — if it yields ≥1 valid result, that list is the
     answer; the scraping chain is NOT called (credit + latency).
  2. On Serper failure (HTTP 400/403/429 = bad key / out of
     credits, network error, odd payload) or zero valid results →
     the EXISTING fallback exactly as before: TikTok tries tikwm
     then the engine chain; Facebook/Instagram go straight to the
     engine chain — including the endpoint's stale-while-error
     serving when everything fails.
- **Caching**: unchanged machinery — successes from ANY source
  are cached by the endpoint under the same keys
  (`platform|q.lower()`), same TTLs (30 min fresh for the three
  web platforms, 24 h stale horizon). A popular query therefore
  costs at most ~2 Serper credits/hour however many visitors ask.

### 9.2 Credit math

- 1 credit per platform search (cache misses only). Serper free
  tier ≈ 2,500 credits → ≈ 2,500 uncached FB/IG/TT searches.
  With the 30-min cache, real visitor searches cost far less
  than 1 credit each on repeat/popular queries. When credits run
  out, Serper answers 403/429 → the app silently falls back to
  the scraping chain (today's behaviour) — no visitor-facing
  breakage, just back to the flaky route until credits refresh.

### 9.3 Tests

- `tests/test_search.py`: **20/20 pass in BOTH copies** (5 new:
  (a) FB Serper hit returns shaped results and the chain is NOT
  called, with the request asserted as one POST
  `{"q": "funny cat site:facebook.com", "num": 10}` carrying the
  key header; (b) Serper HTTP 403 falls through to the chain;
  (b2) Serper 200 with zero valid results falls through;
  (c) env var unset = no POST attempted, chain serves as today;
  (d) TikTok Serper organic parses @handle/id/embed correctly,
  profile links dropped, thumbnail "").
- Full Python suite (12 files) — all pass in master; in the
  mirror all pass EXCEPT `test_install_button.py`, a
  **pre-existing, unrelated** failure: the repo copy's
  `static/icons/` holds only `logo-base64.txt` (the PNG icons
  are generated by `make_icons.py` at Docker build time, never
  committed), so its icon route 404s locally. Master (icons on
  disk) passes; production builds the icons. Not touched by
  this change (app.py is md5-identical in both copies).
- Node suites: all 4 pass in both copies.
- Files changed, md5 parity both copies: `app.py` →
  `b39b11dd2f274e523b9780e1ec63ff4d`; `tests/test_search.py` →
  `e1f6915734ad0a8b0e9dca81ac7e1216`. `templates/index.html`
  unchanged (`7855b8da…`); `static/sw.js` untouched (`7d7af137…`).

### 9.4 Parent — deploy + post-deploy smoke checklist

1. Owner signs up at serper.dev (free) and creates an API key —
   **the key must never transit chat or any file**; the owner (or
   the parent with the owner's go-ahead through the secure
   route) sets `QGRAB_SERPER_API_KEY` in the Render service's
   environment variables. Setting the env var triggers a
   redeploy on Render by itself; the code push can ride the same
   deploy cycle.
2. Push `app.py` + `tests/test_search.py` (pre-warn the owner
   about the GitHub approval card, standing rule), then Render
   Manual Deploy → Deploy latest commit (or just the env-var
   redeploy if the push lands first).
3. Live smoke (key set): `GET /api/search?platform=facebook&q=funny+cat`,
   `platform=instagram&q=funny+cat+reel`, `platform=tiktok&q=funny+cat`
   and `&q=dance` — expect **ok:true with real results on all**
   (this is the moment of truth the sandbox could never prove).
   Repeat one query → second answer should be the cached payload
   (no second credit). `platform=youtube&q=funny+cat` regression
   (ok:true, unaffected). `GET /api/script-prompt/quota` → 10/10.
4. Sanity-protect the credits: if the smoke shows ok:false with
   the key set, check Render logs for "via serper failed
   (HTTP …)" — 403/429 = key/credit problem at Serper's end,
   NOT a code bug; verify the key on serper.dev's dashboard.
5. Refresh the QGrab backup ZIP after live verification
   (standing rule).


## 10. Serper go-live (2026-11-08 ~03:41–03:47 PKT)

- **Account:** Serper has NO Google signup (form + Cloudflare human check only). Two agent-browser registration attempts were refused by Serper itself ("It is not possible to register at this moment, try again later") — a datacenter-egress block, same family as the Upwork wall. The OWNER then created the account himself in his own Chrome (Pakistani IP) in about a minute: dashboard showed **2,500 free credits**. Standing rule recorded in MEMORY.md: Cloudflare-walled signups go to the owner's phone FIRST from now on.
- **Key handling:** owner chose to hand the key to Archer in chat; it was used ONCE, transiently, to set Render env **QGRAB_SERPER_API_KEY** via the agent browser, and the value is recorded NOWHERE (not in this report, memory, files or logs). Rotation path: owner can regenerate in the Serper dashboard anytime; Archer re-sets the env var.
- **Env set** on Render (service qgrab) ~03:41; Render auto-deployed the previous commit, then code commit **2929792d** (app.py + tests/test_search.py) was pushed (owner approved the GitHub card) and manually deployed: **dep-dbnqiuu7bikc73d97hq0, live 03:43 PKT**.
- **LIVE SMOKE (production, query "funny cat"):** facebook **ok, 6 results, 2.1s**; instagram **ok, 7, 2.5s**; tiktok **ok, 9, 2.3s**; youtube **ok, 12, 2.9s**. Repeat facebook query: ok, 6 results, 1.0s. Result-shape inspection: real platform URLs everywhere (facebook.com/.../videos/<id> + plugins embed; instagram.com/reel/<code> + /embed; tiktok.com/@handle/video/<id> + embed/v2; YouTube full metadata via Invidious as before). Quota endpoint still 10/10 after the deploys.
- **Known cosmetic gap (accepted):** Facebook/Instagram/TikTok rows carry no thumbnail/author/duration (Google results don't provide them) — the UI shows the platform placeholder; YouTube rows are full. Download from a result still flows through the existing /api/info + /download machinery.
- **Credit math:** one Serper credit per cold platform search; results cached server-side (5-min fresh + stale-while-error), so repeat/popular queries are mostly free. 2,500 credits is ample for launch traffic.
