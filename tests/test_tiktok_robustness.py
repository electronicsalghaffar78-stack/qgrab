"""Tests for the TikTok robustness pass (2026-11-04).

Two defects, both proven live against
https://vm.tiktok.com/ZN8yVuSDP/ — a post TikTok was refusing
unauthenticated extraction for ("No video formats found", oEmbed
answering "ratelimit triggered") while a control link extracted
fine:

1. extract_info() gave up after a single cascade pass for
   non-YouTube platforms. Platforms refuse in bursts, so a failed
   first pass now earns ONE retry of the primary attempt after a
   4 s pause — failures only; a successful extraction never pays
   the pause, and YouTube keeps its Invidious fallback instead.
   For TikTok's "No video formats found" refusal specifically,
   the app/API endpoint variants (one attempt per api_hostname
   extractor argument) are tried after the standard pass and
   before that paused retry.

2. The Script+Prompt tool reported that same refusal as
   no_subtitles ("this video has no subtitles") — a lie about the
   video. A video that cannot be fetched at all now ends in the
   distinct fetch_failed error; no_subtitles is reserved for a
   video that WAS read and has neither usable captions nor any
   audio track. A fetch_failed job refunds its daily-counter
   reservation like every other job error.

The Gemini layer is never reached in the SP tests (the source
layer fails first); yt_dlp is stubbed throughout.

Run:  .venv/bin/python tests/test_tiktok_robustness.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402
import yt_dlp  # noqa: E402

DownloadError = yt_dlp.utils.DownloadError

GOOD_INFO = {
    "title": "Some video",
    "formats": [{
        "format_id": "1",
        "url": "https://cdn.example/v.mp4",
        "vcodec": "avc1",
        "acodec": "mp4a",
    }],
}

TIKTOK_URL = "https://vm.tiktok.com/ZN8yVuSDP/"
OTHER_URL = "https://example.com/watch/1"
YOUTUBE_URL = "https://youtu.be/ktiJ9GSuPfY"


class _ScriptedYDL:
    """yt_dlp.YoutubeDL stand-in driven by a script of outcomes:
    an exception instance is raised, anything else is returned as
    the extracted info. Calls are counted and every call's opts
    recorded (so tests can see which attempt — and which TikTok
    api_hostname — each call carried)."""

    script = []
    calls = 0
    opts_seen = []

    def __init__(self, opts):
        self.opts = opts
        _ScriptedYDL.opts_seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        _ScriptedYDL.calls += 1
        outcome = _ScriptedYDL.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _clear_winners():
    with qgrab._winner_lock:
        qgrab._winner_cache.clear()
    # The extraction cache (site-hardening round) would otherwise
    # serve a previous test's success to the next scripted run.
    qgrab._info_cache_clear()


class _SleepRecorder:
    """Patches time.sleep just long enough to record the pauses
    extract_info takes (restored on exit, even on failure)."""

    def __enter__(self):
        self.calls = []
        self._real = qgrab.time.sleep
        qgrab.time.sleep = self.calls.append
        return self.calls

    def __exit__(self, *exc):
        qgrab.time.sleep = self._real
        return False


def _run_extract(url, script):
    _clear_winners()
    _ScriptedYDL.script = list(script)
    _ScriptedYDL.calls = 0
    _ScriptedYDL.opts_seen = []
    real_ydl = qgrab.yt_dlp.YoutubeDL
    qgrab.yt_dlp.YoutubeDL = _ScriptedYDL
    try:
        with _SleepRecorder() as sleeps:
            try:
                return qgrab.extract_info(url), sleeps
            except Exception as e:
                return e, sleeps
    finally:
        qgrab.yt_dlp.YoutubeDL = real_ydl
        _clear_winners()


def _api_hostname_of(opts):
    args = (opts or {}).get("extractor_args") or {}
    hosts = (args.get("tiktok") or {}).get("api_hostname")
    return hosts[0] if hosts else None


def test_tiktok_first_pass_fails_retry_succeeds():
    # A refusal that is NOT the "No video formats found" class:
    # the app-endpoint gate stays shut and the paused retry of the
    # primary attempt is what saves the extraction.
    refusal = DownloadError("Unable to download API page")
    result, sleeps = _run_extract(
        TIKTOK_URL, [refusal, refusal, GOOD_INFO])
    assert result is GOOD_INFO, result
    # Two first-pass attempts (impersonate + plain), ONE retry.
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    assert sleeps == [4], sleeps
    # No call carried a TikTok api_hostname.
    assert all(_api_hostname_of(o) is None
               for o in _ScriptedYDL.opts_seen)


def test_tiktok_no_formats_reaches_api_endpoints_first():
    refusal = DownloadError("No video formats found!")
    result, sleeps = _run_extract(
        TIKTOK_URL, [refusal, refusal, GOOD_INFO])
    assert result is GOOD_INFO, result
    # The app-endpoint attempt succeeded BEFORE the paused retry:
    # no pause was paid at all.
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    assert sleeps == [], sleeps
    assert _api_hostname_of(_ScriptedYDL.opts_seen[0]) is None
    assert _api_hostname_of(_ScriptedYDL.opts_seen[1]) is None
    assert _api_hostname_of(_ScriptedYDL.opts_seen[2]) == \
        "api22-normal-c-useast1a.tiktokv.com"


def test_tiktok_no_formats_on_any_attempt_opens_api_gate():
    # The refusal seen by an EARLIER attempt still counts: the
    # pass's last error here is an unrelated webpage failure, yet
    # the app-endpoint attempts must run (this exact mix — one
    # attempt refused, another dying on the network — is what the
    # live probe produced).
    script = [DownloadError("No video formats found!"),
              DownloadError("Unable to download webpage"),
              GOOD_INFO]
    result, sleeps = _run_extract(TIKTOK_URL, script)
    assert result is GOOD_INFO, result
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    assert sleeps == [], sleeps
    assert _api_hostname_of(_ScriptedYDL.opts_seen[2]) == \
        "api22-normal-c-useast1a.tiktokv.com"


def test_tiktok_api_endpoints_in_order_then_paused_retry():
    refusal = DownloadError("No video formats found!")
    result, sleeps = _run_extract(
        TIKTOK_URL, [refusal] * 4 + [GOOD_INFO])
    assert result is GOOD_INFO, result
    # Standard pass (2) + api22 + api16 + the paused primary retry.
    assert _ScriptedYDL.calls == 5, _ScriptedYDL.calls
    hosts = [_api_hostname_of(o) for o in _ScriptedYDL.opts_seen]
    assert hosts == [None, None,
                     "api22-normal-c-useast1a.tiktokv.com",
                     "api16-normal-c-useast1a.tiktokv.com",
                     None], hosts
    assert sleeps == [4], sleeps


def test_other_platform_retry_and_give_up():
    blocked = DownloadError(
        "Unable to download webpage: HTTP Error 403: Forbidden")
    result, sleeps = _run_extract(
        OTHER_URL, [blocked, blocked, GOOD_INFO])
    assert result is GOOD_INFO, result
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    assert sleeps == [4], sleeps
    # And when the retry also fails, the error surfaces — after
    # exactly one pause and one retried attempt, no more.
    result, sleeps = _run_extract(
        OTHER_URL, [blocked, blocked, blocked])
    assert isinstance(result, DownloadError), result
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    assert sleeps == [4], sleeps


def test_successful_extraction_never_pauses():
    result, sleeps = _run_extract(TIKTOK_URL, [GOOD_INFO])
    assert result is GOOD_INFO, result
    assert _ScriptedYDL.calls == 1, _ScriptedYDL.calls
    assert sleeps == [], sleeps


def test_youtube_keeps_invidious_no_paused_retry():
    plan_len = len(qgrab._attempt_plan(YOUTUBE_URL))
    bot_wall = DownloadError("Sign in to confirm you're not a bot")
    real_fallback = qgrab._extract_info_invidious
    qgrab._extract_info_invidious = lambda url: GOOD_INFO
    try:
        result, sleeps = _run_extract(
            YOUTUBE_URL, [bot_wall] * plan_len)
    finally:
        qgrab._extract_info_invidious = real_fallback
    assert result is GOOD_INFO, result
    assert _ScriptedYDL.calls == plan_len, _ScriptedYDL.calls
    assert sleeps == [], sleeps


# --- Script+Prompt: fetch_failed vs no_subtitles -------------------

def _audio_fail(url, expected_duration=None, source_info=None):
    raise qgrab._SpAudioFailed("every attempt failed")


def _with_sp_stubs(extract_stub, fn):
    real_extract = qgrab.extract_info
    real_audio = qgrab._sp_download_audio_mp3
    qgrab.extract_info = extract_stub
    qgrab._sp_download_audio_mp3 = _audio_fail
    try:
        return fn()
    finally:
        qgrab.extract_info = real_extract
        qgrab._sp_download_audio_mp3 = real_audio


def _payload(url):
    return qgrab._sp_generate_payload({}, url, "script", "")


def test_sp_extraction_failure_is_fetch_failed():
    def raising_extract(url):
        raise DownloadError("No video formats found!")

    payload, http = _with_sp_stubs(
        raising_extract, lambda: _payload(TIKTOK_URL))
    assert http == 422, http
    assert payload == {"error": "fetch_failed"}, payload
    assert payload["error"] != "no_subtitles"


def test_sp_no_subtitles_only_when_video_read_without_audio():
    silent_info = {
        "title": "Silent video",
        "duration": 30,
        "formats": [{
            "format_id": "v720",
            "url": "https://cdn.example/v.mp4",
            "vcodec": "avc1",
            "acodec": "none",
            "height": 720,
        }],
    }
    payload, http = _with_sp_stubs(
        lambda url: silent_info, lambda: _payload(OTHER_URL))
    assert (payload, http) == ({"error": "no_subtitles"}, 422), \
        (payload, http)
    # Same video WITH an audio track the cascade could not pull:
    # the video was read and HAS audio — a fetch problem, never a
    # no_subtitles property of the video.
    audible_info = dict(silent_info)
    audible_info["formats"] = [{
        "format_id": "v720",
        "url": "https://cdn.example/v.mp4",
        "vcodec": "avc1",
        "acodec": "mp4a",
        "height": 720,
    }]
    payload, http = _with_sp_stubs(
        lambda url: audible_info, lambda: _payload(OTHER_URL))
    assert (payload, http) == ({"error": "fetch_failed"}, 422), \
        (payload, http)


def _reset_sp_state():
    with qgrab._sp_jobs_lock:
        qgrab._sp_jobs.clear()
    with qgrab._sp_lock:
        qgrab._sp_hits.clear()
    with qgrab._sp_daily_lock:
        qgrab._sp_daily["date"] = None
        qgrab._sp_daily["done"] = {"script": 0, "prompts": 0}
        qgrab._sp_daily["reserved"] = {"script": 0, "prompts": 0}


def test_sp_fetch_failed_job_status_and_refund():
    _reset_sp_state()

    def raising_extract(url):
        raise DownloadError("No video formats found!")

    def run():
        client = qgrab.app.test_client()
        resp = client.post("/api/script-prompt",
                           json={"url": TIKTOK_URL,
                                 "mode": "script"})
        assert resp.status_code == 202, resp.status_code
        job_id = resp.get_json()["job_id"]
        deadline = time.time() + 10.0
        final = None
        while time.time() < deadline:
            body = client.get(
                f"/api/script-prompt/status?id={job_id}").get_json()
            if body.get("status") in ("done", "error"):
                final = body
                break
            time.sleep(0.05)
        assert final is not None, "job did not settle in time"
        assert final["status"] == "error", final
        assert final["error"] == "fetch_failed", final
        assert final["http"] == 422, final
        # The daily-counter reservation was refunded in full.
        quota = client.get("/api/script-prompt/quota").get_json()
        assert quota["script_left"] == \
            qgrab.SP_DAILY_CAP_SCRIPT, quota
        assert quota["prompts_left"] == \
            qgrab.SP_DAILY_CAP_PROMPTS, quota

    _with_sp_stubs(raising_extract, run)
    _reset_sp_state()


if __name__ == "__main__":
    test_tiktok_first_pass_fails_retry_succeeds()
    print("PASS tiktok: first pass fails -> one paused retry -> info")
    test_tiktok_no_formats_reaches_api_endpoints_first()
    print("PASS tiktok: 'no formats' -> app-endpoint attempt "
          "succeeds before the retry (no pause)")
    test_tiktok_no_formats_on_any_attempt_opens_api_gate()
    print("PASS tiktok: 'no formats' on ANY attempt opens the "
          "app-endpoint gate")
    test_tiktok_api_endpoints_in_order_then_paused_retry()
    print("PASS tiktok: api22 then api16 tried, then the paused "
          "primary retry")
    test_other_platform_retry_and_give_up()
    print("PASS other platform: same single retry; error surfaces")
    test_successful_extraction_never_pauses()
    print("PASS success path: no pause, no second pass")
    test_youtube_keeps_invidious_no_paused_retry()
    print("PASS youtube: Invidious fallback, no paused retry")
    test_sp_extraction_failure_is_fetch_failed()
    print("PASS sp: extraction failure -> fetch_failed (not "
          "no_subtitles)")
    test_sp_no_subtitles_only_when_video_read_without_audio()
    print("PASS sp: read + no captions + no audio -> no_subtitles; "
          "read + audio track -> fetch_failed")
    test_sp_fetch_failed_job_status_and_refund()
    print("PASS sp: fetch_failed via status endpoint + quota "
          "refunded")
    print("ALL TIKTOK ROBUSTNESS TESTS PASS")
