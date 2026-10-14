"""One-command local demo. Production runs API and workers separately."""
import argparse
import logging
import os
import signal
import threading

import config
from worker.pool import WorkerPool


def main():
    parser = argparse.ArgumentParser(description="CodeForge local execution studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--api-only", action="store_true")
    args = parser.parse_args()
    if args.workers is not None:
        os.environ['MAX_WORKERS'] = str(args.workers)
    config.validate()
    if config.SANDBOX_BACKEND == "process" and args.host not in ("localhost", "127.0.0.1", "::1"):
        parser.error("The trusted-development process backend must listen on loopback. Use Docker for remote access.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from api.app import app
    from waitress import create_server
    shutdown = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: shutdown.set())
    pool = None if args.api_only else WorkerPool(args.workers)
    server = create_server(app, host=args.host, port=args.port, threads=8,
                           max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
    try:
        if pool:
            pool.start()
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        print(f"\nCodeForge is ready at http://{args.host}:{args.port}", flush=True)
        print(f"Backend: {config.SANDBOX_BACKEND} | Ctrl+C to stop\n", flush=True)
        while not shutdown.wait(1):
            if not thread.is_alive():
                raise RuntimeError("HTTP server stopped unexpectedly")
            if pool:
                pool.watch()
    finally:
        server.close()
        if pool:
            pool.stop()


if __name__ == "__main__":
    main()
