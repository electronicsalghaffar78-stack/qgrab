#!/usr/bin/env python3
"""
QGrab - all-in-one video downloader (v1).

A small Flask app:
  - GET  /            -> single-page UI
  - POST /api/info    -> {url} -> video metadata + format list (via yt-dlp)
  - GET  /download    -> streams the chosen format through this server

Downloads are proxied through the server (using the headers yt-dlp
reports for the media URL) so links that need a specific User-Agent /
Referer still work for the visitor.

Extraction is resilient to cloud-IP blocks: it walks a per-site cascade
of yt-dlp configurations (alternate YouTube player clients, curl_cffi
browser impersonation) until one returns formats — see "Extraction
engine" below.
"""

import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.request
import urllib.error
import uuid
from urllib.parse import quote, urlparse

from flask import Flask, request, jsonify, render_template, Response, abort, send_file
import yt_dlp

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "socket_timeout": 20,
}

MAX_FORMATS = 14


def clean_url(raw):
    """Basic validation of a user-supplied URL."""
    if not raw or not isinstance(raw, str):
        return None
    url = raw.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    if len(url) > 2048:
        return None
    return url


def human_size(num):
    if not num:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


# ---------------------------------------------------------------------------
# Extraction engine — client cascade + browser impersonation
#
# Cloud/datacenter IPs get blocked by some platforms in ways a home IP is
# not: YouTube answers "Sign in to confirm you're not a bot", TikTok
# serves a broken webpage ("Unexpected response from webpage request"),
# etc. To survive that, extraction tries an ordered list of yt-dlp
# configurations ("attempts") until one returns formats:
#
#   YouTube : default client -> player_client=tv -> android_vr ->
#             web_safari. Alternate player clients do not hit the same
#             bot wall as the default web client.
#   TikTok  : curl_cffi browser impersonation (chrome) first, plain as
#             fallback — impersonation is what fixes the broken-webpage
#             failure.
#   Facebook: plain first (it works), one impersonation retry on failure.
#   Others  : plain first, one impersonation retry only when the error
#             looks like a webpage/403-style block.
#
# Every attempt is bounded by YDL_OPTS["socket_timeout"] (20s), so even
# the 4-step YouTube cascade stays within ~80s of network stalls. The
# winning attempt is cached per URL for a few minutes so /download
# re-uses the exact configuration /api/info succeeded with instead of
# re-running the whole cascade.
# ---------------------------------------------------------------------------

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget

    _CHROME_TARGET = ImpersonateTarget.from_str("chrome")
    HAS_IMPERSONATION = True
except Exception:  # curl_cffi not installed — degrade gracefully
    _CHROME_TARGET = None
    HAS_IMPERSONATION = False

# YouTube player clients tried after the default, in order.
YOUTUBE_CLIENT_CASCADE = (None, "tv", "android_vr", "web_safari")

# The only extraction error a visitor ever sees; raw yt-dlp errors are
# logged server-side instead of leaked to the page.
FRIENDLY_ERROR = (
    "This link could not be read — the platform may be limiting our "
    "server right now. Please try again later."
)

_WINNER_TTL = 600  # seconds a winning attempt config is reused per URL
_winner_cache = {}  # url -> (spec dict, expiry timestamp)
_winner_lock = threading.Lock()

_WEBPAGE_ERROR_HINTS = (
    "webpage", "403", "forbidden", "http error", "unable to download",
    "sign in to confirm", "not a bot", "blocked", "captcha",
)


def site_of(url):
    host = (urlparse(url).hostname or "").lower()
    if "youtube" in host or host == "youtu.be":
        return "youtube"
    if "tiktok" in host:
        return "tiktok"
    if "facebook" in host or host == "fb.watch":
        return "facebook"
    return "other"


def _attempt_plan(url):
    """Ordered attempt specs for a URL.

    A spec is {"client": <YouTube player_client or None>,
               "impersonate": bool,
               "webpage_errors_only": bool (optional — only try this
               attempt if the previous failure looked like a block)}.
    """
    site = site_of(url)
    if site == "youtube":
        return [{"client": c, "impersonate": False}
                for c in YOUTUBE_CLIENT_CASCADE]
    if site == "tiktok":
        plan = []
        if HAS_IMPERSONATION:
            plan.append({"client": None, "impersonate": True})
        plan.append({"client": None, "impersonate": False})
        return plan
    if site == "facebook":
        plan = [{"client": None, "impersonate": False}]
        if HAS_IMPERSONATION:
            plan.append({"client": None, "impersonate": True})
        return plan
    plan = [{"client": None, "impersonate": False}]
    if HAS_IMPERSONATION:
        plan.append({"client": None, "impersonate": True,
                     "webpage_errors_only": True})
    return plan


