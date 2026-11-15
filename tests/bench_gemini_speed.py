"""Local speed benchmark for the 2026-11-16 SP/AI speed pass.

No real Gemini key exists in this environment, so the Gemini
HTTP call is STUBBED (urllib.request.urlopen replaced): the
stub records the timeout it was handed and answers on a fixed
schedule. What this honestly measures:
  * the per-attempt timeout the cascade now passes (was 100 s
    for the Script+Prompt text route in the pre-build code,
    40 s now) and the resulting worst-case slow-failure bound
    (slow budget x timeout);
  * a typical mixed path (one slow failure, then a success) —
    expected to be unchanged, proving the fast path was not
    slowed down;
  * the new result caches: a repeated AI Tools generation and
    a repeated Script+Prompt POST, timed against the stubbed
    first call.

Run:  .venv/bin/python tests/bench_gemini_speed.py
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = os.path.join(os.path.dirname(__file__), ".test-data-bench")
os.makedirs(_TMP, exist_ok=True)
os.environ["QGRAB_DATA_DIR"] = _TMP
os.environ["GEMINI_API_KEY"] = "bench-key-not-real"

import app as A  # noqa: E402

TIMEOUTS_SEEN = []


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


GOOD = {"candidates": [{"content": {"parts": [
    {"text": json.dumps({"items": ["x"]})}]}}]}


def stub(mode):
    state = {"n": 0}

    def _open(req, timeout=None):
        TIMEOUTS_SEEN.append(timeout)
        state["n"] += 1
        if mode == "mixed" and state["n"] == 1:
            time.sleep(2.0)  # one slow failure (under any timeout)
            raise TimeoutError("simulated slow pair")
        time.sleep(0.4)
        return _Resp(GOOD)
    return _open


orig = urllib.request.urlopen

print("== cascade: mixed path (1 slow fail, then success) ==")
urllib.request.urlopen = stub("mixed")
t0 = time.monotonic()
try:
    A._gemini_call([{"text": "hi"}], "sys", A.SP_GEMINI_TIMEOUT,
                   slow_max_attempts=A.SP_TEXT_SLOW_MAX_ATTEMPTS,
                   thinking_budget=0)
    print(f"  wall time: {time.monotonic() - t0:.2f}s "
          f"(stub schedule: 2.0 slow + 0.4 success = 2.4s expected)")
except Exception as e:
    print("  FAILED:", e)
print(f"  timeout handed to urlopen (SP text route): "
      f"{TIMEOUTS_SEEN[-1]}s  (pre-build code: 100s)")
print(f"  worst-case slow bound, text route: "
      f"{A.SP_TEXT_SLOW_MAX_ATTEMPTS} attempts x "
      f"{A.SP_GEMINI_TIMEOUT}s = "
      f"{A.SP_TEXT_SLOW_MAX_ATTEMPTS * A.SP_GEMINI_TIMEOUT}s "
      f"(pre-build: 6 x 100 = 600s)")

print("== AI tools: first call vs cached repeat ==")
urllib.request.urlopen = stub("good")
client = A.app.test_client()
t0 = time.monotonic()
r1 = client.post("/api/ai-tools/generate",
                 json={"tool": "titles", "input": "bench topic"})
t1 = time.monotonic() - t0
t0 = time.monotonic()
r2 = client.post("/api/ai-tools/generate",
                 json={"tool": "titles", "input": "bench topic"})
t2 = time.monotonic() - t0
print(f"  first:  {t1:.3f}s status={r1.status_code}")
print(f"  repeat: {t2:.3f}s status={r2.status_code} "
      f"cached={r2.get_json().get('cached')}")

print("== Script+Prompt POST: cached result short-circuit ==")
key = A._sp_cache_key("https://youtu.be/bench", "script", "", {})
A._sp_cache_put(key, {"ok": True, "mode": "script",
                      "script": "BENCH", "title": "Bench"})
t0 = time.monotonic()
r = client.post("/api/script-prompt",
                json={"url": "https://youtu.be/bench",
                      "mode": "script"})
dt = time.monotonic() - t0
job = r.get_json()["job_id"]
st = client.get(f"/api/script-prompt/status?id={job}").get_json()
print(f"  POST+status wall: {dt:.3f}s -> job status={st['status']} "
      f"(no Gemini call, no quota slot)")

urllib.request.urlopen = orig
print("bench done")
