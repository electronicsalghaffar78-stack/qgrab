"""Tests for the Script+Prompt DAILY COUNTERS (owner's order,
mirroring the clip counters on his video tool).

Two server-enforced counters — Scripts and Prompts — each capped
at 10 successful generations per day and counting DOWN. The day
is the Google quota day: midnight in America/Los_Angeles. A slot
is reserved when a job starts; a success counts it, a failure
REFUNDS it. GET /api/script-prompt/quota reports the left counts,
the caps, and "resets_at" (the next Pacific midnight as a UTC
epoch) so the page can show the refresh time in the visitor's own
local time.

Covered here (the Gemini/source layer is stubbed to a fast fake):
  * quota endpoint math on a fresh day + a sane resets_at,
  * a successful job decrements its mode's visible left count,
    an in-flight reservation already counts against it,
  * a failed job refunds (left count unchanged after the error),
  * POST at the cap -> 429 {"error": "daily_limit"}, NO job
    created, and the other mode is unaffected,
  * the Pacific-date rollover resets both counters.

Run:  .venv/bin/python tests/test_sp_quota.py   (or under pytest)
"""

import os
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402

URL = "https://youtu.be/ktiJ9GSuPfY"
PACIFIC = ZoneInfo("America/Los_Angeles")
FAKE_PAYLOAD = {
    "title": "Fake Title",
    "lang": None,
    "mode": "script",
    "route": "captions",
    "script": "FAKE SCRIPT TEXT",
    "prompts": [],
    "truncated": False,
    "partial": False,
    "model": "fake-model",
}


def _reset_state():
    with qgrab._sp_jobs_lock:
        qgrab._sp_jobs.clear()
    with qgrab._sp_lock:
        qgrab._sp_hits.clear()
    with qgrab._sp_daily_lock:
        qgrab._sp_daily["date"] = None
        qgrab._sp_daily["done"] = {"script": 0, "prompts": 0}
        qgrab._sp_daily["reserved"] = {"script": 0, "prompts": 0}


def _quota(client):
    resp = client.get("/api/script-prompt/quota")
    assert resp.status_code == 200, resp.status_code
    return resp.get_json()


def _poll_until_settled(client, job_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/script-prompt/status?id={job_id}")
        assert resp.status_code == 200, resp.status_code
        body = resp.get_json()
        if body.get("status") in ("done", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not settle in time")


def _run_one_job(client, mode):
    resp = client.post("/api/script-prompt",
                       json={"url": URL, "mode": mode})
    assert resp.status_code == 202, resp.status_code
    return _poll_until_settled(client, resp.get_json()["job_id"])


def test_quota_endpoint_fresh_and_reset_time():
    _reset_state()
    client = qgrab.app.test_client()
    body = _quota(client)
    assert body["script_left"] == qgrab.SP_DAILY_CAP_SCRIPT == 10
    assert body["prompts_left"] == qgrab.SP_DAILY_CAP_PROMPTS == 10
    assert body["script_max"] == 10
    assert body["prompts_max"] == 10
    # resets_at: a real epoch, in the future, at most a day away,
    # and exactly a Pacific midnight.
    resets_at = body["resets_at"]
    now = time.time()
    assert isinstance(resets_at, int)
    assert 0 < resets_at - now <= 24 * 3600 + 120, resets_at - now
    reset_local = datetime.fromtimestamp(resets_at, PACIFIC)
    assert (reset_local.hour, reset_local.minute,
            reset_local.second) == (0, 0, 0), reset_local
    # Reading the quota created nothing and counted nothing.
    assert len(qgrab._sp_jobs) == 0
    assert _quota(client)["script_left"] == 10


def test_successful_jobs_decrement():
    _reset_state()

    def fake_generate(data, url, mode, requested):
        payload = dict(FAKE_PAYLOAD)
        payload["mode"] = mode
        return payload, 200

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        final = _run_one_job(client, "script")
        assert final["status"] == "done"
        body = _quota(client)
        assert body["script_left"] == 9, body
        assert body["prompts_left"] == 10, body
        final = _run_one_job(client, "prompts")
        assert final["status"] == "done"
        body = _quota(client)
        assert body["script_left"] == 9, body
        assert body["prompts_left"] == 9, body
    finally:
        qgrab._sp_generate_payload = original


def test_inflight_reservation_counts_then_settles():
    _reset_state()
    gate = threading.Event()

    def blocking_generate(data, url, mode, requested):
        gate.wait(10)
        return dict(FAKE_PAYLOAD), 200

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = blocking_generate
    try:
        client = qgrab.app.test_client()
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "script"})
        assert resp.status_code == 202, resp.status_code
        job_id = resp.get_json()["job_id"]
        # While the job runs, its reserved slot already shows as
        # used — simultaneous visitors cannot overshoot the cap.
        assert _quota(client)["script_left"] == 9
        gate.set()
        final = _poll_until_settled(client, job_id)
        assert final["status"] == "done"
        # After success the slot stays counted (now as a success).
        assert _quota(client)["script_left"] == 9
    finally:
        gate.set()
        qgrab._sp_generate_payload = original


