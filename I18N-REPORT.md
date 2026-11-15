# QGrab — Specs Table + 30-Language i18n Report

Built and verified locally on 2026-11-03. **Not pushed, not deployed** —
go-live still needs the usual steps: snapshot push (Qudoos approves) →
Render Manual Deploy → verify live. Both trees
(`~/workspace/downloader-site/` and `~/workspace/qgrab-repo/`) hold
identical copies of every changed file (md5-verified, see below).

## Addition 1 — Specs / info table

Shared include `templates/_specs.html`, rendered once on the homepage
(after the platform-guide section, before the How-To section) and once
on every platform page (after the content sections, before the FAQ).
Two-column rows (icon + label + value), styled to the existing dark
theme (`.specs` / `.spec` rules in `templates/_extras.html`). Values are
exactly the approved honest ones — nothing inflated:

| Label | Value |
|---|---|
| Quality | 480p · 720p · 1080p HD (depends on the original video) |
| Platforms | YouTube · TikTok · Facebook · Instagram |
| Limits | No registration needed |
| Pricing | $0 — Free |
| Speed | Fast |
| Uptime | Online 24/7 |

All labels and values go through the i18n string table (`spec_*` keys),
so the table is fully translated in every language.

## Addition 2 — 30-language UI

New module `i18n.py`:

- `LANGUAGE_LIST` / `LANGUAGES` — the 30 languages in switcher order:
  en English, ur اردو, hi हिन्दी, ar العربية, bn বাংলা, pa ਪੰਜਾਬੀ,
  sd سنڌي, ps پښتو, fa فارسی, tr Türkçe, es Español, pt Português,
  fr Français, de Deutsch, it Italiano, nl Nederlands, pl Polski,
  ru Русский, uk Українська, id Bahasa Indonesia, ms Bahasa Melayu,
  vi Tiếng Việt, th ไทย, zh 中文 (简体), ja 日本語, ko 한국어,
  tl Filipino, ta தமிழ், te తెలుగు, sw Kiswahili.
- `TRANSLATIONS[code]` — a complete shared string dict per language
  (134 keys, exact key parity across all 30, machine-checked): nav,
  topbar, hero, form (placeholder/button/hint), JS strings (button
  states, result meta, format-kind labels, error fallbacks), trust
  chips, specs table, supported-platforms, why/features, popular
  cards, platform guide, how-to steps, homepage FAQ, install box,
  footer, API error messages.
- `PLATFORM_TRANSLATIONS[code][platform]` — for the 29 non-English
  languages × 4 platforms: H1, tagline, input placeholder, 3 how-to
  steps, the 2 platform-specific content sections, 4 FAQ pairs.
  The third content section (personal-use note) comes from the shared
  table so it exists once per language.
- English is the fallback base: `get_strings()` / `platform_strings()`
  merge over English, so a missing key can never break a page. The
  English dict was verified **verbatim** against the approved SEO copy
  (topbar, hero, hints, placeholders, `PERSONAL_USE_NOTE` and
  `FRIENDLY_ERROR` compared programmatically — all equal).

Wiring in `app.py` (download logic, Invidious fallback, PWA and logo
pipeline untouched):

- `_current_lang()` — `?lang=xx` wins, then the `qgrab_lang` cookie,
  else `en`; invalid values fall back to `en`.
- Context processor injects `lang`, `dir`, `t` (strings), `languages`,
  `current_lang_name`, `lang_url()`, `hreflangs`, `js_strings` into
  every template.
- `after_request` persists a valid `?lang=` into the `qgrab_lang`
  cookie (1 year, path `/`, SameSite=Lax).
- `index()` passes the translated homepage FAQ + matching FAQPage
  JSON-LD built from the same pairs (they cannot drift apart).
- `_platform_view()` overlays the platform translations and builds the
  FAQ JSON-LD from the translated pairs; others-cards use translated
  H1s too.
- `/api/info` error messages (`api_invalid`, `api_friendly`) are
  localized via the same helper.

Templates:

- `templates/index.html`, `templates/platform.html` — every hardcoded
  user-facing string replaced by `t.*` / page data; `<html lang="xx"
  dir="rtl|ltr">`; hreflang `<link rel="alternate">` for all 30
  variants + `x-default` (plain canonical URL) in the head; canonical
  stays the plain URL; page JavaScript reads its strings from an
  injected `I18N` object (`js_strings | tojson`).
