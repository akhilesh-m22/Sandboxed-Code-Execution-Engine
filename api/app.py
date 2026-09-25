# api/app.py
# Flask REST API for the sandboxed code execution engine.
#
# It is deliberately stateless about executions: everything flows through
# the SQLite DB via the database module. The worker pool (a separate process)
# picks up 'queued' rows, so the API never touches the sandbox directly and
# stays responsive under load.

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, jsonify, request

import config
import database
import sandbox  # only used here for describe_caps/limits info

log = logging.getLogger("sandbox.api")

# We accept a *whitelist* of languages. Anything else is rejected at the
# boundary so we never hand unknown blobs to a compiler.
SUPPORTED_LANGUAGES = ("python", "c")


def create_app() -> Flask:
    app = Flask(__name__)
    # Application-wide resource caps: users don't get to pick tighter/looser.
    app.config.update(config.public_dict())
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_CODE_BYTES + 1024

    # ------------------------------------------------------------------
    @app.get("/health")
    def health():
        """Liveness + sandbox capability report (handy for the README and CI)."""
        return jsonify(
            {
                "ok": True,
                "sandbox": sandbox.describe_caps(),
                "limits": {
                    "timeout_seconds": config.TIMEOUT_SECONDS,
                    "cpu_seconds": config.CPU_SECONDS,
                    "mem_mb": config.MEM_MB,
                    "max_workers": config.MAX_WORKERS,
                },
            }
        )

    # ------------------------------------------------------------------
    @app.post("/submit")
    def submit():
        """Accept source + language (+ optional stdin); return a submission id."""
        body = request.get_json(silent=True) or {}
        language = (body.get("language") or "").strip().lower()
        source = body.get("source") or body.get("code") or ""

        if language not in SUPPORTED_LANGUAGES:
            return jsonify(
                {
                    "error": f"unsupported language {language!r}, "
                    f"must be one of {list(SUPPORTED_LANGUAGES)}"
                }
            ), 400
        if not source.strip():
            return jsonify({"error": "source code must not be empty"}), 400
        if len(source.encode("utf-8", errors="replace")) > config.MAX_CODE_BYTES:
            return jsonify({"error": "source code exceeds size limit"}), 413

        stdin = body.get("stdin")
        if stdin is None:
            stdin = ""
        if not isinstance(stdin, str):
            return jsonify({"error": "stdin must be a string"}), 400

        sub_id = database.create_submission(language, source[: config.MAX_CODE_BYTES], stdin)
        log.info("submitted %s (%s)", sub_id, language)
        return jsonify(
            {
                "id": sub_id,
                "status": "queued",
                "_links": {
                    "status": f"/status/{sub_id}",
                    "result": f"/result/{sub_id}",
                },
            }
        ), 201

    # ------------------------------------------------------------------
    @app.get("/status/<submission_id>")
    def status(submission_id: str):
        """Return the current state machine position of a submission."""
        row = database.fetch(submission_id)
        if row is None:
            return jsonify({"error": "submission not found"}), 404
        return jsonify(
            {
                "id": row["id"],
                "language": row["language"],
                "status": row["status"],
                "submitted_at": row["submitted_at"],
            }
        )

    # ------------------------------------------------------------------
    @app.get("/result/<submission_id>")
    def result(submission_id: str):
        """Return stdout, stderr, exit code and timing for a finished run.

        409 while the job is still queued/running; 404 if unknown id.
        """
        row = database.fetch(submission_id)
        if row is None:
            return jsonify({"error": "submission not found"}), 404
        if row["status"] in ("queued", "running"):
            msg = (
                "submission still %s; retry after execution completes" % row["status"]
            )
            return jsonify({"error": msg, "id": row["id"], "status": row["status"]}), 409
        if row["status"] == "failed":
            return jsonify(
                {
                    "id": row["id"],
                    "status": "failed",
                    "stdout": row["stdout"],
                    "stderr": row["stderr"] or "execution failed",
                    "exit_code": row["exit_code"],
                    "wall_time": None,
                }
            ), 200
        return jsonify(
            {
                "id": row["id"],
                "status": row["status"],
                "language": row["language"],
                "stdout": row["stdout"],
                "stderr": row["stderr"],
                "exit_code": row["exit_code"],
                "wall_time": row.get("resource_usage"),
            }
        )

    # ------------------------------------------------------------------
    @app.get("/submissions")
    def submissions():
        """List the most recent submissions (ids + statuses), newest first."""
        rows = database.list_recent(limit=max(1, min(int(request.args.get("limit", 20)), 100)))
        return jsonify({"submissions": rows})

    # ------------------------------------------------------------------
    @app.errorhandler(404)
    def not_found(_err):
        return jsonify({"error": "not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_err):
        return jsonify({"error": "method not allowed"}), 405

    # JSON decode errors (hello, malformed clients)
    @app.errorhandler(400)
    def bad_request(_err):
        return jsonify({"error": "bad request"}), 400

    @app.errorhandler(413)
    def too_large(_err):
        return jsonify({"error": "payload too large"}), 413

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5000, threaded=True)