"""Round 2 (2026-11-16): Dahot-shaped header/hero, Download
History, and the rebuilt AI Assistant (Q-orb avatar + photo
input). Covers the RENDERED pages and the assistant endpoint:

  * header: logo + tagline "All Platform Video Download in
    One Place" (owner's exact corrected dictation, 2026-11-16:
    singular 'Download', with 'Video'), nav Home/Tools/Download History/
    FAQ, hero title and downloader-card title in Dahot's shape
    with QGrab's name, platform chips (verified + beta-noted),
    the four trust chips, the free pill, the Today's-free-usage
    counters and the Download History section;
  * the assistant avatar is QGrab's own animated Q-orb SVG —
    and no ghost (👻) exists anywhere in templates/;
  * assistant photo input: a valid photo reaches Gemini as an
    inline_data part; a bad mime / oversized photo is dropped
    silently; a photo alone (empty message) is a valid
    question and does NOT take the greeting fast-path; empty
    message with no photo is a 400.

Run:  .venv/bin/python tests/test_round2.py
"""
import base64
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-r2-")
os.environ.setdefault("QGRAB_DATA_DIR", _TMPDIR)

import app as qgrab  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


client = qgrab.app.test_client()
home = client.get("/").get_data(as_text=True)

# --- header / hero -----------------------------------------------------------
check("tagline exact", "All Platform Video Download in One Place" in home)
check("hero title", "Free Video Downloader &amp; Social Media Tools — QGrab" in home
      or "Free Video Downloader & Social Media Tools — QGrab" in home)
check("card title", "Online Video Downloader — YouTube, TikTok, Instagram, Facebook" in home)
for label in ("Home", "Tools", "Download History", "FAQ"):
    check(f"nav has {label}", f">{label}</a>" in home)
check("nav history target", 'href="#download-history"' in home)
check("works-with line", "Works with YouTube, TikTok, Instagram, Facebook" in home)
# SEO pass (2026-11-16): the hero chips are real links to the
# platform pages now (they were plain spans), so the checks pin the
# anchor markup; VK has no page of its own and stays a span.
# Release .24 (2026-11-16): every chip now carries its platform's
# brand icon (<svg class="pchip-ic">) before the name, so the
# checks pin anchor + icon + name instead of the bare anchor.
for chip, path in (("YouTube", "/youtube-video-downloader"),
                   ("TikTok", "/tiktok-video-downloader"),
                   ("Instagram", "/instagram-video-downloader"),
                   ("Facebook", "/facebook-video-downloader"),
                   ("SoundCloud", "/soundcloud-downloader"),
                   ("Twitch", "/twitch-video-downloader"),
                   ("Telegram", "/telegram-video-downloader"),
                   # Release .22 (2026-11-16): Vimeo verified fully
                   # working in production (info + real downloads),
                   # so its chip graduated from beta to regular.
                   ("Vimeo", "/vimeo-video-downloader"),
                   # Release .23 (2026-11-16): Dailymotion graduated
                   # too — the .22 HLS fix was live-verified
                   # delivering real MP4 downloads.
                   ("Dailymotion", "/dailymotion-video-downloader")):
    check(f"chip {chip} links to its page",
          re.search(rf'<a class="pchip" href="{re.escape(path)}">'
                    rf'<svg class="pchip-ic".*?>{chip}</a>',
                    home, re.S) is not None)
check("chip VK stays a span (no VK page)",
      re.search(r'<span class="pchip"><svg class="pchip-ic".*?>VK</span>',
                home, re.S) is not None)
for chip, path in (("Reddit", "/reddit-video-downloader"),):
    check(f"beta chip {chip} links to its page",
          re.search(rf'<a class="pchip beta" href="{re.escape(path)}">'
                    rf'<svg class="pchip-ic".*?>{chip} \*</a>',
                    home, re.S) is not None)
check("beta honesty note", "still being improved" in home)
for gone in ("Threads", "SnackVideo", "WhatsApp"):
    check(f"no chip {gone}", f'<span class="pchip">{gone}</span>' not in home
          and f'<span class="pchip beta">{gone}' not in home
          and f'>{gone}</a>' not in home
          and f'>{gone} *</a>' not in home)
for trust in ("Secure processing", "Files are never stored on our servers",
              "Works on all devices", "Direct from the source platform"):
    check(f"trust chip: {trust}", trust in home)
