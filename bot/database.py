"""SQLite store — tracks which deals have already been posted."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from . import config


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS posted_deals (
                deal_id   TEXT PRIMARY KEY,
                site_name TEXT,
                title     TEXT,
                posted_at TEXT
            )
        """)


def already_posted(deal_id: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM posted_deals WHERE deal_id = ?", (deal_id,)
        ).fetchone()
        return row is not None


def mark_posted(deal_id: str, site_name: str, title: str):
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO posted_deals (deal_id, site_name, title, posted_at) VALUES (?,?,?,?)",
            (deal_id, site_name, title, datetime.utcnow().isoformat()),
        )


def purge_old(days: int = 30):
    """Remove records older than `days` to keep the DB lean."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as con:
        con.execute("DELETE FROM posted_deals WHERE posted_at < ?", (cutoff,))
