# sandbox/prechecks.py
# ---------------------------------------------------------------------------
# Static pre-checks ("lint" for malicious submissions).
#
# WHY: Runtime sandboxing (rlimits, timeouts) is the primary defence, but a
# cheap static scan lets us reject trivially dangerous submissions *before*
# they ever consume a worker or touch the filesystem. This is defence in
# depth, NOT the security boundary itself.
#
# LIMITATION: substring/pattern matching is trivially bypassable by anyone
# who can obfuscate text (e.g. `getattr(os, "system")`, string concatenation,
# codecs decode, ...). Always treat this as a convenience filter and rely on
# the process-level sandbox for real protection.
# ---------------------------------------------------------------------------

from __future__ import annotations
from typing import Tuple

# Python risk signals. We look for the *source text* of dangerous symbols/
# imports and for indirection primitives that make static analysis NULL.
PY_BLOCKLIST_PATTERNS: tuple[str, str] = (
    # Process / OS escapes
    "os.system",
    "system(",
    "subprocess",
    "popen",
    "spawn",
    "fork",
    "vfork",
    "execv",
    "execl",
    "pty.",
    # Network exfil
    "socket",
    # Indirection that defeats this static pass
    "__import__",
    "__builtins__",
    "__subclasses__",
    "__globals__",
    "eval(",
    "exec(",
    "compile(",
    "getattr",
    "globals()[",
    "locals()[",
    "codecs.decode",
    "marshal.loads",
    "pickle.loads",
    # Filesystem access outside the sandbox workdir
    "open(",
    "file(",
    "shutil.",
    "glob.",
    "pathlib.",
    # Network / remote libs
    "requests",
    "urllib",
    "http.client",
    "ftplib",
    "smtplib",
    "telnetlib",
    "importlib",
)

# ---------------------------------------------------------------------------
# NOTE on C: because every C submission is compiled with `-fsyntax-only` and
# `-Werror`, the *compiler itself* becomes our static filter: calling an
# undeclared function (system, fork, exec*, socket, ...) is a compile error.
# We still do a light text sniff so the API can reject the submission before
# burning compiler time, but the compiler is the authoritative check.
# ---------------------------------------------------------------------------
C_BLOCKLIST_PATTERNS: tuple[str, str] = (
    "system(",
    "fork",
    "vfork",
    "clone(",
    "execl",
    "execv",
    "posix_spawn",
    "socket(",
)


def check_python(source: str) -> Tuple[bool, str]:
    """Return (is_allowed, reason). Blocks on a single dangerous text match."""
    src = source.lower()
    for pat in PY_BLOCKLIST_PATTERNS:
        if pat in src:
            return False, f"static pre-check flagged pattern: {pat!r}"
    return True, ""


def check_c(source: str) -> Tuple[bool, str]:
    """Return (is_allowed, reason). Blocks obvious syscall usage in C text."""
    src = source.lower()
    for pat in C_BLOCKLIST_PATTERNS:
        if pat in src:
            return False, f"static pre-check flagged pattern: {pat!r}"
    return True, ""


# Name-based import guard for the Python isolation runtime. This is what
# actually refuses dangerous `import`s *at runtime* (defense in depth on top
# of the static pass + process sandbox). See sandbox/runtime.py.
#
# NOTE: `sys` and `os` are deliberately banned too -- but that only stops the
# *user* from importing them. The bootstrap imports `sys`/`os` internally
# before installing the guard, so the engine itself still works.
FORBIDDEN_IMPORTS: frozenset = frozenset(
    {
        # process / OS escapes
        "os",
        "subprocess",
        "shutil",
        "multiprocessing",
        "posix",
        "nt",
        # networking
        "socket",
        "urllib",
        "urllib3",
        "requests",
        "http",
        "ftplib",
        "smtplib",
        "telnetlib",
        "ssl",
        # low-level / native code
        "ctypes",
        "fcntl",
        "mmap",
        "termios",
        "resource",
        "pwd",
        "grp",
        "syslog",
        "pty",
        # interpreter introspection / execution indirection
        "sys",
        "builtins",
        "importlib",
        "runpy",
        "code",
        "codeop",
        "site",
        "inspect",
        "traceback",
        "gc",
        "types",
        "typing",
        # concurrency (fork-bombs / threads bypass rlimits)
        "threading",
        "_thread",
        "queue",
        "asyncio",
        "concurrent",
        # filesystem / env surface
        "pathlib",
        "glob",
        "tempfile",
        "platform",
        "psutil",
        "os",
        "pkgutil",
        "zipfile",
        "tarfile",
        "gzip",
        "bz2",
        "lzma",
        # remote code / serialization pivots
        "pickle",
        "marshal",
        "shelve",
        "dill",
    }
)