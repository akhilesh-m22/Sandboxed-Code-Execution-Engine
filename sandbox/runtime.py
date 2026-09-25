# sandbox/runtime.py
# ---------------------------------------------------------------------------
# Process-level isolation runtime.
#
# The isolation model (in rough order of strength):
#
#   1. STATIC pre-checks      (sandbox/prechecks.py)      -- cheap filter
#   2. Python runtime jail    (this module + generated runner.py)
#      -- a guarded __import__ + warmly preloaded stdlib + stacked builtins,
#      so dangerous modules (os/subprocess/socket/sys/...) are unimportable
#      at runtime and the classic escape builtins do not exist.
#   3. C compiler flags (-Wall -Wextra -Werror -fno-builtin -pie)
#      -- the compiler IS the static filter for C: an undeclared call
#      (system/fork/socket/...) is a hard compile error in C11.
#   4. Process jail:
#        - stripped environment        -> nothing to leak
#        - isolated empty workdir      -> no access to the rest of the repo
#        - RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC (POSIX)
#        - new process group + preexec -> group-kill reaps grandchildren
#        - wall-clock watchdog thread  -> guaranteed kill on stuck progress
#
# Why a bootstrap "runner.py" instead of launching `python <src>` directly?
# Launching the source with plain flags (-I) still exposes the full stdlib
# (os.environ, subprocess, socket, ctypes, ...). The bootstrap replaces
# builtins.__import__ with a guard that raises ImportError for forbidden
# roots *regardless of the source text*, and shrinks the builtins dict. The
# guard only works because a curated stdlib prefix is imported first, before
# the guard is installed -- so legitimate modules like `random`/`json` can
# still load their own internal `os`/`sys` dependencies, while *user* code
# importing them directly is refused.
# ---------------------------------------------------------------------------

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .prechecks import check_c, check_python, FORBIDDEN_IMPORTS

# Hard-coded copy of the forbidden-import list for the ENTIRE bootstrap file
# (it is written to disk for the child; it must not read any engine code).
_BOOTSTRAP_FORBIDDEN_IMPORTS = tuple(sorted(FORBIDDEN_IMPORTS))

# Builtins the untrusted submission may reach. This shrinks the attack
# surface; ordinary algorithmic code never needs the rest.
_SAFE_BUILTINS = tuple(
    sorted(
        {
            "None", "True", "False", "NotImplemented", "Ellipsis",
            "abs", "all", "any", "ascii", "bin", "bool", "bytearray",
            "bytes", "callable", "chr", "classmethod", "complex", "delattr",
            "dict", "divmod", "enumerate", "filter", "float", "format",
            "frozenset", "hasattr", "hash", "hex", "id", "int", "input",
            "isinstance", "issubclass", "iter", "len", "list", "map", "max",
            "min", "next", "object", "oct", "ord", "pow", "print",
            "property", "range", "repr", "reversed", "round", "set",
            "slice", "sorted", "staticmethod", "str", "sum", "tuple", "zip",
            # exceptions users may legitimately catch/raise
            "Exception", "BaseException", "ArithmeticError", "AssertionError",
            "AttributeError", "EOFError", "ImportError", "IndexError",
            "KeyError", "LookupError", "MemoryError", "ModuleNotFoundError",
            "NameError", "OSError", "OverflowError",
            "RuntimeError", "StopIteration", "SyntaxError", "TypeError",
            "UnicodeError", "ValueError", "ZeroDivisionError",
        }
    )
)

# stdlib modules pre-imported by the bootstrap BEFORE the import guard is
# installed. Why: modules like `random` or `decimal` import `os`/`sys`
# internally, which the guard would otherwise reject. Preloading lets the
# engine cache these (and their transitive deps) first, so the guard only
# ever fires on *user* imports of forbidden roots.
_PRELOADED_LIBS = (
    "math", "random", "json", "re", "collections", "functools", "itertools",
    "statistics", "bisect", "heapq", "fractions", "decimal", "string",
    "operator", "array", "unicodedata", "base64", "binascii", "struct",
    "hashlib", "secrets",
)

