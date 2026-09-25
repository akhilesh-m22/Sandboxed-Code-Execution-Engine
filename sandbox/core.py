# sandbox/core.py
# Public, language-agnostic entry point into the isolation layer.

from __future__ import annotations

from typing import Dict, Optional

from .runtime import run_language, describe_caps

DEFAULT_LIMITS = {
    "timeout": 2.0,        # hard wall-clock cap per submission (seconds)
    "cpu_seconds": 2.0,    # RLIMIT_CPU budget (POSIX)
    "mem_mb": 256,         # RLIMIT_AS budget (POSIX)
    "max_output_bytes": 4 * 1024 * 1024,
}


def run_code(
    language: str,
    source: str,
    stdin: str = "",
    timeout: Optional[float] = None,
    cpu_seconds: Optional[float] = None,
    mem_mb: Optional[int] = None,
) -> Dict[str, object]:
    """Execute untrusted code inside the sandbox and return a result dict.

    :param language: one of "python" | "c"
    :param source:   raw source code
    :param stdin:    program input string
    :param timeout:  wall-clock cap in seconds (None -> DEFAULT_LIMITS)
    :param cpu_seconds: RLIMIT_CPU budget (None -> DEFAULT_LIMITS)
    :param mem_mb:      RLIMIT_AS budget (None -> DEFAULT_LIMITS)
    :returns: durable result (stdout/stderr are strings, exit_code is int,
              wall_time is float|None)
    """
    timeout = DEFAULT_LIMITS["timeout"] if timeout is None else timeout
    cpu_seconds = DEFAULT_LIMITS["cpu_seconds"] if cpu_seconds is None else cpu_seconds
    mem_mb = DEFAULT_LIMITS["mem_mb"] if mem_mb is None else mem_mb

    return run_language(
        language,
        source,
        stdin=stdin.encode("utf-8", errors="replace"),
        timeout=timeout,
        cpu_seconds=cpu_seconds,
        mem_mb=mem_mb,
    )


__all__ = ["run_code", "describe_caps", "DEFAULT_LIMITS"]