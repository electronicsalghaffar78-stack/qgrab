# App tweaks for deployment — notes only, app.py is NOT modified

> Update (2026-11-03): one change HAS since landed in `app.py` itself —
> the extraction resilience engine described in the last section below.
> It is part of `app.py` in both the local and the deployment copy
> (byte-identical), not a deploy-only patch. Everything above this line
> still describes the original launch state.

`app.py` runs under the production image **as-is**. This file records why,
and the optional tweaks worth knowing about. Nothing here is applied to
the local app.

## No change needed — and why

- **Port:** `app.py` already reads the `PORT` environment variable
  (default 5000). Under gunicorn the `app.run(...)` block never executes
  at all — gunicorn imports `app:app` and binds `$PORT` itself, so the
  development default `HOST=127.0.0.1` is irrelevant in production.
- **ffmpeg:** called by yt-dlp for merged downloads; provided by the
  Dockerfile's `apt-get install ffmpeg`, not by the app.
- **Storage:** the app keeps no state. Merged downloads go to the system
  temp dir and are deleted when the response closes — a perfect fit for
  Render Free's ephemeral filesystem (no persistent disk exists there).
- **Health check:** `/healthz` already exists → used as Render's
  health-check path.

## If the app is ever run WITHOUT gunicorn on a host

Set `HOST=0.0.0.0` (e.g. `HOST=0.0.0.0 PORT=5000 python app.py`), or the
server will only listen on localhost inside the container and the public
URL will never reach it. This is the one "tweak" to remember; it is an
environment setting, not a code change.

## Optional tweaks — documented, deliberately NOT applied

1. **Cap merged downloads at 720p on the free tier.** In
   `pick_formats()` the merged options are capped with `h <= 1080`.
   On Render Free (512 MB RAM, 0.1 CPU, small temp disk), a 1080p merge
   means downloading ~200–600 MB and holding two files plus the merged
   output at once — it can be slow or run out of room. Changing the cap
   to `720` for the hosted copy would make test-launch merges much more
   reliable. Left unapplied because the same `app.py` serves the local
   full-power version; apply it only to the hosted copy if 1080p merges
   misbehave in testing.
2. **Refresh yt-dlp before launch day.** `requirements.txt` pins
   `yt-dlp==2026.10.26`. Platforms change constantly; on launch morning,
   bump the pin to the then-latest release in the *deployment repo copy*
   and rebuild (Render rebuilds automatically on push).
3. **Concurrency ceiling.** With 1 gunicorn worker × 8 threads, at most
   ~8 downloads stream at once and `/api/info` calls share the same
   threads. Fine for a test launch with a handful of visitors; a real
   launch needs a bigger instance, not a code change.

## Engine resilience — client cascade + impersonation

Added 2026-11-03 after the live Render test showed Facebook working but
YouTube blocked ("Sign in to confirm you're not a bot") and TikTok
failing ("Unexpected response from webpage request") from the cloud IP.
`app.py` (both copies, byte-identical) now extracts through an ordered
cascade of yt-dlp configurations, in `extract_info()` and
`download_merged()` alike:

- **YouTube:** default client → `player_client=tv` → `android_vr` →
  `web_safari`. Each attempt is bounded by the existing 20s
  `socket_timeout`; an attempt that returns a page with no real formats
  also counts as failed and the cascade moves on.
- **TikTok:** curl_cffi browser impersonation (`impersonate=chrome`)
  first, plain request as fallback.
- **Facebook:** plain first (proven working), one impersonation retry
  on failure. Other sites: plain first, impersonation retry only when
  the error looks like a webpage/403-style block.
- **Winner cache:** the configuration that succeeded is remembered per
  URL for 10 minutes, so `/download` re-uses the exact client that
  `/api/info` succeeded with instead of re-running the cascade.
- **Errors:** visitors now only see one friendly message ("This link
  could not be read — the platform may be limiting our server right
  now. Please try again later."); raw yt-dlp errors are logged
  server-side.
- **Dependency:** `curl_cffi==0.17.0` added to `requirements.txt`. If
  it is ever missing, the app degrades gracefully — impersonation
  attempts are skipped and the plain cascade still runs.

Local verification (2026-11-03): unit tests confirm the cascade order,
winner caching, empty-formats handling and graceful degradation. Live
local tests: Facebook info + proxied download + merged download all
pass. Note this dev machine's egress IP is ALSO flagged by YouTube and
TikTok (hard bot wall / IP block on every client; alternate clients
return only storyboard formats), so YouTube/TikTok success from a
cloud IP remains unproven until this build runs on Render — the
cascade gives each platform several distinct chances per request
instead of one, but no client trick can force a platform to serve
formats to an IP it has decided to block outright.
