"""Focused tests for Script+Prompt multi-key Gemini rotation.

Why: the Gemini free tier's daily quota is per Google PROJECT and
per model. The owner added two extra API keys (GEMINI_API_KEY_2 /
GEMINI_API_KEY_3, other projects) alongside GEMINI_API_KEY, so the
cascade now walks (model, key) PAIRS — models outer, keys inner:
the best model is tried on every key before moving to the next
model. The attempt policy is the cascade's existing one, extended
unchanged over pairs: fast failures (< SP_GEMINI_FAST_FAIL, the
quota signature) keep the walk going across all pairs; once any
attempt is slow, total attempts cap at SP_GEMINI_SLOW_MAX_ATTEMPTS.

urlopen is stubbed throughout — no network, no real generation.

Run:  .venv/bin/python tests/test_sp_gemini_keys.py
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
KEYS = ["key-one", "key-two", "key-three"]
KEY_ENV = ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")


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


def _pair_of(req):
    model = req.full_url.split("/models/")[1].split(":")[0]
    return model, req.get_header("X-goog-api-key")


class _patched:
    """Swap urlopen + the Gemini env for one test, restore after.

    keys: list of values for KEY_ENV in order (missing tail entries
    are unset). model_env: GEMINI_MODEL value, or None to unset."""

    def __init__(self, fake_urlopen, keys=(), model_env=None):
        self._fake = fake_urlopen
        self._keys = list(keys)
        self._model_env = model_env

    def __enter__(self):
        self._orig_urlopen = qgrab.urllib.request.urlopen
        self._orig_env = {name: os.environ.get(name)
                          for name in KEY_ENV + ("GEMINI_MODEL",)}
        for i, name in enumerate(KEY_ENV):
            if i < len(self._keys):
                os.environ[name] = self._keys[i]
            else:
                os.environ.pop(name, None)
        if self._model_env is None:
            os.environ.pop("GEMINI_MODEL", None)
        else:
            os.environ["GEMINI_MODEL"] = self._model_env
        qgrab.urllib.request.urlopen = self._fake
        return self

    def __exit__(self, *exc):
        qgrab.urllib.request.urlopen = self._orig_urlopen
        for name, value in self._orig_env.items():
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


def test_rotation_order_models_outer_keys_inner():
    """3 keys: fast 429s on (m1,k1), (m1,k2), (m1,k3) — the best
    model is exhausted across ALL keys before the cascade moves on
    — then success on (m2,k1) is returned."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_pair_of(req))
        if len(calls) < 4:
            raise urllib.error.HTTPError(
                req.full_url, 429, "quota exhausted", None, None)
        return _FakeResponse('{"script": "ok"}')

    with _patched(fake_urlopen, keys=KEYS):
        text, model = qgrab._gemini_call([{"text": "x"}], "sys", 5)
    expected = [(CHAIN[0], k) for k in KEYS] + [(CHAIN[1], KEYS[0])]
    assert calls == expected, calls
    assert text == '{"script": "ok"}', text
    assert model == CHAIN[1], model


def test_all_pairs_fast_fail_then_unavailable():
    """Every (model, key) pair failing fast walks ALL combinations
    — exactly keys x models attempts, in pair order — before
    _GeminiUnavailable."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_pair_of(req))
        raise urllib.error.HTTPError(
            req.full_url, 429, "quota exhausted", None, None)

    with _patched(fake_urlopen, keys=KEYS):
        assert _unavailable(
            lambda: qgrab._gemini_call([{"text": "x"}], "sys", 5))
    expected = [(m, k) for m in CHAIN for k in KEYS]
    assert calls == expected, (len(calls), calls[:3])
    assert len(calls) == len(KEYS) * len(CHAIN)


def test_two_slow_failures_stop_at_two_attempts():
    """Two SLOW failures stop the walk at SP_GEMINI_SLOW_MAX_ATTEMPTS
    total attempts even with 3 keys x 6 models still untried."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_pair_of(req))
        time.sleep(0.3)
        raise urllib.error.HTTPError(
            req.full_url, 429, "slow failure", None, None)

    orig_threshold = qgrab.SP_GEMINI_FAST_FAIL
    qgrab.SP_GEMINI_FAST_FAIL = 0.2
    try:
        with _patched(fake_urlopen, keys=KEYS):
            assert _unavailable(
                lambda: qgrab._gemini_call([{"text": "x"}], "sys", 5))
    finally:
        qgrab.SP_GEMINI_FAST_FAIL = orig_threshold
    assert calls == [(CHAIN[0], KEYS[0]), (CHAIN[0], KEYS[1])], calls


def test_single_key_matches_pre_change_cascade():
    """Only GEMINI_API_KEY set: the walk is exactly the old
    model-only cascade — each model once, 6 fast attempts max."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(_pair_of(req))
        raise urllib.error.HTTPError(
            req.full_url, 429, "quota exhausted", None, None)

    with _patched(fake_urlopen, keys=[KEYS[0]]):
        assert _unavailable(
            lambda: qgrab._gemini_call([{"text": "x"}], "sys", 5))
    assert calls == [(m, KEYS[0]) for m in CHAIN], calls


def test_blank_and_duplicate_extra_keys_ignored():
    """Blank values are skipped and a duplicate of an earlier key is
    dropped; order is preserved, so rotation sees each key once."""
    def fake_urlopen(req, timeout=None):  # never reached
        raise AssertionError("urlopen must not be called here")

    with _patched(fake_urlopen,
                  keys=[KEYS[0], "   ", KEYS[0]]):
        assert qgrab._gemini_api_keys() == [KEYS[0]], \
            qgrab._gemini_api_keys()
    with _patched(fake_urlopen,
                  keys=[KEYS[0], KEYS[1], KEYS[1]]):
        assert qgrab._gemini_api_keys() == KEYS[:2], \
            qgrab._gemini_api_keys()
    with _patched(fake_urlopen, keys=[]):
        assert qgrab._gemini_api_keys() == []
        assert qgrab._gemini_api_key() is None


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
