# QGrab update — 2026-11-08, release .7 (header placement, search thumbnails, assistant hardening)

Version: `APP_VERSION = "2026-11-08.7"`. Driven by the
owner's SECOND phone test of the live site (screenshots
2026-11-08 ~05:55–06:03 PKT): the header already wrapped, but
(a) he asked for the exact placement below, (b) Facebook /
TikTok / Instagram search cards still showed grey placeholder
boxes instead of thumbnails, and (c) the Assistant panel
STILL showed a crushed, invisible typing input and a REVERSED
user bubble ("Hello" rendered as "llo eH") despite the .4
portrait fix. This release fixes all three. No endpoint,
cap or behaviour changed beyond what is written here; the
search response and search speed are untouched (thumbnails
load progressively after the results).

## Part A — header: brand left, Update App center, controls right

The owner's exact placement, implemented as three explicit
slots in the shared header markup of every page that carries
the full header (home, platform pages, script-prompt page):

```
[ logo "QGrab" ⭐ Plans ]   [ 🔄 Update App ]   [ 💾 Install ] [ 🌙 ⋯ ]
        brand-side               nav-center             hnav → nav-right
```

- `.brand-side` — unchanged left group (logo + brand; the
  homepage also keeps the gold ⭐ Plans pill beside the name,
  its only placement; it is not on the other pages because
  #plans exists only on the homepage).
- `.nav-center` — a NEW centered slot holding the header
  "🔄 Update App" button alone. The button still renders
  only in standalone/installed mode (same hidden-by-default
  behaviour, still driven by `_appupdatejs.html` by element
  id — position-independent, script unchanged). When hidden,
  the slot is simply empty space and the layout stays
  balanced.
- `.hnav` → `.nav-right` — the day/night (moon) toggle and
  the three-dot menu button now sit together as ONE cluster
  in the right corner (the `.nav-right` wrapper inside the
  controls group). The 💾 Install button stays just left of
  the cluster, as before — it and the Update App button swap
  visibility by mode, so they never show together.

Implementation notes: the Update App button moved out of
`_installbtn.html` into a new `templates/_updatebtn.html`
(same id/class/hidden attribute). The shared slot CSS lives
in `_extras.html`. Fix-5's gap discipline is kept (`.nav`
min-height 58px, 16px column gap, wrapping allowed). At
phone widths the center slot wraps onto its OWN full-width
row, centered (`@media (max-width:560px)`:
`.nav-center{order:3;flex-basis:100%}`) — nothing can
overlap at ~360px: row 1 is brand | controls, row 2 is the
centered Update App button (standalone mode only). The
three legal pages (DMCA / Privacy / Terms), whose minimal
headers carry only the logo and the theme toggle, got the
same `.nav-right` cluster wrap around the toggle for
consistency.

## Part B — real thumbnails for FB / TT / IG search cards

The search backend (Serper/Google results) returns no
thumbnail, author or duration for Facebook / Instagram /
TikTok, so those cards rendered grey placeholder boxes.
YouTube was unaffected (Invidious returns thumbnails) and
is untouched.

New endpoint: `GET /api/thumb?platform=<facebook|tiktok|instagram>&url=<result page URL>`
→ `{"ok":true,"thumb":"<direct image URL>"}` or
`{"ok":false}`. Every strategy has a ~4s timeout; results —
hits AND misses — are cached in memory for 24h keyed by
platform+URL, so repeat searches cost nothing. The URL is
validated first (platform known, host must belong to that
platform — lookalike hosts are rejected), and ANY failure
answers `{"ok":false}` quickly: the endpoint can never hang
or error the page.

Strategies (first hit wins):

- **TikTok:** the tikwm API — the exact resolver call the
  production downloader already uses for TikTok info —
  returning its `cover` field.
- **Facebook:** the video page's own `og:image`, extracted
  with a browser-like UA; then, only if the page gave
  nothing and the URL carries a numeric video id, the
  `graph.facebook.com/<id>/picture` URL as a last ditch.
- **Instagram:** the post's `/embed/captioned/` page —
  its `og:image`, else the `display_url` in the embed's
  JSON payload, else the embedded media `<img>` — then
  the post page's own `og:image` as a last resort.

Frontend: search cards for these platforms render the same
placeholder as before; as each card scrolls into view
(IntersectionObserver, 240px margin; immediately when the
API is unavailable) the page calls `/api/thumb` once and
swaps a real `<img>` (absolute fill, `object-fit:cover`)
into the placeholder box. An image that fails to load is
removed again, restoring the placeholder. Nothing about
`/api/search`, its speed or its payload changed.

### Verification honesty (read before promising anything)

- **Facebook og:image: VERIFIED LIVE from this sandbox**
  (2026-11-08) against a real search-result URL
  (`facebook.com/thecatbutler.co.uk/videos/<slug>/<id>/`):
  the resolver returned a real `scontent-*.fbcdn.net`
  thumbnail URL.
- **Facebook graph picture: MEASURED DEAD as a primary
  route.** Probed with four real video ids from live
  search results, `graph.facebook.com/<id>/picture`
  answered HTTP 400 for every one (Meta now wants an
  access token there). That is why og:image is the
  primary strategy and graph is only a last-ditch
  fallback for id-carrying, login-walled pages; when it
  fails, the card keeps its placeholder.