- `templates/_langmenu.html` — header switcher: 🌐 + current language's
  native name; a `<details>` dropdown listing all 30 native names as
  `?lang=xx` links (works without JS; current language highlighted).
- `templates/_footer.html` — the (previously duplicated) footer,
  extracted once and translated; both page templates include it.
  Minor unification: homepage footer anchors now use `/#how` style
  (same targets) and the downloaders column uses one order
  (YouTube, TikTok, Instagram, Facebook) on both page types.
- `templates/_extras.html` — shared CSS included in both templates'
  `<style>`: specs table, switcher/dropdown, and a minimal RTL block
  (hint/result/footer alignment flips; the URL input stays LTR).
  RTL languages: **ur, ar, fa, ps, sd**.

### What is NOT translated (deliberate)

- **Legal pages** (`/terms`, `/privacy`, `/dmca`) — body stays English,
  as specified. They render fine with any language cookie set
  (verified: 200 with `qgrab_lang=ur`).
- **`<title>` and meta description** of the homepage and platform
  pages stay English (SEO). Visible H1/body copy is translated.
- Brand name "QGrab" and platform names are never translated.
- Ad placeholder labels ("Advertisement space") stay as-is (internal
  placeholders, not user copy).

## Verification evidence (local server, Flask test client + curl)

- Homepage: en/ur/ar/es/zh all 200. en: `<html lang="en" dir="ltr">`,
  title unchanged, H1 renders exactly as before
  (`Free <span class="grad">Video Downloader</span>`), 31 hreflang
  links (30 + x-default → `https://qgrab.onrender.com/`), specs table
  present with the exact values (6 `.spec` rows), switcher lists all
  30 native names, homepage FAQ question appears in both the visible
  FAQ and the JSON-LD.
- ur: `<html lang="ur" dir="rtl">`, `Set-Cookie: qgrab_lang=ur` on
  `?lang=ur`, Urdu hero/specs strings render; a second request with
  only the cookie (no `?lang=`) still renders Urdu RTL — cookie
  persistence confirmed. ar also RTL; es/zh LTR with translated
  strings present.
- Platform pages: `/youtube-video-downloader?lang=hi` 200 — Hindi H1
  (YouTube वीडियो डाउनलोडर), 4 FAQ entries, specs table, Hindi
  personal-use section present, canonical unchanged, `<title>` stays
  the approved English SEO title. `/tiktok-video-downloader?lang=ur`
  shows the translated Urdu H1. English platform page regression:
  original H1, how-to heading, sections and FAQs unchanged.
- All 30 languages × (homepage + a platform page): every request 200,
  no template errors. Invalid `?lang=xx` falls back to English.
- JSON-LD: parses as valid JSON on en/ur/fa pages; every FAQPage
  entry matches a visible FAQ on the same page (5 home, 4 platform).
- API: `POST /api/info` with an invalid URL returns the Urdu
  `api_invalid` message when the ur cookie is set, English otherwise.
- SEO re-check: sitemap still emits 8 URLs, robots.txt unchanged,
  canonicals unchanged, `/sw.js` and manifest still 200, `/download`
  without parameters still returns its 400 validation response —
  download logic untouched.
- Deploy tree boot-tested standalone (200s on home, an RTL page, a
  Swahili platform page, and a legal page).

## Files changed (both trees, md5-identical)

| File | Change |
|---|---|
| `i18n.py` | NEW — all translations + helpers |
| `app.py` | i18n wiring only (lang resolution, context, cookie, localized API errors, translated views) |
| `templates/index.html` | strings → `t.*`, hreflang, switcher, specs + footer includes, JS strings injected |
| `templates/platform.html` | same treatment; specs include added |
| `templates/_specs.html` | NEW — specs table include |
| `templates/_langmenu.html` | NEW — language switcher include |
| `templates/_footer.html` | NEW — shared translated footer |
| `templates/_extras.html` | NEW — shared CSS (specs, switcher, RTL) |

Untouched: download/extraction code, Invidious fallback, cookie
support, `static/sw.js`, manifest, icons/logo pipeline, legal
templates, sitemap/robots logic.
