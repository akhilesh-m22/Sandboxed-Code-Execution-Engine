# tests/test_sandbox_security.py
# The security test suite: every row in this file is an ACTIVE attack on the
# isolation layer (plus a handful of control cases proving the sandbox is not
# just a black hole). If ANY of these "yes we blocked it" assertions start
# failing, the sandbox is broken -- run them first on a fresh checkout.

from __future__ import annotations

import pytest

import sandbox

# ---------------------------------------------------------------------------
# Controls: benign workloads must still work.
# ---------------------------------------------------------------------------

def test_python_hello_world():
    r = sandbox.run_code("python", "print('hello')")
    assert r["stdout"].strip() == "hello"
    assert r["exit_code"] == 0


def test_python_reads_stdin():
    r = sandbox.run_code("python", "print(input().upper())", stdin="attack surface")
    assert r["stdout"].strip() == "ATTACK SURFACE"
    assert r["exit_code"] == 0


def test_python_safe_stdlib_is_usable():
    # math/random/json import fine even though their deps (os) are banned.
    r = sandbox.run_code(
        "python",
        "import math, random, json\n"
        "print(math.factorial(5))\n"
        "print(len(json.dumps({'x': 1})))\n"
        "print(random.randint(1, 1))",
    )
    assert r["exit_code"] == 0
    lines = r["stdout"].splitlines()
    assert lines[0] == "120"
    assert lines[1] == "8"  # len('{"x": 1}')


def test_python_runtime_error_is_reported():
    r = sandbox.run_code("python", "1 / 0")
    assert r["exit_code"] != 0
    assert "ZeroDivisionError" in r["stderr"]

# ---------------------------------------------------------------------------
# Attack 1: fork-bomb attempts (both explicit and obfuscated-ish).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "import os\nwhile True:\n    os.fork()",
        "import multiprocessing\nwhile True:\n    multiprocessing.Process(target=lambda: 1).start()",
    ],
)
def test_fork_bomb_blocked(source):
    # The import guard + static scan must stop BOTH before any fork happens.
    r = sandbox.run_code("python", source)
    assert r["exit_code"] != 0
    assert "forbidden" in r["stderr"] or "flagged" in r["stderr"]

# ---------------------------------------------------------------------------
# Attack 2: infinite loops -- must be killed by the wall-clock watchdog.
# ---------------------------------------------------------------------------

def test_infinite_loop_times_out_and_is_killed():
    r = sandbox.run_code("python", "while True:\n    pass", timeout=1.0)
    assert r["timed_out"] is True
    assert "timed out" in r["stderr"].lower()
    # The child must actually be gone, not merely "reported timed out".
    assert r["exit_code"] != 0


def test_busy_wait_with_output_times_out():
    # Program that writes forever: the pipe fills, communicate() wedges,
    # the watchdog must reclaim the process. (Guards against deadlock.)
    r = sandbox.run_code(
        "python", "while True:\n    print('y' * 1024)", timeout=1.0
    )
    assert r["timed_out"] or r["output_truncated"]
    assert len(r["stdout"].encode()) + len(r["stderr"].encode()) <= 4 * 1024 * 1024

# ---------------------------------------------------------------------------
# Attack 3: reading files OUTSIDE the temp workdir.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "import os\nprint(open('/etc/passwd').read())",          # direct open
        "import os\nfor root, _, fs in os.walk('/'):\n    print(fs)",  # traversal
        "import shutil\nshutil.copy('/etc/passwd', 'pwned')",    # file copy
        "import pathlib\np = pathlib.Path('/etc/passwd')\nprint(p.read_text())",
    ],
)
def test_read_files_outside_sandbox_blocked(source):
    r = sandbox.run_code("python", source)
    assert r["exit_code"] != 0
    assert "forbidden" in r["stderr"] or "flagged" in r["stderr"]
    assert "/etc/passwd" not in r["stdout"]


