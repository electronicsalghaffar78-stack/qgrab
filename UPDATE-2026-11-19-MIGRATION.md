# QGrab 2026-11-19.38 — Old-Site Migration Gate

**Why:** QGrab moved to a new Render account and address
(https://qgrab-lrin.onrender.com) after Google disabled the account
behind the old address (qgrab.onrender.com, appeal rejected). The old
site still runs build .28 and its installed apps can never receive
updates the normal way — the old Render account can no longer be
signed in to, and the service does not auto-deploy.

**What this build does (owner's order, 2026-11-19):** on the OLD
address only, the first download attempt in a session (video, photo,
extension — any download) is stopped and an update popup is shown
first. The popup's button takes the visitor to the same page on the
new website, where they can install the new app and keep receiving
updates. A small "continue here this time" link lets that one
download proceed. A slim banner at the top of every page announces
the move. The gate is fenced by hostname
(`window.location.hostname !== 'qgrab.onrender.com'` → inert), so
the new website never shows it.

**How it reaches the old site:** the code ships in the shared repo.
The new service is deployed manually as usual. The old service is
redeployed once through its existing auto-heal path: the keep-warm
GitHub Actions workflow checks the old homepage for the
`qgrab-migration-38` marker every 10 minutes and, while the marker
is missing, posts the old service's Render deploy hook (the
`RENDER_DEPLOY_HOOK_URL` repo secret). Once the marker is served,
the step never fires again.

**Changes:**
- `templates/_appupdatejs.html` — migration gate script appended
  (marker `qgrab-migration-38`, banner + popup + capture-phase
  download interception; navigation links are never intercepted).
- `app.py` — `APP_VERSION = "2026-11-19.38"`.
- `static/sw.js` — shell cache `qgrab-shell-v13`.
- `templates/_assistant.html` — assistant version label .38.
- `tests/test_migration_gate.py` — new: marker + new address on the
  homepage, hostname fence, interception wiring.
- `tests/test_app_version.py`, `tests/test_audit_regressions.py` —
  version/cache expectations bumped.

**Tests:** full suite green — every `tests/test_*.py` and
`tests/test_*.js` file passes, including the new migration tests
(3/3) and the audit regressions.