def _build_opts(spec, extra=None):
    opts = dict(YDL_OPTS)
    if spec.get("client"):
        opts["extractor_args"] = {
            "youtube": {"player_client": [spec["client"]]}
        }
    if spec.get("impersonate") and _CHROME_TARGET is not None:
        opts["impersonate"] = _CHROME_TARGET
    if extra:
        opts.update(extra)
    return opts


def _spec_key(spec):
    return (spec.get("client"), bool(spec.get("impersonate")))


def _ordered_attempts(url):
    """Cached winner first (if fresh), then the full plan, de-duplicated."""
    plan = _attempt_plan(url)
    with _winner_lock:
        hit = _winner_cache.get(url)
    if hit and hit[1] > time.time():
        winner = hit[0]
        plan = [winner] + [s for s in plan
                           if _spec_key(s) != _spec_key(winner)]
    return plan


def _remember_winner(url, spec):
    with _winner_lock:
        _winner_cache[url] = (dict(spec), time.time() + _WINNER_TTL)


def _cascade_gate_open(spec, last_error):
    """A 'webpage_errors_only' attempt runs only after a block-style error."""
    if not spec.get("webpage_errors_only") or last_error is None:
        return True
    msg = str(last_error).lower()
    return any(h in msg for h in _WEBPAGE_ERROR_HINTS)


def _has_formats(info):
    if not info:
        return False
    if info.get("formats"):
        return True
    entries = [e for e in info.get("entries") or [] if e]
    return bool(entries and entries[0].get("formats"))


def extract_info(url):
    """Extract metadata, walking the attempt cascade until one attempt
    returns formats. Raises the last error if every attempt fails."""
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        try:
            with yt_dlp.YoutubeDL(_build_opts(spec)) as ydl:
                info = ydl.extract_info(url, download=False)
            if not _has_formats(info):
                # Page "loaded" but empty — from a blocked IP this is
                # the bot wall wearing a disguise; keep cascading.
                raise yt_dlp.utils.DownloadError(
                    "Extractor returned no formats "
                    "(webpage may have been blocked)")
            _remember_winner(url, spec)
            return info
        except Exception as e:  # DownloadError or network error
            last_error = e
            app.logger.info(
                "extract attempt failed (client=%s impersonate=%s) "
                "for %s: %s",
                spec.get("client"), spec.get("impersonate"), url, e)
    if last_error is not None:
        raise last_error
    raise yt_dlp.utils.DownloadError("No extraction attempt was made.")


def pick_formats(info):
    """Turn yt-dlp's raw format list into a clean, user-friendly list."""
    combined, video_only, audio_only = [], [], []
    for f in info.get("formats", []):
        if not f.get("url"):
            continue
        proto = (f.get("protocol") or "")
        if proto.startswith("m3u8") and f.get("ext") not in ("mp4",):
            # HLS streams can't be proxied as a single file download in v1.
            continue
        has_v = f.get("vcodec") not in (None, "none")
        has_a = f.get("acodec") not in (None, "none")
        height = f.get("height") or 0
        size = f.get("filesize") or f.get("filesize_approx")
        item = {
            "id": f.get("format_id"),
            "ext": f.get("ext") or "mp4",
            "height": height,
            "size": size,
            "size_h": human_size(size),
            "note": f.get("format_note") or "",
        }
        if has_v and has_a:
            item["kind"] = "video+audio"
            item["label"] = f"{height}p" if height else (f.get("format_note") or "Video")
            combined.append(item)
        elif has_v:
            item["kind"] = "video"
            item["label"] = f"{height}p" if height else (f.get("format_note") or "Video")
            video_only.append(item)
        elif has_a:
            item["kind"] = "audio"
            abr = f.get("abr") or 0
            item["label"] = f"Audio {int(abr)}kbps" if abr else "Audio"
            audio_only.append(item)
    combined.sort(key=lambda x: x["height"], reverse=True)
    video_only.sort(key=lambda x: x["height"], reverse=True)
    audio_only.sort(key=lambda x: x["label"], reverse=True)

    # Many sites (YouTube especially) now serve ONLY split video/audio
    # streams. Offer "merged" options for those: when picked, /download
    # fetches best video + best audio and joins them with ffmpeg into one
    # mp4 with sound. Capped at 1080p to keep files and merge time sane.
    merged = []
    if video_only and audio_only:
        seen = set()
        for v in video_only:
            h = v["height"]
            if h and h <= 1080 and h not in seen:
                seen.add(h)
                merged.append({
                    "id": f"merge:{h}",
                    "ext": "mp4",
                    "height": h,
                    "size": None,
                    "size_h": None,
                    "note": "merged on download",
                    "kind": "video+audio",
                    "label": f"{h}p",
                })
            if len(merged) >= 4:
                break

    # Merged + combined (with sound) first, then video-only, then audio.
    return (merged + combined + video_only[:5] + audio_only[:3])[:MAX_FORMATS]


