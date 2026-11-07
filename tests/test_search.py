"""Tests for the Search Videos feature (/api/search + shapers).

Pure shaping tests run on canned JSON; endpoint validation tests
use Flask's test_client with the per-platform source functions
monkeypatched. Nothing here touches the live network.
Run:  python -m pytest tests/test_search.py
  or: python tests/test_search.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as A


# ----------------------------------------------------------------
# YouTube shaper (Invidious /api/v1/search shape)
# ----------------------------------------------------------------

def test_youtube_shaper():
    data = [
        {"type": "video", "title": "Funny Cats", "videoId": "MIW2VPprnLw",
         "author": "Clumsy Critters", "lengthSeconds": 372,
         "viewCountText": "1.2M views", "publishedText": "3 days ago"},
        {"type": "channel", "title": "A Channel", "authorId": "UCx"},
        {"type": "video", "title": "Bad Id", "videoId": "short",
         "author": "X"},
        {"type": "video", "title": "Second", "videoId": "dQw4w9WgXcQ",
         "author": "Rick", "lengthSeconds": 213},
    ]
    out = A._shape_youtube_search_results(data)
    assert len(out) == 2
    first = out[0]
    assert first["id"] == "MIW2VPprnLw"
    assert first["title"] == "Funny Cats"
    assert first["author"] == "Clumsy Critters"
    assert first["thumbnail"] == (
        "https://i.ytimg.com/vi/MIW2VPprnLw/hqdefault.jpg")
    assert first["webpage_url"] == (
        "https://www.youtube.com/watch?v=MIW2VPprnLw")
    assert first["embed_url"] == (
        "https://www.youtube-nocookie.com/embed/MIW2VPprnLw")
    assert first["duration_h"] == "6:12"


def test_youtube_shaper_cap():
    data = [{"type": "video", "title": f"V{i}", "videoId": "a" * 11,
             "author": "X"} for i in range(20)]
    assert len(A._shape_youtube_search_results(data)) == 12


# ----------------------------------------------------------------
# TikTok shaper (tikwm feed/search shape)
# ----------------------------------------------------------------

def test_tiktok_shaper():
    data = {"videos": [
        {"video_id": 7300000000000000001, "title": "Dance clip",
         "cover": "https://cdn.example/cover.jpg", "duration": 21,
         "play_count": 5500,
         "author": {"unique_id": "dancer1", "nickname": "Dancer One"}},
        {"title": "No id — dropped", "author": {"unique_id": "x"}},
    ]}
    out = A._shape_tiktok_search_results(data)
    assert len(out) == 1
    first = out[0]
    assert first["id"] == "7300000000000000001"
    assert first["author"] == "Dancer One"
    assert first["webpage_url"] == (
        "https://www.tiktok.com/@dancer1/video/7300000000000000001")
    assert first["embed_url"] == (
        "https://www.tiktok.com/embed/v2/7300000000000000001")
    assert first["duration_h"] == "0:21"
    assert first["views"] == "5500 views"


# ----------------------------------------------------------------
# Facebook / Instagram web-search shaping
# ----------------------------------------------------------------

def test_web_search_shaper_filters_and_dedupes():
    pairs = [
        ("Funny video | Facebook",
         "https://www.facebook.com/watch/?v=123456"),
        ("Duplicate", "https://www.facebook.com/watch/?v=123456"),
        ("Help page", "https://www.facebook.com/help/123"),
        ("Not facebook", "https://example.com/watch/?v=9"),
        ("A reel", "https://www.facebook.com/reel/987654"),
    ]
    out = A._shape_web_search_results("facebook", pairs)
    urls = [r["webpage_url"] for r in out]
    assert urls == ["https://www.facebook.com/watch/?v=123456",
                    "https://www.facebook.com/reel/987654"]
    assert out[0]["thumbnail"] == ""
    assert "plugins/video.php?href=" in out[0]["embed_url"]

    ig_pairs = [
        ("Cool reel", "https://www.instagram.com/reel/Cabc123XYZ/"),
        ("Profile", "https://www.instagram.com/someuser/"),
        ("A post", "https://www.instagram.com/p/Cdef456UVW/"),
    ]
    out = A._shape_web_search_results("instagram", ig_pairs)
    assert [r["id"] for r in out] == ["Cabc123XYZ", "Cdef456UVW"]
    assert out[0]["embed_url"] == (
        "https://www.instagram.com/reel/Cabc123XYZ/embed")


def test_ddg_unwrap():
    href = ("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.facebook.com"
            "%2Fwatch%2F%3Fv%3D42&rut=abc")
    assert A._unwrap_ddg_href(href) == (
        "https://www.facebook.com/watch/?v=42")


# ----------------------------------------------------------------
# Endpoint validation (sources monkeypatched — no network)
# ----------------------------------------------------------------

def _client():
    A._search_cache_clear()
    return A.app.test_client()


def test_endpoint_missing_q():
    r = _client().get("/api/search?platform=youtube")
    assert r.status_code == 400


def test_endpoint_bad_platform():
    r = _client().get("/api/search?platform=vimeo&q=cats")
    assert r.status_code == 400


def test_endpoint_unavailable_source():
    orig = A._SEARCH_SOURCES["facebook"]

    def boom(q):
        raise ValueError("blocked")

    A._SEARCH_SOURCES["facebook"] = boom
    try:
        r = _client().get("/api/search?platform=facebook&q=cats")
    finally:
        A._SEARCH_SOURCES["facebook"] = orig
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert body["platform"] == "facebook"
    assert body["reason"] == "unavailable"
    assert body["results"] == []


def test_endpoint_ok_and_cached():
    orig = A._SEARCH_SOURCES["youtube"]
    calls = []

    def fake(q):
        calls.append(q)
        return A._shape_youtube_search_results([
            {"type": "video", "title": "Cats", "videoId": "MIW2VPprnLw",
             "author": "C", "lengthSeconds": 60}])

    A._SEARCH_SOURCES["youtube"] = fake
    try:
        client = _client()
        r1 = client.get("/api/search?platform=youtube&q=funny cats")
        r2 = client.get("/api/search?platform=youtube&q=Funny Cats")
    finally:
        A._SEARCH_SOURCES["youtube"] = orig
    assert r1.status_code == 200
    body = r1.get_json()
    assert body["ok"] is True
    assert body["results"][0]["id"] == "MIW2VPprnLw"
    # Second (case-variant) query was served from the 5-minute cache.
    assert len(calls) == 1
    assert r2.get_json()["ok"] is True


# ----------------------------------------------------------------
# Hardening (2026-11-08): Brave/Yahoo parsers, FB chain, stale cache
# ----------------------------------------------------------------

def _brave_block(url, title):
    return ('<div class="snippet x"><a href="%s">› crumb › videos</a>'
            '<span>%s</span><span>some description text here</span>'
            '</div>' % (url, title))


def _ddg_link(url, title):
    from urllib.parse import quote as _q
    return ('<a class="result__a" href="//duckduckgo.com/l/?uddg=%s">'
            '%s</a>' % (_q(url, safe=""), title))


def test_brave_and_yahoo_parsers():
    html = (_brave_block(
        "https://www.facebook.com/page/videos/cool-video/123/",
        "Cool Video Title")
        + '<div class="snippet y"><a href="https://search.brave.com/'
          'a/redirect?click_url=x">› ad</a><span>Sponsored Thing</span>'
          '</div>')
    pairs = A._parse_brave_results(html)
    assert pairs == [("Cool Video Title",
                      "https://www.facebook.com/page/videos/cool-video/123/")]

    yahoo_html = (
        '<a href="https://r.search.yahoo.com/_ylt=A/RV=2/RE=1/'
        'RU=https%3a%2f%2fwww.facebook.com%2fwatch%2f%3Fv%3D42/RK=2">'
        'Funny Cat Video</a>')
    pairs = A._parse_yahoo_results(yahoo_html)
    assert pairs == [("Funny Cat Video",
                      "https://www.facebook.com/watch/?v=42")]


def test_facebook_url_filter_hardened():
    ok = A._is_platform_video_url
    assert ok("facebook", "https://fb.watch/AbCdEf/")
    assert ok("facebook", "https://www.facebook.com/watch/?v=123")
    assert ok("facebook", "https://www.facebook.com/reel/987654")
    assert not ok("facebook", "https://www.facebook.com/watch/explore/dance/")
    assert not ok("facebook", "https://www.facebook.com/watch/hashtag/dance/")
    assert not ok("facebook", "https://www.facebook.com/watch/")
    assert not ok("facebook", "https://apps.facebook.com/watch/")
    # fb.watch with an unknown title gets the generic Facebook title
    out = A._shape_web_search_results("facebook", [("", "https://fb.watch/Xy9/")])
    assert len(out) == 1 and out[0]["title"] == "Facebook video"


def test_tiktok_engine_shaper():
    pairs = [
        ("Cool dance video",
         "https://www.tiktok.com/@dancer1/video/7300000000000000001"),
        ("Profile page", "https://www.tiktok.com/@dancer1"),
        ("Music page", "https://www.tiktok.com/music/original-sound-123"),
    ]
    out = A._shape_web_search_results("tiktok", pairs)
    assert len(out) == 1
    first = out[0]
    assert first["id"] == "7300000000000000001"
    assert first["author"] == "dancer1"
    assert first["webpage_url"] == (
        "https://www.tiktok.com/@dancer1/video/7300000000000000001")
    assert first["embed_url"] == (
        "https://www.tiktok.com/embed/v2/7300000000000000001")


def test_fb_chain_aggregation_dedupe_and_stop():
    orig = A._http_get_text
    brave_html = (
        _brave_block("https://www.facebook.com/a/videos/x/111/", "A One")
        + _brave_block("https://www.facebook.com/b/videos/y/222/", "B Two"))
    ddg_html = (
        _ddg_link("https://www.facebook.com/b/videos/y/222/", "B dupe")
        + _ddg_link("https://www.facebook.com/reel/333", "C Three")
        + _ddg_link("https://www.facebook.com/reel/444", "D Four"))
    pages = {"search.brave.com": brave_html,
             "duckduckgo.com": ddg_html,
             "bing.com": "", "yahoo.com": ""}
    calls = []

    def fake(url, headers=None, timeout=None):
        calls.append(url)
        for host, page in pages.items():
            if host in url:
                return page
        return ""

    A._http_get_text = fake
    try:
        out = A._run_web_chain("facebook", "cats")
    finally:
        A._http_get_text = orig
    urls = [r["webpage_url"] for r in out]
    assert urls == ["https://www.facebook.com/a/videos/x/111/",
                    "https://www.facebook.com/b/videos/y/222/",
                    "https://www.facebook.com/reel/333",
                    "https://www.facebook.com/reel/444"]
    # Under the 5-result goal the chain consulted every source.
    assert len(calls) == 4

    # Stop-early: Brave alone clears the 5-result goal -> no other
    # source is consulted (one page may itself carry more than 5).
    calls.clear()
    pages["search.brave.com"] = "".join(
        _brave_block(f"https://www.facebook.com/p/videos/v/{i}/",
                     f"Title Number {i}") for i in range(6))
    A._http_get_text = fake
    try:
        out = A._run_web_chain("facebook", "cats")
    finally:
        A._http_get_text = orig
    assert len(out) == 6
    assert len(calls) == 1


def test_fb_chain_retry_best_source():
    orig = A._http_get_text
    state = {"brave": 0}

    def fake(url, headers=None, timeout=None):
        if "search.brave.com" in url:
            state["brave"] += 1
            if state["brave"] == 1:
                raise ValueError("burst block")
            return _brave_block(
                "https://www.facebook.com/a/videos/x/111/", "Retry Win")
        return ""

    A._http_get_text = fake
    try:
        out = A._run_web_chain("facebook", "cats")
    finally:
        A._http_get_text = orig
    assert [r["webpage_url"] for r in out] == [
        "https://www.facebook.com/a/videos/x/111/"]
    assert state["brave"] == 2


def test_stale_cache_served_on_failure():
    orig = A._SEARCH_SOURCES["facebook"]

    def good(q):
        return A._shape_web_search_results(
            "facebook", [("Cats", "https://www.facebook.com/reel/777")])

    def boom(q):
        raise ValueError("all engines blocked")

    client = _client()
    A._SEARCH_SOURCES["facebook"] = good
    try:
        r1 = client.get("/api/search?platform=facebook&q=cats")
        assert r1.get_json()["ok"] is True
        # Drop ONLY the fresh cache; the 24 h stale copy remains.
        with A._search_cache_lock:
            A._search_cache.clear()
        A._SEARCH_SOURCES["facebook"] = boom
        r2 = client.get("/api/search?platform=facebook&q=cats")
        body = r2.get_json()
        assert body["ok"] is True
        assert body["cached"] is True
        assert body["results"][0]["webpage_url"].endswith("/reel/777")
        # With the stale copy gone too, the honest unavailable returns.
        A._search_cache_clear()
        r3 = client.get("/api/search?platform=facebook&q=cats")
        assert r3.get_json()["ok"] is False
    finally:
        A._SEARCH_SOURCES["facebook"] = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"{len(fns)} tests passed")
