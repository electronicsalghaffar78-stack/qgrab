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
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import urllib.error
import uuid
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, \
    urlparse, urlunparse

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
#   YouTube : default client -> android_vr -> tv_downgraded -> web
#             player clients. Alternate player clients do not hit the
#             same bot wall as the default web client; a public
#             Invidious instance is the last resort after all of them.
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

# YouTube player clients in cascade order: the default first, then
# android_vr (the full quality range with no PO token needed, but
# intermittent), tv_downgraded (the most reliable of the TV
# family), and web last (SABR-era and the weakest of the set).
# Invidious stays the final fallback after every client — see
# _extract_info_uncached.
YOUTUBE_CLIENT_CASCADE = (None, "android_vr", "tv_downgraded", "web")

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
               attempt if the previous failure looked like a block),
               "api_hostname": str (optional — TikTok only: pass
               this host to the extractor as its app/API endpoint,
               see _tiktok_api_attempts),
               "twitter_api": str (optional — X only: the
               extractor's twitter "api" argument, e.g.
               "syndication")}.
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
    if spec.get("api_hostname"):
        # TikTok app/API endpoint variant: the extractor reads
        # this as its _API_HOSTNAME (the host its app-API calls
        # are built against; yt-dlp's own default is the api16
        # host below). Merged in, never replacing other args.
        args = dict(opts.get("extractor_args") or {})
        tiktok_args = dict(args.get("tiktok") or {})
        tiktok_args["api_hostname"] = [spec["api_hostname"]]
        args["tiktok"] = tiktok_args
        opts["extractor_args"] = args
    if spec.get("twitter_api"):
        # X's extractor can be pointed at a different API family:
        # "syndication" is the embed backend's API, the one route
        # that still answers anonymously now that the default
        # GraphQL route needs a session. Merged like the TikTok
        # argument above, never replacing other args.
        args = dict(opts.get("extractor_args") or {})
        twitter_args = dict(args.get("twitter") or {})
        twitter_args["api"] = [spec["twitter_api"]]
        args["twitter"] = twitter_args
        opts["extractor_args"] = args
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


def _extract_attempt(url, spec):
    """One cascade attempt: extract with this spec's options and
    return the info. Raises the DownloadError / network error when
    the attempt fails or yields no formats (a page that "loads"
    empty is the bot wall wearing a disguise)."""
    with yt_dlp.YoutubeDL(_build_opts(spec, url=url)) as ydl:
        info = ydl.extract_info(url, download=False)
    if not _has_formats(info):
        raise yt_dlp.utils.DownloadError(
            "Extractor returned no formats "
            "(webpage may have been blocked)")
    _remember_winner(url, spec)
    return info


def _extract_info_cascade(url):
    """One pass over the attempt cascade. Returns (info, None,
    no_formats_seen) on success and (None, last_error,
    no_formats_seen) when every attempt failed — the flag records
    whether ANY attempt met yt-dlp's "No video formats found"
    refusal (a later attempt failing differently, e.g. on the
    network, must not erase that sighting)."""
    last_error = None
    no_formats_seen = False
    for spec in _ordered_attempts(url):
        if not _cascade_gate_open(spec, last_error):
            break
        try:
            return _extract_attempt(url, spec), None, no_formats_seen
        except Exception as e:  # DownloadError or network error
            last_error = e
            no_formats_seen = no_formats_seen or _no_formats_error(e)
            app.logger.info(
                "extract attempt failed (client=%s impersonate=%s) "
                "for %s: %s",
                spec.get("client"), spec.get("impersonate"), url, e)
    return None, last_error, no_formats_seen


# TikTok app/API endpoint variants. yt-dlp's "No video formats
# found" is the refusal the standard web-flavoured attempts cannot
# argue with — it is also what a post whose creator disabled
# in-app downloads looks like, so no variant can promise success
# there. The extractor builds its app-API calls against a single
# api_hostname (its "api_hostname" extractor argument; yt-dlp's
# default is the api16 host). Asking a DIFFERENT app endpoint can
# still reach posts the default route refuses, so a failed
# standard pass earns one attempt per host below — each a normal
# cascade attempt (the primary attempt's shape plus the
# api_hostname spec key), not a parallel code path.
TIKTOK_API_HOSTNAMES = (
    "api22-normal-c-useast1a.tiktokv.com",
    "api16-normal-c-useast1a.tiktokv.com",
)


def _no_formats_error(error):
    """True for yt-dlp's "No video formats found" refusal — the
    one error class the TikTok app-endpoint attempts exist for."""
    return error is not None \
        and "no video formats found" in str(error).lower()


def _tiktok_api_attempts(url):
    """The TikTok app-endpoint attempt specs: the primary
    attempt's shape (impersonation first for TikTok) with each
    api_hostname in turn."""
    plan = _ordered_attempts(url)
    if not plan:
        return []
    return [dict(plan[0], api_hostname=hostname)
            for hostname in TIKTOK_API_HOSTNAMES]


# ---------------------------------------------------------------------------
# Third backends — one public resolver of last resort per platform
#
# yt-dlp alone, from a datacenter IP, is refused in bursts on
# several platforms (see the 2026-11-04 research notes): TikTok's
# app API demands native-code request signatures, Instagram and
# Facebook wall logged-out page fetches, X's GraphQL route needs a
# session. Each platform still has ONE public surface that answers
# anonymously, and the downloaders that survive use exactly those:
#   TikTok    -> the tikwm.com resolver API (it fetches on ITS
#                infrastructure, so TikTok's IP blocks do not apply)
#   Instagram -> the public embed page (/p/<id>/embed/captioned/)
#   Facebook  -> the video embed player (video/embed?video_id=)
#   X         -> yt-dlp against the syndication API, then the
#                FxTwitter mirror API
# Each helper below returns an info dict in the same shape the
# yt-dlp path returns (the "_qgrab_source" key records which
# backend won, for logs and status), or raises DownloadError.
# They run ONLY after the whole yt-dlp cascade — including the
# TikTok app-endpoint attempts and the paused retry — has failed,
# and a helper's own failure never replaces the original yt-dlp
# error the visitor's fetch_failed story is built on.
# ---------------------------------------------------------------------------

_BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
}


def _http_get_text(url, headers=None, timeout=15):
    """GET a page as text: impersonated curl_cffi first (some
    embed surfaces fingerprint the TLS handshake of the fetch
    itself), urllib as the fallback — the same two-step as
    _fetch_to_file, for text."""
    hdrs = headers or _BROWSER_UA
    if HAS_CFFI_REQUESTS:
        try:
            resp = _cffi_requests.get(
                url, headers=hdrs, impersonate="chrome",
                timeout=timeout)
            try:
                if resp.status_code >= 400:
                    raise _MediaFetchError(resp.status_code)
                return resp.text
            finally:
                resp.close()
        except Exception as e:
            app.logger.info(
                "text fetch (impersonated) failed for %s: %s",
                url, e)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# --- TikTok: the tikwm.com resolver --------------------------------

TIKWM_API_URL = "https://www.tikwm.com/api/"


def _shape_tikwm_info(data, url):
    """Shape a tikwm API answer into the yt-dlp-style info dict
    the rest of the app (pick_formats, /download, the SP tool)
    already consumes. The format urls are signed TikTok-CDN URLs:
    they expire and are coupled to the side that resolved them,
    so — exactly like yt-dlp's CDN URLs — they are only ever
    streamed through this server's /download proxy, never handed
    to the visitor's browser as a direct link."""
    formats = []

    def _add(fid, media_url, note, size, audio_only=False):
        if not media_url:
            return
        formats.append({
            "format_id": fid,
            "url": media_url,
            "ext": "mp3" if audio_only else "mp4",
            "protocol": "https",
            "vcodec": "none" if audio_only else "avc1",
            "acodec": "mp4a",
            "height": 0,
            "filesize": size,
            "format_note": note,
        })

    # hdplay (the HD no-watermark stream, present because the
    # resolver is asked with hd=1) is the top row, then the SD
    # play stream, then the watermarked export, then the sound
    # track as an audio row.
    _add("tikwm-hd", data.get("hdplay"), "HD", data.get("hd_size"))
    _add("tikwm-sd", data.get("play"), "", data.get("size"))
    _add("tikwm-wm", data.get("wmplay"), "watermarked",
         data.get("wm_size"))
    _add("tikwm-music", data.get("music"), "", None, audio_only=True)

    duration = data.get("duration")
    try:
        duration = int(duration) if duration else None
    except (TypeError, ValueError):
        duration = None
    author = data.get("author") or {}
    return {
        "id": data.get("id"),
        "title": data.get("title") or "Untitled",
        "thumbnail": data.get("cover"),
        "duration": duration,
        "duration_string": (
            f"{duration // 60}:{duration % 60:02d}"
            if duration else None),
        "uploader": author.get("nickname")
                    or author.get("unique_id"),
        "webpage_url": url,
        "extractor_key": "TikTok",
        "formats": formats,
        "_qgrab_source": "tikwm",
    }


def _extract_info_tikwm(url):
    """extract_info()'s TikTok last resort: the public tikwm.com
    resolver. No key; its free endpoint asks for ~1 request per
    second, which the cascade in front already paces. A code != 0
    answer is tikwm's per-video failure mode and raises — the
    caller keeps the original yt-dlp error."""
    api_url = (TIKWM_API_URL + "?url=" + quote(url, safe="")
               + "&hd=1")
    data = _http_get_json(api_url, timeout=15)
    if not isinstance(data, dict) or data.get("code") != 0:
        msg = data.get("msg") if isinstance(data, dict) else None
        raise yt_dlp.utils.DownloadError(
            f"tikwm could not resolve this post: {msg or 'no answer'}")
    payload = data.get("data") or {}
    if not (payload.get("hdplay") or payload.get("play")):
        # A photo/slideshow post lands here: it carries images,
        # not a video stream this downloader can serve.
        raise yt_dlp.utils.DownloadError(
            "tikwm returned no video stream for this post.")
    info = _shape_tikwm_info(payload, url)
    if not _has_formats(info):
        raise yt_dlp.utils.DownloadError(
            "tikwm returned no usable formats.")
    app.logger.info("tikwm fallback succeeded for %s", url)
    return info


# --- Instagram: the public embed page (public posts/reels only) ----

def _is_instagram_url(url):
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host == "instagram.com" \
        or host.endswith(".instagram.com")


def _instagram_shortcode(url):
    m = re.search(
        r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)",
        url or "")
    return m.group(1) if m else None


