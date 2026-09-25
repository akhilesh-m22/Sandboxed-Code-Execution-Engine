# Sandboxed Code Execution Engine

A backend service that safely executes **untrusted student/AI-snippet code**
(Python and C) with a REST API, a multiprocessing worker pool, SQLite
persistence, and a defence-in-depth isolation layer — the same shape as the
things powering HackerRank / LeetCode / CI runners. Written for clarity so
every design decision is explainable in an interview.

---

## Quick start

```bash
# 1. create a venv and install dependencies
python -m venv .venv
.\.venv\Scripts\activate        # POSIX: source .venv/bin/activate
pip install -r requirements.txt

# 2. run the API + worker pool together (dev mode)
python run.py

# 3. or run them as separate processes (readier for prod)
python -m api.app               # terminal 1 : REST API on http://127.0.0.1:5000
python -m worker.pool           # terminal 2 : worker pool

# 4. exercise the API (or run the self-contained demo)
curl -X POST http://127.0.0.1:5000/submit \
     -H "Content-Type: application/json" \
     -d "{\"language\":\"python\",\"source\":\"print('hi')\",\"stdin\":\"\"}"
curl http://127.0.0.1:5000/status/<id>
curl http://127.0.0.1:5000/result/<id>
python examples/demo.py         # push all examples through a real pool
```

All config lives in `config.py` and is overridable per key via environment
variable or `config.json` (`MAX_WORKERS`, `TIMEOUT_SECONDS`, `CPU_SECONDS`,
`MEM_MB`, `DB_PATH`, …).

---

## REST API

| Endpoint | Method | Body / Params | Returns |
|---|---|---|---|
| `/submit` | POST | `{"language": "python\|c", "source": "...", "stdin": "..."}` | `201 {id, status, _links}` |
| `/status/<id>` | GET | — | `{id, language, status, submitted_at}` |
| `/result/<id>` | GET | — | `{id, status, stdout, stderr, exit_code, wall_time}` |
| `/submissions` | GET | `?limit=` | latest rows, newest first |
| `/health` | GET | — | liveness + live sandbox capability report |

`status` is exactly one of **`queued` → `running` → `completed` | `failed`**.
`/result/<id>` returns `409` until execution is finished, `404` for unknown
ids. Lifecycle:

```text
client ──POST /submit──▶ submission(id=queued) ──▶ SQLite (shared queue)
        ◀─201 + id──                         │
                                             ▼
                        worker pool (N processes, claim-next = atomic UPDATE
                        ... RETURNING)  ──▶ sandbox.run_code ──▶ result
                                             │
client ──GET /status/id──────────────▶ status  ▼
client ──GET /result/id──────────────▶ stdout/stderr/exit_code/wall_time
```

---

## The isolation model (defence in depth)

Each submission is executed as a **separate child process** (`subprocess`),
behind the following independent layers. Layers 1–3 are *cheap and language
specific*; layers 4–6 are the *real* process sandbox that applies to any
runtime.

### Layer 1 — Static pre-checks (`sandbox/prechecks.py`)
Before a submission is ever scheduled, its source text is scanned for
blocklist patterns (`os.system`, `subprocess`, `socket`, `eval(`, `open(`,
`__import__`, `getattr`, `fork`, `system(`, …). Matches are rejected with a
clear message. **This is a convenience filter, not a security boundary** —
string scanning is trivially obfuscatable.

### Layer 2 — Python runtime guard (`sandbox/runtime.py` → generated `runner.py`)
The child interpreter boots through a **bootstrap runner** that:
1. **Preloads a curated stdlib prefix** (`math`, `random`, `json`, `re`,
   `collections`, …). Because these load *before* the guard, their benign
   internal `import os` / `import sys` calls still work.
2. **Strips dangerous attributes** from the resident `os` module
   (`os.system`, `os.popen`, `os.fork`, `os.exec*`, `os.kill`, …) — so even a
   guard bypass can't reach the classic escape hatches.
3. **Installs a guarded `__import__`**: any *user* import whose root module
   is on a forbid-list (`os`, `subprocess`, `socket`, `sys`, `ctypes`,
   `pathlib`, `threading`, `multiprocessing`, `pickle`, `importlib`, …)
   raises `ImportError` **at runtime**, independent of source text.
4. **Shrinks builtins** to a minimal algorithmic subset — `open`, `eval`,
   `exec`, `getattr`, `dir`, `vars`, `compile`, `__import__` (exposed only as
   the guarded version) are simply not there.

The submission is executed with `exec(compile(...))` in a fresh namespace,
by an interpreter launched as `python -S -I -E -B` (no site, fully isolated,
no `.pyc`, no `PYTHON*` env influence).

