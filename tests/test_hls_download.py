"""Tests for the HLS (m3u8) download fix (release 2026-11-16.22).

The production retest of .21 found Dailymotion broken in a quiet
way: /api/info works (it lists HLS formats), but /download proxied
the format URL straight through — and that URL is an .m3u8
PLAYLIST, so visitors received a 375-byte text playlist wearing a
video filename instead of a video.

The contract pinned here:

  * an HLS format (protocol m3u8*, ext m3u8, or a URL ending in
    .m3u8) is NEVER proxied raw — it is remuxed server-side
    (ffmpeg -c copy) and served as a real video/mp4 file;
  * when ffmpeg cannot do it, yt-dlp's native HLS download is
    the fallback;
  * when both fail, the visitor gets the site's friendly error
    (502 + FRIENDLY_ERROR) — never the playlist;
  * a non-HLS format still takes the ordinary proxy path,
    untouched;
  * _ffmpeg_remux_url itself refuses a "successful" output that
    is still a playlist.

No network: extraction, the remux and the yt-dlp fallback are
stubbed; the remux guard is exercised against fake ffmpeg
executables on PATH.

Run:  .venv/bin/python tests/test_hls_download.py   (or pytest)
"""

import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402

DM_URL = "https://www.dailymotion.com/video/x8abcd"
HLS_FORMAT = {
    "format_id": "hls-720",
    "url": "https://cdn.example/master.m3u8?token=xyz",
    "protocol": "m3u8_native",
    "ext": "mp4",
    "vcodec": "avc1",
    "acodec": "mp4a",
    "height": 720,
}
HLS_INFO = {"title": "Some DM Video", "formats": [HLS_FORMAT]}
MP4_FORMAT = {
    "format_id": "mp4-360",
    "url": "https://cdn.example/video.mp4",
    "protocol": "https",
    "ext": "mp4",
    "vcodec": "avc1",
    "acodec": "mp4a",
    "height": 360,
}
MP4_INFO = {"title": "Plain MP4 Video", "formats": [MP4_FORMAT]}

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x11" * 2048
PLAYLIST = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nseg.m3u8\n"