def _find_key(obj, key):
    """First value stored under key anywhere in a nested
    dict/list structure (embed-page JSON shapes shift; the media
    fields this app needs keep their names)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def _extract_info_instagram_embed(url):
    """extract_info()'s Instagram last resort: the public embed
    page. instagram.com/p/<id>/embed/captioned/ still serves
    PUBLIC posts to logged-out requesters and carries the media
    in a "gql_data" JSON blob. Photo posts parse fine but carry
    no video_url — they raise, like any other failure here."""
    code = _instagram_shortcode(url)
    if not code:
        raise yt_dlp.utils.DownloadError(
            "No Instagram post id in that URL.")
    html = _http_get_text(
        f"https://www.instagram.com/p/{code}/embed/captioned/",
        timeout=15)
    marker = html.find('"gql_data"')
    brace = html.find("{", marker) if marker >= 0 else -1
    if brace < 0:
        raise yt_dlp.utils.DownloadError(
            "Instagram's embed page carried no media data.")
    try:
        gql, _end = json.JSONDecoder().raw_decode(html[brace:])
    except ValueError as e:
        raise yt_dlp.utils.DownloadError(
            f"Instagram's embed data did not parse: {e}")
    video_url = _find_key(gql, "video_url")
    if not video_url:
        raise yt_dlp.utils.DownloadError(
            "Instagram's embed data had no video URL "
            "(photo post or login-walled).")
    dims = _find_key(gql, "dimensions") or {}
    duration = _find_key(gql, "video_duration")
    try:
        duration = int(float(duration)) if duration else None
    except (TypeError, ValueError):
        duration = None
    title = None
    media = gql.get("shortcode_media") if isinstance(gql, dict) \
        else None
    edges = ((media or {}).get("edge_media_to_caption")
             or {}).get("edges") or []
    if edges:
        text = ((edges[0].get("node") or {}).get("text") or "")
        title = text.split("\n")[0].strip()[:120] or None
    info = {
        "id": code,
        "title": title or "Instagram video",
        "thumbnail": _find_key(gql, "display_url"),
        "duration": duration,
        "duration_string": (
            f"{duration // 60}:{duration % 60:02d}"
            if duration else None),
        "uploader": None,
        "webpage_url": url,
        "extractor_key": "Instagram",
        "formats": [{
            "format_id": "ig-embed",
            "url": video_url,
            "ext": "mp4",
            "protocol": "https",
            "vcodec": "avc1",
            "acodec": "mp4a",
            "height": dims.get("height") or 0,
            "filesize": None,
            "format_note": "",
        }],
        "_qgrab_source": "instagram-embed",
    }
    app.logger.info("instagram embed fallback succeeded for %s",
                    url)
    return info


# --- Facebook: the video embed player (public posts only) ----------

def _facebook_video_id(url):
    """The numeric video id of a facebook.com video URL, or None.
    fb.watch short links carry no id in the URL itself — those
    stay with the yt-dlp cascade alone."""
    if not url:
        return None
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("v")
    if values and values[0].isdigit():
        return values[0]
    m = re.search(r"/(?:videos|reel|watch)/(\d+)", parsed.path)
    return m.group(1) if m else None


_FB_EMBED_UA = {
    "User-Agent": "facebookexternalhit/1.1 "
                  "(+http://www.facebook.com/externalhit_uatext.php)",
}


def _fb_embed_src(html, key):
    """One "key":"<url>" field from the embed player's response;
    the URLs are JSON-escaped (\\/ and \\uXXXX), so the value is
    decoded as a JSON string when it parses."""
    m = re.search(r'"' + key + r'":"((?:[^"\\]|\\.)*)"', html)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return raw.replace("\\/", "/")


def _extract_info_facebook_embed(url):
    """extract_info()'s Facebook last resort: Facebook's own
    embed player (video/embed?video_id=), asked with the
    platform's crawler user-agent, answers logged-out for PUBLIC
    videos and carries hd_src / sd_src stream URLs. Login-walled
    posts return a player without sources and raise."""
    video_id = _facebook_video_id(url)
    if not video_id:
        raise yt_dlp.utils.DownloadError(
            "No numeric Facebook video id in that URL.")
    html = _http_get_text(
        f"https://www.facebook.com/video/embed?video_id={video_id}",
        headers=_FB_EMBED_UA, timeout=15)
    hd = _fb_embed_src(html, "hd_src") \
        or _fb_embed_src(html, "hd_src_no_ratelimit")
    sd = _fb_embed_src(html, "sd_src") \
        or _fb_embed_src(html, "sd_src_no_ratelimit")
    if not hd and not sd:
        raise yt_dlp.utils.DownloadError(
            "Facebook's embed player returned no stream "
            "(login-walled post?).")
    formats = []
    if hd:
        formats.append({
            "format_id": "fb-hd", "url": hd, "ext": "mp4",
            "protocol": "https", "vcodec": "avc1",
            "acodec": "mp4a", "height": 0, "filesize": None,
            "format_note": "HD",
        })
    if sd:
        formats.append({
            "format_id": "fb-sd", "url": sd, "ext": "mp4",
            "protocol": "https", "vcodec": "avc1",
            "acodec": "mp4a", "height": 0, "filesize": None,
            "format_note": "SD",
        })
    title = None
    m = re.search(r"<title>([^<]+)</title>", html)
    if m and m.group(1).strip().lower() not in (
            "facebook", "facebook video"):
        title = m.group(1).strip()
    info = {
        "id": video_id,
        "title": title or "Facebook video",
        "thumbnail": None,
        "duration": None,
        "duration_string": None,
        "uploader": None,
        "webpage_url": url,
        "extractor_key": "Facebook",
        "formats": formats,
        "_qgrab_source": "facebook-embed",
    }
    app.logger.info("facebook embed fallback succeeded for %s",
                    url)
    return info


# --- X: the FxTwitter mirror (after the syndication attempt) --------

def _twitter_status_id(url):
    m = re.search(r"(?:x\.com|twitter\.com)/[^/]+/status/(\d+)",
                  url or "")
    return m.group(1) if m else None


def _extract_info_fxtwitter(url):
    """extract_info()'s X last resort: the FxTwitter mirror API.
    Its status JSON carries the tweet's video variants (the MP4
    ladder on video.twimg.com); HLS playlist variants are left
    out — the /download proxy serves single files only, the same
    rule pick_formats applies to yt-dlp tables."""
    status_id = _twitter_status_id(url)
    if not status_id:
        raise yt_dlp.utils.DownloadError(
            "No X status id in that URL.")
    data = _http_get_json(
        f"https://api.fxtwitter.com/status/{status_id}",
        timeout=15)
    tweet = (data or {}).get("tweet") or {}
    media = tweet.get("media") or {}
    videos = media.get("videos") or [
        e for e in media.get("all") or []
        if isinstance(e, dict) and e.get("type") == "video"]
    formats = []
    thumbnail = None
    duration = None
    for v_index, video in enumerate(videos):
        if not isinstance(video, dict):
            continue
        thumbnail = thumbnail or video.get("thumbnail_url")
        if duration is None and video.get("duration"):
            try:
                duration = int(float(video["duration"]))
            except (TypeError, ValueError):
                pass
        variants = [
            v for v in video.get("variants") or []
            if isinstance(v, dict) and v.get("url")
            and (v.get("content_type") or "video/mp4")
            == "video/mp4"]
        variants.sort(key=lambda v: v.get("bitrate") or 0,
                      reverse=True)
        seen_heights = set()
        for variant in variants:
            m = re.search(r"/(\d{2,4})x(\d{2,4})/", variant["url"])
            height = int(m.group(2)) if m else 0
            if height in seen_heights:
                continue
            seen_heights.add(height)
            formats.append({
                "format_id": f"fx-{v_index}-{height}",
                "url": variant["url"],
                "ext": "mp4",
                "protocol": "https",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": height,
                "filesize": None,
                "format_note": "",
                "tbr": (variant.get("bitrate") or 0) / 1000
                       or None,
            })
        if not variants and video.get("url"):
            formats.append({
                "format_id": f"fx-{v_index}",
                "url": video["url"],
                "ext": "mp4",
                "protocol": "https",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "height": video.get("height") or 0,
                "filesize": None,
                "format_note": "",
            })
    if not formats:
        raise yt_dlp.utils.DownloadError(
            "FxTwitter returned no video media for this post.")
    text = (tweet.get("text") or "").split("\n")[0].strip()
    info = {
        "id": status_id,
        "title": text[:120] or "X video",
        "thumbnail": thumbnail,
        "duration": duration,
        "duration_string": (
            f"{duration // 60}:{duration % 60:02d}"
            if duration else None),
        "uploader": (tweet.get("author") or {}).get("name"),
        "webpage_url": url,
        "extractor_key": "Twitter",
        "formats": formats,
        "_qgrab_source": "fxtwitter",
    }
    app.logger.info("fxtwitter fallback succeeded for %s", url)
    return info


def _extract_info_uncached(url):
    """extract_info()'s engine room: walk the attempt cascade,
    then each platform's fallback, until something returns
    formats. Raises the last yt-dlp error if everything fails —
    a fallback's own failure never replaces it."""
    info, last_error, no_formats_seen = _extract_info_cascade(url)
    if info is not None:
        return info
    if site_of(url) == "youtube":
        # Every yt-dlp attempt failed (on a cloud IP this is the bot
        # wall) — one last, cookie-free resort: a public Invidious
        # instance. Only its failure surfaces the original error.
        try:
            return _extract_info_invidious(url)
        except Exception as inv_error:
            app.logger.info("invidious fallback failed for %s: %s",
                            url, inv_error)
    else:
        if site_of(url) == "tiktok" and no_formats_seen:
            # A standard attempt met the "No video formats found"
            # refusal: try the app/API endpoints (one attempt per
            # api_hostname) before falling back to the paused
            # retry below.
            for spec in _tiktok_api_attempts(url):
                try:
                    return _extract_attempt(url, spec)
                except Exception as e:  # DownloadError/network
                    last_error = e
                    app.logger.info(
                        "extract attempt failed (client=%s "
                        "impersonate=%s api_hostname=%s) for %s: %s",
                        spec.get("client"), spec.get("impersonate"),
                        spec.get("api_hostname"), url, e)
        # Non-YouTube platforms refuse in bursts: TikTok can answer
        # "No video formats found" (and even rate-limit its oEmbed)
        # for a post it served fine minutes earlier, then recover on
        # its own. When the whole first pass failed, pause briefly
        # and retry the primary attempt ONCE before giving up. Only
        # failures pay the pause — a successful first pass never
        # waits.
        plan = _ordered_attempts(url)
        if plan:
            app.logger.info(
                "extract pass failed for %s (%s); retrying the "
                "primary attempt once after a pause", url, last_error)
            time.sleep(4)
            try:
                return _extract_attempt(url, plan[0])
            except Exception as e:  # DownloadError or network error
                last_error = e
                app.logger.info(
                    "extract attempt failed (client=%s "
                    "impersonate=%s) for %s: %s",
                    plan[0].get("client"), plan[0].get("impersonate"),
                    url, e)
    # The whole yt-dlp side has failed. Each platform still has
    # one public resolver that answers anonymously (see the
    # "Third backends" section above) — try the one that fits
    # this URL before giving up. A fallback's failure is only
    # logged; the ORIGINAL yt-dlp error stays in charge.
    fallback = None
    if site_of(url) == "tiktok":
        fallback = _extract_info_tikwm
    elif _is_instagram_url(url):
        fallback = _extract_info_instagram_embed
    elif site_of(url) == "facebook":
        fallback = _extract_info_facebook_embed
    if fallback is not None:
        try:
            return fallback(url)
        except Exception as e:
            app.logger.info(
                "third-backend fallback failed for %s: %s", url, e)
    if site_of(url) == "twitter":
        # X gets two: first yt-dlp once more, pointed at its
        # syndication API (the embed backend — the default
        # GraphQL route is the dead one), then the FxTwitter
        # mirror if even that fails.
        plan = _ordered_attempts(url)
        if plan:
            try:
                return _extract_attempt(
                    url, dict(plan[0], twitter_api="syndication"))
            except Exception as e:
                app.logger.info(
                    "syndication attempt failed for %s: %s", url, e)
        try:
            return _extract_info_fxtwitter(url)
        except Exception as e:
            app.logger.info(
                "fxtwitter fallback failed for %s: %s", url, e)
    if last_error is not None:
        raise last_error
    raise yt_dlp.utils.DownloadError("No extraction attempt was made.")


# ---------------------------------------------------------------------------
# Extraction cache — 10-minute TTL, successes only, single-flight
#
# Extraction, not transfer, is this app's bottleneck (a cascade
# pass costs seconds of platform round-trips; the winner cache
# only skips re-walking it). Successful extractions are therefore
# cached whole for 10 minutes — short, because the format URLs
# inside are signed and expire — and concurrent requests for the
# same URL share ONE extraction through a per-key lock
# (single-flight) instead of stampeding the platform in parallel.
# Failures are never cached: platforms refuse in bursts and
# recover, and a cached failure would outlive the recovery.
# /api/info, /download and the Script+Prompt tool all reach the
# cache through extract_info below.
# ---------------------------------------------------------------------------

_INFO_CACHE_TTL = 600  # seconds
_info_cache = {}         # key -> (info dict, expiry timestamp)
_info_cache_lock = threading.Lock()
_info_flight_locks = {}  # key -> threading.Lock (single-flight)


def _info_cache_key(url):
    """The cache key for a URL: scheme/host lowercased, fragment
    and utm_* tracking parameters removed, the remaining query
    sorted — so one video shared with different tracking junk
    shares one extraction, while any parameter that identifies
    content (a YouTube ?v=, say) still separates keys."""
    parsed = urlparse(url or "")
    pairs = [(k, v) for k, v in
             parse_qsl(parsed.query, keep_blank_values=True)
             if not k.startswith("utm_")]
    pairs.sort()
    return urlunparse((parsed.scheme.lower(),
                       parsed.netloc.lower(), parsed.path, "",
                       urlencode(pairs), ""))


def _info_cache_get(key):
    with _info_cache_lock:
        hit = _info_cache.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    return None


def _info_cache_put(key, info):
    with _info_cache_lock:
        if len(_info_cache) > 512:
            # Opportunistic tidy-up so the map cannot grow
            # forever on a long-lived worker.
            now = time.time()
            for stale in [k for k, (_i, exp) in _info_cache.items()
                          if exp <= now]:
                _info_cache.pop(stale, None)
        _info_cache[key] = (info, time.time() + _INFO_CACHE_TTL)


