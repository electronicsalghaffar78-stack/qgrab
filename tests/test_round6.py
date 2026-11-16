"""Round 6 (2026-11-16.26): the nav "Tools" dropdown.

The owner's order: the top nav's "Tools" item (right after
Home) must be a DROPDOWN MENU listing ALL of QGrab's tools,
grouped like the Tools Hub, so a visitor picks one tool at a
time from the nav itself — and picking a tool OPENS it
directly (his example: click "AI Title Generator" in the
dropdown and the AI Title Generator opens, pre-selected).

Contract pinned here:
  * every page with the shared nav renders the dropdown
    (toggle button + grouped panel, starting closed);
  * the panel lists all 12 tools in hub order — 6 AI
    generators, 4 Video Toolkit tools, Video to Script and
    AI Video Prompts listed separately — plus an "All tools"
    entry that keeps the old #tools-hub destination;
  * every entry's href carries the activation the homepage
    consumes (/?tool=…#ai-tools, /?toolkit=…#video-toolkit,
    /?sp=…#script-prompt) and its data-* key matches the
    control it activates (the AI-grid / toolkit buttons);
  * the old plain nav Tools link is gone everywhere;
  * the on-page Tools Hub itself is untouched (11 cards);
  * the activation JS + dropdown CSS ship on the pages.

Same round, the owner's precise spec + two more orders:
  * the toggle's down-arrow sits on the RIGHT of the word
    "Tools"; on desktop HOVERING opens the list (fine-pointer
    mouseenter wiring ships), tapping/clicking toggles it;
  * the visible "Today's free usage" card is REMOVED from
    the homepage — while the invisible server-side counting
    (/api/event, the quota counters, /api/stats) keeps
    working exactly as before;
  * RESPONSIVE NAV: on phone widths (<= 820px) the header
    menu collapses behind a Menu (hamburger) button and the
    nav becomes a stacked panel (burger + panel markup and
    the breakpoint CSS ship on every shared-nav page);
    desktop keeps the full row, burger hidden.

Run:  .venv/bin/python tests/test_round6.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-r6-")
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

AI_ITEMS = [
    ("titles", "AI Title Generator"),
    ("tags", "AI Tags Generator"),
    ("hashtags", "AI Hashtag Generator"),
    ("channel_names", "AI Channel Name Generator"),
    ("keywords", "Keyword Suggestions"),
    ("thumbnail_ideas", "AI Thumbnail Idea Generator"),
]
TK_ITEMS = [
    ("details", "Video Details"),
    ("thumbnail", "Thumbnail Downloader"),
    ("hashtags", "Hashtag Extractor"),
    ("tags", "Video Tags Extractor"),
]
SP_ITEMS = [
    ("script", "Video to Script"),
    ("prompts", "AI Video Prompts"),
]
ALL_NAMES = [n for _, n in AI_ITEMS + TK_ITEMS + SP_ITEMS]

PAGES = ("/", "/youtube-video-downloader", "/telegram-proxies",
         "/video-to-script-prompt", "/download-history")

for path in PAGES:
    page = client.get(path).get_data(as_text=True)
    check(f"dropdown toggle [{path}]",
          'id="toolsMenuBtn"' in page and 'aria-expanded="false"' in page)
    check(f"dropdown panel closed at render [{path}]",
          'id="toolsMenuPanel" role="menu" hidden' in page)
    check(f"dropdown groups in hub order [{path}]",
          re.findall(r'tmenu-sec">([^<]+)', page)
          == ["AI Tools", "Video Toolkit", "Script + Prompt"],
          str(re.findall(r'tmenu-sec">([^<]+)', page)))
    check(f"dropdown lists all 12 tools in order [{path}]",
          re.findall(r'tmenu-item"[^>]*>([^<]+)</a>', page) == ALL_NAMES,
          str(re.findall(r'tmenu-item"[^>]*>([^<]+)</a>', page)))
    check(f"dropdown all-tools entry [{path}]",
          'class="tmenu-all"' in page and 'href="/#tools-hub"' in page)
    check(f"old plain nav Tools link gone [{path}]",
          'class="nav-link" href="/#tools-hub">Tools</a>' not in page
          and "js-tools" not in page)
    check(f"dropdown CSS + toggle JS shipped [{path}]",
          ".tmenu-panel{" in page and "qgrabCloseToolsMenu" in page)
    check(f"mobile Menu button + panel nav [{path}]",
          'id="navBurger"' in page and 'id="mainNav"' in page
          and 'aria-controls="mainNav"' in page)
    check(f"responsive nav CSS shipped [{path}]",
          ".nav-burger{display:none" in page
          and "@media (max-width:820px)" in page
          and ".hnav.nav-open{" in page)

home = client.get("/").get_data(as_text=True)

# --- every entry's href + data key pair -----------------------
for key, _name in AI_ITEMS:
    check(f"AI entry activates its generator [{key}]",
          f'href="/?tool={key}#ai-tools" data-ai-tool="{key}"' in home)
for key, _name in TK_ITEMS:
    check(f"toolkit entry activates its tool [{key}]",
          f'href="/?toolkit={key}#video-toolkit" data-tk-tool="{key}"'
          in home)
for key, _name in SP_ITEMS:
    check(f"script/prompt entry activates its side [{key}]",
          f'href="/?sp={key}#script-prompt" data-sp-tool="{key}"' in home)

# --- data keys match the controls they activate ---------------
grid_ai = set(re.findall(r'class="ai-tool[^"]*" data-tool="([^"]+)"', home))
menu_ai = set(re.findall(r'data-ai-tool="([^"]+)"', home))
check("dropdown AI keys == AI grid buttons",
      grid_ai == {k for k, _ in AI_ITEMS} and grid_ai <= menu_ai,
      f"grid={sorted(grid_ai)}")
tk_btns = set(re.findall(r'class="tk-tool" data-tool="([^"]+)"', home))
menu_tk = set(re.findall(r'data-tk-tool="([^"]+)"', home))
check("dropdown toolkit keys == toolkit buttons",
      tk_btns == menu_tk == {k for k, _ in TK_ITEMS},
      f"buttons={sorted(tk_btns)} menu={sorted(menu_tk)}")
menu_sp = set(re.findall(r'data-sp-tool="([^"]+)"', home))
check("dropdown script/prompt keys", menu_sp == {"script", "prompts"},
      str(sorted(menu_sp)))

# --- the hub itself is untouched -------------------------------
check("tools hub still on the homepage", 'id="tools-hub"' in home)
check("hub still has 11 cards",
      len(re.findall(r'class="hub-card"', home)) == 11,
      str(len(re.findall(r'class="hub-card"', home))))

# --- activation wiring shipped ---------------------------------
check("same-page interception shipped",
      ".tmenu-panel a[data-ai-tool]" in home
      and "qgrabCloseToolsMenu" in home)
check("cross-page param activation shipped",
      "params.get('tool')" in home and "params.get('toolkit')" in home
      and "params.get('sp')" in home)
check("SP activation flashes the right button",
      "spBtnPrompts" in home and "tool-flash" in home
      and ".tool-flash{" in home)

# --- precise spec: arrow right of "Tools", hover opens ---------
check("chevron sits right of the word Tools",
      re.search(r'id="toolsMenuBtn"[^>]*>Tools <svg class="tchev"',
                home) is not None)
check("hover-open wiring shipped (desktop)",
      "mouseenter" in home and "pointer: fine" in home
      and "mouseleave" in home)
check("mobile nav toggle JS shipped", "qgrabCloseMobileNav" in home
      and "nav-open" in home)

# --- usage card removed, counting untouched ----------------------
check("no usage card on the homepage",
      'id="usage"' not in home and "Today's free usage" not in home
      and 'id="usageToolsVal"' not in home
      and 'id="usageDlVal"' not in home)
check("usage card CSS + filler JS gone",
      ".usage-card{" not in home and "qgrabUsageRefresh = load" not in home)
check("tools block directly under the hero now",
      -1 < home.find('id="download"') < home.find('id="tools-hub"'))
r = client.get("/api/ai-tools/quota")
check("AI tools counter still served", r.status_code == 200
      and "used" in r.get_json(), str(r.status_code))
r = client.get("/api/script-prompt/quota")
check("script/prompt counters still served", r.status_code == 200
      and "script_used" in r.get_json(), str(r.status_code))
r = client.post("/api/event", json={"name": "history_view"})
check("usage events still counted", r.status_code == 200,
      str(r.status_code))

# --- the activation URLs themselves render fine -----------------
for url in ("/?tool=titles#ai-tools", "/?toolkit=tags#video-toolkit",
            "/?sp=prompts#script-prompt"):
    r = client.get(url.split("#")[0])
    check(f"activation URL renders [{url}]", r.status_code == 200,
          str(r.status_code))

print()
if FAILURES:
    print(f"{len(FAILURES)} failures")
    sys.exit(1)
print("ALL ROUND-6 CHECKS PASSED")
