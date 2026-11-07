"""Tests for the Video Toolkit feature (/api/video-details).

Pure shaping tests run on canned info dicts; endpoint tests use
Flask's test_client with app.extract_info monkeypatched — the
same pattern as tests/test_search.py. Nothing touches the live
network.
Run:  python -m pytest tests/test_toolkit.py
  or: python tests/test_toolkit.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as A


# ----------------------------------------------------------------
# Hashtag extraction
# ----------------------------------------------------------------

def test_hashtags_basic_dedupe_order():
    out = A._extract_hashtags(
        "Funny #cats video #funny",
        "Watch #cats and #dogs_daily #funny #2024")
    assert out == ["#cats", "#funny", "#dogs_daily", "#2024"]


def test_hashtags_none_and_junk():
    assert A._extract_hashtags(None, "", "no tags here") == []
    assert A._extract_hashtags("a # alone, #! not tags") == []
    # Unicode word characters are part of a hashtag.
    assert A._extract_hashtags("اردو #کہانی end") == ["#کہانی"]


def test_hashtags_from_shape_uses_title_and_description():
    info = {"title": "Clip #one",
            "description": "About #two and #one"}
    d = A._shape_video_details(info, "https://youtu.be/x")
    assert d["hashtags"] == ["#one", "#two"]


# ----------------------------------------------------------------
# Shaping: a rich YouTube-style info dict
# ----------------------------------------------------------------

YOUTUBE_INFO = {
    "id": "MIW2VPprnLw",
    "title": "Funny Cats Compilation #cats",
    "description": "The funniest cats.\n#cats #funny #pets",
    "thumbnail": "https://i.ytimg.com/vi/MIW2VPprnLw/hqdefault.jpg",
    "thumbnails": [
        {"url": "https://i.ytimg.com/vi/MIW2VPprnLw/default.jpg",
         "width": 120, "height": 90},
        {"url": "https://i.ytimg.com/vi/MIW2VPprnLw/maxres.jpg",
         "width": 1280, "height": 720},
    ],
    "webpage_url": "https://www.youtube.com/watch?v=MIW2VPprnLw",
    "uploader": "Clumsy Critters",
    "channel_url": "https://www.youtube.com/@ClumsyCritters",
    "uploader_url": "https://www.youtube.com/@ClumsyCrittersAlt",
    "upload_date": "20251102",
    "view_count": 1234567,
    "like_count": 8901,
    "comment_count": 234,
    "duration": 372,
    "duration_string": "6:12",
    "tags": ["cats", "funny animals", "pets"],
    "extractor_key": "Youtube",
    "formats": [{"format_id": "22", "url": "https://media.example/v"}],
}


def test_shape_youtube_rich():
    d = A._shape_video_details(
        dict(YOUTUBE_INFO), YOUTUBE_INFO["webpage_url"])
    assert d["title"] == "Funny Cats Compilation #cats"
    assert d["description"].startswith("The funniest cats.")
    # The shaped 'thumbnail' field wins over the ladder.
    assert d["thumbnail"].endswith("hqdefault.jpg")
    assert d["webpage_url"] == YOUTUBE_INFO["webpage_url"]
    assert d["uploader"] == "Clumsy Critters"
    # channel_url preferred over uploader_url.
    assert d["channel_url"].endswith("@ClumsyCritters")
    assert d["upload_date"] == "2025-11-02"
    assert d["view_count"] == 1234567
    assert d["like_count"] == 8901
    assert d["comment_count"] == 234
    assert d["duration"] == 372
    assert d["duration_h"] == "6:12"
    assert d["site"] == "Youtube"
    assert d["tags"] == ["cats", "funny animals", "pets"]
    assert d["hashtags"] == ["#cats", "#funny", "#pets"]


def test_shape_best_thumbnail_from_ladder():
    info = dict(YOUTUBE_INFO)
    del info["thumbnail"]
    d = A._shape_video_details(info, info["webpage_url"])
    assert d["thumbnail"].endswith("maxres.jpg")


def test_shape_upload_date_from_timestamp():
    info = {"title": "t", "timestamp": 1762300000}
    d = A._shape_video_details(info, "https://example.com/v")
    assert d["upload_date"] == "2025-11-04"


# ----------------------------------------------------------------
# Shaping: a minimal TikTok (tikwm-shaped) info dict
# ----------------------------------------------------------------

TIKTOK_INFO = {
    "id": "7300000000000000001",
    "title": "Dance clip",
    "thumbnail": "https://cdn.example/cover.jpg",
    "duration": 21,
    "duration_string": "0:21",
    "uploader": "Dancer One",
    "webpage_url": "https://www.tiktok.com/@dancer1/video/"
                   "7300000000000000001",
    "extractor_key": "TikTok",
    "formats": [{"format_id": "tikwm-hd", "url": "https://cdn.example/v"}],
    "_qgrab_source": "tikwm",
}


def test_shape_tiktok_minimal_nulls_stay_null():
    d = A._shape_video_details(
        dict(TIKTOK_INFO), TIKTOK_INFO["webpage_url"])
    assert d["title"] == "Dance clip"
    assert d["thumbnail"] == "https://cdn.example/cover.jpg"
    assert d["duration"] == 21
    assert d["duration_h"] == "0:21"
    assert d["description"] is None
    assert d["channel_url"] is None
    assert d["upload_date"] is None
    assert d["view_count"] is None
    assert d["like_count"] is None
    assert d["comment_count"] is None
    assert d["tags"] == []
    assert d["hashtags"] == []


def test_tikwm_shaper_surfaces_genuine_fields():
    payload = {
        "id": "7300000000000000001",
        "title": "Dance clip #dance",
        "cover": "https://cdn.example/cover.jpg",
        "duration": 21,
        "play": "https://cdn.example/sd.mp4",
        "play_count": 5500,
        "digg_count": 321,
        "comment_count": 12,
        "create_time": 1762300000,
        "author": {"unique_id": "dancer1", "nickname": "Dancer One"},
    }
    info = A._shape_tikwm_info(payload, TIKTOK_INFO["webpage_url"])
    d = A._shape_video_details(info, TIKTOK_INFO["webpage_url"])
    assert d["description"] == "Dance clip #dance"
    assert d["view_count"] == 5500
    assert d["like_count"] == 321
    assert d["comment_count"] == 12
    assert d["upload_date"] == "2025-11-04"
    assert d["channel_url"] == "https://www.tiktok.com/@dancer1"
    assert d["hashtags"] == ["#dance"]


def test_invidious_shaper_surfaces_genuine_fields():
    data = {
        "videoId": "MIW2VPprnLw",
        "title": "Funny Cats",
        "description": "Line one<br>Line two &amp; more",
        "author": "Clumsy Critters",
        "authorUrl": "/channel/UCxyz",
        "lengthSeconds": 372,
        "viewCount": 4242,
        "likeCount": 99,
        "published": 1762300000,
        "keywords": ["cats", "funny"],
        "formatStreams": [{
            "url": "https://inv.example/videoplayback", "itag": 22,
            "container": "mp4", "qualityLabel": "720p",
            "contentLength": "1000",
        }],
        "videoThumbnails": [{
            "quality": "high", "url": "https://img.example/hq.jpg",
        }],
    }
    info = A._shape_invidious_info("https://inv.example", data,
                                   "https://youtu.be/MIW2VPprnLw")
    d = A._shape_video_details(info, "https://youtu.be/MIW2VPprnLw")
    assert d["description"] == "Line one\nLine two & more"
    assert d["view_count"] == 4242
    assert d["like_count"] == 99
    assert d["upload_date"] == "2025-11-04"
    assert d["channel_url"] == \
        "https://www.youtube.com/channel/UCxyz"
    assert d["tags"] == ["cats", "funny"]


# ----------------------------------------------------------------
# Endpoint validation (extract_info monkeypatched — no network)
# ----------------------------------------------------------------

def _client():
    return A.app.test_client()


def test_endpoint_missing_url():
    r = _client().get("/api/video-details")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_endpoint_rejects_junk_urls():
    client = _client()
    for bad in ("not a url", "ftp://example.com/v", "javascript:x"):
        r = client.get("/api/video-details",
                       query_string={"url": bad})
        assert r.status_code == 400, bad


def test_endpoint_ok_with_mocked_extractor():
    orig = A.extract_info

    def fake(url):
        return dict(YOUTUBE_INFO)

    A.extract_info = fake
    try:
        r = _client().get(
            "/api/video-details",
            query_string={"url": YOUTUBE_INFO["webpage_url"]})
    finally:
        A.extract_info = orig
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["title"] == YOUTUBE_INFO["title"]
    assert body["view_count"] == 1234567
    assert body["hashtags"] == ["#cats", "#funny", "#pets"]
    # The payload never leaks raw format URLs.
    assert "formats" not in body


def test_endpoint_extractor_failure_is_friendly_422():
    orig = A.extract_info

    def boom(url):
        raise ValueError("extractor internals here")

    A.extract_info = boom
    try:
        r = _client().get(
            "/api/video-details",
            query_string={"url": "https://youtu.be/MIW2VPprnLw"})
    finally:
        A.extract_info = orig
    assert r.status_code == 422
    body = r.get_json()
    assert "error" in body
    assert "extractor internals" not in body["error"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"{len(fns)} tests passed")
