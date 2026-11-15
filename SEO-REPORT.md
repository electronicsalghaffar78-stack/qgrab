# QGrab — SEO Overhaul Report

Prepared: 2026-11-03 · Status: **built and verified locally — NOT pushed, NOT deployed.**
Site: https://qgrab.onrender.com (Render free tier, Docker `./deploy/Dockerfile`)

Goal: make QGrab indexable and rankable for "QGrab", "video downloader",
"YouTube video download", "TikTok video download", "Facebook video
download" and "Instagram video download".

All copy is honest — it describes only what QGrab verifiably does
(YouTube/TikTok/Facebook downloads working, TikTok watermark-free,
public posts only, personal use). No fake stats, no fake testimonials.

---

## 1. Files changed — BOTH trees, kept identical (md5-verified)

Trees: master `~/workspace/downloader-site/` and deploy copy
`~/workspace/qgrab-repo/`. The deploy `Dockerfile` copies the whole
`templates/` directory, so the new template ships automatically.

| File | Change |
|---|---|
| `app.py` | **Modified.** Added `SITE_URL`, honest copy data for the 4 platform pages (`PLATFORM_PAGES`), FAQ JSON-LD builder, 4 new page routes, `/sitemap.xml` and `/robots.txt` routes. No download/extraction code touched. |
| `templates/platform.html` | **NEW.** Shared template for the 4 landing pages: same design language + same downloader form/JS as the homepage, per-page title/meta/canonical/OG/Twitter, FAQPage JSON-LD generated from the same data as the visible FAQ (cannot drift apart), trust chips, 3 steps, content sections, FAQ, internal links to home + the other 3 downloaders, full footer nav, personal-use disclaimer. |
| `templates/index.html` | **Modified.** New SEO title + meta description, keywords, robots, canonical, Open Graph + Twitter cards, WebApplication + FAQPage JSON-LD (matches the 5 visible FAQs), H1 now "Free Video Downloader", new "Download Videos From Every Platform" guide section with the 4 target-phrase H2s, Popular Downloaders cards now link to the new pages, footer "Downloaders" column links to the new pages. |
| `templates/terms.html` | **Modified.** Canonical + robots meta; footer gained a downloader-links line. |
| `templates/privacy.html` | **Modified.** Same as terms. |
| `templates/dmca.html` | **Modified.** Same as terms. |

Untouched, as required: download routes/logic (`/api/info`, `/download`,
Invidious fallback, cookie handling), `static/sw.js` (PWA service
worker), `static/manifest.webmanifest`, logo handling
(`static/icons/logo-base64.txt` + `make_icons.py`).

## 2. Final titles + meta descriptions

**Home — `/`**
- Title: `QGrab — Free Video Downloader | Download YouTube, TikTok, Facebook & Instagram Videos`
- Meta: `Download videos free with QGrab — the free video downloader for YouTube, TikTok, Facebook & Instagram. HD quality, no sign-up, TikTok with no watermark.` (~152 chars)
- Canonical: `https://qgrab.onrender.com/` · H1: "Free Video Downloader"
- H2 guides: "Download YouTube Videos", "TikTok Video Downloader — No Watermark", "Facebook Video Downloader", "Instagram Video Downloader"
- JSON-LD: WebApplication (MultimediaApplication, operatingSystem Web, offers price 0) + FAQPage (the 5 visible FAQs)

**`/youtube-video-downloader`**
- Title: `YouTube Video Downloader — Download YouTube Videos Free in HD | QGrab`
- Meta: `Download YouTube videos free with QGrab. Save videos in HD up to 1080p with sound, or save the audio only. No sign-up and nothing to install.` (~143 chars)
- H1: "YouTube Video Downloader"

**`/tiktok-video-downloader`**
- Title: `TikTok Video Downloader — Download TikTok Videos Without Watermark | QGrab`
- Meta: `Download TikTok videos without the watermark, free with QGrab. Paste the TikTok link, pick a quality and save the clean video to your phone or PC.` (~148 chars)
- H1: "TikTok Video Downloader — No Watermark"

**`/facebook-video-downloader`**
- Title: `Facebook Video Downloader — Download Facebook Videos & Reels Free | QGrab`
- Meta: `Download Facebook videos and reels free with QGrab. Paste a public Facebook video link, choose the quality and save the video straight to your device.` (~152 chars)
- H1: "Facebook Video Downloader"

