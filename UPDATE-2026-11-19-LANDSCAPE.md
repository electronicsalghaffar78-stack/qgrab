# QGrab 2026-11-19.40 — Showcase Stage Goes Landscape (owner's correction)

**Owner's report (2026-11-19 ~14:53 PKT, with a photo of his PC
screen):** the homepage animated showcase looked VERTICAL — on
PC the tall stage left big empty bands around the scene, and on
phone it needed scrolling up/down to see the whole animation.
His order: make it LANDSCAPE so it shows fully and easily on PC
and on phone.

**Root cause:** the stage used fixed tall heights
(`min-height:540px` desktop, `500px` on phone) inside an 860px
content column — on phone that is literally a portrait box.

**Fix (templates/_showcase.html only):**
- Desktop stage: `aspect-ratio: 2.05/1` with min-height 360px /
  max-height 440px — a wide, short landscape stage.
- Phone (≤560px): fixed height dropped 500px → 302px; scene
  padding, feature-card padding/type and headline sizes compacted
  so every scene fits inside the shorter stage.
- Static fallback on phone: cards now sit 2 per row instead of
  one full-width card per row (the other long vertical scroll).
- Reduced-motion rule updated for the new aspect-ratio sizing.
- A regression check keeps the tall heights from returning.

**Also in .40:** app version bump, service-worker cache
qgrab-shell-v15, assistant label, update-gate marker
qgrab-migration-40 (so the keep-warm step redeploys the old
address once more with this build).
