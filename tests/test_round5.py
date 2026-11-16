"""Round 5 (2026-11-16.25): owner's homepage-layout orders.

After the .24 check the owner approved everything EXCEPT the
homepage section placement, and ordered:

  1. the homepage Subscribe card ("QGrab updates, by email")
     REMOVED — the footer subscribe form stays (owner: "that
     one is perfect"); the /api/subscribe backend and the
     3rd-download subscribe popup stay too;
  2. the Invite card moved to the VERY BOTTOM of the homepage
     content — the last section before the footer;
  3. the tools block (Tools Hub + Video Toolkit + AI Tools +
     Script + Prompt) moved UP to directly below the "Today's
     free usage" card;
  4. Download History is its OWN PAGE (/download-history),
     like Chrome's downloads tab — no longer a homepage
     section; nav links on every page point at the page;
  5. the stale "Premium subscription — $20/month" row deleted
     from "QGrab at a Glance" (site is 100% free since .17);
  6. the iOS card's red-apple emoji replaced with the authentic
     monochrome bitten-apple glyph (inline SVG).

Run:  .venv/bin/python tests/test_round5.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-r5-")
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

# --- 1. homepage Subscribe card removed, footer form kept -----
check("no subscribe section on homepage", 'id="subscribe"' not in home)
check("section subscribe card text gone",
      "QGrab updates, by email" not in home)
check("no section subscribe form", 'data-source="section"' not in home)
check("footer subscribe form kept", 'data-source="footer"' in home
      and 'id="subEmailFoot"' in home)
check("subscribe popup still shipped", "qgrab_subscribed" in home
      and "sub-pop" in home)
r = client.post("/api/subscribe", json={"email": "fan@example.com"})
check("subscribe API still works", r.status_code == 200
      and r.get_json().get("subscribed") is True, str(r.status_code))

# --- 4. Download History: own page, off the homepage ----------
check("no history section on homepage",
      'id="download-history"' not in home and 'id="histList"' not in home)
check("recording JS still on homepage", "QGHistory" in home
      and "qgrab_dl_history_v1" in home)
r = client.get("/download-history")
check("/download-history serves 200", r.status_code == 200,
      str(r.status_code))
hist = r.get_data(as_text=True)
check("history page has the list markup",
      'id="download-history"' in hist and 'id="histList"' in hist
      and 'id="histEmpty"' in hist and 'id="histClear"' in hist)
check("history page empty-state text",
      "No downloads yet — your downloads will appear here." in hist)
check("history page intro text",
      "saved in this browser, on this device" in hist)
check("history page ships the renderer", "qgrab_dl_history_v1" in hist
      and "Download Again" in hist)
check("history page rerun handoff", "qgrabHistoryRerun" in hist
      and "/?url=" in hist)
for path in ("/", "/youtube-video-downloader", "/telegram-proxies",
             "/video-to-script-prompt", "/download-history"):
    page = client.get(path).get_data(as_text=True)
    check(f"nav history link is the page [{path}]",
          'href="/download-history"' in page)
    check(f"no dead history anchor [{path}]",
          'href="#download-history"' not in page
          and 'href="/#download-history"' not in page)

# --- 3 + 2. homepage order: usage -> tools -> search -> specs,
#        invite last before the footer --------------------------
def pos(needle, label):
    i = home.find(needle)
    check(f"present: {label}", i >= 0, needle)
    return i

p_usage = pos('id="usage"', "usage card")
p_hub = pos('id="tools-hub"', "tools hub")
p_tk = pos('id="video-toolkit"', "video toolkit")
p_ai = pos('id="ai-tools"', "ai tools")
p_sp = pos('id="script-prompt"', "script+prompt")
p_search = pos('id="search-videos"', "search videos")
p_specs = pos('class="specs"', "at a glance")
p_invite = pos('id="invite"', "invite")
p_footer = pos("<footer", "footer")
check("tools block directly after usage",
      p_usage < p_hub < p_tk < p_ai < p_sp)
check("search + specs after the tools block",
      p_sp < p_search < p_specs)
check("invite is the last section before the footer",
      p_specs < p_invite < p_footer
      and home.rfind("<section") < p_footer
      and home.find('id="invite"') > home.find('id="pc"'))

# --- 5. premium leftover gone ----------------------------------
check("no Premium subscription text", "Premium subscription" not in home)
check("no $20/month text", "$20/month" not in home)
check("specs section still present", 'class="specs"' in home)

# --- 6. iOS card: authentic bitten-apple glyph ------------------
check("apple emoji gone from homepage", "🍎" not in home)
check("bitten-apple glyph on the iOS card", 'class="ios-apple"' in home
      and "M12.152 6.896" in home)
check("iOS card still present", 'class="ios-card"' in home
      and "iPhone / iOS" in home)

# --- assistant: KB + fallback + goto know the new page ---------
check("assistant KB says Download History page",
      "listed on the Download History page" in qgrab.ASSISTANT_SYSTEM_PROMPT)
check("assistant goto still offers download-history",
      "download-history" in qgrab.ASSISTANT_GOTO_IDS)
check("assistant goto navigates to the page",
      "gotoId === 'download-history'" in home
      and "'/download-history'" in home)
tpl = open(os.path.join(os.path.dirname(__file__), "..",
                        "templates", "_asstfallback.html"),
           encoding="utf-8").read()
check("assistant fallback says page",
      "Open the Download History page" in tpl)

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
