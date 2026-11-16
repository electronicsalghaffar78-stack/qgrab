"""Round 7 (2026-11-16.27): extension-download fix +
subscribe removal + usage-section confirmation.

The owner tested .26 on his own laptop and reported:

  1. The PC extension download was BROKEN — Chrome said
     "qgrab-extension.zip — File wasn't available on site"
     (the ZIP binary never reached the code repo, so the
     static URL 404'd in production). Fix: app.py BUILDS the
     ZIP at runtime from the extension's text sources and
     serves it at the same URL; icon PNGs missing on disk
     (production) are generated in memory as valid PNGs.
  2. Subscribe is REMOVED ENTIRELY from the visitor-facing
     site — footer form AND the 3rd-download popup AND all
     subscribe copy. The /api/subscribe backend stays in
     app.py, dormant (nothing calls it; no email was ever
     sent — RESEND_API_KEY was never set).
  3. The "unlimited use" section: the "Today's free usage"
     card already went in .26; this round pins that no
     usage/unlimited section remains on the homepage.

Run:  .venv/bin/python tests/test_round7.py
"""
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("GEMINI_API_KEY", "test-key")
_TMPDIR = tempfile.mkdtemp(prefix="qgrab-r7-")
os.environ.setdefault("QGRAB_DATA_DIR", _TMPDIR)

import app as qgrab  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        print("FAIL", name, detail)
        FAILURES.append(name)


client = qgrab.app.test_client()
home = client.get("/").get_data(as_text=True)

# --- 1. the extension ZIP route --------------------------------
r = client.get("/static/downloads/qgrab-extension.zip")
check("extension zip serves 200", r.status_code == 200,
      str(r.status_code))
check("extension zip content-type",
      (r.headers.get("Content-Type") or "").startswith(
          "application/zip"), r.headers.get("Content-Type"))
check("extension zip attachment name",
      "qgrab-extension.zip" in (r.headers.get(
          "Content-Disposition") or ""))
check("homepage button still points at the same URL",
      'id="extDownload"' in home
      and 'href="/static/downloads/qgrab-extension.zip"' in home)

z = zipfile.ZipFile(io.BytesIO(r.data))
names = set(z.namelist())
expected = {"manifest.json", "background.js", "content.js",
            "popup.html", "popup.js", "README.md",
            "icons/icon-16.png", "icons/icon-32.png",
            "icons/icon-48.png", "icons/icon-128.png",
            "icons/icon-192.png"}
check("zip carries the full package", expected <= names,
      str(sorted(expected - names)))

manifest = json.loads(z.read("manifest.json"))
check("manifest parses, MV3", manifest.get("manifest_version") == 3)
check("manifest name is QGrab", "QGrab" in manifest.get("name", ""))

refs = set(manifest["icons"].values())
refs |= set(manifest["action"]["default_icon"].values())
refs.add(manifest["action"]["default_popup"])
refs.add(manifest["background"]["service_worker"])
for cs in manifest["content_scripts"]:
    refs |= set(cs["js"])
check("every manifest-referenced file is in the zip",
      refs <= names, str(sorted(refs - names)))


def png_dims(b):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", b[16:24])


for size in (16, 32, 48, 128, 192):
    dims = png_dims(z.read("icons/icon-%d.png" % size))
    check(f"icon-{size} is a valid {size}x{size} PNG",
          dims == (size, size), str(dims))

# --- 1b. production simulation: sources WITHOUT icon PNGs -----
# (the repo checkout carries no binaries, so on Render the icons
# directory is empty — the builder must generate valid icons)
sim = tempfile.mkdtemp(prefix="qgrab-ext-sim-")
for fname in qgrab._EXT_TEXT_FILES:
    shutil.copy(os.path.join(qgrab._EXT_DIR, fname),
                os.path.join(sim, fname))
data = qgrab._build_extension_zip(sim)
z2 = zipfile.ZipFile(io.BytesIO(data))
names2 = set(z2.namelist())
check("no-icons build still complete", refs <= names2,
      str(sorted(refs - names2)))
for size in (16, 32, 48, 128, 192):
    dims = png_dims(z2.read("icons/icon-%d.png" % size))
    check(f"generated icon-{size} valid {size}x{size} PNG",
          dims == (size, size), str(dims))


def png_pixel(b, x, y):
    w, _h = struct.unpack(">II", b[16:24])
    idat, off = b"", 8
    while off < len(b):
        ln, tag = struct.unpack(">I4s", b[off:off + 8])
        if tag == b"IDAT":
            idat += b[off + 8:off + 8 + ln]
        off += 12 + ln
    raw = zlib.decompress(idat)
    stride = 1 + w * 4
    o = y * stride + 1 + x * 4
    return tuple(raw[o:o + 4])


icon = z2.read("icons/icon-128.png")
check("generated icon corner is transparent",
      png_pixel(icon, 0, 0)[3] == 0)
check("generated icon body is QGrab red",
      png_pixel(icon, 64, 64)[:3] == (227, 45, 40))
check("generated icon ring is white",
      png_pixel(icon, 64 + 32, 64) == (255, 255, 255, 255))

# --- 2. subscribe UI: gone from every rendered page ------------
PAGES = ["/", "/youtube-video-downloader", "/telegram-proxies",
         "/video-to-script-prompt", "/download-history"]
for path in PAGES:
    page = client.get(path).get_data(as_text=True)
    check(f"{path}: no subscribe form", "js-sub-form" not in page
          and "subEmailFoot" not in page)
    check(f"{path}: no subscribe copy",
          "Daily updates by email" not in page
          and "Get daily updates" not in page)
    check(f"{path}: no subscribe popup machinery",
          "qgrabSubMaybeShow" not in page
          and "qgrab_subscribed" not in page)
    check(f"{path}: page does not reference /api/subscribe",
          "/api/subscribe" not in page)
    check(f"{path}: footer still renders",
          "foot-grid" in page and "<footer>" in page)
check("stats ping still shipped", "window.qgStat" in home
      and "/api/event" in home)

# --- 3. no usage / unlimited section on the homepage -----------
check("no Today's free usage card", "Today's free usage" not in home
      and "free usage" not in home)
check("no usage section anchor", 'id="usage"' not in home)

print(f"\n{len(FAILURES)} failures")
sys.exit(1 if FAILURES else 0)
