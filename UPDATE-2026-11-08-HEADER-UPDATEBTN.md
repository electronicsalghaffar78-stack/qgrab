# Release 2026-11-08.11 — Update App removed from the header (owner's order)

**Owner's order (2026-11-08 ~08:53 PKT):** the "Update App" written at the
top header must be removed from there; it stays only at the bottom of the
page (the footer copy, which already existed, is untouched).

## Changes
- Removed the `.nav-center` slot + `_updatebtn.html` include from all three
  full headers: `templates/index.html`, `templates/platform.html`,
  `templates/scriptprompt.html`. Deleted `templates/_updatebtn.html`
  (the header twin button `appUpdateBtnTop`).
- `templates/_appupdatejs.html`: removed all `appUpdateBtnTop` logic
  (standalone unhide + click wiring). The footer button flow is unchanged.
- `templates/_extras.html`: header-layout comment rewritten; `.nav-center`
  CSS and its phone media rule removed. `.nav` already used
  `justify-content:space-between`, so the header is now simply
  brand left / controls right.
- `templates/_installbtn.html`: stale comment updated.
- `APP_VERSION` → `2026-11-08.11` (app.py, tests/test_app_version.py,
  Assistant panel stamp in templates/_assistant.html).

## Tests
- tests/test_plans.py header block rewritten to the new layout: two header
  groups, NO `nav-center`, NO `appUpdateBtnTop` anywhere, the only Update
  App button asserted inside the footer; per-page loop updated likewise.
- Full master suites: 20/20 Python + 4/4 Node PASS.

## Note
Prepared while the live service was down/hanging (Render diagnosis in
parallel). The redeploy of this release doubles as the service restart.
Supersedes the 2026-11-08.7 center-slot placement.
