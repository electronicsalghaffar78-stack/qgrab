"""SEO pass tests (2026-11-16, APP_VERSION 2026-11-16.25).

The owner's goal: when anyone searches Google for "video
download", "video downloader", "video download without
watermark", "download TikTok video without watermark" and the
per-platform variants, QGrab's pages carry the words those
searches use — in titles, descriptions, headings, FAQs and
structured data — with honest copy (QGrab never ADDS a watermark;
TikTok's clean original file means no platform watermark there
either).

Pinned here:
  * every indexable page serves 200 with a unique, non-empty
    <title> (all carrying the QGrab brand) and a unique meta
    description of sane length;
  * every page has the correct canonical URL and an og:title;
  * the sitemap lists every indexable route (including
    /telegram-proxies, added this pass) and every listed URL
    serves 200; robots.txt points at the sitemap and keeps
    crawlers out of /api/ and /download;
  * every JSON-LD block on the key pages parses as JSON, and the
    expected types are present (WebApplication + FAQPage on the
    homepage and platform pages, FAQPage on /telegram-proxies,
    WebApplication on the Script+Prompt tool page);
  * the homepage FAQ (and its FAQPage JSON-LD) answers "How do I
    download a video without a watermark?" and "Does QGrab work
    on iPhone?"; the TikTok page answers the exact "download a
    TikTok video without a watermark" question and the other
    video pages answer "Does QGrab add a watermark?";
  * internal linking: the hero platform chips are real anchors
    and the footer links to every downloader/tool page.

Run:  .venv/bin/python tests/test_seo.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QGRAB_DATA_DIR",
                      os.path.join(os.path.dirname(__file__),
                                   ".test-data"))

import app as qgrab  # noqa: E402

client = qgrab.app.test_client()
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


SITE = qgrab.SITE_URL
PAGES = ["/",
         "/youtube-video-downloader",
         "/tiktok-video-downloader",
         "/facebook-video-downloader",
         "/instagram-video-downloader",
         "/pinterest-video-downloader",
         "/twitter-video-downloader",
         "/reddit-video-downloader",
         "/vimeo-video-downloader",
         "/twitch-video-downloader",
         "/soundcloud-downloader",
         "/dailymotion-video-downloader",
         "/telegram-video-downloader",
         "/video-script-generator",
         "/ai-video-prompt-generator",
         "/video-to-script-prompt",
         "/telegram-proxies",
         "/terms", "/privacy", "/dmca"]

htmls = {}
for path in PAGES:
    r = client.get(path)
    check(f"{path} serves 200", r.status_code == 200,
          str(r.status_code))
    htmls[path] = r.get_data(as_text=True)


def title_of(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    return m.group(1).strip() if m else ""


def desc_of(html):
    m = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
    return m.group(1).strip() if m else ""


def ld_blocks(html):
    return re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html, re.S)


def ld_types(html):
    types = []
    for block in ld_blocks(html):
        try:
            data = json.loads(block)
        except ValueError:
            return None
        types.append(data.get("@type"))
    return types


def faq_names(html):
    names = []
    for block in ld_blocks(html):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if data.get("@type") == "FAQPage":
            names += [e["name"] for e in data.get("mainEntity", [])]
    return names


# ------------------------------------------------------------------
# Titles & descriptions: present, unique, branded, sane length
# ------------------------------------------------------------------
titles = {p: title_of(h) for p, h in htmls.items()}
descs = {p: desc_of(h) for p, h in htmls.items()}
for p in PAGES:
    check(f"{p} has a title", bool(titles[p]))
    check(f"{p} title carries the brand", "QGrab" in titles[p],
          titles[p])
    check(f"{p} has a description", 40 <= len(descs[p]) <= 210,
          f"len={len(descs[p])}")
check("all titles unique", len(set(titles.values())) == len(PAGES),
      str([t for t in titles.values()
           if list(titles.values()).count(t) > 1]))
check("all descriptions unique",
      len(set(descs.values())) == len(PAGES))
check("homepage title targets 'without watermark'",
      "without watermark" in titles["/"].lower(), titles["/"])
check("homepage description targets 'without watermark'",
      "without a watermark" in descs["/"].lower()
      or "without watermark" in descs["/"].lower(), descs["/"])
check("tiktok title targets 'without watermark'",
      "without watermark" in titles["/tiktok-video-downloader"].lower())

# ------------------------------------------------------------------
# Canonical + Open Graph on every page
# ------------------------------------------------------------------
for p in PAGES:
    h = htmls[p]
    check(f"{p} canonical is correct",
          f'<link rel="canonical" href="{SITE}{p}">' in h
          or (p == "/" and
              f'<link rel="canonical" href="{SITE}/">' in h))
    check(f"{p} has og:title", '<meta property="og:title"' in h)

# ------------------------------------------------------------------
# Sitemap & robots
# ------------------------------------------------------------------
sm = client.get("/sitemap.xml").get_data(as_text=True)
locs = re.findall(r"<loc>(.*?)</loc>", sm)
loc_paths = [u[len(SITE):] for u in locs]
for p in PAGES:
    check(f"sitemap lists {p}", p in loc_paths)
for p in loc_paths:
    r = client.get(p)
    check(f"sitemap URL {p} serves 200", r.status_code == 200,
          str(r.status_code))
check("sitemap homepage priority 1.0",
      re.search(r"<loc>" + re.escape(SITE) + r"/</loc>\s*"
                r"<lastmod>.*?</lastmod>\s*<changefreq>weekly"
                r"</changefreq>\s*<priority>1\.0</priority>",
                sm, re.S) is not None)

robots = client.get("/robots.txt").get_data(as_text=True)
check("robots points at sitemap",
      f"Sitemap: {SITE}/sitemap.xml" in robots)
check("robots keeps crawlers out of /api/",
      "Disallow: /api/" in robots)
check("robots keeps crawlers out of /download",
      "Disallow: /download" in robots)

# ------------------------------------------------------------------
# Structured data: parses, right types in the right places
# ------------------------------------------------------------------
for p in PAGES:
    check(f"{p} JSON-LD all parses", ld_types(htmls[p]) is not None)
check("homepage has WebApplication + FAQPage",
      set(ld_types(htmls["/"]) or []) >= {"WebApplication", "FAQPage"},
      str(ld_types(htmls["/"])))
for p in ("/youtube-video-downloader", "/tiktok-video-downloader",
          "/instagram-video-downloader"):
    check(f"{p} has WebApplication + FAQPage",
          set(ld_types(htmls[p]) or []) >= {"WebApplication",
                                            "FAQPage"},
          str(ld_types(htmls[p])))
check("script-prompt tool has WebApplication",
      "WebApplication" in (ld_types(htmls["/video-to-script-prompt"])
                           or []))
check("proxies page has FAQPage",
      "FAQPage" in (ld_types(htmls["/telegram-proxies"]) or []))

# ------------------------------------------------------------------
# The questions people actually search
# ------------------------------------------------------------------
home_faq = faq_names(htmls["/"])
check("homepage FAQ answers the without-watermark question",
      "How do I download a video without a watermark?" in home_faq,
      str(home_faq))
check("homepage FAQ answers the iPhone question",
      "Does QGrab work on iPhone?" in home_faq)
check("homepage FAQ says QGrab is free",
      "Is QGrab free to use?" in home_faq)
check("tiktok FAQ answers the exact search question",
      "How do I download a TikTok video without a watermark?"
      in faq_names(htmls["/tiktok-video-downloader"]))
for p in ("/youtube-video-downloader", "/facebook-video-downloader",
          "/instagram-video-downloader", "/reddit-video-downloader"):
    check(f"{p} FAQ answers 'Does QGrab add a watermark?'",
          "Does QGrab add a watermark to downloads?"
          in faq_names(htmls[p]))
check("soundcloud FAQ answers the clean-audio question",
      "Does QGrab change or brand the audio?"
      in faq_names(htmls["/soundcloud-downloader"]))
proxies_faq = faq_names(htmls["/telegram-proxies"])
check("proxies FAQ covers using Telegram without a VPN",
      "Can I use Telegram without a VPN with these proxies?"
      in proxies_faq, str(proxies_faq))
check("proxies page has hreflang alternates",
      'rel="alternate" hreflang=' in htmls["/telegram-proxies"])

# ------------------------------------------------------------------
# Internal linking
# ------------------------------------------------------------------
home = htmls["/"]
# Release .24: chips carry brand icons now — anchor + icon + name.
check("hero tiktok chip is a real link",
      re.search(r'<a class="pchip" href="/tiktok-video-downloader">'
                r'<svg class="pchip-ic".*?>TikTok</a>',
                home, re.S) is not None)
check("hero soundcloud chip is a real link",
      re.search(r'<a class="pchip" href="/soundcloud-downloader">'
                r'<svg class="pchip-ic".*?>SoundCloud</a>',
                home, re.S) is not None)
for p in PAGES:
    if p in ("/", "/terms", "/privacy", "/dmca"):
        continue
    check(f"footer links to {p}", f'href="{p}"' in home)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL SEO TESTS PASS")
