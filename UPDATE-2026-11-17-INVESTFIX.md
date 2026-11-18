# QGrab build 2026-11-17.29 — INVESTFIX (local build, NOT pushed, NOT deployed)

Safe, reversible code items from the investment-readiness audit
(2026-11-17: A=3, B=7, C=2). Only copy/docs/honesty fixes — no
behaviour change to downloads, AI or any route. Ads were NOT
started (owner's standing order). NOT in this build, by design:
durable data store (A-2), Render paid plan (A-1), Script+Prompt
fetch speed (B-2).

## 1. (B-1) Ad placeholder + false FAQ ads claim — removed/corrected

- `templates/index.html`: the visible in-content
  "AD — Advertisement space" placeholder box is removed completely.
- `i18n.py`: the FAQ answer "Is QGrab free to use?" no longer claims
  "The site is supported by the ads you see on the page" — in **all
  30 languages** it now says QGrab shows no ads at this time and
  that any future ads will be clearly marked as ads. (This key also
  feeds the platform pages' FAQ, so they are fixed too.)

## 2. (C-1) Specs table completed to all 13 platforms

- `i18n.py` `spec_platforms_val` (all 30 languages):
  "YouTube · TikTok · Instagram · Facebook · X · Pinterest ·
  SoundCloud · Twitch · Telegram · VK · Vimeo · Dailymotion ·
  Reddit (currently unavailable)" — was only 7 platforms.

## 3. (B-5) Stale docs updated

- `README.md`: rewritten from the v1-era text (3 routes / "not
  deployed" / APK plan) to the current reality — live site, 52
  routes, full feature list, Ant Ling (Ling-3.1-flash + Ming ASR)
  with Gemini fallback, unlimited free, 13 platforms with the
  Reddit caveat, deployment via GitHub + Render Manual Deploy, and
  an honest known-limitations list.
- `FEATURES-REPORT.md`: header no longer says "NOT pushed, NOT
  deployed"; it is marked as a historical 2026-11-03 report and a
  "Current status — 2026-11-17 (build .29)" section was added at
  the top (live state, AI providers, Reddit status, open items).

## 4. (A-3, honesty only) Reddit marked as currently unavailable

No page or route was deleted. Everywhere Reddit was presented as a
working platform it now carries the honest marking, in the site's
existing "still being improved" note style:

- Homepage: the works-note now reads "Reddit downloads are
  currently unavailable — Reddit restricts automated access from
  our servers, so links will fail for now. Reddit support is still
  being improved." The platforms grid entry gained the same `*`
  marker the hero chip already had.
- Reddit platform page: tagline carries a "NOTE: currently
  unavailable" line; the explainer section is retitled "Currently
  Unavailable — A Reddit-Side Restriction" and states plainly that
  downloads are unavailable because Reddit restricts automated
  access from the server, and will be switched back on if Reddit
  allows access again.
- Assistant knowledge base: still lists Reddit outside the
  "Downloads work from" list, now adding that downloads from
  Reddit are currently unavailable and its links will fail for now.
- Specs table: "Reddit (currently unavailable)" (see item 2).

## Version

- `APP_VERSION` = **2026-11-17.29** in both `app.py` copies;
  Assistant label bumped in both `templates/_assistant.html`
  copies; `tests/test_app_version.py` expectation updated.
- All changes applied identically to `~/workspace/qgrab-repo` and
  `~/workspace/downloader-site` (verified with `diff`).

## Tests

Full suite run locally on this build (venv Python + node):

- **41/41 test files pass** (35 Python `tests/test_*.py` + 6 JS
  `tests/test_*.js`), every file exit 0.
- **1,032 PASS-marked check lines, 0 failed checks.** (The only
  "FAIL" strings in the raw log are `CERTIFICATE_VERIFY_FAILED`
  inside yt-dlp error output that passing fallback tests trigger
  on purpose.)
- Render sanity via the Flask test client in BOTH trees: homepage
  has no ad placeholder, carries the Reddit-unavailable note, the
  completed specs list and the corrected FAQ; the Reddit page
  carries the unavailable marking; `/api/version` returns
  `2026-11-17.29`.

## Status

LOCAL ONLY — not pushed to GitHub, not deployed. Live site remains
on 2026-11-17.28 until the owner approves the push (approval-card
warning first, as always) + Render Manual Deploy.
