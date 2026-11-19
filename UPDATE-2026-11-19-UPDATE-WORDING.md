# QGrab 2026-11-19.39 — Update Gate Wording (owner's correction)

**Owner's order (2026-11-19 ~14:09 PKT):** the old-site gate from
build .38 worked, but its visible wording ("QGrab has moved",
"new website") is forbidden — nobody must be able to tell an
address changed. The gate must read as a plain, simple app update.

**New visible wording (the ONLY text visitors see):**
- Banner: "**QGrab Update:** a new version is available — voice
  search, new tools and more." Button: "Update Now".
- Popup title: "QGrab Update"
- Popup body: "A new version of QGrab is ready. This update brings
  voice search, new tools and a smoother experience. Tap Update
  Now to get the new version — it only takes a few seconds, and
  you can continue your download right after."
- Buttons: "Update Now" / "Later".

Behaviour is unchanged from .38 (banner + first-download popup,
old-host fenced). The internal marker changed to
`qgrab-migration-39` so the keep-warm workflow's marker-gated step
fires one more redeploy of the old service; the workflow's grep
string was updated to match. A regression test now asserts the
served homepage contains no "moved"/"new website" phrasing.

**Changes:** `templates/_appupdatejs.html` (wording + marker),
`app.py` (APP_VERSION 2026-11-19.39), `static/sw.js`
(qgrab-shell-v14), `templates/_assistant.html` (label),
`tests/test_migration_gate.py` (marker + wording guard),
`tests/test_app_version.py`, `tests/test_audit_regressions.py`.
