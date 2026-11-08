"""Tests for the AI thumbnail IMAGE endpoint
(POST /api/ai-tools/thumbnail-image).

The Thumbnail Idea Generator's companion: from a topic it
creates ONE real thumbnail image. Generation chain:
  1. Gemini's image model (gemini-2.5-flash-image) through the
     existing key rotation — the image comes back as an
     inlineData part of the generateContent response;
  2. the free Pollinations image API as fallback.
Both transports are stubbed by replacing urllib.request.urlopen
(exactly like tests/test_aitools.py) — no network, no real
generation. The endpoint draws on the SAME shared AI daily cap
as the text tools: a slot is reserved on POST and refunded on
any failure.

Covered:
  * the prompt builder: 16:9 composition + the explicit
    no-text instruction + the topic, always English,
  * Gemini success: the data URL is returned, the counter
    decrements, and the request that reached the API carries
    the image model + the image response modality,
  * Gemini failure -> Pollinations success (image bytes pass
    through with their content type),
  * both failing -> 502 with the slot refunded,
  * an oversized Gemini image is rejected and the chain moves
    on to Pollinations; an oversized Pollinations image -> 502,
  * 400 on bad input (nothing reserved, no transport call),
    429 at the cap (no transport call), 503 with no key.

Run:  .venv/bin/python tests/test_thumbnail_image.py
(or under pytest)
"""

import base64
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402

# A 1x1 transparent PNG — small, valid, definitely an image.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
TINY_JPG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" + b"\xff\xd9"


class _GeminiImageResp:
    """A generateContent response carrying one inlineData
    image part, in the documented response shape."""

    def __init__(self, raw, mime="image/png"):
        self._body = json.dumps({
            "candidates": [{"content": {"parts": [
                {"text": "Here is your thumbnail."},
                {"inlineData": {
                    "mimeType": mime,
                    "data": base64.b64encode(raw).decode("ascii"),
                }},
            ]}}],
        }).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self._body


class _ImageResp:
    """A raw image-bytes response (the Pollinations shape)."""

    def __init__(self, raw, ctype="image/jpeg"):
        self._body = raw
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        if args and isinstance(args[0], int):
            return self._body[:args[0]]
        return self._body


class _patched:
    """Swap urlopen for one test, restore after. Records the
    request URLs and bodies it was called with."""

    def __init__(self, fake_urlopen):
        self._fake = fake_urlopen
        self.urls = []
        self.bodies = []

    def __enter__(self):
        outer = self
        self._orig_urlopen = qgrab.urllib.request.urlopen

        def recording(req, timeout=None):
            outer.urls.append(req.full_url)
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


def _left(client):
    resp = client.get("/api/ai-tools/quota")
    assert resp.status_code == 200, resp.status_code
    return resp.get_json()["left"]


def _is_gemini(req):
    return "generativelanguage" in req.full_url


def _is_pollinations(req):
    return "pollinations" in req.full_url


# ----------------------------------------------------------------
# Prompt builder
# ----------------------------------------------------------------

def test_prompt_builder_shape():
    prompt = qgrab._ai_thumbnail_prompt("funny cat videos")
    assert "funny cat videos" in prompt
    assert "16:9" in prompt, prompt
    assert "NO text" in prompt, prompt
    for banned in ("no letters", "no numbers", "no watermarks"):
        assert banned in prompt, (banned, prompt)


# ----------------------------------------------------------------
# Endpoint: Gemini success
# ----------------------------------------------------------------

def test_gemini_success_returns_data_url():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        assert _is_gemini(req), req.full_url
        return _GeminiImageResp(TINY_PNG)

    with _patched(fake) as patched:
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "funny cat videos"})
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    assert body["ok"] is True
    expect = "data:image/png;base64," + \
        base64.b64encode(TINY_PNG).decode("ascii")
    assert body["image"] == expect, body["image"][:60]
    assert body["left"] == 9 and body["max"] == 10
    assert _left(client) == 9
    # The request that reached the API: the image model in the
    # URL, the image response modality + the built prompt (with
    # its 16:9 / no-text instructions) in the body.
    assert "gemini-2.5-flash-image" in patched.urls[0], patched.urls
    payload = json.loads(patched.bodies[0].decode("utf-8"))
    assert "IMAGE" in \
        payload["generationConfig"]["responseModalities"]
    sent = payload["contents"][0]["parts"][0]["text"]
    assert "funny cat videos" in sent and "16:9" in sent
    assert "NO text" in sent


