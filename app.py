#!/usr/bin/env python3
"""
QGrab - all-in-one video downloader (v1).

A small Flask app:
  - GET  /            -> single-page UI
  - POST /api/info    -> {url} -> video metadata + format list (via yt-dlp)
  - GET  /download    -> streams the chosen format through this server

Downloads are proxied through the server (using the headers yt-dlp
reports for the media URL) so links that need a specific User-Agent /
Referer still work for the visitor. When the proxied fetch fails
anyway — some CDNs bind the media URL to the extraction session — a
last-resort fallback lets yt-dlp download the file natively instead
(see _download_via_ytdlp).

Optionally, a YouTube session cookie file can be supplied through
the QGRAB_YT_COOKIES_B64 environment variable — see "YouTube session
cookies" below.

Extraction is resilient to cloud-IP blocks: it walks a per-site cascade
of yt-dlp configurations (alternate YouTube player clients, curl_cffi
browser impersonation) until one returns formats — see "Extraction
engine" below. When every yt-dlp attempt still fails for a YouTube
URL, a public Invidious instance is asked instead (no cookies, no
sign-in) — see "Invidious fallback" below and
YOUTUBE-FALLBACK-REPORT.md.
"""

import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import urllib.error
import uuid
from urllib.parse import parse_qs, quote, urlparse

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

# curl_cffi's own requests API, used directly by the /download proxy:
# some CDNs (TikTok's) fingerprint the TLS handshake of the media fetch
# itself, so extraction succeeding via impersonation is not enough —
# the bytes must be fetched with an impersonated client too.
try:
    from curl_cffi import requests as _cffi_requests

    HAS_CFFI_REQUESTS = True
except Exception:  # curl_cffi not installed — proxy falls back to urllib
    _cffi_requests = None
    HAS_CFFI_REQUESTS = False

# ---------------------------------------------------------------------------
# Optional YouTube session cookies — QGRAB_YT_COOKIES_B64 (env var only)
#
# YouTube's bot wall blocks some cloud IPs outright, where no player
# client trick helps. As an optional escape hatch the operator can
# supply the Netscape-format cookies.txt of a YouTube session (exported
# from a browser signed in with a SPARE account) base64-encoded in
# the QGRAB_YT_COOKIES_B64 environment variable. That value is a LIVE
# SESSION credential: it belongs only in the host's environment
# settings, must NEVER be committed to git or written into any file
# in this repo, and the cookie values are never logged — only whether
# they were configured (and how many). At startup the value is
# decoded once into a private temp file (mode 0600) and handed to
# yt-dlp as "cookiefile" for YouTube URLs only — see _build_opts.
# Sessions expire and Google rotates these cookies, so the variable
# must be refreshed with a fresh export whenever YouTube starts
# answering with the bot message again. Absent or invalid value =
# exactly the behaviour the app has without cookies.
# ---------------------------------------------------------------------------

YT_COOKIEFILE = None  # path of the decoded cookie file, or None


def _is_youtube_url(url):
    """True only for youtube.com / youtu.be and their subdomains."""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h)
               for h in ("youtube.com", "youtu.be"))


def _load_yt_cookies():
    """Decode QGRAB_YT_COOKIES_B64 into a private temp file, once."""
    global YT_COOKIEFILE
    raw = (os.environ.get("QGRAB_YT_COOKIES_B64") or "").strip()
    if not raw:
        app.logger.info("YouTube session cookies configured: no")
        return
    try:
        text = base64.b64decode(raw, validate=True).decode("utf-8")
    except Exception:
        app.logger.warning(
            "QGRAB_YT_COOKIES_B64 is set but is not valid base64 "
            "UTF-8; ignoring it. "
            "YouTube session cookies configured: no")
        return
    # Cookie lines are the tab-separated ones; "#HttpOnly_" lines are
    # cookies too, other "#" lines are comments.
    count = sum(
        1 for line in text.splitlines()
        if line.strip()
        and (not line.startswith("#") or line.startswith("#HttpOnly_")))
    fd, path = tempfile.mkstemp(prefix="qgrab-yt-cookies-",
                                suffix=".txt")
    try:
        os.fchmod(fd, 0o600)  # mkstemp already uses 0600; be explicit
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        app.logger.warning(
            "Could not write the YouTube session cookie file; "
            "continuing without cookies. "
            "YouTube session cookies configured: no")
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    YT_COOKIEFILE = path
    app.logger.info(
        "YouTube session cookies configured: yes (%d cookies)", count)