check("no advertisement placeholder", "ADVERTISEMENT" not in home
      and "Ads appear here" not in home)
check("usage counters", 'id="usageToolsVal"' in home
      and 'id="usageDlVal"' in home and "Today's free usage" in home)
check("history section", 'id="download-history"' in home
      and 'id="histList"' in home and 'id="histClear"' in home
      and "Clear History" in home)
check("history js shipped", "qgrab_dl_history_v1" in home
      and "QGHistory" in home)

plat = client.get("/youtube-video-downloader").get_data(as_text=True)
check("platform header tagline", "All Platform Video Download in One Place" in plat)
check("platform nav history", "Download History" in plat)

# --- assistant avatar: Q-orb, never the ghost --------------------------------
tpl_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
ghost_found = []
for fn in os.listdir(tpl_dir):
    with open(os.path.join(tpl_dir, fn), encoding="utf-8") as fh:
        if "👻" in fh.read():
            ghost_found.append(fn)
check("no ghost anywhere in templates", not ghost_found, str(ghost_found))
asst = open(os.path.join(tpl_dir, "_assistant.html"), encoding="utf-8").read()
check("orb avatar present", 'class="asst-orb"' in asst and "qorb-ring" in asst
      and "qorb-eye" in asst)
check("assistant labelled AI Assistant", "AI Assistant" in asst)
check("robot emoji gone", "🤖" not in asst)
check("attach button present", 'id="asstAttach"' in asst
      and 'id="asstFile"' in asst)

# --- assistant photo flow ------------------------------------------------------
class _FakeResponse:
    def __init__(self, text):
        self._body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": text}]}}],
        }).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _reset_asst():
    with qgrab._asst_daily_lock:
        qgrab._asst_daily["date"] = None
        qgrab._asst_daily["done"] = 0
        qgrab._asst_daily["reserved"] = 0


_bodies = []
_orig_urlopen = qgrab.urllib.request.urlopen


def _recording(req, timeout=None):
    _bodies.append(req.data)
    return _FakeResponse(json.dumps(
        {"answer": "I can see the screenshot.", "goto": None,
         "support": False}))


qgrab.urllib.request.urlopen = _recording
try:
    _reset_asst()
    b64 = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg").decode()
    r = client.post("/api/assistant", json={
        "message": "", "image": {"mime": "image/jpeg", "data": b64}})
    check("photo-only question 200", r.status_code == 200,
          str(r.status_code))
    check("photo-only is not the greeting",
          r.get_json()["answer"] == "I can see the screenshot.",
          str(r.get_json()))
    payload = json.loads(_bodies[-1].decode("utf-8"))
    parts = payload["contents"][0]["parts"]
    inline = [p for p in parts if "inline_data" in p]
    check("inline_data part reached Gemini", len(inline) == 1
          and inline[0]["inline_data"]["mime_type"] == "image/jpeg"
          and inline[0]["inline_data"]["data"] == b64, str(parts)[:200])

    _reset_asst()
    r = client.post("/api/assistant", json={
        "message": "what is this error?",
        "image": {"mime": "image/bmp", "data": b64}})
    payload = json.loads(_bodies[-1].decode("utf-8"))
    parts = payload["contents"][0]["parts"]
    check("bad mime dropped, question still answered",
          r.status_code == 200
          and not any("inline_data" in p for p in parts))

    _reset_asst()
    big = "A" * (qgrab.ASSISTANT_IMAGE_MAX_B64 + 10)
    r = client.post("/api/assistant", json={
        "message": "big photo", "image": {"mime": "image/png", "data": big}})
    payload = json.loads(_bodies[-1].decode("utf-8"))
    parts = payload["contents"][0]["parts"]
    check("oversized photo dropped", r.status_code == 200
          and not any("inline_data" in p for p in parts))

    _reset_asst()
    r = client.post("/api/assistant", json={"message": ""})
    check("empty message + no photo is 400", r.status_code == 400,
          str(r.status_code))
    r = client.post("/api/assistant", json={
        "message": "", "image": {"mime": "image/bmp", "data": b64}})
    check("empty message + bad photo is 400", r.status_code == 400,
          str(r.status_code))
finally:
    qgrab.urllib.request.urlopen = _orig_urlopen

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
