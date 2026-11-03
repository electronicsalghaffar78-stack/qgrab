"""Regression tests for the 2026-11-04 full-site audit fixes.

Covers:
  * Security headers on HTML and error responses (the app set
    none; Mozilla Observatory graded the live site D/30).
  * Scoped long-cache for /static/ assets (manifest excluded).
  * Secure + HttpOnly flags on the language and rated cookies.
  * The SP per-IP rate limiter's atomic take/give-back (the old
    check-then-record pair could overshoot under concurrency)
    and its rejection refund via the daily-limit path.
  * HTML validity fixes the W3C Nu validator flagged: the result
    thumbnail <img> now carries a src, heading levels never skip
    (result title h2, SP pane headings h2, footer headings h3).
  * The service worker only refreshes its cached "/" shell from
    the homepage itself.

Run:  .venv/bin/python tests/test_audit_regressions.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as A  # noqa: E402

client = A.app.test_client()
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


# ------------------------------------------------------------------
# Security headers
# ------------------------------------------------------------------
EXPECTED = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=()",
}
for path in ("/", "/video-to-script-prompt", "/nonexistent-404"):
    r = client.get(path)
    for h, frag in EXPECTED.items():
        check(f"header {h} on {path}",
              frag in (r.headers.get(h) or ""),
              f"got {r.headers.get(h)!r}")

# ------------------------------------------------------------------
# Static caching scope
# ------------------------------------------------------------------
# Any real file under /static/ (the deploy repo generates its
# PNG icons at image-build time, so pick whatever ships here).
_static_pick = None
for _root, _dirs, _files in os.walk(A.app.static_folder):
    for _f in _files:
        if not _f.endswith(".webmanifest"):
            _static_pick = os.path.relpath(
                os.path.join(_root, _f), A.app.static_folder)
            break
    if _static_pick:
        break
r = client.get("/static/" + _static_pick.replace(os.sep, "/"))
check("static asset gets week-long cache",
      r.status_code == 200
      and "max-age=604800" in (r.headers.get("Cache-Control") or ""),
      f"{_static_pick}: {r.status_code} "
      f"{r.headers.get('Cache-Control')}")
r = client.get("/static/manifest.webmanifest")
check("manifest is NOT long-cached",
      "max-age=604800" not in (r.headers.get("Cache-Control") or ""),
      r.headers.get("Cache-Control"))
r = client.get("/")
check("HTML is NOT long-cached",
      "max-age=604800" not in (r.headers.get("Cache-Control") or ""),
      r.headers.get("Cache-Control"))
r = client.get("/sw.js")
check("sw.js keeps no-cache",
      "no-cache" in (r.headers.get("Cache-Control") or ""),
      r.headers.get("Cache-Control"))

# ------------------------------------------------------------------
# Cookie flags
# ------------------------------------------------------------------
r = client.get("/?lang=ur")
sc = "; ".join(r.headers.getlist("Set-Cookie"))
check("lang cookie Secure+HttpOnly",
      "qgrab_lang=" in sc and "Secure" in sc and "HttpOnly" in sc,
      sc[:160])

r = client.post("/api/rate", json={"stars": 5, "name": "Audit",
                                   "text": "regression test"})
sc = "; ".join(r.headers.getlist("Set-Cookie"))
check("rate POST ok", r.status_code == 200, str(r.status_code))
check("rated cookie Secure+HttpOnly",
      "qgrab_rated=" in sc and "Secure" in sc and "HttpOnly" in sc,
      sc[:160])

# ------------------------------------------------------------------
# Rate limiter: atomic take / give-back / window pruning
# ------------------------------------------------------------------
ip = "203.0.113.77"
A._sp_hits.pop(ip, None)
takes = [A._sp_rate_try_take(ip) for _ in range(A.SP_RATE_LIMIT + 1)]
check("limiter admits exactly SP_RATE_LIMIT takes",
      takes == [True] * A.SP_RATE_LIMIT + [False], str(takes))
A._sp_rate_give_back(ip)
check("give-back restores one take", A._sp_rate_try_take(ip) is True)
check("limiter full again after re-take",
      A._sp_rate_try_take(ip) is False)

old_ip = "203.0.113.78"
A._sp_hits[old_ip] = [0.0] * (A.SP_RATE_LIMIT + 5)  # all expired
check("expired hits are pruned, take allowed",
      A._sp_rate_try_take(old_ip) is True)
check("expired hits replaced by the fresh one",
      len(A._sp_hits[old_ip]) == 1, str(A._sp_hits[old_ip]))

# ------------------------------------------------------------------
# HTML validity (the W3C-flagged shapes)
# ------------------------------------------------------------------
def heading_levels(html):
    return [int(m) for m in re.findall(r"<h([1-6])[\s>]", html)]


for path in ("/", "/youtube-video-downloader",
             "/video-to-script-prompt", "/terms"):
    html = client.get(path).get_data(as_text=True)
    check(f"{path}: exactly one <h1>",
          len(re.findall(r"<h1[\s>]", html)) == 1)
    levels = heading_levels(html)
    skips = [(a, b) for a, b in zip(levels, levels[1:]) if b > a + 1]
    check(f"{path}: heading levels never skip", not skips,
          f"levels={levels} skips={skips}")
    check(f"{path}: no <h4> left", "<h4" not in html)

for path in ("/", "/youtube-video-downloader"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'<img id="rThumb"[^>]*>', html)
    check(f"{path}: rThumb img carries a src",
          bool(m) and "src=" in m.group(0), m.group(0) if m else "absent")
    check(f"{path}: result title is an <h2>",
          '<h2 id="rTitle">' in html)

# ------------------------------------------------------------------
# Service worker guard
# ------------------------------------------------------------------
sw = client.get("/sw.js").get_data(as_text=True)
check("sw caches the shell only from the homepage",
      'url.pathname === "/"' in sw)
check("sw cache version bumped past v4", "qgrab-shell-v5" in sw)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL AUDIT REGRESSION TESTS PASS")
