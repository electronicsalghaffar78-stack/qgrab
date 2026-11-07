# QGrab Update — 2026-11-08 — Video Toolkit (Phase 1, CORE)

Owner-ordered feature, built after the Serper search fix went live
(owner's sequence: "Serper first, Toolkit after"). The owner
described a tools site ("Y Tool") where pasting a video link opens
a details page — thumbnail, title, published date, views, likes,
description, hashtags, tags, quick copy actions — and asked for a
"Video Toolkit" section on QGrab with the same core for YouTube,
Facebook, TikTok, Instagram and the other supported platforms.

Status: **built + tested locally, NOT pushed, NOT deployed.**

## What was built

### Backend — `GET /api/video-details?url=<video page URL>`
- Validation reuses `/api/info`'s `clean_url()`: non-empty
  http(s) only, ≤2048 chars; junk → `400 {"error": <api_invalid>}`.
  Extraction failure → `422 {"error": <api_friendly>}` (raw
  extractor errors stay in the server log, same contract as
  `/api/info`). Playlist answers unwrap to the first entry, also
  like `/api/info`.
- Extraction reuses the existing `extract_info()` path (cascade +
  per-platform fallbacks + 10-minute cache) — no new fetching
  machinery, no extra quota anywhere.
- Success payload: `{"ok": true, ...}` shaped by
  `_shape_video_details(info, url)`:
  `title, description, thumbnail (best/largest: shaped
  'thumbnail' field, else biggest entry of the 'thumbnails'
  ladder by pixel area), webpage_url, uploader, channel_url
  (channel_url → uploader_url), upload_date (YYYY-MM-DD, from
  upload_date YYYYMMDD or a publish epoch), view_count,
  like_count, comment_count (ints or null), duration, duration_h,
  site, tags (list, ≤100), hashtags`.
- Hashtags: `_extract_hashtags()` — `#[\w]+` (Unicode-aware) over
  title + description, deduped, first-seen order, `#` kept.
- **Honesty rule:** fields a platform does not publish stay
  `null` (never invented) and the UI hides them.

### Shaper enrichment (genuinely-present fields only)
The shaped infos for three fallback paths used to drop metadata
their raw answers carry; they now surface it (extra keys only —
`/api/info`, `/download` and the SP tool ignore them):
- **Invidious (YouTube fallback):** description (HTML flattened
  to text), viewCount, likeCount, published epoch,
  `https://www.youtube.com` + authorUrl, keywords → tags.
- **tikwm (TikTok fallback):** caption as description,
  play_count → view_count, digg_count → like_count,
  comment_count, create_time, `https://www.tiktok.com/@<unique_id>`
  as uploader_url.
- **Instagram embed:** full caption as description, owner
  username as uploader, like/comment edge counts,
  taken_at_timestamp.
- yt-dlp's native path already carries all of these fields for
  YouTube/TikTok/Facebook/X etc.; the endpoint reads them
  directly.

### Homepage — "Video Toolkit" section
- New partial `templates/_toolkit.html`, included in
  `templates/index.html` directly below the Search Videos
  section; CSS added beside the Search CSS (theme variables,
  cards, chips — `#tkMsg` shares the `#searchMsg` rules).
- Paste-link input + **Get Details** → details card:
  big thumbnail with a **Download Thumbnail** anchor (direct
  image URL, `download` attribute), title with **Copy**,
  meta row (site · uploader · published · views · likes ·
  comments · duration — non-null only), collapsible description
  ("Read more", shown only when long) with **Copy**, **Hashtags**
  chips with **Copy All**, **Video Tags** chips with **Copy All**
  or an honest "No tags found for this video." state, **View
  Channel** (only when a channel URL exists), and **Download
  Video**, which hands the URL to the existing main downloader
  flow exactly like the Search results' Download button.
- Tools grid with exactly four WORKING cards — **Video Details**,
  **Thumbnail Downloader**, **Hashtag Extractor**, **Video Tags
  Extractor**. Each reuses the same details fetch: with no
  details loaded it scrolls to and focuses the paste box; with
  details loaded it scrolls to and flashes the relevant part of
  the card. No separate/fake backends.
- All dynamic text is injected via `textContent` (no innerHTML
  with remote data); clipboard uses `navigator.clipboard` with a
  textarea/`execCommand` fallback; the fetched URL is
  `encodeURIComponent`-escaped.

## Per-platform field availability (honest)
- **YouTube (yt-dlp or Invidious):** full set — description,
  date, views, likes, comments (yt-dlp path), tags, channel URL.
- **TikTok (yt-dlp):** description (caption), counts, date,
  uploader URL. **(tikwm fallback):** same via enrichment.
  Tags are usually empty on TikTok — the UI then shows the
  honest "No tags found" state; hashtags come from the caption.
- **Instagram (embed fallback):** caption/description, uploader,
  likes, comments, date, thumbnail. No tags field exists.
- **Facebook (embed fallback):** title only — description,
  counts, date, thumbnail stay null and are hidden.
- **X / Pinterest / VK (yt-dlp):** whatever the extractor
  publishes (typically title/thumbnail/uploader, sparse counts).

## Tests
- New `tests/test_toolkit.py` — **13 tests, all pass**: hashtag
  extraction (dedupe/order/Unicode/junk), rich YouTube shaping,
  best-thumbnail ladder pick, timestamp→date, minimal
  TikTok-shaped null honesty, tikwm + Invidious enrichment
  shaping, endpoint 400s (missing/junk), mocked-extractor 200
  (asserts no raw `formats` leak), friendly 422.
- `tests/test_homepage_js.js` extended: `/api/video-details`
  fetch stub + two checks (card renders; null comment count
  hidden; thumbnail/chips/channel filled) — **all pass**.
- Full suites, master tree: **13/13 Python files exit 0**
  (incl. test_search 20/20, test_site_hardening, test_sp_*),
  **4/4 Node suites pass**.
- Mirror tree (qgrab-repo): same results; the known pre-existing
  `test_install_button.py` mirror failure (generated PNG icons
  absent from the repo snapshot) is unrelated — see test report
  in the hand-off; master passes it.

## Deliberately NOT in phase 1
- No AI generators (hashtag/title/tag generators) — phase 2
  candidate on the existing Gemini stack with its own cap.
- No Trending Videos / Find Competitor / Explore Channel /
  Earning Calculator — they need live platform data this site
  does not have; not even greyed-out cards were added.
- No new endpoint quota/caps; no changes to `/api/search`,
  `/api/info`, `/download`, `sw.js` or the SP tool.
- Not pushed, not deployed — owner's normal release flow
  (push → Render Manual Deploy → live smoke) still applies.
