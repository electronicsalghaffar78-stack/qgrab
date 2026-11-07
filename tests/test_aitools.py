"""Tests for the AI Tools feature (/api/ai-tools/generate +
/api/ai-tools/quota).

Six Gemini generators (titles, tags, hashtags, channel names,
keywords, thumbnail ideas) share ONE daily cap of 10 successful
generations on the America/Los_Angeles quota day — the same
reserve/settle mechanics as the Script+Prompt counters: a slot
is reserved before the (synchronous) cascade call and refunded
on any failure. The Gemini layer is stubbed by replacing
urllib.request.urlopen, exactly like
tests/test_sp_gemini_cascade.py — no network, no real
generation.

Covered:
  * the item parser: strict-JSON path, markdown fences, plain-
    line fallback, tags comma-line split, numbering/bullet/bold
    cleaning, hashtag normalisation, dedupe + per-tool caps,
  * prompt construction: the tool instruction + the SAME-
    language rule + the visitor's topic reach the request body,
  * endpoint contract: 200 with cleaned items and a decremented
    counter, 400 on a bad tool/input (nothing reserved), 429 at
    the cap (Gemini never called), 502 with a refund when the
    cascade fails or returns nothing usable, 503 with no key,
  * the read-only quota endpoint's shape.

Run:  .venv/bin/python tests/test_aitools.py   (or under pytest)
"""

import json
import os
import sys
import time
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")
TOOLS = ["titles", "tags", "hashtags", "channel_names",
         "keywords", "thumbnail_ideas"]


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


def _reset_state():
    with qgrab._ai_daily_lock:
        qgrab._ai_daily["date"] = None
        qgrab._ai_daily["done"] = 0
        qgrab._ai_daily["reserved"] = 0


def _quota(client):
    resp = client.get("/api/ai-tools/quota")
    assert resp.status_code == 200, resp.status_code
    return resp.get_json()


def _items_reply(items):
    return _FakeResponse(json.dumps({"items": items}))


# ----------------------------------------------------------------
# Parser
# ----------------------------------------------------------------

def test_parse_json_with_fences_and_dirty_items():
    raw = ('```json\n{"items": ["1. **Bold Title**", '
           '"2) Second One", "- Third One"]}\n```')
    out = qgrab._ai_parse_items(raw, "titles")
    assert out == ["Bold Title", "Second One", "Third One"], out


def test_parse_plain_lines_fallback():
    out = qgrab._ai_parse_items(
        "1. Alpha title\n2. Beta title\n* Gamma title", "titles")
    assert out == ["Alpha title", "Beta title", "Gamma title"], out


def test_parse_tags_comma_line_split():
    out = qgrab._ai_parse_items("cats, funny cats, pets", "tags")
    assert out == ["cats", "funny cats", "pets"], out


def test_parse_hashtags_normalised_and_deduped():
    out = qgrab._ai_parse_items(
        json.dumps({"items": ["cats", "#dogs", "Funny Cats",
                              "#CATS"]}),
        "hashtags")
    assert out == ["#cats", "#dogs", "#FunnyCats"], out


def test_parse_caps_per_tool():
    raw = json.dumps({"items": [f"Title {i}" for i in range(15)]})
    assert len(qgrab._ai_parse_items(raw, "titles")) == 10
    raw = json.dumps({"items": [f"Name {i}" for i in range(15)]})
    assert len(qgrab._ai_parse_items(raw, "channel_names")) == 12


def test_parse_thumbnail_multiline_items_kept():
    items = ["Text: BIG CATS\nColors: red on black\nLayout: cat face right",
             "Text: WOW\nColors: yellow\nLayout: split screen"]
    out = qgrab._ai_parse_items(json.dumps({"items": items}),
                                "thumbnail_ideas")
    assert out == items, out
    assert "\n" in out[0]


def test_parse_unusable_replies_are_empty():
    assert qgrab._ai_parse_items("", "titles") == []
    assert qgrab._ai_parse_items('{"items": []}', "titles") == []
    assert qgrab._ai_parse_items('{"other": 1, "more": 2}',
                                 "titles") == []


# ----------------------------------------------------------------
# Endpoint: success + prompt construction
# ----------------------------------------------------------------

def test_generate_titles_success_and_prompt():
    _reset_state()
    client = qgrab.app.test_client()
    titles = [f"Great Title {i}" for i in range(10)]

    def fake(req, timeout=None):
        return _items_reply(titles)

    with _patched(fake) as patched:
        resp = client.post("/api/ai-tools/generate",
                           json={"tool": "titles",
                                 "input": "funny cat videos"})
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    assert body["ok"] is True and body["tool"] == "titles"
    assert body["items"] == titles
    assert body["left"] == 9 and body["max"] == 10
    assert _quota(client)["left"] == 9
    # The request that reached Gemini: tool instruction + the
    # language rule in the system part, the topic in the user part.
    payload = json.loads(patched.bodies[0].decode("utf-8"))
    system = payload["system_instruction"]["parts"][0]["text"]
    assert "SAME language" in system, system
    assert "10" in system
    user = payload["contents"][0]["parts"][0]["text"]
    assert "funny cat videos" in user, user


def test_generate_all_six_tools():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _items_reply(["one", "two", "three"])

    with _patched(fake):
        for tool in TOOLS:
            resp = client.post("/api/ai-tools/generate",
                               json={"tool": tool, "input": "cats"})
            assert resp.status_code == 200, (tool, resp.status_code)
            assert resp.get_json()["tool"] == tool
    assert _quota(client)["left"] == 10 - len(TOOLS)


def test_generate_accepts_roman_urdu_topic_verbatim():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _items_reply(["x"])

    with _patched(fake) as patched:
        resp = client.post(
            "/api/ai-tools/generate",
            json={"tool": "titles",
                  "input": "gaon ki mazahiya kahani"})
    assert resp.status_code == 200
    payload = json.loads(patched.bodies[0].decode("utf-8"))
    assert "gaon ki mazahiya kahani" in \
        payload["contents"][0]["parts"][0]["text"]


# ----------------------------------------------------------------
# Endpoint: validation / limits / failures
# ----------------------------------------------------------------

def test_generate_invalid_requests_reserve_nothing():
    _reset_state()
    client = qgrab.app.test_client()
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        return _items_reply(["x"])

    with _patched(fake):
        for payload in ({"tool": "bogus", "input": "cats"},
                        {"tool": "titles", "input": ""},
                        {"tool": "titles", "input": "   "},
                        {"tool": "titles", "input": "x" * 301},
                        {"tool": "titles"},
                        {"input": "cats"},
                        {"tool": "titles", "input": 42}):
            resp = client.post("/api/ai-tools/generate", json=payload)
            assert resp.status_code == 400, (payload, resp.status_code)
            assert resp.get_json()["error"] == "invalid_request"
    assert calls == [], "Gemini must not be called for a 400"
    assert _quota(client)["left"] == 10


def test_generate_daily_limit_never_calls_gemini():
    _reset_state()
    with qgrab._ai_daily_lock:
        qgrab._ai_daily["date"] = qgrab._sp_quota_now().date()
        qgrab._ai_daily["done"] = qgrab.AI_TOOLS_DAILY_CAP
    client = qgrab.app.test_client()
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        return _items_reply(["x"])

    with _patched(fake):
        resp = client.post("/api/ai-tools/generate",
                           json={"tool": "tags", "input": "cats"})
    assert resp.status_code == 429, resp.status_code
    assert resp.get_json()["error"] == "daily_limit"
    assert calls == []
    assert _quota(client)["left"] == 0


def test_generate_cascade_failure_refunds():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 500, "boom", None, None)

    with _patched(fake):
        resp = client.post("/api/ai-tools/generate",
                           json={"tool": "keywords", "input": "cats"})
    assert resp.status_code == 502, resp.status_code
    assert resp.get_json()["error"] == "ai_unavailable"
    assert _quota(client)["left"] == 10, "failure must refund the slot"


def test_generate_empty_items_refunds():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        return _items_reply([])

    with _patched(fake):
        resp = client.post("/api/ai-tools/generate",
                           json={"tool": "tags", "input": "cats"})
    assert resp.status_code == 502, resp.status_code
    assert _quota(client)["left"] == 10


def test_generate_not_configured_without_key():
    _reset_state()
    client = qgrab.app.test_client()
    saved = {name: os.environ.pop(name, None)
             for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2",
                          "GEMINI_API_KEY_3")}
    try:
        resp = client.post("/api/ai-tools/generate",
                           json={"tool": "titles", "input": "cats"})
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
    assert resp.status_code == 503, resp.status_code
    assert resp.get_json()["error"] == "not_configured"
    assert _quota(client)["left"] == 10


# ----------------------------------------------------------------
# Quota endpoint
# ----------------------------------------------------------------

def test_quota_endpoint_shape_and_reset_time():
    _reset_state()
    client = qgrab.app.test_client()
    body = _quota(client)
    assert body["left"] == qgrab.AI_TOOLS_DAILY_CAP == 10
    assert body["max"] == 10
    resets_at = body["resets_at"]
    now = time.time()
    assert isinstance(resets_at, int)
    assert 0 < resets_at - now <= 24 * 3600 + 120, resets_at - now
    reset_local = datetime.fromtimestamp(resets_at, PACIFIC)
    assert (reset_local.hour, reset_local.minute,
            reset_local.second) == (0, 0, 0), reset_local
    # Reading the quota counted nothing.
    assert _quota(client)["left"] == 10


def test_quota_rollover_on_pacific_date_change():
    _reset_state()
    with qgrab._ai_daily_lock:
        from datetime import timedelta
        qgrab._ai_daily["date"] = \
            qgrab._sp_quota_now().date() - timedelta(days=1)
        qgrab._ai_daily["done"] = 10
    client = qgrab.app.test_client()
    assert _quota(client)["left"] == 10, "a new Pacific day refills"


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
