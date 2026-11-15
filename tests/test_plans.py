"""Plans are GONE — the site is fully free (round 3,
2026-11-16, owner's order cancelling paid Premium:
"har koi free me use kare, kamai ads se hogi").

This file used to pin the Plans header link and the #plans
section (2026-11-08 announcement, then the round-1 manual
JazzCash/Easypaisa payment flow). The owner's round-3 order
supersedes all of that. What it pins now, on the RENDERED
homepage and the other main pages:

  * no #plans section, no ⭐ Plans header link, no Premium
    wording anywhere in the rendered pages;
  * the hero pill reads "100% Free · No account needed";
  * every /api/premium/* route answers 404;
  * _plans.html no longer exists in templates/.

Run:  .venv/bin/python tests/test_plans.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as A  # noqa: E402

client = A.app.test_client()
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


for path in ("/", "/youtube-video-downloader", "/video-to-script-prompt"):
    html = client.get(path).get_data(as_text=True)
    check(f"{path} has no plans section", 'id="plans"' not in html)
    check(f"{path} has no Plans header link", "⭐ Plans" not in html)
    check(f"{path} has no Premium marketing",
          "Premium active" not in html and "Premium costs" not in html
          and "⭐ Premium" not in html)

home = client.get("/").get_data(as_text=True)
check("hero pill is the free pill",
      "100% Free · No account needed" in home)
check("no payment methods in UI",
      "JazzCash" not in home and "Easypaisa" not in home)

for method, path in (("GET", "/api/premium/config"),
                     ("GET", "/api/premium/status"),
                     ("POST", "/api/premium/claim-welcome"),
                     ("POST", "/api/premium/request"),
                     ("GET", "/api/premium/inbox"),
                     ("POST", "/api/premium/approve"),
                     ("POST", "/api/premium/reject")):
    r = client.open(path, method=method, json={})
    check(f"{method} {path} is 404", r.status_code == 404,
          str(r.status_code))

tpl = os.path.join(os.path.dirname(__file__), "..", "templates",
                   "_plans.html")
check("_plans.html deleted", not os.path.exists(tpl))

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