class _Patch:
    """Tiny monkeypatch context: set module attrs, restore after."""

    def __init__(self, **attrs):
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        for name, value in self.attrs.items():
            self.saved[name] = getattr(qgrab, name)
            setattr(qgrab, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(qgrab, name, value)
        return False


def _client():
    return qgrab.app.test_client()


def _get(client, url, format_id):
    resp = client.get("/download", query_string={
        "url": url, "format_id": format_id})
    data = resp.get_data()
    resp.close()
    return resp, data


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_is_hls_target_detection():
    assert qgrab._is_hls_target(HLS_FORMAT, HLS_FORMAT["url"])
    # Protocol alone decides it, whatever the URL looks like.
    assert qgrab._is_hls_target(
        {"protocol": "m3u8", "ext": "mp4"}, "https://cdn.example/vid")
    # So does an m3u8 extension on the format...
    assert qgrab._is_hls_target(
        {"protocol": "https", "ext": "m3u8"}, "https://cdn.example/vid")
    # ...or a playlist URL (query string must not hide it).
    assert qgrab._is_hls_target(
        {"protocol": "https", "ext": "mp4"},
        "https://cdn.example/list.M3U8?tok=1")
    # A plain media file is not HLS.
    assert not qgrab._is_hls_target(MP4_FORMAT, MP4_FORMAT["url"])
    assert not qgrab._is_hls_target(
        {"protocol": "https", "ext": "mp4"},
        "https://cdn.example/movie.mp4?x=.m3u8")


# ---------------------------------------------------------------------------
# The happy path: remuxed MP4 bytes, video/mp4, .mp4 filename
# ---------------------------------------------------------------------------

def test_hls_download_serves_remuxed_mp4():
    calls = {}

    def fake_remux(media_url, headers, out_path):
        calls["media_url"] = media_url
        with open(out_path, "wb") as fh:
            fh.write(FAKE_MP4)
        return True

    def no_proxy(*a, **k):
        raise AssertionError("HLS format must not be proxied raw")

    with _Patch(extract_info=lambda url: HLS_INFO,
                _ffmpeg_remux_url=fake_remux,
                _open_media_stream=no_proxy):
        resp, data = _get(_client(), DM_URL, "hls-720")
    assert calls["media_url"] == HLS_FORMAT["url"], calls
    assert resp.status_code == 200, resp.status_code
    assert resp.content_type.startswith("video/mp4"), resp.content_type
    assert data == FAKE_MP4
    assert not data.startswith(b"#EXTM3U")
    disp = resp.headers.get("Content-Disposition") or ""
    assert ".mp4" in disp, disp


# ---------------------------------------------------------------------------
# Fallback + failure paths
# ---------------------------------------------------------------------------

def test_hls_ytdlp_fallback_when_ffmpeg_fails():
    from flask import Response
    calls = {}

    def fake_fallback(url, format_id):
        calls["args"] = (url, format_id)
        return Response(FAKE_MP4, mimetype="video/mp4")

    with _Patch(extract_info=lambda url: HLS_INFO,
                _ffmpeg_remux_url=lambda *a: False,
                _download_via_ytdlp=fake_fallback):
        resp, data = _get(_client(), DM_URL, "hls-720")
    assert calls["args"] == (DM_URL, "hls-720"), calls
    assert resp.status_code == 200, resp.status_code
    assert data == FAKE_MP4


def test_hls_failure_is_friendly_error_never_playlist():
    with _Patch(extract_info=lambda url: HLS_INFO,
                _ffmpeg_remux_url=lambda *a: False,
                _download_via_ytdlp=lambda url, fid: None):
        resp, data = _get(_client(), DM_URL, "hls-720")
    assert resp.status_code == 502, resp.status_code
    assert b"#EXTM3U" not in data
    assert b"could not be read" in data, data[:200]


# ---------------------------------------------------------------------------
# Regression: a normal format still goes through the proxy untouched
# ---------------------------------------------------------------------------

def test_non_hls_format_still_proxied():
    def fake_stream(media_url, headers):
        return (200,
                {"Content-Type": "video/mp4",
                 "Content-Length": str(len(FAKE_MP4))},
                iter([FAKE_MP4]),
                lambda: None)

    def no_remux(*a, **k):
        raise AssertionError("non-HLS format must not be remuxed")

    with _Patch(extract_info=lambda url: MP4_INFO,
                _open_media_stream=fake_stream,
                _ffmpeg_remux_url=no_remux):
        resp, data = _get(_client(), DM_URL, "mp4-360")
    assert resp.status_code == 200, resp.status_code
    assert data == FAKE_MP4


# ---------------------------------------------------------------------------
# The remux guard itself: a playlist output is a failure, using
# fake ffmpeg executables so the real function runs end to end.
# ---------------------------------------------------------------------------

def _remux_with_fake_ffmpeg(body):
    """Run the real _ffmpeg_remux_url against a fake `ffmpeg`
    executable (first on PATH) that "produces" the given bytes as
    its output file (the output path is ffmpeg's last argument)."""
    tmpdir = tempfile.mkdtemp(prefix="qgrab-fakeffmpeg-")
    body_path = os.path.join(tmpdir, "body.bin")
    with open(body_path, "wb") as fh:
        fh.write(body)
    script = os.path.join(tmpdir, "ffmpeg")
    with open(script, "w") as fh:
        fh.write("#!/bin/sh\n")
        fh.write("for last; do :; done\n")
        fh.write(f'cp "{body_path}" "$last"\n')
    os.chmod(script, os.stat(script).st_mode | stat.S_IEXEC)
    out = os.path.join(tmpdir, "out.mp4")
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = tmpdir + os.pathsep + old_path
    try:
        return qgrab._ffmpeg_remux_url(
            "https://cdn.example/master.m3u8", {}, out)
    finally:
        os.environ["PATH"] = old_path


def test_remux_rejects_playlist_output():
    assert _remux_with_fake_ffmpeg(PLAYLIST) is False


def test_remux_accepts_real_mp4_output():
    assert _remux_with_fake_ffmpeg(FAKE_MP4) is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e!r}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
