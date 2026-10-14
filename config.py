# config.py
# Central configuration.
#
# Precedence for every key (highest first):
#   1. process environment variable named after the key (e.g. MAX_WORKERS)
#   2. config.json sitting next to this file
#   3. hard-coded default below
#
# Values are resolved LAZILY (module __getattr__, PEP 562): every `config.X`
# read re-checks the environment, which is what lets tests swap DB_PATH per
# test run without re-importing anything.

from __future__ import annotations

import json
import math
import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent


def _load_file_config() -> dict:
    """Read optional config.json; reject malformed configuration at startup."""
    path = _BASE_DIR / "config.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("config.json must contain an object")
            return data
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("Cannot read config.json") from exc
    return {}


def _coerce(raw, default):
    """Convert an env/file string into the default's type."""
    if not isinstance(raw, str):
        return raw  # already a native type (e.g. from config.json)
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


_FILE_CONFIG = _load_file_config()

_DEFAULTS = {
    "DB_PATH": str(_BASE_DIR / "submissions.db"),
    "POLL_INTERVAL": 0.2,
    "MAX_WORKERS": 4,
    "TIMEOUT_SECONDS": 2.0,
    "CPU_SECONDS": 2.0,
    "MEM_MB": 256,
    "MAX_CODE_BYTES": 1024 * 1024,
    "MAX_RESULT_BYTES": 4 * 1024 * 1024,
    "SQLITE_TIMEOUT": 10.0,
    "APP_ENV": "development",
    "API_TOKEN": "",
    "SANDBOX_BACKEND": "process",
    "SANDBOX_IMAGE": "codeforge-sandbox:local",
    "MAX_STDIN_BYTES": 64 * 1024,
    "MAX_PENDING_JOBS": 100,
    "WORKER_HEARTBEAT_SECONDS": 2.0,
    "WORKER_STALE_SECONDS": 60.0,
    "RESULT_RETENTION_SECONDS": 86400,
}


def _resolve(name):
    """env override -> config.json value -> default."""
    if name in os.environ and os.environ[name] != "":
        return _coerce(os.environ[name], _DEFAULTS[name])
    if name in _FILE_CONFIG and _FILE_CONFIG[name] != "":
        return _coerce(_FILE_CONFIG[name], _DEFAULTS[name])
    return _DEFAULTS[name]


def __getattr__(name: str):
    """Module-level lazy resolution: `config.MAX_WORKERS` hits env config.json
    on every access (PEP 562)."""
    if name in _DEFAULTS:
        return _resolve(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def public_dict() -> dict:
    """Non-secret snapshot used by /health and the README."""
    return {
        "max_workers": _resolve("MAX_WORKERS"),
        "timeout_seconds": _resolve("TIMEOUT_SECONDS"),
        "cpu_seconds": _resolve("CPU_SECONDS"),
        "mem_mb": _resolve("MEM_MB"),
        "max_code_bytes": _resolve("MAX_CODE_BYTES"),
        "max_result_bytes": _resolve("MAX_RESULT_BYTES"),
        "max_stdin_bytes": _resolve("MAX_STDIN_BYTES"),
        "max_pending_jobs": _resolve("MAX_PENDING_JOBS"),
    }


def validate() -> None:
    """Fail at startup on unsafe deployment settings or invalid limits."""
    for name, default in _DEFAULTS.items():
        value = _resolve(name)
        if isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
            if isinstance(default, int) and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        elif not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
    if _resolve("APP_ENV") not in ("development", "production", "testing"):
        raise ValueError("APP_ENV must be development, testing, or production")
    if _resolve("SANDBOX_BACKEND") not in ("process", "docker"):
        raise ValueError("SANDBOX_BACKEND must be process or docker")
    if _resolve("WORKER_STALE_SECONDS") <= 3 * _resolve("WORKER_HEARTBEAT_SECONDS"):
        raise ValueError("WORKER_STALE_SECONDS must exceed three heartbeat intervals")
    if _resolve("MEM_MB") < 16:
        raise ValueError("MEM_MB must be at least 16")
    if not _resolve("DB_PATH").strip() or not _resolve("SANDBOX_IMAGE").strip():
        raise ValueError("DB_PATH and SANDBOX_IMAGE cannot be blank")
    token = _resolve("API_TOKEN")
    if token and (len(token) < 32 or not token.isascii() or any(c.isspace() for c in token)):
        raise ValueError("API_TOKEN must contain at least 32 ASCII characters without whitespace")
    if _resolve("APP_ENV") == "production":
        if _resolve("SANDBOX_BACKEND") != "docker":
            raise ValueError("Production requires SANDBOX_BACKEND=docker; process is for trusted local development")
        if not token:
            raise ValueError("Production requires a randomly generated API_TOKEN (at least 32 characters)")
