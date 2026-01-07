from __future__ import annotations

import sqlite3

from .base import QUERIES_PATH


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript((QUERIES_PATH / "schema.sql").read_text())
