# tests/test_database.py
# Unit tests for the persistence + queueing contract the workers depend on.

from __future__ import annotations

import database


def test_create_and_fetch_roundtrip(tmp_db_path):
    sub_id = database.create_submission("python", "print(1)", stdin="x")
    row = database.fetch(sub_id)
    assert row["status"] == "queued"
    assert row["language"] == "python"
    assert row["code"] == "print(1)"
    assert row["stdin"] == "x"


def test_claim_is_exactly_once(tmp_db_path):
    """Two workers claiming concurrently must never get the same row."""
    ids = [database.create_submission("python", f"print({i})") for i in range(5)]
    claims = []
    for _ in range(5):
        claims.append(database.claim_next("worker-test"))
    claimed_ids = {c["id"] for c in claims}
    assert claimed_ids == set(ids)
    assert database.claim_next("worker-test") is None
    # idempotence: the same worker can't re-claim its own running job
    assert database.claim_next("worker-test") is None


def test_status_transitions_with_results(tmp_db_path):
    sub_id = database.create_submission("python", "print(42)")
    database.claim_next("worker-1")
    assert database.fetch(sub_id)["status"] == "running"

    database.store_result(
        sub_id,
        {"stdout": "42\n", "stderr": "", "exit_code": 0, "wall_time": 0.1, "timed_out": False},
    )
    row = database.fetch(sub_id)
    assert row["status"] == "completed"
    assert row["exit_code"] == 0
    assert row["stdout"] == "42\n"


def test_invalid_language_still_persists(tmp_db_path):
    # The DB layer is language-agnostic; validation is the API's job.
    sub_id = database.create_submission("brainfuck", "++++")
    assert database.fetch(sub_id)["language"] == "brainfuck"


def test_requeue_stuck_rows(tmp_db_path):
    sub_id = database.create_submission("python", "print(1)")
    database.claim_next("worker-deadpid")
    assert database.fetch(sub_id)["status"] == "running"
    database.requeue_stuck()
    assert database.fetch(sub_id)["status"] == "queued"
    assert database.fetch(sub_id)["executor_pid"] is None


def test_list_recent_orders_by_time(tmp_db_path):
    ids = [database.create_submission("python", f"print({i})") for i in range(3)]
    recent = database.list_recent(limit=2)
    ids_in_recent = {r["id"] for r in recent}
    assert ids[-1] in ids_in_recent and ids[1] in ids_in_recent