"""Focused tests for the Script+Prompt AUDIO route.

Original bug covered: for a TikTok video whose own duration is
105 s, the audio route used yt-dlp "bestaudio/best" and downloaded
a SEPARATE 164 s music asset (no speech) instead of the video's own
audio — Gemini then correctly reported no_speech for the wrong
track. The muxed-first order + duration guard fixed that.

Speed pass (2026-11-04) covered here: when the duration is KNOWN,
the small audio-only download is tried FIRST (the guard still
rejects a mismatched candidate — the 164 s trap — and the muxed
format is used instead); when it is UNKNOWN, muxed still goes
first. The audio fetch is bounded to the first 2 cascade attempts.
The Gemini cascade walks a 6-model chain while failures are fast
(quota 429s) and caps at 2 attempts once failures are slow —
see tests/test_sp_gemini_cascade.py.

These tests monkeypatch yt_dlp.YoutubeDL with a fake that mimics
the TikTok format table (a long standalone audio asset + a
duration-matching muxed format) and assert that
_sp_download_audio_mp3:
  * tries audio-only first when the duration is known and the
    track matches (no video-sized download happens),
  * rejects a duration-mismatched audio candidate via the guard
    and falls back to the muxed format,
  * still falls back to bestaudio when it is the matching track,
  * keeps the muxed-first behaviour when the duration is unknown,
  * tries at most the first 2 attempts of the cascade,
and that _gemini_call honours its max_models cap.

Run:  .venv/bin/python tests/test_sp_audio.py   (or under pytest)
"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
VIDEO_SECONDS = 105     # the TikTok video's own duration
MUSIC_SECONDS = 164     # the standalone "sound" asset's duration


def _make_fixture(path, seconds, video=False):
    """A silent-ish media file of an exact duration (sine tone)."""
    args = [FFMPEG, "-y", "-v", "error"]
    if video:
        args += ["-f", "lavfi", "-i", "color=c=black:s=64x64:r=1"]
    args += ["-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=44100",
             "-t", str(seconds)]
    if video:
        args += ["-codec:v", "libx264", "-pix_fmt", "yuv420p",
                 "-codec:a", "aac", "-shortest"]
    args.append(path)
    subprocess.run(args, check=True)


class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: 'downloads' the fixture the
    format selector asks for — the muxed file for any selector that
    names a video codec, an audio fixture for the bestaudio-family
    selectors. A None fixture means that format does not exist on
    this source. Every selector and cascade client seen is recorded
    in .used / .clients so tests can assert the fetch order.
    """
    fixtures = {}
    used = []
    clients = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        selector = self.opts.get("format", "")
        _FakeYDL.used.append(selector)
        args = (self.opts.get("extractor_args") or {}).get(
            "youtube") or {}
        client = (args.get("player_client") or [None])[0]
        _FakeYDL.clients.append(client)
        kind = "muxed" if "vcodec" in selector else "bestaudio"
        src = self.fixtures.get(kind)
        if src is None:
            raise Exception("Requested format is not available")
        ext = os.path.splitext(src)[1].lstrip(".")
        dest = self.opts["outtmpl"].replace("%(ext)s", ext)
        shutil.copyfile(src, dest)
        return {"duration": VIDEO_SECONDS}


_FIXTURE_DIR = None
_URL = "https://vm.tiktok.com/ZN8y4yboh/"


def _setup():
    global _FIXTURE_DIR
    if _FIXTURE_DIR:
        return _FIXTURE_DIR
    d = tempfile.mkdtemp(prefix="qgrab-sp-test-")
    _make_fixture(os.path.join(d, "muxed.mp4"), VIDEO_SECONDS,
                  video=True)
    _make_fixture(os.path.join(d, "music.mp3"), MUSIC_SECONDS)
    _make_fixture(os.path.join(d, "matching.mp3"), VIDEO_SECONDS)
    _FIXTURE_DIR = d
    # One benign cascade attempt; the fake downloader does the rest.
    qgrab._ordered_attempts = lambda url: [
        {"client": None, "impersonate": False}]
    qgrab.yt_dlp.YoutubeDL = _FakeYDL
    return d


def _fetch(expected):
    _FakeYDL.used = []
    _FakeYDL.clients = []
    return qgrab._sp_download_audio_mp3(_URL,
                                        expected_duration=expected)


def test_guard_predicate():
    m = qgrab._sp_duration_mismatch
    assert m(105, 164) is True     # the TikTok music-asset case
    assert m(105, 100) is False    # small drift is fine
    assert m(105, 105) is False
    assert m(None, 164) is False   # unknown video duration: no guard
    assert m(105, None) is False   # unprobeable candidate: no guard
    # unknown duration: muxed is always the first strategy tried
    assert qgrab.SP_AUDIO_STRATEGIES[0][0] == "muxed"
    assert qgrab.SP_AUDIO_STRATEGIES[1][0] == "bestaudio"
    # duration-aware order: audio-first when the guard can vet the
    # result, muxed-first when it cannot
    known = [name for name, _ in
             qgrab._sp_audio_strategies(VIDEO_SECONDS)]
    assert known == ["audio", "muxed", "bestaudio"], known
    unknown = [name for name, _ in qgrab._sp_audio_strategies(None)]
    assert unknown == ["muxed", "bestaudio"], unknown


