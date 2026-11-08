# QGrab Update — 2026-11-08 — Homepage Removal Release (APP_VERSION 2026-11-08.5)

Owner's phone test, third round of the night: the homepage had
become too long. Three changes, all in this one release, shipped
on top of 2026-11-08.4.

## 1. Two homepage sections REMOVED (templates/index.html)

- **"Popular Downloaders"** — heading + "Jump straight to the
  downloader you need…" sub + the four platform cards (YouTube /
  TikTok / Instagram / Facebook Video Downloader, "Open the …
  Downloader →" links, card ids `youtube-downloader`,
  `tiktok-downloader`, `instagram-downloader`,
  `facebook-downloader`).
- **"Download Videos From Every Platform"** (the guide section)
  — heading + "Guides for the platforms people ask about most…"
  sub + the four guide cards ("Download YouTube Videos",
  "TikTok Video Downloader — No Watermark", …, "Use the …
  video downloader →" links).

Both were plain `<section>` blocks inline in index.html (not
partials); 54 lines removed. Section order is otherwise
unchanged and `#plans` remains the last section before the
footer.

**Deliberately kept:**
- The **All Tools** section (`_tools.html`, `id="tools"`) —
  the owner explicitly wants it to stay.
- The **platform landing pages** themselves
  (/youtube-video-downloader, /tiktok-video-downloader,
  /instagram-video-downloader, /facebook-video-downloader)
  still serve; the footer still links to them.
- The hero H1 "Download Videos From Every Platform Easy &
  Fast" — it contains the removed guide heading as a substring
  but is a different element and stays.

**Dangling-reference findings:**
- No nav, header, footer, JS, assistant goto, or test pointed
  at the removed sections or their card ids — nothing else
  needed cleanup. (Footer links target the platform PAGES,
  which stay.)
- The translation strings for the removed sections
  (`popular_*`, `card_*`, `guide_*` in i18n.py, all 30
  languages) are now unused. They were LEFT in place on
  purpose: deleting them from 30 dicts is extra churn for
  zero user-visible gain, and leaving them keeps this removal
  trivially reversible.
- `QGrab-Preview.html` (a static mockup in the repo root, NOT
  served by the app) contains nav anchors to the removed card
  ids. It is not part of the live site; left untouched,
  recorded here for completeness.

## 2. Specs section MOVED (templates/index.html)

The "QGrab at a Glance" specs section (`_specs.html` — quality
rows + pricing row; identified by its content: Quality
"480p · 720p · 1080p HD" and the pricing row — the only such
table on the page) moved from below All Tools to **directly
below the Script+Prompt section** (`#script-prompt`) and
**above the Supported Platforms section**. Only the
`{% include "_specs.html" %}` line moved; the partial's
content, classes and styling are byte-identical.

## 3. Specs pricing row CHANGED (i18n.py, all 30 languages)

The pricing row no longer advertises "$0":

- `spec_pricing` (label): "Pricing" → **"Premium
  subscription"**, translated in all 30 languages (e.g. ur
  "پریمیم سبسکرپشن", hi "प्रीमियम सदस्यता", ar "الاشتراك
  المميز", fa "اشتراک پریمیوم", zh "高级订阅",
  sw "Usajili wa Premium" — full set in i18n.py).
- `spec_pricing_val` (value): "$0 — Free" (and its localized
  forms) → **"$20/month"**, the identical literal in every
  language, so every rendering of the row shows $20/month
  and no "$0" remains anywhere on the homepage.

No other price anywhere changed — the Plans section facts
($10 first month for new users, then $20/month, trial, etc.)
are untouched.

## 4. Search Videos heading clarified (templates/index.html)

The section heading did not explain itself to new visitors:
"Search Videos" → **"Search Videos — Watch & Download"**.
The sub-line under it is unchanged.

Implementation note (differs from the original instruction's
assumption): this heading does **not** live in i18n. The whole
Search Videos section (heading, sub-line, placeholder, button)
was built with hardcoded English strings in index.html — it
was never translated — so every language already rendered the
English words "Search Videos". There were no translated
headings to preserve; the new heading is therefore the same
English text in all 30 languages, which matches the owner's
choice that the action phrase stays English and
self-explanatory. If the section is ever i18n-ized later, the
heading should become a key at that point.

## Tests

- NEW `tests/test_remove_sections.py` (29 checks): the new
  Search Videos heading pinned (old bare heading absent,
  sub-line unchanged); both
  headings/subs/card-ids/link texts absent from the rendered
  homepage (the TikTok guide card is asserted via its unique
  paragraph, because its title string doubles as the footer's
  TikTok page link text, which stays); hero H1 intact; All
  Tools, Plans and specs still present; all four platform
  pages still serve 200; specs pricing row renders
  "Premium subscription" / "$20/month", no "$0" on the
  homepage, and all 30 languages carry the new value + their
  own translated label.
- `tests/test_plans.py` extended (+3 checks): specs section
  renders and sits after `#script-prompt` and before the
  Supported Platforms grid.
- `tests/test_app_version.py`: expected version → 2026-11-08.5.
- No test had pinned the removed sections' presence, and no
  test pinned "$0" — nothing had to be weakened or deleted.

Suites: master 18/18 Python + 4/4 Node pass. Mirror identical
except the known pre-existing `test_install_button.py`
manifest failure (generated PNG icons absent from the repo
snapshot — unrelated).

## Release discipline

APP_VERSION bumped 2026-11-08.4 → **2026-11-08.5** (the
homepage is cached content; the Update App button compares
against this stamp).
