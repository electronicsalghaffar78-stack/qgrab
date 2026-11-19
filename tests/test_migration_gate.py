"""Tests for the site-migration gate (build 2026-11-19.38).

QGrab moved to a new Render account/address
(https://qgrab-lrin.onrender.com) after Google closed the account
behind the old address. The gate ships inside _appupdatejs.html —
which every main page includes — and must satisfy three contracts:

1. The migration marker and the new address are present in the
   served homepage (the keep-warm workflow greps for the marker to
   decide whether the old service still needs its one redeploy).
2. The gate is fenced to the OLD hostname only, so the new website
   can never show the popup to its own visitors.
3. The download interception is wired (capture-phase click handler
   + the session "continue" flag).

Run:  .venv/bin/python tests/test_migration_gate.py   (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402


def _home_html():
    client = qgrab.app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def test_marker_and_new_address_on_homepage():
    html = _home_html()
    assert "qgrab-migration-38" in html
    assert "https://qgrab-lrin.onrender.com" in html


def test_gate_fenced_to_old_hostname():
    html = _home_html()
    assert "window.location.hostname !== 'qgrab.onrender.com'" in html


def test_download_interception_wired():
    html = _home_html()
    assert "qgrabMigOverlay" in html
    assert "qgrab_mig_continue" in html
    assert "/download?" in html


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
