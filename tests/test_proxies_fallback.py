"""Telegram Proxies deploy-proof fallback (release 2026-11-16.21).

Regression being pinned: the round-3 list lived only in
data/proxies.json. data/ is git-ignored runtime state and the
production Dockerfile created an empty /app/data without copying
data/ into the image, so the LIVE /telegram-proxies page served
0 proxies ("list is being refreshed") even though the snapshot
existed locally and on GitHub.

The fix ships exact copies of the snapshot with the code —
bundled_data/proxies.json (plus a Dockerfile COPY for it) and
static/bundled/proxies.json (static/ is always copied) — and
_load_proxy_list() falls back to them whenever the runtime file
is missing or yields nothing valid.

Run:  .venv/bin/python tests/test_proxies_fallback.py
"""
import html as html_lib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


def load_json(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


# --- bundled copies exist, are complete and cannot drift apart --------------
runtime = load_json(os.path.join("data", "proxies.json"))
bundled = load_json(os.path.join("bundled_data", "proxies.json"))
static_copy = load_json(os.path.join("static", "bundled",
                                     "proxies.json"))
check("bundled copy has the full snapshot",
      bundled == runtime and len(bundled["proxies"]) == 100,
      str(len(bundled.get("proxies") or [])))
check("static copy identical to bundled copy", static_copy == bundled)
check("bundled updated date kept", bundled.get("updated") == "2026-11-16",
      str(bundled.get("updated")))
check("source note ships with the bundled copy",
      os.path.exists(os.path.join(ROOT, "bundled_data",
                                  "PROXIES-SOURCE-NOTE.md")))

# --- the Dockerfile must carry bundled_data/ into the image -----------------
with open(os.path.join(ROOT, "deploy", "Dockerfile"),
          encoding="utf-8") as fh:
    dockerfile = fh.read()
check("Dockerfile copies bundled_data into the image",
      "COPY bundled_data ./bundled_data" in dockerfile)

# --- loader: normal order serves the snapshot --------------------------------
proxies, updated = A._load_proxy_list()
check("loader returns the snapshot", len(proxies) == 100,
      str(len(proxies)))
check("loader returns the updated date", updated == "2026-11-16",
      updated)

# --- loader: runtime file missing -> bundled fallback -------------------------
real_candidates = A._PROXY_LIST_FILES
missing = os.path.join(ROOT, "data", "definitely-not-here.json")
try:
    A._PROXY_LIST_FILES = (missing,) + tuple(real_candidates[1:])
    proxies, updated = A._load_proxy_list()
    check("fallback serves bundled list when runtime file missing",
          len(proxies) == 100 and updated == "2026-11-16",
          f"{len(proxies)} / {updated}")

    # --- loader: every candidate missing -> honest empty ---------------------
    A._PROXY_LIST_FILES = (missing,)
    proxies, updated = A._load_proxy_list()
    check("all candidates missing -> empty, no invention",
          proxies == [] and updated == "")

    # --- route: with only bundled candidates the page renders all 100 --------
    A._PROXY_LIST_FILES = tuple(real_candidates[1:])
    client = A.app.test_client()
    r = client.get("/telegram-proxies")
    page = html_lib.unescape(r.get_data(as_text=True))
    check("route 200 on bundled fallback", r.status_code == 200,
          str(r.status_code))
    check("route renders all 100 proxies from the fallback",
          page.count("t.me/proxy?server=") == 100,
          str(page.count("t.me/proxy?server=")))
    check("route shows the snapshot's updated date",
          "2026-11-16" in page)
finally:
    A._PROXY_LIST_FILES = real_candidates

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
