# QGrab — Feature Expansion + Real Reviews: Implementation Report

Built 2026-11-03 (local only — **NOT pushed, NOT deployed**). Implements
exactly what `FEATURES-TEST-REPORT.md` verified, on top of the SEO +
30-language i18n state described in `SEO-REPORT.md` / `I18N-REPORT.md`.
Both trees updated and md5-synced: `~/workspace/downloader-site/`
(master) and `~/workspace/qgrab-repo/` (deploy).

Hard rules honoured: no fake stats/ratings/testimonials anywhere; the
existing YouTube/TikTok/Facebook download cascade, the Invidious
fallback, PWA, the logo pipeline, i18n and all SEO elements are
untouched in behaviour (spot-checked below).

---

## 1. Files changed (identical in both trees unless noted)

| File | Change |
|---|---|
| `app.py` | New platforms in cascade; MP3 download; subtitles/transcript downloads; captions in `/api/info`; ratings backend (`/api/ratings`, `/api/rate`); index view passes ratings state |
| `i18n.py` | +44 keys × 30 languages (178 keys total, parity re-verified); `spec_platforms_val` updated in all 30 languages |
| `templates/index.html` | Grouped format renderer (Video / MP3-Audio / Subtitles & Transcript); platform chips: Pinterest + VK added, Dailymotion removed, X relabelled "X (Twitter)"; includes for tools + reviews sections |
| `templates/platform.html` | Same grouped format renderer |
| `templates/_tools.html` | **New** — "All Tools" section (10 real tools) |
| `templates/_reviews.html` | **New** — "Rate QGrab" widget + reviews list |
| `templates/_extras.html` | CSS for format groups, captions row, tools list, ratings/reviews (incl. RTL variants) |
| `templates/_footer.html` | "All Tools" link added to Quick Links (shared footer → appears on every page) |
| `templates/_specs.html` | Unchanged file — its Platforms value comes from i18n, updated there |
| `.gitignore` | **New** — `data/` (user ratings must never be committed), `__pycache__/`, `*.pyc`, `.venv/` |
| `deploy/Dockerfile` (each tree's own variant, edited in place) | `mkdir -p /app/data` owned by `appuser`; **also fixed a latent bug: neither Dockerfile copied `i18n.py`, which `app.py` imports — the image could not have booted without it. `COPY i18n.py ./` added in both.** |

Not changed: `static/` (PWA, icons, logo base64 pipeline), sitemap
(still 8 URLs — the tools/reviews additions are homepage sections, not
pages), robots.txt, legal pages, `make_icons.py`, download cascade
order for existing platforms.

## 2. How each feature works

### Download options (grouped, after formats load)
`/api/info` now also returns `"mp3"` (true when any format carries
audio) and `"captions"` (available caption tracks, manual subtitles
preferred over auto-generated, UI languages sorted first, capped at
60). The page JS renders three clearly separated groups:

- **Video** — the existing format rows, unchanged.
- **MP3 / Audio** — an "MP3 · audio only" row (`format_id=mp3`) plus
  any native audio formats. Server-side, `download_mp3()` walks the
  normal attempt cascade with `bestaudio/best` + yt-dlp's
  FFmpegExtractAudio postprocessor (MP3). If the source is already MP3
  (e.g. TikTok) it is saved untouched; otherwise ffmpeg transcodes.
  YouTube fallback: `_download_mp3_invidious()` picks the best audio
  adaptive format from the Invidious instance and transcodes with
  ffmpeg (`libmp3lame -q:a 2`). Verified: TikTok → 800,957-byte ID3
  MP3; YouTube TED talk via Invidious → 18.3 MB MP3, 1203 s.
- **Subtitles & Transcript** — shown only when caption tracks exist:
  a language `<select>` plus two links, `subs:<lang>` and
  `transcript:<lang>`. Subtitles download the track as WebVTT (yt-dlp
  cascade, or the Invidious captions API) and convert to **.srt** with
  ffmpeg (raw .vtt served if conversion ever fails). Transcript runs
  the same fetch through `vtt_to_transcript()` — strips headers,
  timing lines and tags, de-duplicates YouTube's rolling lines — and
  serves a clean `.txt`. Verified on the TED talk through **both**
  paths: SRT with correct cues, and a transcript of **exactly 17,574
  characters beginning "Good morning. How are you?"** — identical to
  the length FEATURES-TEST-REPORT.md measured independently.
  Videos without captions (Big Buck Bunny test) return
  `captions: []` and the section simply doesn't render.

### New platforms
`site_of()` recognises Pinterest (`pinterest.*`, `pin.it`), VK
(`vk.com`, `*.vk.ru`, `*.vkvideo.ru`) and X/Twitter (`x.com`,
`twitter.com`). All three join TikTok in the **impersonation-first**
attempt plan (plain attempt as fallback), exactly as the test report
specified. Instagram kept as-is (already verified end-to-end in the
test round). Homepage chips and the specs-table Platforms value now
read **"YouTube · TikTok · Facebook · Instagram · Pinterest · X ·
VK"**. Dailymotion, Vimeo, Reddit and Threads appear **nowhere** on
the site (the old Dailymotion chip was removed).

### All Tools section
`templates/_tools.html`, reachable at `/#tools` and linked from the
footer on every page. Ten entries — and only what works: YouTube,
TikTok (no watermark), Facebook, Instagram (→ their platform pages),
Pinterest, X, VK, MP3/Audio, Subtitles, YouTube Transcript (→ the home
tool; the architecture has no mode-preselection, so no fake deep
links). Titles + one-liners are i18n keys in all 30 languages.

### Real reviews + 5-star rating
- Widget on the homepage: 5 clickable stars, optional name
  (≤ 40 chars), optional review text (≤ 300 chars), submit.
- Storage: `data/ratings.json` next to `app.py` (path overridable via
  `QGRAB_DATA_DIR`), created at runtime, written atomically
  (tmp + replace) under a lock, newest-first, last 500 kept. The
  Docker image creates `/app/data` owned by the app user; the file is
  gitignored in both trees.
- Display is computed **only from stored submissions**: gold star fill
  = average/5 × 100 %, numeric average to one decimal, "(N ratings)"
  (singular "(1 rating)"). At zero ratings the widget shows empty
  stars and the honest localized line "No ratings yet — be the first
  to rate QGrab." Reviews with text are listed newest-first under the
  widget; name/text render through Jinja autoescaping (XSS-safe —
  verified, see below).
- One rating per browser via a `qgrab_rated` cookie (1 year,
  SameSite=Lax): repeat submissions get a localized 409. Invalid
  star values get a localized 400. All widget strings, messages, the
  tools entries and the format-group labels are i18n keys in all 30
  languages (parity check passes: **178 keys × 30 languages**).

## 3. Bugs found and fixed during verification

1. **Invidious caption field name** — the API returns `language_code`
   (snake_case); the shaper/fetch code initially read `languageCode`
   and found nothing. Fixed in both places; captions then listed 60
   tracks for the TED talk.
2. **MP3 flag for X/Pinterest** — their combined formats report
   `acodec` as *missing* rather than a codec name, so the MP3 option
   was hidden. The flag now treats only `acodec="none"` as
   audio-less (a missing field = progressive format with audio).
   `pick_formats` download behaviour deliberately untouched.
3. **Count label parentheses** — the rendered "(N ratings)" lost its
   parentheses; restored at template + JS level so server-rendered
   and post-submit states match.

## 4. Verification evidence (local, this machine)

- App boots from both trees; homepage 200 with zero-state ratings
  copy, 10 tool rows, updated chips/specs; Urdu (`?lang=ur`) renders
  the new sections localized + RTL.
- `/api/info`: TED talk → 12 formats, `mp3: true`, 60 caption tracks;
  Big Buck Bunny → `captions: []` (graceful); TikTok → 5 formats;
  Pinterest pin → 5 formats; X post → 3 formats; VK video → 12
  formats.
- Downloads exercised end-to-end: YouTube SRT + transcript (via the
  Invidious path on the plain server, and via the yt-dlp cascade in
  the harness — identical 17,574-char transcript), YouTube MP3 via
  Invidious (real MP3, correct duration), TikTok MP3 (ID3, 800,957
  bytes).
- Ratings: zero-state → POST 5★ (with an XSS-attempt name) → average
  5.0, count 1 → POST 4★ → **average 4.5, "(2 ratings)", 90 % star
  fill** → duplicate POST → 409 → invalid stars → 400 → **app restart
  → ratings persist** → homepage HTML shows the malicious name
  **escaped** (`&lt;script&gt;…`), zero raw occurrences.
- SEO spot checks after all changes: homepage + platform-page titles
  and canonicals intact, sitemap still 8 URLs, robots.txt unchanged,
  /terms 200.
- i18n parity re-run: 30 languages × 178 keys, zero failures;
  29 platform payloads intact.
- **Cleanup done:** all test ratings deleted — `data/` does not exist
  in either tree, so the live site starts from a true zero.

### Network caveat (honest)
This sandbox sits behind a TLS-intercepting proxy, so the app's
yt-dlp attempts fail certificate verification here (the same artifact
FEATURES-TEST-REPORT.md worked around with `--no-check-certificate`).
Two consequences: (a) on the plain local server, YouTube traffic fell
back to the Invidious path — which is a real production path and
passed fully; (b) the yt-dlp-direct paths (TikTok MP3, Pinterest/X/VK
info, cascade captions) were exercised through a throwaway harness
that injects `nocheckcertificate` into `_build_opts` — **test-only,
no shipped code changed**. Render's network has no such proxy; the
cascade is unchanged from the already-live build. X was reachable
from here after all and passed.

## 5. Known limits

- **Ratings storage is ephemeral on Render Free.** `data/ratings.json`
  survives process restarts (verified) but **not** redeploys,
  filesystem resets or instance replacement. Durable ratings need a
  real store (Render Disk is paid; a free external DB is the other
  option) — decide before promoting the widget heavily.
- **One-rating-per-browser is a soft limit** (cookie only). Clearing
  cookies or another browser allows another rating. There is no
  account system by design.
- **No admin panel / moderation UI.** To remove a review, edit
  `data/ratings.json` on the server (entries carry name/stars/text/
  date) — or delete the file to reset to the honest zero state.
- **Dailymotion is still unlisted and untested from Render's
  network.** It returned no formats from this sandbox; if it is ever
  wanted, run one live test from the deployed site first — do not
  list it before that passes.
- Caption availability is per-video: some videos have no caption
  tracks at all, in which case the Subtitles/Transcript group is
  hidden by design. Machine (auto) captions are labelled as such by
  the track name where the source provides it.
- MP3/transcript/subtitle downloads of long videos are bounded by
  the same free-tier limits as video downloads (bandwidth, request
  timeouts).

## 6. Handover state

Nothing pushed, nothing deployed. Both trees md5-identical for all
ship files (app.py, i18n.py, all templates, .gitignore; the two
Dockerfiles differ only by the repo tree's pre-existing
`make_icons.py`/pillow lines, as before). Go-live remains the single
combined step: snapshot push (Qudoos's approval) → Render Manual
Deploy → live check → Search Console submission.
