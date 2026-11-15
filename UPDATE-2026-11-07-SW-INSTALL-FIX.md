# QGrab — Service-worker install fix (2026-11-07, IN PROGRESS — push pending approval)

## Problem (live-checked 5–6 Nov)
- Homepage, manifest (`/static/manifest.webmanifest` — valid, standalone, 192/512 + maskable icons), all icons, apple-touch-icon and `/sw.js` all serve correctly.
- Header 'Install App' button opens a manual-steps dialog, NOT Chrome's native install prompt — `beforeinstallprompt` never fires. Same symptom as Qudoos's phone (no 'Install app' / 'Add to Home screen' in the ⋮ menu).
- Suspected cause: `static/sw.js` install step used atomic `cache.addAll(SHELL)` over 6 files — one fetch failure fails the whole install, the worker never activates, Chrome blocks install.

## Fix applied (local only so far)
- `static/sw.js` install handler now uses per-file tolerant caching:
  `Promise.allSettled(SHELL.map((url) => cache.add(url)))`, `self.skipWaiting()` kept.
  Fetch handler and `/api/` + `/download` exclusions NOT touched.
- Edited in master `~/workspace/downloader-site/static/sw.js`, synced to mirror `~/workspace/qgrab-repo/static/sw.js` (md5 `7d7af1373fc13fa3c386d8165c7fd656`, both copies).
- Verified against GitHub remote: head is `f37aacbe73e89592ff9fa9d4844f7941bcef40ec` ("Fix install sheet position…"), remote `static/sw.js` == pre-edit local file (no divergence).

## BLOCKED — push approval expired (2026-11-07 ~11:00 PKT)
- `github push-files` (owner electronicsalghaffar78-stack, repo qgrab, branch main, paths-file `/tmp/qgrab-sw-push.paths` = `static/sw.js`) raised `approval_expired` (approval_id `connector-attempt-f1a5eb9ed80b736e451052380f31341425a7c18dc3748f410fc8254e9b4e4d20`). The push did NOT happen. No pending approvals remain.
- The sync record `~/workspace/qgrab-repo.muse-github-snapshot-sync.json` was NOT advanced (correct — no confirmed write).

## Resume steps (one command each)
1. Re-run the push (fresh approval card appears for Qudoos to tap):
   `/opt/hatch/bin/github push-files --owner electronicsalghaffar78-stack --repo qgrab --branch main --message "SW install: tolerant per-file shell caching so one failed fetch cannot block install (Chrome install prompt fix)" --source-dir /home/hatch/workspace/qgrab-repo --paths-file /tmp/qgrab-sw-push.paths`
   Then append the confirmed commit SHA to the sync record.
2. Render dashboard → Manual Deploy → Deploy latest commit.
3. Live verify: manifest + icons + sw.js serve; service-worker registration ACTUALLY ACTIVATES (the deciding check). If the install prompt still does not fire after activation, that check is the next step.
4. Refresh backup `~/workspace/QGrab-Complete-Backup-2026-11-04.zip` (standing rule).
5. Only then tell Qudoos in this chat, briefly in Roman Urdu (fixed / still missing + next step). Phone retest is an offer of a quick check, not a task: open qgrab.onrender.com in Chrome, wait a few seconds, check the ⋮ menu; note the menu option does not appear if the app is already installed.