**`/instagram-video-downloader`**
- Title: `Instagram Video Downloader — Download Instagram Videos & Reels Free | QGrab`
- Meta: `Download Instagram videos and reels from public posts, free with QGrab. Paste the link, pick a quality and save the video — no login needed.` (~144 chars)
- H1: "Instagram Video Downloader"

Each landing page also has: the working downloader form, a platform
3-step "how to" section, 3 honest content sections (features /
limitations / personal-use note), a 4-question FAQ with matching
FAQPage JSON-LD, and internal links to home + the other 3 downloader
pages (plus the footer nav that appears on every page, legal pages
included). Every page has exactly one H1; all logo/thumbnail images
carry alt text ("QGrab logo" / "Video thumbnail").

**Technical endpoints**
- `/sitemap.xml` — dynamically generated, well-formed XML, 8 URLs:
  `/`, the 4 downloader pages, `/terms`, `/privacy`, `/dmca`
  (canonical `https://qgrab.onrender.com` domain, lastmod = build day).
- `/robots.txt` — `User-agent: *` / `Allow: /` + `Sitemap:` line.

## 3. Local verification (all run 2026-11-03, Flask dev server, port 5057)

- HTTP 200: `/`, all 4 new pages, `/sitemap.xml`, `/robots.txt`,
  `/terms`, `/privacy`, `/dmca`, `/healthz`, `/sw.js`, logo file.
- Homepage: exact new title + meta served; canonical present; OG +
  Twitter tags present; exactly 1 H1 ("Free Video Downloader"); all 4
  target-phrase H2s present; 2 JSON-LD blocks (WebApplication,
  FAQPage), both parse as valid JSON; FAQ JSON-LD questions match the
  visible FAQs 5/5; download form + personal-use disclaimer present.
- Each platform page: unique title + meta + canonical served; exactly
  1 H1 with the exact target phrase; download form present (same
  form/JS mechanism as homepage); 4 visible FAQs; FAQPage JSON-LD
  valid and matching the visible FAQs 4/4 on every page (Facebook:
  the only diff was the HTML-escaped apostrophe `&#39;` vs raw `'`
  in JSON — identical rendered text); internal links to all downloader
  pages present; disclaimer present.
- `sitemap.xml` parsed with an XML parser: well-formed, 8 `<loc>`s.
- `robots.txt` body confirmed (allow-all + Sitemap line).
- Download machinery intact: `POST /api/info` with an invalid URL
  returns the normal validation error JSON (route + validation
  unchanged). A full live download was **not** re-tested locally —
  extraction/download code is byte-identical to the previously
  live-verified version; only templates + additive routes changed.
- Both trees md5-identical for every changed file; `app.py` compiles.

## 4. Remaining steps to go live (for Archer + Qudoos)

1. **Snapshot push to GitHub** — push the changed files (TEXT only,
   as usual) to `github.com/electronicsalghaffar78-stack/qgrab`:
   `app.py`, `templates/index.html`, `templates/platform.html` (new),
   `templates/terms.html`, `templates/privacy.html`,
   `templates/dmca.html`. **Needs Qudoos's approval tap on the card.**
2. **Render deploy** — Render does NOT auto-deploy: dashboard →
   service "qgrab" → **Manual Deploy → Deploy latest commit**, then
   wait for the build (Docker; `make_icons.py` runs as before).
3. **Verify live** — open https://qgrab.onrender.com and check: new
   homepage title, the 4 downloader pages load, `/sitemap.xml` and
   `/robots.txt` respond, and one real download still works.
4. **Google Search Console** (do this right after the deploy is live):
   - Go to https://search.google.com/search-console (sign in with the
     site account — electronicsalghaffar78@gmail.com).
   - Add property → **URL prefix** → `https://qgrab.onrender.com`.
   - Verify ownership: easiest is the **HTML tag** method — copy the
     meta tag Google gives, Archer adds it to the homepage `<head>`
     (one more small push + deploy), **or** the HTML file method —
     upload the `googleXXXX.html` file it offers into the repo root
     and add a tiny route/static serving for it (ask Archer; the meta
     tag route is simplest for this codebase).
   - Sitemaps → enter `sitemap.xml` → Submit.
   - URL Inspection → for `/` and each of the 4 downloader pages →
     **Request Indexing** (one by one; daily quota is small, home +
     YouTube + TikTok first if it caps out).
5. **Set expectations honestly**: indexing usually takes days, and
   ranking for competitive terms like "video downloader" takes weeks
   to months of the site being live, indexed and linked. The brand
   term "QGrab" should appear first. Nothing here guarantees a #1
   ranking — this overhaul gives Google everything it needs to index
   and understand the site; the rest is time + real users sharing the
   link (which Qudoos is already doing).