### Layer 3 — C compile gates (`_compile_c`)
C is dangerous the other way: source is mostly safe until the *links* happen.
We compile every submission with
`gcc -std=c11 -Wall -Wextra -Werror -fno-builtin -fPIE -pie`. In C11 an
implicit function declaration is a **hard compile error**, so a submission
calling `system()`, `fork()`, `exec*()`, `socket()`, … fails at compile time
— the compiler is the authoritative static filter. The light text scan in
layer 1 just saves the compile cycle for obvious cases. (No compiler on
PATH → the submission degrades to a clean `failed` result, never a crash.)

### Layer 4 — Process jail (`sandbox/runtime.py → run_command`)
* **Fresh empty workdir**: every run creates a brand-new `tempfile.mkdtemp()`
  directory, chdirs into it, and deletes it afterwards. The submission has no
  window on the repo, the DB, or any sibling file.
* **Stripped environment**: the child gets `PATH`, `LANG`, `LC_ALL`,
  `TMPDIR` (and Windows system plumbing) — **nothing else**. Host secrets
  (API keys, config, CI tokens) simply don't exist in its `os.environ`.
* **Pipes, not temp files**: stdin/stdout/stderr travel through anonymous
  pipe descriptors; the child never holds a persistent file handle.
* **POSIX rlimits set in `preexec_fn`** (before `exec`, so inherited by the
  runtime and anything it could spawn):
  - `RLIMIT_CPU` — hard CPU-seconds budget (→ `SIGXCPU` on overrun);
  - `RLIMIT_AS` — hard address-space / memory cap in MB (→ `MemoryError`);
  - `RLIMIT_NPROC` — fork-bomb guard (no child processes);
  - `os.setsid()` — a fresh session/process group so grandchildren can be
    killed as a group.
  On `win32` `resource` doesn't exist, so these degrade gracefully to the
  watchdog (see Platform notes).

### Layer 5 — Wall-clock watchdog + process-tree kill
`run_command` blocks on `proc.communicate(stdin, timeout=…)`; on timeout it
kills **the whole process group** (`os.killpg(..., SIGKILL)`) or the process
on Windows, and reaps it. A **daemon watchdog thread** independently enforces
`deadline = now + timeout + 1s` and group-kills if the main thread is ever
wedged — for example on an uninterruptible syscall that swallows the Python
level timeout. A program that spins forever, forks a tree, or writes
unbounded output cannot outlive `wall_time ≤ timeout + ~1s`.

### Layer 6 — One submission, one process, one temporary world
Everything above composes into: **untrusted code runs once, in a fresh,
empty, secret-free directory, under hard CPU/memory/time caps, in a process
that is guaranteed to be killed and reaped.** Results are captured and
persisted; the scratch directory and pipes are destroyed.

---

## Concurrency & persistence

* **Worker pool** (`worker/pool.py`): `multiprocessing` `spawn` children
  (fresh interpreters; a crashed worker — segfault, native OOM — is isolated
  and **respawned** by a supervision loop). Each worker loops
  `claim → execute → store`. Max concurrency = `MAX_WORKERS`.
* **Atomic claims, exactly-once**: relying on SQLite as the shared work
  queue, `claim_next` is a single
  `UPDATE … WHERE id=(SELECT oldest queued …) RETURNING …` — two workers can
  never pick the same row (`codahale`s “take a lock by mutating state”).
* **Crash recovery**: `database.requeue_stuck()` marks `running` rows left
  by a dead pool back to `queued` at startup.
* **WAL mode**: readers (API) never block writers (workers); each call gets a
  short-lived connection.

---

## Project layout

```text
api/           Flask routes (submit/status/result/health), no logic of its own
sandbox/       THE isolation layer: prechecks.py, runtime.py, core.py
worker/        sync coordinator + multiprocessing pool (pool.py)
tests/         db tests, sandbox security suite, end-to-end API integration
examples/      3 safe + 4 malicious submissions, plus a self-contained demo
config.py      env/config.json overridable settings
database.py    SQLite access layer (schema, claims, results)
run.py         dev launcher (API + pool in one command)
submissions.db created at runtime (gitignored)
```

---

## Security test suite

```bash
python -m pytest -q
```

`tests/test_sandbox_security.py` is the security suite. Every attack below
has a passing test that proves the sandbox catches it **cleanly** (process
killed and reaped, submission marked completed/failed, host unaffected):

| Attack in the suite | Layer that catches it |
|---|---|
| Fork-bomb (`os.fork`, `multiprocessing`) | static scan + guarded import + `RLIMIT_NPROC` + kill-tree |
| Infinite loop | wall-clock watchdog (`timed_out=True`) |
| Busy-write that wedges the pipe | watchdog (not just Python timeout) |
| Read `/etc/passwd`, `os.walk('/')`, `shutil.copy`, `pathlib` | guarded import + `open` removed |
| Read project files (`config.py` beside the sandbox) | fresh isolated workdir |
| Env-var exfiltration | `clean_env()` stripping |
| `subprocess.run/Popen`, `os.system`, `os.popen`, `pty.spawn`, `ctypes.CDLL` | static scan + guarded import |
| ≥GB memory allocation | `RLIMIT_AS` → `MemoryError` (POSIX), watchdog bound (win32) |
| `__import__('os')`, `getattr(...,'system')`, `__builtins__` reach-arounds | guarded `__import__` + shrunk builtins |
| C `system("ls")` | static scan + `-Werror` implicit-declaration compile error |

