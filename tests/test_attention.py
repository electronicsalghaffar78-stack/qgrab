"""Reports & low-rating watch (round 3 G, CORRECTED by the
owner 2026-11-16 — "DO NOT ask visitors anything"):

  * ratings are STARS-ONLY, exactly as before round 3: a LOW
    rating (1-2 stars) stores stars/name/text/date only — any
    reason / reason_text a client sends is IGNORED, never
    stored (there is no "What went wrong?" prompt, no reason
    chips and no reason field anywhere in the UI);
  * a HIGH rating likewise stores no reason fields;
  * GET /api/attention is owner-gated and its "Needs
    attention" digest shows COUNTS (reports_total,
    new_reports_7d, low_ratings_total) + newest-first entries
    WITHOUT any reason fields;
  * reports + support inbox responses carry the same summary;
  * the Reports form itself is unchanged (whatever a visitor
    voluntarily writes there is read by the owner only);
  * rating_low + report_submitted land in the usage stats.

Run:  .venv/bin/python tests/test_attention.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = tempfile.mkdtemp(prefix="qgrab-attn-")
os.environ["QGRAB_DATA_DIR"] = _TMP

import app as A  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


client = A.app.test_client()

# fresh client per rating: the ratings cookie blocks a second
# rating from one browser
def rate(payload):
    c = A.app.test_client()
    return c.post("/api/rate", json=payload)

# Even when a (stale/crafted) client still SENDS reason fields
# with a low rating, the server must ignore them entirely.
r = rate({"stars": 2, "name": "Sad", "text": "it broke",
          "reason": "download_failed",
          "reason_text": "the MP4 never started"})
check("low rating accepted", r.status_code == 200, str(r.status_code))
rows = A._load_ratings()
low = [x for x in rows if x["stars"] == 2]
check("low rating stores STARS ONLY (reason ignored)",
      low and "reason" not in low[0] and "reason_text" not in low[0]
      and low[0].get("text") == "it broke",
      str(rows))

r = rate({"stars": 1, "reason": "nonsense", "text": ""})
rows = A._load_ratings()
one = [x for x in rows if x["stars"] == 1]
check("1-star rating kept, reason ignored",
      r.status_code == 200 and one and "reason" not in one[0]
      and "reason_text" not in one[0],
      str(one))

r = rate({"stars": 5, "name": "Happy", "text": "great",
          "reason": "too_slow", "reason_text": "should not stick"})
rows = A._load_ratings()
hi = [x for x in rows if x["stars"] == 5]
check("high rating stores NO reason",
      hi and "reason" not in hi[0] and "reason_text" not in hi[0],
      str(hi))

# the UI must not ask anything: no prompt, chips or fields
import pathlib
reviews_html = (pathlib.Path(__file__).resolve().parent.parent
                / "templates" / "_reviews.html").read_text(
                    encoding="utf-8")
check("no 'What went wrong?' prompt in UI",
      "What went wrong" not in reviews_html
      and "rateReason" not in reviews_html
      and "reason-chip" not in reviews_html,
      "prompt/chips still present in _reviews.html")
check("no RATING_REASONS constant in app",
      not hasattr(A, "RATING_REASONS"))

# a report to surface in the digest (form unchanged: whatever
# the visitor voluntarily writes is stored for the owner)
r = client.post("/api/report", json={
    "category": "broken_download",
    "message": "this tiktok link fails every time", "page": "/"})
check("report stored", r.status_code == 200)

# gating + digest (counts only, no reasons)
r = client.get("/api/attention")
check("attention 404 without env key", r.status_code == 404)
os.environ["SUPPORT_INBOX_KEY"] = "owner-test-key"
HK = {"X-Support-Key": "owner-test-key"}
r = client.get("/api/attention", headers={"X-Support-Key": "wrong"})
check("attention 401 wrong key", r.status_code == 401)
r = client.get("/api/attention", headers=HK)
body = r.get_json()
check("attention 200 for owner", r.status_code == 200)
check("digest counts", body["reports_total"] >= 1
      and body["new_reports_7d"] >= 1
      and body["low_ratings_total"] == 2, str(body)[:200])
lows = body["low_ratings"]
check("digest lists low ratings newest first",
      [x["stars"] for x in lows] == [1, 2], str(lows))
check("digest carries NO reason fields",
      all("reason" not in x and "reason_text" not in x
          for x in lows), str(lows))
check("digest lists newest report",
      body["latest_reports"]
      and body["latest_reports"][0]["category"] == "broken_download")

r = client.get("/api/reports/inbox", headers=HK)
check("reports inbox carries summary",
      r.get_json().get("needs_attention", {})
      .get("low_ratings_total") == 2)
r = client.get("/api/support/inbox", headers=HK)
check("support inbox carries summary",
      r.get_json().get("needs_attention", {})
      .get("reports_total") >= 1)
del os.environ["SUPPORT_INBOX_KEY"]

# analytics: low ratings + reports counted
today = A._stats_day()
data = A._load_stats()
check("rating_low counted", data.get(today, {}).get("rating_low") == 2,
      str(data.get(today)))
check("report_submitted counted",
      data.get(today, {}).get("report_submitted") == 1)

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
