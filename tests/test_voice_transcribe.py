"""Tests for POST /api/voice-transcribe — the AI half of the
hybrid mic (build 2026-11-18.32).

The browser's Web Speech API only hears the phone/site language;
when the visitor speaks a different one, the mic's parallel
MediaRecorder clip lands here and Gemini transcribes it in the
language actually spoken. The contract pinned here:

  200 {"text", "lang"}   — the model's JSON, parsed defensively
  400 invalid_request    — no (or empty) "audio" form field
  413 too_large          — upload over the ~2.5 MB cap
  502 ai_unavailable     — the cascade failed / reply unusable
  503 not_configured     — no Gemini key configured

_gemini_call is stubbed throughout — no network, no real keys.
The stub also pins HOW the route calls Gemini: the audio goes
as inline_data with the codecs parameter stripped from its
mime type, next to the exact transcription instruction.

Run:  .venv/bin/python tests/test_voice_transcribe.py  (or pytest)
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402


def _post_audio(client, payload=b"fake-audio-bytes",
                filename="voice.webm", content_type="audio/webm"):
    return client.post(
        "/api/voice-transcribe",
        data={"audio": (io.BytesIO(payload), filename, content_type)},
        content_type="multipart/form-data")


class _GeminiStub:
    """Context manager: swap in a fake _gemini_call + a fake key
    list, restore both afterwards (the test_site_hardening
    pattern). reply is the raw text the fake cascade returns, or
    an exception instance to raise."""

    def __init__(self, reply, keys=("test-key",)):
        self.reply = reply
        self.keys = keys
        self.seen = []

    def __enter__(self):
        self._real_call = qgrab._gemini_call
        self._real_keys = qgrab._gemini_api_keys

        def fake_call(parts, system, timeout, max_models=None,
                      slow_max_attempts=None, **kwargs):
            self.seen.append((parts, system))
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply, "fake-model"

        qgrab._gemini_call = fake_call
        qgrab._gemini_api_keys = lambda: list(self.keys)
        return self

    def __exit__(self, *exc):
        qgrab._gemini_call = self._real_call
        qgrab._gemini_api_keys = self._real_keys
        return False


def test_valid_json_reply_is_returned():
    client = qgrab.app.test_client()
    reply = json.dumps({"text": "میری ویڈیو ڈاؤن لوڈ کرو",
                        "lang": "ur-PK"})
    with _GeminiStub(reply) as stub:
        resp = _post_audio(client)
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"text": "میری ویڈیو ڈاؤن لوڈ کرو",
                               "lang": "ur-PK"}, resp.get_json()
    # The route must hand Gemini the audio inline (codecs stripped
    # from the mime type) plus the exact transcription instruction.
    parts, _system = stub.seen[0]
    assert parts[0]["inline_data"]["mime_type"] == "audio/webm", parts
    assert parts[0]["inline_data"]["data"], parts
    assert parts[1]["text"] == qgrab.VOICE_TRANSCRIBE_TEXT, parts


def test_fenced_json_reply_is_parsed():
    client = qgrab.app.test_client()
    reply = "```json\n{\"text\": \"hello world\", \"lang\": " \
            "\"en-US\"}\n```"
    with _GeminiStub(reply):
        resp = _post_audio(client)
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"text": "hello world",
                               "lang": "en-US"}, resp.get_json()


def test_no_speech_reply_passes_through_empty():
    client = qgrab.app.test_client()
    with _GeminiStub(json.dumps({"text": "", "lang": ""})):
        resp = _post_audio(client)
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"text": "", "lang": ""}, resp.get_json()


def test_model_error_is_ai_unavailable():
    client = qgrab.app.test_client()
    with _GeminiStub(qgrab._GeminiUnavailable("every pair failed")):
        resp = _post_audio(client)
    assert resp.status_code == 502, resp.status_code
    assert resp.get_json() == {"error": "ai_unavailable"}, resp.get_json()


def test_unusable_reply_is_ai_unavailable():
    client = qgrab.app.test_client()
    with _GeminiStub("sorry, I cannot help with that"):
        resp = _post_audio(client)
    assert resp.status_code == 502, resp.status_code
    assert resp.get_json() == {"error": "ai_unavailable"}, resp.get_json()


def test_missing_audio_field_is_400():
    client = qgrab.app.test_client()
    with _GeminiStub(json.dumps({"text": "x", "lang": "en-US"})):
        resp = client.post("/api/voice-transcribe",
                           data={}, content_type="multipart/form-data")
    assert resp.status_code == 400, resp.status_code
    assert resp.get_json() == {"error": "invalid_request"}, resp.get_json()


def test_empty_audio_is_400():
    client = qgrab.app.test_client()
    with _GeminiStub(json.dumps({"text": "x", "lang": "en-US"})):
        resp = _post_audio(client, payload=b"")
    assert resp.status_code == 400, resp.status_code
    assert resp.get_json() == {"error": "invalid_request"}, resp.get_json()


def test_oversize_audio_is_413():
    client = qgrab.app.test_client()
    big = b"x" * (qgrab.VOICE_MAX_AUDIO_BYTES + 1)
    with _GeminiStub(json.dumps({"text": "x", "lang": "en-US"})):
        resp = _post_audio(client, payload=big)
    assert resp.status_code == 413, resp.status_code
    assert resp.get_json() == {"error": "too_large"}, resp.get_json()


def test_no_keys_is_503():
    client = qgrab.app.test_client()
    with _GeminiStub(json.dumps({"text": "x", "lang": "en-US"}),
                     keys=()):
        resp = _post_audio(client)
    assert resp.status_code == 503, resp.status_code
    assert resp.get_json() == {"error": "not_configured"}, resp.get_json()


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
