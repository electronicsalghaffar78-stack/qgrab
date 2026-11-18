# QGrab Build 2026-11-17.30 — Durable Visitor-Data Store (audit item A-2)

**Status: LOCAL ONLY.** Not pushed, not deployed. Live site is still
2026-11-17.29 (.29 fixes) / .28 — nothing about this build is live
until the owner-guided provisioning step below is done and a normal
push + Manual Deploy follows.

## The problem

Visitor data — ratings, support messages, problem reports, usage
stats and subscribers — lived in JSON files under `DATA_DIR` on
Render's ephemeral filesystem. Every redeploy wiped them (the
investment-ready audit proved it: the live ratings count had reset
to 0).

## The design (3 lines)

1. All five datasets now read/write through one small storage layer
   in `app.py` (`_store_read` / `_store_write`); every existing
   `_load_*` / `_save_*` helper and call site goes through it with
   identical shapes, caps, filtering and trimming rules.
2. With `DATABASE_URL` set, each dataset's payload — the exact JSON
   the file used to hold — is stored as one row of a single Postgres
   table `qgrab_datasets` (`name TEXT PRIMARY KEY`, `payload JSONB`,
   `updated_at TIMESTAMPTZ`), created automatically if absent.
3. Without `DATABASE_URL`, behaviour is byte-for-byte the old JSON
   files (local dev + the whole test suite unchanged).

## Safety behaviour

- **One-time migration:** on first run against Postgres, any dataset
  that has no row yet is imported from its JSON file when the file
  exists and holds data. A dataset that already has a row is never
  overwritten by a file again (proven by test).
- **Failure fallback:** if Postgres is unreachable, the URL is bad,
  or the driver is missing, the layer logs a warning and falls back
  to the JSON files — a store hiccup can never break a feature.
- `psycopg` is imported lazily (only when `DATABASE_URL` is set) and
  was added to `requirements.txt` as `psycopg[binary]>=3.2,<4`.
- The "attention" digest needs no store of its own — it is computed
  from reports + ratings, which are now durable.

## Tests

- New `tests/test_durable_store.py`: **17/17 checks pass** — JSON
  fallback exactness for all five datasets (round-trips, filtering,
  the stats 400-day trim, the ratings summary), dead-Postgres
  fallback, and against a real throwaway Postgres 16.4 (zonky
  binaries, port 54399): one-time JSON import, writes that leave the
  JSON files untouched, data surviving a simulated restart (fresh
  store state + fresh connections), and no second import over live
  data. The Postgres half skips cleanly when no PG answers.
- Full suite after the change: **36/36 Python test files pass,
  6/6 JS test files pass, 0 failures** (984 lines beginning "PASS"
  and 0 beginning "FAIL" across the Python files' own check output).

## What the owner-guided provisioning step must provide (later, NOT in this build)

1. A Postgres database QGrab can reach — e.g. a free Neon database
   (owner creates the account; no database/account was created by
   this build).
2. Its connection string set in the Render `qgrab` service
   environment as **`DATABASE_URL`** (owner pastes it in the Render
   dashboard, the same way `ANT_LING_API_KEY` was added — the value
   is never sent in chat and never committed).
3. Then the normal flow: GitHub push (approval card) → Render Manual
   Deploy → live verify (`/api/version` = 2026-11-17.30, ratings
   count survives the deploy itself — that is the acceptance test).

Nothing else changes at deploy time: no schema to run by hand (the
app creates the table), no data to move by hand (first run imports
whatever JSON the live disk still holds).
