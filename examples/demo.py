# examples/demo.py
# Self-contained demo: boots a real worker pool, then pushes every example
# through the Flask test client exactly as the REST API would serve it.
#
#   python examples/demo.py
#
# (Uses a throwaway DB in your temp dir; nothing persists.)

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# Put the repo root on sys.path so `api`, `worker`, `config` import cleanly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "sandbox_demo.db")


def main() -> None:
    from api.app import create_app
    from worker.pool import WorkerPool

    pool = WorkerPool(max_workers=2)
    pool.start()
    try:
        client = create_app().test_client()

        cases = [
            ("01_hello.py", "python", "", None),
            ("02_stdin_sort.py", "python", "5 3 9 1 7", None),
            ("03_hello.c", "c", "", None),
            ("04_fork_bomb.py", "python", "", None),
            ("05_steal_env.py", "python", "", None),
            ("06_mem_alloc.py", "python", "", None),
            ("07_infinite_loop.py", "python", "", None),
        ]

        print(f"{'submission':<22} {'status':<10} {'exit':<5} {'timed_out':<10} output")
        print("-" * 90)
        for fname, lang, stdin, _ in cases:
            source = (ROOT / "examples" / fname).read_text(encoding="utf-8")
            resp = client.post(
                "/submit", json={"language": lang, "source": source, "stdin": stdin}
            )
            assert resp.status_code == 201
            sub_id = resp.get_json()["id"]

            deadline = time.monotonic() + 30
            status = "queued"
            while status in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(0.2)
                status = client.get(f"/status/{sub_id}").get_json()["status"]

            result = client.get(f"/result/{sub_id}").get_json()
            out = (result.get("stdout") or "").strip().replace("\n", " | ")
            if not out:
                out = (result.get("stderr") or "").strip().splitlines()
                out = out[-1][:50] if out else "(empty)"
            print(
                f"{fname:<22} {status:<10} {result.get('exit_code', ''):<5} "
                f"{str(result.get('wall_time') or ''):<10} {out}"
            )
    finally:
        pool.stop()


if __name__ == "__main__":
    main()