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
import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent


def _load_file_config() -> dict:
    """Read config.json (optional). Non-fatal if missing/invalid."""
    path = _BASE_DIR / "config.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _coerce(raw, default):
    """Convert an env/file string into the default's type."""
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
        "db_path": _resolve("DB_PATH"),
        "max_workers": _resolve("MAX_WORKERS"),
        "timeout_seconds": _resolve("TIMEOUT_SECONDS"),
        "cpu_seconds": _resolve("CPU_SECONDS"),
        "mem_mb": _resolve("MEM_MB"),
        "max_code_bytes": _resolve("MAX_CODE_BYTES"),
        "max_result_bytes": _resolve("MAX_RESULT_BYTES"),
    }