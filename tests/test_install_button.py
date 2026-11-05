"""Tests for the PWA "Install App" header button + install guide.

Chrome/Android no longer shows an automatic install banner, so the
header carries a visible Install App button (_installbtn.html) on
the homepage, the platform pages and the Script+Prompt page;
_installjs.html captures beforeinstallprompt and fires the native
prompt from the button.

Chrome withholds beforeinstallprompt from new / low-engagement
visitors, though, and iOS never sends it — those visitors used to
get only a how-to hint pill that vanished after ~6 s, so nobody
could finish the steps and no QGrab icon ever reached the home
screen. The fallback is now a proper install-guide bottom sheet:
server-rendered numbered steps (Android and iOS variants), a
visible close button, backdrop-tap / Escape to dismiss, and NO
auto-hide timer. The Android steps name both menu labels —
«Install app», falling back to «Add to Home screen» — so the flow
truly ends with the icon on the home screen.

Covered here:
  * install_app / install_hint_ios / install_hint_menu and the
    seven guide keys (install_guide_close, install_step_android_1..3,
    install_step_ios_1..3) exist, non-empty, in the raw dict of ALL
    30 languages (no silent English fallback),
  * the English Android steps carry the ⋮ glyph and both menu
    labels, and the final steps promise the home-screen icon,
  * the rendered homepage, a platform page and the tool page carry
    the button AND the sheet markup (dialog role, close button,
    both step lists, localised step text), the old hint pill is
    gone, and the install script still wires beforeinstallprompt /
    appinstalled / standalone handling with no auto-hide timer,
  * the served manifest parses and keeps display=standalone,
    start_url=/ and scope=/; every icon src answers 200 in the
    test client; the categories list is present; and the two
    screenshots entries point at files that exist on disk with
    exactly the declared pixel sizes (narrow 1080x1920, wide
    1920x1080) and matching form factors.

Run:  .venv/bin/python tests/test_install_button.py   (or pytest)
"""

import json
import os
import struct
import sys
from html import unescape

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402
import i18n  # noqa: E402

KEYS = ("install_app", "install_hint_ios", "install_hint_menu")
GUIDE_KEYS = ("install_guide_close",
              "install_step_android_1", "install_step_android_2",
              "install_step_android_3",
              "install_step_ios_1", "install_step_ios_2",
              "install_step_ios_3")
PAGES = ("/", "/youtube-video-downloader", "/video-to-script-prompt")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _raw_dict(code):
    return i18n.EN if code == "en" else i18n.TRANSLATIONS[code]


def test_install_strings_all_languages():
    assert len(i18n.LANG_CODES) == 30
    for code in i18n.LANG_CODES:
        raw = _raw_dict(code)
        for key in KEYS + GUIDE_KEYS:
            assert key in raw, (code, key, "missing from language dict")
            assert raw[key].strip(), (code, key, "empty")
        merged = i18n.get_strings(code)
        for key in KEYS + GUIDE_KEYS:
            assert merged[key].strip(), (code, key)
        # step 1 renders the menu glyph as text in every language
        assert "⋮" in raw["install_step_android_1"], code
    print("  install + guide strings present in all 30 languages")


def test_guide_step_content_english():
    en = i18n.EN
    # Android step 2 must cover BOTH menu labels, with the fallback
    # order, so a visitor whose menu has no «Install app» still
    # finishes with the icon on the home screen.
    a2 = en["install_step_android_2"]
    assert "Install app" in a2 and "Add to Home screen" in a2, a2
    # final steps (both platforms) end on the home screen
    assert "home screen" in en["install_step_android_3"]
    assert "home screen" in en["install_step_ios_3"]
    assert "Add to Home Screen" in en["install_step_ios_2"]
    print("  English guide steps: glyph, both labels, home-screen ending")


