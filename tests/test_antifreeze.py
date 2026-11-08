"""Tests for the 2026-11-08.13 anti-freeze release.

The site froze three times on 2026-11-08 with no crash and no
log error: one gunicorn worker, 8 threads, and /download holding
a thread for the whole job (streaming proxy) or for minutes
(merged/MP3: yt-dlp + ffmpeg inside the request). Eight busy
downloads left no thread for /healthz, so the site looked dead.

Pinned here:
  * the download-slot gate exists with the shipped limits;
  * when every slot is taken, /download answers an honest 503
    with Retry-After instead of queueing forever;
  * /healthz answers 200 even while every download slot is held
    (the exact property whose absence froze the site);
  * the Dockerfile carries the gunicorn hardening flags
    (--worker-tmp-dir /dev/shm, --max-requests).

Run:  .venv/bin/python tests/test_antifreeze.py   (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_slot_gate_limits():
    assert qgrab._HEAVY_DOWNLOAD_LIMIT == 3
    assert qgrab._HEAVY_SLOT_WAIT > 0


def test_download_503_when_slots_full_and_healthz_still_ok():
    client = qgrab.app.test_client()
    old_wait = qgrab._HEAVY_SLOT_WAIT
    qgrab._HEAVY_SLOT_WAIT = 0  # fail fast inside the test
    held = []
    try:
        for _ in range(qgrab._HEAVY_DOWNLOAD_LIMIT):
            assert qgrab._heavy_download_slots.acquire(blocking=False)
            held.append(True)
        resp = client.get(
            "/download",
            query_string={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "format_id": "mp3",
            })
        assert resp.status_code == 503, resp.status_code
        assert resp.headers.get("Retry-After") == "60"
        # The property that was missing on freeze day: the health
        # endpoint must still answer while downloads are saturated.
        health = client.get("/healthz")
        assert health.status_code == 200, health.status_code
        assert health.get_json() == {"ok": True}
    finally:
        qgrab._HEAVY_SLOT_WAIT = old_wait
        for _ in held:
            qgrab._heavy_download_slots.release()


def test_dockerfile_gunicorn_hardening():
    with open(os.path.join(ROOT, "deploy", "Dockerfile")) as fh:
        dockerfile = fh.read()
    assert "--worker-tmp-dir /dev/shm" in dockerfile
    assert "--max-requests 250" in dockerfile
    assert "--max-requests-jitter 50" in dockerfile


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print("test_antifreeze: all passed")
