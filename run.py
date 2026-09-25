# run.py
# Convenience launcher that brings up BOTH the API and the worker pool.
#
#   python run.py                # dev mode (Flask dev server + pool)
#   python run.py --workers 8    # custom concurrency
#
# For production, run separately:
#   gunicorn -w 1 "api:app" &  python -m worker.pool
#   (Flask dev server + multiprocessing quickly hits main-thread limits;
#    prefer a WSGI server with the pool in its own process.)

import argparse
import logging
import threading

from worker.pool import WorkerPool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sandboxed Code Execution Engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=4, help="concurrent executors")
    parser.add_argument("--api-only", action="store_true", help="skip the worker pool")
    args = parser.parse_args()

    import config
    import database

    database.requeue_stuck()  # rescue rows orphaned by a previous crash

    pool = None
    if not args.api_only:
        pool = WorkerPool(max_workers=args.workers)
        pool.start()
        threading.Thread(target=_supervise, args=(pool,), daemon=True).start()

    try:
        from api.app import app
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        if pool is not None:
            pool.stop()


def _supervise(pool: WorkerPool) -> None:
    """Background supervisor: respawn crashed workers every second."""
    import time

    while True:
        try:
            pool.watch()
        except Exception:
            logging.exception("supervisor error")
        time.sleep(1.0)


if __name__ == "__main__":
    main()