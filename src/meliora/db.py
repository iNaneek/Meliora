"""SQLite storage. Lives in data/ (gitignored, outside iCloud)."""

import sqlite3
import zlib
from contextlib import contextmanager
from datetime import datetime

from meliora.config import DATA_DIR

DB_PATH = DATA_DIR / "meliora.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pencil_decisions (
    day        TEXT NOT NULL,              -- ISO date the block belongs to
    block_id   TEXT NOT NULL,
    decision   TEXT NOT NULL CHECK (decision IN ('confirm', 'decline')),
    decided_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (day, block_id)
);
CREATE TABLE IF NOT EXISTS places (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    kind   TEXT NOT NULL,              -- home | peak | resort
    range  TEXT,
    lat    REAL NOT NULL,
    lon    REAL NOT NULL,
    elev_m REAL NOT NULL
);
-- Latest run of each model only; a refetch replaces that model's rows.
-- Metric units, local Denver time.
CREATE TABLE IF NOT EXISTS weather_hourly (
    place_id     TEXT NOT NULL,
    model        TEXT NOT NULL,
    time         TEXT NOT NULL,
    temp_c       REAL,
    feels_c      REAL,
    precip_mm    REAL,
    snow_cm      REAL,
    snow_depth_m REAL,
    freezing_m   REAL,
    code         INTEGER,              -- WMO weather code
    cloud_pct    REAL,
    gust_kmh     REAL,
    cape         REAL,                 -- J/kg; thunderstorm fuel
    PRIMARY KEY (place_id, model, time)
);
CREATE TABLE IF NOT EXISTS nws_alerts (
    id        TEXT PRIMARY KEY,
    event     TEXT,
    severity  TEXT,
    headline  TEXT,
    area_desc TEXT,
    onset     TEXT,
    ends      TEXT
);
CREATE TABLE IF NOT EXISTS nws_forecast (
    place_id TEXT NOT NULL,
    number   INTEGER NOT NULL,
    name     TEXT,
    start    TEXT,
    end      TEXT,
    temp     INTEGER,
    temp_unit TEXT,
    wind     TEXT,
    short    TEXT,
    detailed TEXT,
    PRIMARY KEY (place_id, number)
);
-- Every personal number, one shape: weight, sleep, HRV, VO2 max... (see SYNTHESIS / metrics design).
-- One row per metric per day per source; re-pulling a day replaces it, never duplicates.
CREATE TABLE IF NOT EXISTS metrics (
    metric     TEXT NOT NULL,              -- e.g. sleep_score, hrv_night_ms, vo2max
    day        TEXT NOT NULL,              -- ISO date the value belongs to (sleep: the wake-up date)
    value      REAL NOT NULL,
    unit       TEXT,
    source     TEXT NOT NULL,              -- garmin | sample | ...
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (metric, day, source)
);
CREATE TABLE IF NOT EXISTS activities (
    id          TEXT PRIMARY KEY,          -- source:native id
    source      TEXT NOT NULL,
    start       TEXT NOT NULL,             -- local time, ISO
    type        TEXT,                      -- running, trail_running, hiking, ...
    name        TEXT,
    distance_m  REAL,
    duration_s  REAL,
    elev_gain_m REAL,
    avg_hr      REAL,
    max_hr      REAL
);
CREATE INDEX IF NOT EXISTS activities_start ON activities (start);
-- Full API responses, zlib-compressed JSON, so new fields can be extracted later
-- without asking the source again. Keyed so a re-pull replaces, never duplicates.
CREATE TABLE IF NOT EXISTS raw_responses (
    source     TEXT NOT NULL,
    endpoint   TEXT NOT NULL,
    key        TEXT NOT NULL,              -- usually the ISO date
    fetched_at TEXT NOT NULL,
    body       BLOB NOT NULL,
    PRIMARY KEY (source, endpoint, key)
);
-- Garmin auto-pull bookkeeping: at most 3 automatic pulls per calendar day.
CREATE TABLE IF NOT EXISTS garmin_pulls (
    day        TEXT PRIMARY KEY,
    auto_count INTEGER NOT NULL DEFAULT 0,
    last_try   TEXT,
    sleep_ok   INTEGER NOT NULL DEFAULT 0
);
-- Per-source "last synced" for the footer (degrade honestly).
CREATE TABLE IF NOT EXISTS source_sync (
    source   TEXT PRIMARY KEY,
    last_ok  TEXT,
    last_try TEXT,
    detail   TEXT
);
"""


_schema_ready = False


def connect() -> sqlite3.Connection:
    """Callers close it; `with conn:` only commits."""
    global _schema_ready
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    if not _schema_ready:
        conn.executescript(SCHEMA)
        _schema_ready = True
    return conn


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mark_sync(conn: sqlite3.Connection, source: str, ok: bool, detail: str = "") -> None:
    conn.execute(
        """INSERT INTO source_sync (source, last_ok, last_try, detail) VALUES (?, ?, ?, ?)
           ON CONFLICT(source) DO UPDATE SET
             last_ok = COALESCE(excluded.last_ok, last_ok), last_try = excluded.last_try, detail = excluded.detail""",
        (source, now() if ok else None, now(), detail),
    )


def put_metric(conn: sqlite3.Connection, metric: str, day: str, value, unit: str, source: str) -> None:
    if value is None:
        return
    conn.execute(
        """INSERT INTO metrics (metric, day, value, unit, source) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(metric, day, source) DO UPDATE SET
             value = excluded.value, unit = excluded.unit, updated_at = datetime('now', 'localtime')""",
        (metric, day, float(value), unit, source),
    )


def put_raw(conn: sqlite3.Connection, source: str, endpoint: str, key: str, body: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO raw_responses (source, endpoint, key, fetched_at, body) VALUES (?, ?, ?, ?, ?)",
        (source, endpoint, key, now(), zlib.compress(body.encode(), 9)),
    )


def raw_rows(conn: sqlite3.Connection, source: str):
    """(endpoint, key, json text) for every stored raw response of a source."""
    for endpoint, key, body in conn.execute(
            "SELECT endpoint, key, body FROM raw_responses WHERE source = ? ORDER BY key", (source,)):
        yield endpoint, key, zlib.decompress(body).decode()


@contextmanager
def session():
    """Connection that commits on success and always closes."""
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def decisions(day: str) -> dict[str, str]:
    with session() as conn:
        rows = conn.execute(
            "SELECT block_id, decision FROM pencil_decisions WHERE day = ?", (day,)
        ).fetchall()
    return dict(rows)


def record_decision(day: str, block_id: str, decision: str) -> None:
    with session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pencil_decisions (day, block_id, decision) VALUES (?, ?, ?)",
            (day, block_id, decision),
        )


def clear_decisions(day: str) -> None:
    with session() as conn:
        conn.execute("DELETE FROM pencil_decisions WHERE day = ?", (day,))


def clear_decision(day: str, block_id: str) -> None:
    with session() as conn:
        conn.execute("DELETE FROM pencil_decisions WHERE day = ? AND block_id = ?", (day, block_id))

