"""SQLite durable queue: atomic capacity/claims and expiring worker leases."""
from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import time
import uuid
from pathlib import Path

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id TEXT PRIMARY KEY, language TEXT NOT NULL, code TEXT NOT NULL,
    stdin TEXT DEFAULT '', submitted_at REAL NOT NULL, status TEXT NOT NULL,
    stdout TEXT DEFAULT '', stderr TEXT DEFAULT '', exit_code INTEGER,
    created_at REAL, executor_pid TEXT, started_at REAL, resource_usage TEXT
);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status, submitted_at);
CREATE TABLE IF NOT EXISTS workers (name TEXT PRIMARY KEY, heartbeat_at REAL NOT NULL);
"""


class QueueFull(Exception):
    """The bounded execution queue has reached capacity."""


@contextmanager
def _connect():
    path = Path(config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=config.SQLITE_TIMEOUT)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


def gen_submission_id():
    return uuid.uuid4().hex


def create_submission(language, code, stdin=""):
    sub_id, now = gen_submission_id(), time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('queued', 'running')").fetchone()[0]
        if count >= config.MAX_PENDING_JOBS:
            raise QueueFull("Execution queue is full")
        conn.execute("INSERT INTO submissions (id, language, code, stdin, submitted_at, status, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                     (sub_id, language, code, stdin, now, now))
    return sub_id


def claim_next(worker_name):
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id, language, code, stdin FROM submissions WHERE status='queued' ORDER BY submitted_at, rowid LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE submissions SET status='running', executor_pid=?, started_at=? WHERE id=?", (worker_name, time.time(), row['id']))
        return dict(row)


def fetch(id_):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id=?", (id_,)).fetchone()
        return dict(row) if row else None


def list_recent(limit=20):
    with _connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id, language, status, submitted_at FROM submissions ORDER BY submitted_at DESC, rowid DESC LIMIT ?", (limit,))]


def _trim(value, limit):
    return (value or "").encode("utf-8", errors="replace")[:limit].decode("utf-8", errors="ignore")


def mark_failed(id_, reason, worker_name=None):
    with _connect() as conn:
        conn.execute("UPDATE submissions SET status='failed', stderr=?, exit_code=-1 WHERE id=? AND (? IS NULL OR (status='running' AND executor_pid=?))", (_trim(reason, config.MAX_RESULT_BYTES), id_, worker_name, worker_name))


def store_result(id_, result, worker_name=None):
    stdout = _trim(result.get("stdout"), config.MAX_RESULT_BYTES)
    stderr = _trim(result.get("stderr"), max(0, config.MAX_RESULT_BYTES - len(stdout.encode())))
    usage = json.dumps({"wall_time": result.get("wall_time"), "timed_out": bool(result.get("timed_out")), "output_truncated": bool(result.get("output_truncated"))})
    with _connect() as conn:
        conn.execute("UPDATE submissions SET status='completed', stdout=?, stderr=?, exit_code=?, resource_usage=? WHERE id=? AND (? IS NULL OR (status='running' AND executor_pid=?))", (stdout, stderr, int(result.get("exit_code", -1)), usage, id_, worker_name, worker_name))


def heartbeat(worker_name):
    with _connect() as conn:
        conn.execute("INSERT INTO workers(name, heartbeat_at) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET heartbeat_at=excluded.heartbeat_at", (worker_name, time.time()))


def expire_worker(worker_name):
    with _connect() as conn:
        conn.execute("UPDATE workers SET heartbeat_at=0 WHERE name=?", (worker_name,))


def worker_health():
    cutoff = time.time() - config.WORKER_STALE_SECONDS
    with _connect() as conn:
        workers = conn.execute("SELECT heartbeat_at FROM workers").fetchall()
        counts = dict(conn.execute("SELECT status, COUNT(*) FROM submissions GROUP BY status").fetchall())
    active = sum(row[0] >= cutoff for row in workers)
    return {"ready": active > 0, "active_workers": active, "stale_workers": len(workers) - active,
            "last_heartbeat_at": max((row[0] for row in workers), default=None),
            "queued": counts.get("queued", 0), "running": counts.get("running", 0)}


def requeue_stuck():
    """Recover expired leases; live workers are never reset by another pool."""
    cutoff = time.time() - config.WORKER_STALE_SECONDS
    with _connect() as conn:
        cursor = conn.execute("""UPDATE submissions SET status='queued', executor_pid=NULL, started_at=NULL
            WHERE status='running' AND (
                executor_pid IN (SELECT name FROM workers WHERE heartbeat_at < ?)
                OR (started_at < ? AND NOT EXISTS (SELECT 1 FROM workers WHERE name=submissions.executor_pid))
            )""", (cutoff, cutoff))
        return cursor.rowcount


def prune_results():
    """Delete finished history older than retention; SQLite reuses freed pages."""
    with _connect() as conn:
        count = conn.execute("DELETE FROM submissions WHERE status IN ('completed','failed') AND submitted_at < ?", (time.time() - config.RESULT_RETENTION_SECONDS,)).rowcount
        conn.execute("DELETE FROM workers WHERE heartbeat_at < ? AND name NOT IN (SELECT executor_pid FROM submissions WHERE executor_pid IS NOT NULL AND status='running')", (time.time() - config.WORKER_STALE_SECONDS,))
        return count
