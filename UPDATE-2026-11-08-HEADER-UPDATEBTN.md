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

## Outage + deploy (2026-11-08)
- The free instance froze silently at 08:00:57 PKT: app logs stop dead
  (Render's own /healthz checks, every ~5s, simply cease), zero bytes to
  any request, dashboard still showed "Live", no crash/error/shutdown
  line, limits untouched (36.75/750 instance hours, 289 MB / 5 GB
  bandwidth). Confirmed down from two independent paths (curl from the
  sandbox + browser fetch — both timed out at 60s with 0 bytes).
- Push: commit 12b282bc2e4099aaf201405f12011f686b6146c2 (11 paths;
  snapshot sync record #21). The deleted templates/_updatebtn.html
  could not be deleted by the push tool — removed via GitHub web UI
  afterwards (nothing referenced it; the app never loads it).
- Manual Deploy dep-dbnv6em417fc73ergk20, 08:57:46 PKT, 40.3s,
  "Deploy succeeded | Live"; new instance clean gunicorn start,
  live 08:58:27 PKT.
- Independent live verification by Archer (curl): /healthz 200
  {"ok":true} ~1.0s; /api/version → 2026-11-08.11; homepage 200,
  175,187 bytes, TTFB ~1.0s; served HTML: appUpdateBtnTop ×0,
  nav-center ×0, footer id="appUpdateBtn" ×1. ✔
