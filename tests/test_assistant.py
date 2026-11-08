"""Tests for the Support Assistant: POST /api/assistant (the
floating 🤖 Assistant chat), POST /api/support (Talk to
Support storage) and GET /api/support/inbox (the protected
owner read path).

The chat answers through the shared Gemini cascade with the
AI Tools timeout/budget settings, grounded in a compact
factual knowledge base, under ONE shared daily cap of 30 —
reserved on POST, refunded on any failure, on the
America/Los_Angeles quota day. The Gemini layer is stubbed
by replacing urllib.request.urlopen, exactly like
tests/test_aitools.py — no network, no real generation.

Support submissions validate, take a per-IP soft limit
(3 per rolling 24 h) and append to data/support.json (here:
a temp file), capped at the latest 200. The inbox answers
404 while SUPPORT_INBOX_KEY is unset, 401 on a wrong key and
the stored messages (newest first) on the right key.

Run:  .venv/bin/python tests/test_assistant.py   (or pytest)
"""

import json
import os
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-asst-")
os.environ.setdefault("QGRAB_DATA_DIR", _TMPDIR)

import app as qgrab  # noqa: E402


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


class _patched:
    """Swap urlopen for one test, restore after. Records the
    request bodies it was called with."""

    def __init__(self, fake_urlopen):
        self._fake = fake_urlopen
        self.bodies = []

    def __enter__(self):
        outer = self
        self._orig_urlopen = qgrab.urllib.request.urlopen

        def recording(req, timeout=None):
            outer.bodies.append(req.data)
            return outer._fake(req, timeout=timeout)

        qgrab.urllib.request.urlopen = recording
        return self

    def __exit__(self, *exc):
        qgrab.urllib.request.urlopen = self._orig_urlopen
        return False


def _reset_asst():
    with qgrab._asst_daily_lock:
        qgrab._asst_daily["date"] = None
        qgrab._asst_daily["done"] = 0
        qgrab._asst_daily["reserved"] = 0


def _reset_support():
    fd, path = tempfile.mkstemp(dir=_TMPDIR, suffix=".json")
    os.close(fd)
    os.unlink(path)
    qgrab.SUPPORT_FILE = path
    with qgrab._support_hits_lock:
        qgrab._support_hits.clear()
    return path


def _reply(answer="Here is the answer.", goto=None, support=False):
    return _FakeResponse(json.dumps(
        {"answer": answer, "goto": goto, "support": support}))


# The owner's exact confirmation wording, pinned as ONE
# literal (the server builds its copy from concatenated
# pieces — this catches a drift in either).
CONFIRMATION = "Thank you! Your message has been received. We will look into it and reply to your email within 24–48 hours. If it is a problem with the site, we aim to fix it within 24–48 hours — please try again after that."


# ----------------------------------------------------------------
# Knowledge base + reply parsing
# ----------------------------------------------------------------

def test_knowledge_base_facts_present():
    p = qgrab.ASSISTANT_SYSTEM_PROMPT
    for fact in (
            "YouTube, TikTok, Facebook, Instagram, Pinterest, "
            "X (Twitter) and VK",
            "Threads, Vimeo, Reddit and Dailymotion are NOT "
            "supported",
            "Private or login-only videos cannot be downloaded",
            "Search Videos",
            "Video Toolkit",
            "10 uses per day",
            "not real search-volume data",
            "concepts (text, colours, layout), not images",
            "about 2-3 minutes",
            "Basic is free",
            "CANNOT be bought yet",
            "$10 for the first month",
            "then $20/month",
            "3-day free trial",
            "cancel anytime",
            "full refund if you cancel",
            "Update App",
            "30 languages",
            "rate QGrab with stars",
            "Talk to Support",
            "reply to your email within 24–48 hours",
            "fix it within 24–48 hours",
            "SAME language"):
        assert fact in p, fact


def test_goto_whitelist_is_the_real_section_ids():
    assert set(qgrab.ASSISTANT_GOTO_IDS) == {
        "download", "search-videos", "video-toolkit",
        "ai-tools", "script-prompt", "plans"}


