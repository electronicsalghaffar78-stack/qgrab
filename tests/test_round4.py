"""Round 4 (2026-11-16.24): owner-verdict fixes.

  * ROOT CAUSE of the broken live layout: the Round-2 comment
    in templates/_extras.html was never closed, so the whole
    Round-2 CSS block (header lockup, hero chips, trust chips,
    usage counters, history list) was commented out on every
    page. Guarded here by a comment-balance check.
  * Header lockup: big "QGrab" + small tagline beneath it
    (.brand-text column + .tagline rules must be LIVE css).
  * Hero chips: pills with real brand icons, flex-wrap + gap.
  * Subscribe forms: email input wide, Subscribe button
    compact — .sub-row .btn{width:auto} must outrank the
    pages' global mobile .btn{width:100%} rule.
  * Tools Hub: nav "Tools" opens #tools-hub, a chooser with
    EVERY tool in the app (6 AI generators, 4 Video Toolkit
    tools, Script + Prompt) — cross-checked against the tool
    grids that actually exist on the page.
  * Platforms grid: Pinterest carries its own P icon inside
    its own link; VK is its own pill (they were garbled).

Run:  .venv/bin/python tests/test_round4.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-r4-")
os.environ.setdefault("QGRAB_DATA_DIR", _TMPDIR)

import app as qgrab  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        print("FAIL", name, detail)
        FAILURES.append(name)


client = qgrab.app.test_client()
home = client.get("/").get_data(as_text=True)
plat = client.get("/youtube-video-downloader").get_data(as_text=True)
prox = client.get("/telegram-proxies").get_data(as_text=True)
sp = client.get("/video-to-script-prompt").get_data(as_text=True)

TPL = os.path.join(os.path.dirname(__file__), "..", "templates")

# --- the root-cause guard: every CSS comment closed ----------
extras_src = open(os.path.join(TPL, "_extras.html")).read()
check("extras comment balance",
      extras_src.count("/*") == extras_src.count("*/"),
      f"{extras_src.count('/*')} opens vs {extras_src.count('*/')} closes")
for fname in sorted(os.listdir(TPL)):
    if fname.endswith(".html"):
        s = open(os.path.join(TPL, fname)).read()
        check(f"comment balance {fname}", s.count("/*") == s.count("*/"))

# --- revived Round-2 CSS is present in the rendered page -----
check("pchip-row flex css live",
      ".pchip-row{display:flex;flex-wrap:wrap;gap:6px" in home)
check("tagline css live", ".tagline{display:block" in home)
check("brand-text column css live",
      ".logo .brand-text{display:flex;flex-direction:column" in home)
# (was "usage-row css live" until release .26 removed the
# usage card and its CSS with it — same guard, surviving rule)
check("tchip-row css live", ".tchip-row{display:flex" in home)
check("wrap centered", ".wrap{max-width:860px;margin:0 auto" in home)

# --- subscribe proportions ------------------------------------
# (Removed in release .27: the owner ordered ALL subscribe UI
# off the site, so the .sub-row proportion rules were deleted
# with the footer form. The absence contract — no subscribe
# form, popup or CSS on any rendered page — is pinned in
# test_round7.py.)

# --- footer grid hardening ------------------------------------
check("foot-grid shrink css", ".foot-grid>*{min-width:0}" in home)

# --- Tools Hub --------------------------------------------------
check("hub section exists", 'id="tools-hub"' in home)
cards = re.findall(r'class="hub-card"', home)
check("hub has 11 cards", len(cards) == 11, f"got {len(cards)}")

# every AI generator that exists in the AI grid has a hub card
grid_tools = set(re.findall(r'class="ai-tool[^"]*" data-tool="([^"]+)"', home))
hub_tools = set(re.findall(r'data-ai-tool="([^"]+)"', home))
check("hub covers all AI tools", grid_tools == hub_tools and len(grid_tools) == 6,
      f"grid={sorted(grid_tools)} hub={sorted(hub_tools)}")
check("hub toolkit cards", home.count('class="hub-card" href="#video-toolkit"') == 4)
check("hub script+prompt card", 'class="hub-card" href="#script-prompt"' in home)

# nav Tools destination on every page — SUPERSEDED by
# release .26 (2026-11-16): the nav item is the Tools
# dropdown now (one entry per tool, grouped like the hub;
# the full contract lives in test_round6.py). The footer
# link still lands on the hub.
check("home nav tools -> dropdown",
      'id="toolsMenuBtn"' in home and 'id="toolsMenuPanel"' in home)
for name, page in [("platform", plat), ("proxies", prox), ("scriptprompt", sp)]:
    check(f"{name} nav tools -> dropdown", 'id="toolsMenuPanel"' in page)
check("footer tools -> hub", 'href="/#tools-hub"' in home)

# hub entrance animation wiring
check("animjs pops hub cards", ".hub-grid .hub-card" in home
      and "hub-pop" in home)

# --- hero chips carry brand icons ------------------------------
m = re.search(r'class="pchip-row".*?</div>', home, re.S)
chip_row = m.group(0) if m else ""
check("hero chips all have icons",
      chip_row.count('<svg class="pchip-ic"') == 13,
      f"got {chip_row.count('<svg class=\"pchip-ic\"')}")
check("hero chips are pills (css)", ".pchip{display:inline-flex" in home)

# --- platforms grid: Pinterest / VK un-garbled ------------------
m = re.search(r'href="/pinterest-video-downloader"><svg.*?</a>', home, re.S)
check("pinterest pill has own P icon",
      bool(m) and "#E60023" in m.group(0) and "Pinterest</a>" in m.group(0))
check("vk is its own pill", bool(re.search(
    r'<div class="plat"><svg[^>]*>.*?VK</div>', home, re.S)))
m = re.search(r'href="/reddit-video-downloader"><svg.*?</a>', home, re.S)
check("reddit pill has Snoo glyph",
      bool(m) and "<ellipse" in m.group(0) and "#FF4500" in m.group(0))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:", FAILURES)
    sys.exit(1)
print("ALL ROUND-4 CHECKS PASSED")
