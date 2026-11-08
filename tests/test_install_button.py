"""Tests for QGrab's install surface AFTER the owner's
2026-11-08.12 order: NO "Install App" button in the header.

The header used to carry a PWA Install App button
(_installbtn.html) on the homepage, the platform pages and the
Script+Prompt page, wired by _installjs.html, with an
install-guide bottom sheet as the no-prompt fallback. The owner
ordered the header button deleted outright ("khatam kar do"),
so the button, its script and the sheet it alone could open are
all retired. What remains, by design:

  * the homepage #install SECTION keeps its own button
    (id="installBtn", exactly one on the page) shown by the
    homepage's inline script when the browser fires
    beforeinstallprompt, plus the always-visible manual steps
    (install_li1..3),
  * the platform and tool pages carry no install button at all,
  * the PWA manifest contract is unchanged — the installed app
    itself is untouched; only the header entry point is gone.

Covered here:
  * the homepage install-section strings (install_btn,
    install_h2, install_p, install_li1..3) resolve non-empty in
    all 30 languages,
  * no page's <header> carries an install button / sheet markup;
    the homepage carries exactly one id="installBtn" and it sits
    inside the #install section; the other pages carry none;
    the retired partials are gone from disk,
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
import re
import struct
import sys
from html import unescape

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402
import i18n  # noqa: E402

SECTION_KEYS = ("install_btn", "install_h2", "install_p",
                "install_li1", "install_li2", "install_li3")
PAGES = ("/", "/youtube-video-downloader", "/video-to-script-prompt")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_install_section_strings_all_languages():
    assert len(i18n.LANG_CODES) == 30
    for code in i18n.LANG_CODES:
        merged = i18n.get_strings(code)
        for key in SECTION_KEYS:
            assert merged[key].strip(), (code, key, "empty")
    print("  install-section strings resolve in all 30 languages")


def test_header_has_no_install_button():
    client = qgrab.app.test_client()
    for path in PAGES:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        html = unescape(resp.get_data(as_text=True))
        hdr_m = re.search(r"<header>([\s\S]*?)</header>", html)
        assert hdr_m, path
        hdr = hdr_m.group(1)
        # the owner's order: nothing install-related in the header
        assert 'id="installBtn"' not in hdr, path
        assert "install-btn" not in hdr, path
        assert "installBackdrop" not in html, path
        assert "installSheet" not in html, path
        # right corner keeps theme toggle + three-dot menu cluster
        assert 'class="nav-right"' in hdr, path
        assert 'class="theme-toggle"' in hdr, path
        assert 'id="hmenuBtn"' in hdr, path
    # the other pages carry no install button anywhere
    for path in PAGES[1:]:
        html = client.get(path).get_data(as_text=True)
        assert 'id="installBtn"' not in html, path
        assert "beforeinstallprompt" not in html, path
    print("  headers clean on home/platform/tool; no stray buttons")


def test_homepage_install_section_button():
    client = qgrab.app.test_client()
    html = unescape(client.get("/").get_data(as_text=True))
    # exactly one install button on the homepage...
    assert html.count('id="installBtn"') == 1
    # ...and it lives inside the #install section
    sec_i = html.find('id="install"')
    btn_i = html.find('id="installBtn"')
    assert sec_i != -1 and btn_i > sec_i
    # the homepage's own prompt wiring is still served
    assert "beforeinstallprompt" in html
    assert "deferredInstall" in html
    assert "appinstalled" in html
    # manual steps render inside the section
    assert i18n.EN["install_li1"].split("<")[0][:20] in html
    print("  homepage #install section: one button + prompt wiring")


def test_retired_partials_gone():
    for name in ("_installbtn.html", "_installjs.html"):
        disk = os.path.join(ROOT, "templates", name)
        assert not os.path.exists(disk), disk
    print("  retired partials _installbtn/_installjs are gone")


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
    test_install_section_strings_all_languages()
    print("PASS install section strings (30 languages)")
    test_header_has_no_install_button()
    print("PASS header has no install button")
    test_homepage_install_section_button()
    print("PASS homepage install section")
    test_retired_partials_gone()
    print("PASS retired partials gone")
    test_manifest_pwa_contract()
    print("PASS manifest PWA contract")
    print("ALL INSTALL BUTTON TESTS PASS")
