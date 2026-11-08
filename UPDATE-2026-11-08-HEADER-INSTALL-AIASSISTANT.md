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
