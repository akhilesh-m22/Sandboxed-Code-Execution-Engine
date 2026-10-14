"""Supervised workers with live leases, crash recovery and graceful shutdown."""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import signal
import threading
import time
import uuid

import config
import database
import sandbox

log = logging.getLogger("sandbox.worker")


def _worker_loop(stop_event, name):
    config.validate()
    heartbeat_stop = threading.Event()

    def keep_lease():
        while not heartbeat_stop.wait(config.WORKER_HEARTBEAT_SECONDS):
            try:
                database.heartbeat(name)
            except Exception:
                log.exception("Worker heartbeat failed")

    database.heartbeat(name)
    lease = threading.Thread(target=keep_lease, daemon=True)
    lease.start()
    try:
        while not stop_event.is_set():
            parent = mp.parent_process()
            if parent is not None and not parent.is_alive():
                break
            job = database.claim_next(name)
            if job is None:
                stop_event.wait(config.POLL_INTERVAL)
                continue
            try:
                result = sandbox.run_code(job["language"], job["code"], stdin=job.get("stdin") or "",
                                          timeout=config.TIMEOUT_SECONDS, cpu_seconds=config.CPU_SECONDS, mem_mb=config.MEM_MB)
                database.store_result(job["id"], result, worker_name=name)
            except Exception:
                log.exception("Execution failed id=%s", job["id"])
                database.mark_failed(job["id"], "Execution infrastructure failed", worker_name=name)
    finally:
        heartbeat_stop.set()
        lease.join(timeout=config.SQLITE_TIMEOUT + 1)
        database.expire_worker(name)


class WorkerPool:
    def __init__(self, max_workers=None):
        self.max_workers = config.MAX_WORKERS if max_workers is None else max_workers
        if self.max_workers < 1:
            raise ValueError("At least one worker is required")
        self._ctx = mp.get_context("spawn")
        self._stop = self._ctx.Event()
        self._procs = []
        self._names = {}
        self._last_maintenance = 0

    def _spawn(self):
        name = f"worker-{uuid.uuid4().hex}"
        process = self._ctx.Process(target=_worker_loop, args=(self._stop, name), name=name)
        process.start()
        self._procs.append(process)
        self._names[process.pid] = name

    def start(self):
        config.validate()
        if self._procs:
            return
        self._stop.clear()
        # Docker readiness is checked before advertising workers as available.
        if config.SANDBOX_BACKEND == "docker":
            from sandbox.runtime import check_backend
            check_backend()
        database.requeue_stuck()
        for _ in range(self.max_workers):
            self._spawn()

    def stop(self, timeout=None):
        self._stop.set()
        # Allow container startup/compile/execution/cleanup to finish normally.
        deadline = time.monotonic() + (config.TIMEOUT_SECONDS + 50 if timeout is None else timeout)
        for process in self._procs:
            process.join(timeout=max(0, deadline - time.monotonic()))
            if process.is_alive():
                process.terminate()
                process.join(5)
            database.expire_worker(self._names[process.pid])
        self._procs.clear()
        database.requeue_stuck()

    def watch(self):
        if self._stop.is_set():
            return
        for process in list(self._procs):
            if not process.is_alive():
                process.join()
                database.expire_worker(self._names.pop(process.pid))
                self._procs.remove(process)
        database.requeue_stuck()
        while len(self._procs) < self.max_workers:
            self._spawn()
        if time.monotonic() - self._last_maintenance > 30:
            database.prune_results()
            self._last_maintenance = time.monotonic()

    def alive_count(self):
        return sum(process.is_alive() for process in self._procs)


def run_forever(max_workers=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    shutdown = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    pool = WorkerPool(max_workers)
    pool.start()
    try:
        while not shutdown.wait(1):
            pool.watch()
    finally:
        pool.stop()


if __name__ == "__main__":
    run_forever()
