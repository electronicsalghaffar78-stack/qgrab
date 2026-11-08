"""Tests for the Plans header link + #plans section
(2026-11-08 release, announcement only).

Covers the RENDERED homepage:
  * the header carries a "Plans" link to #plans positioned
    AFTER the QGrab logo (the owner's placement: top header,
    beside the brand name) and inside the <header> element —
    not in the three-dot menu panel;
  * the header nav keeps a real gap (>= 8px) between the brand
    group and the controls group and wraps instead of letting
    the Plans pill and the Update App button overlap
    (2026-11-08 phone fix);
  * the #plans section is the LAST content section on the page
    (2026-11-08 phone fix: moved to the very bottom, right
    before the footer) and holds both cards with exactly the
    approved facts (Basic — Free; Premium — $10 first month
    for new users, then $20/month, "Coming Soon");
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
# Header spacing (2026-11-08 phone fix): on the owner's phone the
# Plans pill and the Update App button touched/overlapped, the
# pill half-hidden behind the button. The header nav must be a
# wrapping flex row with a real gap (>= 8px) between the brand
# group (logo + Plans pill) and the controls group, the controls
# group must carry its own gap, and the pill must never shrink.
# ------------------------------------------------------------------
nav_m = re.search(r"\.nav\{([^}]*)\}", html)
nav_css = nav_m.group(1) if nav_m else ""
gap_m = re.search(r"(?:column-)?gap:\s*(\d+)px", nav_css)
check("header nav wraps instead of overlapping",
      "flex-wrap:wrap" in nav_css, nav_css[:100])
check("header nav gap between brand and controls is >= 8px",
      bool(gap_m) and int(gap_m.group(1)) >= 8, nav_css[:100])
hnav_m = re.search(r"\.hnav\{([^}]*)\}", html)
check("header controls group (.hnav) carries its own gap",
      bool(hnav_m) and "gap:" in hnav_m.group(1))
pill_m = re.search(r"\.plans-link\{([^}]*)\}", html)
check("Plans pill can never be squeezed (flex:none)",
      bool(pill_m) and "flex:none" in pill_m.group(1))

# ------------------------------------------------------------------
# #plans section + cards
# ------------------------------------------------------------------
sec_m = re.search(r'<section id="plans"[^>]*>([\s\S]*?)</section>', html)
check("#plans section renders", bool(sec_m))
sec = sec_m.group(1) if sec_m else ""
ai_i = html.find('id="ai-tools"')
check("#plans section comes after the AI Tools section",
      bool(sec_m) and ai_i != -1 and sec_m.start() > ai_i)

# 2026-11-08 phone fix: the owner moved Plans to the very BOTTOM
# of the page — it must be the LAST <section> on the homepage,
# after the FAQ, the Script+Prompt tool and the install section,
# immediately before the footer.
sec_starts = [m.start() for m in re.finditer(r"<section", html)]
check("#plans is the last <section> on the homepage",
      bool(sec_m) and bool(sec_starts)
      and sec_m.start() == max(sec_starts),
      f"plans at {sec_m.start() if sec_m else -1}, "
      f"last section at {max(sec_starts) if sec_starts else -1}")
for anchor in ('id="script-prompt"', 'id="faq"', 'id="install"'):
    check(f"#plans comes after the {anchor} section",
          bool(sec_m) and html.find(anchor) != -1
          and sec_m.start() > html.find(anchor))
foot_i = html.find("<footer")
check("#plans sits before the footer",
      bool(sec_m) and foot_i != -1 and sec_m.start() < foot_i)

# ------------------------------------------------------------------
# Specs ("QGrab at a Glance") position — 2026-11-08 removal release:
# the owner moved the quality/specs section to sit DIRECTLY BELOW
# the Script+Prompt section and ABOVE the Supported Platforms
# section (it used to sit down by All Tools).
# ------------------------------------------------------------------
sp_i = html.find('id="script-prompt"')
specs_i = html.find('class="specs"')
supp_i = html.find('class="platforms"')
check("specs section renders on the homepage", specs_i != -1)
check("specs section sits below the Script+Prompt section",
      sp_i != -1 and specs_i != -1 and specs_i > sp_i,
      f"script-prompt at {sp_i}, specs at {specs_i}")
check("specs section sits above the Supported Platforms section",
      specs_i != -1 and supp_i != -1 and specs_i < supp_i,
      f"specs at {specs_i}, platforms grid at {supp_i}")

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