# Dangerous attributes stripped from modules that are necessarily preloaded
# (so `os` exists in sys.modules but `os.system`/`os.popen` cannot be called,
# even if the import guard were ever bypassed).
_STRIP_FROM_OS = (
    "system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe", "fork", "forkpty",
    "execl", "execle", "execlp", "execlpe", "execv", "execve",
    "execvp", "execvpe", "posix_spawn", "kill", "killpg", "getenv",
    "putenv", "unsetenv", "remove", "unlink", "rmdir", "removedirs",
    "chmod", "chown", "chroot", "chdir", "open", "mkfifo", "mknod",
    "mount", "umount", "searchpath",
)


def describe_caps() -> Dict[str, str]:
    """Return a dict of effective sandbox capabilities (for tests/readme)."""
    caps: Dict[str, str] = {
        "platform": sys.platform,
        "wallclock_watchdog": "true",
        "python_guarded_import": "true",
        "python_restricted_builtins": "true",
        "python_preloaded_libs": str(len(_PRELOADED_LIBS)),
        "c_werror_filter": "true",
    }
    try:
        import resource  # noqa: F401

        for attr in ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_NPROC"):
            caps[f"posix:{attr.lower()}"] = str(hasattr(resource, attr))
    except ImportError:
        caps["posix_rlimits"] = "unavailable (win32)"
    caps["killpg"] = str(hasattr(os, "killpg"))
    return caps


# =========================================================================
# Clean environment.
# =========================================================================

def clean_env() -> Dict[str, str]:
    """Return a minimal environment for the untrusted child.

    Everything sensitive on the host (API keys, config, secrets) lives in the
    surrounding process env; we forward almost nothing, so `os.environ` inside
    the sandbox naturally cannot see it.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
    }
    if os.name == "nt":
        env.setdefault("TEMP", os.environ.get("TEMP", ""))
        env.setdefault("TMP", os.environ.get("TMP", ""))
        env.setdefault("SYSTEMROOT", os.environ.get("SYSTEMROOT", "C:\\Windows"))
    return env


# =========================================================================
# Process-group kill / reaping.
# =========================================================================

def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill the subprocess and, on POSIX, its entire process group.

    The watchdog relies on this to guarantee a submission that forked
    children (fork-bomb attempts, async workers, ...) is fully torn down
    in bounded time instead of leaking processes.
    """
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL the whole group
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


# =========================================================================
# The bootstrap runner (written into the empty workdir).
# =========================================================================

_BOOTSTRAP_RUNNER = '''\
# sandbox bootstrap runner -- generated by the execution engine and executed
# with `python -S -I -E -B runner.py`. It hardens the interpreter in this
# order, then runs the user's main.py:
#   1. preload a curated stdlib prefix        (safe modules + their deps)
#   2. strip dangerous attrs from preloaded os
#   3. install a guarded __import__           (user code can no longer
#      import os/subprocess/socket/sys/...   -- raise ImportError instead)
#   4. shrink builtins to a safe subset
import builtins
import sys

FORBIDDEN = @@FORBIDDEN@@
SAFE = set(@@SAFE@@)
PRELOAD = @@PRELOAD@@

# -- 1. preload the safe stdlib prefix (import guard NOT active yet) ------
import importlib
for _name in PRELOAD:
    try:
        importlib.import_module(_name)
    except Exception:
        pass  # a missing module must not brick the whole sandbox

# -- 2. strip dangerous attributes from os (it is necessarily resident) ---
import os as _os
for _attr in @@STRIP@@:
    try:
        delattr(_os, _attr)
    except AttributeError:
        pass

# -- 3. guarded __import__ -------------------------------------------------
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0:  # relative imports (``from .x import y``) are engine-side
        root = name.split(".")[0]
        if root in FORBIDDEN:
            raise ImportError(
                "import %r is forbidden in the sandbox" % root
            )
    return _real_import(name, globals, locals, fromlist, level)

_real_import = builtins.__import__
builtins.__import__ = _guarded_import

# -- 4. shrink builtins to a safe algorithmic subset -----------------------
# Capture interpreter primitives the runner itself still needs, since the
# shrink below removes them from builtins.
_exec = exec
_compile = compile
_open = open

for name in list(builtins.__dict__):
    if name not in SAFE:
        builtins.__dict__.pop(name, None)
for name in ("help", "breakpoint"):
    builtins.__dict__.pop(name, None)
# The import machinery needs builtins.__import__ *at call time* (statements
# in exec'd/shared code resolve it lazily). Keep the GUARDED version -- user
# code can import, but only roots outside FORBIDDEN get through.
builtins.__dict__["__import__"] = _guarded_import

# -- 5. run the submission -------------------------------------------------
# exec(compile(...)) instead of runpy.run_path: runpy lazily imports pkgutil
# (which we ban), and runpy's module bookkeeping is surface we don't need.
_globals = {
    "__name__": "__main__",
    "__file__": "main.py",
    "__builtins__": builtins.__dict__,
}
with _open("main.py", "rb") as _fh:
    _code = _compile(_fh.read(), "main.py", "exec")
_exec(_code, _globals)
'''