_load_yt_cookies()

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


def _build_opts(spec, extra=None, url=None):
    opts = dict(YDL_OPTS)
    if spec.get("client"):
        opts["extractor_args"] = {
            "youtube": {"player_client": [spec["client"]]}
        }
    if spec.get("impersonate") and _CHROME_TARGET is not None:
        opts["impersonate"] = _CHROME_TARGET
    if extra:
        opts.update(extra)
    if url and YT_COOKIEFILE and _is_youtube_url(url):
        # The optional session cookies are for YouTube only — they
        # must never ride along on another platform's requests.
        opts["cookiefile"] = YT_COOKIEFILE
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


# ---------------------------------------------------------------------------
# Invidious fallback — YouTube only, no cookies / no sign-in / no payment
#
# When every yt-dlp attempt fails for a YouTube URL (the cloud-IP bot
# wall: "Sign in to confirm you're not a bot"), QGrab asks a public
# Invidious instance instead. Invidious is an open-source alternative
# YouTube front-end; with ?local=true its API returns the video's
# formats with stream URLs rewritten so the bytes are proxied through
# the instance itself (its /videoplayback endpoint 307-redirects to a
# companion proxy host) — which is what makes them fetchable from a
# datacenter IP that googlevideo.com would refuse directly, because
# the signed URLs are bound to the instance's IP, not ours.
#
# Verified live on 2026-11-03 (full evidence in
# YOUTUBE-FALLBACK-REPORT.md): https://yt.chocolatemoo53.com was the
# ONLY instance on the public api.invidious.io list with its API
# enabled, and it delivered real, ffprobe-verified video+audio
# streams for 5 of 6 test videos (one popular video answered with a
# stale cached URL — "Videoplayback URL has expired" — and simply
# falls through to the same friendly error as before). Public
# instances come and go, so the list is overridable with the
# QGRAB_INVIDIOUS_INSTANCES env var (comma-separated base URLs).
#
# Routes evaluated the same day and rejected: Cobalt — the official
# api.cobalt.tools no longer lists YouTube among its services and
# demands JWT/Turnstile auth (error.api.auth.jwt.missing); community
# instances demand the same auth or answer error.api.youtube.login.
# Piped — its public instances were bot-blocked by YouTube
# themselves (SignInConfirmNotBotException).
# ---------------------------------------------------------------------------

INVIDIOUS_INSTANCES = tuple(
    u.strip().rstrip("/")
    for u in (os.environ.get("QGRAB_INVIDIOUS_INSTANCES")
              or "https://yt.chocolatemoo53.com").split(",")
    if u.strip()
)

_INVIDIOUS_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
}


def _youtube_video_id(url):
    """Extract the 11-char video id from any YouTube URL shape
    (watch?v=, youtu.be/, /shorts/, /embed/, /live/, /v/)."""
    if not _is_youtube_url(url):
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    candidate = ""
    if host == "youtu.be" or host.endswith(".youtu.be"):
        candidate = parsed.path.lstrip("/").split("/")[0]
    else:
        values = parse_qs(parsed.query).get("v")
        if values:
            candidate = values[0]
        else:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "embed",
                                                "live", "v"):
                candidate = parts[1]
    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    return None


def _http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=_INVIDIOUS_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _invidious_raw(video_id):
    """Ask each configured Invidious instance for a video's formats
    (locally-proxied stream URLs). Returns (instance_base, raw_json);
    raises the last error when no instance answers usefully."""
    last_error = None
    for base in INVIDIOUS_INSTANCES:
        api_url = f"{base}/api/v1/videos/{video_id}?local=true"
        try:
            data = _http_get_json(api_url)
        except Exception as e:
            last_error = e
            app.logger.info("invidious info failed via %s: %s", base, e)
            continue
        if data.get("error"):
            last_error = yt_dlp.utils.DownloadError(
                f"Invidious error via {base}: {data.get('error')}")
            continue
        if data.get("formatStreams") or data.get("adaptiveFormats"):
            return base, data
        last_error = yt_dlp.utils.DownloadError(
            f"Invidious returned no formats via {base}")
    if last_error is not None:
        raise last_error
    raise yt_dlp.utils.DownloadError("No Invidious instance configured.")


