# tests/test_api_integration.py
# End-to-end test through the real HTTP API + real worker pool + SQLite.
# This is the closest thing to a full submission lifecycle WITHOUT spinning
# up a network server (Flask's test_client works in-process).

from __future__ import annotations

import time

import pytest

from api.app import create_app
from worker.pool import WorkerPool


@pytest.fixture(scope="module")
def client_and_pool(tmp_path_factory):
    """One worker pool + one Flask test client for the whole module.

    The pool is spawned with the real multiprocessing machinery (spawn on
    Windows), so this also exercises the child-process claim loop.
    """
    db = tmp_path_factory.mktemp("api_it") / "it.db"
    # Point config at the temp DB via env (lazy resolution makes every read
    # see it -- including in newly spawned worker processes).
    import os

    os.environ["DB_PATH"] = str(db)

    pool = WorkerPool(max_workers=2)
    pool.start()
    app = create_app()
    client = app.test_client()
    yield client, pool, db
    pool.stop()
    del os.environ["DB_PATH"]


def _wait_status(client, sub_id, timeout=20.0, target="completed"):
    """Poll GET /status until the submission leaves the queue."""
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        resp = client.get(f"/status/{sub_id}")
        assert resp.status_code == 200
        seen = resp.get_json()["status"]
        if seen == target or seen in ("completed", "failed"):
            return seen
        time.sleep(0.1)
    raise AssertionError(f"submission {sub_id} stuck in status {seen!r}")


def test_health_and_caps(client_and_pool):
    client, _pool, _db = client_and_pool
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "sandbox" in body and "platform" in body["sandbox"]


def test_submit_status_result_lifecycle(client_and_pool):
    client, _pool, _db = client_and_pool
    resp = client.post(
        "/submit",
        json={"language": "python", "source": "print(21 * 2)", "stdin": ""},
    )
    assert resp.status_code == 201
    sub_id = resp.get_json()["id"]

    assert _wait_status(client, sub_id) == "completed"

    result = client.get(f"/result/{sub_id}").get_json()
    assert result["status"] == "completed"
    assert result["stdout"].strip() == "42"
    assert result["exit_code"] == 0
    assert result["stderr"] == ""


def test_malicious_submission_completes_as_failed(client_and_pool):
    """A fork-bomb attempt must NOT wedge the worker pool."""
    client, _pool, _db = client_and_pool
    resp = client.post(
        "/submit",
        json={"language": "python", "source": "import os\nwhile True:\n    os.fork()"},
    )
    sub_id = resp.get_json()["id"]
    assert _wait_status(client, sub_id) in ("completed", "failed")

    result = client.get(f"/result/{sub_id}").get_json()
    assert result["exit_code"] != 0
    assert "forbidden" in result["stderr"].lower() or "flagged" in result["stderr"].lower()


def test_infinite_loop_submission_terminates(client_and_pool):
    client, _pool, _db = client_and_pool
    resp = client.post(
        "/submit", json={"language": "python", "source": "while True:\n    pass"}
    )
    sub_id = resp.get_json()["id"]
    assert _wait_status(client, sub_id) in ("completed", "failed")

    result = client.get(f"/result/{sub_id}").get_json()
    assert result["exit_code"] != 0
    assert "timed out" in result["stderr"].lower()


def test_unknown_language_rejected(client_and_pool):
    client, _, _ = client_and_pool
    resp = client.post("/submit", json={"language": "bash", "source": "echo hi"})
    assert resp.status_code == 400


def test_empty_source_rejected(client_and_pool):
    client, _, _ = client_and_pool
    resp = client.post("/submit", json={"language": "python", "source": "   "})
    assert resp.status_code == 400


def test_status_not_found(client_and_pool):
    client, _, _ = client_and_pool
    assert client.get("/status/nope").status_code == 404
    assert client.get("/result/nope").status_code == 404


def test_stdin_passed_to_submission(client_and_pool):
    client, _pool, _db = client_and_pool
    resp = client.post(
        "/submit",
        json={"language": "python", "source": "print(input())", "stdin": "hi from api"},
    )
    sub_id = resp.get_json()["id"]
    assert _wait_status(client, sub_id) == "completed"
    result = client.get(f"/result/{sub_id}").get_json()
    assert result["stdout"].strip() == "hi from api"


def test_concurrent_submissions_all_finish(client_and_pool):
    """Ten queued jobs against a 2-worker pool -- all must complete."""
    client, _pool, _db = client_and_pool
    ids = []
    for i in range(10):
        resp = client.post(
            "/submit", json={"language": "python", "source": f"print({i})", "stdin": ""}
        )
        ids.append(resp.get_json()["id"])

    outs = []
    for sub_id in ids:
        assert _wait_status(client, sub_id) == "completed"
        outs.append(client.get(f"/result/{sub_id}").get_json()["stdout"].strip())

    assert sorted(map(int, outs)) == list(range(10))