def safe_filename(title, ext):
    name = re.sub(r"[^\w\s.-]+", "", title or "video", flags=re.UNICODE).strip()
    name = re.sub(r"\s+", " ", name)[:80].strip() or "video"
    return f"{name}.{ext}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/dmca")
def dmca():
    return render_template("dmca.html")


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", ""))
    if not url:
        return jsonify({"error": "Please paste a valid video link (http/https)."}), 400
    try:
        info = extract_info(url)
    except Exception as e:
        # Raw yt-dlp errors (bot walls, extractor internals) stay in the
        # server log; visitors get one short, friendly message.
        app.logger.warning("info failed for %s: %s", url, e)
        return jsonify({"error": FRIENDLY_ERROR}), 422

    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if entries:
            info = entries[0]

    return jsonify({
        "title": info.get("title") or "Untitled",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "duration_h": info.get("duration_string"),
        "site": info.get("extractor_key") or info.get("extractor"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or url,
        "formats": pick_formats(info),
    })


def download_merged(url, height):
    """Download best video (<= height) + best audio and merge with ffmpeg.

    Walks the same attempt cascade as extract_info() — cached winner
    first — so the merged download uses a client/impersonation combo
    that can actually read the page from this server's IP.
    """
    fmt = (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={height}]+bestaudio"
        f"/best[height<={height}]"
    )
    info = path = tmpdir = None
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        tmpdir = tempfile.mkdtemp(prefix="qgrab-")
        outtmpl = os.path.join(tmpdir, f"{uuid.uuid4().hex}.%(ext)s")
        opts = _build_opts(spec, {
            "format": fmt,
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
                if not os.path.exists(path):  # merged file may differ in ext
                    path = os.path.splitext(path)[0] + ".mp4"
        except Exception as e:
            last_error = e
            app.logger.info(
                "merged attempt failed (client=%s impersonate=%s) "
                "for %s: %s",
                spec.get("client"), spec.get("impersonate"), url, e)
            shutil.rmtree(tmpdir, ignore_errors=True)
            info = path = tmpdir = None
            continue
        if not os.path.exists(path):
            app.logger.info(
                "merged attempt produced no file (client=%s) for %s",
                spec.get("client"), url)
            shutil.rmtree(tmpdir, ignore_errors=True)
            info = path = tmpdir = None
            continue
        _remember_winner(url, spec)
        break
    if not path:
        if last_error is not None:
            app.logger.warning("merged download failed for %s: %s",
                               url, last_error)
        abort(502, "Could not prepare that merged download.")

    filename = safe_filename(info.get("title"), "mp4")
    resp = send_file(path, as_attachment=True, download_name=filename,
                     mimetype="video/mp4")

    @resp.call_on_close
    def _cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    return resp


@app.route("/download")
def download():
    url = clean_url(request.args.get("url", ""))
    format_id = request.args.get("format_id", "")
    if not url or not format_id:
        abort(400, "Missing url or format_id")

    if format_id.startswith("merge:"):
        try:
            height = int(format_id.split(":", 1)[1])
        except (IndexError, ValueError):
            abort(400, "Bad format_id")
        return download_merged(url, height)

    try:
        info = extract_info(url)
    except Exception as e:
        app.logger.warning("download re-check failed for %s: %s", url, e)
        abort(422, FRIENDLY_ERROR)

    target = None
    for f in info.get("formats", []):
        if str(f.get("format_id")) == str(format_id) and f.get("url"):
            target = f
            break
    if target is None:
        abort(404, "That format is no longer available.")

    media_url = target["url"]
    headers = dict(target.get("http_headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/124.0 Safari/537.36")
    # Pass through byte-range requests so downloads can resume / seek.
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    req = urllib.request.Request(media_url, headers=headers, method="GET")
    try:
        upstream = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        abort(502, f"Upstream returned {e.code}")
    except Exception:
        abort(502, "Could not reach the media server.")

    ext = target.get("ext") or "mp4"
    filename = safe_filename(info.get("title"), ext)
    ascii_name = filename.encode("ascii", "ignore").decode() or f"video.{ext}"

    resp_headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Content-Type": upstream.headers.get("Content-Type", "application/octet-stream"),
    }
    for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if upstream.headers.get(h):
            resp_headers[h] = upstream.headers[h]

    def stream():
        try:
            while True:
                chunk = upstream.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return Response(stream(), status=upstream.status, headers=resp_headers)


@app.route("/sw.js")
def service_worker():
    # The service worker must be served from the root path so its scope
    # covers the whole site (a worker under /static/ could not).
    resp = send_file(os.path.join(app.static_folder, "sw.js"),
                     mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, threaded=True)