---

## 5. Addendum — Script + Prompt SEO expansion (2026-11-04)

Status: **built and verified locally in both trees — NOT pushed,
NOT deployed.** Owner's order: people searching for making a video
script or video prompts should find QGrab. Target phrases: "video
to script", "video script generator", "video scripting", "get
script from a video", "youtube video to script", "tiktok video to
script", "video to prompt", "AI video prompt generator", "video
prompt maker", "make prompts from a video". Done as real content
(titles, descriptions, headings, FAQ, dedicated pages) — no keyword
stuffing.

**Tool page `/video-to-script-prompt`** (`templates/scriptprompt.html`)
- Title: `Video to Script + AI Video Prompt Generator — Free | QGrab`
- Meta description: "Paste a video link and get its full script —
  from subtitles or the audio itself — plus scene-by-scene AI video
  prompts. Free video to script + prompt generator, no sign-up."
  (Also corrects the old "subtitles only" wording in the meta/OG/
  Twitter descriptions — the audio route has existed since SP v2.)
- Keywords meta extended to the full target-phrase list above.

**Homepage `/`** (`templates/index.html`)
- Keywords meta extended with the script/prompt phrases.
- WebApplication JSON-LD gained a `featureList` (existing honest
  features plus "Video to Script Converter" and "AI Video Prompt
  Generator").
- Meta description deliberately **unchanged**: it is already ~152
  chars, and appending a script/prompt clause would push it past
  ~200 — too long to stay natural. The script/prompt angle is
  covered by the keywords, the featureList, the tool page and the
  two new landing pages instead.

**Two new landing pages** — same `PLATFORM_PAGES` + `platform.html`
machinery, marked `"tool": True`: the hero is a CTA card into
`/video-to-script-prompt` instead of the downloader form (the
downloader JS is not shipped on these pages), the downloader specs
table is skipped, per-page keywords/heading overrides are used,
and tool pages are excluded from the "other downloaders" cards so
the four downloader pages are byte-identical in that section. Each
page has 3 honest FAQ Q&As emitted as FAQPage JSON-LD from the same
data as the visible FAQ:
- `/video-script-generator` — Title: `Video Script Generator —
  Video to Script, Free Online | QGrab` · H1: "Video Script
  Generator". Copy: paste a YouTube/TikTok/Facebook/Instagram link,
  get the full script from subtitles or from the audio itself
  (20-min cap on the audio route, stated honestly); editable
  preview, .txt download.
- `/ai-video-prompt-generator` — Title: `AI Video Prompt Generator
  — Make Prompts from Any Video | QGrab` · H1: "AI Video Prompt
  Generator". Copy: scene-by-scene prompts built from the video's
  own (editable) script, carrying the production rules; FAQ states
  plainly that QGrab does not generate videos itself.

**All Tools list** (`templates/_tools.html` + 2 keys added to the
EN dict in `i18n.py` only — other languages fall back to English,
no 30-language churn): new entry "Video to Script + Prompts" →
`/video-to-script-prompt`, following the existing entry format.

**Sitemap**: both new URLs are picked up automatically from
`PLATFORM_PAGES` — `/sitemap.xml` now lists **11 URLs** (was 9).

**Verification (2026-11-04, Flask test client, both trees)**:
150 checks PASS / 0 FAIL in the master tree and 0 failures in the
deploy tree — homepage, tool page and both new pages render 200 in
English and Urdu; titles/descriptions/keywords as specified;
exactly one H1 per new page; 3 visible FAQs matching the FAQPage
JSON-LD on both new pages; all JSON-LD parses; every rendered
script block passes `node --check`; the YouTube downloader page is
unchanged (form, generated keywords, specs, other-downloader cards
all intact); sitemap parses as XML with 11 `<loc>`s. Previous
suites still pass in both trees: `tests/test_sp_audio.py` 5/5,
`tests/test_formats_audio_rule.py` 8/8. Files changed (identical
in both trees, md5 in the delivery report): `app.py`, `i18n.py`,
`templates/index.html`, `templates/platform.html`,
`templates/scriptprompt.html`, `templates/_tools.html`.

To go live, follow the same steps as §4 (snapshot push of those 6
files → Render Manual Deploy → verify → in Search Console, submit
the updated sitemap and request indexing for the 2 new pages and
the tool page).
