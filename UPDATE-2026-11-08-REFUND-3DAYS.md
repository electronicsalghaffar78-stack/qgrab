# Release 2026-11-08.10 — Refund timing in the Premium billing note

**Owner's order (2026-11-08):** in the Plans section's billing-clarity
note, at the exact spot he marked with a red tick in a phone
screenshot, add that a refund will reach the visitor within 3 days.

## Change — billing-clarity note, last bullet (`templates/_plans.html`)

Before:

> Cancel anytime. Cancel before the trial ends and you pay nothing. Cancel after paying and you get a full refund.

After:

> Cancel anytime. Cancel before the trial ends and you pay nothing. Cancel after paying and you get a full refund — the refund will reach you within 3 days.

The note lives only in `templates/_plans.html`, included once on the
homepage (`templates/index.html`, `#plans` section). No other
template carries it. The Premium card's checkbox bullets
("Everything unlimited", "3-day free trial included",
"Cancel anytime", "Full refund if you cancel") and every
price/trial fact are unchanged.

## Assistant knowledge consistency (`app.py`)

The Support Assistant's built-in knowledge already stated the
refund promise ("a full refund if you cancel"), so the same timing
was added there to keep the Assistant from contradicting the site.
The KB's Premium billing sentence now ends:

> …cancel before the trial ends and you pay nothing; cancel after paying and you get a full refund — the refund will reach you within 3 days.

## Release discipline

- `APP_VERSION` → `2026-11-08.10` (`app.py`), expected value in
  `tests/test_app_version.py` updated, and the Assistant panel's
  static stamp in `templates/_assistant.html` bumped to
  `v2026-11-08.10` (a test pins stamp == APP_VERSION).

## Tests

- `tests/test_plans.py`: new checks pin the billing note's heading,
  the unchanged cancel-before-trial line, the new last bullet
  verbatim (including "within 3 days"), and that the old bullet
  ending ("…full refund.</li>") is gone.
- `tests/test_assistant.py`: the knowledge-base fact list now also
  pins "refund will reach you within 3 days".
- Full Python + Node suites run in both the master tree and the
  mirror (see the release report for tallies).
