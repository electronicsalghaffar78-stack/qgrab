"""Tests for the Script+Prompt usage counters.

ROUND 3 (2026-11-16, owner's order): ALL daily limits were
removed. The counters that used to cap Scripts/Prompts at 10
successful generations per day now only COUNT — the homepage
usage card shows the counts, and nothing ever blocks. This
file previously pinned the cap (429 daily_limit at 10, slots
counting down); it now pins the opposite:

  * quota endpoint shape on a fresh day: {script_used,
    prompts_used, unlimited: true, resets_at} with resets_at
    the next Pacific midnight as a UTC epoch,
  * a successful job increments its mode's used count; a
    failed job counts nothing,
  * jobs keep running well past the old cap of 10,
  * the Pacific-date rollover resets both counters.

Run:  .venv/bin/python tests/test_sp_quota.py   (or under pytest)
"""

import os
import sys
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
    qgrab._sp_cache_clear()
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


def _run_one_job(client, mode, url=URL):
    resp = client.post("/api/script-prompt",
                       json={"url": url, "mode": mode})
    assert resp.status_code == 202, resp.status_code
    return _poll_until_settled(client, resp.get_json()["job_id"])


def test_quota_endpoint_fresh_and_reset_time():
    _reset_state()
    client = qgrab.app.test_client()
    body = _quota(client)
    assert body["script_used"] == 0
    assert body["prompts_used"] == 0
    assert body["unlimited"] is True
    assert "script_left" not in body and "script_max" not in body
    resets_at = body["resets_at"]
    now = time.time()
    assert isinstance(resets_at, int)
    assert 0 < resets_at - now <= 24 * 3600 + 120, resets_at - now
    reset_local = datetime.fromtimestamp(resets_at, PACIFIC)
    assert (reset_local.hour, reset_local.minute,
            reset_local.second) == (0, 0, 0), reset_local
    assert len(qgrab._sp_jobs) == 0
    assert _quota(client)["script_used"] == 0


def test_successful_jobs_count_up():
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
        assert body["script_used"] == 1, body
        assert body["prompts_used"] == 0, body
        final = _run_one_job(client, "prompts")
        assert final["status"] == "done"
        body = _quota(client)
        assert body["script_used"] == 1, body
        assert body["prompts_used"] == 1, body
    finally:
        qgrab._sp_generate_payload = original


def test_failed_job_counts_nothing():
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
        body = _quota(client)
        assert body["script_used"] == 0, body
        assert body["prompts_used"] == 0, body
    finally:
        qgrab._sp_generate_payload = original


def test_no_cap_beyond_the_old_limit():
    _reset_state()

    def fake_generate(data, url, mode, requested):
        payload = dict(FAKE_PAYLOAD)
        payload["mode"] = mode
        return payload, 200

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        # A day already past the old cap of 10: jobs still run.
        with qgrab._sp_daily_lock:
            qgrab._sp_quota_rollover_locked()
            qgrab._sp_daily["done"]["script"] = 10
        final = _run_one_job(client, "script")
        assert final["status"] == "done"
        assert _quota(client)["script_used"] == 11
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
    assert body["script_used"] == 4, body
    assert body["prompts_used"] == 5, body
    real_now = qgrab._sp_quota_now
    qgrab._sp_quota_now = lambda: real_now() + timedelta(days=2)
    try:
        body = _quota(client)
        assert body["script_used"] == 0, body
        assert body["prompts_used"] == 0, body
        with qgrab._sp_daily_lock:
            assert qgrab._sp_daily["done"] == \
                {"script": 0, "prompts": 0}
    finally:
        qgrab._sp_quota_now = real_now


if __name__ == "__main__":
    test_quota_endpoint_fresh_and_reset_time()
    print("PASS quota endpoint: counts shape + sane resets_at")
    test_successful_jobs_count_up()
    print("PASS successful jobs count up per mode")
    test_failed_job_counts_nothing()
    print("PASS failed job counts nothing")
    test_no_cap_beyond_the_old_limit()
    print("PASS no cap: jobs run past the old limit of 10")
    test_rollover_resets_counts()
    print("PASS Pacific rollover resets both counters")
