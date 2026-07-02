"""SQLite helpers for the expense tracker demo app."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category TEXT NOT NULL
)
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists.

    Amounts are stored as integer cents — never floats — so money math stays exact.
    check_same_thread=False because FastAPI may open, use, and close the
    per-request connection on different threadpool workers.

    The CREATE TABLE IF NOT EXISTS runs on every connect on purpose: the db file
    is disposable (delete it to reset demo state), so a memoized "already created"
    flag would leave a recreated file without its schema.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn
