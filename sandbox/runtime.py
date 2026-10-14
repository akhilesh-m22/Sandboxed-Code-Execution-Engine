"""Execution backends and bounded subprocess capture.

Docker is the security boundary for untrusted submissions. The process
backend is exclusively for trusted local development: working directories,
Python import filters and compiler warnings do not prevent host access.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
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
            "__build_class__", "super", "type",
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
    """Describe configured guarantees; this is not a Docker readiness probe."""
    import config

    backend = config.SANDBOX_BACKEND
    return {
        "backend": backend,
        "platform": sys.platform,
        "security_boundary": "linux-container" if backend == "docker" else "none (trusted local development only)",
        "network_isolation": str(backend == "docker").lower(),
        "filesystem_isolation": str(backend == "docker").lower(),
        "bounded_output": "true",
        "wallclock_timeout": "true",
        "process_tree_cleanup": "true",
        "memory_limit": "container cgroup" if backend == "docker" else ("Windows Job Object" if os.name == "nt" else "RLIMIT_AS"),
        "python_filters": "defense in depth; not a security boundary",
    }


def check_backend():
    """Fail startup if Docker or the configured Linux runner image is missing."""
    import config
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker CLI not found; install Docker or use process for trusted local demos")
    for args, expected in ((["info", "--format", "{{.OSType}}"], "linux"),
                           (["image", "inspect", "--format", "{{.Os}}", config.SANDBOX_IMAGE], "linux")):
        result = subprocess.run([docker, *args], capture_output=True, text=True, timeout=15)
        if result.returncode or result.stdout.strip() != expected:
            raise RuntimeError("Docker requires a running Linux daemon and a built SANDBOX_IMAGE")


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
            os.killpg(proc.pid, 9)  # SIGKILL the whole group
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


def _output_limit(value: Optional[int]) -> int:
    if value is None:
        import config
        value = config.MAX_RESULT_BYTES
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_output_bytes must be a positive integer")
    return value


def run_language(
    language: str,
    source: str,
    stdin: bytes = b"",
    timeout: float = 2.0,
    cpu_seconds: float = 2.0,
    mem_mb: int = 256,
    max_output_bytes: Optional[int] = None,
) -> Dict[str, object]:
    """Run source with the explicitly configured backend, never a fallback."""
    import config

    max_output_bytes = _output_limit(max_output_bytes)
    for name, value in (("timeout", timeout), ("cpu_seconds", cpu_seconds)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if isinstance(mem_mb, bool) or not isinstance(mem_mb, int) or mem_mb < 16:
        raise ValueError("mem_mb must be an integer of at least 16")
    checks = {"python": check_python, "c": check_c}
    if language not in checks:
        return _result(b"", f"unsupported language: {language!r}".encode(), -1, False)
    allowed, reason = checks[language](source)
    if not allowed:
        return _result(b"", reason.encode(), -1, False)
    backend = config.SANDBOX_BACKEND
    if backend == "docker":
        return _run_docker(language, source, stdin, timeout, cpu_seconds, mem_mb, max_output_bytes)
    if backend == "process":
        return _run_process(language, source, stdin, timeout, cpu_seconds, mem_mb, max_output_bytes)
    raise ValueError(f"unsupported SANDBOX_BACKEND: {backend!r}")


def _run_process(language, source, stdin, timeout, cpu_seconds, mem_mb, max_output_bytes):
    """Trusted-development runner; also used *inside* the isolated container."""
    with tempfile.TemporaryDirectory(prefix="sandbox_") as workdir:
        if language == "python":
            argv, cwd = _build_python_argv(source, workdir)
        else:
            compiler = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
            if compiler is None:
                return _result(b"", b"no C compiler found on PATH (need gcc/cc/clang)", -1, False)
            src_path = os.path.join(workdir, "main.c")
            with open(src_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(source)
            binary = os.path.join(workdir, "main.exe" if os.name == "nt" else "main")
            compilation = run_command(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O1",
                 "-fno-builtin", "-fPIE", "-pie", "-o", binary, src_path],
                cwd=workdir, timeout=10.0, cpu_seconds=10.0,
                mem_mb=max(mem_mb, 256), max_output_bytes=max_output_bytes,
            )
            if compilation["exit_code"] != 0:
                compilation["stderr"] = "compilation failed:\n" + compilation["stderr"]
                return _bounded_result(compilation, max_output_bytes)
            argv, cwd = [binary], workdir
        return run_command(
            argv, cwd=cwd, stdin=stdin, timeout=timeout, cpu_seconds=cpu_seconds,
            mem_mb=mem_mb, max_output_bytes=max_output_bytes,
        )


def _run_docker(language, source, stdin, timeout, cpu_seconds, mem_mb, max_output_bytes):
    import config

    docker = shutil.which("docker")
    if docker is None:
        return _result(b"", b"Docker backend unavailable: docker CLI was not found. No fallback is permitted.", 127, False)
    name = "codeforge-" + uuid.uuid4().hex
    # No host bind mounts, Docker socket, host environment or privileged mode
    # is passed to a submission. --pull=never makes a missing image fail closed.
    create = [
        docker, "create", "--name", name, "--pull=never", "--interactive", "--rm",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--user=65534:65534",
        "--pids-limit=64", f"--memory={mem_mb}m", f"--memory-swap={mem_mb}m",
        "--cpus=1.0", "--ulimit", "nofile=64:64", "--ulimit", "core=0:0",
        "--ulimit", "fsize=16777216:16777216", "--log-driver=none",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--tmpfs", "/work:rw,exec,nosuid,nodev,size=32m,mode=1777",
        "--workdir=/work", "--env=TMPDIR=/work", "--env=HOME=/work",
        config.SANDBOX_IMAGE,
    ]
    host_env = os.environ.copy()  # For Docker client/context; never sent to the container.
    try:
        created = run_command(
            create, cwd=tempfile.gettempdir(), timeout=15, max_output_bytes=16384,
            enforce_limits=False, env=host_env,
        )
        if created["exit_code"] != 0:
            created["stderr"] = "Docker container could not be created: " + created["stderr"]
            return _bounded_result(created, max_output_bytes)
        payload = json.dumps({
            "language": language, "source": source,
            "stdin": stdin.decode("utf-8", errors="replace"),
            "timeout": timeout, "cpu_seconds": cpu_seconds,
            "mem_mb": mem_mb, "max_output_bytes": max_output_bytes,
        }, ensure_ascii=True).encode("utf-8")
        attached = run_command(
            [docker, "start", "--attach", "--interactive", name],
            cwd=tempfile.gettempdir(), stdin=payload,
            # Runtime has its own wall clock; this outer cap also bounds startup
            # and compilation. rm --force in finally terminates the container.
            timeout=timeout + (10 if language == "c" else 0) + 10,
            max_output_bytes=max_output_bytes * 6 + 65536,
            enforce_limits=False, env=host_env,
        )
        if attached["exit_code"] != 0 or attached["output_truncated"]:
            attached["stderr"] = "Docker sandbox failed: " + attached["stderr"]
            return _bounded_result(attached, max_output_bytes)
        try:
            result = json.loads(attached["stdout"])
            if not isinstance(result, dict):
                raise ValueError("result is not an object")
            if not isinstance(result.get("stdout"), str) or not isinstance(result.get("stderr"), str):
                raise ValueError("invalid output fields")
            if type(result.get("exit_code")) is not int or type(result.get("timed_out")) is not bool:
                raise ValueError("invalid status fields")
            if type(result.get("output_truncated")) is not bool:
                raise ValueError("invalid output status")
            wall = result.get("wall_time")
            if wall is not None and (type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0):
                raise ValueError("invalid duration")
            return _result(
                result["stdout"].encode(), result["stderr"].encode(),
                result["exit_code"], result["timed_out"], wall=wall,
                output_truncated=result["output_truncated"], max_output_bytes=max_output_bytes,
            )
        except (ValueError, TypeError):
            return _result(b"", b"Docker sandbox returned an invalid response.", 127, False)
    finally:
        # Removing by the known random name also handles create timing out after
        # the daemon accepted it. Never just kill the attached Docker client.
        run_command(
            [docker, "rm", "--force", name], cwd=tempfile.gettempdir(),
            timeout=10, max_output_bytes=16384, enforce_limits=False, env=host_env,
        )


def run_command(
    argv: Sequence[str], cwd: str, stdin: bytes = b"", timeout: float = 2.0,
    cpu_seconds: float = 2.0, mem_mb: int = 256,
    max_output_bytes: Optional[int] = None, *, enforce_limits: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Capture a child with a shared stdout/stderr byte budget and tree cleanup.

    Reader threads discard excess bytes immediately and signal termination;
    communicate() is deliberately avoided because it buffers without a limit.
    POSIX limits use an exec helper, avoiding preexec_fn's threaded deadlocks.
    """
    max_output_bytes = _output_limit(max_output_bytes)
    command = list(argv)
    if enforce_limits and os.name == "posix":
        command = [sys.executable, "-I", "-S", os.path.join(os.path.dirname(__file__), "posix_exec.py"),
                   str(cpu_seconds), str(mem_mb)] + command
    started = time.monotonic()
    job = None
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, env=clean_env() if env is None else env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, start_new_session=(os.name == "posix"),
        )
        if enforce_limits and os.name == "nt":
            from .windows_job import WindowsJob
            try:
                job = WindowsJob(proc, mem_mb)
            except OSError:
                kill_process_tree(proc)
                proc.wait(timeout=5)
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    stream.close()
                raise
    except (OSError, subprocess.SubprocessError) as exc:
        return _result(b"", f"failed to start limited process: {exc}".encode(), 127, False)

    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    exceeded = threading.Event()
    used = 0

    def read_output(stream, target):
        nonlocal used
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                with lock:
                    remaining = max_output_bytes - used
                    buffers[target].extend(chunk[:remaining])
                    used += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        exceeded.set()
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def write_input():
        try:
            view = memoryview(stdin)
            while view:
                count = proc.stdin.write(view[:8192])
                if not count:
                    break
                view = view[count:]
        except (OSError, ValueError):
            pass
        finally:
            proc.stdin.close()

    readers = [threading.Thread(target=read_output, args=(stream, index), daemon=True)
               for index, stream in enumerate((proc.stdout, proc.stderr))]
    writer = threading.Thread(target=write_input, daemon=True)
    for thread in readers + [writer]:
        thread.start()
    timed_out = False
    try:
        while proc.poll() is None or any(thread.is_alive() for thread in readers):
            if exceeded.is_set():
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                break
            exceeded.wait(0.01)
    finally:
        # Always terminate the group, even after the direct child exited: a
        # descendant may still hold a pipe or outlive its parent.
        if job is not None:
            job.kill()
            job.close()
        else:
            kill_process_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for thread in readers + [writer]:
            thread.join(timeout=1)
    out, err = bytes(buffers[0]), bytes(buffers[1])
    if timed_out:
        # Put the diagnostic first so it survives a nearly full output budget.
        err = ("Execution timed out after %.2fs (wall clock).\n" % timeout).encode() + err
    if exceeded.is_set():
        err = b"Output limit exceeded.\n" + err
    return _result(
        out, err, -1 if exceeded.is_set() or timed_out else (proc.returncode if proc.returncode is not None else -1), timed_out,
        wall=time.monotonic() - started, output_truncated=exceeded.is_set(),
        max_output_bytes=max_output_bytes,
    )