def test_install_sheet_and_script_rendered():
    client = qgrab.app.test_client()
    for path in PAGES:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        # unescape so dict strings with apostrophes (Jinja renders
        # them as &#39;) compare equal to the raw i18n values
        html = unescape(resp.get_data(as_text=True))
        # button + sheet markup ship together, on every button page
        assert 'id="installBtn"' in html, path
        assert 'id="installBackdrop"' in html, path
        assert 'id="installSheet"' in html, path
        assert 'role="dialog"' in html, path
        assert 'id="installStepsAndroid"' in html, path
        assert 'id="installStepsIos"' in html, path
        # visible close button for the sheet
        assert 'id="installSheetClose"' in html, path
        # the old auto-vanishing hint pill is gone
        assert 'id="installHint"' not in html, path
        assert "install-hint" not in html, path
        # English guide steps are rendered into the sheet
        assert i18n.EN["install_app"] in html, path
        assert i18n.EN["install_step_android_1"] in html, path
        assert i18n.EN["install_step_android_2"] in html, path
        assert i18n.EN["install_step_ios_2"] in html, path
        assert i18n.EN["install_guide_close"] in html, path
        # behaviour wiring is served with the page
        assert "beforeinstallprompt" in html, path
        assert "appinstalled" in html, path
        assert "display-mode: standalone" in html, path
        assert "openSheet" in html, path
        assert "closeSheet" in html, path
    # localised sheet follows the page language (title + steps)
    html = unescape(client.get("/?lang=ur").get_data(as_text=True))
    assert i18n.TRANSLATIONS["ur"]["install_app"] in html
    assert i18n.TRANSLATIONS["ur"]["install_step_android_2"] in html
    assert i18n.TRANSLATIONS["ur"]["install_step_ios_1"] in html
    print("  install button + guide sheet rendered on home/platform/tool (en+ur)")


def test_no_autohide_timer_remains():
    """The sheet must stay until closed: the install script may not
    carry the old 6-second hint timer (or any timer) at all."""
    with open(os.path.join(ROOT, "templates", "_installjs.html"),
              encoding="utf-8") as fh:
        js = fh.read()
    assert "setTimeout" not in js
    assert "installHint" not in js
    assert "6000" not in js
    assert "hintTimer" not in js
    print("  no auto-hide timer in the install script")


def _png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def test_manifest_pwa_contract():
    client = qgrab.app.test_client()
    resp = client.get("/static/manifest.webmanifest")
    assert resp.status_code == 200
    manifest = json.loads(resp.get_data(as_text=True))
    # defensive PWA contract: the fields that make the installed
    # app a real standalone home-screen app
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert "utilities" in manifest["categories"]
    # every icon the manifest promises must actually be served
    assert manifest["icons"], "manifest has no icons"
    for icon in manifest["icons"]:
        r = client.get(icon["src"])
        assert r.status_code == 200, (icon["src"], r.status_code)
    # screenshots for Chrome's richer install dialog: entries parse,
    # are served, and the files on disk match the declared sizes
    shots = manifest["screenshots"]
    assert len(shots) == 2
    by_factor = {s["form_factor"]: s for s in shots}
    assert set(by_factor) == {"narrow", "wide"}
    for factor, shot in by_factor.items():
        r = client.get(shot["src"])
        assert r.status_code == 200, (shot["src"], r.status_code)
        disk = os.path.join(ROOT, shot["src"].lstrip("/"))
        assert os.path.isfile(disk), disk
        want_w, want_h = (int(v) for v in shot["sizes"].split("x"))
        got_w, got_h = _png_size(disk)
        assert (got_w, got_h) == (want_w, want_h), (disk, got_w, got_h)
        if factor == "narrow":
            assert got_h > got_w, disk
        else:
            assert got_w > got_h, disk
    assert by_factor["narrow"]["sizes"] == "1080x1920"
    assert by_factor["wide"]["sizes"] == "1920x1080"
    print("  manifest: standalone contract, icons 200, screenshots verified")


if __name__ == "__main__":
    test_install_strings_all_languages()
    print("PASS install strings (30 languages)")
    test_guide_step_content_english()
    print("PASS guide step content")
    test_install_sheet_and_script_rendered()
    print("PASS install sheet rendered")
    test_no_autohide_timer_remains()
    print("PASS no auto-hide timer")
    test_manifest_pwa_contract()
    print("PASS manifest PWA contract")
    print("ALL INSTALL BUTTON TESTS PASS")