def _parse_height(fmt):
    """Best-effort pixel height from an Invidious format entry."""
    for key in ("height",):
        try:
            if fmt.get(key):
                return int(fmt[key])
        except (TypeError, ValueError):
            pass
    for key in ("resolution", "qualityLabel"):
        m = re.match(r"(\d+)p", str(fmt.get(key) or ""))
        if m:
            return int(m.group(1))
    return 0


def _shape_invidious_info(base, data, url):
    """Shape an Invidious API answer into the yt-dlp-style info dict
    the rest of the app (pick_formats, /download) already consumes.
    Format urls are the instance-proxied ones (?local=true), so the
    existing /download proxy can fetch them like any media URL."""
    formats = {}

    def _add(entry):
        fid = str(entry["format_id"])
        old = formats.get(fid)
        if old is None or (entry.get("filesize") or 0) > \
                (old.get("filesize") or 0):
            formats[fid] = entry

    for f in data.get("formatStreams") or []:
        # Muxed (video+audio in one file) formats.
        if not f.get("url") or f.get("itag") is None:
            continue
        size = None
        try:
            size = int(f.get("contentLength") or f.get("clen") or 0) or None
        except (TypeError, ValueError):
            pass
        _add({
            "format_id": str(f["itag"]),
            "url": f["url"],
            "ext": f.get("container") or "mp4",
            "protocol": "https",
            "vcodec": "avc1",
            "acodec": "mp4a",
            "height": _parse_height(f),
            "filesize": size,
            "format_note": f.get("qualityLabel") or "",
        })
    for f in data.get("adaptiveFormats") or []:
        # Split video-only / audio-only formats.
        if not f.get("url") or f.get("itag") is None:
            continue
        mime = f.get("type") or ""
        is_video = mime.startswith("video/")
        is_audio = mime.startswith("audio/")
        if not (is_video or is_audio):
            continue
        size = None
        try:
            size = int(f.get("contentLength") or f.get("clen") or 0) or None
        except (TypeError, ValueError):
            pass
        _add({
            "format_id": str(f["itag"]),
            "url": f["url"],
            "ext": f.get("container") or ("mp4" if is_video else "m4a"),
            "protocol": "https",
            "vcodec": ("avc1" if "avc1" in mime else "vp9")
                      if is_video else "none",
            "acodec": "mp4a" if is_audio else "none",
            "height": _parse_height(f) if is_video else 0,
            "filesize": size,
            # Invidious reports bitrate as a string on some formats.
            "abr": (int(f.get("bitrate") or 0) / 1000
                    if is_audio else None),
            "format_note": f.get("resolution") or "",
        })

    thumbs = data.get("videoThumbnails") or []
    thumbnail = None
    for quality in ("maxres", "sddefault", "high", "medium", "default"):
        for t in thumbs:
            if t.get("quality") == quality and t.get("url"):
                thumbnail = t["url"]
                break
        if thumbnail:
            break
    if not thumbnail and thumbs:
        thumbnail = thumbs[0].get("url")

    duration = data.get("lengthSeconds")
    duration_string = None
    if duration:
        duration_string = f"{int(duration) // 60}:{int(duration) % 60:02d}"

    return {
        "id": data.get("videoId"),
        "title": data.get("title") or "Untitled",
        "thumbnail": thumbnail,
        "duration": duration,
        "duration_string": duration_string,
        "uploader": data.get("author"),
        "webpage_url": url,
        "extractor_key": "Youtube",
        "formats": list(formats.values()),
        "_qgrab_source": "invidious",
        "_qgrab_instance": base,
    }


def _extract_info_invidious(url):
    """extract_info()'s YouTube last resort: metadata + formats from
    a public Invidious instance instead of yt-dlp."""
    video_id = _youtube_video_id(url)
    if not video_id:
        raise yt_dlp.utils.DownloadError(
            "Could not find a video id in that YouTube URL.")
    base, data = _invidious_raw(video_id)
    info = _shape_invidious_info(base, data, url)
    if not _has_formats(info):
        raise yt_dlp.utils.DownloadError(
            "Invidious returned no usable formats.")
    app.logger.info("invidious fallback succeeded via %s for %s",
                    base, url)
    return info