def test_failed_job_refunds():
    _reset_state()

    def fake_generate(data, url, mode, requested):
        return {"error": "no_speech"}, 422

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        final = _run_one_job(client, "script")
        assert final["status"] == "error"
        assert final["error"] == "no_speech"
        # The reservation was refunded: the day is whole again.
        body = _quota(client)
        assert body["script_left"] == 10, body
        assert body["prompts_left"] == 10, body
    finally:
        qgrab._sp_generate_payload = original


def test_daily_limit_at_cap():
    _reset_state()

    def fake_generate(data, url, mode, requested):
        payload = dict(FAKE_PAYLOAD)
        payload["mode"] = mode
        return payload, 200

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        # Fill the script day: successes alone reach the cap.
        with qgrab._sp_daily_lock:
            qgrab._sp_quota_rollover_locked()
            qgrab._sp_daily["done"]["script"] = \
                qgrab.SP_DAILY_CAP_SCRIPT
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "script"})
        assert resp.status_code == 429, resp.status_code
        assert resp.get_json() == {"error": "daily_limit"}
        assert len(qgrab._sp_jobs) == 0
        # In-flight reservations count towards the cap too.
        with qgrab._sp_daily_lock:
            qgrab._sp_daily["done"]["script"] = \
                qgrab.SP_DAILY_CAP_SCRIPT - 1
            qgrab._sp_daily["reserved"]["script"] = 1
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "script"})
        assert resp.status_code == 429, resp.status_code
        assert resp.get_json() == {"error": "daily_limit"}
        assert len(qgrab._sp_jobs) == 0
        # The other mode's day is untouched and still runs.
        final = _run_one_job(client, "prompts")
        assert final["status"] == "done"
        assert _quota(client)["prompts_left"] == 9
    finally:
        qgrab._sp_generate_payload = original


def test_rollover_resets_counts():
    _reset_state()
    client = qgrab.app.test_client()
    with qgrab._sp_daily_lock:
        qgrab._sp_quota_rollover_locked()
        qgrab._sp_daily["done"]["script"] = 4
        qgrab._sp_daily["done"]["prompts"] = 5
    body = _quota(client)
    assert body["script_left"] == 6, body
    assert body["prompts_left"] == 5, body
    # Jump the quota clock two Pacific days ahead: both counters
    # reset to a fresh day.
    real_now = qgrab._sp_quota_now
    qgrab._sp_quota_now = lambda: real_now() + timedelta(days=2)
    try:
        body = _quota(client)
        assert body["script_left"] == 10, body
        assert body["prompts_left"] == 10, body
        with qgrab._sp_daily_lock:
            assert qgrab._sp_daily["done"] == \
                {"script": 0, "prompts": 0}
    finally:
        qgrab._sp_quota_now = real_now


if __name__ == "__main__":
    test_quota_endpoint_fresh_and_reset_time()
    print("PASS quota endpoint: fresh-day math + sane resets_at")
    test_successful_jobs_decrement()
    print("PASS successful jobs decrement their mode's counter")
    test_inflight_reservation_counts_then_settles()
    print("PASS in-flight reservation counts, then settles")
    test_failed_job_refunds()
    print("PASS failed job refunds its slot")
    test_daily_limit_at_cap()
    print("PASS cap -> 429 daily_limit, no job, other mode fine")
    test_rollover_resets_counts()
    print("PASS Pacific-date rollover resets both counters")
    print("ALL SP QUOTA TESTS PASS")
