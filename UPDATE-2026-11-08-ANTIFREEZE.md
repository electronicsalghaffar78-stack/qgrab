# QGrab — Release 2026-11-08.13 "Anti-Freeze" (2026-11-08, ~22:05 PKT)

APP_VERSION: 2026-11-08.12 → **2026-11-08.13**

## Why

The site froze THREE times on 2026-11-08 (~08:00, ~10:53, ~21:40 PKT):
dashboard still "Live", no crash, no error in the logs, limits
untouched — the instance simply stopped answering everything,
including Render's own /healthz checks. Each time only a manual
redeploy brought it back.

## Root cause (code level)

One gunicorn worker, 8 threads — and /download holds its thread
for the whole job:

- a streaming proxy download lasts as long as the visitor's
  connection takes to receive the file;
- a merged / MP3 download runs yt-dlp **and** ffmpeg *inside* the
  request — minutes on free-tier CPU.

Eight concurrent downloads therefore occupy all 8 threads.
After that there is no thread left to serve pages, search or
even /healthz, and with `--timeout 600` gunicorn does not recycle
a busy worker for 10 minutes. The process is alive but fully
saturated: to every visitor (and to Render's checks) the site is
dead. Downloads arriving steadily can keep it saturated
indefinitely — which is why the freezes "never recovered" on
their own and the logs showed nothing: nothing had crashed.

## The fix (this release)

1. **Download-slot gate (app.py).** At most 3 downloads run at
   once (`threading.BoundedSemaphore(3)` around /download). A
   download holds its slot until its response is fully sent
   (released from the response's on-close hook — the pattern the
   merged download already used for temp-dir cleanup). A download
   that finds all slots taken waits up to 20 s for one, then
   answers an honest **503 + Retry-After: 60** ("QGrab is busy
   with other downloads right now. Please try again in a
   minute.") instead of queueing silently. The other 5 threads
   always stay free for pages, search and /healthz.
2. **Gunicorn hardening (deploy/Dockerfile).**
   `--worker-tmp-dir /dev/shm` (worker heartbeats on tmpfs — a
   slow container filesystem can never make a healthy worker
   look dead) and `--max-requests 250 --max-requests-jitter 50`
   (the single worker gracefully recycles itself regularly, so
   any slow build-up of stuck state is cleared instead of
   accumulating until the process jams).
3. **Auto-healing (GitHub Actions, keep-warm workflow).** The
   10-minute keep-warm ping became a health guard: three failed
   /healthz checks spread over ~3 minutes are treated as a
   freeze and the workflow calls the Render **deploy hook**
   (stored as the `RENDER_DEPLOY_HOOK_URL` Actions secret — the
   URL itself is recorded NOWHERE else), which redeploys and
   restarts the service with no human involved. A single failed
   ping never triggers a redeploy. Expected worst case: a freeze
   heals itself within ~15 minutes (≤10 min until the next run,
   ~3 min of confirmation checks, ~1 min deploy).

## Tests

- New `tests/test_antifreeze.py`: slot limits pinned; with all
  slots held, /download answers 503 + Retry-After AND /healthz
  still answers 200 `{"ok": true}` (the exact property missing
  on freeze day); Dockerfile carries the hardening flags.
- `tests/test_app_version.py` expectation bumped to .13;
  assistant version stamp bumped in templates/_assistant.html.
- Full suites after the change: **21/21 Python + 3/3 Node PASS.**

## Honest limits

- The free Render tier can still freeze for platform reasons
  outside the app's control; that is exactly what the
  auto-healing now covers. Paid hosting remains the structural
  fix and remains the owner's decision.
- During a heavy-download burst some visitors will see the 503
  busy message and need to retry — deliberately traded against
  the whole site going down for everyone.
