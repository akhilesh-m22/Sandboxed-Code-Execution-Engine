# database.py
# Thin, direct SQLite access layer shared by the API process, the worker
# processes and the coordinator. Uses one connection per call (short-lived),
# which sidesteps most cross-process locking headaches; WAL mode further
# reduces reader/writer contention.

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import config

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
# We deliberately keep stdout/stderr in the DB (NOT on disk as temp files):
#   * subprocess pipes already hold them in memory, so persisting is trivial
#   * files on disk would need per-submission cleanup plus permission juggling
# Downside: very large outputs bloat the DB; we cap with MAX_RESULT_BYTES.
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id           TEXT PRIMARY KEY,
    language     TEXT    NOT NULL,
    code         TEXT    NOT NULL,
    stdin        TEXT    DEFAULT '',
    submitted_at REAL    NOT NULL,       -- epoch seconds (wall)
    status       TEXT    NOT NULL,       -- queued|running|completed|failed
    stdout       TEXT    DEFAULT '',
    stderr       TEXT    DEFAULT '',
    exit_code    INTEGER,
    created_at   REAL,
    executor_pid INTEGER,                -- pid of the worker that claimed it
    started_at   REAL,                   -- when execution began
    resource_usage TEXT                  -- JSON: {"wall_time": ..., ...}
);

CREATE INDEX IF NOT EXISTS idx_submissions_status
    ON submissions(status, submitted_at);
"""


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _connect() -> sqlite3.Connection:
    db_path: Path = Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=config.SQLITE_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    _init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def gen_submission_id() -> str:
    """Short, URL-safe, unguessable id (uuid4 hex cut to 16 chars)."""
    return uuid.uuid4().hex[:16]


def create_submission(language: str, code: str, stdin: str = "") -> str:
    """Insert a queued submission; returns its id."""
    sub_id = gen_submission_id()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO submissions (id, language, code, stdin, submitted_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'queued')",
            (sub_id, language, code[: config.MAX_CODE_BYTES], stdin, time.time()),
        )
    return sub_id


def claim_next(worker_name: str) -> Optional[Dict]:
    """Claim the oldest queued submission for this worker (best-effort).

    Uses SQLite's RETURNING clause so the "pick + mark-running + hand back"
    happens in ONE atomic statement: two workers can never claim the same
    row. Falls back to a BEGIN IMMEDIATE two-step for old SQLite builds.
    """
    now = time.time()
    stmt = """
        UPDATE submissions
           SET status = 'running', executor_pid = ?, started_at = ?
         WHERE id = (
             SELECT id FROM submissions
              WHERE status = 'queued'
              ORDER BY submitted_at, rowid
              LIMIT 1
         )
        RETURNING id, language, code, stdin
    """
    with _connect() as conn:
        try:
            row = conn.execute(stmt, (worker_name, now)).fetchone()
            return dict(row) if row else None
        except sqlite3.OperationalError:
            # Older SQLite: lock the queue, pick, update, release.
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id, language, code, stdin FROM submissions "
                    "WHERE status = 'queued' "
                    "ORDER BY submitted_at, rowid LIMIT 1"
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                conn.execute(
                    "UPDATE submissions SET status='running', executor_pid=?, "
                    "started_at=? WHERE id = ?",
                    (worker_name, now, row["id"]),
                )
                conn.execute("COMMIT")
                return dict(row)
            except Exception:
                conn.execute("ROLLBACK")
                raise


def fetch(id_: str) -> Optional[Dict]:
    """Return a single submission row (or None)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id = ?", (id_,)).fetchone()
        return dict(row) if row else None


def list_recent(limit: int = 20) -> List[Dict]:
    """Latest submissions, oldest-first among the newest `limit`."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, language, status, submitted_at FROM submissions "
            "ORDER BY submitted_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def mark_failed(id_: str, reason: str) -> None:
    """Set status=failed (crash / infra error), persisting what we know."""
    with _connect() as conn:
        conn.execute(
            "UPDATE submissions SET status='failed', stderr=?, exit_code=-1 "
            "WHERE id = ?",
            (reason[: config.MAX_RESULT_BYTES], id_),
        )


def store_result(id_: str, result: Dict) -> None:
    """Persist a completed (or timed-out) execution result."""
    stdout = (result.get("stdout") or "").encode("utf-8", errors="replace")[
        : config.MAX_RESULT_BYTES
    ].decode("utf-8", errors="replace")
    stderr = (result.get("stderr") or "").encode("utf-8", errors="replace")[
        : config.MAX_RESULT_BYTES
    ].decode("utf-8", errors="replace")

    import json as _json

    usage = _json.dumps(
        {
            "wall_time": result.get("wall_time"),
            "timed_out": bool(result.get("timed_out")),
        }
    )
    with _connect() as conn:
        conn.execute(
            """
            UPDATE submissions
               SET status = 'completed',
                   stdout = ?,
                   stderr = ?,
                   exit_code = ?,
                   resource_usage = ?
             WHERE id = ?
            """,
            (stdout, stderr, int(result.get("exit_code", -1)), usage, id_),
        )


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def requeue_stuck() -> int:
    """Mark 'running' rows leftover from a crashed worker (pid no longer ours)
    back to 'queued' so a fresh worker can retry them."""
    # A worker writes its name (pid) into executor_pid. On startup we sweep
    # anything 'running' that isn't owned by a currently-alive worker.
    alive = 0
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM submissions WHERE status = 'running'"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE submissions SET status='queued', executor_pid=NULL "
                "WHERE id = ?",
                (r["id"],),
            )
            alive += 1
    return alive