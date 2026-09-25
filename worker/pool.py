# worker/pool.py
# Coordinator + multiprocessing worker pool.

# Design decisions (good interview material):
#   * multiprocessing.Process (not threads): true parallelism for the GIL-
#     bounded interpreter, and a worker that dies (segfault, OOM) is isolated
#     -- the pool notices and respawns rather than killing the API.
#   * Each worker is a daemonless child that loops claim -> run -> store.
#     The coordinator supervises, replacing any worker that vanished.
#   * 'spawn' start method (default on Windows/macOS): each worker gets a
#     *fresh* process, so a worker that messes with its own imports cannot
#     poison the API process.
#   * Polling: claim_next() uses SQLite's atomic UPDATE, so two workers can
#     never claim the same row (see database._claim_ready).
#   * On coordinator shutdown, workers exit cleanly via an Event.

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import time
from typing import Optional

import config
import database
import sandbox

log = logging.getLogger("sandbox.worker")


# ---------------------------------------------------------------------------
# Worker main loop (runs in its own process).
# ---------------------------------------------------------------------------

def _worker_loop(
    stop_event: mp.sync.Event,
    poll_interval: float,
    timeout: float,
    cpu_seconds: float,
    mem_mb: int,
) -> None:
    """Endless claim->execute->persist loop for one child process."""
    name = f"worker-{os.getpid()}"
    log.info("%s started", name)

    while not stop_event.is_set():
        job = database.claim_next(name)
        if job is None:
            stop_event.wait(poll_interval)  # idle sleep == polite poll rate
            continue

        log.info("%s running %s (%s)", name, job["id"], job["language"])
        try:
            result = sandbox.run_code(
                job["language"],
                job["code"],
                stdin=job.get("stdin") or "",
                timeout=timeout,
                cpu_seconds=cpu_seconds,
                mem_mb=mem_mb,
            )
        except Exception as exc:  # engine failure (not user failure)
            log.exception("%s engine error for %s", name, job["id"])
            database.mark_failed(job["id"], f"engine error: {exc}")
            continue

        database.store_result(job["id"], result)
        log.info("%s finished %s in %.3fs", name, job["id"], result.get("wall_time") or 0)

    log.info("%s stopping", name)


# ---------------------------------------------------------------------------
# Coordinating pool.
# ---------------------------------------------------------------------------

class WorkerPool:
    """Supervises `max_workers` child processes executing queued submissions."""

    def __init__(self, max_workers: Optional[int] = None) -> None:
        self.max_workers = max_workers or config.MAX_WORKERS
        self._stop = mp.Event()
        self._procs: list[mp.Process] = []

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """(Re)fill the pool with as many workers as configured."""
        ctx = mp.get_context("spawn")
        for _ in range(self.max_workers):
            p = ctx.Process(
                target=_worker_loop,
                args=(
                    self._stop,
                    config.POLL_INTERVAL,
                    config.TIMEOUT_SECONDS,
                    config.CPU_SECONDS,
                    config.MEM_MB,
                ),
                daemon=False,
                name=f"worker-{len(self._procs)}",
            )
            p.start()
            self._procs.append(p)
        log.info("pool started with %d workers", self.max_workers)

    def stop(self, timeout: float = 10.0) -> None:
        """Signal workers to stop and join them (bounded wait)."""
        self._stop.set()
        for p in self._procs:
            p.join(timeout=timeout)
            if p.is_alive():
                p.terminate()
                p.join(5)
        log.info("pool stopped")

    # -- supervision --------------------------------------------------------

    def watch(self) -> None:
        """Replace any worker that died unexpectedly (crash/segfault)."""
        if all(p.is_alive() for p in self._procs):
            return
        dead = self.max_workers - sum(1 for p in self._procs if p.is_alive())
        log.warning("respawn %d crashed worker(s)", dead)
        # Drop stale references, keeping only living workers.
        self._procs = [p for p in self._procs if p.is_alive()]
        ctx = mp.get_context("spawn")
        for _ in range(dead):
            p = ctx.Process(
                target=_worker_loop,
                args=(
                    self._stop,
                    config.POLL_INTERVAL,
                    config.TIMEOUT_SECONDS,
                    config.CPU_SECONDS,
                    config.MEM_MB,
                ),
                daemon=False,
            )
            p.start()
            self._procs.append(p)

    def alive_count(self) -> int:
        return sum(1 for p in self._procs if p.is_alive())


def run_forever(max_workers: Optional[int] = None) -> None:
    """Entry point for `python -m worker.pool`."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s",
    )
    database.requeue_stuck()  # pick up rows orphaned by a previous crash
    pool = WorkerPool(max_workers)
    pool.start()
    try:
        while True:
            pool.watch()
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.info("shutting down pool")
        pool.stop()


if __name__ == "__main__":
    run_forever()