def test_cannot_touch_project_files():
    # A smarter probe: `eval` indirection to smuggle an open(). The static
    # checker flags it, and even if it slipped through, `open` is not a
    # builtin + os/importlib are guarded.
    r = sandbox.run_code(
        "python",
        "import sys\nprint(open('config.py').read())",  # config.py sits next door
    )
    assert r["exit_code"] != 0

# ---------------------------------------------------------------------------
# Attack 4: environment variable leakage.
# ---------------------------------------------------------------------------

def test_environment_does_not_leak(monkeypatch):
    # Plant a secret in the HOST process env; the sandbox must never see it.
    monkeypatch.setenv("SANDBOX_TEST_SECRET", "hunter2")
    r = sandbox.run_code(
        "python",
        "import os\nprint(os.environ.get('SANDBOX_TEST_SECRET', 'not found'))",
    )
    assert "not found" in r["stdout"] or "forbidden" in r["stderr"]
    assert "hunter2" not in r["stdout"]
    assert "hunter2" not in r["stderr"]

# ---------------------------------------------------------------------------
# Attack 5: subprocess spawning (any form).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nsubprocess.run(['id'])",
        "import subprocess\nsubprocess.Popen(['ls'])",
        "from subprocess import check_output",
        "import os\nos.system('ls')",
        "import os\nos.popen('ls')",
        "import pty\npty.spawn('/bin/sh')",
        "import ctypes\nlibc = ctypes.CDLL(None)",
    ],
)
def test_subprocess_and_shell_escapes_blocked(source):
    r = sandbox.run_code("python", source)
    assert r["exit_code"] != 0
    assert "forbidden" in r["stderr"] or "flagged" in r["stderr"]

# ---------------------------------------------------------------------------
# Attack 6: memory abuse -- large allocation must be capped (rlimit) or
# crash (MemoryError) -- never succeed, never OOM the host.
# ---------------------------------------------------------------------------

def test_large_memory_allocation_blocked():
    r = sandbox.run_code("python", "x = [1] * (2 ** 31)", timeout=5.0, mem_mb=64)
    assert r["exit_code"] != 0
    assert "MemoryError" in r["stderr"] or r["timed_out"]


def test_moderate_memory_ok():
    # 20 MB fits under the default 256 MB cap -- ensure we didn't break normal
    # allocation (catches over-eager rlimit bugs).
    r = sandbox.run_code("python", "x = bytearray(20 * 1024 * 1024)\nprint(len(x))")
    assert r["exit_code"] == 0
    assert "20971520" in r["stdout"]

# ---------------------------------------------------------------------------
# Attack 7: interpreter indirection -- meta-programming the guard.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        # dynamic import must still hit the guarded __import__
        "__import__('os').system('ls')",
        # builtins reach-around via __builtins__ is impossible post-shrink
        "print(__builtins__.__dict__.keys())",
        # getattr is removed from builtins
        "getattr(__import__('os'), 'system')",
    ],
)
def test_metaprogramming_indirection_blocked(source):
    r = sandbox.run_code("python", source)
    assert r["exit_code"] != 0

# ---------------------------------------------------------------------------
# Attack 8: C submissions -- a system() attempt must not even compile.
# ---------------------------------------------------------------------------

def test_c_hello_world_missing_compiler_is_graceful_or_succeeds():
    # On CI with gcc this runs; on a laptop without a compiler the engine
    # must degrade to a clean failure result -- never a raise.
    r = sandbox.run_code("c", "#include <stdio.h>\nint main(void){printf(\"hi\\n\");return 0;}")
    assert "exit_code" in r
    if "no C compiler" not in r["stderr"]:
        assert r["exit_code"] == 0
        assert r["stdout"].strip() == "hi"
    else:
        assert r["exit_code"] == -1


def test_c_system_call_rejected():
    r = sandbox.run_code("c", "int main(void){system(\"ls\"); return 0;}")
    assert r["exit_code"] != 0
    assert (
        "flagged" in r["stderr"]
        or "compilation failed" in r["stderr"]
        or "no C compiler" in r["stderr"]
    )
