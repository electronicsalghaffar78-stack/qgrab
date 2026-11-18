# QGrab — All Platform Video Download in One Place

**Live:** https://qgrab.onrender.com · **Version:** 2026-11-17.29 ·
**Code:** github.com/electronicsalghaffar78-stack/qgrab

QGrab is a free, no-account web app for downloading public videos:
paste a link, pick a format, download. It also bundles a set of
creator tools (AI Tools, Script+Prompt, a Video Toolkit) around the
downloader. Everything is free with **no usage limits** — there is no
pricing, no premium tier and no sign-up.

> **Name note:** the site is branded **QGrab** with the "Q" logo
> (white Q ring, play triangle, red download-arrow tail on deep navy)
> in `static/icons/`.
> **Legal note:** the site carries a personal-use disclaimer.
> Visitors should only download videos they own or have permission
> to save.

## Platforms

Downloads work from 13 platforms: YouTube, TikTok, Instagram,
Facebook, X (Twitter), Pinterest, SoundCloud, Twitch, Telegram
(public posts), VK, Vimeo and Dailymotion.

**Reddit is the exception:** downloads are currently unavailable
because Reddit restricts automated access from the server. The site
says so honestly wherever Reddit is listed; the Reddit page and
route still exist for the day access works again. Private or
login-only videos cannot be downloaded on any platform.

## What the site includes

- **Downloader** — grouped formats (video with sound first), MP3
  audio, subtitles and transcript downloads where the platform
  offers them; byte-range streaming through the server so downloads
  can resume.
- **Search** — YouTube search in the page, plus web video search.
- **AI Tools (6)** — title/description generators and helpers,
  powered by AI (see below).
- **Script+Prompt** — turns a video into a scene-by-scene script and
  ready-to-use image/video prompts; it also auto-starts alongside a
  download. It can also work from a pasted transcript or your own
  script.
- **Video Toolkit** — thumbnail grabber and related utilities.
- **AI Assistant + support** — an on-site assistant that answers
  QGrab questions in the visitor's language, a "Talk to Support"
  form, and a report-a-problem form.
- **Ratings & reviews**, **Telegram Proxies** page (100 proxies),
  **Download History** page (stored in the visitor's own browser),
  **browser extension** (manual Developer-mode install; not on the
  Chrome Web Store yet), **PWA** install on phones and desktops.
- **30 languages** of interface text (`i18n.py`), SEO pages for
  every platform, sitemap and legal pages (Terms / Privacy / DMCA).
- **No ads at this time.** If ads are ever introduced, they will be
  clearly marked as ads. (The old ad placeholder boxes were removed
  in build .29.)

## How it works

- `app.py` — the Flask server (52 routes). Key routes:
  - `GET /` — the homepage (`templates/index.html` + includes);
    one page per platform under `/<platform>-video-downloader`,
    plus `/download-history`, `/telegram-proxies`, the
    Script+Prompt pages and the legal pages.
  - `POST /api/info` — takes `{"url": "..."}`, asks **yt-dlp** for
    metadata and returns title, thumbnail, duration and a cleaned,
    grouped list of formats as JSON.
  - `GET /download?url=...&format_id=...` — resolves the real media
    URL via yt-dlp and **streams the file through this server** with
    the correct filename and headers; byte-range requests are
    passed through so downloads can resume.
  - `POST /api/ai-tools/*`, `POST /api/assistant`,
    `POST /api/script-prompt` (+ status/quota) — the AI features.
  - `/api/ratings` + `/api/rate`, `/api/support`, `/api/report` —
    visitor feedback (stored as JSON files, see the note below).
- **AI providers:** text generation defaults to **Ant Ling**
  (`Ling-3.1-flash`, thinking disabled; `Ming-3.0-asr-tiny` for the
  Script+Prompt audio route) and falls back to a **Google Gemini**
  chain (fastest model first) if Ant Ling is unavailable or its
  daily free quota is exhausted. Thumbnail *image* generation is
  Gemini-only. Provider keys live only in the host's environment
  variables (`ANT_LING_API_KEY`, `GEMINI_API_KEY[_2/_3]`,
  `QGRAB_SERPER_API_KEY`, `SUPPORT_INBOX_KEY`) — never in the repo.
- `templates/` — the front end (server-rendered, no build step).
- `requirements.txt` — pinned Python dependencies (Flask + yt-dlp).

## Run it locally

From this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Then open **http://127.0.0.1:5000**. Options: `PORT=8080`,
`HOST=0.0.0.0` (LAN). Stop with `Ctrl+C`. Without provider keys in
the environment, the downloader works and the AI features report
themselves as not configured.

## Deployment

Hosted on **Render** (free plan) from the GitHub repo above.
Pushes go to `main`; because of a webhook issue, a **Manual Deploy**
on Render is required after each push. The service reports its
build at `GET /api/version` (used by the installed PWA's
"Update App" button).

## Known limitations (honest list)

- **Visitor data is ephemeral:** ratings, support tickets, problem
  reports and stats are JSON files on the host's disk and reset on
  redeploy — a durable store is a known pre-investment task.
- **Free hosting fences:** the Render free plan sleeps when idle
  and has monthly instance-hour/bandwidth caps shared with the
  owner's other service.
- **Script+Prompt first run:** for a fresh video, fetching the
  video/captions from the platform can take minutes from a
  datacenter IP; the AI step itself takes seconds, and repeat
  requests are served from cache.
- **Reddit:** currently unavailable (see Platforms above).

## Tests

```bash
.venv/bin/python tests/test_<name>.py   # 35 Python suites
node tests/test_<name>.js               # 6 JS suites
```

Build history lives in the `UPDATE-*.md` notes in this repo.
