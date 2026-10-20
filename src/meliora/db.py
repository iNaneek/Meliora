"""SQLite storage. Lives in data/ (gitignored, outside iCloud)."""

import sqlite3
from contextlib import contextmanager

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