def test_muxed_preferred_over_music_asset():
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": os.path.join(d, "muxed.mp4"),
        "bestaudio": os.path.join(d, "music.mp3"),
    }
    mp3, tmpdir = _fetch(VIDEO_SECONDS)
    try:
        got = qgrab._sp_probe_duration(mp3)
        assert got is not None and abs(got - VIDEO_SECONDS) < 3, got
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_bestaudio_fallback_when_it_matches():
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": None,  # no muxed format on this source
        "bestaudio": os.path.join(d, "matching.mp3"),
    }
    mp3, tmpdir = _fetch(VIDEO_SECONDS)
    try:
        got = qgrab._sp_probe_duration(mp3)
        assert got is not None and abs(got - VIDEO_SECONDS) < 3, got
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_guard_rejects_mismatched_only_candidate():
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": None,
        "bestaudio": os.path.join(d, "music.mp3"),  # 164 s vs 105 s
    }
    try:
        _fetch(VIDEO_SECONDS)
    except qgrab._SpAudioFailed:
        return
    raise AssertionError(
        "mismatched bestaudio candidate was accepted")


def test_unknown_duration_keeps_legacy_behaviour():
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": None,
        "bestaudio": os.path.join(d, "music.mp3"),
    }
    mp3, tmpdir = _fetch(None)
    try:
        got = qgrab._sp_probe_duration(mp3)
        assert got is not None and abs(got - MUSIC_SECONDS) < 3, got
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_audio_first_when_duration_known_and_matching():
    """Speed path: with a known duration and a matching audio-only
    track, the audio strategy wins outright — no video-sized
    (vcodec) download is ever attempted."""
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": os.path.join(d, "muxed.mp4"),
        "bestaudio": os.path.join(d, "matching.mp3"),
    }
    mp3, tmpdir = _fetch(VIDEO_SECONDS)
    try:
        got = qgrab._sp_probe_duration(mp3)
        assert got is not None and abs(got - VIDEO_SECONDS) < 3, got
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    assert len(_FakeYDL.used) == 1, _FakeYDL.used
    assert "vcodec" not in _FakeYDL.used[0], _FakeYDL.used


def test_unknown_duration_muxed_first():
    """Without a known duration the guard is blind, so the muxed
    format (the video's own audio by construction) is tried first
    even when an audio-only track also exists."""
    d = _setup()
    _FakeYDL.fixtures = {
        "muxed": os.path.join(d, "muxed.mp4"),
        "bestaudio": os.path.join(d, "matching.mp3"),
    }
    mp3, tmpdir = _fetch(None)
    try:
        got = qgrab._sp_probe_duration(mp3)
        assert got is not None and abs(got - VIDEO_SECONDS) < 3, got
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    assert _FakeYDL.used and "vcodec" in _FakeYDL.used[0], \
        _FakeYDL.used


def test_audio_cascade_bounded_to_two_attempts():
    """The SP audio fetch walks at most the first 2 attempts of the
    downloader cascade, even when every strategy fails."""
    _setup()
    _FakeYDL.fixtures = {"muxed": None, "bestaudio": None}
    orig = qgrab._ordered_attempts
    qgrab._ordered_attempts = lambda url: [
        {"client": "c1", "impersonate": False},
        {"client": "c2", "impersonate": False},
        {"client": "c3", "impersonate": False},
    ]
    try:
        try:
            _fetch(VIDEO_SECONDS)
        except qgrab._SpAudioFailed:
            pass
        else:
            raise AssertionError("expected _SpAudioFailed")
    finally:
        qgrab._ordered_attempts = orig
    seen = set(_FakeYDL.clients)
    assert seen == {"c1", "c2"}, seen


def test_gemini_model_cap():
    """_gemini_call with max_models=2 makes at most 2 requests when
    every model fails retryably; without a cap it walks the whole
    6-model chain (every failure here is an instant 429 = fast)."""
    import urllib.error

    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(
            req.full_url, 429, "rate limited", None, None)

    orig_urlopen = qgrab.urllib.request.urlopen
    orig_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "test-key"
    qgrab.urllib.request.urlopen = fake_urlopen
    try:
        try:
            qgrab._gemini_call([{"text": "x"}], "sys", 5,
                               max_models=2)
        except qgrab._GeminiUnavailable:
            pass
        else:
            raise AssertionError("expected _GeminiUnavailable")
        assert len(calls) == 2, calls
        calls.clear()
        try:
            qgrab._gemini_call([{"text": "x"}], "sys", 5)
        except qgrab._GeminiUnavailable:
            pass
        else:
            raise AssertionError("expected _GeminiUnavailable")
        assert len(calls) == 6, calls
    finally:
        qgrab.urllib.request.urlopen = orig_urlopen
        if orig_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = orig_key


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
    if _FIXTURE_DIR:
        shutil.rmtree(_FIXTURE_DIR, ignore_errors=True)
    sys.exit(1 if failed else 0)
