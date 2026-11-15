"""Tests for the 2026-11-16 Dahot-features build
(UPDATE-2026-11-16-DAHOT-FEATURES.md).

Covers:
  * site_of() naming the new platforms + their attempt plan;
  * the new platform pages rendering (200 + own H1) and the
    sitemap listing them;
  * Eye Care: the eyecare CSS block + the 3-mode cycle in the
    theme bootstrap on home and platform pages;
  * round 3 (2026-11-16, owner's order): paid Premium was
    cancelled and the site is fully free — the premium config
    math, welcome/referral claims and JazzCash/Easypaisa
    payment-request tests that stood here now assert the
    /api/premium/* routes are GONE (404) instead;
  * reports: validation, storage, key-gated inbox (404 without
    the env key, 401 with a wrong key, 200 with the right one);
  * ratings summary now carries a real star distribution;
  * SP/AI caches: a second identical AI generation is served
    from cache (Gemini stubbed — the stub is called once).

Run:  .venv/bin/python tests/test_dahot_features.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = os.path.join(os.path.dirname(__file__), ".test-data-dahot")
os.makedirs(_TMP, exist_ok=True)
os.environ["QGRAB_DATA_DIR"] = _TMP
for _f in ("premium.json", "reports.json", "ratings.json"):
    try:
        os.remove(os.path.join(_TMP, _f))
    except OSError:
        pass

import app as A  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS", name)
    else:
        failed += 1
        print("FAIL", name, extra)


client = A.app.test_client()

# --- platforms -------------------------------------------------------------
for host, want in [
        ("https://www.reddit.com/r/videos/comments/abc/x/", "reddit"),
        ("https://vimeo.com/12345", "vimeo"),
        ("https://www.twitch.tv/videos/123", "twitch"),
        ("https://soundcloud.com/a/b", "soundcloud"),
        ("https://www.dailymotion.com/video/x1", "dailymotion"),
        ("https://dai.ly/x1", "dailymotion"),
        ("https://www.threads.net/@a/post/x", "threads"),
        ("https://t.me/c/1/2", "telegram"),
        ("https://www.snackvideo.com/@a", "kwai"),
        ("https://www.messenger.com/t/1", "messenger")]:
    check(f"site_of {want}", A.site_of(host) == want,
          A.site_of(host))
plan = A._attempt_plan("https://vimeo.com/12345")
check("new platforms impersonation-first plan",
      plan and plan[0].get("impersonate") is True, str(plan))

for path, h1 in [
        ("/reddit-video-downloader", "Reddit Video Downloader"),
        ("/vimeo-video-downloader", "Vimeo Video Downloader"),
        ("/twitch-video-downloader", "Twitch Video Downloader"),
        ("/soundcloud-downloader", "SoundCloud Downloader"),
        ("/dailymotion-video-downloader", "Dailymotion Video Downloader"),
        ("/pinterest-video-downloader", "Pinterest Video Downloader"),
        ("/twitter-video-downloader", "X (Twitter) Video Downloader")]:
    r = client.get(path)
    check(f"page {path}", r.status_code == 200 and h1.encode() in r.data,
          str(r.status_code))
sm = client.get("/sitemap.xml").data.decode()
check("sitemap lists new pages",
      "/reddit-video-downloader" in sm and "/soundcloud-downloader" in sm)

# --- eye care ---------------------------------------------------------------
home = client.get("/").data.decode()
check("home eyecare CSS", 'html[data-theme="eyecare"]' in home)
check("theme cycle includes eyecare",
      "eyecare" in home and "MODES" in home)
plat = client.get("/reddit-video-downloader").data.decode()
check("platform eyecare CSS", 'html[data-theme="eyecare"]' in plat)
check("home hero chips new platforms",
      "Reddit" in home and "SoundCloud" in home and "Dailymotion" in home)
check("home auto-SP note + hook",
      "spAutoNote" in home and "qgrabAutoScriptPrompt" in home)

# --- round 3: Premium / referral / payments REMOVED -----------------------
# The owner's 2026-11-16 round-3 order cancelled paid Premium
# altogether ("har koi free me use kare, kamai ads se hogi").
# The round-1 premium config, welcome/referral claims and the
# JazzCash/Easypaisa payment-request flow that were tested
# here are gone by design: every /api/premium/* route answers
# 404 and the homepage carries no Plans/Premium wording.
for method, path in [("GET", "/api/premium/config"),
                     ("GET", "/api/premium/status"),
                     ("POST", "/api/premium/claim-welcome"),
                     ("POST", "/api/premium/request"),
                     ("GET", "/api/premium/inbox"),
                     ("POST", "/api/premium/approve"),
                     ("POST", "/api/premium/reject")]:
    r = client.open(path, method=method, json={})
    check(f"premium route gone {method} {path}",
          r.status_code == 404, str(r.status_code))
check("no USD_PKR_RATE left", not hasattr(A, "USD_PKR_RATE"))
check("home has no plans section", 'id="plans"' not in home
      and "⭐ Plans" not in home)

# --- reports ----------------------------------------------------------------
os.environ["SUPPORT_INBOX_KEY"] = "owner-test-key"
r = client.post("/api/report", json={"category": "nope",
                                     "message": "hello world"})
check("report bad category 400", r.status_code == 400)
r = client.post("/api/report", json={"category": "bug",
                                     "message": "the button broke",
                                     "page": "/"})
check("report stored", r.status_code == 200 and r.get_json()["ok"])
inbox = client.get("/api/reports/inbox",
                   headers={"X-Support-Key": "owner-test-key"})
check("reports inbox", inbox.status_code == 200
      and inbox.get_json()["count"] >= 1)
r = client.get("/api/reports/inbox",
               headers={"X-Support-Key": "wrong"})
check("reports inbox wrong key 401", r.status_code == 401)
del os.environ["SUPPORT_INBOX_KEY"]
r = client.get("/api/reports/inbox",
               headers={"X-Support-Key": "owner-test-key"})
check("reports inbox no env key 404", r.status_code == 404)

# --- ratings distribution ---------------------------------------------------
with A._ratings_lock:
    A._save_ratings([
        {"stars": 5, "name": "T", "text": "great", "date": "2026-11-16"},
        {"stars": 5, "name": "", "text": "", "date": "2026-11-16"},
        {"stars": 3, "name": "", "text": "", "date": "2026-11-16"},
    ])
summary = A.ratings_summary()
check("ratings distribution real",
      summary["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 2},
      str(summary.get("distribution")))
check("ratings average real", summary["average"] == 4.3)

# --- AI tools cache (Gemini stubbed) ----------------------------------------
import urllib.request  # noqa: E402

A._ai_result_cache.clear()
os.environ["GEMINI_API_KEY"] = "test-key-not-real"
calls = {"n": 0}


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    calls["n"] += 1
    return _FakeResp({"candidates": [{"content": {"parts": [
        {"text": json.dumps({"items": ["One", "Two"]})}]}}]})


_orig = urllib.request.urlopen
urllib.request.urlopen = _fake_urlopen
try:
    r1 = client.post("/api/ai-tools/generate",
                     json={"tool": "titles", "input": "cats"})
    r2 = client.post("/api/ai-tools/generate",
                     json={"tool": "titles", "input": "Cats"})
finally:
    urllib.request.urlopen = _orig
check("ai first call ok", r1.status_code == 200, str(r1.status_code))
check("ai second call cached",
      r2.status_code == 200 and r2.get_json().get("cached") is True,
      str(r2.get_json()))
check("gemini called once for repeats", calls["n"] == 1,
      str(calls["n"]))

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
