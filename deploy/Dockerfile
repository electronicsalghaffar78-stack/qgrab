# QGrab — production image for the free test launch (Render, Docker runtime).
#
# Build context = the downloader-site/ folder (repo root), NOT this deploy/
# folder. On Render set:
#   Runtime:        Docker
#   Dockerfile Path: ./deploy/Dockerfile
# (the build context stays the repo root, so the COPY paths below work.)

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is a hard requirement of the app: yt-dlp calls it to merge the
# separate video+audio streams most sites now serve into one MP4 with
# sound (the "merged on download" options in the format list).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies first, so rebuilds after code changes stay fast.
# gunicorn is the production server (not in requirements.txt, which is
# kept as the app's own dependency list).
COPY requirements.txt ./
RUN pip install -r requirements.txt "gunicorn==23.0.0"

# The application itself.
COPY app.py ./
COPY i18n.py ./
COPY templates ./templates
COPY static ./static

# Run unprivileged. Merged downloads are written to the system temp dir
# (/tmp) by app.py and deleted after each response, so nothing else
# needs to be writable — except data/, which holds the ratings file
# the reviews widget writes at runtime (ephemeral on Render Free: it
# survives process restarts, not redeploys).
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

# Render (like most PaaS) injects the listen port as $PORT; gunicorn needs
# a shell to expand it, hence `sh -c`.
#   --workers 1 / gthread / 8 threads: Render Free has only 512 MB RAM —
#     one worker, threads for concurrency (a streaming download holds one
#     thread, the UI stays responsive on the others).
#   --timeout 600: a "merged" download runs yt-dlp + ffmpeg *inside* the
#     request on free-tier CPU; the default 30 s worker timeout would
#     kill it mid-merge.
#   --worker-tmp-dir /dev/shm (2026-11-08.13): gunicorn's worker
#     heartbeat files live on tmpfs, so a slow/container filesystem
#     can never make a healthy worker look dead (a classic silent
#     freeze on Docker/PaaS setups).
#   --max-requests + jitter (2026-11-08.13): the single worker is
#     gracefully recycled after ~250 requests, so any slow build-up
#     of stuck state is cleared regularly instead of accumulating
#     until the process jams — the pattern behind the three silent
#     freezes of 2026-11-08 (the app-level half of that fix, the
#     download-slot gate, lives in app.py).
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --worker-class gthread --threads 8 --timeout 600 --graceful-timeout 30 --worker-tmp-dir /dev/shm --max-requests 250 --max-requests-jitter 50 --access-logfile - app:app"]
