"""Focused tests for the Script+Prompt Gemini model cascade.

Why: the Gemini free tier's DAILY quota is per project AND per
model, and a night of testing exhausted the primary model's quota
— production answered ai_unavailable even though other models
still had quota left. The cascade now walks a 6-model chain
(SP_MODEL_CHAIN, env GEMINI_MODEL first when set): quota failures
come back FAST (an instant 429), so fast failures keep falling
through to the next model; SLOW failures (timeouts / long
attempts) cap the walk at the calling route's slow budget — the
bare _gemini_call fallback is 2 attempts total, while both
production routes pass a deeper budget of 6 (the text routes
since 2026-11-05; see the text-route regression tests below).

urlopen is stubbed throughout — no network, no real generation.

Run:  .venv/bin/python tests/test_sp_gemini_cascade.py
"""

import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402

CHAIN = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash",
         "gemini-3.7-flash", "gemini-3.5-flash-lite",
         "gemini-3.1-flash-lite"]


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


def _model_of(req):
    return req.full_url.split("/models/")[1].split(":")[0]


class _patched:
    """Swap urlopen + the Gemini env for one test, restore after."""

    def __init__(self, fake_urlopen, model_env=None):
        self._fake = fake_urlopen
        self._model_env = model_env

    def __enter__(self):
        self._orig_urlopen = qgrab.urllib.request.urlopen
        self._orig_key = os.environ.get("GEMINI_API_KEY")
        self._orig_model = os.environ.get("GEMINI_MODEL")
        os.environ["GEMINI_API_KEY"] = "test-key"
        if self._model_env is None:
            os.environ.pop("GEMINI_MODEL", None)
        else:
            os.environ["GEMINI_MODEL"] = self._model_env
        qgrab.urllib.request.urlopen = self._fake
        return self

    def __exit__(self, *exc):
        qgrab.urllib.request.urlopen = self._orig_urlopen
        for name, value in (("GEMINI_API_KEY", self._orig_key),
                            ("GEMINI_MODEL", self._orig_model)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        return False


def _unavailable(fn):
    try:
        fn()
    except qgrab._GeminiUnavailable:
        return True
    return False


def test_fast_failures_fall_through_to_third_model():
    """Models 1-2 fail fast (instant 429 = the quota signature);
    model 3 is tried and its success is returned."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_model_of(req))
        if len(calls) < 3:
            raise urllib.error.HTTPError(
                req.full_url, 429, "quota exhausted", None, None)
        return _FakeResponse('{"script": "ok"}')

    with _patched(fake_urlopen):
        text, model = qgrab._gemini_call([{"text": "x"}], "sys", 5)
    assert calls == CHAIN[:3], calls
    assert text == '{"script": "ok"}', text
    assert model == CHAIN[2], model


def test_fast_failures_walk_all_six_then_unavailable():
    """Every model failing fast walks the WHOLE chain in order —
    exactly 6 attempts — before _GeminiUnavailable."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_model_of(req))
        raise urllib.error.HTTPError(
            req.full_url, 429, "quota exhausted", None, None)

    with _patched(fake_urlopen):
        assert _unavailable(
            lambda: qgrab._gemini_call([{"text": "x"}], "sys", 5))
    assert calls == CHAIN, calls


def test_slow_failures_stop_at_two_attempts():
    """Two SLOW failures (each consuming >= the fast-fail
    threshold) stop the cascade at 2 attempts total, even though
    four models remain untried. Slowness is simulated with a small
    patched threshold + a real short sleep — no 20 s waits."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_model_of(req))
        time.sleep(0.3)
        raise urllib.error.HTTPError(
            req.full_url, 429, "slow failure", None, None)

    orig_threshold = qgrab.SP_GEMINI_FAST_FAIL
    qgrab.SP_GEMINI_FAST_FAIL = 0.2
    try:
        with _patched(fake_urlopen):
            assert _unavailable(
                lambda: qgrab._gemini_call([{"text": "x"}], "sys", 5))
    finally:
        qgrab.SP_GEMINI_FAST_FAIL = orig_threshold
    assert calls == CHAIN[:2], calls


def test_text_route_slow_failures_walk_six_attempts():
    """The TEXT routes carry the deeper slow budget
    (SP_TEXT_SLOW_MAX_ATTEMPTS = 6, raised 2026-11-05 from the
    inherited fallback of 2 after production Prompts jobs died on
    the first model): prompts-from-script with every attempt
    failing SLOW walks all six models before _GeminiUnavailable,
    instead of stopping at 2 attempts on the first model."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_model_of(req))
        time.sleep(0.3)
        raise urllib.error.HTTPError(
            req.full_url, 503, "slow failure", None, None)

    orig_threshold = qgrab.SP_GEMINI_FAST_FAIL
    qgrab.SP_GEMINI_FAST_FAIL = 0.2
    try:
        with _patched(fake_urlopen):
            assert _unavailable(
                lambda: qgrab._gemini_generate_prompts_from_script(
                    "SCENE 1 — a test script"))
    finally:
        qgrab.SP_GEMINI_FAST_FAIL = orig_threshold
    assert qgrab.SP_TEXT_SLOW_MAX_ATTEMPTS == 6
    assert calls == CHAIN, calls


def test_caption_route_slow_failures_walk_six_attempts():
    """Same deeper slow budget on the caption route
    (_gemini_generate_text): SLOW failures walk the whole chain
    before _GeminiUnavailable."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_model_of(req))
        time.sleep(0.3)
        raise urllib.error.HTTPError(
            req.full_url, 503, "slow failure", None, None)

    orig_threshold = qgrab.SP_GEMINI_FAST_FAIL
    qgrab.SP_GEMINI_FAST_FAIL = 0.2
    try:
        with _patched(fake_urlopen):
            assert _unavailable(
                lambda: qgrab._gemini_generate_text(
                    "00:00 hello", "A title", "en", "script"))
    finally:
        qgrab.SP_GEMINI_FAST_FAIL = orig_threshold
    assert calls == CHAIN, calls


def test_env_model_leads_chain_without_duplication():
    """GEMINI_MODEL leads the chain when set and is not repeated;
    unset, the chain is exactly SP_MODEL_CHAIN in order."""
    def fake_urlopen(req, timeout=None):  # never reached
        raise AssertionError("urlopen must not be called here")

    with _patched(fake_urlopen, model_env="gemini-3.7-flash"):
        models = qgrab._gemini_models()
    assert models[0] == "gemini-3.7-flash", models
    assert models.count("gemini-3.7-flash") == 1, models
    assert models == ["gemini-3.7-flash"] + [
        m for m in CHAIN if m != "gemini-3.7-flash"], models

    with _patched(fake_urlopen):
        assert qgrab._gemini_models() == CHAIN, qgrab._gemini_models()
        assert qgrab.SP_MODEL_CHAIN == CHAIN


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
    sys.exit(1 if failed else 0)
