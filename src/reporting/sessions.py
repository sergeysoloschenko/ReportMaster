"""Persist login sessions across backend restarts; store only token digests."""
import hashlib
import os
import sqlite3
import time
from pathlib import Path


class Sessions:
    def __init__(self):
        self.path = (
            Path(os.getenv("REPORTMASTER_DATA", "data"))
            / "history"
            / "sessions.sqlite3"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL)"
            )

    def add(self, token):
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), time.time() + 14 * 86400),
            )

    def __contains__(self, token):
        with sqlite3.connect(self.path) as db:
            return (
                db.execute(
                    "SELECT 1 FROM sessions WHERE digest=? AND expires>?",
                    (hashlib.sha256(token.encode()).hexdigest(), time.time()),
                ).fetchone()
                is not None
            )

    def discard(self, token):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "DELETE FROM sessions WHERE digest=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
