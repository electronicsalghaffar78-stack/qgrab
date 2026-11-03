"""Tests for the owner's download-list rule in pick_formats.

RULE: the download list may show ONLY qualities that download WITH
the video's own audio. A video row is therefore one of exactly two
things:
  (a) a true muxed format (vcodec and acodec both present — a
      missing codec field counts as present, only an explicit
      "none" means absent); or
  (b) a synthetic "merge:{height}" row whose download joins the
      best video-only stream at that height with the best audio
      (the delivered mp4 carries sound — verified end-to-end).
A bare video-only stream is NEVER listed as itself. Where a height
has a muxed format, the muxed row wins over a merge row — one video
row per height.

Two layers:
  * Synthetic format tables (TikTok-like, YouTube-like split-only,
    Facebook-like progressive) — always run, no network.
  * Live /api/info checks for one YouTube, one TikTok and one
    Facebook URL, plus an explicit merge-row check on the YouTube
    URL. Every returned video row's audio is RE-DERIVED from the
    raw yt-dlp format table (the row labels are not trusted). A
    source the sandbox network cannot reach is reported as SKIP,
    never silently passed.

Run:  .venv/bin/python tests/test_formats_audio_rule.py (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402


def _fmt(fid, v, a, h=None, note=None, size=None, tbr=None, ext="mp4"):
    return {"format_id": fid, "url": f"https://cdn.example/{fid}",
            "protocol": "https", "ext": ext, "vcodec": v, "acodec": a,
            "height": h, "format_note": note, "filesize": size,
            "tbr": tbr}


def _video_rows(rows):
    return [r for r in rows if r["kind"] == "video+audio"]


# ------------------------------------------------------------------
# Synthetic tables
# ------------------------------------------------------------------

def test_tiktok_like_table():
    # Mirrors the real table probed 2026-11-04: a watermarked muxed
    # "download" (no height), two identical no-watermark muxed
    # mirrors at 1024, silent bytevc1 streams at 1024/1280, and a
    # standalone audio asset.
    info = {"formats": [
        _fmt("audio", "none", "mp3", ext="mp3"),
        _fmt("download", "h264", "aac", note="watermarked"),
        _fmt("h264_540p-0", "h264", "aac", h=1024, size=10775112,
             tbr=813),
        _fmt("h264_540p-1", "h264", "aac", h=1024, size=10775112,
             tbr=813),
        _fmt("bytevc1_540p-0", "h265", "none", h=1024, size=6466177),
        _fmt("bytevc1_720p-0", "h265", "none", h=1280, size=8709297),
    ]}
    rows = qgrab.pick_formats(info)
    vids = _video_rows(rows)
    assert not any(r["id"].startswith("merge:") for r in rows)
    assert not any(r["kind"] == "video" for r in rows)
    # Exactly one row for height 1024 (first mirror wins the tie),
    # plus the watermarked no-height muxed row; the silent 1280 and
    # 1024 bytevc1 rows are gone.
    assert [r["id"] for r in vids] == ["h264_540p-0", "download"], vids
    assert any(r["kind"] == "audio" for r in rows)


def test_split_only_source_gets_merge_rows():
    # YouTube-style: every video stream is video-only, audio is
    # separate. Each split height returns as a "merge:" row (its
    # download muxes the audio in, so it plays with sound); NO bare
    # video-only id is ever listed; audio rows remain.
    info = {"formats": [
        _fmt("140", "none", "mp4a", ext="m4a"),
        _fmt("251", "none", "mp4a", ext="webm"),
        _fmt("160", "avc1", "none", h=144),
        _fmt("134", "avc1", "none", h=360),
        _fmt("136", "avc1", "none", h=720),
        _fmt("398", "vp9", "none", h=720),
    ]}
    rows = qgrab.pick_formats(info)
    vids = _video_rows(rows)
    assert [r["id"] for r in vids] == ["merge:720", "merge:360",
                                       "merge:144"], vids
    assert all(r["note"] == "merged on download" for r in vids)
    assert not any(r["id"] in ("160", "134", "136", "398")
                   for r in rows)
    assert not any(r["kind"] == "video" for r in rows)
    assert any(r["kind"] == "audio" for r in rows)


def test_facebook_like_progressive_pair_kept():
    # sd/hd progressive formats report BOTH codecs as missing
    # (None) — the app's convention counts them as muxed. The pair
    # itself is unchanged (distinct options, not per-height dupes).
    # The DASH video-only streams are never listed bare: the 640
    # height returns as a "merge:" row, while 1280 exceeds the
    # 1080p merge cap and produces no row at all.
    info = {"formats": [
        _fmt("1512a", "none", "mp4a.40.5", ext="m4a"),
        _fmt("sd", None, None),
        _fmt("hd", None, None),
        _fmt("1512v640", "vp09", "none", h=640),
        _fmt("1512v1280", "vp09", "none", h=1280),
    ]}
    rows = qgrab.pick_formats(info)
    assert [r["id"] for r in _video_rows(rows)] == ["merge:640", "sd",
                                                    "hd"], rows
    assert not any(r["id"] in ("1512v640", "1512v1280") for r in rows)


def test_best_per_height_prefers_nowatermark_then_size():
    info = {"formats": [
        _fmt("wm720", "h264", "aac", h=720, size=9000,
             note="watermarked"),
        _fmt("clean720small", "h264", "aac", h=720, size=4000),
        _fmt("clean720big", "h264", "aac", h=720, size=8000),
        _fmt("v720", "h265", "none", h=720, size=99999),
    ]}
    rows = qgrab.pick_formats(info)
    vids = _video_rows(rows)
    assert [r["id"] for r in vids] == ["clean720big"], vids


def test_no_formats():
    assert qgrab.pick_formats({"formats": []}) == []
    assert qgrab.pick_formats({}) == []


# ------------------------------------------------------------------
# Live /api/info checks (network; SKIP when unreachable)
# ------------------------------------------------------------------

LIVE_SOURCES = [
    ("youtube", "https://youtu.be/ktiJ9GSuPfY"),
    ("tiktok", "https://vm.tiktok.com/ZN8y4yboh/"),
    ("facebook", "https://www.facebook.com/reel/2036368387227367"),
]


def _recorded_info(url):
    """POST /api/info while recording the exact info dict the route
    consumed, so rows are checked against the SAME yt-dlp table that
    produced them (platforms vary their tables between requests).
    Returns (resp, raw_info_or_None)."""
    recorded = {}
    real_extract = qgrab.extract_info

    def recording_extract(u):
        info = real_extract(u)
        recorded["info"] = info
        return info

    qgrab.extract_info = recording_extract
    try:
        client = qgrab.app.test_client()
        resp = client.post("/api/info", json={"url": url})
    finally:
        qgrab.extract_info = real_extract
    return resp, recorded.get("info")


def _raw_tables(raw):
    """Split a raw yt-dlp table into (by_id, muxed_heights,
    video_only_heights, has_audio_only) using the app's codec
    convention (missing field counts as present)."""
    by_id, muxed_h, vonly_h, has_audio_only = {}, set(), set(), False
    for f in raw.get("formats", []):
        if not f.get("url"):
            continue
        by_id[str(f.get("format_id"))] = f
        has_v = f.get("vcodec") != "none"
        has_a = f.get("acodec") != "none"
        h = f.get("height") or 0
        if has_v and has_a and h:
            muxed_h.add(h)
        elif has_v and h:
            vonly_h.add(h)
        elif has_a:
            has_audio_only = True
    return by_id, muxed_h, vonly_h, has_audio_only


def _expected_merge_heights(muxed_h, vonly_h, has_audio_only):
    if not has_audio_only:
        return []
    return sorted((h for h in vonly_h if h <= 1080 and h not in muxed_h),
                  reverse=True)[:4]


def _live_check(name, url):
    resp, raw = _recorded_info(url)
    if raw is None:
        return f"SKIP {name}: extraction failed inside /api/info"
    if resp.status_code != 200:
        return f"SKIP {name}: /api/info HTTP {resp.status_code}"
    by_id, muxed_h, vonly_h, has_audio_only = _raw_tables(raw)
    rows = resp.get_json()["formats"]
    assert not any(r["kind"] == "video" for r in rows), rows
    heights = []
    for r in _video_rows(rows):
        rid = str(r["id"])
        if rid.startswith("merge:"):
            # A merge row is legitimate only for a height that has
            # split streams but NO muxed format (muxed wins), within
            # the 1080p merge cap.
            h = int(rid.split(":", 1)[1])
            assert h <= 1080, (name, r)
            assert h in vonly_h, (name, r, vonly_h)
            assert h not in muxed_h, (name, r, muxed_h)
            heights.append(h)
            continue
        src = by_id.get(rid)
        assert src is not None, f"{name}: row id {r['id']} not in raw"
        # Re-derived from the raw yt-dlp table, not the row's label:
        assert src.get("vcodec") != "none", (name, r, src)
        assert src.get("acodec") != "none", (name, r, src)
        heights.append(r["height"] or src.get("height") or 0)
    # Completeness: every raw muxed height appears exactly once as a
    # direct row, and the merge rows are exactly the expected ones.
    row_muxed_h = [r["height"] for r in _video_rows(rows)
                   if r["height"]
                   and not str(r["id"]).startswith("merge:")]
    assert sorted(row_muxed_h) == sorted(muxed_h), (
        name, row_muxed_h, muxed_h)
    row_merge_h = [int(str(r["id"]).split(":", 1)[1])
                   for r in _video_rows(rows)
                   if str(r["id"]).startswith("merge:")]
    assert row_merge_h == _expected_merge_heights(
        muxed_h, vonly_h, has_audio_only), (
        name, row_merge_h, muxed_h, vonly_h)
    return (f"LIVE PASS {name}: video heights {sorted(set(heights), reverse=True) or 'NONE'}"
            f" ({len(_video_rows(rows))} video rows, "
            f"{sum(1 for r in rows if r['kind'] == 'audio')} audio rows)")


def test_live_sources():
    for name, url in LIVE_SOURCES:
        print(" ", _live_check(name, url))


def test_live_youtube_merge_rows():
    # The owner's own YouTube video is split-stream only: its list
    # must offer merge rows for 720/480/360/240, must never list the
    # bare video-only ids, and must keep the audio ids as audio.
    resp, raw = _recorded_info("https://youtu.be/ktiJ9GSuPfY")
    if raw is None or resp.status_code != 200:
        print("  SKIP youtube-merge: source unreachable")
        return
    rows = resp.get_json()["formats"]
    merge_h = {int(str(r["id"]).split(":", 1)[1])
               for r in _video_rows(rows)
               if str(r["id"]).startswith("merge:")}
    assert {720, 480, 360, 240} <= merge_h, merge_h
    video_ids = {str(r["id"]) for r in _video_rows(rows)}
    assert not video_ids & {"136", "398", "397", "134", "243"}, video_ids
    audio_ids = {str(r["id"]) for r in rows if r["kind"] == "audio"}
    assert {"139", "140", "251"} <= audio_ids, audio_ids
    print(f"  LIVE PASS youtube-merge: merge heights "
          f"{sorted(merge_h, reverse=True)}, audio {sorted(audio_ids)}")


def test_pages_render():
    client = qgrab.app.test_client()
    for path in ("/", "/?lang=ur", "/youtube-video-downloader",
                 "/youtube-video-downloader?lang=ur"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
