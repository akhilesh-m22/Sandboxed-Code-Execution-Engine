"""HTTP boundary for CodeForge; execution belongs to separate workers."""
from __future__ import annotations

import hmac
import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import config
import database
import sandbox

log = logging.getLogger("sandbox.api")
ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_LANGUAGES = ("python", "c")


def create_app() -> Flask:
    config.validate()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 6 * (config.MAX_CODE_BYTES + config.MAX_STDIN_BYTES) + 4096

    @app.before_request
    def prepare_request():
        g.request_id = uuid.uuid4().hex
        g.started_at = time.monotonic()
        protected = request.path in ("/submit", "/submissions") or request.path.startswith(("/status/", "/result/"))
        if protected and config.API_TOKEN:
            expected = ("Bearer " + config.API_TOKEN).encode()
            supplied = request.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(supplied, expected):
                response = jsonify(error="A valid API token is required")
                response.headers["WWW-Authenticate"] = "Bearer"
                return response, 401

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-eval' blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "connect-src 'self' https://cdn.jsdelivr.net; worker-src 'self' blob:; "
            "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if response.is_json:
            response.headers["Cache-Control"] = "no-store"
        log.info("request id=%s method=%s status=%s duration_ms=%.1f", g.get("request_id"), request.method, response.status_code, (time.monotonic() - g.get("started_at", time.monotonic())) * 1000)
        return response

    @app.get("/")
    def serve_index():
        return send_from_directory(ROOT / "frontend", "index.html")

    @app.get("/css/<path:filename>")
    def serve_css(filename):
        return send_from_directory(ROOT / "frontend" / "css", filename)

    @app.get("/js/<path:filename>")
    def serve_js(filename):
        return send_from_directory(ROOT / "frontend" / "js", filename)

    @app.get("/health")
    def health():
        return jsonify(ok=True, sandbox=sandbox.describe_caps(), limits=config.public_dict())

    @app.get("/ready")
    def ready():
        workers = database.worker_health()
        return jsonify(ok=workers["ready"], workers=workers), 200 if workers["ready"] else 503

    @app.get("/api/config")
    def public_config():
        limits = config.public_dict()
        limits["memory_mb"] = config.MEM_MB
        return jsonify(languages=list(SUPPORTED_LANGUAGES), limits=limits,
                       sandbox={"backend": config.SANDBOX_BACKEND, "isolated": config.SANDBOX_BACKEND == "docker"},
                       authentication_required=bool(config.API_TOKEN))

    @app.get("/openapi.json")
    def openapi():
        return send_from_directory(ROOT / "docs", "openapi.json")

    @app.post("/submit")
    def submit():
        if not request.is_json:
            return jsonify(error="Content-Type must be application/json"), 415
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(error="Request body must be a JSON object"), 400
        language = body.get("language", "")
        source = body.get("source", body.get("code", ""))
        stdin = body.get("stdin", "")
        if stdin is None:
            stdin = ""
        for name, value in (("language", language), ("source", source), ("stdin", stdin)):
            if not isinstance(value, str):
                return jsonify(error=f"{name} must be a string"), 400
        language = language.strip().lower()
        if language not in SUPPORTED_LANGUAGES:
            return jsonify(error="Unsupported language; use python or c"), 400
        if not source.strip():
            return jsonify(error="Source code must not be empty"), 400
        for name, value, limit in (("source", source, config.MAX_CODE_BYTES), ("stdin", stdin, config.MAX_STDIN_BYTES)):
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError:
                return jsonify(error=f"{name} contains invalid Unicode"), 400
            if size > limit:
                return jsonify(error=f"{name} exceeds size limit ({limit} bytes)"), 413
        if config.APP_ENV == "production" and not database.worker_health()["ready"]:
            return jsonify(error="No execution workers are ready"), 503
        try:
            sub_id = database.create_submission(language, source, stdin)
        except database.QueueFull:
            response = jsonify(error="Execution queue is full; retry shortly")
            response.headers["Retry-After"] = "5"
            return response, 429
        response = jsonify(id=sub_id, status="queued", _links={"status": f"/status/{sub_id}", "result": f"/result/{sub_id}"})
        response.headers["Location"] = f"/status/{sub_id}"
        return response, 201

    @app.get("/status/<submission_id>")
    def status(submission_id):
        row = database.fetch(submission_id)
        if row is None:
            return jsonify(error="Submission not found"), 404
        return jsonify({key: row[key] for key in ("id", "language", "status", "submitted_at")})

    @app.get("/result/<submission_id>")
    def result(submission_id):
        row = database.fetch(submission_id)
        if row is None:
            return jsonify(error="Submission not found"), 404
        if row["status"] in ("queued", "running"):
            response = jsonify(error="Execution has not finished", id=row["id"], status=row["status"])
            response.headers["Retry-After"] = "1"
            return response, 409
        try:
            usage = json.loads(row.get("resource_usage") or "{}")
        except (ValueError, TypeError):
            usage = {}
        return jsonify(id=row["id"], language=row["language"], status=row["status"],
                       stdout=row["stdout"] or "", stderr=row["stderr"] or "", exit_code=row["exit_code"],
                       wall_time=usage.get("wall_time"), resource_usage=usage)

    @app.get("/submissions")
    def submissions():
        try:
            limit = max(1, min(int(request.args.get("limit", 20)), 100))
        except (ValueError, TypeError):
            return jsonify(error="limit must be an integer"), 400
        return jsonify(submissions=database.list_recent(limit=limit))

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description, request_id=g.get("request_id")), error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        log.exception("Database request failed")
        return jsonify(error="Database temporarily unavailable", request_id=g.get("request_id")), 503

    @app.errorhandler(Exception)
    def unexpected_error(error):
        log.exception("Unhandled request error")
        return jsonify(error="Internal server error", request_id=g.get("request_id")), 500

    return app


app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=5000, threaded=True)
