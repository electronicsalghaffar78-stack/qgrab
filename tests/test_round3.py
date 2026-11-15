"""Round 3 (2026-11-16) — site fully free, Telegram Proxies,
animations, PC extension, iPhone install:

  * homepage: Telegram Proxies in the nav + a Tools card, the
    "QGrab for PC" card + #pc section with the extension ZIP
    link and honest manual-install steps, the iPhone/iOS card
    with the real Safari Share -> Add to Home Screen route
    (and NO App Store claim);
  * scroll/Tools animations shipped (_animjs.html included,
    .rv CSS + tool-pop keyframes + reduced-motion guard);
  * /telegram-proxies renders 50-100 proxies whose connect
    links are correctly formed from data/proxies.json
    (server/port/secret round-trip through the URL);
  * the extension ZIP exists with manifest.json at its root
    and the manifest is valid MV3 JSON.

Run:  .venv/bin/python tests/test_round3.py
"""
import html as html_lib
import json
import os
import sys
import urllib.parse
import zipfile

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


home = client.get("/").get_data(as_text=True)

# --- homepage mentions -------------------------------------------------------
check("nav Telegram Proxies", 'href="/telegram-proxies"' in home)
check("tools card Telegram Proxies",
      "Telegram Proxies" in home and "without a VPN" in home)
check("tools card QGrab for PC", "QGrab for PC" in home)
check("pc section", 'id="pc"' in home
      and "IDM-style downloader" in home)
check("extension zip linked", "/static/downloads/qgrab-extension.zip" in home)
check("install steps honest",
      "Developer mode" in home and "Load unpacked" in home
      and "not on the Chrome Web Store" in home)
check("iphone card", "iPhone / iOS" in home and "Safari" in home
      and "Add to Home Screen" in home)
check("no app store claim", "App Store" not in home.replace(
    "not on the App Store", "").replace("no App Store app", ""))

# --- animations ---------------------------------------------------------------
check("animjs included", "qgrabPopTools" in home
      and "IntersectionObserver" in home)
check("reveal CSS shipped", ".rv{" in home and "qgToolL" in home
      and "prefers-reduced-motion" in home)
check("tools nav hook", 'class="nav-link js-tools"' in home)

# --- proxies page --------------------------------------------------------------
data_path = os.path.join(os.path.dirname(__file__), "..", "data",
                         "proxies.json")
with open(data_path, encoding="utf-8") as fh:
    data = json.load(fh)
src = data["proxies"]
check("source list 50-100", 50 <= len(src) <= 100, str(len(src)))

r = client.get("/telegram-proxies")
check("proxies page 200", r.status_code == 200, str(r.status_code))
page = html_lib.unescape(r.get_data(as_text=True))
check("proxies heading", "Telegram Proxies" in page
      and "run without VPN" in page)
check("last updated shown", data["updated"] in page)
check("refresh note", "stop working" in page)
links = [p["link"] for p in src]
check("all proxies rendered", all(l in page for l in links[:5])
      and page.count("t.me/proxy?server=") == len(src),
      str(page.count("t.me/proxy?server=")))
for p in src:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(p["link"]).query)
    assert q["server"][0] == str(p["server"]), p
    assert int(q["port"][0]) == int(p["port"]), p
    assert q["secret"][0] == str(p["secret"]), p
check("every link round-trips server/port/secret", True)

# --- extension package ----------------------------------------------------------
zip_path = os.path.join(os.path.dirname(__file__), "..", "static",
                        "downloads", "qgrab-extension.zip")
check("extension zip exists", os.path.exists(zip_path))
if os.path.exists(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        check("manifest at zip root", "manifest.json" in names, str(names))
        man = json.loads(zf.read("manifest.json"))
        check("manifest is MV3", man.get("manifest_version") == 3)
        check("content script shipped", "content.js" in names)

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
