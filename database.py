"""Thin SQLite connection helper. No ORM — the schema is small enough that
plain SQL keeps the business logic in rental_logic.py easy to read and test."""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "rental.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None, force=False):
    """Create tables if they don't exist. force=True wipes the DB file first
    (handy for tests / a clean demo), otherwise existing data is preserved."""
    path = db_path or DB_PATH
    if force and Path(path).exists():
        Path(path).unlink()
    conn = get_connection(path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
