"""Tests for the Ant Ling speed build (2026-11-17, release
2026-11-17.28).

Every AI text generation now tries Ant Ling FIRST (Ling-3.1-flash
for chat, Ming-3.0-asr-tiny for transcription) and falls back to
the Gemini cascade. Both providers are stubbed by replacing
urllib.request.urlopen — no network, no real generation, no real
keys (the env values below are dummies read at call time).

Covered:
  * _antling_chat: OpenAI-shaped request, reasoning disabled
    ("thinking": {"type": "disabled"} — the hidden reasoning
    pass measured 5,251 of 5,871 tokens / 58 s when left on),
    the reply text is returned;
  * _ai_text_call: Ant Ling preferred when configured (the
    Gemini URL is never hit), Gemini fallback when Ant Ling
    fails, inline_data parts (audio/image) go straight to
    Gemini, and with no Ant Ling key the Gemini cascade is used
    exactly as before;
  * _antling_transcribe_file: multipart shape + the transcript
    text is returned;
  * _antling_generate_audio: ASR transcript -> script JSON via
    the transcript route, and the {"error": "no_speech"} answer
    when the audio holds no speech;
  * endpoint gates: with ONLY an Ant Ling key configured (no
    Gemini key at all) the AI Tools and Assistant endpoints
    answer 200 instead of 503 not_configured.

Run:  .venv/bin/python tests/test_antling_speed.py  (or pytest)
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GEMINI_API_KEY_2", None)
os.environ.pop("GEMINI_API_KEY_3", None)
os.environ["ANT_LING_API_KEY"] = "test-ant-key"

import app as qgrab  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _gemini_payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _antling_payload(text):
    return {"choices": [{"message": {"content": text}}]}


class _router:
    """A urlopen stub that routes by URL: Ant Ling chat /
    transcription handlers and a Gemini handler, each a callable
    taking the request and returning a _FakeResponse (or raising).
    Records (url, body) for every call."""

    def __init__(self, ant_chat=None, ant_asr=None, gemini=None):
        self.ant_chat = ant_chat
        self.ant_asr = ant_asr
        self.gemini = gemini
        self.calls = []

    def __enter__(self):
        self._orig = qgrab.urllib.request.urlopen
        router = self

        def fake(req, timeout=None):
            url = req.full_url
            router.calls.append((url, req.data))
            if "api.ant-ling.com" in url:
                if url.endswith("/audio/transcriptions"):
                    assert router.ant_asr is not None, "ASR not stubbed"
                    return router.ant_asr(req)
                assert router.ant_chat is not None, "chat not stubbed"
                return router.ant_chat(req)
            assert router.gemini is not None, "gemini not stubbed"
            return router.gemini(req)

        qgrab.urllib.request.urlopen = fake
        return self

    def __exit__(self, *exc):
        qgrab.urllib.request.urlopen = self._orig
        return False

    def urls(self):
        return [u for u, _ in self.calls]


def test_antling_chat_shape_and_reply():
    seen = {}

    def ant_chat(req):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResponse(_antling_payload('{"items": ["a", "b"]}'))

    with _router(ant_chat=ant_chat) as r:
        raw, model = qgrab._antling_chat("SYS", "USER")
    assert raw == '{"items": ["a", "b"]}', raw
    assert model == "Ling-3.1-flash", model
    assert seen["body"]["model"] == "Ling-3.1-flash", seen["body"]
    assert seen["body"]["thinking"] == {"type": "disabled"}, seen["body"]
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"}], seen["body"]
    assert seen["auth"] == "Bearer test-ant-key", seen["auth"]
    assert r.urls() and "api.ant-ling.com" in r.urls()[0]


def test_ai_text_call_prefers_antling():
    def ant_chat(req):
        return _FakeResponse(_antling_payload("ANT ANSWER"))

    def gemini(req):  # must never be reached
        raise AssertionError("gemini must not be called")

    with _router(ant_chat=ant_chat, gemini=gemini):
        raw, model = qgrab._ai_text_call(
            [{"text": "hello"}], "SYS", 15, thinking_budget=0)
    assert raw == "ANT ANSWER", raw
    assert model == "Ling-3.1-flash", model


def test_ai_text_call_falls_back_to_gemini():
    os.environ["GEMINI_API_KEY"] = "test-gemini-key"
    def ant_chat(req):
        raise qgrab.urllib.error.HTTPError(
            req.full_url, 500, "boom", None, None)

    def gemini(req):
        return _FakeResponse(_gemini_payload("GEMINI ANSWER"))

    try:
        with _router(ant_chat=ant_chat, gemini=gemini) as r:
            raw, model = qgrab._ai_text_call(
                [{"text": "hello"}], "SYS", 15, thinking_budget=0)
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    assert raw == "GEMINI ANSWER", raw
    assert any("generativelanguage" in u for u in r.urls()), r.urls()


def test_ai_text_call_inline_data_goes_straight_to_gemini():
    os.environ["GEMINI_API_KEY"] = "test-gemini-key"
    def ant_chat(req):  # must never be reached
        raise AssertionError("ant ling must not be called")

    def gemini(req):
        return _FakeResponse(_gemini_payload("GEMINI AUDIO ANSWER"))

    parts = [{"inline_data": {"mime_type": "audio/mp3", "data": "AA=="}},
             {"text": "transcribe this"}]
    try:
        with _router(ant_chat=ant_chat, gemini=gemini):
            raw, _model = qgrab._ai_text_call(parts, "SYS", 15)
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    assert raw == "GEMINI AUDIO ANSWER", raw


def test_antling_transcribe_file():
    seen = {}

    def ant_asr(req):
        seen["body"] = req.data
        seen["ctype"] = req.headers.get("Content-type")
        return _FakeResponse({"text": "  hello world transcript  "})

    path = os.path.join(os.path.dirname(__file__), "_tmp_asr.mp3")
    with open(path, "wb") as fh:
        fh.write(b"fake mp3 bytes")
    try:
        with _router(ant_asr=ant_asr):
            text = qgrab._antling_transcribe_file(path)
    finally:
        os.unlink(path)
    assert text == "hello world transcript", text
    assert b"Ming-3.0-asr-tiny" in seen["body"], seen["body"][:200]
    assert b"fake mp3 bytes" in seen["body"]
    assert "multipart/form-data" in seen["ctype"], seen["ctype"]


def test_antling_generate_audio_script_and_no_speech():
    def ant_asr(req):
        return _FakeResponse({"text": "some spoken words"})

    def ant_chat(req):
        return _FakeResponse(_antling_payload(
            '{"script": "SCENE 1 (0:00-0:05) — Test\\n'
            'NARRATOR: some spoken words"}'))

    path = os.path.join(os.path.dirname(__file__), "_tmp_audio.mp3")
    with open(path, "wb") as fh:
        fh.write(b"fake mp3 bytes")
    try:
        with _router(ant_chat=ant_chat, ant_asr=ant_asr):
            raw, _model = qgrab._antling_generate_audio(
                path, "Title", "script")
        script, _p, partial, no_speech = qgrab._sp_parse_output(raw)
        assert "some spoken words" in script, script
        assert not no_speech

        def ant_asr_empty(req):
            return _FakeResponse({"text": "   "})

        with _router(ant_chat=ant_chat, ant_asr=ant_asr_empty):
            raw, _model = qgrab._antling_generate_audio(
                path, "Title", "script")
        _s, _p, _partial, no_speech = qgrab._sp_parse_output(raw)
        assert no_speech, raw
    finally:
        os.unlink(path)


def test_endpoints_work_with_only_antling_key():
    def ant_chat(req):
        body = json.loads(req.data.decode("utf-8"))
        system = body["messages"][0]["content"]
        if "title writer" in system:
            return _FakeResponse(_antling_payload(json.dumps(
                {"items": [f"Title {i}" for i in range(10)]})))
        return _FakeResponse(_antling_payload(json.dumps(
            {"answer": "Paste the link and press Download.",
             "goto": "download", "support": False})))

    client = qgrab.app.test_client()
    with _router(ant_chat=ant_chat):
        resp = client.post("/api/ai-tools/generate", json={
            "tool": "titles", "input": "funny cats antling test"})
        assert resp.status_code == 200, resp.status_code
        assert len(resp.get_json()["items"]) == 10, resp.get_json()

        resp = client.post("/api/assistant", json={
            "message": "How do I download a TikTok video?"})
        assert resp.status_code == 200, resp.status_code
        data = resp.get_json()
        assert data["answer"].startswith("Paste the link"), data
        assert data["goto"] == "download", data


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
