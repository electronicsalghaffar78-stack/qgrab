"""Per-feature usage stats (round 3, 2026-11-16):

  * POST /api/event increments the right daily counter;
    unknown events are a 400 and count nothing;
  * server-side bumps land in the same store;
  * GET /api/stats is owner-gated and returns totals +
    7/30-day windows sorted most-used first;
  * a broken event call never breaks a real feature
    (subscribe + assistant still work right after).

Run:  .venv/bin/python tests/test_stats.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = tempfile.mkdtemp(prefix="qgrab-stats-")
os.environ["QGRAB_DATA_DIR"] = _TMP
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as A  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


client = A.app.test_client()
today = A._stats_day()

r = client.post("/api/event", json={"name": "proxy_connect"})
check("event ok", r.status_code == 200)
client.post("/api/event", json={"name": "proxy_connect"})
client.post("/api/event", json={"name": "history_view"})
data = A._load_stats()
check("daily counters increment",
      data[today]["proxy_connect"] == 2
      and data[today]["history_view"] == 1, str(data))

r = client.post("/api/event", json={"name": "made_up_event"})
check("unknown event 400", r.status_code == 400)
check("unknown counted nothing",
      "made_up_event" not in A._load_stats().get(today, {}))
r = client.post("/api/event", json={})
check("missing name 400", r.status_code == 400)

# server-side bumps share the store
A._stats_bump("download_youtube")
A._stats_bump("download_youtube")
A._stats_bump("ai_tool_titles")
A._stats_bump("not_a_real_event")  # silently ignored, never raises
data = A._load_stats()
check("server bumps counted", data[today]["download_youtube"] == 2
      and data[today]["ai_tool_titles"] == 1)

# an older day's counts join totals + windows correctly
# (10 days ago: inside the 30-day window and the 400-day
# storage pruning horizon, outside the 7-day window)
from datetime import timedelta
_old_day = (A._sp_quota_now().date() - timedelta(days=10)).isoformat()
A._stats_bump("proxy_connect", day=_old_day)
A._stats_bump("extension_download", day=_old_day)

# gating
r = client.get("/api/stats")
check("stats 404 without env key", r.status_code == 404)
os.environ["SUPPORT_INBOX_KEY"] = "owner-test-key"
HK = {"X-Support-Key": "owner-test-key"}
r = client.get("/api/stats", headers={"X-Support-Key": "wrong"})
check("stats 401 wrong key", r.status_code == 401)
r = client.get("/api/stats", headers=HK)
body = r.get_json()
check("stats 200 for owner", r.status_code == 200, str(r.status_code))
totals = {p["event"]: p["count"] for p in body["totals"]}
check("totals include old days", totals["proxy_connect"] == 3
      and totals["extension_download"] == 1)
w7 = {p["event"]: p["count"] for p in body["last_7_days"]}
w30 = {p["event"]: p["count"] for p in body["last_30_days"]}
check("7-day window excludes old day",
      w7.get("proxy_connect") == 2
      and "extension_download" not in w7)
check("30-day window includes old day",
      w30.get("extension_download") == 1)
counts = [p["count"] for p in body["totals"]]
check("totals sorted most-used first",
      counts == sorted(counts, reverse=True), str(body["totals"]))
check("today reported", body["today"] == today)
del os.environ["SUPPORT_INBOX_KEY"]

# a failed event call never breaks the underlying feature
r = client.post("/api/event", data="not json",
                content_type="application/json")
check("garbage event body handled", r.status_code in (200, 400))
r = client.post("/api/subscribe",
                json={"email": "stats@example.com", "source": "footer"})
check("subscribe still works", r.status_code == 200
      and r.get_json().get("subscribed") is True)
data = A._load_stats()
check("subscribe counted server-side",
      data[today].get("subscribe") == 1, str(data.get(today)))

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
