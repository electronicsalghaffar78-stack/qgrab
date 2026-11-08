"""Tests for GET /api/thumb — the lazy thumbnail resolver
behind the Search Videos cards for Facebook / TikTok /
Instagram (their web-search results carry no thumbnail, so
the cards show a platform placeholder until this endpoint
resolves the real image, progressively, after the results
are already on screen).

Contract: {"ok": true, "thumb": url} or {"ok": false}; a
400 only for a malformed request (unknown platform, missing
/ over-long / foreign-host URL). Strategies per platform:
  tiktok    -> tikwm resolver cover (mocked _http_get_json)
  facebook  -> graph.facebook.com/<id>/picture straight from
               the URL's id (NO fetch); else the page og:image
  instagram -> /embed/captioned/ og:image, then display_url,
               then the post page og:image
Hits AND misses are cached for 24 h — a second identical
request must not fetch again.

All network is mocked by swapping qgrab._http_get_json /
qgrab._http_get_text — no real requests.

Run:  .venv/bin/python tests/test_thumb.py   (or pytest)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as qgrab  # noqa: E402


class _mock:
    """Swap one app-level fetcher for the block, count calls."""

    def __init__(self, name, fn):
        self._name = name
        self._fn = fn
        self.calls = []

    def __enter__(self):
        self._orig = getattr(qgrab, self._name)
        outer = self

        def wrapped(*args, **kwargs):
            outer.calls.append(args[0] if args else None)
            return outer._fn(*args, **kwargs)

        setattr(qgrab, self._name, wrapped)
        return self

    def __exit__(self, *exc):
        setattr(qgrab, self._name, self._orig)
        return False


def _boom(*args, **kwargs):
    raise AssertionError("no fetch expected here")


def _client():
    qgrab._thumb_cache_clear()
    return qgrab.app.test_client()


TT_URL = "https://www.tiktok.com/@dancer1/video/7300000000000000001"
FB_ID_URL = "https://www.facebook.com/watch/?v=1234567890123"
FB_REEL_URL = "https://www.facebook.com/reel/9876543210987"
FB_PAGE_URL = "https://www.facebook.com/SomePage/videos/abc-no-id"
IG_REEL_URL = "https://www.instagram.com/reel/C8xYzAbCdEf/"
IG_POST_URL = "https://www.instagram.com/p/C9aBcDeFgHi/"


# ----------------------------------------------------------------
# TikTok via tikwm
# ----------------------------------------------------------------

def test_tiktok_cover_from_tikwm():
    client = _client()

    def fake_json(url, timeout=None):
        assert "tikwm.com/api/" in url, url
        assert "url=" in url and "7300000000000000001" in url, url
        assert timeout == qgrab._THUMB_TIMEOUT, timeout
        return {"code": 0, "data": {
            "cover": "https://cdn.example/tt-cover.jpg",
            "origin_cover": "https://cdn.example/tt-orig.jpg"}}

    with _mock("_http_get_json", fake_json) as m:
        resp = client.get("/api/thumb",
                          query_string={"platform": "tiktok",
                                        "url": TT_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {
        "ok": True, "thumb": "https://cdn.example/tt-cover.jpg"}
    assert len(m.calls) == 1


def test_tiktok_tikwm_failure_is_ok_false():
    client = _client()

    def fake_json(url, timeout=None):
        return {"code": -1, "msg": "not found"}

    with _mock("_http_get_json", fake_json):
        resp = client.get("/api/thumb",
                          query_string={"platform": "tiktok",
                                        "url": TT_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"ok": False}

    def boom_json(url, timeout=None):
        raise RuntimeError("network down")

    qgrab._thumb_cache_clear()
    with _mock("_http_get_json", boom_json):
        resp = client.get("/api/thumb",
                          query_string={"platform": "tiktok",
                                        "url": TT_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"ok": False}


# ----------------------------------------------------------------
# Facebook: graph URL from the id, og:image fallback
# ----------------------------------------------------------------

def test_facebook_video_id_shapes():
    """The id extractor against the shapes real results have —
    above all /<page>/videos/<slug>/<id>/, the dominant one."""
    cases = {
        "https://www.facebook.com/thecatbutler.co.uk/videos/"
        "funny-cats-to-brighten-your-day-/603296735100249/":
            "603296735100249",
        "https://www.facebook.com/SomePage/videos/111222333444":
            "111222333444",
        "https://www.facebook.com/reel/9876543210987":
            "9876543210987",
        "https://www.facebook.com/watch/?v=1234567890123":
            "1234567890123",
        "https://www.facebook.com/SomePage/videos/abc-no-id": "",
        "https://fb.watch/xyZ123/": "",
    }
    for url, want in cases.items():
        got = qgrab._fb_video_id(url)
        assert got == want, (url, got, want)


def test_facebook_og_image_wins_when_id_present():
    """Measured order (2026-11-08): a real /videos/ page's
    og:image resolves, graph /picture answers 400 — so when
    the page offers an og:image it is the answer, id or not."""
    client = _client()
    url = ("https://www.facebook.com/thecatbutler.co.uk/videos/"
           "funny-cats-to-brighten-your-day-/603296735100249/")
    page = ('<meta property="og:image" '
            'content="https://scontent.example/fb-real.jpg">')

    def fake_text(u, headers=None, timeout=None):
        assert u == url, u
        return page

    with _mock("_http_get_text", fake_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "facebook",
                                        "url": url})
    assert resp.get_json() == {
        "ok": True, "thumb": "https://scontent.example/fb-real.jpg"}


def test_facebook_graph_picture_when_page_has_no_og_image():
    """Last ditch: the page fetched fine but carries no
    og:image (or the fetch failed) and the URL has an id —
    the graph picture URL is the answer; if Meta refuses it,
    the card's <img> errors and the placeholder stays."""
    client = _client()

    def bare_page(url, headers=None, timeout=None):
        return "<html><head><title>fb</title></head></html>"

    with _mock("_http_get_text", bare_page):
        resp = client.get("/api/thumb",
                          query_string={"platform": "facebook",
                                        "url": FB_ID_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {
        "ok": True,
        "thumb": "https://graph.facebook.com/1234567890123/picture"}

    qgrab._thumb_cache_clear()

    def boom_text(url, headers=None, timeout=None):
        raise RuntimeError("blocked")

    with _mock("_http_get_text", boom_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "facebook",
                                        "url": FB_REEL_URL})
    assert resp.get_json() == {
        "ok": True,
        "thumb": "https://graph.facebook.com/9876543210987/picture"}


def test_facebook_og_image_fallback_when_no_id():
    client = _client()
    page = ('<html><head><meta property="og:image" '
            'content="https://cdn.example/fb-og.jpg?a=1&amp;b=2">'
            "</head></html>")

    def fake_text(url, headers=None, timeout=None):
        assert url == FB_PAGE_URL, url
        assert timeout == qgrab._THUMB_TIMEOUT, timeout
        return page

    with _mock("_http_get_text", fake_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "facebook",
                                        "url": FB_PAGE_URL})
    assert resp.get_json() == {
        "ok": True, "thumb": "https://cdn.example/fb-og.jpg?a=1&b=2"}


