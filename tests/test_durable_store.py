"""Durable visitor-data store (build 2026-11-17.30, audit A-2):

  * WITHOUT DATABASE_URL every dataset (ratings, support,
    reports, stats, subscribers) keeps the exact pre-.30 JSON-file
    behaviour -- same shapes, same filtering, same trimming;
  * WITH DATABASE_URL (Postgres) the same payloads live in the
    qgrab_datasets table, survive a simulated app restart (fresh
    store state + fresh connections), and a pre-existing JSON file
    is imported ONCE, never twice;
  * a configured-but-dead Postgres falls back to the JSON files
    instead of breaking the feature.

The Postgres half uses QGRAB_TEST_DATABASE_URL (default: the
throwaway local cluster on port 54399) and SKIPS cleanly when no
Postgres answers there -- the JSON half always runs.

Run:  .venv/bin/python tests/test_durable_store.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_TMP = tempfile.mkdtemp(prefix="qgrab-durable-")
os.environ["QGRAB_DATA_DIR"] = _TMP
os.environ.pop("DATABASE_URL", None)
os.environ.setdefault("GEMINI_API_KEY", "test-key")

import app as A  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        FAILURES.append(name)
        print("FAIL", name, detail)


def _file_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Part A -- JSON fallback (no DATABASE_URL): pre-.30 behaviour, exactly
# ---------------------------------------------------------------------------
check("no DATABASE_URL -> no pg state",
      A._database_url() == "" and not A._store_pg_state["ready"])

A._save_ratings([
    {"stars": 5, "name": "A", "text": "great", "date": "2026-11-17"},
    {"stars": "bad", "name": "X"},          # dropped: stars not int
    {"stars": 2, "name": "B", "text": "", "date": "2026-11-17"},
])
rows = A._load_ratings()
check("ratings round-trip via file",
      [r["stars"] for r in rows] == [5, 2], str(rows))
check("ratings file holds the raw payload",
      len(_file_json(A.RATINGS_FILE)) == 3)
summary = A.ratings_summary()
check("ratings summary unchanged",
      summary["count"] == 2 and summary["average"] == 3.5
      and summary["distribution"]["5"] == 1, str(summary))

A._save_support([
    {"email": "a@b.co", "message": "help me please"},
    {"email": 42, "message": "dropped"},    # dropped: email not str
])
check("support round-trip + filter",
      len(A._load_support()) == 1
      and A._load_support()[0]["email"] == "a@b.co")

A._save_reports([{"category": "bug", "message": "it broke", "ts": "t"}])
check("reports round-trip",
      len(A._load_reports()) == 1
      and A._load_reports()[0]["category"] == "bug")

today = A._stats_day()
A._save_stats({today: {"proxy_connect": 3},
               "2000-01-01": {"proxy_connect": 9}})
data = A._load_stats()
check("stats round-trip + 400-day trim",
      data.get(today, {}).get("proxy_connect") == 3
      and "2000-01-01" not in data, str(data))

A._save_subscribers([{"email": "x@y.co", "source": "footer",
                      "ts": 1, "token": "t"}])
check("subscribers round-trip",
      len(A._load_subscribers()) == 1
      and A._load_subscribers()[0]["email"] == "x@y.co")

# A dead DATABASE_URL must fall back to the files, never raise.
os.environ["DATABASE_URL"] = "postgresql://qgrab@127.0.0.1:59999/dead"
A._store_pg_state.update({"url": None, "ready": False})
check("dead pg: load falls back to file",
      [r["stars"] for r in A._load_ratings()] == [5, 2])
A._save_ratings([{"stars": 4, "name": "C"}])
check("dead pg: save falls back to file",
      [r["stars"] for r in A._load_ratings()] == [4]
      and len(_file_json(A.RATINGS_FILE)) == 1)
os.environ.pop("DATABASE_URL", None)
A._store_pg_state.update({"url": None, "ready": False})

# ---------------------------------------------------------------------------
# Part B -- Postgres: durability + one-time import (skips if unavailable)
# ---------------------------------------------------------------------------
PG_URL = os.environ.get(
    "QGRAB_TEST_DATABASE_URL",
    "postgresql://qgrab@127.0.0.1:54399/qgrabtest")
try:
    import psycopg
    with psycopg.connect(PG_URL, connect_timeout=3) as _c:
        _c.execute("DROP TABLE IF EXISTS qgrab_datasets")
        _c.commit()
    pg_available = True
except Exception as exc:  # noqa: BLE001
    pg_available = False
    print(f"SKIP postgres half (unavailable: {exc!r})")

if pg_available:
    # Seed the JSON files as a pre-.30 deploy would have left them.
    A._store_file_write(A.RATINGS_FILE,
                        [{"stars": 3, "name": "Old", "text": "from file"}])
    A._store_file_write(A.STATS_FILE, {today: {"history_view": 7}})

    os.environ["DATABASE_URL"] = PG_URL
    A._store_pg_state.update({"url": None, "ready": False})

    rows = A._load_ratings()
    check("pg: one-time import from JSON file",
          len(rows) == 1 and rows[0]["name"] == "Old", str(rows))
    check("pg: stats imported too",
          A._load_stats().get(today, {}).get("history_view") == 7)

    A._save_ratings([{"stars": 5, "name": "New", "text": "in pg"}])
    A._save_support([{"email": "p@q.co", "message": "stored in pg"}])
    check("pg: writes do NOT touch the JSON file",
          _file_json(A.RATINGS_FILE)[0]["name"] == "Old")

    # Simulated restart: forget all store state; every read opens a
    # fresh connection anyway, exactly like a new process would.
    A._store_pg_state.update({"url": None, "ready": False})
    rows = A._load_ratings()
    check("pg: data survives a restart",
          len(rows) == 1 and rows[0]["name"] == "New", str(rows))
    check("pg: support survives a restart",
          len(A._load_support()) == 1
          and A._load_support()[0]["email"] == "p@q.co")

    # Import-once: changing the file afterwards must NOT overwrite PG.
    A._store_file_write(A.RATINGS_FILE,
                        [{"stars": 1, "name": "Sneaky"}])
    A._store_pg_state.update({"url": None, "ready": False})
    rows = A._load_ratings()
    check("pg: no second import over live data",
          len(rows) == 1 and rows[0]["name"] == "New", str(rows))

    with psycopg.connect(PG_URL) as _c:
        n = _c.execute("SELECT count(*) FROM qgrab_datasets").fetchone()[0]
    check("pg: datasets stored as rows", n >= 3, f"rows={n}")

    os.environ.pop("DATABASE_URL", None)
    A._store_pg_state.update({"url": None, "ready": False})
    with psycopg.connect(PG_URL) as _c:
        _c.execute("DROP TABLE IF EXISTS qgrab_datasets")
        _c.commit()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
