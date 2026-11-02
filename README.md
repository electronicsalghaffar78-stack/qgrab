# QGrab — All-in-One Video Downloader (v1)

A small web app where a visitor pastes a video link (YouTube, TikTok,
Instagram, Facebook, Twitter/X, Dailymotion and 1000+ other sites that
yt-dlp supports), sees the video's title / thumbnail / duration and the
available qualities, and downloads the one they pick.

> **Name note:** the site is branded **QGrab** with the "Q" logo (white Q ring, play triangle, red download-arrow tail on deep navy) in `static/icons/`.
> **Legal note:** the site carries a personal-use disclaimer. Visitors should
> only download videos they own or have permission to save.

## How to run it locally

From this folder (`~/workspace/downloader-site/`):

```bash
# one-time setup (already done on this machine, repeat on a new one)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# start the site
.venv/bin/python app.py
```

Then open **http://127.0.0.1:5000** in a browser.

Useful options:

```bash
PORT=8080 .venv/bin/python app.py          # different port
HOST=0.0.0.0 .venv/bin/python app.py       # reachable from other devices on the LAN
```

Stop it with `Ctrl+C`.

## How it works

- `app.py` — a Flask server with three routes:
  - `GET /` — serves the single-page UI (`templates/index.html`).
  - `POST /api/info` — takes `{"url": "..."}`, asks **yt-dlp** for the video's
    metadata, and returns title, thumbnail, duration and a cleaned-up list of
    formats (quality, file type, size, with-sound / video-only / audio-only)
    as JSON.
  - `GET /download?url=...&format_id=...` — looks up that format's real media
    URL via yt-dlp, then **streams the file through this server** to the
    visitor with the correct filename. Streaming through the server (with the
    headers yt-dlp provides) is what makes downloads work even when a
    platform's direct link needs a specific browser header. Byte-range
    requests are passed through, so downloads can resume.
- `templates/index.html` — the whole front end: one self-contained page
  (no external CSS/JS files), dark theme, mobile-first. It includes clearly
  marked **AD placeholder boxes** (top banner + in-content) showing where ad
  units will go later, a supported-platforms row, a 3-step "How to use"
  section, an FAQ, and the personal-use/copyright disclaimer in the footer.
- `requirements.txt` — pinned Python dependencies (Flask + yt-dlp).
- `.venv/` — the local Python environment for this project.

Notes / v1 limitations:

- Many sites (YouTube especially) now serve video and audio as **separate**
  streams. For those, the format list includes "with sound" options marked
  *merged on download*: when picked, the server downloads the best video
  (up to 1080p) + best audio and joins them into one MP4 with **ffmpeg**
  before sending it. That makes ffmpeg a required system tool on the host
  (`ffmpeg -version` should work). Bigger merged files take a little longer
  to start because the merge happens first.
- Formats delivered as HLS (`.m3u8`) streams are filtered out of the direct
  list — v1 only offers direct single-file downloads plus the merged option
  above.
- No accounts, no history, nothing is stored on the server: each download is
  fetched live from the original platform.
- Very large files pass through the server, so the host needs decent
  bandwidth once the site is public.

## App plan (phone app + PC)

The product is **not website-only**. The plan has two phases:

**Phase 1 — Responsive website + PWA (done in v1).**
The site is mobile-first and ships as a **Progressive Web App**:

- `static/manifest.webmanifest` — app name "QGrab", dark theme colors
  matching the UI, `display: standalone`, and icon entries
  (`static/icons/`: 192px + 512px PNGs, a maskable 512px, and an Apple
  touch icon — all derived locally with PIL from the chosen "Q" logo,
  `static/icons/qgrab-logo.webp`).
- `static/sw.js` — a service worker, served by the app at `/sw.js` so its
  scope covers the whole site. It caches the homepage shell (page,
  manifest, icons) so the installed app opens instantly and the homepage
  loads offline. `/api/` and `/download` requests are never cached.
- The page has an **"Install The QGrab App"** section: on Android/Chrome
  it shows a real Install button when the browser offers one
  (`beforeinstallprompt`), and it always shows the manual steps —
  Android: menu → "Add to Home screen"; iPhone Safari: Share → "Add to
  Home Screen". On PC the same site simply runs in the browser (Chrome/Edge
  can also install it as a desktop app from the address-bar icon).

Result: users get an installable app icon on their phone and a full
experience on PC, from this one codebase, with no app store involved.

**Phase 2 — Android APK (later, not built yet).**
A thin native Android app that is basically a **WebView wrapper around the
live website** (loads the real site, handles downloads through the
Android download manager, and nothing more). It will be **distributed as
an APK download from our own website**, because Google Play does not
allow video-downloader apps on the Play Store — direct distribution is
the normal route for this category.

What the APK build will need when we get there:

- Android Studio / Android SDK + Gradle on a PC to build and sign the APK.
- One small project: a single-activity WebView app with a download
  listener, our icon/name, and the production site URL baked in.
- A signing key (kept safe — all future updates must use the same key).
- iPhone note: Apple does not allow sideloading like this, so on iPhone
  the Phase 1 PWA ("Add to Home Screen") remains the app experience.

## Deployment notes (for later — not done yet)

- Needs a small **VPS** (e.g. 1–2 GB RAM) or a Python-friendly PaaS
  (Render / Railway / Fly.io style). A domain name will be bought later and
  pointed at it.
- On a VPS, run it properly behind a process manager and reverse proxy, e.g.:

  ```bash
  .venv/bin/pip install gunicorn
  .venv/bin/gunicorn -w 2 --timeout 300 -b 127.0.0.1:5000 app:app
  ```

  …with Nginx (or Caddy) in front for HTTPS (free certificates via
  Let's Encrypt) and the public domain.
- **Keep yt-dlp updated** — platforms change their sites often; most
  "downloads stopped working" problems are fixed by
  `.venv/bin/pip install -U yt-dlp`.
- Ads: the placeholder boxes mark the spots. When a real ad network account
  exists (e.g. AdSense or an alternative network), replace those boxes with
  the network's ad code.
- Some platforms (notably Instagram/Facebook private content) may require
  login cookies to download; that is intentionally **not** part of v1.