`tests/test_api_integration.py` runs the full lifecycle over the real worker
pool + SQLite with Flask's test client (10 concurrent jobs → all complete).

---

## Honest limitations (read this — it's the interview part)

**This is a userspace process sandbox, not a container or VM.** Sequences
someone determined can still attempt:

1. **Native syscalls that rlimits don't tax.** `RLIMIT_CPU` counts CPU time but
   not, e.g., I/O-loops or `time.sleep`; a busy `open()` loop eats wall time,
   not CPU. The wall-clock watchdog bounds the *duration* but not the *work*.
2. **File access via allowed modules.** Whitelisted stdlib modules are real
   code; `import math` can't `open()`, but any bug in the python runtime or
   the guest /kernel/ can be exploited. We strip the headline primitives
   (`os.system`, …) but not every possible gadget.
3. **C is link-restricted, not syscall-restricted.** A C program that gets a
   libc `open`-equivalent via allowed headers (e.g. defining `_GNU_SOURCE`)
   is running with *unrestricted host privileges* for that child. Compile
   gates reject the obvious `system`/`fork`/`exec` calls but a C sandbox
   without `seccomp`/containers is **fundamentally weaker** than the Python
   one. (This is why real judge engines run C in containers.)
4. **No seccomp / landlock / resource container.** `setrlimit` is kernel
   authority but a single goal: **cap resources**, not *isolate filesystem*.
   It has no namespace isolation, so there is no true VFS containment.
5. **Shared kernel resources.** `/proc`, `/dev`, network stack, host signals,
   SysV IPC are not namespaced. A successful native-code exploitation in the
   child is host-exploitation.
6. **Statistical/algorithmic CPU bypass.** Programs can sleep (bounded by the
   watchdog) or interleave compute to stay under `RLIMIT_CPU` while
   dominating the wall clock — we bound *wall time* too, so worst case is
   `MAX_WORKERS × timeout` CPU-slot saturation, not infinite.
7. **Import guard is a defense, not a theorem.** `builtins` shrinking and
   guarded `__import__` stop the obvious and moderately clever paths; they
   are not a sound analysis of all Python metaprogramming.

**How a real judge engine would harden this same design:**

| Gap here | Industrial fix |
|---|---|
| rlimits only | `seccomp-bpf` allowlist of syscalls (Docker default profile) |
| filesystem via any syscall | `chroot`/`pivot_root` + `landlock`/`ns` (Docker, gVisor) |
| no kernel namespaces | run in a container: PID, mount, net, IPC, UTS namespaces |
| host network/SHM access | container network namespace + read-only rootfs |
| Python guard is heuristic-audit | PyPy subinterpreters, WASM, or co-located containers per language |
| single-machine verdict | multi-tenant judge clusters, egress egress blocking, per-run sandbox VMs |

If the threat model is "AI/CS students uploading random snippets", the above
is a strong, cheap, explainable baseline. If the threat model is "malicious
nation-state", you want **gVisor/Firecracker** between the code and the
kernel — nothing in this repo will substitute for that boundary.

### Platform notes
* The suite is written to pass **identically on Linux/macOS/Windows**: on
  win32, `resource` is unavailable, so `RLIMIT_*` and `setsid()` are skipped
  and enforcement degrades to (a) static scans, (b) the import guard, (c) the
  wall-clock watchdog — programs may allocate big virtual memory and are
  duration-bounded rather than size-bounded. See `examples/06_mem_alloc.py`.
* C execution requires `gcc`/`cc`/`clang` on `PATH` (Cython-style judges ship
  the toolchain in the image).

---

## Configuration cheat-sheet

| Key | Default | Meaning |
|---|---|---|
| `MAX_WORKERS` | `4` | concurrent executions |
| `TIMEOUT_SECONDS` | `2.0` | hard wall-clock cap per submission |
| `CPU_SECONDS` | `2.0` | `RLIMIT_CPU` budget |
| `MEM_MB` | `256` | `RLIMIT_AS` budget |
| `MAX_CODE_BYTES` | `1 MiB` | accepted source size |
| `MAX_RESULT_BYTES` | `4 MiB` | persisted stdout/stderr cap |
| `DB_PATH` | `./submissions.db` | SQLite location |
| `POLL_INTERVAL` | `0.2 s` | worker idle polling cadence |

## Testing gotchas
* Tests use a throwaway DB (via `DB_PATH` env + lazy `config`), never the
  real `submissions.db`.
* The suite spawns real subprocesses and a real worker pool (`spawn`), so it
  is intentionally ~20s. Run `pytest` serial (default) — the pool tests
  assume a fresh DB per module.