def _write_bootstrap(workdir: str) -> None:
    """Write runner.py into workdir with the forbidden/safe lists injected."""
    content = (
        _BOOTSTRAP_RUNNER.replace("@@FORBIDDEN@@", repr(_BOOTSTRAP_FORBIDDEN_IMPORTS))
        .replace("@@" + "SAFE" + "@@", repr(set(_SAFE_BUILTINS)))
        .replace("@@" + "PRELOAD" + "@@", repr(_PRELOADED_LIBS))
        .replace("@@" + "STRIP" + "@@", repr(_STRIP_FROM_OS))
    )
    with open(os.path.join(workdir, "runner.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


# =========================================================================
# POSIX resource limits.
# =========================================================================

def _apply_posix_limits(cpu_seconds: float, mem_mb: int, max_procs: int) -> None:
    """Apply hard rlimits to the *current process* (executed pre-exec in the
    child). Sets a new process group first so the watchdog can group-kill.

    Failures are silent by design: losing an rlimit means the CPU/memory
    enforcement falls back to the wall-clock watchdog -- a graceful
    degradation rather than a silent security hole.
    """
    if os.name != "posix":
        return
    import resource

    try:
        os.setsid()  # start a fresh session/process group
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds), int(cpu_seconds) + 1))
    except Exception:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
    except Exception:
        pass
    if max_procs > 0:
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))
        except Exception:
            pass


# =========================================================================
# Language-specific argv builders.
# =========================================================================

