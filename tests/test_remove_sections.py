"""Tests for the 2026-11-08 removal release (APP_VERSION 2026-11-08.5).

The owner found the homepage too long and ordered two sections
removed:
  1. "Popular Downloaders" — the platform cards (YouTube / TikTok /
     Instagram / Facebook Video Downloader with "Open the ...
     Downloader ->" links);
  2. "Download Videos From Every Platform" — the platform guide
     cards ("Use the ... video downloader ->" links).

Same release, in the specs ("QGrab at a Glance") section that
moved up under Script+Prompt: the pricing row no longer says
"$0 — Free" — it is the premium line, "Premium subscription" /
"$20/month", in every language (asserted below).

Deliberately KEPT (asserted here so a future edit cannot quietly
undo the owner's decision):
  * the "All Tools" section (id="tools");
  * the platform landing PAGES themselves (/youtube-video-
    downloader etc. must still serve 200);
  * the hero H1 "Download Videos From Every Platform Easy & Fast"
    — note it CONTAINS the removed guide heading as a substring,
    so the guide section's absence is asserted via its exact
    <h2> markup and its unique sub/card texts, never via the
    bare heading string.

Run:  .venv/bin/python tests/test_remove_sections.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as A  # noqa: E402
import i18n  # noqa: E402

client = A.app.test_client()
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


EN = i18n.EN
html = client.get("/").get_data(as_text=True)

# ------------------------------------------------------------------
# 1. Popular Downloaders section is GONE
# ------------------------------------------------------------------
check("popular heading absent", EN["popular_h2"] not in html)
check("popular sub absent", EN["popular_sub"] not in html)
for cid in ("youtube-downloader", "tiktok-downloader",
            "instagram-downloader", "facebook-downloader"):
    check(f"popular card id #{cid} absent", f'id="{cid}"' not in html)
check("popular card link text absent",
      EN["card_link"].format(name="YouTube") not in html)

# ------------------------------------------------------------------
# 2. Platform guide section is GONE
# ------------------------------------------------------------------
check("guide heading <h2> absent",
      f"<h2>{EN['guide_h2']}</h2>" not in html)
check("guide sub absent", EN["guide_sub"] not in html)
check("guide YouTube card absent", EN["guide_yt_t"] not in html)
# guide_tt_t ("TikTok Video Downloader — No Watermark") is ALSO the
# footer's link text for the TikTok platform page (foot_dl_tt),
# which stays — so the TikTok guide card is asserted via its
# unique paragraph text instead of its title.
check("guide TikTok card absent", EN["guide_tt_p"] not in html)
check("guide Facebook card absent", EN["guide_fb_p"] not in html)
check("guide card link text absent",
      EN["guide_link"].format(name="YouTube") not in html)

# ------------------------------------------------------------------
# Kept on purpose
# ------------------------------------------------------------------
check("hero H1 intact (contains the guide heading as substring)",
      "Download Videos From Every Platform Easy" in html)
check("All Tools section still present",
      'id="tools"' in html and EN["tools_h2"] in html)
check("Plans section still present", 'id="plans"' in html)
check("specs section still present", 'class="specs"' in html)
for path in ("/youtube-video-downloader", "/tiktok-video-downloader",
             "/instagram-video-downloader",
             "/facebook-video-downloader"):
    r = client.get(path)
    check(f"platform page {path} still serves", r.status_code == 200,
          f"got {r.status_code}")

# ------------------------------------------------------------------
# Specs pricing row: premium line instead of "$0 — Free"
# ------------------------------------------------------------------
check("specs pricing label renders (EN)",
      EN["spec_pricing"] in html)
check("specs pricing value renders as $20/month (EN)",
      "$20/month" in html)
check("no $0 price anywhere on the homepage", "$0" not in html)
bad_val = [c for c in i18n.LANG_CODES
           if i18n.get_strings(c)["spec_pricing_val"] != "$20/month"]
check("spec_pricing_val is $20/month in all 30 languages",
      not bad_val, f"bad: {bad_val}")
bad_lbl = [c for c in i18n.LANG_CODES if c != "en"
           and (not i18n.get_strings(c)["spec_pricing"]
                or i18n.get_strings(c)["spec_pricing"]
                == EN["spec_pricing"])]
check("every language carries its own premium label",
      not bad_lbl, f"bad: {bad_lbl}")

# ------------------------------------------------------------------
# Search Videos heading: now self-explanatory (owner, same
# release). NOTE: this section's heading/sub were never i18n
# keys — they are hardcoded English in index.html, so every
# language already showed "Search Videos" in English; the new
# heading is therefore the same in all languages, with the
# action phrase in English as ordered. Sub-line unchanged.
# ------------------------------------------------------------------
check("search heading is the new self-explanatory text",
      "<h2>Search Videos — Watch & Download</h2>" in html)
check("old bare search heading gone",
      "<h2>Search Videos</h2>" not in html)
check("search sub-line unchanged",
      "Pick a platform, type a video, movie or reel name, "
      "then watch it here or download it." in html)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL REMOVE-SECTIONS TESTS PASS")
