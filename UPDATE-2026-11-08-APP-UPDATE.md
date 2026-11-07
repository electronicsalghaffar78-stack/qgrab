# QGrab — "Update App" Button for the Installed PWA — 2026-11-08

An on-demand refresh for people who installed QGrab as an app,
in the owner's model: **press Update → today's version arrives
immediately; never press → nothing happens.** Built locally,
**not pushed, not deployed** — it ships in the same release as
the Video Toolkit + AI Tools.

## The contract

- `APP_VERSION = "2026-11-08.1"` in `app.py` — a free-form
  release stamp; only equality matters.
- `GET /api/version` → `{"version": APP_VERSION}` with
  `Cache-Control: no-store`, so the check can never be answered
  from a cache. Pinned by `tests/test_app_version.py` (2/2).

> **Release rule:** bump `APP_VERSION` in `app.py` on EVERY
> future release that changes anything a browser could have
> cached. If it is not bumped, the button truthfully reports
> "already latest" while the installed app may still hold the
> old shell — the check is only as honest as the stamp.

## The buttons

- **Footer (mandatory, always visible):** "🔄 Update App" in the
  footer's bottom strip (`templates/_footer.html`, styled by
  `.app-update-foot` in `_extras.html`) — present on home,
  platform and tool pages alike.
- **Header twin (standalone only):** a second button
  (`#appUpdateBtnTop`, reusing the `.install-btn` styling) sits
  in the header slot the Install button owns — hidden in a
  normal browser, unhidden by the script exactly when the app
  runs standalone, which is also exactly when the Install
  button hides itself. No crowding: the slot changes tenant.

## The flow (`templates/_appupdatejs.html`)

One IIFE, included right after `_installjs.html` on every page
that carries the footer. It lives in its **own** partial on
purpose: `_installjs.html` carries a tested no-timers invariant
(the install guide sheet must never auto-hide), while this
script's toast legitimately hides itself — the site's
established `.sp-toast` behaviour, which the flow reuses (the SP
section's `#spToast` element when the page has one; a same-class
element created on the fly on platform pages, which don't).

1. Click → both buttons show "Checking…" and disable.
2. `fetch('/api/version', {cache: 'no-store'})`.
3. Compare with `localStorage["qgrab_app_version"]`:
   - **Equal** → toast **"You already have the latest version."**,
     buttons restored, no reload.
   - **Different or unset** → the update: the service worker
     registration's `update()` is called when available; **every
     Cache Storage entry is deleted** (`caches.keys()` → delete
     each); `localStorage["qgrab_app_version"]` is set to the
     fetched version and `sessionStorage["qgrab_just_updated"]`
     to `"1"`; then `location.reload()`. On the way back in, the
     flag shows the toast **"App updated — you now have the
     latest version ✔"** and is cleared.
   - **Fetch fails** (offline etc.) → toast **"Couldn't check
     for updates — please check your connection and try again."**,
     buttons restored.
4. No countdown or timer gates anything; the toast simply hides
   itself after ~4.5 s, like the SP toast.

Every step is best-effort guarded: a failed SW poke or cache
clear never blocks the reload, and unavailable storage degrades
to "treat as unset" (the update path) instead of an error.

## Service worker — inspected, deliberately untouched

`static/sw.js` names its shell cache statically
(`"qgrab-shell-v5"`, **not** derived from `APP_VERSION`), and
page navigations are network-first with the cached shell only
as an offline fallback. So a plain reload would *usually* be
fresh — but "usually" is not the owner's model: the button's
**clear-all-caches step is what guarantees** the reload cannot
be answered by the old shell. Since the flow needs nothing from
the worker itself, `sw.js` is unchanged: its tolerant per-file
caching and `skipWaiting` behaviour are exactly as installed,
and the install suites pass untouched.

## Tests

- `tests/test_app_version.py` — **2/2**: the endpoint body is
  exactly `{"version": APP_VERSION}`, the value is
  `2026-11-08.1`, and `Cache-Control` carries `no-store`.
- `tests/test_homepage_js.js` — extended with a `/api/version`
  stub: stored version equal to the server's → the
  "already latest" toast and **no** reload; an older stored
  version → new version recorded in localStorage, the
  just-updated flag set in sessionStorage, exactly one reload.
  (The post-reload "App updated" toast itself fires on the next
  real page load, so the suite pins the flag it depends on
  rather than the toast.)
- `tests/test_install_button.py` — passes again in the master
  tree after the move to a separate partial (see above); the
  mirror tree keeps its known pre-existing failure there
  (generated PNG icons absent from the repo snapshot).
- Full suites: master **15/15 Python + 4/4 Node**; mirror
  identical except that known install-button failure.