def _build_python_argv(source: str, workdir: str) -> Tuple[List[str], str]:
    """Write main.py + the bootstrap runner into the empty workdir."""
    _write_bootstrap(workdir)
    with open(os.path.join(workdir, "main.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source)
    # -S : no site; -I : isolated (ignore PYTHON* env, no user site);
    # -B : no .pyc; -E : ignore PYTHON* env vars explicitly.
    argv = [sys.executable, "-S", "-I", "-E", "-B", os.path.join(workdir, "runner.py")]
    return argv, workdir


def _compile_c(source: str, workdir: str) -> Optional[str]:
    """Compile C source into workdir; returns path to the binary or None
    (with the human-readable compile rejection written to <workdir>/err.txt).
    """
    src_path = os.path.join(workdir, "main.c")
    with open(src_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source)

    cc = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if cc is None:
        raise RuntimeError("no C compiler found on PATH (need gcc/cc/clang)")

    out_path = os.path.join(workdir, "main" + (".exe" if os.name == "nt" else ""))

    # -std=c11 -Wall -Wextra -Werror : foundational safety net. An implicit
    # declaration (call to system/fork/exec*/socket without a prototype) is a
    # hard compile error in C11 -- the compiler is the authoritative static
    # filter for C. -fno-builtin/-fPIE/-pie: predictable, position-independent
    # code and no clever builtin substitutions.
    cmd = [
        cc,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O1",
        "-fno-builtin",
        "-fPIE",
        "-pie",
        "-o",
        out_path,
        src_path,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        err_text = proc.stderr.decode("utf-8", errors="replace") or "compile failed"
        with open(os.path.join(workdir, "err.txt"), "w", encoding="utf-8") as fh:
            fh.write(err_text)
        return None
    return out_path


# =========================================================================
# The core runner.
# =========================================================================

def run_language(
    language: str,
    source: str,
    stdin: bytes = b"",
    timeout: float = 2.0,
    cpu_seconds: float = 2.0,
    mem_mb: int = 256,
) -> Dict[str, object]:
    """Sandboxed execution of untrusted source.

    Returns a dict with stdout/stderr (str), exit_code (int), timed_out
    (bool) and wall_time (float seconds). This function is what the workers
    call; it never raises for user-code failures (only for engine/compiler
    absence).
    """
    if language == "python":
        allowed, reason = check_python(source)
        if not allowed:
            return _result(b"", reason.encode(), -1, False)
    elif language == "c":
        allowed, reason = check_c(source)
        if not allowed:
            return _result(b"", reason.encode(), -1, False)
    else:
        return _result(b"", f"unsupported language: {language!r}".encode(), -1, False)

    # A brand-new, empty directory only the child can write to. It is removed
    # after execution -- the submission has no persistent home.
    workdir = tempfile.mkdtemp(prefix="sandbox_")
    try:
        if language == "python":
            argv, cwd = _build_python_argv(source, workdir)
        else:
            try:
                binary = _compile_c(source, workdir)
            except RuntimeError as exc:
                # Engine-level problem (missing compiler) -- surface as a
                # failed submission, not an unhandled exception.
                return _result(b"", str(exc).encode(), -1, False)
            if binary is None:
                return _read_compile_error(workdir)
            argv, cwd = [binary], workdir
        return run_command(
            argv,
            cwd=cwd,
            stdin=stdin,
            timeout=timeout,
            cpu_seconds=cpu_seconds,
            mem_mb=mem_mb,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _read_compile_error(workdir: str) -> Dict[str, object]:
    try:
        with open(os.path.join(workdir, "err.txt"), encoding="utf-8") as fh:
            msg = fh.read()
    except OSError:
        msg = "compilation failed"
    return _result(b"", f"compilation failed:\n{msg}".encode(), 127, False)


def run_command(
    argv: Sequence[str],
    cwd: str,
    stdin: bytes = b"",
    timeout: float = 2.0,
    cpu_seconds: float = 2.0,
    mem_mb: int = 256,
) -> Dict[str, object]:
    """The heart of the sandbox: spawn -> jail -> watch -> reap.

      * cwd    = the fresh empty workdir
      * env    = clean_env() (stripped of host secrets)
      * preexec_posix: new process group + RLIMIT_CPU/AS/NPROC (POSIX)
      * stdout/stderr = captured through pipes (no temp-file handles leaked)
      * watchdog thread enforces a hard wall-clock deadline even if the main
        thread's communicate() is wedged on uninterruptible IO.
    """
    env = clean_env()

    def _preexec():
        _apply_posix_limits(cpu_seconds, mem_mb, max_procs=1)

    try:
        proc: subprocess.Popen = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_preexec if os.name == "posix" else None,
        )
    except Exception as exc:  # interpreter/binary never started
        return _result(b"", f"failed to start sandboxed process: {exc}".encode(), 127, False)

    started = time.monotonic()
    watchdog = threading.Thread(
        target=_watchdog,
        args=(proc, timeout),
        name="sandbox-watchdog",
        daemon=True,
    )
    watchdog.start()

    timed_out = False
    out = b""
    err = b""
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Wall-clock limit hit: the submission was stuck. Nuke the whole tree.
        timed_out = True
        kill_process_tree(proc)
        proc.wait()
        out = b""
        err = b"Execution timed out after %.1fs (wall clock).\n" % timeout
    finally:
        watchdog.join(timeout=5)

    wall = time.monotonic() - started
    return _result(out, err, proc.returncode, timed_out, wall=wall)


def _watchdog(proc: subprocess.Popen, timeout: float) -> None:
    """Daemon thread enforcing a hard wall-clock cap.

    Normal timeouts are handled by communicate(timeout=...) in the main
    thread; this thread only claims the kill when the main thread is stuck
    (e.g. blocked in uninterruptible IO that swallows the OS signal), or to
    guarantee the process TREE (forked children) is killed, which
    communicate() cannot do by itself.
    """
    deadline = time.monotonic() + timeout + 1.0
    while True:
        if proc.poll() is not None:
            return  # exited on its own
        if time.monotonic() > deadline:
            kill_process_tree(proc)
            return
        time.sleep(0.05)


def _result(
    stdout: bytes,
    stderr: bytes,
    exit_code: int,
    timed_out: bool,
    wall: Optional[float] = None,
) -> Dict[str, object]:
    return {
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_time": wall,
    }