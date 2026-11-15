# Telegram Proxies — Sourcing Note

**Fetch date:** 2026-11-16
**Output:** `data/proxies.json` — 100 proxies kept
**Rule followed:** No server/port/secret value was invented. Every entry was fetched
verbatim from the public sources below during this build, then validated and
deduplicated programmatically.

## Method

1. Sources discovered via web search for public MTProto proxy lists
   (GitHub repos publishing raw `.txt` lists).
2. Each raw list was downloaded and parsed for `https://t.me/proxy?...` and
   `tg://proxy?...` links (tg:// links converted to the https://t.me form).
3. Validation per entry: server = non-empty hostname or IPv4; port = numeric
   1–65535; secret = non-empty hex-format MTProto secret (plain hex, or
   dd/ee-prefixed FakeTLS-style hex), length ≥ 16.
4. Deduplication by (server, port, secret). Kept the first 100 unique valid
   entries (target range 50–100).

Note: 458 further links across the sources carried base64-format secrets
(a format some lists publish). They were excluded by the hex-format validation
rule above, not because the sources were unreachable.

## Sources and counts

| # | Source | Found | Valid (hex-format) | New unique |
|---|--------|------:|------:|------:|
| 1 | https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt | 174 | 71 | 71 |
| 2 | https://raw.githubusercontent.com/ALIILAPRO/MTProtoProxy/main/mtproto.txt | 174 | 71 | 0 (identical mirror of source 1) |
| 3 | https://raw.githubusercontent.com/aviamastersgh/mtproto-free-russia/main/verified_proxies.txt | 284 | 109 | 60 |
| 4 | https://raw.githubusercontent.com/aviamastersgh/mtproto-free-russia/main/all_proxies.txt | 301 | 119 | 3 |

**Totals:** 933 found → 370 valid → 134 unique after dedupe → **100 kept**.

## Caveats

- These are public, third-party proxies aggregated by the source projects;
  QGrab does not operate them. Public proxies can go offline at any time —
  the source lists refresh every 2–12 hours, so this snapshot will age.
- Source 3 is the "verified" list from its project (connection-checked at
  their publish time, 2026-11-15 21:00 UTC per its file header).