def extract_info(url):
    """Extract metadata, walking the attempt cascade until one attempt
    returns formats. Raises the last error if every attempt fails."""
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        try:
            with yt_dlp.YoutubeDL(_build_opts(spec, url=url)) as ydl:
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
    if site_of(url) == "youtube":
        # Every yt-dlp attempt failed (on a cloud IP this is the bot
        # wall) — one last, cookie-free resort: a public Invidious
        # instance. Only its failure surfaces the original error.
        try:
            return _extract_info_invidious(url)
        except Exception as inv_error:
            app.logger.info("invidious fallback failed for %s: %s",
                            url, inv_error)
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


def _fetch_to_file(media_url, dest, timeout=120):
    """Download media_url into dest, following redirects (the
    Invidious /videoplayback endpoint answers 307 to a companion
    proxy host). Impersonated curl_cffi goes first — the same
    reasoning as _open_media_stream — urllib is the fallback.
    Raises on failure; a normal return guarantees a non-empty file."""
    if HAS_CFFI_REQUESTS:
        try:
            resp = _cffi_requests.get(
                media_url, headers=_INVIDIOUS_UA, impersonate="chrome",
                stream=True, timeout=timeout)
            try:
                if resp.status_code >= 400:
                    raise _MediaFetchError(resp.status_code)
                with open(dest, "wb") as out:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            out.write(chunk)
            finally:
                resp.close()
            if os.path.getsize(dest) > 0:
                return
            raise _MediaFetchError(None)
        except Exception as e:
            app.logger.info(
                "invidious media fetch (impersonated) failed for %s: %s",
                media_url, e)
    req = urllib.request.Request(media_url, headers=_INVIDIOUS_UA)
    with urllib.request.urlopen(req, timeout=timeout) as upstream, \
            open(dest, "wb") as out:
        shutil.copyfileobj(upstream, out, 256 * 1024)
    if os.path.getsize(dest) == 0:
        raise _MediaFetchError(None)


def _download_merged_invidious(url, height):
    """download_merged()'s Invidious twin: fetch the best split
    video+audio pair (or a muxed stream, when that is all the
    instance offers) through the instance's own proxy and join the
    pair with ffmpeg. Returns a send_file response, or None when
    Invidious cannot serve this video."""
    video_id = _youtube_video_id(url)
    if not video_id:
        return None
    try:
        base, data = _invidious_raw(video_id)
    except Exception as e:
        app.logger.info("invidious merged: no info for %s: %s", url, e)
        return None

    videos = [f for f in data.get("adaptiveFormats") or []
              if f.get("url")
              and (f.get("type") or "").startswith("video/")]
    audios = [f for f in data.get("adaptiveFormats") or []
              if f.get("url")
              and (f.get("type") or "").startswith("audio/")]
    muxed = [f for f in data.get("formatStreams") or [] if f.get("url")]

    video_pick = audio_pick = None
    if videos and audios:
        def _vkey(f):
            mime = f.get("type") or ""
            return (1 if "avc1" in mime else 0,
                    int(f.get("bitrate") or 0))

        fit = [f for f in videos
               if _parse_height(f) and _parse_height(f) <= height]
        video_pick = max(fit or videos, key=_vkey)

        def _akey(f):
            mime = f.get("type") or ""
            return (1 if "mp4" in mime else 0,
                    int(f.get("bitrate") or 0))

        audio_pick = max(audios, key=_akey)
    elif muxed:
        fit = [f for f in muxed
               if _parse_height(f) and _parse_height(f) <= height]
        video_pick = max(fit or muxed, key=_parse_height)
    if video_pick is None:
        app.logger.info("invidious merged: no usable formats for %s",
                        url)
        return None

    tmpdir = tempfile.mkdtemp(prefix="qgrab-inv-")
    try:
        vext = video_pick.get("container") or "mp4"
        vpath = os.path.join(tmpdir, f"video.{vext}")
        _fetch_to_file(video_pick["url"], vpath)
        final = vpath
        if audio_pick is not None:
            aext = audio_pick.get("container") or "m4a"
            apath = os.path.join(tmpdir, f"audio.{aext}")
            _fetch_to_file(audio_pick["url"], apath)
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                app.logger.warning(
                    "invidious merged: ffmpeg missing, cannot merge")
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            final = os.path.join(tmpdir, "merged.mp4")
            for cmd in (
                    [ffmpeg, "-y", "-i", vpath, "-i", apath,
                     "-c", "copy", final],
                    [ffmpeg, "-y", "-i", vpath, "-i", apath,
                     "-c:v", "copy", "-c:a", "aac", final]):
                if subprocess.run(cmd, capture_output=True,
                                  timeout=300).returncode == 0 \
                        and os.path.exists(final) \
                        and os.path.getsize(final) > 0:
                    break
            else:
                app.logger.info(
                    "invidious merged: ffmpeg merge failed for %s", url)
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
    except Exception as e:
        app.logger.info("invidious merged failed for %s: %s", url, e)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    app.logger.info("invidious merged succeeded via %s for %s",
                    base, url)
    filename = safe_filename(data.get("title"), "mp4")
    resp = send_file(final, as_attachment=True, download_name=filename,
                     mimetype="video/mp4")

    @resp.call_on_close
    def _cleanup(tmpdir=tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)

    return resp


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
        }, url=url)
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
        # yt-dlp could not fetch it natively either — for YouTube,
        # try the cookie-free Invidious proxy route before giving up.
        if site_of(url) == "youtube":
            inv_resp = _download_merged_invidious(url, height)
            if inv_resp is not None:
                return inv_resp
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


