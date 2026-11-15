# QGrab "All Resources" Feature Test Report

Test-only research — no site files were changed. All tests run 2026-11-03 from
this sandbox machine (a datacenter-style network behind a TLS-intercepting
proxy; yt-dlp was run with `--no-check-certificate` to get past the local
proxy's self-signed chain — that flag is a local-test artifact, not something
the site needs).

- yt-dlp version tested: **2026.10.26** (exactly the version pinned in
  `requirements.txt`), plus `curl_cffi` for `--impersonate chrome`, mirroring
  the app's own cascade.
- ffmpeg: present on this machine (8.1.2) **and** in the production image —
  `deploy/Dockerfile` installs `ffmpeg` via apt. So any feature that needs an
  ffmpeg step (MP3 transcode, subtitle conversion) has its tooling in both
  places.
- Current app behaviour (from `app.py`): YouTube gets a player-client
  cascade, TikTok impersonation-first, Facebook plain-then-impersonation,
  every other host plain-then-impersonation (the impersonation retry only
  fires after a webpage/403-style error), plus the Invidious proxy fallback
  for YouTube. Downloads are proxied/merged server-side the same way for
  all hosts, so any extractor below that returns formats can ride the
  existing download path.

Verdict key: **WORKS** = tested end-to-end or extraction + formats proven
from here · **FAILS** = extractor ran and refused/errored for a reason that
is not this network · **BLOCKED-FROM-HERE** = this network stopped the test;
may still work from Render.

---

## 1. Extra platforms (video download)

### Dailymotion — BLOCKED-FROM-HERE (no formats returned)
- Sample: `https://www.dailymotion.com/video/x9o94sq` (also `xbhty7m` and
  the `dai.ly/x9o94sq` short form).
- Without impersonation the metadata request timed out / the connection was
  cut by this network. With `--impersonate chrome` the extractor loaded the
  video but reported **"No video formats found!"** on all three videos.
- The extractor itself is present and functional (it parsed the pages); the
  stream metadata Dailymotion returns to this network contains nothing
  downloadable — consistent with region/network filtering of Dailymotion's
  HLS metadata rather than a broken extractor.
- **Needs a re-test from Render before listing it.**

### Vimeo — FAILS (login required)
- Sample: `https://vimeo.com/76979871`.
- With and without impersonation: **"The web client only works when
  logged-in. Use --cookies … to provide account credentials."**
- Vimeo's current web extraction demands an account session. That conflicts
  with QGrab's no-login design (the only cookie the app supports is the
  optional YouTube one). Do not list Vimeo unless a Vimeo cookie story is
  deliberately accepted later.

### Reddit (video posts) — FAILS without login (cookies required)
- Samples: post URL `https://www.reddit.com/r/China_irl/comments/z09a7r/`
  and the direct `https://v.redd.it/4huchegx4x0a1`.
- Both fail with **"Account authentication is required. Use --cookies-from-
  browser or --cookies"** (with impersonation; without it the JSON fetch was
  cut off mid-body by this network).
- Reddit now gates its JSON API behind authentication for anonymous
  datacenter-style access, so this is very likely to fail the same way from
  Render. yt-dlp's Reddit support itself is fine (it merges v.redd.it's
  split DASH video+audio via ffmpeg), but only behind a logged-in session
  QGrab does not have. Do not list Reddit.