def _info_flight_lock(key):
    with _info_cache_lock:
        lock = _info_flight_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _info_flight_locks[key] = lock
        return lock


def _info_cache_clear():
    """Drop every cached extraction (tests / maintenance)."""
    with _info_cache_lock:
        _info_cache.clear()


def extract_info(url):
    """Extract metadata for a URL — a 10-minute in-memory cache
    (successes only) with single-flight dedup in front of the
    cascade in _extract_info_uncached. The returned dict is the
    cached object itself; callers must not mutate it."""
    key = _info_cache_key(url)
    cached = _info_cache_get(key)
    if cached is not None:
        return cached
    with _info_flight_lock(key):
        # A concurrent request may have filled the cache while
        # this one waited for the lock.
        cached = _info_cache_get(key)
        if cached is not None:
            return cached
        info = _extract_info_uncached(url)
        _info_cache_put(key, info)
        return info


def pick_formats(info):
    """Turn yt-dlp's raw format list into a clean, user-friendly list.

    OWNER'S RULE (absolute): every video quality offered must
    DOWNLOAD WITH the video's own audio. A video row is therefore
    one of exactly two things:

    (a) a true muxed format — vcodec and acodec both present (a
        missing codec field counts as present: some sites report
        their progressive formats that way; only an explicit "none"
        means the stream is absent); or
    (b) a synthetic "merge:{height}" row: when picked, /download
        fetches the best video-only stream at that height plus the
        best audio and joins them with ffmpeg into one mp4 WITH
        sound (verified end-to-end: the delivered file carries a
        full audio stream).

    A bare video-only stream is NEVER listed as itself — that was
    the original injury: silent downloads. Where a height has both
    a muxed format and split streams, the muxed row wins (a direct
    file beats a merge) — one video row per height.
    """
    best_by_height, unheighted, audio_only = {}, [], []
    video_only_heights = set()
    for f in info.get("formats", []):
        if not f.get("url"):
            continue
        proto = (f.get("protocol") or "")
        if proto.startswith("m3u8") and f.get("ext") not in ("mp4",):
            # HLS streams can't be proxied as a single file download in v1.
            continue
        has_v = f.get("vcodec") != "none"
        has_a = f.get("acodec") != "none"
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
            if height:
                # One row per height: keep the best muxed encode. A
                # watermark-free variant beats a watermarked one
                # (TikTok serves both); after that the larger file
                # (then the higher bitrate) is the better encode.
                # Ties keep the earlier format — yt-dlp's own order
                # (e.g. the first of two identical CDN mirrors).
                rank = (
                    0 if "watermark" in item["note"].lower() else 1,
                    size or 0,
                    f.get("tbr") or 0,
                )
                current = best_by_height.get(height)
                if current is None or rank > current[0]:
                    best_by_height[height] = (rank, item)
            else:
                # No height reported (e.g. Facebook's sd/hd
                # progressive pair): genuinely distinct options —
                # keep them all, in source order.
                unheighted.append(item)
        elif has_a:
            item["kind"] = "audio"
            abr = f.get("abr") or 0
            item["label"] = f"Audio {int(abr)}kbps" if abr else "Audio"
            audio_only.append(item)
        elif has_v and height:
            # has_v and not has_a: a silent video-only stream — never
            # offered as itself (owner's rule), but its height can be
            # offered as a "merge:" row below, whose download muxes
            # the best audio in.
            video_only_heights.add(height)
    rows_by_height = {h: item for h, (_, item) in best_by_height.items()}
    if audio_only:
        # Split-stream heights with no muxed row of their own become
        # merge rows, best heights first, capped at 1080p (files and
        # merge time stay sane) and at 4 rows — the pre-rule shape.
        merge_heights = sorted(
            (h for h in video_only_heights
             if h <= 1080 and h not in rows_by_height),
            reverse=True)[:4]
        for h in merge_heights:
            rows_by_height[h] = {
                "id": f"merge:{h}",
                "ext": "mp4",
                "height": h,
                "size": None,
                "size_h": None,
                "note": "merged on download",
                "kind": "video+audio",
                "label": f"{h}p",
            }
    combined = [rows_by_height[h]
                for h in sorted(rows_by_height, reverse=True)]
    combined += unheighted
    audio_only.sort(key=lambda x: x["label"], reverse=True)

    # Video rows (every one downloads with sound) first, then audio.
    return (combined + audio_only[:3])[:MAX_FORMATS]


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
# can download immediately. Two more entries (/video-script-generator
# and /ai-video-prompt-generator, marked "tool": True) are landing
# pages for the Video -> Script + AI Prompts tool and render the same
# template with a CTA hero instead of the downloader form. All copy
# is honest: it describes only what QGrab actually does (see the
# live-verified notes at the top of this file) — no invented numbers
# or testimonials.
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
    # The next two entries are NOT downloaders: they are landing
    # pages for the Video -> Script + AI Prompts tool. "tool": True
    # switches platform.html to a CTA hero (the tool itself lives on
    # /video-to-script-prompt) and keeps these pages out of the
    # "other downloaders" cards. Copy is English-only SEO copy, like
    # the downloaders' titles/meta; platform_strings() has no entries
    # for these keys, so the English body is used in every language.
    "script": {
        "path": "/video-script-generator",
        "name": "Video Script",
        "tool": True,
        "title": "Video Script Generator — Video to Script, Free "
                 "Online | QGrab",
        "description": "Free video to script generator: paste a "
                       "YouTube, TikTok, Facebook or Instagram link "
                       "and get the video's full script — from its "
                       "subtitles, or from the audio itself. No "
                       "sign-up.",
        "h1": "Video Script Generator",
        "tagline": "Turn any video into its written script. Paste a "
                   "link from YouTube, TikTok, Facebook or Instagram "
                   "and QGrab writes out everything that is said — "
                   "free, with no sign-up.",
        "keywords": "video to script, video script generator, video "
                    "scripting, get script from a video, youtube "
                    "video to script, tiktok video to script, "
                    "facebook video to script, instagram video to "
                    "script, video script maker, qgrab",
        "cta_text": "The generator itself lives on the tool page — "
                    "paste your video link there, press Create "
                    "Script, and read or edit your script.",
        "cta_label": "Open the Video to Script Tool →",
        "cta_href": "/video-to-script-prompt",
        "howto_h2": "How to Get a Video's Script in 3 Steps",
        "howto_sub": "From a video link to a written script in "
                     "about a minute — nothing is generated until "
                     "you press the button.",
        "faq_h2": "Video Script Generator — Frequently Asked "
                  "Questions",
        "faq_sub": "Quick answers about turning videos into "
                   "scripts with QGrab.",
        "placeholder": "Paste a video link here… e.g. "
                       "https://www.youtube.com/watch?v=…",
        "steps": [
            ("Copy the video link",
             "Open the video on YouTube, TikTok, Facebook or "
             "Instagram and copy its link — Share → Copy link in "
             "the app, or copy the address bar in a browser."),
            ("Paste it into the tool",
             "Open the Video to Script + Prompts tool, paste the "
             "link and press Create Script. The script is only "
             "created when you press the button — never "
             "automatically."),
            ("Read, edit & download",
             "The script appears in an editable preview. Fix "
             "anything you like, then download it as a text file — "
             "or go on to create AI video prompts from it."),
        ],
        "sections": [
            ("Get the Script from a Video — Without Typing It "
             "Yourself",
             "Video scripting by hand means pausing and rewinding "
             "for every line. QGrab does the listening for you: "
             "give it the link and it writes out the video's spoken "
             "words as a clean, readable script you can quote, "
             "study, subtitle or rebuild from."),
            ("Works from Subtitles — or from the Audio Itself",
             "When a video has subtitles or captions, the script "
             "is built from them. When it has none, QGrab listens "
             "to the video's own audio and transcribes what is "
             "said — that route works for videos up to 20 minutes. "
             "If a video has neither subtitles nor clear speech, "
             "the tool says so honestly instead of inventing a "
             "script."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Is the video script generator free?",
             "Yes. It is completely free to use — no account, no "
             "sign-up and nothing to install."),
            ("Which videos can I turn into a script?",
             "Any public video you can link to on YouTube, TikTok, "
             "Facebook or Instagram. Subtitled videos are scripted "
             "from their captions; videos without subtitles are "
             "transcribed from their own audio (up to 20 "
             "minutes)."),
            ("Can I edit the script it makes?",
             "Yes. The script opens in an editable preview — "
             "correct names or lines right on the page, then "
             "download it as a .txt file. From the same script you "
             "can also generate scene-by-scene AI video prompts."),
        ],
    },
    "prompts": {
        "path": "/ai-video-prompt-generator",
        "name": "Video Prompt",
        "tool": True,
        "title": "AI Video Prompt Generator — Make Prompts from "
                 "Any Video | QGrab",
        "description": "Free AI video prompt generator: QGrab turns "
                       "a video's own script into ready-to-use, "
                       "scene-by-scene prompts for AI video tools. "
                       "Edit the script first, then generate. No "
                       "sign-up.",
        "h1": "AI Video Prompt Generator",
        "tagline": "Make prompts from a video: QGrab first writes "
                   "the video's script, then turns it into "
                   "scene-by-scene AI video prompts you can paste "
                   "into your video generator. Free, no sign-up.",
        "keywords": "ai video prompt generator, video to prompt, "
                    "video prompt maker, make prompts from a video, "
                    "video to ai prompt, ai video prompts, prompt "
                    "generator for ai video, scene by scene video "
                    "prompts, qgrab",
        "cta_text": "The generator itself lives on the tool page — "
                    "paste a video link there, create the script, "
                    "check it, then press Create Prompts.",
        "cta_label": "Open the Script + Prompts Tool →",
        "cta_href": "/video-to-script-prompt",
        "howto_h2": "How to Make Video Prompts in 3 Steps",
        "howto_sub": "From a video link to ready-to-paste prompts "
                     "— the script comes first, so the prompts "
                     "match what the video really says.",
        "faq_h2": "AI Video Prompt Generator — Frequently Asked "
                  "Questions",
        "faq_sub": "Quick answers about making AI video prompts "
                   "from a video with QGrab.",
        "placeholder": "Paste a video link here… e.g. "
                       "https://www.youtube.com/watch?v=…",
        "steps": [
            ("Copy the video link",
             "Open the video on YouTube, TikTok, Facebook or "
             "Instagram and copy its link — Share → Copy link in "
             "the app, or copy the address bar in a browser."),
            ("Create the script first",
             "In the tool, press Create Script. QGrab writes the "
             "video's script from its subtitles — or from the "
             "audio itself — and shows it in an editable preview."),
            ("Generate the prompts",
             "Edit the script if you want to, then press Create "
             "Prompts. You get one ready-to-use prompt per scene, "
             "which you can copy, download as a text file, or "
             "regenerate."),
        ],
        "sections": [
            ("Video to Prompt — Scene by Scene",
             "Each prompt describes a single scene: who is in it, "
             "what happens, the exact dialogue, the camera work "
             "and the mood. Because the prompts are built from the "
             "video's own script — not from its title or guesswork "
             "— they follow what the video actually shows and "
             "says."),
            ("Prompts Written Like a Real Film Shoot",
             "Every prompt carries the same production rules: "
             "dialogue spoken once, clearly, with lip-sync; "
             "characters talking to each other, never into the "
             "camera; complete camera angles and movement; "
             "expressions that match the scene's mood; the same "
             "character looking consistent in every scene; and no "
             "text or logos inside the picture."),
            ("A Note on Personal Use", PERSONAL_USE_NOTE),
        ],
        "faq": [
            ("Is the AI video prompt generator free?",
             "Yes — completely free, with no account and no "
             "sign-up."),
            ("Can QGrab make the video itself?",
             "No. QGrab creates the script and the prompts; you "
             "paste the prompts into an AI video tool (such as "
             "Google Flow / Veo or a similar generator) to create "
             "the video. The prompts are plain text, so they work "
             "with any generator that accepts written prompts."),
            ("Do the prompts work for videos without subtitles?",
             "Yes. The script they are built from can come from "
             "the video's subtitles or — for videos up to 20 "
             "minutes — from listening to the video's own audio. "
             "You can also edit the script before the prompts are "
             "made, so the prompts follow your version."),
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
        "sp_btn_result": t["sp_btn_result"],
        "sp_working": t["sp_working"],
        "sp_wait_note": t["sp_wait_note"],
        "sp_copy": t["sp_copy"],
        "sp_copied": t["sp_copied"],
        "sp_err_nosubs": t["sp_err_nosubs"],
        "sp_err_rate": t["sp_err_rate"],
        "sp_err_ai": t["sp_err_ai"],
        "sp_err_setup": t["sp_err_setup"],
        "sp_err_toolong": t["sp_err_toolong"],
        "sp_err_audiobig": t["sp_err_audiobig"],
        "sp_err_nospeech": t["sp_err_nospeech"],
        "sp_err_daily_limit": t["sp_err_daily_limit"],
        "sp_err_fetch_failed": t["sp_err_fetch_failed"],
        "sp_left_script": t["sp_left_script"],
        "sp_left_prompts": t["sp_left_prompts"],
        "sp_refresh_at": t["sp_refresh_at"],
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
                        path="/", samesite="Lax", secure=True,
                        httponly=True)
    return resp


@app.after_request
def _security_headers(resp):
    """Baseline hardening headers on every response (audit pass,
    2026-11-04): the app set none of these itself, so the live
    site answered without HSTS / nosniff / frame protection and
    scored a D on Mozilla Observatory. Values are chosen to be
    safe for this site: it is HTTPS-only behind Render's proxy
    (which redirects http -> https), it never needs to be framed
    by third parties, and it uses no camera/mic/geolocation/
    payment APIs. No full Content-Security-Policy on purpose: the
    pages rely on inline scripts/styles, so a CSP would have to
    allow 'unsafe-inline' anyway; X-Frame-Options covers the
    clickjacking case without that risk."""
    resp.headers.setdefault("Strict-Transport-Security",
                            "max-age=31536000; includeSubDomains")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy",
                            "strict-origin-when-cross-origin")
    resp.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()")
    # Static assets (icons, logo) are immutable in practice: let
    # browsers and the CDN keep them for a week instead of the
    # no-cache Flask's send_file defaults to. The web manifest
    # stays uncached so PWA metadata changes are seen at once,
    # and the service worker keeps its no-cache — both its own
    # /sw.js route and the physical /static/sw.js copy — so a
    # service-worker update is never delayed by an HTTP cache.
    if request.method == "GET" and resp.status_code == 200 \
            and request.path.startswith("/static/") \
            and not request.path.endswith(".webmanifest") \
            and not request.path.endswith("/sw.js"):
        resp.headers["Cache-Control"] = "public, max-age=604800"
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
        if p.get("tool"):
            # Tool landing pages never appear as "other downloaders"
            # cards; on the tool pages themselves this leaves the
            # four real downloaders as the cards.
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