def _download_via_ytdlp(url, format_id):
    """Last-resort download: let yt-dlp fetch the file itself.

    The /download proxy extracts a media URL and then fetches the bytes
    separately (impersonated curl_cffi, then urllib). Some CDNs —
    TikTok's above all — bind the media URL to the extraction session
    (cookies/fingerprint carried inside yt-dlp) and 403 any fetch that
    does not come through that session, so the proxy can fail even when
    /api/info succeeded moments earlier. Downloading natively keeps the
    session end-to-end — the same reason the merged path works.

    Walks the same attempt cascade as download_merged() — cached winner
    first, same gate. Per attempt the format selector is the exact
    requested id (a bare format id IS a valid yt-dlp selector); if a
    client rejects it, that attempt is retried once with "<id>/best" so
    a client whose format table differs still yields the closest
    download instead of nothing. Returns a send_file response on
    success, None when every attempt failed (the caller then answers
    502/404 exactly as it did before this fallback existed).
    """
    selectors = [str(format_id), f"{format_id}/best"]
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        for selector in selectors:
            tmpdir = tempfile.mkdtemp(prefix="qgrab-")
            outtmpl = os.path.join(tmpdir, f"{uuid.uuid4().hex}.%(ext)s")
            opts = _build_opts(spec, {
                "format": selector,
                "outtmpl": outtmpl,
            }, url=url)
            info = path = None
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    path = ydl.prepare_filename(info)
            except Exception as e:
                last_error = e
                app.logger.info(
                    "ytdlp fallback attempt failed (client=%s "
                    "impersonate=%s format=%s) for %s: %s",
                    spec.get("client"), spec.get("impersonate"),
                    selector, url, e)
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            if not path or not os.path.exists(path):
                # prepare_filename can miss when the produced file's
                # extension differs from the info dict's (the same
                # mismatch download_merged patches with a .mp4 fix-up);
                # fall back to whatever file the download left behind.
                produced = [f for f in os.listdir(tmpdir)
                            if not f.endswith(".part")]
                if produced:
                    path = os.path.join(tmpdir, produced[0])
            if not path or not os.path.exists(path) \
                    or os.path.getsize(path) == 0:
                app.logger.info(
                    "ytdlp fallback produced no file (client=%s "
                    "impersonate=%s format=%s) for %s",
                    spec.get("client"), spec.get("impersonate"),
                    selector, url)
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            _remember_winner(url, spec)
            ext = os.path.splitext(path)[1].lstrip(".") or "mp4"
            filename = safe_filename(info.get("title"), ext)
            mimetype = (mimetypes.guess_type(filename)[0]
                        or "application/octet-stream")
            resp = send_file(path, as_attachment=True,
                             download_name=filename, mimetype=mimetype)

            @resp.call_on_close
            def _cleanup(tmpdir=tmpdir):
                shutil.rmtree(tmpdir, ignore_errors=True)

            app.logger.info(
                "ytdlp fallback succeeded (client=%s impersonate=%s "
                "format=%s) for %s",
                spec.get("client"), spec.get("impersonate"),
                selector, url)
            return resp
    if last_error is not None:
        app.logger.warning("ytdlp fallback failed for %s: %s",
                           url, last_error)
    return None