def test_facebook_no_og_image_is_ok_false():
    client = _client()

    def fake_text(url, headers=None, timeout=None):
        return "<html><head><title>login</title></head></html>"

    with _mock("_http_get_text", fake_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "facebook",
                                        "url": FB_PAGE_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"ok": False}


# ----------------------------------------------------------------
# Instagram: embed og:image, display_url, page fallback
# ----------------------------------------------------------------

def test_instagram_embed_og_image():
    client = _client()
    embed = ('<html><head><meta content="https://cdn.example/'
             'ig-embed.jpg" property="og:image"></head></html>')

    def fake_text(url, headers=None, timeout=None):
        assert url == ("https://www.instagram.com/reel/"
                       "C8xYzAbCdEf/embed/captioned/"), url
        return embed

    with _mock("_http_get_text", fake_text) as m:
        resp = client.get("/api/thumb",
                          query_string={"platform": "instagram",
                                        "url": IG_REEL_URL})
    assert resp.get_json() == {
        "ok": True, "thumb": "https://cdn.example/ig-embed.jpg"}
    assert len(m.calls) == 1, "og:image hit must not fetch the page"


def test_instagram_embed_display_url_fallback():
    client = _client()
    embed = (r'<html><body><script>{"display_url":"https:\/\/'
             r'cdn.example\/ig-display.jpg?x=1"}</script>'
             "</body></html>")

    def fake_text(url, headers=None, timeout=None):
        return embed

    with _mock("_http_get_text", fake_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "instagram",
                                        "url": IG_POST_URL})
    assert resp.get_json() == {
        "ok": True, "thumb": "https://cdn.example/ig-display.jpg?x=1"}