@app.route("/video-script-generator")
def video_script_generator():
    return _platform_view("script")


@app.route("/ai-video-prompt-generator")
def ai_video_prompt_generator():
    return _platform_view("prompts")


@app.route("/video-to-script-prompt")
def script_prompt_tool():
    # The dedicated page for the Video -> Script + AI Prompts tool
    # (the same tool is featured on the homepage). Title/meta stay
    # English in the template (SEO), like the platform pages.
    return render_template("scriptprompt.html", site_url=SITE_URL)


@app.route("/sitemap.xml")
def sitemap():
    import datetime
    lastmod = datetime.date.today().isoformat()
    entries = [("/", "1.0", "weekly")]
    entries += [(p["path"], "0.9", "weekly")
                for p in PLATFORM_PAGES.values()]
    entries += [("/video-to-script-prompt", "0.8", "weekly")]
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


# ---------------------------------------------------------------------------
# Video -> Script + AI Prompts (Google Gemini)
#
# The featured tool: a visitor pastes a video link and presses one
# of the tool's TWO buttons — "Create Script" or "Create Prompts"
# (Script and Prompts are separate jobs; the request carries
# "mode": "script" | "prompts"). Two routes feed the model:
#   1. CAPTIONS — the video's own captions (the same
#      _fetch_caption_vtt pipeline as Subtitles/Transcript) become a
#      timed script, and Gemini formats the clean script or writes
#      the scene-by-scene AI video prompts in the approved sample's
#      shape (character + scene + exact dialogue line + audio rules
#      + camera + photorealistic, nobody looking at the camera).
#   2. AUDIO (v2, the owner's order after testing a subtitle-less
#      TikTok) — when a video has no usable caption track, its audio
#      is downloaded, converted to a small mono MP3 and sent to
#      Gemini, which transcribes it and produces the same outputs.
#      Caps: 20 minutes max, 18 MB max converted file.
#
# OWNER'S HARD RULE: generation happens ONLY on that explicit
# button press. Nothing calls this endpoint on page load, on paste,
# or after /api/info — the ONLY caller in the shipped JS is the
# tool's own Generate button (homepage section + dedicated page).
# The download-result area's "Script + Prompts" button merely
# scrolls to the section and pre-fills its input; generation still
# waits for the visitor to press Generate there.
#
# Config (environment only — the key is never logged, never returned
# and never stored in the repo):
#   GEMINI_API_KEY  required; without it the endpoint answers
#                   503 {"error": "not_configured"} and the tool
#                   shows its "being set up" message.
#   GEMINI_API_KEY_2 / GEMINI_API_KEY_3
#                   optional extra keys (other Google projects).
#                   Quota is per project AND per model, so each
#                   extra key multiplies the daily capacity; the
#                   cascade rotates through (model, key) pairs.
#   GEMINI_MODEL    optional override of the primary model.
# Models (verified against ai.google.dev on 2026-11-03 — the models
# page + the pricing page's Free Tier column, "Free of charge").
# The cascade walks SP_MODEL_CHAIN (an env GEMINI_MODEL override
# leads when set). Each model carries its OWN free-tier daily
# quota, so a quota-exhausted model (fast HTTP 429) falls through
# to the next one; the attempt policy in _gemini_call keeps slow
# failures (timeouts) from multiplying the visitor's wait.
# API shape (official reference, ai.google.dev/api/generate-content):
#   POST https://generativelanguage.googleapis.com/v1beta/models/
#        {model}:generateContent     header: x-goog-api-key: <key>
#   body: system_instruction + contents + generationConfig with
#   responseMimeType "application/json"; the reply text lives in
#   candidates[0].content.parts[].text.
#
# Abuse control is a soft per-IP limit: 6 generations per rolling
# 24 h, kept in memory (a restart resets it — acceptable, the same
# spirit as the one-rating-per-browser cookie). The IP comes from
# the first X-Forwarded-For hop when present (Render's proxy sets
# it), else the direct peer.
# ---------------------------------------------------------------------------

