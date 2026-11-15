"""Email subscribe system (round 3, 2026-11-16, owner's
order — Fiverr-style daily update emails, NO accounts):

  * POST /api/subscribe validates, stores (email + source +
    timestamp + unsubscribe token) and dedupes;
  * GET /api/subscribe/inbox is owner-gated (404 without the
    env key, 401 wrong key, 200 right key) and exports CSV;
  * GET /api/unsubscribe?token= removes exactly that
    subscriber; a bad token is a 404;
  * the digest builder produces the branded HTML with the
    subscriber's own unsubscribe link;
  * sending NO-OPS safely with no Resend key configured, and
    with a key + stubbed transport it "sends" to all
    subscribers (nothing real is ever sent in tests).

Run:  .venv/bin/python tests/test_subscribe.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = tempfile.mkdtemp(prefix="qgrab-sub-")
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

r = client.post("/api/subscribe", json={"email": "not-an-email"})
check("bad email 400", r.status_code == 400
      and r.get_json()["error"] == "invalid_email")
r = client.post("/api/subscribe", json={"email": "a@b"})
check("no TLD 400", r.status_code == 400)

r = client.post("/api/subscribe",
                json={"email": "Fan@Example.com", "source": "popup"})
check("subscribe ok", r.status_code == 200
      and r.get_json().get("subscribed") is True, str(r.get_json()))
rows = A._load_subscribers()
check("stored once", len(rows) == 1, str(rows))
check("stored fields", rows[0]["email"] == "Fan@Example.com"
      and rows[0]["source"] == "popup" and rows[0]["ts"]
      and len(rows[0]["token"]) >= 16, str(rows[0]))
token = rows[0]["token"]

r = client.post("/api/subscribe",
                json={"email": "fan@example.com", "source": "footer"})
check("dedupe case-insensitive", r.status_code == 200
      and r.get_json().get("already") is True)
check("still one row", len(A._load_subscribers()) == 1)

r = client.post("/api/subscribe",
                json={"email": "two@example.com", "source": "weird"})
check("unknown source normalised", r.get_json().get("subscribed")
      and A._load_subscribers()[1]["source"] == "site")

# owner inbox gating
r = client.get("/api/subscribe/inbox")
check("inbox 404 without env key", r.status_code == 404,
      str(r.status_code))
os.environ["SUPPORT_INBOX_KEY"] = "owner-test-key"
HK = {"X-Support-Key": "owner-test-key"}
r = client.get("/api/subscribe/inbox",
               headers={"X-Support-Key": "wrong"})
check("inbox 401 wrong key", r.status_code == 401)
r = client.get("/api/subscribe/inbox", headers=HK)
body = r.get_json()
check("inbox lists subscribers", r.status_code == 200
      and body["count"] == 2
      and body["subscribers"][0]["email"] == "Fan@Example.com",
      str(body))
check("tokens never exposed", "token" not in str(body))
r = client.get("/api/subscribe/inbox?format=csv", headers=HK)
check("csv export", r.status_code == 200
      and "Fan@Example.com" in r.get_data(as_text=True)
      and r.headers["Content-Type"].startswith("text/csv"))

# unsubscribe
r = client.get("/api/unsubscribe?token=nope")
check("bad token 404", r.status_code == 404)
r = client.get("/api/unsubscribe?token=" + token)
check("unsubscribe works", r.status_code == 200
      and "unsubscribed" in r.get_data(as_text=True).lower())
check("row removed", [x["email"] for x in A._load_subscribers()]
      == ["two@example.com"])
r = client.get("/api/unsubscribe?token=" + token)
check("second unsubscribe 404", r.status_code == 404)

# digest builder
html = A._build_digest_html(
    "https://qgrab.onrender.com/api/unsubscribe?token=abc")
check("digest branded", "What's new on QGrab" in html
      and "Q" in html and "Grab" in html)
check("digest has updates + tip",
      "Telegram Proxies" in html and "Tip:" in html)
check("digest carries unsubscribe link",
      "/api/unsubscribe?token=abc" in html
      and "Unsubscribe anytime" in html)

# sending: no key -> safe no-op
os.environ.pop("RESEND_API_KEY", None)
out = A._send_digest()
check("no key -> no-op", out["sent"] == 0
      and out.get("skipped") == "resend_not_configured", str(out))

# sending: key + stubbed transport -> counts, nothing real
os.environ["RESEND_API_KEY"] = "test-key-not-real"
calls = []


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


_orig = A.urllib.request.urlopen


def _fake(req, timeout=None):
    calls.append(req)
    return _Resp()


A.urllib.request.urlopen = _fake
try:
    out = A._send_digest()
finally:
    A.urllib.request.urlopen = _orig
    del os.environ["RESEND_API_KEY"]
check("stubbed send counts", out["sent"] == 1 and out["failed"] == 0,
      str(out))
check("resend endpoint + auth", calls
      and calls[0].full_url == "https://api.resend.com/emails"
      and calls[0].headers.get("Authorization") == "Bearer test-key-not-real")
payload = json.loads(calls[0].data.decode())
check("email payload", payload["to"] == ["two@example.com"]
      and payload["subject"] == "What's new on QGrab"
      and "/api/unsubscribe?token=" in payload["html"])

# owner-triggered endpoint is gated
r = client.post("/api/subscribe/send-digest",
                headers={"X-Support-Key": "wrong"})
check("send-digest 401 wrong key", r.status_code == 401)
r = client.post("/api/subscribe/send-digest", headers=HK)
check("send-digest owner ok + no-op unconfigured",
      r.status_code == 200
      and r.get_json()["skipped"] == "resend_not_configured")
del os.environ["SUPPORT_INBOX_KEY"]

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
