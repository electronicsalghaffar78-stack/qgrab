# QGrab — YouTube download fallback (NO cookies, NO payment)

**Status: WORKING ROUTE FOUND + IMPLEMENTED LOCALLY. Not pushed, not deployed** (deployment needs Qudoos's approval card).
Date: 2026-11-03 (~05:30–05:45 PKT). Tested from the Archer sandbox (egress-proxy IP — also a non-residential IP that YouTube bot-walls, like Render's).

## The problem
On cloud/datacenter IPs YouTube answers yt-dlp with **"Sign in to confirm you're not a bot"**. Facebook and TikTok downloads already work on QGrab; YouTube did not, and the cookie route was ruled out (no credentials/cookies may be used).

## 1. Baseline — yt-dlp cascade (this sandbox, yt-dlp 2026.10.26)
Test video: `jNQXAC9IVRw` ("Me at the zoo", https://www.youtube.com/watch?v=jNQXAC9IVRw)
- default client → `Sign in to confirm you're not a bot`
- player_client=tv → same bot error
- player_client=android_vr → same bot error
- player_client=web_safari / ios → `No video formats found!`
(First runs also hit the sandbox proxy's custom-CA SSL error; with `--no-check-certificate` the true bot error above is what remains. Render has no such CA quirk — it gets the bot error directly, as observed live.)

## 2. ✅ WINNER — Invidious public instance (locally-proxied streams)
Public list fetched from https://api.invidious.io/instances.json — only 4 HTTPS instances remain, and 3 have the API disabled/forbidden:
- `inv.nadeko.net` → 403 "Endpoint disabled"
- `invidious.nerdvpn.de` → 401 Authorization Required
- `invidious.tiekoetter.com` → 403 Forbidden
- **`yt.chocolatemoo53.com` → API enabled (api=true, cors=true) — WORKS**

How it works: `GET {instance}/api/v1/videos/{videoId}?local=true` returns title/author/duration/thumbnails plus `adaptiveFormats` whose URLs are rewritten to the instance's own `/videoplayback` proxy (they 307-redirect to a companion host, `yt-comp1.chocolatemoo53.com`). The signed googlevideo URLs are bound to the *instance's* IP, and the instance proxies the bytes — so a datacenter IP can fetch them. Follows redirects (`curl -L` / urllib / curl_cffi all do).

### Verified downloads (real bytes + ffprobe)
| Video | Test | Result |
|---|---|---|
| jNQXAC9IVRw "Me at the zoo" (19s) | video itag 133 (240p mp4) full download | **433,081 bytes** (exactly the advertised `clen`), ffprobe: h264 320×240, 18.93s ✔ |
| jNQXAC9IVRw | audio itag 140 (m4a) full download | **309,197 bytes**, ffprobe: aac, 19.06s ✔ |
| jNQXAC9IVRw | ffmpeg mux of the two | 744,413 bytes, h264 + aac ✔ |
| jNQXAC9IVRw | Range GET on video URL | HTTP **206** ✔ |
| dQw4w9WgXcQ "Rick Astley – Never Gonna Give You Up" | itag 136 (720p) Range 0–2 MiB | HTTP **206, 2,097,152 bytes**, `ftyp dash / iso6 avc1` header ✔ (formats up to 2160p listed) |
| kJQP7kiw5Fk "Despacito" (282s) | itag 136 (720p) Range 512 KiB | HTTP 206, ftyp/moov present ✔ |
| 9bZkp7q19f0 "Gangnam Style" (252s) | itag 136 (720p) Range 512 KiB | HTTP 206 ✔ |
| LXb3EKWsInQ "Costa Rica 4K" (314s) | itag 698 (720p AV1) Range 512 KiB | HTTP 206 ✔ |
| aqz-KE-bpKQ "Big Buck Bunny" (635s) | itags 135/298/398 | ✘ **403 "Videoplayback URL has expired"** — the instance served a stale cached playback URL for this one video (its `expire` was ~3.7 h older than fresh ones). Per-video instance quirk, not a general failure: **5 of 6 videos worked.** Affected videos fall through to the normal friendly error. |

## 3. ✘ Cobalt — not viable server-side
- `POST https://api.cobalt.tools/` → HTTP 400 `error.api.auth.jwt.missing`; its server-info **services list does not include YouTube at all** anymore (v11.7.1: bilibili, facebook, instagram, tiktok, … no youtube).
- Community instances `cobaltapi.squair.xyz`, `nuko-c.meowing.de`, `cobaltapi.kittycat.boo` → same `error.api.auth.jwt.missing` (they require a browser-solved Turnstile/JWT — cannot be done server-to-server, and solving CAPTCHAs for this is out of scope).
- `cobaltapi.cjs.nz` (the one no-auth instance) → `error.api.youtube.login` (its own YouTube access is broken).
- `api.dl.woof.monster`, `api.cobalt.liubquanti.click` → unreachable (HTTP 000); `instances.cobalt.best` → unreachable; `cobalt.directory` → Cloudflare-blocked from this IP.

## 4. ✘ Piped (bonus check) — its instances are bot-blocked themselves
- `api.piped.private.coffee/streams/jNQXAC9IVRw` → HTTP 500 `SignInConfirmNotBotException: "Sign in to confirm that you're not a bot"`
- `pipedapi.wireway.ch` → same exception.

## Implementation (in `app.py`, BOTH copies, kept identical)
Files changed: `~/workspace/downloader-site/app.py` and `~/workspace/qgrab-repo/app.py` (diff-verified identical; `python -m py_compile` passes on both).
- New "Invidious fallback" section: `INVIDIOUS_INSTANCES` (default `https://yt.chocolatemoo53.com`, overridable via env var `QGRAB_INVIDIOUS_INSTANCES`, comma-separated), `_youtube_video_id()` (watch / youtu.be / shorts / embed / live / music shapes), `_invidious_raw()`, `_shape_invidious_info()` (maps Invidious formats into the yt-dlp-style info dict the app already uses — including the app's existing `merge:<height>` options), `_fetch_to_file()`, `_download_merged_invidious()` (ffmpeg join, same as the yt-dlp merged path).
- `extract_info()`: unchanged cascade first; **only when every yt-dlp attempt has failed AND the URL is YouTube**, it tries Invidious; if that also fails, the original error/friendly message is what the visitor sees.
- `download_merged()`: after the yt-dlp native attempts fail, YouTube URLs try the Invidious merged route before answering 502.
- Plain single-format downloads need no new code: Invidious format URLs flow through the existing `/download` proxy (impersonated curl_cffi → urllib, redirects followed, Range passed through).
- Non-YouTube platforms are untouched (the fallback is gated on `site_of(url) == "youtube"`).

### End-to-end test through the real Flask app (local run, port 5055)
- `POST /api/info` {zoo URL} → **HTTP 200** (previously 422): "Me at the zoo", 0:19, uploader jawed, formats incl. `merge:240`, `merge:144`, itags 133/134/242/395/160 + audios.
- `GET /download?format_id=133` → **HTTP 200, 433,081 bytes**, ffprobe h264 320×240 ✔ (byte count identical to the direct test)
- `GET /download?format_id=merge:240` → **HTTP 200, 744,413 bytes**, ffprobe h264 + aac ✔ (identical size to the manual mux)
- `GET /download` Rick Astley `format_id=136` with `Range: bytes=0-2097151` → **HTTP 206, 2,097,152 bytes**, dash/ftyp header ✔
- Two bugs found & fixed during testing: Invidious reports `bitrate`/`itag` as strings (division crashed the shaper) and the size field is `clen`, not `contentLength`.

## Honest limits / risks
- **Single point of failure:** exactly ONE public Invidious instance currently has its API enabled. If it goes down or disables its API, YouTube falls back to today's friendly error until another instance is added via `QGRAB_INVIDIOUS_INSTANCES` (no code change needed). It is a free community service — no SLA, unknown rate limits; heavy traffic could get Render's IP throttled by it.
- ~1 in 6 tested videos failed with the instance's stale-URL "expired" answer (per-video cache quirk).
- This was verified from the sandbox egress IP, not from Render's IP. The mechanism (instance proxies the bytes) is IP-independent by design, but the final proof is a live test after deployment.

## Next step (needs Qudoos awake)
Push the two synced `app.py` copies via the usual snapshot-push (his approval card) → Render "Manual Deploy → Deploy latest commit" → live-test a YouTube download on https://qgrab.onrender.com.

## Remaining options if this route ever dies
1. Qudoos attaches a real `cookies.txt` **file** (the server-side cookie support from commit b7d129eb is already built; chat-pasted codes are never used).
2. Paid/residential hosting (the bot wall is IP-based; a residential/clean IP usually clears it for plain yt-dlp).
3. Self-hosted Invidious or Cobalt on a paid VPS (own instance + own IP reputation; monthly cost).
