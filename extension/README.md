# QGrab Downloader — browser extension (Chrome / Edge, Manifest V3)

Adds a small, IDM-style **QGrab panel** on YouTube and Facebook video pages.
Click **⬇ QGrab** in the floating panel (bottom-right of the page) to see the
real formats QGrab offers for that video, and download the one you want.

> **Honest note:** this extension does **not** download anything directly
> from YouTube or Facebook. Every download link opens the QGrab website
> (`https://qgrab.onrender.com`), and **QGrab's server processes the
> download** — exactly like using the website by pasting the link there.
> The extension is only a shortcut panel on the video page.

## What it does

- On a YouTube video page (`youtube.com/watch`, Shorts, `youtu.be` links)
  and on Facebook video pages (`facebook.com/watch`, reels, `…/videos/…`),
  a floating **QGrab** panel appears at the bottom-right.
- Clicking **⬇ QGrab** asks `qgrab.onrender.com/api/info` for that video's
  formats and lists them (label + file size where known). Each format is a
  link to `qgrab.onrender.com/download?url=…&format_id=…`.
- If the format lookup fails (offline, QGrab busy, unsupported video), the
  panel falls back to a single **“Open in QGrab”** link that opens the video
  on the QGrab website, with a short note explaining what happened.
- The toolbar popup explains the extension and has an **Open QGrab** button.

## Install (unpacked — not on the Chrome Web Store yet)

This extension is **not published on the Chrome Web Store yet**, so you
install it manually from the unzipped folder:

1. Download and **unzip** `qgrab-extension.zip`. Remember where the folder is
   (you should see `manifest.json` inside it).
2. Open your browser's extensions page:
   - **Chrome:** `chrome://extensions`
   - **Edge:** `edge://extensions`
3. Turn **Developer mode** ON (toggle at the top-right of that page; in Edge
   it is in the left sidebar).
4. Click **Load unpacked**.
5. Select the unzipped extension folder (the one containing `manifest.json`).
6. Done — open any YouTube or Facebook video and look at the bottom-right
   corner for the QGrab panel. Pin the extension from the puzzle-piece menu
   if you want its icon in the toolbar.

To update later: unzip the new version over the old folder, then click the
**reload** (↻) button on the extension's card on the extensions page.

To remove it: on the extensions page, click **Remove** on the QGrab card.

## Notes & limits

- **Facebook changes its page layout often.** The panel is a floating
  fixed-position element that does not depend on Facebook's internal page
  structure, so redesigns should not break it — but video-link *detection*
  can occasionally miss a new Facebook URL shape. If the panel does not
  appear on a Facebook video, use **Open QGrab** from the toolbar popup and
  paste the link on the website instead.
- YouTube / Facebook may change their pages in ways that affect detection;
  the same “paste it on QGrab” fallback always works.
- A QGrab account / plan rules on the website apply to downloads the same
  way as when you use the website directly.
- Permissions used: `activeTab`, plus access to `youtube.com`,
  `facebook.com`, and `qgrab.onrender.com` only. The extension stores
  nothing and sends nothing anywhere except the current video page URL to
  QGrab when you click the **⬇ QGrab** button.

## Files

| File | Purpose |
| --- | --- |
| `manifest.json` | Manifest V3 definition (permissions, content scripts, service worker, popup) |
| `content.js` | Floating panel on video pages + pure URL-detection helpers |
| `background.js` | Service worker: calls QGrab `POST /api/info` and returns formats |
| `popup.html` / `popup.js` | Toolbar popup: explanation + “Open QGrab” button |
| `icons/` | Extension icons (from QGrab's own site icons) |
| `test_logic.js` | Node unit tests for the URL helpers: `node extension/test_logic.js` |