class _MediaFetchError(Exception):
    """Every media-fetch path failed. ``code`` is the HTTP status the
    upstream produced, or None when no response was received at all."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _read_chunks(resp, size=256 * 1024):
    """Yield an urllib response body in chunks (empty read = EOF)."""
    while True:
        chunk = resp.read(size)
        if not chunk:
            break
        yield chunk


def _nonempty_chunks(iterable):
    """Drop empty keep-alive chunks from a curl_cffi content iterator."""
    for chunk in iterable:
        if chunk:
            yield chunk


def _open_media_stream(media_url, headers):
    """Open a streaming GET of a media URL for the /download proxy.

    Returns (status, headers, chunk_iterator, close_callable); raises
    _MediaFetchError if every path fails.

    The impersonated curl_cffi fetch goes first: TikTok's CDN rejects
    the plain urllib handshake with 403 even though /api/info succeeded
    (extraction was already impersonated — the media fetch was not).

    Fallback choice: ANY impersonated failure earns one second chance
    through the original urllib path — connection-level errors because
    impersonation may be unavailable/flaky, and HTTP error statuses
    because some other CDN may dislike impersonation while tolerating a
    plain request (the reverse of TikTok). Only when both paths fail do
    we give up; the reported code is the HTTP status if either attempt
    produced one (urllib's own status wins when it has one, as the most
    recent answer), otherwise the failure is a reachability problem.
    """
    http_code = None

    if HAS_CFFI_REQUESTS:
        try:
            resp = _cffi_requests.get(
                media_url, headers=headers, impersonate="chrome",
                stream=True, timeout=30)
        except Exception as e:
            app.logger.info(
                "impersonated media fetch failed for %s; "
                "falling back to urllib: %s", media_url, e)
        else:
            if resp.status_code < 400:
                return (resp.status_code, resp.headers,
                        _nonempty_chunks(
                            resp.iter_content(chunk_size=256 * 1024)),
                        resp.close)
            http_code = resp.status_code
            app.logger.info(
                "impersonated media fetch returned %s for %s; "
                "retrying with urllib", http_code, media_url)
            resp.close()

    req = urllib.request.Request(media_url, headers=headers, method="GET")
    try:
        upstream = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise _MediaFetchError(e.code)
    except Exception:
        raise _MediaFetchError(http_code)
    return (upstream.status, upstream.headers,
            _read_chunks(upstream), upstream.close)


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
        # Extraction succeeded but lists no fetchable URL for this
        # format (defensive: e.g. the winning client returned formats
        # without direct URLs). Give the yt-dlp-native fallback a
        # chance before telling the visitor the format is gone.
        app.logger.info(
            "no target format URL for %s format %s; "
            "trying ytdlp fallback", url, format_id)
        fallback = _download_via_ytdlp(url, format_id)
        if fallback is not None:
            return fallback
        abort(404, "That format is no longer available.")

    media_url = target["url"]
    headers = dict(target.get("http_headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/124.0 Safari/537.36")
    # Pass through byte-range requests so downloads can resume / seek.
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    try:
        status, up_headers, chunks, close_upstream = _open_media_stream(
            media_url, headers)
    except _MediaFetchError as e:
        # Both media-fetch paths failed (impersonated curl_cffi and
        # urllib). Before answering 502, let yt-dlp download the file
        # natively — session-bound media URLs are exactly the case the
        # proxy cannot fetch (see _download_via_ytdlp). Only when the
        # fallback also fails does the visitor get the same 502 as
        # before.
        app.logger.info(
            "proxy fetch failed for %s format %s (code=%s); "
            "trying ytdlp fallback", url, format_id, e.code)
        fallback = _download_via_ytdlp(url, format_id)
        if fallback is not None:
            return fallback
        if e.code is not None:
            abort(502, f"Upstream returned {e.code}")
        abort(502, "Could not reach the media server.")

    ext = target.get("ext") or "mp4"
    filename = safe_filename(info.get("title"), ext)
    ascii_name = filename.encode("ascii", "ignore").decode() or f"video.{ext}"

    resp_headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}"
        ),
        "Content-Type": up_headers.get("Content-Type", "application/octet-stream"),
    }
    for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if up_headers.get(h):
            resp_headers[h] = up_headers[h]

    def stream():
        try:
            yield from chunks
        finally:
            close_upstream()

    return Response(stream(), status=status, headers=resp_headers)


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