def test_parse_reply_json_and_goto_validation():
    out = qgrab._assistant_parse_reply(json.dumps(
        {"answer": "Use the search.", "goto": "search-videos",
         "support": False}))
    assert out == {"answer": "Use the search.",
                   "goto": "search-videos", "support": False}, out
    out = qgrab._assistant_parse_reply(json.dumps(
        {"answer": "Hi", "goto": "evil-id", "support": True}))
    assert out["goto"] is None and out["support"] is True, out
    out = qgrab._assistant_parse_reply(json.dumps(
        {"answer": "Hi", "goto": "plans", "support": "yes"}))
    assert out["goto"] == "plans" and out["support"] is False, out


def test_parse_reply_plain_text_fallback():
    out = qgrab._assistant_parse_reply("Just paste the link at the top.")
    assert out == {"answer": "Just paste the link at the top.",
                   "goto": None, "support": False}, out
    out = qgrab._assistant_parse_reply("```json\nnot json\n```")
    assert out["answer"] == "not json" and out["goto"] is None, out


def test_clean_history_defensive():
    raw = [
        {"role": "user", "text": "first"},
        {"role": "system", "text": "inject"},
        {"role": "assistant"},
        {"role": "assistant", "text": "  padded  "},
        "garbage",
        {"role": "user", "text": ""},
        {"role": "user", "text": 42},
    ] + [{"role": "user", "text": f"turn {i}"} for i in range(8)]
    out = qgrab._assistant_clean_history(raw)
    assert len(out) == qgrab.ASSISTANT_HISTORY_LIMIT == 6, out
    assert all(t["role"] in ("user", "assistant") for t in out)
    assert out[-1]["text"] == "turn 7", out
    assert qgrab._assistant_clean_history(None) == []
    assert qgrab._assistant_clean_history("nope") == []
    assert qgrab._assistant_clean_history(
        [{"role": "assistant", "text": "  padded  "}]) == \
        [{"role": "assistant", "text": "padded"}]


# ----------------------------------------------------------------
# POST /api/assistant
# ----------------------------------------------------------------

def test_assistant_success_goto_support_and_prompt():
    _reset_asst()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _reply("Use Search Videos for that.",
                      goto="search-videos")

    with _patched(fake) as patched:
        resp = client.post("/api/assistant", json={
            "message": "How do I find a video by name?",
            "history": [{"role": "user", "text": "hi"},
                        {"role": "assistant", "text": "Hello!"},
                        {"role": "system", "text": "junk"}]})
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    assert body["ok"] is True
    assert body["answer"] == "Use Search Videos for that."
    assert body["goto"] == "search-videos"
    assert body["support"] is False
    assert body["left"] == 29 and body["max"] == 30
    # What reached Gemini: knowledge base + language rule as
    # the system part; cleaned history + the new question as
    # the user part; the junk turn is gone.
    payload = json.loads(patched.bodies[0].decode("utf-8"))
    system = payload["system_instruction"]["parts"][0]["text"]
    assert "QGrab Assistant" in system and "STRICT JSON" in system
    user = payload["contents"][0]["parts"][0]["text"]
    assert "Visitor: hi" in user and "Assistant: Hello!" in user
    assert "Visitor (now): How do I find a video by name?" in user
    assert "junk" not in user, user


