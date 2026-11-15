# Release 2026-11-08.12 — header Install App removed; "AI Assistant" rename

**Owner's orders (2026-11-08 ~09:03–09:06 PKT, with screenshot):**
(1) delete the "Install App" button from the top header entirely;
the day/night toggle and the three-dot menu stay together in the
RIGHT corner. (2) The floating robot button's label "Assistant"
becomes "AI Assistant".

## Changes
- Removed the `_installbtn.html` include from all three headers
  (index, platform, scriptprompt) and deleted the partial. The
  header is now: brand (logo + QGrab + ⭐ Plans) LEFT, and the
  `.nav-right` cluster (theme toggle + three-dot menu) RIGHT —
  that cluster already existed; with the Install button gone the
  header sits on one clean row.
- Retired the install-guide bottom sheet with it: the header
  button was the ONLY element that could open the sheet, so
  `_installjs.html` (prompt capture + sheet wiring) and the
  sheet markup/CSS are removed too — no orphaned dead code.
  Deleted: templates/_installbtn.html, templates/_installjs.html,
  tests/test_install_sheet_js.js; install CSS block removed from
  templates/_extras.html; stale comments updated.
- Install is NOT gone from the site: the homepage #install
  section keeps its own button (now the page's only
  id="installBtn"; the homepage's inline prompt script is
  unchanged) plus the always-visible manual steps, and the
  footer keeps its "Install" link to that section. The PWA
  manifest contract is untouched.
- tests/test_install_button.py rewritten to the new contract:
  headers carry no install button/sheet on any page; homepage
  carries exactly one installBtn inside #install; platform/tool
  pages carry none; retired partials absent; manifest checks
  preserved verbatim. tests/test_plans.py header check updated.
- FAB label: templates/_assistant.html "Assistant" → "AI
  Assistant" (tests/test_assistant.py marker updated). The
  panel title/stamp stay "QGrab Assistant · v…".

## Tests
Full master suites after both changes: 20/20 Python PASS,
3/3 Node PASS (the retired sheet JS suite removed by design).
APP_VERSION → 2026-11-08.12.

## Deploy (2026-11-08)
- Push: commit e32571f492283315b487c46b771a29ce31c481c8 (12 paths;
  snapshot sync record #22). The 3 deleted files (templates/
  _installbtn.html, templates/_installjs.html, tests/
  test_install_sheet_js.js) were removed via GitHub web UI
  afterwards — the push tool cannot delete.
- Manual Deploy dep-dbnvbnrl550s738aevtg (09:09:03 PKT, 34s) →
  live 09:09:37 PKT, clean gunicorn start.
- Archer's independent live verification (curl): /api/version →
  2026-11-08.12; homepage 200, 168,590 bytes; header slice: no
  installBtn, no install-btn class, theme toggle + hmenuBtn +
  nav-right present; page has exactly ONE id="installBtn" (the
  #install section), no installBackdrop; ">AI Assistant<"
  present; footer appUpdateBtn present, appUpdateBtnTop absent. ✔
- **SECOND silent freeze, same day (~10:53 PKT):** the instance
  froze again ~1.5h after the 09:09 redeploy — own curl checks
  timed out 30s/30s/45s with 0 bytes on /healthz, /api/version
  and homepage. Fixed by a second redeploy
  dep-dbo0u295efls73cj8g80 (10:56:25 PKT, 31.7s, commit
  a805525 — the .12 cleanup commit, same code), live 10:56:57.
  Archer re-verified: /healthz 200 ~0.9s, /api/version .12,
  homepage 200 ~0.8s. Support inbox re-checked after the
  restart: count 0, no new messages. Free-instance freezes
  are recurring; only a redeploy restarts the instance.