### Pinterest (video pins) — WORKS
- Sample: `https://www.pinterest.com/pin/vegan-chickpeas-recipe-video--844493672922948/`
- Extractor returned **7 formats: 5 downloadable MP4 renditions** (plus
  image renditions), title/duration parsed, anonymous, no login, no
  watermark concerns (the file is the pin's own video).
- Works with the same generic flow the app already uses for "other" hosts;
  note the first attempt from here needed impersonation to get a clean
  metadata read, and the app's "other" plan only retries with impersonation
  after a webpage-style error — worth making Pinterest impersonation-first,
  like TikTok, when this is built.

### Threads — FAILS (extractor unsupported/removed)
- Sample: `https://www.threads.net/@andylim_ss/post/DHErg5ozVRy`.
- **yt-dlp 2026.10.26 ships no Threads extractor at all** (checked
  `--list-extractors`), and threads.net now redirects to threads.com, which
  yt-dlp rejects as an unsupported URL.
- There is no yt-dlp route to Threads today. Leave it out until/unless
  yt-dlp restores support.

### VK — WORKS (impersonation required from here)
- Sample: `https://vk.com/video-30558759_456239017` (a real public video,
  44 s).
- Plain attempts timed out from this network; with `--impersonate chrome`
  the extractor returned **30 formats (MP4 video + M4A audio)**.
- Caveats: public videos only (private/closed-group videos need a VK
  login); VK's CDN is referer-sensitive, but the app already proxies
  downloads with the extractor's headers and falls back to a native yt-dlp
  download, which is the right shape for this. When built, VK should be
  impersonation-first in the attempt plan, not impersonation-on-retry.

### X / Twitter — WORKS (impersonation required from here)
- Sample: `https://x.com/NASA/status/1902118174591521056` (video post).
- Plain attempts timed out; with `--impersonate chrome` the extractor
  returned **9 formats, MP4 video up to the post's full quality**.
- Caveats: public posts only; protected accounts and some posts still need
  a logged-in session (X rate-limits anonymous guests per IP, so occasional
  failures from a shared datacenter IP are expected — the app's friendly
  error already covers that case).

### Instagram (re-test) — WORKS
- Sample: `https://www.instagram.com/reel/Ckpu22yDFki/`.
- Extraction returned 9 formats anonymously (no login, no impersonation
  needed from here), and an actual download was verified end-to-end:
  4.5 MB MP4, 23.9 s, plays correctly.
- Caveats (unchanged from the site's existing honest copy): public posts
  only; private accounts can't be fetched; Instagram changes its anonymous
  access often, so treat it as best-effort.

---

## 2. MP3 / audio-only download — WORKS

Approach that works: `yt-dlp -f bestaudio -x --audio-format mp3 <url>`
(bestaudio download + ffmpeg ExtractAudio transcode).

- **YouTube** (`https://www.youtube.com/watch?v=aqz-KE-bpKQ`): the download
  step is client-dependent from a datacenter IP, exactly like video —
  `player_client=tv` failed on the media fetch here ("The page needs to be
  reloaded"), `web_safari` hit the "Sign in to confirm you're not a bot"
  wall, `android_vr` offered no audio format for this video, while the
  **default client + `--impersonate chrome` downloaded the full bestaudio
  M4A (10.3 MB)** and ffmpeg transcoded it to a verified MP3
  (13.6 MB, ~171 kbps VBR, full 634 s duration). The app's existing cascade
  + Invidious fallback is the right delivery shape; Invidious also exposes
  audio-only formats that can be transcoded the same way.
- **MP3 always needs ffmpeg when the source isn't already MP3**: YouTube
  serves Opus/M4A, so the MP3 is a real transcode (libmp3lame). ffmpeg is
  present here and in the Docker image, so this is fine — it costs CPU
  seconds on Render's free tier, acceptable for audio-sized files.
- **TikTok** (`https://www.tiktok.com/@rangbirangatv/video/7702522136258383127`):
  works with `--impersonate chrome`; in this case TikTok's bestaudio **was
  already MP3 (128 kbps)**, so yt-dlp saved it directly with no transcode
  (verified file: 50 s, 128 kbps). Note the audio track TikTok exposes is
  the post's sound track.
- Product note: QGrab already lists M4A "audio only" formats today; an
  "MP3" option is this same path plus the transcode step.

## 3. Subtitles-only download (YouTube) — WORKS

Approach: `yt-dlp --write-subs --write-auto-subs --sub-langs "<lang>"
--sub-format vtt --skip-download <url>` (YouTube also offers `srt`
natively, and ffmpeg converts vtt↔srt — verified both ways here).

- Test video `https://www.youtube.com/watch?v=iG9CE55wbtY` (TED talk):
  caption listing shows automatic captions in 100+ languages, each in
  vtt/srt/ttml/json3 formats; the English `.vtt` downloaded successfully
  (30 KB) with `--skip-download` (no media bytes fetched), and ffmpeg
  converted it to a valid `.srt`.
- Caveats: availability is entirely per-video — the uploader's manual
  tracks plus YouTube's auto captions; some videos have **none at all**
  (the Big Buck Bunny upload `aqz-KE-bpKQ` returned "no subtitles / no
  automatic captions" on every player client). The UI must handle the
  empty case gracefully. Extraction must succeed first, so the same
  bot-wall caveat as video applies (the app's cascade mitigates it).

## 4. YouTube transcript (plain-text .txt) — WORKS

- Same caption download as §3, then a trivial cleanup pass: drop the
  WEBVTT header, cue timings and inline tags, de-duplicate the rolling
  caption lines, join into flowing text.
- Verified on the TED talk above: produced a clean **17,574-character
  plain-text transcript** beginning "Good morning. How are you? (Audience)
  Good. It's been great, hasn't it?…" — readable, no timestamps.
- Pure server-side string processing once the .vtt exists; no extra
  dependencies. Inherits §3's per-video availability caveat.

## 5. Pinterest IMAGE download (photo pins) — FAILS via yt-dlp

- Sample photo pin: `https://ar.pinterest.com/pin/chicken-salan-recipe--15410823721794573/`
- yt-dlp's Pinterest extractor is **video-only**: for an image pin it
  errors with "No video formats found!" and returns nothing.
- The full-size image does exist on the pin page (served from
  `i.pinimg.com/originals/…`, the same host the extractor uses for video
  pins' poster thumbnails), so a small custom page parser *could* fetch
  it — but that is new non-yt-dlp code, untested here, and Pinterest's
  embedded page data changes often. Verdict: **not available through the
  current stack; only via custom parsing, to be prototyped and verified
  live before listing.**

## 6. File-upload converters on Render FREE — feasibility

Environment facts (from `deploy/Dockerfile` + the free plan): ffmpeg is in
the image; gunicorn runs **1 worker × 8 threads with a 600 s timeout**;
Render Free gives **512 MB RAM**, a slow shared CPU, an **ephemeral disk**
(files vanish on restart/sleep — fine for convert-and-download in one
request, nothing can be queued or resumed), **~5 GB/month bandwidth**,
and the instance **sleeps when idle** (~1 min cold start). Every converted
file crosses that 5 GB **twice** (upload in + download out).

- **MOV → MP4 — Feasible, with a hard size cap.** Most MOV uploads are
  H.264/AAC, so conversion is usually a stream-copy remux
  (`ffmpeg -c copy`) that takes seconds and little CPU. Cap uploads
  (~50–100 MB) and convert inside the request.
- **MKV → MP4 — Feasible, same shape.** MKV is a container, not a codec;
  typical H.264/AAC contents remux to MP4 the same way. (Exotic audio
  codecs may need a cheap audio-only transcode.)
- **WEBM → MP4 — Not feasible as a general feature.** WebM means VP9/AV1
  video, which MP4 players don't accept — it needs a **full re-encode to
  H.264**. On free-tier CPU even a short HD clip takes minutes, risks the
  600 s worker timeout and 512 MB RAM, and burns double bandwidth. Only
  toy-length, low-res clips would survive.
- **MP4 → GIF — Not feasible.** GIF encoding is a slow two-pass palette
  process and the output explodes (a 10 s clip's GIF is routinely larger
  than the source MP4). A handful of GIFs would eat the month's 5 GB
  bandwidth. Only ≤5 s / ≤360 p toy clips would work — not a feature
  worth listing.

---

## Recommended implement list

**Safe to build and list now** (proven here, ride the existing app design):
1. **Pinterest video pins** — make Pinterest impersonation-first in the
   attempt plan.
2. **VK** and **X/Twitter** video — add as impersonation-first hosts in
   the cascade (both only worked with impersonation from here).
3. **Instagram** — keep listed; re-verified working end-to-end today.
4. **MP3 audio option** for YouTube/TikTok (and anywhere bestaudio
   exists): download bestaudio + ffmpeg transcode; also covers the
   Invidious audio formats.
5. **Subtitles-only download** (.srt/.vtt, language picker, graceful
   "this video has no captions" state) and **Transcript (.txt)** — both
   are one feature underneath: fetch captions once, serve three shapes.

**Build only with live-site verification after deploy:**
6. **Dailymotion** — the extractor loads but returned no formats from
   this network; verify from Render's network before listing it.
7. **Pinterest image pins** — needs a small custom parser (not yt-dlp);
   prototype and verify live before listing.
8. **MOV → MP4 / MKV → MP4 converter** — technically feasible as a
   remux with a strict size cap, but defer until the bandwidth budget
   allows: on 5 GB/month, a few dozen conversions consume the whole
   month. Revisit on paid hosting.

**Leave out:**
9. **Threads** — no yt-dlp extractor exists in the pinned version.
10. **Vimeo** and **Reddit** — both hard-require account cookies;
    incompatible with QGrab's no-login design.
11. **WEBM → MP4** and **MP4 → GIF** converters — not viable on Render
    Free (full re-encode cost / GIF size explosion vs 512 MB RAM,
    600 s timeout and 5 GB/month bandwidth).
