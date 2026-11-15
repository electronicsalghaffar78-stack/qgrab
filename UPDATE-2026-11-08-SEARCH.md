# QGrab Update — 2026-11-08: Search Videos + SP caps 10 + SW install fix

Deployed live 2026-11-08 ~03:15 PKT. GitHub commit 252ccda06b139d6ba09b564219c1e29d2cf4aec9, Render deploy dep-dbnq5mou01pc73deinh0 (Manual Deploy, latest commit).

## What shipped
1. **Search Videos** (owner's design): homepage section below the hero — tabs YouTube / Facebook / TikTok / Instagram -> one search bar -> result cards (thumbnail/placeholder, title, author, duration/views) with **Watch** (on-site modal embed per platform) and **Download** (fills the main downloader; existing /api/info -> /download flow). Backend `GET /api/search?platform=&q=` — public sources only, 12 results max, in-memory cache + 24h stale-while-error for engine-fed platforms. Full detail: SEARCH-FEATURE-REPORT.md (incl. §8 hardening: Brave -> DDG html -> Bing -> Yahoo aggregation chain for FB; tikwm-first + engine chain for TikTok; Brave -> Bing -> DDG for Instagram; Invidious for YouTube).
2. **Script/Prompt daily caps 150 -> 10 each** (owner order 2026-11-08): `SP_DAILY_CAP_SCRIPT/PROMPTS = 10`; quota mechanics unchanged. Live verified: `/api/script-prompt/quota` returns max 10/10.
3. **SW install fix** (prepared 2026-11-07, push had expired): `static/sw.js` tolerant per-file shell caching (`Promise.allSettled`) — live verified the served sw.js contains the new code.

## Live verification (2026-11-08 ~03:17-03:22 PKT)
- Homepage loads, Search Videos section + 4 tabs present (browser-verified).
- `/healthz` ok; quota 10/10; sw.js new version serving.
- **YouTube search LIVE OK** — real results ("funny cat").
- **Facebook / Instagram / TikTok search: live smoke returned `ok:false` (unavailable) on the production server for every test query**, although the identical code returned real results from the sandbox (FB 4/10/9, IG 12/12/12, TT 8/1/3). Cause: the search engines behind those three platforms rate-limit/block the Render server's datacenter IP (Brave answered 429 Too Many Requests in a direct probe). YouTube is unaffected (direct Invidious API). Popular repeated queries may still succeed via cache when an engine relents.
- **Recommended permanent fix:** an official key-authenticated search API (Brave Search API free tier ~2,000 queries/mo, or Serper free credits) for the FB/IG/TT platforms. Needs the owner's OK + a free signup on his electronics email (login-warning rule). Owner was asked on 2026-11-08 ~03:25 PKT; decision pending.
