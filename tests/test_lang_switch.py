"""Regression tests for the language-switch bug found 2026-11-05.

The owner selected Urdu once, and afterwards could never switch
back to English: the language menu's English link pointed at the
bare path (lang_url returned `path` unchanged for "en"), so the
request carried no ?lang= parameter, _current_lang() fell back to
the year-long qgrab_lang cookie, and the site stayed in Urdu
forever. lang_url now returns "?lang=<code>" for EVERY language,
English included, so an explicit English choice renders English
and _persist_lang stores qgrab_lang=en like any other language.

Covers:
  * With a qgrab_lang=ur cookie, GET /?lang=en renders English
    (<html lang="en"> + the English UI strings) and the response
    persists qgrab_lang=en via Set-Cookie.
  * The rendered language menu links every language — English
    included — with an explicit ?lang=<code> parameter.
  * Sanity: the cookie path is untouched — with qgrab_lang=ur and
    no ?lang, the page still renders Urdu (RTL).

Note: the cookie is planted via the test client's set_cookie —
a hand-passed Cookie header is ignored by this client's jar.

Run:  .venv/bin/python tests/test_lang_switch.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as A  # noqa: E402


def ur_client():
    # A new client per section: the test client keeps a cookie jar,
    # and the Set-Cookie from a ?lang= response would otherwise leak
    # into later requests and change what is under test.
    c = A.app.test_client()
    c.set_cookie(A.i18n.COOKIE_NAME, "ur")
    return c


FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


# Per-language UI copy used as render evidence (the homepage H1 is
# deliberately English SEO copy in every language, so it cannot
# discriminate; the Download button text can).
EN_BTN = A.i18n.get_strings("en")["btn_download"]
UR_BTN = A.i18n.get_strings("ur")["btn_download"]

# ------------------------------------------------------------------
# Explicit ?lang=en beats a stored non-English cookie
# ------------------------------------------------------------------
r = ur_client().get("/?lang=en")
html = r.get_data(as_text=True)
check("GET /?lang=en with ur cookie is 200", r.status_code == 200,
      str(r.status_code))
check("renders English (<html lang=en, ltr)",
      '<html lang="en"' in html and 'dir="ltr"' in html,
      html[:120])
check("renders the English UI copy",
      EN_BTN in html and UR_BTN not in html)
sc = "; ".join(r.headers.getlist("Set-Cookie"))
check("response persists qgrab_lang=en", "qgrab_lang=en" in sc,
      sc[:160])

# ------------------------------------------------------------------
# Language menu: every link carries an explicit ?lang=<code>
# ------------------------------------------------------------------
r = ur_client().get("/")
html = r.get_data(as_text=True)
m = re.search(r'<a href="([^"]*\?lang=en)"[^>]*>English</a>', html)
check("menu English link carries ?lang=en", m is not None,
      "no ?lang=en English anchor found")
for code in ("ur", "ar", "hi"):
    check(f"menu link for {code} keeps ?lang={code}",
          f"?lang={code}" in html)

# ------------------------------------------------------------------
# Sanity: cookie path untouched (no ?lang -> cookie wins)
# ------------------------------------------------------------------
r = ur_client().get("/")
html = r.get_data(as_text=True)
check("GET / with ur cookie and no ?lang is 200",
      r.status_code == 200, str(r.status_code))
check("still renders Urdu (<html lang=ur, rtl)",
      '<html lang="ur"' in html and 'dir="rtl"' in html,
      html[:120])
check("renders the Urdu UI copy", UR_BTN in html)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL LANG SWITCH TESTS PASS")
