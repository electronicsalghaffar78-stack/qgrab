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

import i18n

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
#   Pinterest / VK / X: impersonation first, plain as fallback — all
#             three were verified (2026-11-03) to need impersonation
#             from a cloud IP, exactly like TikTok.
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
    if "pinterest" in host or host == "pin.it":
        return "pinterest"
    if "vk.com" in host or host.endswith(".vk.ru") \
            or host.endswith(".vkvideo.ru"):
        return "vk"
    if "twitter" in host or host == "x.com" or host.endswith(".x.com"):
        return "twitter"
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
    if site in ("pinterest", "vk", "twitter"):
        # Verified 2026-11-03 (FEATURES-TEST-REPORT.md): from a cloud
        # IP all three extract reliably only WITH browser
        # impersonation, so — like TikTok — impersonation goes first
        # and plain is the fallback (not the other way round).
        plan = []
        if HAS_IMPERSONATION:
            plan.append({"client": None, "impersonate": True})
        plan.append({"client": None, "impersonate": False})
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

    shaped = {
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

    # The API also lists the video's caption tracks; shape them like
    # yt-dlp's "subtitles" dict so the Subtitles / Transcript options
    # work on the Invidious path too.
    captions = {}
    for c in data.get("captions") or []:
        code = c.get("language_code") or c.get("languageCode")
        if code:
            captions[code] = [{"ext": "vtt",
                               "name": c.get("label") or code}]
    if captions:
        shaped["subtitles"] = captions
    return shaped


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


def pick_captions(info):
    """Caption tracks for the Subtitles / Transcript options.

    The uploader's own subtitle tracks win; YouTube's automatic
    captions are the fallback (the same preference yt-dlp itself
    uses). Returns [{"code": ..., "name": ...}] — empty when the
    video simply has no captions, in which case the page hides the
    options. Languages the UI itself speaks are listed first.
    """
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    source = subs if subs else auto
    out = []
    for code, fmts in source.items():
        name = None
        for f in fmts or []:
            if f.get("name"):
                name = f["name"]
                break
        out.append({"code": code, "name": name or code})
    order = {c: i for i, c in enumerate(i18n.LANG_CODES)}

    def _rank(item):
        base = item["code"].split("-")[0].lower()
        return (0, order[base]) if base in order else (1, item["code"])

    out.sort(key=_rank)
    return out[:60]


def safe_filename(title, ext):
    name = re.sub(r"[^\w\s.-]+", "", title or "video", flags=re.UNICODE).strip()
    name = re.sub(r"\s+", " ", name)[:80].strip() or "video"
    return f"{name}.{ext}"


# ---------------------------------------------------------------------------
# SEO — canonical site URL, per-platform landing pages, sitemap, robots
#
# The four landing pages (/youtube-video-downloader and friends) exist
# so search engines can index a focused page per platform instead of
# only the single homepage. Each renders templates/platform.html with
# the same downloader tool, so a visitor landing from a search result
# can download immediately. All copy is honest: it describes only what
# QGrab actually does (see the live-verified notes at the top of this
# file) — no invented numbers or testimonials.
# ---------------------------------------------------------------------------

SITE_URL = "https://qgrab.onrender.com"

PERSONAL_USE_NOTE = (
    "QGrab is a personal-use tool. Please download only videos that you "
    "own, that you created yourself, or that you have the owner's "
    "permission to save — and keep them for your own offline viewing. "
    "Copyrighted content belongs to its creators."
)

PLATFORM_PAGES = {
    "youtube": {
        "path": "/youtube-video-downloader",
        "name": "YouTube",
        "title": "YouTube Video Downloader — Download YouTube Videos Free "
                 "in HD | QGrab",
        "description": "Download YouTube videos free with QGrab. Save "
                       "videos in HD up to 1080p with sound, or save the "
                       "audio only. No sign-up and nothing to install.",
        "h1": "YouTube Video Downloader",
        "tagline": "Download YouTube videos free — in HD with sound, or "
                   "as audio only. Paste the link, pick a quality, and "
                   "save the file to your device. No sign-up, nothing to "
                   "install.",
        "placeholder": "Paste a YouTube link here… e.g. "
                       "https://www.youtube.com/watch?v=…",
        "steps": [
            ("Copy the YouTube link",
             "Open the video on YouTube and copy its link — Share → "
             "Copy link in the app, or copy the address bar in a "
             "browser."),
            ("Paste it here",
             "Paste the link into the box at the top of this page and "
             "press the Download button."),
            ("Pick a quality & save",
             "Choose a format — the ones marked \u201cwith sound\u201d "
             "play anywhere — and the download starts right away."),
        ],
        "sections": [
            ("Download YouTube Videos in HD, With Sound",
             "Many YouTube videos are served as separate picture and "
             "sound streams. QGrab lists the ready-to-watch formats "
             "with sound first — including merged options up to 1080p "
             "HD that it joins into a single MP4 file for you — plus "
             "audio-only options for when you only want the sound."),
            ("Free, With Nothing to Install",
             "QGrab runs entirely in your browser, on phones, tablets "
             "and computers alike. There is no account to create and no "
             "app or software to download first, and using the "
             "downloader is completely free."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Is the YouTube video downloader free?",
             "Yes. QGrab is completely free to use — no account, no "
             "sign-up and nothing to install. The site is supported by "
             "the ads shown on the page."),
            ("What quality can I download YouTube videos in?",
             "Whatever the video itself offers, up to 1080p HD. Where "
             "YouTube serves picture and sound as separate streams, "
             "QGrab lists \u201cmerged on download\u201d options that "
             "it joins into a single MP4 file with sound for you."),
            ("Can I download just the audio from a YouTube video?",
             "Yes. When a video offers audio-only formats, they appear "
             "in the list marked \u201caudio only\u201d — handy for "
             "music, talks and lectures that you have the right to "
             "save."),
            ("Why did my YouTube link fail?",
             "Private, age-restricted or region-locked videos may not "
             "work, and platforms change their systems from time to "
             "time. Check that the link opens in your browser, then "
             "try again."),
        ],
    },
    "tiktok": {
        "path": "/tiktok-video-downloader",
        "name": "TikTok",
        "title": "TikTok Video Downloader — Download TikTok Videos "
                 "Without Watermark | QGrab",
        "description": "Download TikTok videos without the watermark, "
                       "free with QGrab. Paste the TikTok link, pick a "
                       "quality and save the clean video to your phone "
                       "or PC.",
        "h1": "TikTok Video Downloader — No Watermark",
        "tagline": "Save TikTok videos to your phone or computer "
                   "without the watermark. Paste the link, choose a "
                   "quality, download — no TikTok account or app needed.",
        "placeholder": "Paste a TikTok link here… e.g. "
                       "https://www.tiktok.com/@user/video/…",
        "steps": [
            ("Copy the TikTok link",
             "Open the video in TikTok and tap Share → Copy link. You "
             "can also copy the link from the video's page in a "
             "browser."),
            ("Paste it here",
             "Paste the link into the box at the top of this page and "
             "press the Download button."),
            ("Pick a quality & save",
             "Choose the quality you want and the clean, "
             "watermark-free video saves straight to your device."),
        ],
        "sections": [
            ("Download TikTok Videos Without a Watermark",
             "QGrab saves the video file itself rather than recording "
             "your screen, so TikTok downloads arrive clean — the "
             "picture has no TikTok watermark moving across it, "
             "exactly as the original file looks."),
            ("Works on Phone and PC",
             "There is nothing to install and no account to create. "
             "QGrab works in the browser on Android and iPhone as well "
             "as on tablets and computers, and it is free to use."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Do TikTok downloads really have no watermark?",
             "Yes. QGrab downloads the video file itself instead of "
             "recording the screen, so the saved video carries no "
             "TikTok watermark."),
            ("Do I need a TikTok account to use this?",
             "No. You only need the link to a public TikTok video — no "
             "login and no TikTok app are required."),
            ("Where do downloaded TikTok videos go?",
             "They save to your device like any other download — "
             "usually your Downloads folder, or your browser's "
             "downloads list on a phone."),
            ("Why did my TikTok link fail?",
             "Private videos may not work, and platforms change their "
             "systems from time to time. Check that the link opens in "
             "your browser, then try again."),
        ],
    },
    "facebook": {
        "path": "/facebook-video-downloader",
        "name": "Facebook",
        "title": "Facebook Video Downloader — Download Facebook Videos "
                 "& Reels Free | QGrab",
        "description": "Download Facebook videos and reels free with "
                       "QGrab. Paste a public Facebook video link, "
                       "choose the quality and save the video straight "
                       "to your device.",
        "h1": "Facebook Video Downloader",
        "tagline": "Download Facebook videos and reels for free. Paste "
                   "a public video link, pick the quality you want, and "
                   "save the file to your phone or computer.",
        "placeholder": "Paste a Facebook link here… e.g. "
                       "https://www.facebook.com/watch/?v=…",
        "steps": [
            ("Copy the Facebook link",
             "Open the video or reel on Facebook and copy its link — "
             "Share → Copy link in the app, or copy the address bar in "
             "a browser."),
            ("Paste it here",
             "Paste the link into the box at the top of this page and "
             "press the Download button."),
            ("Pick a quality & save",
             "Choose the quality you want and the download starts "
             "right away."),
        ],
        "sections": [
            ("Download Facebook Videos and Reels",
             "Paste a link to a public Facebook video or reel and "
             "QGrab lists the qualities the video offers, so you can "
             "pick a smaller file for your phone or a sharper one for "
             "a bigger screen — then save it straight to your device."),
            ("Public Videos Only",
             "QGrab can only fetch videos that are publicly visible. "
             "Videos that are private, or shared only with the "
             "poster's friends, cannot be downloaded by any tool "
             "without logging in — and QGrab never asks for your "
             "Facebook password."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Can I download Facebook reels too?",
             "Yes. Reels are videos, and a public reel link works in "
             "the same box — paste it, pick a quality, and save."),
            ("Why can't I download a private Facebook video?",
             "Private videos, and videos shared only with friends, are "
             "visible only to people logged in with permission to see "
             "them. QGrab has no access to those, so only public "
             "videos can be downloaded."),
            ("Is the Facebook video downloader free?",
             "Yes. QGrab is completely free to use — no account, no "
             "sign-up and nothing to install. The site is supported "
             "by the ads shown on the page."),
            ("Which quality should I pick?",
             "Higher numbers (1080p, 720p) mean a sharper picture and "
             "a bigger file; lower numbers download faster and take "
             "less space. Formats marked \u201cwith sound\u201d "
             "include the audio in a single file."),
        ],
    },
    "instagram": {
        "path": "/instagram-video-downloader",
        "name": "Instagram",
        "title": "Instagram Video Downloader — Download Instagram "
                 "Videos & Reels Free | QGrab",
        "description": "Download Instagram videos and reels from "
                       "public posts, free with QGrab. Paste the link, "
                       "pick a quality and save the video — no login "
                       "needed.",
        "h1": "Instagram Video Downloader",
        "tagline": "Download videos and reels from public Instagram "
                   "posts, free. Paste the post link, pick a quality, "
                   "and save the video to your device — no Instagram "
                   "login required.",
        "placeholder": "Paste an Instagram link here… e.g. "
                       "https://www.instagram.com/reel/…",
        "steps": [
            ("Copy the Instagram link",
             "Open the video post or reel and copy its link — tap the "
             "Share icon (or the \u22ef menu) → Copy link."),
            ("Paste it here",
             "Paste the link into the box at the top of this page and "
             "press the Download button."),
            ("Pick a quality & save",
             "Choose the quality you want and the video saves "
             "straight to your device."),
        ],
        "sections": [
            ("Download Instagram Videos and Reels",
             "QGrab works with videos and reels from public Instagram "
             "posts. Paste the link and QGrab lists the available "
             "formats, so you can save the video to your phone or "
             "computer in the quality you choose."),
            ("Only Public Posts — No Login",
             "Only posts from public accounts can be fetched, because "
             "private content is visible only to approved followers "
             "who are logged in. QGrab never asks for your Instagram "
             "password — you only ever paste a link."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Can I download Instagram reels?",
             "Yes — reels from public accounts work in the same box. "
             "Paste the reel's link, pick a quality, and save."),
            ("Do I need to log in to Instagram?",
             "No — and you should never type your Instagram password "
             "into a downloader site. QGrab only needs the link to a "
             "public post."),
            ("Why did my Instagram link fail?",
             "Links from private accounts cannot be fetched, and "
             "platforms change their systems from time to time. "
             "Check that the post opens in your browser without "
             "logging in, then try again."),
            ("Is the Instagram video downloader free?",
             "Yes. QGrab is completely free to use — no account, no "
             "sign-up and nothing to install. The site is supported "
             "by the ads shown on the page."),
        ],
    },
}

# ---------------------------------------------------------------------------
# Internationalisation — 30 languages (see i18n.py)
#
# Language choice: ?lang=xx wins, then the qgrab_lang cookie, else
# English. A valid ?lang= is persisted in the cookie by _persist_lang.
# The canonical URL of every page stays the plain (English) URL; the
# language variants are advertised to search engines via hreflang.
# ---------------------------------------------------------------------------

def _current_lang():
    lang = (request.args.get("lang") or "").strip().lower()
    if i18n.is_valid(lang):
        return lang
    lang = (request.cookies.get(i18n.COOKIE_NAME) or "").strip().lower()
    if i18n.is_valid(lang):
        return lang
    return i18n.DEFAULT_LANG


def _hreflangs(path):
    out = []
    for code in i18n.LANG_CODES:
        url = SITE_URL + path if code == "en" else f"{SITE_URL}{path}?lang={code}"
        out.append({"code": code, "url": url})
    out.append({"code": "x-default", "url": SITE_URL + path})
    return out


def _js_strings(t):
    """The strings the page JavaScript needs, in the current language."""
    return {
        "working": t["btn_working"],
        "download": t["btn_download"],
        "length": t["js_length"],
        "by": t["js_by"],
        "dl": t["js_dl"],
        "kind_va": t["js_kind_va"],
        "kind_v": t["js_kind_v"],
        "kind_a": t["js_kind_a"],
        "err_formats": t["js_err_formats"],
        "err_link": t["js_err_link"],
        "err_generic": t["js_err_generic"],
        "group_video": t["js_group_video"],
        "group_mp3": t["js_group_mp3"],
        "mp3": t["js_mp3"],
        "group_caps": t["js_group_caps"],
        "subs": t["js_subs"],
        "transcript": t["js_transcript"],
        "cap_lang": t["js_cap_lang"],
    }


@app.context_processor
def _i18n_context():
    lang = _current_lang()
    t = i18n.get_strings(lang)
    path = request.path

    def lang_url(code):
        return path if code == "en" else f"{path}?lang={code}"

    return {
        "lang": lang,
        "dir": "rtl" if lang in i18n.RTL_LANGS else "ltr",
        "t": t,
        "languages": i18n.LANGUAGES,
        "current_lang_name": i18n.language_name(lang),
        "lang_url": lang_url,
        "hreflangs": _hreflangs(path),
        "js_strings": _js_strings(t),
    }


@app.after_request
def _persist_lang(resp):
    lang = (request.args.get("lang") or "").strip().lower()
    if i18n.is_valid(lang):
        resp.set_cookie(i18n.COOKIE_NAME, lang, max_age=31536000,
                        path="/", samesite="Lax")
    return resp


def _faq_jsonld(faq):
    """FAQPage structured data built from the same (question, answer)
    pairs the page renders visibly, so the two can never drift apart."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faq
        ],
    }


def _platform_view(key):
    lang = _current_lang()
    t = i18n.get_strings(lang)
    page = dict(PLATFORM_PAGES[key])
    tr = i18n.platform_strings(lang, key)
    if tr:
        # Translated body copy; <title>/meta description stay English.
        page["h1"] = tr["h1"]
        page["tagline"] = tr["tagline"]
        page["placeholder"] = tr["placeholder"]
        page["steps"] = [tuple(s) for s in tr["steps"]]
        page["sections"] = [tuple(s) for s in tr["sections"]] + [
            (t["sect_personal_h"], t["personal_use"])
        ]
        page["faq"] = [tuple(f) for f in tr["faq"]]
    others = []
    for k, p in PLATFORM_PAGES.items():
        if k == key:
            continue
        other = {"name": p["name"], "path": p["path"], "h1": p["h1"]}
        otr = i18n.platform_strings(lang, k)
        if otr:
            other["h1"] = otr["h1"]
        others.append(other)
    return render_template(
        "platform.html",
        page=page,
        page_hint=t["hint_platform"].format(name=page["name"]),
        site_url=SITE_URL,
        others=others,
        faq_ld=_faq_jsonld(page["faq"]),
    )


# ---------------------------------------------------------------------------
# Visitor ratings & reviews — real submissions only
#
# The homepage "Rate QGrab" widget stores every rating a visitor
# actually submits in a JSON file on the server, and the average,
# the filled stars and the "(N ratings)" line are computed from
# those stored submissions — nothing is seeded, rounded up or
# invented; with zero submissions the widget says exactly that.
#
# Storage is a plain JSON file (data/ratings.json next to app.py,
# overridable with QGRAB_DATA_DIR). Render's free tier has an
# ephemeral disk, so the file survives restarts of the process but
# NOT a redeploy or a filesystem reset — ratings collected between
# deploys are real but not permanent (see FEATURES-REPORT.md).
# The data/ directory is gitignored: user data is never committed.
#
# Abuse controls are deliberately light for v1: one rating per
# browser via a cookie flag (a soft limit — clearing cookies resets
# it), length caps, and Jinja's autoescaping when reviews render.
# There is no admin panel; moderation = editing the JSON file.
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("QGRAB_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data")
RATINGS_FILE = os.path.join(DATA_DIR, "ratings.json")
RATINGS_COOKIE = "qgrab_rated"
MAX_REVIEW_NAME = 40
MAX_REVIEW_TEXT = 300
MAX_STORED_RATINGS = 500
MAX_LISTED_REVIEWS = 20
_ratings_lock = threading.Lock()

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except OSError:
    pass  # _save_ratings retries the mkdir on every write


def _load_ratings():
    try:
        with open(RATINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)
                    and isinstance(r.get("stars"), int)]
    except (OSError, ValueError):
        pass
    return []


def _save_ratings(ratings):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = RATINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ratings, fh, ensure_ascii=False)
    os.replace(tmp, RATINGS_FILE)


def ratings_summary():
    """{count, average, reviews} computed from the stored ratings.

    average is None until at least one real rating exists; reviews
    (the submissions that included text) come newest first."""
    ratings = _load_ratings()
    count = len(ratings)
    average = None
    if count:
        average = round(
            sum(r.get("stars", 0) for r in ratings) / count, 1)
    reviews = []
    for r in reversed(ratings):
        if r.get("text"):
            reviews.append({
                "name": r.get("name") or "",
                "stars": r.get("stars", 0),
                "text": r.get("text") or "",
                "date": r.get("date") or "",
            })
        if len(reviews) >= MAX_LISTED_REVIEWS:
            break
    return {"count": count, "average": average, "reviews": reviews}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    faq = i18n.home_faq(_current_lang())
    t = i18n.get_strings(_current_lang())
    rate_js = {
        "thanks": t["rate_thanks"],
        "already": t["rate_already"],
        "err_stars": t["rate_err_stars"],
        "err_save": t["rate_err_save"],
        "ratings": t["rate_ratings"],
        "one": t["rate_one"],
        "none": t["rate_none"],
        "reviews_h": t["rate_reviews_h"],
    }
    return render_template(
        "index.html",
        home_faq=faq,
        home_faq_ld=_faq_jsonld(faq),
        ratings=ratings_summary(),
        already_rated=bool(request.cookies.get(RATINGS_COOKIE)),
        rate_js=rate_js,
    )


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/dmca")
def dmca():
    return render_template("dmca.html")


@app.route("/youtube-video-downloader")
def youtube_downloader():
    return _platform_view("youtube")


@app.route("/tiktok-video-downloader")
def tiktok_downloader():
    return _platform_view("tiktok")


@app.route("/facebook-video-downloader")
def facebook_downloader():
    return _platform_view("facebook")


@app.route("/instagram-video-downloader")
def instagram_downloader():
    return _platform_view("instagram")


@app.route("/sitemap.xml")
def sitemap():
    import datetime
    lastmod = datetime.date.today().isoformat()
    entries = [("/", "1.0", "weekly")]
    entries += [(p["path"], "0.9", "weekly")
                for p in PLATFORM_PAGES.values()]
    entries += [("/terms", "0.3", "monthly"),
                ("/privacy", "0.3", "monthly"),
                ("/dmca", "0.3", "monthly")]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/'
             'sitemap/0.9">']
    for path, priority, freq in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_URL}{path}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{priority}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return Response("\n".join(lines) + "\n", mimetype="application/xml")


@app.route("/robots.txt")
def robots_txt():
    body = ("User-agent: *\n"
            "Allow: /\n"
            "\n"
            f"Sitemap: {SITE_URL}/sitemap.xml\n")
    return Response(body, mimetype="text/plain")


@app.route("/api/info", methods=["POST"])
def api_info():
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", ""))
    if not url:
        return jsonify({"error": i18n.get_strings(_current_lang())["api_invalid"]}), 400
    try:
        info = extract_info(url)
    except Exception as e:
        # Raw yt-dlp errors (bot walls, extractor internals) stay in the
        # server log; visitors get one short, friendly message.
        app.logger.warning("info failed for %s: %s", url, e)
        return jsonify({"error": i18n.get_strings(_current_lang())["api_friendly"]}), 422

    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if entries:
            info = entries[0]

    # An MP3 can be produced whenever some format carries audio. A
    # missing acodec field means a combined/progressive format (X and
    # Pinterest report it that way); only acodec="none" is audio-less.
    has_audio = any(
        f.get("acodec") != "none"
        for f in info.get("formats", []) if f.get("url"))

    return jsonify({
        "title": info.get("title") or "Untitled",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "duration_h": info.get("duration_string"),
        "site": info.get("extractor_key") or info.get("extractor"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or url,
        "formats": pick_formats(info),
        # Extra download options (see download_mp3/download_captions):
        # an MP3 transcode whenever the source has any audio at all,
        # and Subtitles/Transcript whenever caption tracks exist.
        "mp3": has_audio,
        "captions": pick_captions(info),
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


def _send_temp_file(path, tmpdir, filename, mimetype):
    """send_file() a file inside a temp dir, deleting the dir when
    the response closes (the pattern the merged download uses)."""
    resp = send_file(path, as_attachment=True, download_name=filename,
                     mimetype=mimetype)

    @resp.call_on_close
    def _cleanup(tmpdir=tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)

    return resp


def _find_produced_file(tmpdir, prefer_ext=None):
    """The file a yt-dlp download left behind in tmpdir (never a
    .part), preferring a given extension; None when there is none."""
    files = [f for f in os.listdir(tmpdir) if not f.endswith(".part")]
    if prefer_ext:
        for f in files:
            if f.lower().endswith(prefer_ext):
                return os.path.join(tmpdir, f)
    if files:
        return os.path.join(tmpdir, files[0])
    return None


# ---------------------------------------------------------------------------
# MP3 / audio-only download
#
# The approach FEATURES-TEST-REPORT.md verified with the CLI
# (yt-dlp -f bestaudio -x --audio-format mp3): download bestaudio and
# let yt-dlp's FFmpegExtractAudio post-processor transcode to MP3
# with ffmpeg. Sources that are already MP3 (TikTok's sound track)
# pass through untouched; YouTube's Opus/M4A becomes a real MP3.
# Like every other download this walks the attempt cascade, and for
# YouTube the Invidious proxy route is the last resort.
# ---------------------------------------------------------------------------

def _download_mp3_invidious(url):
    """download_mp3()'s Invidious twin: fetch the best audio-only
    adaptive format through the instance's proxy and transcode it to
    MP3 with ffmpeg. Returns a send_file response, or None."""
    video_id = _youtube_video_id(url)
    if not video_id:
        return None
    try:
        base, data = _invidious_raw(video_id)
    except Exception as e:
        app.logger.info("invidious mp3: no info for %s: %s", url, e)
        return None
    audios = [f for f in data.get("adaptiveFormats") or []
              if f.get("url")
              and (f.get("type") or "").startswith("audio/")]
    if not audios:
        return None

    def _akey(f):
        mime = f.get("type") or ""
        return (1 if "mp4" in mime else 0, int(f.get("bitrate") or 0))

    pick = max(audios, key=_akey)
    tmpdir = tempfile.mkdtemp(prefix="qgrab-inv-mp3-")
    try:
        ext = pick.get("container") or "m4a"
        src = os.path.join(tmpdir, f"audio.{ext}")
        _fetch_to_file(pick["url"], src)
        final = src
        if ext.lower() != "mp3":
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                app.logger.warning("invidious mp3: ffmpeg missing")
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            final = os.path.join(tmpdir, "audio.mp3")
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", src, "-vn", "-codec:a",
                 "libmp3lame", "-q:a", "2", final],
                capture_output=True, timeout=300)
            if proc.returncode != 0 or not os.path.exists(final) \
                    or os.path.getsize(final) == 0:
                app.logger.info("invidious mp3: transcode failed")
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
    except Exception as e:
        app.logger.info("invidious mp3 failed for %s: %s", url, e)
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    app.logger.info("invidious mp3 succeeded via %s for %s", base, url)
    return _send_temp_file(final, tmpdir,
                           safe_filename(data.get("title"), "mp3"),
                           "audio/mpeg")


def download_mp3(url):
    """Serve the 'MP3 / Audio only' option for a video URL."""
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        tmpdir = tempfile.mkdtemp(prefix="qgrab-mp3-")
        outtmpl = os.path.join(tmpdir, f"{uuid.uuid4().hex}.%(ext)s")
        opts = _build_opts(spec, {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
            }],
        }, url=url)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            last_error = e
            app.logger.info(
                "mp3 attempt failed (client=%s impersonate=%s) "
                "for %s: %s",
                spec.get("client"), spec.get("impersonate"), url, e)
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
        path = _find_produced_file(tmpdir, ".mp3")
        if not path or os.path.getsize(path) == 0:
            app.logger.info(
                "mp3 attempt produced no file (client=%s) for %s",
                spec.get("client"), url)
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
        _remember_winner(url, spec)
        return _send_temp_file(path, tmpdir,
                               safe_filename(info.get("title"), "mp3"),
                               "audio/mpeg")
    if site_of(url) == "youtube":
        inv_resp = _download_mp3_invidious(url)
        if inv_resp is not None:
            return inv_resp
    if last_error is not None:
        app.logger.warning("mp3 download failed for %s: %s",
                           url, last_error)
    abort(502, "Could not prepare that MP3 download.")


# ---------------------------------------------------------------------------
# Subtitles + transcript downloads
#
# One feature underneath, two shapes on top (FEATURES-TEST-REPORT.md
# §3/§4): fetch the caption track once as WebVTT — yt-dlp with
# --write-subs/--write-auto-subs/--skip-download through the usual
# cascade, the Invidious captions API as YouTube's last resort — then
# either convert it to .srt with ffmpeg (the preferred subtitle
# shape; the .vtt itself is the fallback) or clean it into a plain
# text transcript.
# ---------------------------------------------------------------------------

_CAPTION_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def _fetch_caption_vtt_invidious(url, lang):
    """Ask each Invidious instance for one caption track as raw VTT.
    Returns (vtt_text, title) or None."""
    video_id = _youtube_video_id(url)
    if not video_id:
        return None
    for base in INVIDIOUS_INSTANCES:
        try:
            listing = _http_get_json(f"{base}/api/v1/captions/{video_id}")
        except Exception as e:
            app.logger.info("invidious captions list failed via %s: %s",
                            base, e)
            continue
        tracks = listing.get("captions") or []

        def _code(c):
            return c.get("language_code") or c.get("languageCode") or ""

        chosen = None
        for c in tracks:
            if _code(c) == lang:
                chosen = c
                break
        if chosen is None:  # same base language, any region variant
            for c in tracks:
                if _code(c).split("-")[0] == lang.split("-")[0]:
                    chosen = c
                    break
        if chosen is None or not chosen.get("url"):
            continue
        try:
            req = urllib.request.Request(base + chosen["url"],
                                         headers=_INVIDIOUS_UA)
            with urllib.request.urlopen(req, timeout=20) as resp:
                vtt = resp.read().decode("utf-8", "replace")
        except Exception as e:
            app.logger.info("invidious caption fetch failed via %s: %s",
                            base, e)
            continue
        if "WEBVTT" not in vtt[:64]:
            continue
        title = None
        try:
            _, data = _invidious_raw(video_id)
            title = data.get("title")
        except Exception:
            pass
        app.logger.info("invidious captions succeeded via %s for %s",
                        base, url)
        return vtt, title
    return None


def _fetch_caption_vtt(url, lang):
    """Fetch one caption track as raw WebVTT text; (vtt, title).

    Walks the attempt cascade with yt-dlp's subtitle writer, then —
    for YouTube — the Invidious captions API. Raises the last error
    when no attempt produced a track."""
    last_error = None
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        tmpdir = tempfile.mkdtemp(prefix="qgrab-subs-")
        try:
            opts = _build_opts(spec, {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [lang],
                "subtitlesformat": "vtt",
                "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            }, url=url)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            candidates = [f for f in os.listdir(tmpdir)
                          if f.endswith(".vtt")]
            if not candidates:
                raise yt_dlp.utils.DownloadError(
                    "Extractor wrote no caption file")

            def _score(fn):
                stem = fn[:-4].rsplit(".", 1)[-1]
                if stem == lang:
                    return 0
                if stem.startswith(lang) or lang.startswith(stem):
                    return 1
                return 2

            candidates.sort(key=_score)
            with open(os.path.join(tmpdir, candidates[0]),
                      encoding="utf-8") as fh:
                vtt = fh.read()
            if "WEBVTT" not in vtt[:64]:
                raise yt_dlp.utils.DownloadError(
                    "Caption file was not WebVTT")
            _remember_winner(url, spec)
            return vtt, info.get("title")
        except Exception as e:
            last_error = e
            app.logger.info(
                "caption attempt failed (client=%s impersonate=%s) "
                "for %s [%s]: %s",
                spec.get("client"), spec.get("impersonate"), url,
                lang, e)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if site_of(url) == "youtube":
        got = _fetch_caption_vtt_invidious(url, lang)
        if got is not None:
            return got
    if last_error is not None:
        raise last_error
    raise yt_dlp.utils.DownloadError("No caption attempt was made.")


def vtt_to_transcript(vtt):
    """Clean plain-text transcript from a WebVTT caption file: drop
    the header, cue timings and inline tags, de-duplicate the rolling
    lines auto-captions repeat (each cue re-shows the previous line),
    and join what remains into flowing text."""
    out = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit() \
                or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        line = re.sub(r"\s+", " ", line)
        if not line:
            continue
        if out and line == out[-1]:
            continue  # the roll-up repeated the previous line
        if out and line.startswith(out[-1]) and len(line) > len(out[-1]):
            out[-1] = line  # same line, still growing word by word
            continue
        out.append(line)
    return " ".join(out).strip()


def _send_text_download(text, filename, mimetype):
    resp = Response(text.encode("utf-8"), mimetype=mimetype)
    ascii_name = filename.encode("ascii", "ignore").decode() \
        or "transcript.txt"
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}")
    return resp


def download_captions(url, lang, as_transcript):
    """Serve the 'Subtitles (.srt)' or 'Transcript (.txt)' option."""
    if not _CAPTION_LANG_RE.match(lang or ""):
        abort(400, "Bad caption language")
    try:
        vtt, title = _fetch_caption_vtt(url, lang)
    except Exception as e:
        app.logger.warning("captions failed for %s [%s]: %s",
                           url, lang, e)
        abort(502, FRIENDLY_ERROR)
    title = title or "video"
    if as_transcript:
        text = vtt_to_transcript(vtt)
        if not text:
            abort(404, "That video has no captions.")
        return _send_text_download(
            text, safe_filename(f"{title} - transcript", "txt"),
            "text/plain; charset=utf-8")
    # .srt is the preferred subtitle shape; ffmpeg converts the VTT.
    # When ffmpeg is missing or the conversion fails, the visitor
    # still gets the captions — as the original .vtt.
    tmpdir = tempfile.mkdtemp(prefix="qgrab-srt-")
    vpath = os.path.join(tmpdir, "caps.vtt")
    with open(vpath, "w", encoding="utf-8") as fh:
        fh.write(vtt)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        spath = os.path.join(tmpdir, "caps.srt")
        try:
            proc = subprocess.run([ffmpeg, "-y", "-i", vpath, spath],
                                  capture_output=True, timeout=120)
        except Exception:
            proc = None
        if proc is not None and proc.returncode == 0 \
                and os.path.exists(spath) and os.path.getsize(spath) > 0:
            return _send_temp_file(
                spath, tmpdir,
                safe_filename(f"{title} - subtitles", "srt"),
                "application/x-subrip")
    return _send_temp_file(
        vpath, tmpdir, safe_filename(f"{title} - subtitles", "vtt"),
        "text/vtt")


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

    # The extra options /api/info advertises next to the format list.
    if format_id == "mp3":
        return download_mp3(url)
    if format_id.startswith("subs:"):
        return download_captions(url, format_id[len("subs:"):],
                                 as_transcript=False)
    if format_id.startswith("transcript:"):
        return download_captions(url, format_id[len("transcript:"):],
                                 as_transcript=True)

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


@app.route("/api/ratings")
def api_ratings():
    return jsonify(ratings_summary())


@app.route("/api/rate", methods=["POST"])
def api_rate():
    t = i18n.get_strings(_current_lang())
    if request.cookies.get(RATINGS_COOKIE):
        return jsonify({"error": t["rate_already"]}), 409
    data = request.get_json(silent=True) or {}
    try:
        stars = int(data.get("stars"))
    except (TypeError, ValueError):
        stars = 0
    if stars < 1 or stars > 5:
        return jsonify({"error": t["rate_err_stars"]}), 400
    name = str(data.get("name") or "").strip()[:MAX_REVIEW_NAME]
    text = str(data.get("text") or "").strip()[:MAX_REVIEW_TEXT]
    entry = {
        "name": name,
        "stars": stars,
        "text": text,
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
        "ts": int(time.time()),
    }
    with _ratings_lock:
        ratings = _load_ratings()
        ratings.append(entry)
        try:
            _save_ratings(ratings[-MAX_STORED_RATINGS:])
        except OSError as e:
            app.logger.warning("could not save rating: %s", e)
            return jsonify({"error": t["rate_err_save"]}), 500
    resp = jsonify({"ok": True, **ratings_summary()})
    resp.set_cookie(RATINGS_COOKIE, "1", max_age=31536000, path="/",
                    samesite="Lax")
    return resp


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
