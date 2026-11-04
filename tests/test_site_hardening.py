"""Tests for the whole-site hardening round (2026-11-04).

One new backend or fix per platform, all behind extract_info's
existing cascade (research notes: tiktok-fetch-methods-research):

  A. TikTok — when the whole yt-dlp cascade fails, the tikwm.com
     resolver is asked; its answer is shaped into the same info
     dict (hdplay top row, watermarked row, music audio row,
     "_qgrab_source": "tikwm") so /download proxies the signed
     CDN URLs like any yt-dlp URL. The SP audio route then takes
     the audio from the tikwm MP4 (the video's OWN audio) —
     never from the music field.
  B. SP audio route — the converted MP3 is normalised to
     16 kHz mono; audio over 10 minutes is transcribed in
     <=10-minute chunks through the key x model rotation and
     stitched in order; and the diagnosed 214 s failure (one
     slow timeout + the shared 2-attempt slow cap exhausting
     the rotation) is fixed with a deeper audio slow budget.
  C. YouTube — the client cascade is default -> android_vr ->
     tv_downgraded -> web (Invidious still last).
  D. Instagram — public embed-page fallback ("gql_data" blob).
  E. Facebook — video/embed fallback with the crawler UA.
  F. X — a syndication-API yt-dlp attempt, then FxTwitter.
  G. extract_info cache — 10-minute TTL, successes only,
     single-flight: a second call within the TTL extracts
     nothing new, and failures are never cached.

yt_dlp and every third-backend HTTP call are stubbed; ffmpeg and
ffprobe run for real on generated fixtures. NO live Gemini
calls: the Gemini transport (urlopen / _gemini_call) is stubbed.

Run:  .venv/bin/python tests/test_site_hardening.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.pop("GEMINI_MODEL", None)

import app as qgrab  # noqa: E402
import yt_dlp  # noqa: E402

DownloadError = yt_dlp.utils.DownloadError
FFMPEG = shutil.which("ffmpeg")

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
IG_URL = "https://www.instagram.com/reel/ABC123/"
FB_URL = "https://www.facebook.com/watch/?v=1234567890"
X_URL = "https://x.com/someuser/status/1234567890123"

NO_FORMATS = DownloadError("No video formats found!")
WEBPAGE_FAIL = DownloadError("Unable to download webpage")


# --- shared yt-dlp stub (same shape as test_tiktok_robustness) -----

class _ScriptedYDL:
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


def _reset_caches():
    with qgrab._winner_lock:
        qgrab._winner_cache.clear()
    qgrab._info_cache_clear()


class _SleepRecorder:
    def __enter__(self):
        self.calls = []
        self._real = qgrab.time.sleep
        qgrab.time.sleep = self.calls.append
        return self.calls

    def __exit__(self, *exc):
        qgrab.time.sleep = self._real
        return False


def _run_extract(url, script):
    """extract_info with a scripted YoutubeDL; returns the info
    or the raised exception."""
    _reset_caches()
    _ScriptedYDL.script = list(script)
    _ScriptedYDL.calls = 0
    _ScriptedYDL.opts_seen = []
    real_ydl = qgrab.yt_dlp.YoutubeDL
    qgrab.yt_dlp.YoutubeDL = _ScriptedYDL
    try:
        with _SleepRecorder():
            try:
                return qgrab.extract_info(url)
            except Exception as e:
                return e
    finally:
        qgrab.yt_dlp.YoutubeDL = real_ydl
        _reset_caches()


def _stub_http_json(payload):
    """Patch _http_get_json to answer payload; returns a recorder
    of the URLs it was asked for."""
    asked = []

    def fake(url, timeout=20):
        asked.append(url)
        if isinstance(payload, Exception):
            raise payload
        return payload

    real = qgrab._http_get_json
    qgrab._http_get_json = fake
    return asked, real


def _unstub_http_json(real):
    qgrab._http_get_json = real


# --- C: YouTube client rotation -------------------------------------

def test_youtube_client_rotation_order():
    plan = qgrab._attempt_plan(YOUTUBE_URL)
    clients = [spec.get("client") for spec in plan]
    assert clients == [None, "android_vr", "tv_downgraded", "web"], \
        clients


# --- G: extraction cache ----------------------------------------------

def test_cache_second_call_extracts_nothing():
    result = _run_extract(OTHER_URL, [GOOD_INFO])
    assert result is GOOD_INFO, result
    # _run_extract reset the caches, so run the pair manually:
    _reset_caches()
    _ScriptedYDL.script = [GOOD_INFO]
    _ScriptedYDL.calls = 0
    real_ydl = qgrab.yt_dlp.YoutubeDL
    qgrab.yt_dlp.YoutubeDL = _ScriptedYDL
    try:
        first = qgrab.extract_info(OTHER_URL)
        second = qgrab.extract_info(OTHER_URL)
        # Same video, cosmetically different URL (tracking junk,
        # fragment, host case): still the cached extraction.
        third = qgrab.extract_info(
            "https://EXAMPLE.com/watch/1?utm_source=share#t=3")
    finally:
        qgrab.yt_dlp.YoutubeDL = real_ydl
        _reset_caches()
    assert first is GOOD_INFO and second is GOOD_INFO
    assert third is GOOD_INFO
    assert _ScriptedYDL.calls == 1, _ScriptedYDL.calls


def test_cache_failures_are_not_cached():
    result = _run_extract(OTHER_URL, [WEBPAGE_FAIL] * 3)
    assert isinstance(result, DownloadError), result
    assert _ScriptedYDL.calls == 3, _ScriptedYDL.calls
    # The failure left nothing behind: a fresh call extracts
    # again — and succeeds on the first attempt this time.
    _reset_caches()
    _ScriptedYDL.script = [WEBPAGE_FAIL] * 3 + [GOOD_INFO]
    _ScriptedYDL.calls = 0
    real_ydl = qgrab.yt_dlp.YoutubeDL
    qgrab.yt_dlp.YoutubeDL = _ScriptedYDL
    try:
        with _SleepRecorder():
            try:
                qgrab.extract_info(OTHER_URL)
            except DownloadError:
                pass
            again = qgrab.extract_info(OTHER_URL)
    finally:
        qgrab.yt_dlp.YoutubeDL = real_ydl
        _reset_caches()
    assert again is GOOD_INFO, again
    assert _ScriptedYDL.calls == 4, _ScriptedYDL.calls


class _SlowYDL:
    calls = 0
    lock = threading.Lock()

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        with _SlowYDL.lock:
            _SlowYDL.calls += 1
        time.sleep(0.3)
        return GOOD_INFO


def test_cache_single_flight():
    _reset_caches()
    _SlowYDL.calls = 0
    real_ydl = qgrab.yt_dlp.YoutubeDL
    qgrab.yt_dlp.YoutubeDL = _SlowYDL
    results = []
    try:
        threads = [threading.Thread(
            target=lambda: results.append(
                qgrab.extract_info(OTHER_URL)))
            for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        qgrab.yt_dlp.YoutubeDL = real_ydl
        _reset_caches()
    assert results == [GOOD_INFO, GOOD_INFO], results
    assert _SlowYDL.calls == 1, _SlowYDL.calls


# --- A: tikwm ---------------------------------------------------------

TIKWM_PAYLOAD = {
    "code": 0,
    "msg": "success",
    "data": {
        "id": "7702859124844809486",
        "title": "A story video",
        "cover": "https://cdn.example/cover.jpg",
        "duration": 105,
        "play": "https://cdn.example/play.mp4",
        "wmplay": "https://cdn.example/wm.mp4",
        "hdplay": "https://cdn.example/hd.mp4",
        "size": 9000000,
        "wm_size": 9100000,
        "hd_size": 12000000,
        "music": "https://cdn.example/song.mp3",
        "author": {"unique_id": "someuser", "nickname": "Some User"},
    },
}


def test_tikwm_fallback_shapes_info():
    asked, real = _stub_http_json(TIKWM_PAYLOAD)
    try:
        # Standard pass (2) + app-endpoint attempts (2) + paused
        # retry (1) all refuse; tikwm answers.
        result = _run_extract(TIKTOK_URL, [NO_FORMATS] * 5)
    finally:
        _unstub_http_json(real)
    assert isinstance(result, dict), result
    assert result["_qgrab_source"] == "tikwm", result
    assert result["title"] == "A story video"
    assert result["duration"] == 105
    assert result["uploader"] == "Some User"
    assert _ScriptedYDL.calls == 5, _ScriptedYDL.calls
    assert len(asked) == 1 and "tikwm.com/api/" in asked[0] \
        and "hd=1" in asked[0], asked
    rows = qgrab.pick_formats(result)
    labels = [r["label"] for r in rows]
    assert labels[0] == "HD", labels           # hdplay is the top row
    assert "watermarked" in labels, labels
    assert any(r["kind"] == "audio" for r in rows), rows


def test_tikwm_failure_surfaces_original_error():
    asked, real = _stub_http_json(
        {"code": -1, "msg": "Url parsing is failed!"})
    try:
        result = _run_extract(TIKTOK_URL, [NO_FORMATS] * 5)
    finally:
        _unstub_http_json(real)
    assert isinstance(result, DownloadError), result
    # The visitor's story stays the yt-dlp refusal, not tikwm's.
    assert "No video formats found" in str(result), result
    assert "tikwm" not in str(result), result


def _make_media(path, seconds, video=False, sample_rate=44100):
    args = [FFMPEG, "-y", "-v", "error"]
    if video:
        args += ["-f", "lavfi", "-i", "color=c=black:s=64x64:r=1"]
    args += ["-f", "lavfi", "-i",
             f"sine=frequency=440:sample_rate={sample_rate}",
             "-t", str(seconds)]
    if video:
        args += ["-codec:v", "libx264", "-pix_fmt", "yuv420p",
                 "-codec:a", "aac", "-shortest"]
    args.append(path)
    subprocess.run(args, check=True)


def _probe_stream(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-of", "json", path],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)["streams"][0]


def test_sp_audio_via_tikwm_stream_not_music():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        fixture = os.path.join(d, "video.mp4")
        _make_media(fixture, 105, video=True)
        info = qgrab._shape_tikwm_info(TIKWM_PAYLOAD["data"],
                                       TIKTOK_URL)
        fetched = []

        def fake_fetch(media_url, dest, timeout=120):
            fetched.append(media_url)
            shutil.copyfile(fixture, dest)

        real_fetch = qgrab._fetch_to_file
        qgrab._fetch_to_file = fake_fetch
        try:
            mp3, tmpdir = qgrab._sp_download_audio_mp3(
                TIKTOK_URL, expected_duration=105,
                source_info=info)
        finally:
            qgrab._fetch_to_file = real_fetch
        try:
            # The HD stream (the video's own audio) — never music.
            assert fetched == ["https://cdn.example/hd.mp4"], \
                fetched
            got = qgrab._sp_probe_duration(mp3)
            assert got is not None and abs(got - 105) < 3, got
            # ... normalised to the ASR shape on the way.
            stream = _probe_stream(mp3)
            assert stream["sample_rate"] == "16000", stream
            assert stream["channels"] == 1, stream
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sp_audio_tikwm_duration_guard_rejects_wrong_track():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        fixture = os.path.join(d, "short.mp4")
        _make_media(fixture, 60, video=True)  # not the 105 s video
        info = qgrab._shape_tikwm_info(TIKWM_PAYLOAD["data"],
                                       TIKTOK_URL)
        fetched = []

        def fake_fetch(media_url, dest, timeout=120):
            fetched.append(media_url)
            shutil.copyfile(fixture, dest)

        real_fetch = qgrab._fetch_to_file
        real_attempts = qgrab._ordered_attempts
        qgrab._fetch_to_file = fake_fetch
        qgrab._ordered_attempts = lambda url: []
        try:
            try:
                qgrab._sp_download_audio_mp3(
                    TIKTOK_URL, expected_duration=105,
                    source_info=info)
            except qgrab._SpAudioFailed:
                pass
            else:
                raise AssertionError("expected _SpAudioFailed")
        finally:
            qgrab._fetch_to_file = real_fetch
            qgrab._ordered_attempts = real_attempts
        # Every video stream was tried and rejected by the guard;
        # the music field was never fetched.
        assert fetched == ["https://cdn.example/hd.mp4",
                           "https://cdn.example/play.mp4",
                           "https://cdn.example/wm.mp4"], fetched
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- B: audio route ---------------------------------------------------

class _FakeGeminiResponse:
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


def test_sp_214s_survives_slow_timeout_plus_quota():
    """The diagnosed failure: attempt 1 times out SLOWLY (a real
    214 s transcription can outlast the per-attempt timeout),
    attempt 2 fails FAST on quota. The old shared slow cap (2)
    gave up there; the audio budget walks on and attempt 3
    answers. The default (text-route) cap still stops at 2."""
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        mp3 = os.path.join(d, "audio.mp3")
        _make_media(mp3, 214)
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req.full_url)
            if len(calls) == 1:
                time.sleep(0.3)  # slow, past the patched threshold
                raise urllib.error.URLError("timed out")
            if len(calls) == 2:
                raise urllib.error.HTTPError(
                    req.full_url, 429, "quota exhausted",
                    None, None)
            return _FakeGeminiResponse('{"script": "ok"}')

        real_urlopen = qgrab.urllib.request.urlopen
        real_threshold = qgrab.SP_GEMINI_FAST_FAIL
        qgrab.urllib.request.urlopen = fake_urlopen
        qgrab.SP_GEMINI_FAST_FAIL = 0.2
        try:
            raw, _model = qgrab._gemini_generate_audio(
                mp3, "Some title", "script")
            assert json.loads(raw) == {"script": "ok"}, raw
            assert len(calls) == 3, calls
            # The default budget is unchanged: the same script
            # through a plain _gemini_call stops at 2 attempts.
            calls.clear()
            try:
                qgrab._gemini_call([{"text": "x"}], "sys", 5)
            except qgrab._GeminiUnavailable:
                pass
            else:
                raise AssertionError("expected _GeminiUnavailable")
            assert len(calls) == 2, calls
        finally:
            qgrab.urllib.request.urlopen = real_urlopen
            qgrab.SP_GEMINI_FAST_FAIL = real_threshold
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _make_long_mp3(path, seconds):
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=16000", "-t", str(seconds),
         "-codec:a", "libmp3lame", "-b:a", "64k", path],
        check=True)


def test_sp_chunks_split_at_ten_minutes():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        mp3 = os.path.join(d, "audio.mp3")
        _make_long_mp3(mp3, 1140)  # 19 minutes
        chunks = qgrab._sp_split_audio_chunks(mp3)
        assert len(chunks) == 2, chunks
        durations = [qgrab._sp_probe_duration(c) for c in chunks]
        assert all(x is not None and x <= 605 for x in durations), \
            durations
        assert abs(sum(durations) - 1140) < 5, durations
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _with_fake_gemini_call(fake):
    real = qgrab._gemini_call
    qgrab._gemini_call = fake
    return real


def test_sp_19min_two_chunks_stitched_in_order():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        mp3 = os.path.join(d, "audio.mp3")
        _make_long_mp3(mp3, 1140)  # 19 minutes -> 2 chunks
        seen = []

        def fake_call(parts, system, timeout, max_models=None,
                      slow_max_attempts=None):
            seen.append(system)
            if system == qgrab.SP_AUDIO_CHUNK_INSTRUCTION:
                text = parts[-1]["text"]
                if "chunk 1 of 2" in text:
                    return json.dumps(
                        {"transcript": "FIRST PART"}), "m1"
                assert "chunk 2 of 2" in text, text
                return json.dumps(
                    {"transcript": "SECOND PART"}), "m1"
            # The writing stage: echo its input so the test can
            # see the stitched order it was handed.
            return json.dumps(
                {"script": "<<" + parts[0]["text"] + ">>"}), "m2"

        real = _with_fake_gemini_call(fake_call)
        try:
            raw, _model = qgrab._gemini_generate_audio(
                mp3, "Some title", "script")
        finally:
            qgrab._gemini_call = real
        script, _p, _partial, _ns = qgrab._sp_parse_output(raw)
        assert "FIRST PART" in script and "SECOND PART" in script
        assert script.index("FIRST PART") \
            < script.index("SECOND PART"), script
        assert seen == [qgrab.SP_AUDIO_CHUNK_INSTRUCTION] * 2 \
            + [qgrab.SP_TRANSCRIPT_INSTRUCTION_SCRIPT], seen
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sp_chunk_failure_is_ai_unavailable():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        mp3 = os.path.join(d, "audio.mp3")
        _make_long_mp3(mp3, 1140)

        def failing_call(parts, system, timeout, max_models=None,
                         slow_max_attempts=None):
            raise qgrab._GeminiUnavailable("every pair failed")

        real = _with_fake_gemini_call(failing_call)
        try:
            try:
                qgrab._gemini_generate_audio(mp3, "t", "script")
            except qgrab._GeminiUnavailable:
                pass
            else:
                raise AssertionError(
                    "expected _GeminiUnavailable")
        finally:
            qgrab._gemini_call = real
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_sp_convert_normalises_to_16k_mono():
    d = tempfile.mkdtemp(prefix="qgrab-hardening-")
    try:
        src = os.path.join(d, "src.mp3")
        _make_media(src, 5, sample_rate=44100)
        out = os.path.join(d, "out.mp3")
        assert qgrab._sp_convert_to_mp3(src, out)
        stream = _probe_stream(out)
        assert stream["sample_rate"] == "16000", stream
        assert stream["channels"] == 1, stream
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- D: Instagram embed -------------------------------------------------

IG_HTML = (
    '<html><head></head><body><script type="text/javascript">'
    'window.__data = {"gql_data":{"shortcode_media":{'
    '"__typename":"GraphVideo","id":"321",'
    '"display_url":"https://cdn.example/poster.jpg",'
    '"dimensions":{"height":1080,"width":608},'
    '"video_duration":12.5,'
    '"edge_media_to_caption":{"edges":[{"node":{'
    '"text":"Hello world caption\\nsecond line"}}]},'
    '"video_url":"https://cdn.example/ig-video.mp4"}}}'
    ';</script></body></html>')


def _stub_http_text(html):
    asked = []

    def fake(url, headers=None, timeout=15):
        asked.append((url, headers))
        return html

    real = qgrab._http_get_text
    qgrab._http_get_text = fake
    return asked, real


def test_instagram_embed_fallback():
    asked, real = _stub_http_text(IG_HTML)
    try:
        result = _run_extract(
            IG_URL, [WEBPAGE_FAIL, WEBPAGE_FAIL, WEBPAGE_FAIL])
    finally:
        qgrab._http_get_text = real
    assert isinstance(result, dict), result
    assert result["_qgrab_source"] == "instagram-embed", result
    assert result["formats"][0]["url"] == \
        "https://cdn.example/ig-video.mp4", result
    assert result["formats"][0]["height"] == 1080, result
    assert result["title"] == "Hello world caption", result
    assert result["thumbnail"] == "https://cdn.example/poster.jpg"
    assert asked[0][0] == \
        "https://www.instagram.com/p/ABC123/embed/captioned/", asked


def test_instagram_embed_failure_keeps_original_error():
    asked, real = _stub_http_text("<html>no media here</html>")
    try:
        result = _run_extract(
            IG_URL, [WEBPAGE_FAIL, WEBPAGE_FAIL, WEBPAGE_FAIL])
    finally:
        qgrab._http_get_text = real
    assert isinstance(result, DownloadError), result
    assert "webpage" in str(result), result


# --- E: Facebook embed ----------------------------------------------------

FB_HTML = (
    '<html><head><title>Some FB Video</title></head><body>'
    '<script>var x = {"hd_src":"https:\\/\\/video.example'
    '\\/hd.mp4?a=1\\u0026b=2","sd_src":"https:\\/\\/video.example'
    '\\/sd.mp4"};</script></body></html>')


def test_facebook_embed_fallback():
    asked, real = _stub_http_text(FB_HTML)
    try:
        result = _run_extract(
            FB_URL, [WEBPAGE_FAIL, WEBPAGE_FAIL, WEBPAGE_FAIL])
    finally:
        qgrab._http_get_text = real
    assert isinstance(result, dict), result
    assert result["_qgrab_source"] == "facebook-embed", result
    urls = [f["url"] for f in result["formats"]]
    # hd first, JSON-escaped URLs fully decoded.
    assert urls == ["https://video.example/hd.mp4?a=1&b=2",
                    "https://video.example/sd.mp4"], urls
    embed_url, headers = asked[0]
    assert embed_url == ("https://www.facebook.com/video/embed"
                         "?video_id=1234567890"), embed_url
    assert "facebookexternalhit" in headers["User-Agent"], headers


# --- F: X -------------------------------------------------------------------

def test_x_syndication_attempt_before_fxtwitter():
    result = _run_extract(
        X_URL, [WEBPAGE_FAIL, WEBPAGE_FAIL, WEBPAGE_FAIL,
                GOOD_INFO])
    assert result is GOOD_INFO, result
    # Cascade (2) + paused retry (1) + the syndication attempt.
    assert _ScriptedYDL.calls == 4, _ScriptedYDL.calls
    args = (_ScriptedYDL.opts_seen[3].get("extractor_args") or {})
    assert (args.get("twitter") or {}).get("api") == \
        ["syndication"], args


FX_PAYLOAD = {
    "code": 200,
    "tweet": {
        "text": "A clip worth saving",
        "author": {"name": "Some User"},
        "media": {
            "videos": [{
                "url": "https://video.twimg.com/x/720.mp4",
                "thumbnail_url": "https://cdn.example/thumb.jpg",
                "duration": 42.0,
                "width": 1280,
                "height": 720,
                "variants": [
                    {"bitrate": 2176000,
                     "content_type": "video/mp4",
                     "url": "https://video.twimg.com/ext/pu/vid/"
                            "1280x720/a.mp4"},
                    {"bitrate": 832000,
                     "content_type": "video/mp4",
                     "url": "https://video.twimg.com/ext/pu/vid/"
                            "640x360/b.mp4"},
                    {"content_type": "application/x-mpegURL",
                     "url": "https://video.twimg.com/ext/pl.m3u8"},
                ],
            }],
        },
    },
}


def test_x_fxtwitter_fallback_maps_variant_ladder():
    asked, real = _stub_http_json(FX_PAYLOAD)
    try:
        result = _run_extract(X_URL, [WEBPAGE_FAIL] * 4)
    finally:
        _unstub_http_json(real)
    assert isinstance(result, dict), result
    assert result["_qgrab_source"] == "fxtwitter", result
    heights = [f["height"] for f in result["formats"]]
    assert heights == [720, 360], heights     # best first, HLS out
    assert all("m3u8" not in f["url"] for f in result["formats"])
    assert result["duration"] == 42, result
    assert asked == ["https://api.fxtwitter.com/status/"
                     "1234567890123"], asked


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