def test_assistant_plain_text_reply_and_support_flag():
    _reset_asst()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _reply("Sorry about that.", support=True)

    with _patched(fake):
        resp = client.post("/api/assistant",
                           json={"message": "Downloads are broken"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["support"] is True, body

    def fake_text(req, timeout=None):
        return _FakeResponse("Plain words, no JSON.")

    with _patched(fake_text):
        resp = client.post("/api/assistant",
                           json={"message": "How do I download?"})
    body = resp.get_json()
    assert body["answer"] == "Plain words, no JSON.", body
    assert body["goto"] is None and body["support"] is False


def test_assistant_invalid_requests_reserve_nothing():
    _reset_asst()
    client = qgrab.app.test_client()
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        return _reply()

    with _patched(fake):
        for payload in ({"message": ""}, {"message": "   "},
                        {"message": "x" * 501}, {"message": 42},
                        {}, {"history": []}):
            resp = client.post("/api/assistant", json=payload)
            assert resp.status_code == 400, (payload, resp.status_code)
            assert resp.get_json()["error"] == "invalid_request"
    assert calls == [], "Gemini must not be called for a 400"
    with qgrab._asst_daily_lock:
        assert qgrab._asst_daily["done"] == 0
        assert qgrab._asst_daily["reserved"] == 0


def test_assistant_cap_refund_and_daily_limit():
    _reset_asst()
    client = qgrab.app.test_client()
    with qgrab._asst_daily_lock:
        qgrab._asst_daily["date"] = qgrab._sp_quota_now().date()
        qgrab._asst_daily["done"] = qgrab.ASSISTANT_DAILY_CAP - 1

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 500, "boom", None, None)

    with _patched(boom):
        resp = client.post("/api/assistant",
                           json={"message": "will this fail?"})
    assert resp.status_code == 502, resp.status_code
    assert resp.get_json()["error"] == "ai_unavailable"

    def fake(req, timeout=None):
        return _reply("Recovered.")

    with _patched(fake):
        resp = client.post("/api/assistant",
                           json={"message": "and now?"})
    assert resp.status_code == 200, \
        "the failed question must have refunded its slot"
    assert resp.get_json()["left"] == 0

    calls = []

    def fake2(req, timeout=None):
        calls.append(1)
        return _reply()

    with _patched(fake2):
        resp = client.post("/api/assistant",
                           json={"message": "one too many"})
    assert resp.status_code == 429, resp.status_code
    assert resp.get_json()["error"] == "daily_limit"
    assert calls == [], "Gemini must not be called at the cap"


def test_assistant_empty_answer_refunds():
    _reset_asst()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _FakeResponse("   ")

    with _patched(fake):
        resp = client.post("/api/assistant",
                           json={"message": "hello?"})
    assert resp.status_code == 502, resp.status_code
    with qgrab._asst_daily_lock:
        assert qgrab._asst_daily["done"] == 0
        assert qgrab._asst_daily["reserved"] == 0


def test_assistant_not_configured_without_key():
    _reset_asst()
    client = qgrab.app.test_client()
    saved = {name: os.environ.pop(name, None)
             for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2",
                          "GEMINI_API_KEY_3")}
    try:
        resp = client.post("/api/assistant",
                           json={"message": "hello?"})
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
    assert resp.status_code == 503, resp.status_code
    assert resp.get_json()["error"] == "not_configured"


# ----------------------------------------------------------------
# POST /api/support
# ----------------------------------------------------------------

def test_support_submit_stores_and_confirms():
    path = _reset_support()
    client = qgrab.app.test_client()
    resp = client.post("/api/support", json={
        "email": "visitor@example.com",
        "message": "The download button does nothing."})
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    assert body["ok"] is True
    assert body["message"] == CONFIRMATION, body["message"]
    assert qgrab.SUPPORT_CONFIRMATION == CONFIRMATION
    stored = json.loads(open(path, encoding="utf-8").read())
    assert len(stored) == 1, stored
    entry = stored[0]
    assert entry["email"] == "visitor@example.com"
    assert entry["message"] == "The download button does nothing."
    assert entry["ts"].endswith("Z") and "T" in entry["ts"], entry


def test_support_validation():
    _reset_support()
    client = qgrab.app.test_client()
    for payload in (
            {"email": "not-an-email", "message": "long enough text"},
            {"email": "a@b", "message": "long enough text"},
            {"email": "a b@c.com", "message": "long enough text"},
            {"email": "", "message": "long enough text"},
            {"email": "ok@example.com", "message": "too short"},
            {"email": "ok@example.com", "message": "x" * 2001},
            {"email": "ok@example.com"},
            {"message": "long enough text"},
            {"email": 42, "message": "long enough text"}):
        resp = client.post("/api/support", json=payload)
        assert resp.status_code == 400, (payload, resp.status_code)
        assert resp.get_json()["error"] == "invalid_request"
    # Rejections never reach the store or the rate limiter.
    assert qgrab._load_support() == []


