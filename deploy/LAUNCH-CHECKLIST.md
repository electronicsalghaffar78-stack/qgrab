# QGrab — FREE test-launch checklist (Render)

Target: **Render Free web service** running the Docker image from
`deploy/Dockerfile`. Cost: **Rs 0** — no card is needed for Render's free
tier, and with no payment method on file Render *suspends* (never bills)
the service if a monthly allowance runs out.

The whole launch takes ~15–25 minutes, most of it waiting for the first
build. **Qudoos must be present for Step 1** (account sign-in may send a
Google verification prompt to his phone — per his standing rule, he is
told first and taps it himself).

---

## Before launch day (Archer prep — no accounts involved)

- [ ] Put the `downloader-site/` code into a git repo Render can read:
      either a **public GitHub repository** (Render can deploy straight
      from a public repo URL) or a repo under the owner's own GitHub
      account, connected on launch day.
- [ ] In that repo: copy `deploy/render.yaml` and `.dockerignore` to the
      **repo root** (Render/Docker only read them there). The repo root
      must be the `downloader-site/` folder itself, so the repo contains
      `app.py`, `requirements.txt`, `templates/`, `static/`, `deploy/`.
- [ ] Bump the `yt-dlp` pin in that repo's `requirements.txt` to the
      latest release (platforms change weekly; a stale yt-dlp is the #1
      cause of "downloads stopped working").
- [ ] Re-run the local smoke test once against the final repo copy
      (gunicorn + `/healthz` + homepage — same commands used in prep).

## Launch day — with Qudoos present

### Step 1 — Render account (owner does this, ~3 min)

1. Qudoos opens **https://render.com** and clicks **Get Started**.
2. He signs up with **Google**, using **electronicsalghaffar78@gmail.com**
   (the "AI Control Social" account he has approved for free use).
   ⚠️ A Google "Verify it's you" prompt may appear on his phone — this
   is expected; he taps **Yes** (and the number shown, if asked).
3. If Render offers workspace/plan choices, keep everything **Free /
   Hobby $0**. **Do not add a payment method** — free is the point of
   the test launch, and without a card nothing can ever be charged.

### Step 2 — Create the web service (~2 min of clicking)

1. Dashboard → **New → Web Service**.
2. Choose the repo prepared above (public repo URL, or the connected
   GitHub account → select the QGrab repo).
3. Settings:
   - **Name:** `qgrab` → the site will live at
     **https://qgrab.onrender.com**. If the name is taken, use
     `qgrab-app` or `qgrab-video` (the URL changes accordingly).
   - **Region:** **Singapore** (closest free region to Pakistan).
   - **Branch:** `main`
   - **Runtime:** **Docker**
   - **Dockerfile Path:** `./deploy/Dockerfile`
   - **Instance Type:** **Free**
   - **Health Check Path:** `/healthz`
   - **Environment variables:** none required. (Optional:
     `PYTHONUNBUFFERED` = `1`.)
4. Click **Create Web Service**. First build takes ~3–8 minutes
   (Python + ffmpeg install). Watch the **Logs** tab; success ends with
   gunicorn "Listening at: http://0.0.0.0:10000" — Render assigns its
   own `$PORT`, the Dockerfile already handles that.

### Step 3 — Confirm the live site (~5 min)

1. Open **https://qgrab.onrender.com/healthz** → must show
   `{"ok": true}`.
2. Open **https://qgrab.onrender.com** → QGrab homepage with the Q logo.
   (First visit after idle can take ~1 minute — the free service sleeps
   after 15 quiet minutes and shows a loading page while it wakes. That
   is normal on the free tier, not an error.)
3. **Phone test (Qudoos):** open the same URL on his phone → paste a
   short YouTube link → formats appear → download the **smallest**
   format → file plays with sound. Then try one **"merged"** quality
   (e.g. 360p) — it takes longer to start (server downloads + joins
   video and audio first); the file must also play with sound.
4. Try one TikTok or Facebook link the same way.
5. ⚠️ If YouTube answers *"Sign in to confirm you're not a bot"*: this
   is YouTube blocking cloud-server IPs — a known risk on **every** free
   host, not a failed launch. Note which sites work; the site, account
   and URL are still valid. (Mitigations exist later — cookies/paid
   host — not part of the free test.)

### Step 4 — Know the free-tier fences (check together)

- Dashboard → **Billing → Monthly Included Usage**: 750 instance
  hours/month and **5 GB outbound bandwidth/month** on the free
  workspace. A handful of test downloads a day is fine; a public
  crowd would eat 5 GB quickly (roughly a few dozen typical videos).
- At 100% bandwidth with no card on file, Render **suspends** the site
  until the 1st of next month. Nothing is charged, nothing is lost —
  the service and URL stay his.
- The site carries the personal-use disclaimer ("download only videos
  you own or have permission for"). Keep it — it matters for both the
  host's and ad networks' policies.

## After a successful test (later steps, not launch day)

1. Buy the domain (owner's decision + payment, ~Rs 3,000–4,500/yr) →
   Render → service → **Settings → Custom Domains** → point the domain
   (free HTTPS is automatic).
2. Ad network signup (Adsterra/Monetag type — AdSense does not approve
   downloader sites) → paste the ad code into the two **AD placeholder
   boxes** in `templates/index.html` → push → auto-redeploy.
3. When traffic outgrows 5 GB/month, move the same Docker image to the
   paid home (~Rs 1,500–2,800/mo VPS, or Render Starter $7) or to
   **Oracle Cloud Always Free** (2 ARM cores / 12 GB RAM / 10 TB
   transfer — the strongest free option, but its signup demands a real
   credit/debit card for verification, which is why it is plan B).

## Fallbacks if Render blocks us on the day

- **Signup/build problem:** SnapDeploy (snapdeploy.dev) — free Docker
  containers, no card, accepts a repo or an uploaded image; only
  100 container-hours/month, so strictly a demo-day fallback.
- **Render suspends the app over downloader complaints:** the code and
  this bundle are host-agnostic — the same repo deploys to Oracle
  Always Free or any VPS unchanged (see README deployment notes).