def _bounded_result(result, limit):
    return _result(
        result["stdout"].encode(), result["stderr"].encode(),
        result["exit_code"], result["timed_out"], wall=result.get("wall_time"),
        output_truncated=result.get("output_truncated", False), max_output_bytes=limit,
    )


def _result(
    stdout: bytes, stderr: bytes, exit_code: int, timed_out: bool,
    wall: Optional[float] = None, output_truncated: bool = False,
    max_output_bytes: Optional[int] = None,
) -> Dict[str, object]:
    if max_output_bytes is not None:
        # Replacement characters can expand invalid UTF-8. Bound the encoded
        # response too, including the diagnostics added by the supervisor.
        stdout = stdout.decode("utf-8", errors="replace").encode("utf-8")
        stderr = stderr.decode("utf-8", errors="replace").encode("utf-8")
        if len(stdout) + len(stderr) > max_output_bytes:
            output_truncated = True
        stderr = stderr[:max_output_bytes]
        stdout = stdout[:max(0, max_output_bytes - len(stderr))]
    return {
        "stdout": stdout.decode("utf-8", errors="ignore" if max_output_bytes else "replace"),
        "stderr": stderr.decode("utf-8", errors="ignore" if max_output_bytes else "replace"),
        "exit_code": exit_code, "timed_out": timed_out, "wall_time": wall,
        "output_truncated": output_truncated,
    }