SP_INPUT_LIMIT = 24000        # max caption characters sent to Gemini
SP_RATE_LIMIT = 6             # generations per IP ...
SP_RATE_WINDOW = 24 * 60 * 60  # ... per rolling 24 hours
SP_GEMINI_TIMEOUT = 100       # seconds, per model attempt (text route)
SP_AUDIO_MAX_SECONDS = 1200   # audio route: videos up to 20 minutes
SP_AUDIO_MAX_BYTES = 18 * 1024 * 1024  # converted MP3 hard cap
SP_AUDIO_GEMINI_TIMEOUT = 150  # seconds, per model attempt (audio)
SP_AUDIO_MAX_ATTEMPTS = 2     # audio route: first 2 fetch attempts
SP_FFMPEG_TIMEOUT = 300       # seconds for the MP3 conversion
# Audio longer than this is transcribed in chunks of at most this
# many seconds (research §9: past ~15 minutes a single call's
# transcript risks the model's OUTPUT token limit, and one giant
# call is also one giant point of failure). Each chunk goes
# through the same key x model rotation; the transcripts are
# stitched in order and the script/prompts are written from the
# stitched text.
SP_AUDIO_CHUNK_SECONDS = 600  # 10-minute transcription chunks
# The audio route's slow-failure budget (see _gemini_call's
# attempt policy). Diagnosis of the 2026-11-04 live failure — a
# 214 s no-caption TikTok dying as ai_unavailable after ~160 s:
# payload size is innocent (214 s of the normalised 64 kbps MP3
# is ~1.7 MB, far under Gemini's 20 MB inline cap). The killer
# was timeout classification + the SHARED slow cap: one
# transcription attempt legitimately exceeding the 150 s
# per-attempt timeout flipped the cascade into slow mode, whose
# cap is 2 attempts TOTAL — so a single timeout plus one fast
# quota error on the next pair exhausted the rotation without
# ever trying five of the six models. A slow transcription is
# per-pair congestion, not a global "stop" signal, so audio
# calls walk deeper before giving up. The text routes were given
# the same deeper budget on 2026-11-05 — see
# SP_TEXT_SLOW_MAX_ATTEMPTS below.
SP_AUDIO_SLOW_MAX_ATTEMPTS = 6  # audio: pairs tried after a slow failure
SP_DEFAULT_MODEL = "gemini-3.8-flash"
# The Gemini cascade, in order. Every model has its own free-tier
# daily quota, so widening the chain stretches the day's total.
SP_MODEL_CHAIN = ["gemini-3.8-flash", "gemini-3.6-flash",
                  "gemini-3.5-flash", "gemini-3.7-flash",
                  "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
# Attempt policy (see _gemini_call): a failure that comes back in
# under this many seconds is the quota/error signature and the
# cascade keeps walking the chain; once a failure is SLOW (a
# timeout or a long attempt), total attempts cap at the calling
# route's slow budget so the worst-case wait stays bounded.
# SP_GEMINI_SLOW_MAX_ATTEMPTS is the generic fallback for a call
# that passes no budget of its own; both production routes pass
# theirs (SP_AUDIO_SLOW_MAX_ATTEMPTS / SP_TEXT_SLOW_MAX_ATTEMPTS).
SP_GEMINI_FAST_FAIL = 20      # seconds; faster failure = fast
SP_GEMINI_SLOW_MAX_ATTEMPTS = 2  # fallback attempt cap once slow
# The TEXT routes' slow-failure budget (the caption route and
# prompts-from-script). Raised 2 -> 6 on 2026-11-05 on production
# evidence: Render logs (08:19-08:27 UTC) showed three Prompts
# jobs dying as ai_unavailable after only TWO attempts, both on
# the FIRST cascade model (gemini-3.8-flash) — an HTTP 503
# (Google-side overload) and a TimeoutError flipped the call into
# slow mode and the inherited tight cap killed the job before the
# cascade ever reached the other five models or the other keys.
# A slow failure on one pair is per-pair congestion, not a global
# "stop" signal — the same diagnosis as the audio route's — so
# the text routes now walk as deep as audio before giving up.
SP_TEXT_SLOW_MAX_ATTEMPTS = 6  # text: pairs tried after a slow failure
GEMINI_API_URL = ("https://generativelanguage.googleapis.com/v1beta/"
                  "models/{model}:generateContent")

_sp_hits = {}
_sp_lock = threading.Lock()

# The SCRIPT rules and PROMPT rules below are the owner's approved
# blocks. The PROMPT rules (the "usool") stay EXACTLY as built — all
# 8 rules, never dropped or softened, on both routes and in prompts
# mode. The instructions are composed per route (captions / audio)
# and per mode (script / prompts): each mode returns ONLY its own
# half of the old combined output.
SP_SCRIPT_RULES = """SCRIPT rules:
- Keep every spoken line EXACTLY as captioned — same words, same original language and script. Never translate the dialogue.
- Group the lines into scenes. Start each scene with a heading line: SCENE n (start-end) — a few English words for the setting / what happens.
- One line per speech: SPEAKER: <line>. Infer speaker labels from the words themselves (for example, someone addressed as "Amma" is the mother; the person calling her that is her child). Use short, consistent ALL-CAPS labels; use NARRATOR for voice-over, and UNKNOWN only when nothing at all can be inferred.
- Mark stretches with no speech as a single line: (no dialogue — a brief English visual note)."""

# The audio route's twin of the script rules: identical formatting,
# only the source word changes ("captioned" -> "transcribed").
SP_SCRIPT_RULES_AUDIO = SP_SCRIPT_RULES.replace(
    "EXACTLY as captioned", "EXACTLY as transcribed")

SP_PROMPT_RULES = """PROMPT rules — exactly one English prompt per scene, in the same order, each a single self-contained paragraph an AI video generator can use directly. EVERY prompt MUST carry ALL of these production rules — none may be dropped or softened:
1. DIALOGUE DELIVERY: the speaking character delivers the exact dialogue line himself/herself, in the line's own language, lips moving with the words. Add verbatim: DIALOGUE — <SPEAKER> says exactly, in clear <the caption language>, lips moving with the words, in their own voice, spoken ONCE, slowly and clearly, never repeated: "<the exact original line(s)>". The line is NEVER dubbed by anyone else. Audio: ONLY that character's voice — no other voices, no background talking or chatter, no music over the dialogue.
2. EYELINE: characters talk TO EACH OTHER — nobody ever looks at or into the camera. State this in every prompt ("looking at <the other character>, never at the camera").
3. CAMERA: give an explicit virtual-camera direction in every scene — BOTH an angle/shot size (e.g. medium shot, close-up, over-the-shoulder, wide shot) AND a movement (e.g. slow push-in, gentle pan, static locked-off).
4. LOOK: open every prompt with "Photorealistic cinematic video," and keep the whole prompt photorealistic, cinematic, like a real film — NEVER cartoon, animation or CGI-looking.
5. EXPRESSIONS: give an explicit facial-expression direction for EACH character in the scene, matched to that scene's emotion (e.g. "AMMA: warm hiding-her-hunger smile; BETA: worried, eyes moist"). A character must never smile in a serious or sad scene.
6. CONSISTENCY: first fix one character description block per character (name, age, face, hair, clothes). Repeat that block VERBATIM, word for word, in every scene prompt of this video, so the same person looks identical in every scene. Never re-describe a character differently between scenes.
7. SILENT SCENES: for a scene without dialogue write explicitly: "Nobody speaks, mouths closed." — no dialogue block, no voice at all.
8. ANTI-TEXT TAIL: end every prompt with exactly: "No subtitles, no captions, no text, no words, no letters, no numbers, no watermark, no logo anywhere in the frame — clean picture only."
"""

SP_TEXT_INSTRUCTION_SCRIPT = (
    "You turn a video's timed captions into a clean production "
    "script. Answer with STRICT JSON only: {\"script\": \"...\"} "
    "— no markdown fences, no commentary, nothing outside the JSON "
    "object.\n\n" + SP_SCRIPT_RULES)

SP_TEXT_INSTRUCTION_PROMPTS = (
    "You turn a video's timed captions into ready-to-use AI video "
    "generation prompts. First segment the captions into scenes "
    "and speeches exactly as the SCRIPT rules below describe — but "
    "do NOT output the script itself. Answer with STRICT JSON "
    "only: {\"prompts\": [\"...\", \"...\"]} — no markdown fences, "
    "no commentary, nothing outside the JSON object.\n\n"
    + SP_SCRIPT_RULES + "\n\n" + SP_PROMPT_RULES)

# Prompts mode from the visitor's OWN script text (the editable
# preview flow): the script in the box — generated a moment ago and
# possibly edited by the visitor — is the source; nothing is
# fetched. The same rules, only the source's description differs.
SP_SCRIPT_INSTRUCTION_PROMPTS = (
    "You are given the script of a video, provided or edited by "
    "the user. Segment it into scenes and speeches exactly as the "
    "SCRIPT rules below describe — but do NOT output the script "
    "itself. Answer with STRICT JSON only: {\"prompts\": [\"...\", "
    "\"...\"]} — no markdown fences, no commentary, nothing "
    "outside the JSON object.\n\n"
    + SP_SCRIPT_RULES + "\n\n" + SP_PROMPT_RULES)

SP_AUDIO_TRANSCRIBE_RULES = """TRANSCRIPTION rules:
- Listen to the attached audio and transcribe the speech VERBATIM — every spoken word, in its ORIGINAL language and its original script. Never translate the dialogue.
- Segment the transcription into scenes with APPROXIMATE time ranges, estimated from the audio's flow; scene headings follow the script rules (SCENE n (start-end) — a few English words for the setting / what happens).
- If the audio contains NO intelligible speech at all (music only, noise, or silence), answer with exactly {"error": "no_speech"} and nothing else."""

SP_AUDIO_INSTRUCTION_SCRIPT = (
    "You are given the complete audio track of a video. Transcribe "
    "it and turn the transcription into a clean production script. "
    "Answer with STRICT JSON only: {\"script\": \"...\"} — no "
    "markdown fences, no commentary, nothing outside the JSON "
    "object (the only exception is the no_speech answer described "
    "below).\n\n"
    + SP_AUDIO_TRANSCRIBE_RULES + "\n\n" + SP_SCRIPT_RULES_AUDIO)

SP_AUDIO_INSTRUCTION_PROMPTS = (
    "You are given the complete audio track of a video. Transcribe "
    "it and segment the transcription into scenes and speeches "
    "exactly as the rules below describe — but do NOT output the "
    "script itself; write the scene-by-scene AI video prompts "
    "instead. Answer with STRICT JSON only: {\"prompts\": "
    "[\"...\", \"...\"]} — no markdown fences, no commentary, "
    "nothing outside the JSON object (the only exception is the "
    "no_speech answer described below).\n\n"
    + SP_AUDIO_TRANSCRIBE_RULES + "\n\n" + SP_SCRIPT_RULES_AUDIO
    + "\n\n" + SP_PROMPT_RULES)

# Chunked transcription (audio over SP_AUDIO_CHUNK_SECONDS): each
# chunk is transcribed on its own — plain transcript text in a
# strict JSON envelope — and the mode's real output is written
# afterwards from the stitched transcript with the two
# instructions below (the audio twins of the caption-route pair:
# same SCRIPT/PROMPT rules, the source worded as a transcript).
SP_AUDIO_CHUNK_INSTRUCTION = (
    "You are given ONE chunk of a video's complete audio track. "
    "Transcribe the speech in this chunk VERBATIM — every spoken "
    "word, in its ORIGINAL language and its original script. "
    "Never translate the dialogue. Answer with STRICT JSON only: "
    "{\"transcript\": \"...\"} — no markdown fences, no "
    "commentary, nothing outside the JSON object. If this chunk "
    "contains NO intelligible speech at all (music only, noise, "
    "or silence), answer with exactly {\"error\": \"no_speech\"} "
    "and nothing else.")

SP_TRANSCRIPT_INSTRUCTION_SCRIPT = (
    "You turn a video's transcript — transcribed from its audio "
    "— into a clean production script. Answer with STRICT JSON "
    "only: {\"script\": \"...\"} — no markdown fences, no "
    "commentary, nothing outside the JSON object.\n\n"
    + SP_SCRIPT_RULES_AUDIO)

SP_TRANSCRIPT_INSTRUCTION_PROMPTS = (
    "You turn a video's transcript — transcribed from its audio "
    "— into ready-to-use AI video generation prompts. First "
    "segment the transcript into scenes and speeches exactly as "
    "the SCRIPT rules below describe — but do NOT output the "
    "script itself. Answer with STRICT JSON only: {\"prompts\": "
    "[\"...\", \"...\"]} — no markdown fences, no commentary, "
    "nothing outside the JSON object.\n\n"
    + SP_SCRIPT_RULES_AUDIO + "\n\n" + SP_PROMPT_RULES)


def _gemini_api_keys():
    """All configured Gemini API keys, in env order: GEMINI_API_KEY,
    then GEMINI_API_KEY_2, then GEMINI_API_KEY_3. Blanks are skipped
    and duplicates removed, order preserved. Quota is per Google
    project AND per model, so every extra key multiplies the day's
    capacity — _gemini_call rotates through (model, key) pairs."""
    keys = []
    for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2",
                 "GEMINI_API_KEY_3"):
        key = (os.environ.get(name) or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def _gemini_api_key():
    keys = _gemini_api_keys()
    return keys[0] if keys else None


def _client_ip():
    fwd = (request.headers.get("X-Forwarded-For") or "") \
        .split(",")[0].strip()
    return fwd or (request.remote_addr or "unknown")


def _sp_rate_try_take(ip):
    """Atomically check this IP's limit and record one hit; True
    when the generation may proceed. Check and record happen in a
    single lock acquisition (audit fix, 2026-11-04): the previous
    check-then-record pair let simultaneous requests from one IP
    each pass the check before any of them recorded, overshooting
    the limit by up to the thread count. The stored hits are
    pruned to the rolling window on every call, and once the
    table grows past 10k IPs the fully-expired entries are swept,
    so the dict cannot grow without bound."""
    now = time.time()
    with _sp_lock:
        hits = [ts for ts in _sp_hits.get(ip, [])
                if now - ts < SP_RATE_WINDOW]
        if len(hits) >= SP_RATE_LIMIT:
            _sp_hits[ip] = hits
            return False
        hits.append(now)
        _sp_hits[ip] = hits
        if len(_sp_hits) > 10000:
            stale = [k for k, v in _sp_hits.items()
                     if not any(now - ts < SP_RATE_WINDOW
                                for ts in v)]
            for k in stale:
                del _sp_hits[k]
        return True


def _sp_rate_give_back(ip):
    """Undo one hit taken by _sp_rate_try_take — used when a
    later pre-check (the daily counter) still rejects the
    request, so a rejected generation never burns the visitor's
    per-IP allowance."""
    with _sp_lock:
        hits = _sp_hits.get(ip)
        if hits:
            hits.pop()


_VTT_TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _vtt_ts_seconds(match):
    hours = int(match.group(1) or 0)
    ms = int(match.group(4).ljust(3, "0"))
    return hours * 3600 + int(match.group(2)) * 60 \
        + int(match.group(3)) + ms / 1000.0


def _fmt_ts(seconds):
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _vtt_timed_script(vtt):
    """Timestamped plain-text script from a WebVTT file: one
    '[M:SS-M:SS] line' per cue, with the rolling duplicates
    auto-captions repeat removed (the same cleaning vtt_to_transcript
    does, but keeping each cue's time range for scene building)."""
    cues = []           # [start, end, text]
    start = end = None
    buf = []

    def _flush():
        if start is None:
            return
        text = re.sub(r"<[^>]+>", "", " ".join(buf))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append([start, end, text])

    for raw in vtt.splitlines():
        line = raw.strip()
        if "-->" in line:
            _flush()
            start = end = None
            buf = []
            parts = line.split("-->")
            m1 = _VTT_TS_RE.search(parts[0])
            m2 = _VTT_TS_RE.search(parts[1]) if len(parts) > 1 else None
            if m1:
                start = _vtt_ts_seconds(m1)
                end = _vtt_ts_seconds(m2) if m2 else start
            continue
        if start is None:
            continue  # header, cue identifiers, NOTE/STYLE blocks
        if not line:
            _flush()
            start = end = None
            buf = []
            continue
        buf.append(line)
    _flush()

    out = []
    for cue_start, cue_end, text in cues:
        if out and text == out[-1][2]:
            out[-1][1] = max(out[-1][1], cue_end)  # roll-up repeat
            continue
        if out and text.startswith(out[-1][2]) \
                and len(text) > len(out[-1][2]):
            out[-1][1] = cue_end  # same line, still growing word by word
            out[-1][2] = text
            continue
        out.append([cue_start, cue_end, text])
    return "\n".join(
        f"[{_fmt_ts(s)}-{_fmt_ts(e)}] {t}" for s, e, t in out)


def _sp_choose_caption(captions, requested):
    """Pick the caption track for the script: the requested language
    when a matching track exists, then Urdu, then English, then the
    first track listed (pick_captions already puts the uploader's own
    tracks and UI languages first)."""
    if not captions:
        return None
    codes = [c["code"] for c in captions]

    def _match(want):
        want = (want or "").strip().lower()
        if not want:
            return None
        for code in codes:
            if code.lower() == want:
                return code
        base = want.split("-")[0]
        for code in codes:
            if code.lower().split("-")[0] == base:
                return code
        return None

    return _match(requested) or _match("ur") or _match("en") or codes[0]


class _GeminiUnavailable(Exception):
    """Every model attempt failed (or a non-retryable error came
    back); the endpoint turns this into a clean 502 ai_unavailable."""


def _gemini_models():
    """The cascade order: the env GEMINI_MODEL override first when
    set (else the default primary), then SP_MODEL_CHAIN in order,
    deduplicated — up to the full 6-model chain."""
    primary = (os.environ.get("GEMINI_MODEL") or "").strip() \
        or SP_DEFAULT_MODEL
    models = [primary]
    for model in SP_MODEL_CHAIN:
        if model not in models:
            models.append(model)
    return models


def _gemini_call(parts, system_instruction, timeout, max_models=None,
                 slow_max_attempts=None):
    """One generateContent call with model + key fallbacks; returns
    (raw_text, model_used). On 404/429/5xx and on network errors the
    next (model, key) pair is tried; anything else fails at once.
    When max_models is given, at most that many models are tried
    (each on every configured key). slow_max_attempts overrides the
    slow-failure attempt cap (SP_GEMINI_SLOW_MAX_ATTEMPTS) — the
    audio route passes SP_AUDIO_SLOW_MAX_ATTEMPTS and the text
    routes pass SP_TEXT_SLOW_MAX_ATTEMPTS, both deeper budgets.

    Pair order: MODELS OUTER, KEYS INNER — the best model is tried
    on every configured key before the cascade moves to the next
    model, because quota is per project AND per model, so a
    quota-dead (project, model) pair says nothing about the same
    model under another project's key.

    Attempt policy: each pair has its own free-tier daily quota,
    and a quota failure comes back FAST (a 429 in well under a
    second), so while attempts keep failing fast the cascade walks
    all the pairs. A SLOW failure (an attempt that consumed
    SP_GEMINI_FAST_FAIL seconds or more — a timeout, an overloaded
    model) flips the call into the bounded mode: total attempts
    then cap at the route's slow budget (slow_max_attempts,
    falling back to SP_GEMINI_SLOW_MAX_ATTEMPTS), so the
    worst-case wait stays bounded by that budget. An API key
    travels in the x-goog-api-key header only —
    it is never put in a URL, a log line or a response."""
    payload = {
        "system_instruction": {
            "parts": [{"text": system_instruction}],
        },
        "contents": [{
            "role": "user",
            "parts": parts,
        }],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    last_error = None
    models = _gemini_models()
    if max_models:
        models = models[:max_models]
    # Models outer, keys inner (see docstring). With a single key
    # configured this is exactly the old model-only cascade.
    pairs = [(model, api_key) for model in models
             for api_key in _gemini_api_keys()]
    attempts = 0
    failures_fast = True  # until an attempt proves slow (see policy)
    for model, api_key in pairs:
        attempts += 1
        started = time.monotonic()
        req = urllib.request.Request(
            GEMINI_API_URL.format(model=model), data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": api_key})
        failed = False
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            app.logger.warning("gemini attempt failed: HTTP %s (model %s)",
                               e.code, model)
            if e.code in (404, 429) or 500 <= e.code < 600:
                failed = True
            else:
                raise _GeminiUnavailable(last_error)
        except Exception as e:  # network error / timeout — try next model
            last_error = type(e).__name__
            app.logger.warning("gemini attempt failed: %s (model %s)",
                               last_error, model)
            failed = True
        if not failed:
            try:
                resp_parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in resp_parts
                               if isinstance(p, dict))
            except (KeyError, IndexError, TypeError):
                text = ""
            if text.strip():
                return text, model
            last_error = "empty response"
            app.logger.warning("gemini returned no text (model %s)", model)
        # This attempt failed (retryable HTTP error, network error
        # or an empty reply). A fast failure is the quota signature
        # — keep walking the chain. A slow one bounds the call:
        # stop once the slow-mode attempt cap is reached.
        if time.monotonic() - started >= SP_GEMINI_FAST_FAIL:
            failures_fast = False
        slow_cap = SP_GEMINI_SLOW_MAX_ATTEMPTS \
            if slow_max_attempts is None else slow_max_attempts
        if not failures_fast and attempts >= slow_cap:
            break
    raise _GeminiUnavailable(str(last_error))


def _gemini_generate_text(timed_script, title, cap_lang, mode):
    """Caption route: timed captions in, the mode's JSON out."""
    system = SP_TEXT_INSTRUCTION_SCRIPT if mode == "script" \
        else SP_TEXT_INSTRUCTION_PROMPTS
    parts = [{"text": (
        f"Video title: {title or 'Untitled'}\n"
        f"Caption language code: {cap_lang}\n\n"
        f"Timed captions:\n{timed_script}")}]
    return _gemini_call(parts, system, SP_GEMINI_TIMEOUT,
                        slow_max_attempts=SP_TEXT_SLOW_MAX_ATTEMPTS)


def _gemini_generate_audio(mp3_path, title, mode):
    """Audio route generation. Audio up to SP_AUDIO_CHUNK_SECONDS
    keeps the single combined call: the MP3 goes inline, Gemini
    transcribes it and answers with the mode's JSON (or the
    no_speech error). LONGER audio is transcribed chunk by chunk
    instead (see _gemini_generate_audio_chunked) — one giant call
    is where long videos used to die. Both paths pass the audio
    route's deeper slow-failure budget to _gemini_call."""
    duration = _sp_probe_duration(mp3_path)
    if duration and duration > SP_AUDIO_CHUNK_SECONDS:
        chunks = _sp_split_audio_chunks(mp3_path)
        if len(chunks) > 1:
            return _gemini_generate_audio_chunked(chunks, title,
                                                  mode)
    with open(mp3_path, "rb") as fh:
        audio_b64 = base64.b64encode(fh.read()).decode("ascii")
    system = SP_AUDIO_INSTRUCTION_SCRIPT if mode == "script" \
        else SP_AUDIO_INSTRUCTION_PROMPTS
    parts = [
        {"inline_data": {"mime_type": "audio/mp3", "data": audio_b64}},
        {"text": (
            f"Video title: {title or 'Untitled'}\n"
            "The attached MP3 is the video's complete audio track. "
            "Follow the system instruction exactly.")},
    ]
    return _gemini_call(parts, system, SP_AUDIO_GEMINI_TIMEOUT,
                        slow_max_attempts=SP_AUDIO_SLOW_MAX_ATTEMPTS)


def _sp_split_audio_chunks(mp3_path):
    """Split an MP3 into pieces of at most SP_AUDIO_CHUNK_SECONDS
    with ffmpeg's segment muxer (stream copy — the input is
    already the normalised 64 kbps shape, so this is fast).
    Returns the chunk paths in play order; [mp3_path] itself when
    splitting is impossible, so the caller falls back to the
    single combined call. The chunks live in a subdirectory of
    the caller's temp dir and are deleted with it."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return [mp3_path]
    outdir = os.path.join(os.path.dirname(mp3_path), "chunks")
    try:
        os.makedirs(outdir, exist_ok=True)
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", mp3_path, "-f", "segment",
             "-segment_time", str(SP_AUDIO_CHUNK_SECONDS),
             "-c", "copy", os.path.join(outdir, "chunk-%03d.mp3")],
            capture_output=True, timeout=SP_FFMPEG_TIMEOUT)
    except Exception:
        return [mp3_path]
    if proc.returncode != 0:
        return [mp3_path]
    chunks = sorted(
        os.path.join(outdir, name) for name in os.listdir(outdir)
        if name.startswith("chunk-") and name.endswith(".mp3"))
    return chunks or [mp3_path]


def _sp_parse_chunk_transcript(raw):
    """One chunk's answer -> its transcript text. The no_speech
    sentinel and a transcript-less answer both count as no speech
    in this chunk (the stitch simply skips it); a bare non-JSON
    reply is taken as the transcript itself."""
    text = (raw or "").strip()
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        return text
    if not isinstance(data, dict) \
            or data.get("error") == "no_speech":
        return ""
    transcript = data.get("transcript")
    return transcript.strip() if isinstance(transcript, str) \
        else ""


def _gemini_transcribe_chunk(chunk_path, title, index, count):
    """Transcribe one audio chunk through the key x model
    rotation (with the audio route's slow budget). Returns the
    chunk's transcript text — '' when the chunk holds no speech.
    Raises _GeminiUnavailable when every pair fails, exactly
    like the single combined call."""
    with open(chunk_path, "rb") as fh:
        audio_b64 = base64.b64encode(fh.read()).decode("ascii")
    parts = [
        {"inline_data": {"mime_type": "audio/mp3", "data": audio_b64}},
        {"text": (
            f"Video title: {title or 'Untitled'}\n"
            f"This is audio chunk {index + 1} of {count} — "
            "transcribe ONLY this chunk, in full.")},
    ]
    raw, _model = _gemini_call(
        parts, SP_AUDIO_CHUNK_INSTRUCTION, SP_AUDIO_GEMINI_TIMEOUT,
        slow_max_attempts=SP_AUDIO_SLOW_MAX_ATTEMPTS)
    return _sp_parse_chunk_transcript(raw)


def _gemini_generate_from_transcript(transcript, title, mode):
    """The chunked route's second stage: write the mode's JSON
    from a stitched transcript. The transcript is capped at
    SP_INPUT_LIMIT, the same input cap the caption route
    applies."""
    if len(transcript) > SP_INPUT_LIMIT:
        cut = transcript[:SP_INPUT_LIMIT]
        transcript = cut[:cut.rfind("\n")].rstrip() \
            if "\n" in cut else cut
    system = SP_TRANSCRIPT_INSTRUCTION_SCRIPT if mode == "script" \
        else SP_TRANSCRIPT_INSTRUCTION_PROMPTS
    parts = [{"text": (
        f"Video title: {title or 'Untitled'}\n\n"
        f"Transcript:\n{transcript}")}]
    return _gemini_call(parts, system, SP_GEMINI_TIMEOUT,
                        slow_max_attempts=SP_AUDIO_SLOW_MAX_ATTEMPTS)


def _gemini_generate_audio_chunked(chunks, title, mode):
    """The chunked audio route: transcribe every chunk in order
    through the rotation, stitch the transcripts, then write the
    mode's JSON from the stitched text. A chunk failing on every
    (model, key) pair raises _GeminiUnavailable — the endpoint's
    ai_unavailable, unchanged. When NO chunk holds speech, the
    answer is the same {"error": "no_speech"} JSON the single
    combined call would have produced, so _sp_parse_output
    upstream behaves identically."""
    pieces = []
    for index, chunk in enumerate(chunks):
        text = _gemini_transcribe_chunk(chunk, title, index,
                                        len(chunks))
        if text:
            pieces.append(text)
    if not pieces:
        return json.dumps({"error": "no_speech"}), ""
    return _gemini_generate_from_transcript(
        "\n".join(pieces), title, mode)


def _gemini_generate_prompts_from_script(script_text):
    """Preview flow: prompts built from the visitor's own (possibly
    edited) script text — no caption or audio fetch happens."""
    parts = [{"text": (
        "The script of the video, provided or edited by the user:\n\n"
        + script_text)}]
    return _gemini_call(parts, SP_SCRIPT_INSTRUCTION_PROMPTS,
                        SP_GEMINI_TIMEOUT,
                        slow_max_attempts=SP_TEXT_SLOW_MAX_ATTEMPTS)


def _sp_parse_output(raw):
    """Defensive parse of the model's reply -> (script, prompts,
    partial, no_speech). Strips markdown fences; when the JSON will
    not parse, the raw text is handed back as the script with an
    empty prompts list and partial=True so the visitor still gets
    something. no_speech is set when the model answers with the
    audio route's {"error": "no_speech"} object."""
    text = (raw or "").strip()
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except ValueError:
        return text, [], True, False
    if not isinstance(data, dict):
        return text, [], True, False
    if data.get("error") == "no_speech":
        return "", [], False, True
    script = data.get("script")
    script = script.strip() if isinstance(script, str) else ""
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        prompts = []
    prompts = [str(p).strip() for p in prompts if str(p).strip()]
    partial = not script and not prompts
    return script, prompts, partial, False


class _SpAudioTooBig(Exception):
    """The converted MP3 is over the hard size cap."""


class _SpAudioFailed(Exception):
    """The audio could not be downloaded or converted at all."""


# Audio-route format strategies. The trap these guard against:
# some sources (TikTok above all) expose a long standalone "sound"
# asset next to the video, and a bare "bestaudio" happily grabs
# THAT — a music track that can run LONGER than the video itself
# and contain no speech at all (a 105 s story video shipped a 164 s
# music file, and Gemini quite correctly reported no_speech for
# it). Two defences, combined:
#
# * The duration guard (below): when the video's duration is known,
#   a candidate that disagrees with it is rejected as the wrong
#   track, whatever strategy produced it.
# * The strategy ORDER depends on whether that guard can protect
#   the fetch:
#   - Duration KNOWN — the small audio-only download goes first
#     (a matching track is a fraction of the video's size, so this
#     is the fast path; a mismatched one is caught by the guard),
#     then the muxed format, then plain "bestaudio/best".
#   - Duration UNKNOWN — the guard is blind, so the pre-merged
#     (video+audio) format goes first: it always carries the
#     video's OWN audio track. "bestaudio" is only the fallback.
_SP_AUDIO_ONLY = ("audio", "bestaudio[acodec!=none]/bestaudio")
_SP_AUDIO_MUXED = (
    "muxed",
    "best[height<=720][vcodec!=none][acodec!=none]"
    "/best[vcodec!=none][acodec!=none]")
_SP_AUDIO_BEST = ("bestaudio", "bestaudio/best")
SP_AUDIO_STRATEGIES = (_SP_AUDIO_MUXED, _SP_AUDIO_BEST)
SP_AUDIO_STRATEGIES_KNOWN_DURATION = (
    _SP_AUDIO_ONLY, _SP_AUDIO_MUXED, _SP_AUDIO_BEST)


def _sp_audio_strategies(expected_duration):
    """Strategy order for one audio fetch: audio-first when the
    duration guard can vet the result, muxed-first when it cannot."""
    if expected_duration:
        return SP_AUDIO_STRATEGIES_KNOWN_DURATION
    return SP_AUDIO_STRATEGIES
# A candidate whose duration disagrees with the video's known
# duration by more than this fraction cannot be the video's own
# audio — it is rejected and the next strategy is tried.
SP_AUDIO_DURATION_TOLERANCE = 0.20


def _sp_probe_duration(path):
    """Duration in seconds of a media file (ffprobe); None when it
    cannot be determined — the duration guard then stays out of the
    way rather than blocking on an unknown."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60)
        return float((out.stdout or "").strip())
    except Exception:
        return None


def _sp_duration_mismatch(expected, actual):
    """True when a downloaded candidate cannot be the video's own
    audio: both durations known and differing by more than the
    tolerance. An unknown duration never counts as a mismatch."""
    if not expected or not actual:
        return False
    return abs(actual - expected) \
        > SP_AUDIO_DURATION_TOLERANCE * expected


def _sp_convert_to_mp3(src, mp3_path):
    """Normalise any extracted media file to the transcription
    input shape: 16 kHz mono 64 kbps MP3 — the canonical ASR
    recipe (research §9: ~20x smaller than typical source audio
    with no accuracy loss for speech; a 20-minute file is
    ~9.6 MB, comfortably under Gemini's 20 MB inline cap).
    Returns True on success."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", src, "-vn", "-ar", "16000",
             "-ac", "1", "-codec:a", "libmp3lame", "-b:a", "64k",
             mp3_path],
            capture_output=True, timeout=SP_FFMPEG_TIMEOUT)
    except Exception:
        return False
    return proc.returncode == 0 and os.path.exists(mp3_path) \
        and os.path.getsize(mp3_path) > 0


