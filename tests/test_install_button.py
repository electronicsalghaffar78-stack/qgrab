"""Tests for the PWA "Install App" header button.

Chrome/Android no longer shows an automatic install banner and the
site never captured beforeinstallprompt, so visitors saw no install
option at all. The header now carries a visible Install App button
(_installbtn.html) on the homepage, the platform pages and the
Script+Prompt page; _installjs.html captures the prompt event and
fires it from the button, falls back to a localised how-to hint on
browsers without the event (iOS Safari / other menus), and hides
the button when the app is already installed / running standalone.

Covered here:
  * install_app / install_hint_ios / install_hint_menu exist,
    non-empty, in the raw dict of ALL 30 languages (no silent
    English fallback for a forgotten language),
  * every I18N.<key> _installjs.html references is shipped by
    _js_strings() — the toast regression pattern (a key translated
    in i18n.py but missing from the whitelist reaches the page as
    undefined and the feature silently dies),
  * the rendered homepage, a platform page and the tool page carry
    the button (with the localised label + hint data attributes),
    the install script (beforeinstallprompt / appinstalled /
    standalone handling) and a rendered I18N carrying the hints.

Run:  .venv/bin/python tests/test_install_button.py   (or pytest)
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as qgrab  # noqa: E402
import i18n  # noqa: E402

KEYS = ("install_app", "install_hint_ios", "install_hint_menu")
PAGES = ("/", "/youtube-video-downloader", "/video-to-script-prompt")


def test_install_strings_all_languages():
    assert len(i18n.LANG_CODES) == 30
    for code in i18n.LANG_CODES:
        raw = i18n.EN if code == "en" else i18n.TRANSLATIONS[code]
        for key in KEYS:
            assert key in raw, (code, key, "missing from language dict")
            assert raw[key].strip(), (code, key, "empty")
        merged = i18n.get_strings(code)
        for key in KEYS:
            assert merged[key].strip(), (code, key)
    print("  install strings present in all 30 languages")


def test_install_i18n_keys_reach_the_page():
    """Toast-regression pattern: _installjs.html reads
    I18N.install_hint_ios / I18N.install_hint_menu — both must be
    shipped by _js_strings() and rendered, or the hint silently
    never shows."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "templates", "_installjs.html"),
              encoding="utf-8") as fh:
        js = fh.read()
    referenced = set(re.findall(r"I18N\.([A-Za-z_]+)", js))
    assert {"install_hint_ios", "install_hint_menu"} <= referenced
    for lang in ("en", "ur"):
        shipped = qgrab._js_strings(qgrab.i18n.get_strings(lang))
        missing = referenced - set(shipped)
        assert not missing, (lang, sorted(missing))
        for key in referenced:
            assert shipped[key].strip(), (lang, key)
    client = qgrab.app.test_client()
    for path in ("/", "/?lang=ur", "/video-to-script-prompt",
                 "/video-to-script-prompt?lang=ur"):
        html = client.get(path).get_data(as_text=True)
        m = re.search(r"const I18N = (\{.*?\});", html, re.S)
        assert m, path
        page_i18n = json.loads(m.group(1))
        for key in ("install_hint_ios", "install_hint_menu"):
            assert page_i18n.get(key, "").strip(), (path, key)
    print("  install I18N keys shipped + rendered OK")


def test_install_button_and_script_rendered():
    client = qgrab.app.test_client()
    for path in PAGES:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        html = resp.get_data(as_text=True)
        assert 'id="installBtn"' in html, path
        assert 'id="installHint"' in html, path
        assert i18n.EN["install_app"] in html, path
        assert "data-hint-ios" in html, path
        assert "data-hint-menu" in html, path
        # behaviour wiring is served with the page
        assert "beforeinstallprompt" in html, path
        assert "appinstalled" in html, path
        assert "display-mode: standalone" in html, path
    # localised label follows the page language
    html = client.get("/?lang=ur").get_data(as_text=True)
    assert i18n.TRANSLATIONS["ur"]["install_app"] in html
    print("  install button + script rendered on home/platform/tool (en+ur)")


if __name__ == "__main__":
    test_install_strings_all_languages()
    print("PASS install strings (30 languages)")
    test_install_i18n_keys_reach_the_page()
    print("PASS install I18N keys reach the page (toast regression pattern)")
    test_install_button_and_script_rendered()
    print("PASS install button rendered")
    print("ALL INSTALL BUTTON TESTS PASS")
