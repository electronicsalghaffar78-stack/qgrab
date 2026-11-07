"""Tests for the Plans header link + #plans section
(2026-11-08 release, announcement only).

Covers the RENDERED homepage:
  * the header carries a "Plans" link to #plans positioned
    AFTER the QGrab logo (the owner's placement: top header,
    beside the brand name) and inside the <header> element —
    not in the three-dot menu panel;
  * the #plans section sits after the AI Tools section and
    holds both cards with exactly the approved facts (Basic —
    Free; Premium — $10 first month for new users, then
    $20/month, "Coming Soon");
  * announcement-only scope: the section contains NO form
    elements (no <form>, <input>, <select> or <textarea>) and
    both plan buttons are disabled — there is no checkout,
    card field or buy flow yet.

Run:  .venv/bin/python tests/test_plans.py
"""
import os
import re
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


html = client.get("/").get_data(as_text=True)

# ------------------------------------------------------------------
# Header Plans link
# ------------------------------------------------------------------
hdr_m = re.search(r"<header>([\s\S]*?)</header>", html)
check("header element renders", bool(hdr_m))
hdr = hdr_m.group(1) if hdr_m else ""
logo_i = hdr.find('class="logo"')
plans_m = re.search(r'<a[^>]*href="#plans"[^>]*>([\s\S]*?)</a>', hdr)
check("header has a Plans link to #plans", bool(plans_m))
check("Plans link label reads 'Plans'",
      bool(plans_m) and "Plans" in plans_m.group(1))
check("Plans link sits after the logo in the header",
      bool(plans_m) and logo_i != -1 and plans_m.start() > logo_i,
      f"logo at {logo_i}, plans at {plans_m.start() if plans_m else -1}")
_panel_i = hdr.find('id="hmenuPanel"')
check("Plans link is not inside the three-dot menu panel",
      bool(plans_m) and (_panel_i == -1 or plans_m.start() < _panel_i))
check("Plans link carries the plans-link pill class",
      bool(plans_m) and 'class="plans-link"' in plans_m.group(0))

# ------------------------------------------------------------------
# #plans section + cards
# ------------------------------------------------------------------
sec_m = re.search(r'<section id="plans"[^>]*>([\s\S]*?)</section>', html)
check("#plans section renders", bool(sec_m))
sec = sec_m.group(1) if sec_m else ""
ai_i = html.find('id="ai-tools"')
check("#plans section comes after the AI Tools section",
      bool(sec_m) and ai_i != -1 and sec_m.start() > ai_i)

for frag in ("Basic", "Free", "All tools included",
             "AI features limited to 10 uses per day",
             "Free forever", "Current plan",
             "Premium", "$10", "first month for new users",
             "$20/month", "Everything unlimited",
             "3-day free trial included", "Cancel anytime",
             "Full refund if you cancel", "Coming Soon"):
    check(f"#plans shows {frag!r}", frag in sec)

# ------------------------------------------------------------------
# Announcement-only: no forms, buttons disabled
# ------------------------------------------------------------------
low = sec.lower()
for tag in ("<form", "<input", "<select", "<textarea"):
    check(f"#plans contains no {tag}> element", tag not in low)
check("#plans has no buy/checkout link", "href=" not in low)
check("both plan buttons are disabled",
      sec.count("disabled") >= 2,
      f"found {sec.count('disabled')}")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL PLANS TESTS PASS")