def _sp_audio_from_tikwm(url, info, expected_duration):
    """Audio route for a tikwm-resolved TikTok: yt-dlp cannot
    fetch this post at all (that is why tikwm resolved it), so
    the audio is taken from tikwm's own stream URLs instead.
    The play/hdplay MP4 carries the VIDEO'S OWN audio — the
    resolver's music field is never used here: it can be a
    separate background song that runs LONGER than the video
    and contains no speech (the 164 s trap the duration guard
    exists for), and the same guard vets this download.
    Returns (mp3_path, tmpdir), or None when no stream could be
    fetched — the caller then falls through to the yt-dlp
    strategies, which fail the usual way."""
    candidates = [f for f in info.get("formats") or []
                  if f.get("url") and f.get("vcodec") != "none"
                  and f.get("acodec") != "none"]
    for fmt in candidates:  # shaped order: hdplay first, then play
        tmpdir = tempfile.mkdtemp(prefix="qgrab-sp-")
        src = os.path.join(tmpdir, "source.mp4")
        try:
            _fetch_to_file(fmt["url"], src, timeout=180)
        except Exception as e:
            app.logger.info(
                "script-prompt tikwm audio fetch failed for "
                "%s: %s", url, e)
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
        actual = _sp_probe_duration(src)
        if _sp_duration_mismatch(expected_duration, actual):
            app.logger.info(
                "script-prompt audio rejected tikwm candidate "
                "for %s: duration %.1fs vs video %.1fs "
                "(wrong track)", url, actual, expected_duration)
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
        mp3 = os.path.join(tmpdir, "audio.mp3")
        if not _sp_convert_to_mp3(src, mp3):
            app.logger.info(
                "script-prompt tikwm audio convert failed "
                "for %s", url)
            shutil.rmtree(tmpdir, ignore_errors=True)
            continue
        if os.path.getsize(mp3) > SP_AUDIO_MAX_BYTES:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise _SpAudioTooBig()
        app.logger.info(
            "script-prompt audio via tikwm stream for %s", url)
        return mp3, tmpdir
    return None


