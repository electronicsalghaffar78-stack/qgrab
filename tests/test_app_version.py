"""Tests for GET /api/version — the release stamp behind the
installed PWA's "Update App" button.

The button fetches this endpoint with cache:"no-store" and
compares the answer with the version stored in the visitor's
browser; a cacheable or drifting answer would make the whole
flow lie, so the contract pinned here is: the body is exactly
{"version": APP_VERSION} and the response carries
Cache-Control: no-store.

Run:  .venv/bin/python tests/test_app_version.py   (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402


def test_version_endpoint_contract():
    client = qgrab.app.test_client()
    resp = client.get("/api/version")
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"version": qgrab.APP_VERSION}
    cache = resp.headers.get("Cache-Control") or ""
    assert "no-store" in cache, cache


def test_app_version_value():
    # The release this feature ships with. Bump APP_VERSION (and
    # this expectation) on every future release — see the
    # APP_VERSION comment in app.py.
    assert qgrab.APP_VERSION == "2026-11-08.3"


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
