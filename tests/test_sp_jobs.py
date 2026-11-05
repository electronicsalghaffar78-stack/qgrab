"""Tests for the Script+Prompt BACKGROUND JOBS flow (v3).

The synchronous endpoint used to hang the visitor's page for the
whole generation (measured: ~105 s for prompts on a 60 s video);
on a flaky phone connection the response was lost and the wait
was for nothing. POST /api/script-prompt now runs only the cheap
synchronous pre-checks, starts the unchanged generation logic on
a thread, and answers 202 {"job_id", "status": "running"}; the
outcome is polled from GET /api/script-prompt/status.

Covered here (the Gemini/source layer is stubbed to a fast fake):
  * POST -> 202 + job_id; status polls -> done with the payload,
  * a stubbed generation failure -> status error with the same
    code + http the synchronous flow would have produced,
  * unknown / expired job id -> 404 {"error": "job_not_found"},
  * the synchronous pre-checks still fire WITHOUT creating a job
    (invalid_url 400, not_configured 503, rate_limited 429),
  * the rate limit is counted once, at POST time,
  * every I18N key the SP script references is actually shipped
    by _js_strings() and rendered (toast-string regression),
  * homepage + tool page still render (en + ur),
  * the rendered inline scripts pass node --check.

Run:  .venv/bin/python tests/test_sp_jobs.py   (or under pytest)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402

URL = "https://youtu.be/ktiJ9GSuPfY"
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


def test_job_lifecycle_done():
    _reset_state()
    seen = {}

    def fake_generate(data, url, mode, requested):
        seen.update(data=data, url=url, mode=mode,
                    requested=requested)
        return dict(FAKE_PAYLOAD), 200

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "script"})
        assert resp.status_code == 202, resp.status_code
        body = resp.get_json()
        assert body.get("status") == "running"
        job_id = body.get("job_id")
        assert job_id
        final = _poll_until_settled(client, job_id)
        assert final["status"] == "done"
        for key, value in FAKE_PAYLOAD.items():
            assert final[key] == value, (key, final.get(key))
        assert seen["url"] == URL and seen["mode"] == "script"
        # Counted exactly once, at POST time.
        hits = qgrab._sp_hits.get("127.0.0.1", [])
        assert len(hits) == 1, hits
    finally:
        qgrab._sp_generate_payload = original


def test_job_lifecycle_error():
    _reset_state()

    def fake_generate(data, url, mode, requested):
        return {"error": "no_speech"}, 422

    original = qgrab._sp_generate_payload
    qgrab._sp_generate_payload = fake_generate
    try:
        client = qgrab.app.test_client()
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "prompts"})
        assert resp.status_code == 202, resp.status_code
        final = _poll_until_settled(
            client, resp.get_json()["job_id"])
        assert final["status"] == "error"
        assert final["error"] == "no_speech"
        assert final["http"] == 422
    finally:
        qgrab._sp_generate_payload = original


def test_unknown_and_expired_job():
    _reset_state()
    client = qgrab.app.test_client()
    resp = client.get("/api/script-prompt/status?id=nope")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "job_not_found"}
    # An expired job is pruned by the lazy janitor -> also 404.
    job_id = qgrab._sp_job_create()
    with qgrab._sp_jobs_lock:
        qgrab._sp_jobs[job_id]["created"] = \
            time.time() - qgrab.SP_JOB_TTL_SECONDS - 1
    resp = client.get(f"/api/script-prompt/status?id={job_id}")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "job_not_found"}


def test_sync_prechecks_create_no_job():
    _reset_state()
    client = qgrab.app.test_client()
    # invalid_url -> 400, synchronously, and no job is created.
    resp = client.post("/api/script-prompt",
                       json={"url": "not a url", "mode": "script"})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "invalid_url"}
    assert len(qgrab._sp_jobs) == 0
    # not_configured -> 503.
    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        resp = client.post("/api/script-prompt",
                           json={"url": URL, "mode": "script"})
        assert resp.status_code == 503
        assert resp.get_json() == {"error": "not_configured"}
        assert len(qgrab._sp_jobs) == 0
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved
    # rate_limited -> 429.
    with qgrab._sp_lock:
        qgrab._sp_hits["127.0.0.1"] = \
            [time.time()] * qgrab.SP_RATE_LIMIT
    resp = client.post("/api/script-prompt",
                       json={"url": URL, "mode": "script"})
    assert resp.status_code == 429
    assert resp.get_json() == {"error": "rate_limited"}
    assert len(qgrab._sp_jobs) == 0
    _reset_state()


def test_sp_i18n_keys_reach_the_page():
    """Regression (2026-11-05): the SP toast never appeared live
    because _spjs.html reads I18N.sp_wait_note but _js_strings()
    never shipped the key, so spShowToast() silently returned.
    The JS suite could not catch it — it stubs I18N by hand, WITH
    the key. Pin the real flow instead: every I18N.<key> the SP
    script references must be present in _js_strings() output,
    and the rendered pages must carry a non-empty sp_wait_note."""
    import json
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    spjs = os.path.join(here, "..", "templates", "_spjs.html")
    with open(spjs, encoding="utf-8") as fh:
        referenced = set(re.findall(r"I18N\.([A-Za-z_]+)", fh.read()))
    assert "sp_wait_note" in referenced  # the toast's string
    for lang in ("en", "ur"):
        shipped = qgrab._js_strings(qgrab.i18n.get_strings(lang))
        missing = referenced - set(shipped)
        assert not missing, (lang, sorted(missing))
        assert shipped["sp_wait_note"].strip(), lang
    client = qgrab.app.test_client()
    for path in ("/", "/?lang=ur", "/video-to-script-prompt",
                 "/video-to-script-prompt?lang=ur"):
        html = client.get(path).get_data(as_text=True)
        m = re.search(r"const I18N = (\{.*?\});", html, re.S)
        assert m, path
        page_i18n = json.loads(m.group(1))
        assert page_i18n.get("sp_wait_note", "").strip(), path
    print("  sp I18N keys shipped + rendered sp_wait_note OK")


def test_pages_render_and_scripts_parse():
    client = qgrab.app.test_client()
    node = shutil.which("node")
    checked = 0
    for path in ("/", "/?lang=ur", "/video-to-script-prompt",
                 "/video-to-script-prompt?lang=ur"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        if node:
            html = resp.get_data(as_text=True)
            import re
            blocks = re.findall(
                r"<script>(.*?)</script>", html, re.S)
            for block in blocks:
                with tempfile.NamedTemporaryFile(
                        "w", suffix=".js", delete=False) as fh:
                    fh.write(block)
                    name = fh.name
                try:
                    proc = subprocess.run(
                        [node, "--check", name],
                        capture_output=True, text=True)
                    assert proc.returncode == 0, (
                        path, proc.stderr[:400])
                    checked += 1
                finally:
                    os.unlink(name)
    print(f"  rendered-script node --check blocks OK: {checked}")


if __name__ == "__main__":
    test_job_lifecycle_done()
    print("PASS job lifecycle -> done")
    test_job_lifecycle_error()
    print("PASS job lifecycle -> error")
    test_unknown_and_expired_job()
    print("PASS unknown/expired job -> 404")
    test_sync_prechecks_create_no_job()
    print("PASS sync pre-checks (400/503/429, no job created)")
    test_sp_i18n_keys_reach_the_page()
    print("PASS sp I18N keys reach the page (toast regression)")
    test_pages_render_and_scripts_parse()
    print("PASS pages render (en+ur) + scripts parse")
    print("ALL SP JOB TESTS PASS")
