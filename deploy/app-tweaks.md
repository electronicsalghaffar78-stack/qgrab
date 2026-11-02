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

## Download proxy impersonation

Added 2026-11-03 after the first live run of the cascade build on
Render: TikTok `/api/info` now succeeded (extraction impersonation
works), but `/download` of a TikTok format returned "502 — Upstream
returned 403". The proxied media fetch in the `/download` route still
used plain `urllib.request`, and TikTok's CDN fingerprints the TLS
handshake of the media request itself — impersonating only the page
extraction is not enough.

`app.py` (both copies, byte-identical) now opens the proxied media
stream through a helper, `_open_media_stream()`:

- **Primary path:** `curl_cffi.requests.get(..., impersonate="chrome",
  stream=True, timeout=30)` with the exact headers dict the route
  already built (the format's `http_headers` from yt-dlp, the default
  User-Agent, and the visitor's `Range` header passed through).
- **Fallback:** if curl_cffi is unavailable, the impersonated request
  raises a connection-level error, OR it returns an HTTP error status,
  the original urllib fetch gets one second chance (some other CDN may
  dislike impersonation while tolerating a plain request — the reverse
  of TikTok). Only when both paths fail does the route answer 502,
  keeping the existing message shapes: "Upstream returned {code}" when
  either attempt produced an HTTP status (urllib's own status wins as
  the most recent answer), otherwise "Could not reach the media
  server.".
- **Contract preserved:** upstream status is returned to the visitor;
  `Content-Disposition` filename headers, `Content-Length`,
  `Content-Range` and `Accept-Ranges` pass through unchanged; the body
  streams in 256 KB chunks and the upstream response is closed when
  the stream finishes. The merged path (`download_merged`, which
  downloads via yt-dlp itself) is untouched.
- **Dependency:** none new — `curl_cffi==0.17.0` was already pinned
  for extraction impersonation. If it is ever missing, the proxy
  silently degrades to the urllib-only behavior.

## yt-dlp native download fallback

Added 2026-11-03 after the impersonated proxy went live on Render:
TikTok `/api/info` succeeds there, yet `/download` STILL returned
"502 — Upstream returned 403" through both the curl_cffi impersonated
fetch and the urllib fallback. Working theory: the media URL TikTok
hands out is bound to the extraction session (cookies/fingerprint
carried inside yt-dlp) — the extract-then-fetch-separately flow loses
that session, and TikTok's CDN also 403s datacenter IPs on direct
media fetches. yt-dlp downloading natively keeps the session
end-to-end, which is why yt-dlp itself can download TikTok whenever
its extraction succeeds.

`app.py` (both copies, byte-identical) now has a helper,
`_download_via_ytdlp(url, format_id)`, wired into the `/download`
route as a last resort — the visitor-visible behavior is otherwise
unchanged:

- **When it runs:** (1) after the proxied fetch ultimately fails —
  at the exact point the route used to abort 502; (2) defensively,
  when the extraction re-check inside `/download` succeeds but yields
  no target format URL — at the point the route used to abort 404.
  The `merge:` path is untouched (it already downloads via yt-dlp).
- **How it downloads:** walks the same attempt cascade as
  `download_merged()` (cached winner first, same `webpage_errors_only`
  gate), building opts via `_build_opts`. The format selector is the
  exact requested format id (a bare format id IS a valid yt-dlp
  selector); if a client rejects it, that attempt is retried once
  with `"<id>/best"`. The file lands in a fresh temp dir via
  `extract_info(url, download=True)`; the produced path is resolved
  with `prepare_filename`, falling back to the single file left in
  the temp dir when the extension differs (the same mismatch class
  `download_merged` patches). On success the winning spec is
  remembered, exactly like the other paths.
- **Response contract:** `send_file` with the same `safe_filename`
  title logic, attachment disposition, and the temp dir deleted via
  `call_on_close` when the response closes — the merged path's exact
  pattern. The MIME type is guessed from the actual file extension
  (video/mp4 for mp4, etc.).
- **Failure contract:** if every cascade attempt fails, the helper
  returns `None` and the route answers precisely what it answered
  before — 502 "Upstream returned {code}" / "Could not reach the
  media server.", or 404 "That format is no longer available.".
  Every fallback invocation and its outcome is logged server-side;
  nothing about the visitor-facing errors changed.
- **Cost note:** unlike the streaming proxy, the fallback downloads
  the whole file to the temp dir before the first byte reaches the
  visitor — slower first byte and temp-disk usage, in exchange for
  downloads that actually complete. It only runs when the proxy has
  already failed, so fast paths are unaffected.

## YouTube session cookies (optional, env var)

Added 2026-11-03. YouTube's bot wall blocks some cloud IPs outright,
where no player-client trick helps; this mechanism lets the operator
supply a signed-in YouTube session so yt-dlp can pass as that session
instead of as an anonymous cloud visitor.

- **What it is:** the environment variable `QGRAB_YT_COOKIES_B64`
  holds the base64 encoding of a Netscape-format `cookies.txt`
  exported from a browser signed in to YouTube. At startup `app.py`
  decodes it once into a private temp file (mode 0600) and passes it
  to yt-dlp as `cookiefile` — for YouTube URLs (youtube.com / youtu.be
  and subdomains) only, in all three yt-dlp paths (`extract_info`,
  `download_merged`, `_download_via_ytdlp`, all via `_build_opts`).
  No other platform's requests ever carry the session. Env vars for
  this service are managed in the Render dashboard, so the variable
  is deliberately NOT listed in `render.yaml`.
- **Security — read before ever setting it:** the value is a LIVE
  SESSION credential, equivalent to being signed in as that account.
  It must NEVER be committed to git, pasted into any file in this
  repo, or logged — the app logs only "YouTube session cookies
  configured: yes (N cookies)" / "no", never the contents. Use a
  SPARE account for the export, never the master account that owns
  the channels: if the session is abused or flagged, only the spare
  account is at risk. Anyone holding the value can act as that
  account on YouTube until the session expires or is revoked.
- **Behaviour when absent/invalid:** if the variable is unset the
  app behaves exactly as before. If it is set but not valid base64
  UTF-8, a warning is logged and the app continues without cookies.
- **Expiry and rotation:** Google session cookies expire and are
  rotated by Google (typically days to a few weeks), and the session
  can die early if the account signs in elsewhere or Google flags
  the datacenter IP anyway — cookies raise the odds, they do not
  guarantee YouTube access. When YouTube downloads start failing
  with the bot message again, export a fresh `cookies.txt` from the
  spare account's browser, replace the env var value in the Render
  dashboard, and restart/redeploy the service (the variable is read
  once, at process startup).
