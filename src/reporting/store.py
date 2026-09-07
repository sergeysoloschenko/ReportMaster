"""SQLite persistence. Approved versions are immutable snapshots."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class ReportStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, period TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_period ON reports(period)
                    WHERE status IN ('queued','processing');
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL NOT NULL);
            """
            )
            rows = db.execute(
                "SELECT id,payload FROM reports WHERE status IN ('queued','processing')"
            ).fetchall()
            for row in rows:
                data = json.loads(row["payload"])
                pid = data.get("worker_pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                        continue
                    except ProcessLookupError:
                        pass
                data.update(
                    status="failed",
                    error="Обработка прервана перезапуском. Повторите генерацию: кеш сохранён.",
                )
                db.execute(
                    "UPDATE reports SET status='failed',payload=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), row["id"]),
                )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, period, **values):
        data = dict(
            id=uuid4().hex,
            period=period,
            status="queued",
            created_at=now(),
            updated_at=now(),
            revision=1,
            logs=[],
            tasks=[],
            risks=[],
            warnings=[],
            coverage={},
        )
        data.update(values)
        with self.connect() as db:
            db.execute(
                "INSERT INTO reports VALUES (?,?,?,?,?,?,?)",
                (
                    data["id"],
                    period,
                    data["status"],
                    data["created_at"],
                    data["updated_at"],
                    1,
                    json.dumps(data, ensure_ascii=False),
                ),
            )
        return data

    def get(self, report_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM reports WHERE id=?", (report_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, report_id, expected_revision=None, **values):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM reports WHERE id=?", (report_id,)
            ).fetchone()
            if not row:
                raise ValueError("Отчёт не найден")
            data = json.loads(row[0])
            if data["status"] == "approved":
                raise ValueError(
                    "Утверждённая версия неизменяема. Создайте новую редакцию."
                )
            if expected_revision is not None and data["revision"] != expected_revision:
                raise ValueError("Версия изменилась. Обновите страницу.")
            data.update(values)
            data["revision"] += 1
            data["updated_at"] = now()
            db.execute(
                "UPDATE reports SET status=?,updated_at=?,revision=?,payload=? WHERE id=?",
                (
                    data["status"],
                    data["updated_at"],
                    data["revision"],
                    json.dumps(data, ensure_ascii=False),
                    report_id,
                ),
            )
        return data

    def list(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM reports ORDER BY period DESC,created_at DESC"
                )
            ]

    def previous(self, period):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM reports WHERE period<? AND status='approved' ORDER BY period DESC,updated_at DESC LIMIT 1",
                (period,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_set(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def save_message(self, message):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO messages VALUES (?,?)",
                (message["id"], json.dumps(message, ensure_ascii=False)),
            )

    def message(self, message_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM messages WHERE id=?", (message_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None
