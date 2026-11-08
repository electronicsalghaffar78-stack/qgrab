# UPDATE 2026-11-08 — Watch player Fullscreen (APP_VERSION 2026-11-08.6)

Owner's request, from his phone test: a visitor who searches a
video and taps Watch should be able to enjoy it properly — a
YouTube video should swing into landscape fullscreen, and a
TikTok video should offer fullscreen from a button at the
video's bottom corner. The platform embeds' own fullscreen
controls are inconsistent (and sometimes absent), so the
player now carries **our own Fullscreen button**.

## What shipped

- **Our own pill button** (templates/index.html, inside
  `#playerFrameWrap`): ⛶ icon + the word "Fullscreen", a small
  dark pill with white text pinned to the **bottom-right corner
  of the video area**, readable over any video, shown for every
  platform (YouTube, TikTok, Facebook, Instagram).
- **Native fullscreen first**: a click calls
  `requestFullscreen()` on the frame wrapper (the element that
  holds the iframe), with the `webkitRequestFullscreen`
  fallback. The iframe markup now carries `allowfullscreen`
  and `fullscreen` in its `allow` list on the shared markup, so
  all four platforms' embeds may go fullscreen.
- **YouTube landscape lock**: after fullscreen engages for a
  YouTube embed, the player tries
  `screen.orientation.lock('landscape')` inside a guarded
  try/catch. Android Chrome grants it (fullscreen + user
  gesture); everywhere else the call fails silently and the
  video simply stays fullscreen as-is.
- **Toggle + clean exit**: with native fullscreen active the
  same button exits it; closing the player also exits native
  fullscreen and clears any fallback state.

## The honest iOS limitation + fallback design

iPhones (Safari / all iOS browsers, which are WebKit) do **not**
support the Fullscreen API on arbitrary page elements — only
`<video>` elements get `webkitEnterFullscreen`, and our player
is a cross-origin iframe wrapper. So on iPhone the native
request is missing or rejects, by design of iOS, not by a bug
here.

Fallback: whenever the native request is unavailable or
rejects, the modal switches to **expanded mode** — a CSS class
(`#playerModal.expanded`) that stretches the player box over
the whole viewport (inset 0, no padding/radius) and lets the
frame flex to fill it, with the title bar and Close button
still reachable. The same Fullscreen button toggles expanded
mode back off, and Close always clears it. Net effect: on
every device the visitor ends up with the biggest viewing area
the device allows — the button is never dead. On iPhone the
YouTube/TikTok embeds' own in-player fullscreen control also
remains available inside the video.

## Scope kept

Embed URLs, the canonical YouTube src rebuild, per-platform
search state, endpoints and caps are untouched — this release
changes only the player modal's markup, styles and JS.

## Tests

- tests/test_homepage_js.js: new fullscreen block — the pill
  is wired; a YouTube Watch + click goes native and attempts
  the landscape lock; a TikTok Watch + click goes native with
  NO lock; a rejecting request falls back to expanded mode and
  the same button toggles it off; a missing API expands and
  Close clears it. (The /api/search stub gained a TikTok
  result to drive this.)
- tests/test_search.py:
  `test_player_fullscreen_button_and_fallback_markup` pins the
  rendered markup/styles/JS hooks (button + label + ⛶, iframe
  `allowfullscreen` + `fullscreen` in allow, `.player-fs`,
  `:fullscreen` and `.expanded` styles, request/webkit/orient-
  ation-lock code paths).
- tests/test_app_version.py: expectation bumped to
  2026-11-08.6 with APP_VERSION.
