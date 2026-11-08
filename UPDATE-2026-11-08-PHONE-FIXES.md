# QGrab — 2026-11-08 Phone-Test Fixes (APP_VERSION 2026-11-08.4)

Five defects the owner found testing the live site on his own
phone, fixed in one release. No endpoints, caps, prices/facts or
sw.js changed; `APP_VERSION` bumped to `2026-11-08.4`.

## Fix 1 — Search "Watch" plays INSIDE the on-site modal

**Before:** a YouTube search result loaded the server-provided
embed URL — `https://www.youtube-nocookie.com/embed/{id}`, no
query parameters — into the modal's iframe, and the iframe
markup itself carried `referrerpolicy="no-referrer"` with
`allow="autoplay; encrypted-media; picture-in-picture;
fullscreen"`. YouTube refuses that combination with "Video
player configuration error" (**Error 153**) and offers a
"Watch video on YouTube" escape — the visitor was pushed off
the site instead of watching in the modal.

**After:**
- The iframe markup (templates/index.html, still the single
  shared modal) now sends the standard referrer:
  `referrerpolicy="strict-origin-when-cross-origin"`, with the
  full allow list `accelerometer; autoplay; encrypted-media;
  gyroscope; picture-in-picture; web-share`.
- `openPlayer()` in the Search Videos script rebuilds a YouTube
  result's src into the canonical pattern
  `https://www.youtube.com/embed/{id}?autoplay=1&rel=0&playsinline=1&origin={window.location.origin}`
  (www.youtube.com, never youtube-nocookie). The video id is
  recovered from the server's embed URL, falling back to the
  `v=` parameter of the watch URL.
- TikTok (`embed/v2`), Facebook (`plugins/video.php`) and
  Instagram (`/embed`) results keep their server-shaped embed
  URLs untouched; the shared iframe now gives them the same
  referrer policy.
- The server-side `/api/search` response is unchanged (the
  shapers' `embed_url` values are pinned by test_search.py and
  remain the raw material the player rebuilds from).

**Verified in code/tests:** runtime DOM-stub scenario clicks
Watch on a YouTube card and asserts the exact canonical src;
a Facebook card asserts its plugin URL passes through
unchanged; static checks pin the iframe attributes. Final
proof is on a real phone — YouTube's Error 153 behaviour
depends on the client actually sending the referrer, which a
stub cannot demonstrate.

## Fix 2 — Each search tab keeps its OWN search

**Before:** one shared query + results area: search on YouTube,
tap the Facebook tab, and the YouTube query and results were
still on screen under Facebook.

**After:** the Search Videos script keeps a per-platform state
(`{query, results, note}` for youtube / facebook / tiktok /
instagram). Leaving a tab saves its state (including text typed
but not yet submitted); entering a tab restores it — a
never-searched platform shows the clean prompt state. Results
are re-rendered from the stored result data on restore, so
Watch/Download buttons work exactly as when first rendered. A
search submitted on one platform lands in that platform's
state even if the visitor switches tabs while it runs, and
only renders immediately when its tab is still active.

**Verified:** DOM-stub scenario — YouTube "cats" (2 results) →
Facebook (clean) → Facebook "dogs" (1 result) → back to
YouTube (query + 2 results restored, Watch works) → TikTok
(clean) → Facebook again ("dogs" + 1 result kept).

## Fix 3 — Assistant panel: proper portrait chat, visible typing

**Before:** the panel sized itself to its content
(`width:min(92vw,360px); max-height:min(72vh,580px)`) with no
flexing scroll area; on the owner's phone the composer input
collapsed into a tiny blank box and typed text was invisible.
Message bubbles inherited the page direction, so on an
RTL-language page an English message rendered reversed
("i olleH" for "Hello i").

**After:**
- Panel is a fixed portrait sheet:
  `width:min(430px, calc(100vw - 24px))`,
  `height:min(80vh, 660px)`, flex column — header on top,
  `.asst-msgs` as the `flex:1` scrolling area, composer bar
  pinned at the panel bottom (top border, Send beside input).
- Composer input: `flex:1`, `min-height:44px`, `font-size:16px`
  (also stops iOS focus zoom), `--text` on `--bg2` with a 1.5px
  border — clearly visible in both themes.
- Every message bubble is created with `dir="auto"` and the
  `.asst-msg` CSS carries `unicode-bidi:plaintext;
  text-align:start`, so English / Urdu / mixed text always
  renders in its own direction, never reversed.
- Endpoints, goto behaviour, Talk to Support form and caps
  are untouched.

**Verified:** static checks pin the panel dimensions, the
composer rule (44px / 16px), the flex:1 message scroller and
the bidi CSS; the JS runtime suite asserts both bubbles of a
live exchange carry `dir="auto"`.

## Fix 4 — Plans section moved to the very bottom

`{% include "_plans.html" %}` in templates/index.html moved
from mid-page (after AI Tools) to immediately before the
footer include — `#plans` is now the LAST `<section>` on the
homepage, after the install-app section. The section's facts,
ids, classes and form-free announcement-only scope are
identical, and the header's ⭐ Plans pill still anchors to
`#plans`. No existing test asserted the old position (the
"after AI Tools" check still holds trivially); new checks pin
"last section on the page" + ordering after script-prompt,
FAQ and install. (_plans.html itself is unchanged.)

## Fix 5 — Header: Plans pill vs Update App button separation

**Before:** every page's `.nav` was a fixed-height (58px),
non-wrapping flex row with no gap. In the installed app —
where the 🔄 Update App button replaces Install in the header —
the logo + ⭐ Plans pill group and the controls group overflowed
a ~360px screen and overlapped; the pill sat half-hidden
behind the button.

**After:**
- `.nav` (all pages: index, platform, script-prompt, dmca,
  privacy, terms) is `min-height:58px` with
  `column-gap:16px; row-gap:6px; flex-wrap:wrap` — the two
  groups can wrap onto a second row instead of ever touching.
- `.brand-side` and `.plans-link` are `flex:none`, so the pill
  can never be squeezed or covered.
- `.hnav` (shared _extras.html) carries its own
  `gap:10px; flex-wrap:wrap` between the Install/Update button,
  the theme toggle and the menu.
- The Update App button's standalone-mode behaviour and the
  pill's `#plans` anchor are unchanged.

**Verified:** CSS-level checks on the rendered homepage assert
the wrapping nav, a gap ≥ 8px, the `.hnav` gap and the pill's
`flex:none`.

## Tests

- test_search.py: 20 → 21 (new player markup/canonical-src
  checks).
- test_assistant.py: 17 → 18 (new portrait-layout checks).
- test_plans.py: +9 checks (last-section ordering ×5, header
  spacing ×4) — all pass, no existing check changed.
- test_homepage_js.js: +11 checks (search render, canonical
  Watch src, player close, Facebook embed passthrough, tab
  isolation and restore scenarios, restored-results Watch,
  bubble dir=auto) — all pass.
- Full suites: 17/17 Python + 4/4 Node pass in the master
  tree and in the deploy mirror.

## Limitations

- Fix 1's final proof needs a real phone: the code now follows
  YouTube's canonical embed pattern exactly (host, parameters,
  referrer policy), and the stub suite verifies the URL the
  iframe receives, but whether YouTube serves the player
  depends on the visitor's client sending the referrer.
- Per-platform search state lives in page memory only — a page
  reload starts all four tabs clean (same as before).