def _sp_download_audio_mp3(url, expected_duration=None,
                           source_info=None):
    """Audio route, step 1: fetch the VIDEO'S OWN audio and convert
    it with ffmpeg to a mono 64 kbps MP3 — small enough to send to
    Gemini inline (20 min ≈ 9.6 MB). To bound the visitor's wait,
    the fetch walks at most the first SP_AUDIO_MAX_ATTEMPTS cascade
    attempts (the download endpoints keep the full cascade), and
    inside each attempt the format strategies in the order given by
    _sp_audio_strategies (audio-first when the duration is known,
    muxed-first when it is not).

    When the video's duration is known (expected_duration, from the
    extracted metadata), a candidate whose probed duration disagrees
    by more than SP_AUDIO_DURATION_TOLERANCE is the wrong track (the
    TikTok music-asset trap) — it is rejected and the next strategy
    is tried instead of transcribing silence.

    When the metadata came from the tikwm resolver (source_info —
    the caller's extract_info result), yt-dlp cannot fetch the
    post, so the audio is taken from tikwm's own MP4 streams
    first (see _sp_audio_from_tikwm).

    Returns (mp3_path, tmpdir); the CALLER owns deleting tmpdir.
    Raises _SpAudioTooBig when the converted file passes the 18 MB
    cap and _SpAudioFailed when every attempt fails."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise _SpAudioFailed("ffmpeg missing")
    if source_info is not None \
            and source_info.get("_qgrab_source") == "tikwm":
        direct = _sp_audio_from_tikwm(url, source_info,
                                      expected_duration)
        if direct is not None:
            return direct
    last_error = None
    attempts = _ordered_attempts(url)[:SP_AUDIO_MAX_ATTEMPTS]
    for spec in attempts:
        if not _cascade_gate_open(spec, last_error):
            break
        for strategy, selector in _sp_audio_strategies(
                expected_duration):
            tmpdir = tempfile.mkdtemp(prefix="qgrab-sp-")
            outtmpl = os.path.join(tmpdir, f"{uuid.uuid4().hex}.%(ext)s")
            opts = _build_opts(spec, {
                "format": selector,
                "outtmpl": outtmpl,
            }, url=url)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.extract_info(url, download=True)
            except Exception as e:
                last_error = e
                app.logger.info(
                    "script-prompt audio attempt failed (strategy=%s "
                    "client=%s impersonate=%s) for %s: %s",
                    strategy, spec.get("client"),
                    spec.get("impersonate"), url, e)
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            src = _find_produced_file(tmpdir)
            if not src:
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            actual = _sp_probe_duration(src)
            if _sp_duration_mismatch(expected_duration, actual):
                app.logger.info(
                    "script-prompt audio rejected %s candidate for "
                    "%s: duration %.1fs vs video %.1fs (wrong track)",
                    strategy, url, actual, expected_duration)
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            mp3 = os.path.join(tmpdir, "audio.mp3")
            if not _sp_convert_to_mp3(src, mp3):
                app.logger.info(
                    "script-prompt audio convert failed for %s", url)
                shutil.rmtree(tmpdir, ignore_errors=True)
                continue
            if os.path.getsize(mp3) > SP_AUDIO_MAX_BYTES:
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise _SpAudioTooBig()
            _remember_winner(url, spec)
            return mp3, tmpdir
    raise _SpAudioFailed(str(last_error))


# ---------------------------------------------------------------------------
# Script+Prompt daily counters (the owner's TAAFT-style counter)
#
# The tool is free and the Google quota behind it is finite, so the
# box shows two honest counters — "Scripts left today: N" and
# "Prompts left today: N" — one per mode, each capped at
# SP_DAILY_CAP_* successful generations and counting DOWN, exactly
# like the clip counters on the owner's video tool. The counters
# are REAL, enforced here on the server: a slot is RESERVED when a
# job starts (so simultaneous visitors cannot overshoot the cap),
# a success turns the reservation into a counted generation, and a
# failure REFUNDS it — the same shape as the video tool refunding
# credits for a failed clip. The "day" is the Google quota day:
# it rolls over at midnight in America/Los_Angeles, and
# /api/script-prompt/quota reports that next reset as a UTC epoch
# so the page can show the refresh time in the visitor's own local
# time. State is in memory only, like the per-IP limiter — a
# restart starts a fresh day early, never a stricter one.
# ---------------------------------------------------------------------------

# Cap derivation: the free capacity behind the tool is the stacked
# Gemini free quotas — 3 API keys (3 projects) x 6 cascade models
# x ~20 free requests/day per model per project (the observed
# free-tier floor) = ~360 generations/day in one shared pool. The
# per-mode caps below sum to 300, deliberately under that floor,
# so a counter-full day still leaves the cascade headroom. Retune
# here if keys or models are added, or if the quotas change.
SP_DAILY_CAP_SCRIPT = 150     # successful script generations per day
SP_DAILY_CAP_PROMPTS = 150    # successful prompt generations per day
SP_DAILY_CAPS = {"script": SP_DAILY_CAP_SCRIPT,
                 "prompts": SP_DAILY_CAP_PROMPTS}
_SP_QUOTA_TZ = ZoneInfo("America/Los_Angeles")

_sp_daily_lock = threading.Lock()
_sp_daily = {"date": None,
             "done": {"script": 0, "prompts": 0},
             "reserved": {"script": 0, "prompts": 0}}


def _sp_quota_now():
    """Now on the Google quota clock (America/Los_Angeles)."""
    return datetime.now(_SP_QUOTA_TZ)


def _sp_next_reset():
    """The next Pacific midnight — when the counters refresh."""
    now = _sp_quota_now()
    nxt = now.date() + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day,
                    tzinfo=_SP_QUOTA_TZ)


def _sp_quota_rollover_locked():
    """Reset the counts when the Pacific date has rolled over.
    Caller holds _sp_daily_lock."""
    today = _sp_quota_now().date()
    if _sp_daily["date"] != today:
        _sp_daily["date"] = today
        _sp_daily["done"] = {"script": 0, "prompts": 0}
        _sp_daily["reserved"] = {"script": 0, "prompts": 0}


def _sp_quota_reserve(mode):
    """Reserve one slot for a job that is about to start. False
    when the mode's day is already full (successes + in-flight
    reservations at the cap)."""
    with _sp_daily_lock:
        _sp_quota_rollover_locked()
        used = _sp_daily["done"][mode] \
            + _sp_daily["reserved"][mode]
        if used >= SP_DAILY_CAPS[mode]:
            return False
        _sp_daily["reserved"][mode] += 1
        return True


def _sp_quota_settle(mode, success):
    """Settle a finished job's reservation: a success becomes a
    counted generation; a failure refunds the slot."""
    if mode not in SP_DAILY_CAPS:
        return
    with _sp_daily_lock:
        _sp_quota_rollover_locked()
        _sp_daily["reserved"][mode] = max(
            0, _sp_daily["reserved"][mode] - 1)
        if success:
            _sp_daily["done"][mode] += 1


def _sp_quota_snapshot():
    """The public counter state served by
    GET /api/script-prompt/quota (read-only; never generates)."""
    with _sp_daily_lock:
        _sp_quota_rollover_locked()
        left = {mode: max(0, SP_DAILY_CAPS[mode]
                          - _sp_daily["done"][mode]
                          - _sp_daily["reserved"][mode])
                for mode in SP_DAILY_CAPS}
    return {
        "script_left": left["script"],
        "prompts_left": left["prompts"],
        "script_max": SP_DAILY_CAP_SCRIPT,
        "prompts_max": SP_DAILY_CAP_PROMPTS,
        "resets_at": int(_sp_next_reset().timestamp()),
    }


# ---------------------------------------------------------------------------
# Script+Prompt background jobs (v3 reliability pass)
#
# Generation can take a minute or more (the audio route listens to
# the whole video), and a synchronous request leaves the visitor's
# page hanging on one fragile connection the entire time — on a
# slow phone the response is simply lost and the wait was for
# nothing. So POST now only runs the cheap synchronous pre-checks,
# starts the UNCHANGED generation logic on a daemon thread, and
# answers 202 at once; the client polls /api/script-prompt/status
# until the job is done or has failed with the same error code the
# synchronous flow would have produced. Jobs live in memory only
# (the same spirit as the rate limiter): a restart drops them, and
# a lazy janitor on each POST/status call drops jobs older than
# SP_JOB_TTL_SECONDS.
# ---------------------------------------------------------------------------

SP_JOB_TTL_SECONDS = 20 * 60  # jobs are dropped 20 minutes after creation

_sp_jobs = {}
_sp_jobs_lock = threading.Lock()


def _sp_jobs_prune(now=None):
    """Lazy janitor: drop jobs older than the TTL. Called on each
    POST and each status poll — no background sweeper needed."""
    now = time.time() if now is None else now
    with _sp_jobs_lock:
        stale = [job_id for job_id, job in _sp_jobs.items()
                 if now - job["created"] > SP_JOB_TTL_SECONDS]
        for job_id in stale:
            del _sp_jobs[job_id]


def _sp_job_create(mode=None):
    job_id = uuid.uuid4().hex
    job = {
        "status": "running",
        "created": time.time(),
        "finished": None,
        "result": None,
        "error": None,
        "http": None,
        "mode": mode,
    }
    with _sp_jobs_lock:
        _sp_jobs[job_id] = job
    return job_id


def _sp_job_finish(job_id, payload, http_status):
    with _sp_jobs_lock:
        job = _sp_jobs.get(job_id)
        if job is None:
            return
        job["finished"] = time.time()
        if http_status == 200:
            job["status"] = "done"
            job["result"] = payload
        else:
            job["status"] = "error"
            job["error"] = (payload or {}).get("error") \
                or "ai_unavailable"
            job["http"] = http_status


def _sp_job_run(job_id, data, url, mode, requested):
    """Worker thread body: run the existing generation logic and
    file its outcome on the job. Any unexpected failure becomes the
    same ai_unavailable the UI already knows how to show."""
    try:
        payload, http_status = _sp_generate_payload(
            data, url, mode, requested)
    except Exception as e:
        app.logger.warning(
            "script-prompt job %s crashed for %s: %s",
            job_id, url, e)
        payload, http_status = {"error": "ai_unavailable"}, 502
    _sp_job_finish(job_id, payload, http_status)
    # Settle the daily-counter slot reserved at POST time: a
    # success counts, a failure is refunded. Runs exactly once
    # per job, whatever the outcome was.
    _sp_quota_settle(mode, http_status == 200)


@app.route("/api/script-prompt", methods=["POST"])
def api_script_prompt():
    """Video -> Script + AI Prompts (v3, asynchronous).

    Called ONLY from the tool's own two buttons (homepage section /
    dedicated page) — never automatically, and not by the
    download-result area's button (that one only scrolls + fills
    the tool's input). The request carries "mode": "script" returns
    ONLY the script, "prompts" returns ONLY the prompts (a missing
    or invalid mode defaults to "script"). In prompts mode an
    optional "script" field — the visitor's own (edited) script
    from the preview box — becomes the source instead, and nothing
    is fetched.

    This POST runs only the synchronous pre-checks and answers
    them exactly as before — 400 invalid_url · 503 not_configured
    · 429 rate_limited · 429 daily_limit (the mode's daily
    counter is full) — counting the generation against the
    per-IP limit once, here at POST time, and reserving one slot
    of the mode's daily counter (refunded if the job fails). On
    success it starts the
    generation as a background job and returns 202 {"job_id",
    "status": "running"}; the outcome (the exact payload the old
    synchronous flow returned, or one of its error codes — 422
    fetch_failed · 422 no_subtitles · 422 too_long · 422
    audio_too_big · 422 no_speech · 502 ai_unavailable) is
    delivered by GET /api/script-prompt/status."""
    data = request.get_json(silent=True) or {}
    url = clean_url(data.get("url", ""))
    if not url:
        return jsonify({"error": "invalid_url"}), 400
    if not _gemini_api_key():
        return jsonify({"error": "not_configured"}), 503
    ip = _client_ip()
    if not _sp_rate_try_take(ip):
        return jsonify({"error": "rate_limited"}), 429
    mode = str(data.get("mode") or "").strip().lower()
    if mode not in ("script", "prompts"):
        mode = "script"
    requested = str(data.get("lang") or "").strip()
    if requested and not _CAPTION_LANG_RE.match(requested):
        requested = ""
    if not _sp_quota_reserve(mode):
        # The daily counter is full: hand the per-IP hit back so
        # this rejection costs the visitor nothing.
        _sp_rate_give_back(ip)
        return jsonify({"error": "daily_limit"}), 429
    _sp_jobs_prune()
    job_id = _sp_job_create(mode)
    worker = threading.Thread(
        target=_sp_job_run,
        args=(job_id, dict(data), url, mode, requested),
        daemon=True)
    worker.start()
    return jsonify({"job_id": job_id, "status": "running"}), 202


@app.route("/api/script-prompt/status", methods=["GET"])
def api_script_prompt_status():
    """Poll a background generation job. 200 {"status": "running"}
    while it works; on success 200 {"status": "done", ...the exact
    payload the generation produced...}; on failure 200
    {"status": "error", "error": <code>, "http": <the status the
    synchronous flow would have answered>}. An unknown or expired
    job id is a plain 404 {"error": "job_not_found"}."""
    _sp_jobs_prune()
    job_id = (request.args.get("id") or "").strip()
    with _sp_jobs_lock:
        job = _sp_jobs.get(job_id)
        snapshot = dict(job) if job is not None else None
    if snapshot is None:
        return jsonify({"error": "job_not_found"}), 404
    if snapshot["status"] == "running":
        return jsonify({"status": "running"})
    if snapshot["status"] == "done":
        payload = dict(snapshot["result"] or {})
        payload["status"] = "done"
        return jsonify(payload)
    return jsonify({
        "status": "error",
        "error": snapshot["error"],
        "http": snapshot["http"],
    })


@app.route("/api/script-prompt/quota", methods=["GET"])
def api_script_prompt_quota():
    """The daily counters, read-only: how many script / prompt
    generations are left today (the America/Los_Angeles day),
    each mode's cap, and "resets_at" — the next Pacific midnight
    as a UTC epoch, so the page can show the refresh time in the
    visitor's own local time. Reading it never generates
    anything and never touches the counters."""
    return jsonify(_sp_quota_snapshot())


def _sp_has_audio_track(info):
    """True when extracted metadata lists at least one format that
    carries audio (muxed or audio-only). A format whose codec
    field is missing counts as carrying audio — the same
    convention pick_formats uses. False with no info, or when the
    video genuinely has no audio-bearing format at all."""
    if not info:
        return False
    return any(f.get("acodec") != "none"
               for f in info.get("formats") or [])


def _sp_generate_payload(data, url, mode, requested):
    """The generation itself (v2 logic, unchanged): the video's
    own captions when a usable track exists, otherwise the AUDIO
    route — the audio is downloaded, converted to a small MP3 and
    transcribed by Gemini (videos up to 20 minutes; caption-route
    videos have no length limit). Runs on a worker thread and
    returns (payload, http_status) instead of a Flask response;
    the per-IP rate limit was already counted once by the POST
    handler, so nothing is recorded here."""
    # Preview flow: prompts built from the visitor's own script
    # text (the editable script box). A non-empty script within the
    # input cap is the source — the caption/audio fetch is skipped
    # entirely; an over-cap or empty one is ignored and the normal
    # flow below runs. Still one rate-limited generation, still the
    # same usool instruction.
    if mode == "prompts":
        provided = data.get("script")
        if isinstance(provided, str) and provided.strip() \
                and len(provided) <= SP_INPUT_LIMIT:
            try:
                raw, model = _gemini_generate_prompts_from_script(
                    provided.strip())
            except _GeminiUnavailable as e:
                app.logger.warning(
                    "script-prompt gemini (user script) failed for "
                    "%s: %s", url, e)
                return {"error": "ai_unavailable"}, 502
            _s, prompts, partial, _ns = _sp_parse_output(raw)
            return {
                "title": "Untitled",
                "lang": None,
                "mode": mode,
                "route": "script",
                "script": "",
                "prompts": prompts,
                "truncated": False,
                "partial": partial or not prompts,
                "model": model,
            }, 200
    info = None
    info_failed = False
    try:
        info = extract_info(url)
    except Exception as e:
        # Extraction failed; the audio route below re-extracts as
        # part of its own download cascade, so it still gets a try.
        # Remember the failure, though: if the audio cascade then
        # fails too, the video could not be FETCHED at all — which
        # is a fetch_failed story, not a no_subtitles one.
        info_failed = True
        app.logger.info("script-prompt info failed for %s: %s", url, e)
    if info is not None and info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if entries:
            info = entries[0]
    title = (info or {}).get("title")

    # --- Route 1: the video's own captions -------------------------
    timed = None
    chosen = None
    if info is not None:
        chosen = _sp_choose_caption(pick_captions(info), requested)
    if chosen:
        try:
            vtt, cap_title = _fetch_caption_vtt(url, chosen)
            title = cap_title or title
            candidate = _vtt_timed_script(vtt)
            if candidate.strip():
                timed = candidate
        except Exception as e:
            app.logger.info(
                "script-prompt captions failed for %s [%s]: %s",
                url, chosen, e)
    if timed is not None:
        truncated = len(timed) > SP_INPUT_LIMIT
        if truncated:
            cut = timed[:SP_INPUT_LIMIT]
            timed = cut[:cut.rfind("\n")].rstrip() if "\n" in cut \
                else cut
        try:
            raw, model = _gemini_generate_text(
                timed, title, chosen, mode)
        except _GeminiUnavailable as e:
            app.logger.warning(
                "script-prompt gemini failed for %s: %s", url, e)
            return {"error": "ai_unavailable"}, 502
        script, prompts, partial, _ns = _sp_parse_output(raw)
        if mode == "script":
            if not script:
                # v1 fallback: hand the model's raw text back rather
                # than an empty pane.
                script, prompts, partial = raw.strip(), [], True
            else:
                prompts = []
        else:
            script = ""
            partial = partial or not prompts
        return {
            "title": title or "Untitled",
            "lang": chosen,
            "mode": mode,
            "route": "captions",
            "script": script,
            "prompts": prompts,
            "truncated": truncated,
            "partial": partial,
            "model": model,
        }, 200

    # --- Route 2: listen to the audio (Gemini transcription) -------
    duration = (info or {}).get("duration")
    if duration and duration > SP_AUDIO_MAX_SECONDS:
        return {"error": "too_long"}, 422
    try:
        mp3_path, tmpdir = _sp_download_audio_mp3(
            url, expected_duration=duration, source_info=info)
    except _SpAudioTooBig:
        return {"error": "audio_too_big"}, 422
    except _SpAudioFailed as e:
        # Neither captions nor audio could be obtained. Which of
        # the two stories is true decides the error the visitor
        # sees:
        # * fetch_failed — the video could not be FETCHED at all:
        #   metadata extraction failed AND the audio cascade (which
        #   re-extracts on its own) failed too, or the metadata
        #   shows an audio track the cascade still could not pull.
        #   Platforms refuse in bursts, so this is usually a
        #   "try again in a few minutes" situation — reporting
        #   no_subtitles here would be a lie about the video.
        # * no_subtitles — reserved for a video that WAS read and
        #   simply has neither usable captions nor any audio track
        #   for the audio route to listen to.
        if info_failed or _sp_has_audio_track(info):
            app.logger.info(
                "script-prompt fetch failed for %s: %s", url, e)
            return {"error": "fetch_failed"}, 422
        app.logger.info("script-prompt audio failed for %s: %s",
                        url, e)
        return {"error": "no_subtitles"}, 422
    try:
        try:
            raw, model = _gemini_generate_audio(mp3_path, title, mode)
        except _GeminiUnavailable as e:
            app.logger.warning(
                "script-prompt gemini (audio) failed for %s: %s",
                url, e)
            return {"error": "ai_unavailable"}, 502
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    script, prompts, partial, no_speech = _sp_parse_output(raw)
    if no_speech or (not script and not prompts):
        return {"error": "no_speech"}, 422
    if mode == "script":
        prompts = []
    else:
        script = ""
        partial = partial or not prompts
    return {
        "title": title or "Untitled",
        "lang": None,
        "mode": mode,
        "route": "audio",
        "script": script,
        "prompts": prompts,
        "truncated": False,
        "partial": partial,
        "model": model,
    }, 200


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
                    samesite="Lax", secure=True, httponly=True)
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
