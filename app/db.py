"""SQLite helpers for the expense tracker demo app."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category TEXT NOT NULL,
    spent_on TEXT NOT NULL DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    month TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    UNIQUE (category, month)
);

CREATE TABLE IF NOT EXISTS recurring_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    category TEXT NOT NULL,
    day_of_month INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS recurring_runs (
    recurring_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    UNIQUE (recurring_id, month)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a pre-existing db file up to the current schema.

    The demo db is disposable, but an old file may predate the spent_on column;
    add it in place rather than forcing a delete.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(expenses)")}
    if cols and "spent_on" not in cols:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN spent_on TEXT NOT NULL DEFAULT ''"
        )
        conn.execute("UPDATE expenses SET spent_on = date('now') WHERE spent_on = ''")


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
    _migrate(conn)
    conn.executescript(SCHEMA)
    return conn