# ----------------------------------------------------------------
# Endpoint: fallback chain
# ----------------------------------------------------------------

def test_gemini_failure_falls_back_to_pollinations():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        if _is_gemini(req):
            raise urllib.error.HTTPError(
                req.full_url, 500, "boom", None, None)
        assert _is_pollinations(req), req.full_url
        return _ImageResp(TINY_JPG, "image/jpeg")

    with _patched(fake) as patched:
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "gaon ki kahani"})
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    expect = "data:image/jpeg;base64," + \
        base64.b64encode(TINY_JPG).decode("ascii")
    assert body["image"] == expect
    assert body["left"] == 9
    # Both legs were walked, Gemini first.
    assert "generativelanguage" in patched.urls[0], patched.urls
    assert any("pollinations" in u for u in patched.urls)
    # The Pollinations URL carries the encoded prompt + the
    # 16:9 size + nologo.
    poll_url = [u for u in patched.urls if "pollinations" in u][0]
    assert "width=1280" in poll_url and "height=720" in poll_url
    assert "nologo=true" in poll_url


def test_both_failing_refunds_the_slot():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 503, "down", None, None)

    with _patched(fake):
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    assert resp.status_code == 502, resp.status_code
    assert resp.get_json()["error"] == "ai_unavailable"
    assert _left(client) == 10, "failure must refund the slot"


def test_oversized_gemini_image_moves_to_pollinations():
    _reset_state()
    client = qgrab.app.test_client()
    big = b"\x89PNG" + b"x" * (qgrab.AI_THUMB_IMAGE_MAX_BYTES + 10)

    def fake(req, timeout=None):
        if _is_gemini(req):
            return _GeminiImageResp(big)
        return _ImageResp(TINY_JPG, "image/jpeg")

    with _patched(fake):
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json()["image"].startswith("data:image/jpeg")


def test_oversized_pollinations_image_is_502():
    _reset_state()
    client = qgrab.app.test_client()
    big = b"\xff\xd8" + b"x" * (qgrab.AI_THUMB_IMAGE_MAX_BYTES + 10)

    def fake(req, timeout=None):
        if _is_gemini(req):
            raise urllib.error.HTTPError(
                req.full_url, 500, "boom", None, None)
        return _ImageResp(big, "image/jpeg")

    with _patched(fake):
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    assert resp.status_code == 502, resp.status_code
    assert _left(client) == 10


def test_gemini_non_image_content_type_rejected():
    _reset_state()
    client = qgrab.app.test_client()

    def fake(req, timeout=None):
        if _is_gemini(req):
            raise urllib.error.HTTPError(
                req.full_url, 500, "boom", None, None)
        return _ImageResp(b"<html>nope</html>", "text/html")

    with _patched(fake):
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    assert resp.status_code == 502, resp.status_code
    assert _left(client) == 10


# ----------------------------------------------------------------
# Endpoint: validation / limits / configuration
# ----------------------------------------------------------------

def test_invalid_requests_reserve_nothing():
    _reset_state()
    client = qgrab.app.test_client()
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        return _GeminiImageResp(TINY_PNG)

    with _patched(fake):
        for payload in ({"input": ""}, {"input": "   "},
                        {"input": "x" * 301}, {"input": 42}, {}):
            resp = client.post("/api/ai-tools/thumbnail-image",
                               json=payload)
            assert resp.status_code == 400, (payload,
                                             resp.status_code)
            assert resp.get_json()["error"] == "invalid_request"
    assert calls == [], "no transport may be called for a 400"
    assert _left(client) == 10


def test_daily_limit_never_calls_out():
    _reset_state()
    with qgrab._ai_daily_lock:
        qgrab._ai_daily["date"] = qgrab._sp_quota_now().date()
        qgrab._ai_daily["done"] = qgrab.AI_TOOLS_DAILY_CAP
    client = qgrab.app.test_client()
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        return _GeminiImageResp(TINY_PNG)

    with _patched(fake):
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    assert resp.status_code == 429, resp.status_code
    assert resp.get_json()["error"] == "daily_limit"
    assert calls == []
    assert _left(client) == 0


def test_not_configured_without_key():
    _reset_state()
    client = qgrab.app.test_client()
    saved = {name: os.environ.pop(name, None)
             for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2",
                          "GEMINI_API_KEY_3")}
    try:
        resp = client.post("/api/ai-tools/thumbnail-image",
                           json={"input": "cats"})
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
    assert resp.status_code == 503, resp.status_code
    assert resp.get_json()["error"] == "not_configured"
    assert _left(client) == 10


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