- **TikTok via tikwm:** the code path is the production
  downloader's own (it serves TikTok downloads daily),
  and the resolver is unit-tested with mocked responses;
  the live call could not be completed from THIS
  sandbox's egress (the fetch was cut at the transport
  level). It is expected to work from the server; if
  tikwm refuses there too, cards keep their placeholders.
- **Instagram:** best-effort. From this sandbox the embed
  and post pages returned no extractable image (login
  wall) — exactly the failure the layered fallbacks and
  the graceful placeholder are designed for. Some
  Instagram cards will keep placeholders; that is the
  honest limit of scraping a login-walled platform, not
  an error state.
- All resolver behaviour (per-platform hit, multi-step
  fallbacks, failure → `ok:false`, cache hit/miss avoiding
  refetch, hostile-URL validation) is covered by mocked
  unit tests: `tests/test_thumb.py` (14 tests).

## Part C — Assistant panel: root cause found, layout made structural

### Why the .4 fix did not work on the owner's phone

The .4 release "fixed" the portrait panel with stylesheet
flex rules. They never stood a chance on a phone. Every
page's main stylesheet carries a global mobile rule,
written for the hero grab buttons:

```css
@media (max-width:560px){ .grab-row{flex-direction:column} .btn{width:100%} }
```

The composer's Send button is a `.btn`. The assistant's own
rule, `.asst-form .btn{flex:none;min-height:44px}`, set
`flex` but never `width` — so at ≤560px Send took
`width:100%` as its flex base, and the `flex:1` input
(basis 0%, shrink 1, `min-width:0`) was crushed to a
padding-width sliver at the right edge: precisely the
owner's screenshot (a wide Send bar, no visible input).
Every desktop check and every JS stub test stayed green
because the media query never fires there. The .4 release
changed only flex properties, so on the phone NOTHING
changed — matching the owner's "still broken" report.

Markup-vs-CSS audit (the other suspects): every `.asst-*`
selector matches the markup in `_assistant.html` (single
definitions, no duplicates, no overrides), and no
`bidi-override` exists anywhere in the codebase. The
reversed bubble ("Hello" → "llo eH") therefore has no
stylesheet cause left in the served code — with the served
CSS/JS the bubble cannot be reversed by style alone; the
remaining path is the phone's own input/IME and RTL
context acting on a plain LTR-assumed element. This
release removes every CSS-level degree of freedom (below),
and the new in-panel version label exists so the owner's
next screenshot proves which build his phone is running.

### What changed (structural, not stylesheet-dependent)

- **Composer layout is INLINE** on the elements, where no
  stylesheet or media query can defeat it: the form carries
  `style="display:flex;gap:8px;align-items:stretch"`; the
  input carries inline `flex:1 1 auto;min-width:0;width:auto`
  plus `min-height:44px;font-size:16px` and explicit
  `color`/`background`; the messages container carries
  inline `style="direction:ltr"`. As a second layer, the
  stylesheet rule `.asst-form .btn` now also sets
  `width:auto`. The global `.btn{width:100%}` rule was
  deliberately NOT rescoped — the hero, Script+Prompt and
  AI Tools mobile layouts depend on it.
- **"Talk to Support" moved into the panel header** — a
  compact pill at the header's right, beside the
  "🤖 QGrab Assistant" title and before the ✕ close. The
  big bottom button is gone. The support FORM view is
  unchanged (its own heading, Back button and close). The
  attention pulse that fires when an answer suggests
  support now pulses the header pill.
- **Send is SMALL**: a compact pill (`flex:0 0 auto`,
  `padding:0 14px`) — the typing input now takes the rest
  of the row, as wide as the old Send button used to be.
- **Text direction, hardened:** every bubble still gets
  `dir="auto"` and now ALSO inline
  `unicode-bidi:plaintext` + `text-align:start` set from
  JS; the composer input carries `dir="auto"` in the
  markup. The mechanisms removed/overridden: (1) the
  inherited page direction context for the messages column
  (now an explicit inline `direction:ltr` island), (2) any
  stylesheet bidi handling for bubbles (now inline
  `unicode-bidi:plaintext`, which isolates each bubble's
  text in its own direction), (3) the `width:100%` flex
  crush (above).
- **Version label in the panel:** a tiny muted line under
  the composer — "QGrab Assistant · v<version>" — filled
  from `GET /api/version` when the panel opens (static
  fallback text baked into the markup), so every future
  screenshot shows exactly which build the phone runs.

All endpoints, the 30/day assistant cap, the support form
and its 24–48-hour promise are unchanged.

## Tests

- NEW `tests/test_thumb.py` — 14 mocked-network tests
  (see Part B).
- `tests/test_assistant.py` — 18 → 20: header support-pill
  placement + pin ordering; the full inline-hardening
  contract (form/input/send inline styles, msgs LTR
  island, JS inline bidi, version label + refresh wire).
- `tests/test_plans.py` — header slot structure on the
  homepage (brand < center < controls ordering, Update App
  inside the center slot, theme + menu inside `.nav-right`,
  cluster CSS, phone center-row rule) and the same
  structure on a platform page and the script-prompt page.
- `tests/test_homepage_js.js` — `/api/thumb` stub; FB and
  TikTok cards lazily swap in the stubbed thumbnails inside
  the `.sph` box; bubbles carry inline
  `unicodeBidi/textAlign`; the version label shows the
  served build after opening the panel.
- `tests/test_app_version.py` — expects `2026-11-08.7`.
- Full suites green in the master tree and the repo
  mirror (the mirror's pre-existing `test_install_button.py`
  icon failure is unrelated and unchanged).
