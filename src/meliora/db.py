"""SQLite storage. Lives in data/ (gitignored, outside iCloud)."""

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "meliora.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pencil_decisions (
    day        TEXT NOT NULL,              -- ISO date the block belongs to
    block_id   TEXT NOT NULL,
    decision   TEXT NOT NULL CHECK (decision IN ('confirm', 'decline')),
    decided_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (day, block_id)
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def decisions(day: str) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT block_id, decision FROM pencil_decisions WHERE day = ?", (day,)
        ).fetchall()
    return dict(rows)


def record_decision(day: str, block_id: str, decision: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pencil_decisions (day, block_id, decision) VALUES (?, ?, ?)",
            (day, block_id, decision),
        )


def clear_decisions(day: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM pencil_decisions WHERE day = ?", (day,))


def clear_decision(day: str, block_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM pencil_decisions WHERE day = ? AND block_id = ?", (day, block_id))