def test_instagram_page_og_image_last_resort():
    client = _client()

    def fake_text(url, headers=None, timeout=None):
        if "/embed/captioned/" in url:
            raise RuntimeError("embed blocked")
        return ('<meta property="og:image" '
                'content="https://cdn.example/ig-page.jpg">')

    with _mock("_http_get_text", fake_text) as m:
        resp = client.get("/api/thumb",
                          query_string={"platform": "instagram",
                                        "url": IG_REEL_URL})
    assert resp.get_json() == {
        "ok": True, "thumb": "https://cdn.example/ig-page.jpg"}
    assert len(m.calls) == 2


def test_instagram_total_failure_is_ok_false():
    client = _client()

    def fake_text(url, headers=None, timeout=None):
        return "<html><body>login wall</body></html>"

    with _mock("_http_get_text", fake_text):
        resp = client.get("/api/thumb",
                          query_string={"platform": "instagram",
                                        "url": IG_REEL_URL})
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {"ok": False}


# ----------------------------------------------------------------
# Cache: hits and misses are resolved once
# ----------------------------------------------------------------

def test_cache_hit_avoids_refetch():
    client = _client()

    def fake_json(url, timeout=None):
        return {"code": 0, "data": {"cover": "https://c.example/x.jpg"}}

    with _mock("_http_get_json", fake_json) as m:
        for _ in range(3):
            resp = client.get("/api/thumb",
                              query_string={"platform": "tiktok",
                                            "url": TT_URL})
            assert resp.get_json()["ok"] is True
    assert len(m.calls) == 1, m.calls


def test_cache_miss_avoids_refetch():
    client = _client()

    def fake_json(url, timeout=None):
        return {"code": -1}

    with _mock("_http_get_json", fake_json) as m:
        for _ in range(2):
            resp = client.get("/api/thumb",
                              query_string={"platform": "tiktok",
                                            "url": TT_URL})
            assert resp.get_json() == {"ok": False}
    assert len(m.calls) == 1, m.calls


# ----------------------------------------------------------------
# Validation: never a general fetcher
# ----------------------------------------------------------------

def test_validation_rejects_bad_requests_without_fetching():
    client = _client()
    bad = [
        {"platform": "youtube", "url": "https://www.youtube.com/watch?v=x"},
        {"platform": "", "url": TT_URL},
        {"platform": "tiktok"},
        {"platform": "tiktok", "url": ""},
        {"platform": "tiktok", "url": "https://example.com/@a/video/1"},
        {"platform": "facebook", "url": "https://www.tiktok.com/@a/video/1"},
        {"platform": "instagram", "url": "https://evil-instagram.com.eh/p/x"},
        {"platform": "tiktok", "url": "https://www.tiktok.com/" + "a" * 2100},
    ]
    with _mock("_http_get_text", _boom), \
            _mock("_http_get_json", _boom):
        for qs in bad:
            resp = client.get("/api/thumb", query_string=qs)
            assert resp.status_code == 400, (qs, resp.status_code)
            assert resp.get_json()["ok"] is False, qs


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