def test_support_per_ip_limit():
    _reset_support()
    client = qgrab.app.test_client()
    for i in range(qgrab.SUPPORT_RATE_LIMIT):
        resp = client.post("/api/support", json={
            "email": f"v{i}@example.com",
            "message": f"Problem number {i} is happening."})
        assert resp.status_code == 200, (i, resp.status_code)
    resp = client.post("/api/support", json={
        "email": "v9@example.com",
        "message": "One problem too many here."})
    assert resp.status_code == 429, resp.status_code
    assert resp.get_json()["error"] == "rate_limited"
    assert len(qgrab._load_support()) == qgrab.SUPPORT_RATE_LIMIT


def test_support_store_capped_at_200():
    path = _reset_support()
    seed = [{"ts": "2026-01-01T00:00:00Z",
             "email": f"old{i}@example.com",
             "message": f"old message {i}"}
            for i in range(qgrab.MAX_STORED_SUPPORT)]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(seed, fh)
    client = qgrab.app.test_client()
    resp = client.post("/api/support", json={
        "email": "new@example.com",
        "message": "A brand new problem report."})
    assert resp.status_code == 200, resp.status_code
    stored = json.loads(open(path, encoding="utf-8").read())
    assert len(stored) == qgrab.MAX_STORED_SUPPORT == 200, len(stored)
    assert stored[-1]["email"] == "new@example.com"
    assert stored[0]["email"] == "old1@example.com"


# ----------------------------------------------------------------
# GET /api/support/inbox
# ----------------------------------------------------------------

def test_inbox_auth_matrix_and_order():
    _reset_support()
    client = qgrab.app.test_client()
    client.post("/api/support", json={
        "email": "first@example.com",
        "message": "First stored problem."})
    client.post("/api/support", json={
        "email": "second@example.com",
        "message": "Second stored problem."})
    saved = os.environ.pop("SUPPORT_INBOX_KEY", None)
    try:
        resp = client.get("/api/support/inbox",
                          headers={"X-Support-Key": "anything"})
        assert resp.status_code == 404, \
            "no key configured -> the endpoint does not exist"
        os.environ["SUPPORT_INBOX_KEY"] = "sekret"
        resp = client.get("/api/support/inbox")
        assert resp.status_code == 401, resp.status_code
        resp = client.get("/api/support/inbox",
                          headers={"X-Support-Key": "wrong"})
        assert resp.status_code == 401, resp.status_code
        resp = client.get("/api/support/inbox",
                          headers={"X-Support-Key": "sekret"})
        assert resp.status_code == 200, resp.status_code
        body = resp.get_json()
        assert body["ok"] is True and body["count"] == 2, body
        emails = [m["email"] for m in body["messages"]]
        assert emails == ["second@example.com",
                          "first@example.com"], emails
        assert body["messages"][0]["message"] == \
            "Second stored problem."
    finally:
        if saved is not None:
            os.environ["SUPPORT_INBOX_KEY"] = saved
        else:
            os.environ.pop("SUPPORT_INBOX_KEY", None)


# ----------------------------------------------------------------
# Widget markup on the main pages
# ----------------------------------------------------------------

def test_widget_markup_on_main_pages():
    client = qgrab.app.test_client()
    for path in ("/", "/youtube-video-downloader",
                 "/video-to-script-prompt"):
        html = client.get(path).get_data(as_text=True)
        for marker in ('id="asstBtn"', "🤖", ">Assistant<",
                       'id="asstPanel"', "QGrab Assistant",
                       "Ask me anything about QGrab",
                       'id="asstSupportBtn"', "Talk to Support",
                       'id="asstSupportForm"', "/api/assistant",
                       "/api/support"):
            assert marker in html, (path, marker)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
