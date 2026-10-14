# Five-minute interview demo

Start with `python run.py`, then open http://127.0.0.1:5000.

1. **Run a real program.** Select Two Sum and click **Submit All**. Three different inputs produce three independently persisted execution results. Explain the source editor, stdin, expected-output comparison and measured wall time.
2. **Show failure handling.** Choose Freeform Sandbox and run `1 / 0`. Open Stderr and Diagnostics. The engine stays responsive; one program failing does not stop the worker pool.
3. **Show a bounded workload.** Choose Runaway Infinite Loop and run it. The wall-clock deadline terminates execution. These are demonstration cases, not proof of a complete security boundary.
4. **Explain the architecture.** The browser sends JSON to Flask/Waitress. SQLite persists the job, a worker atomically claims it, and a fresh child executes it. The browser polls the result. The API process never evaluates submitted source.
5. **Explain reliability.** Open History and Sandbox. Discuss output caps, atomic queue capacity, worker heartbeats, stale-lease recovery, ownership-checked writes, and retention. Run `python scripts/smoke.py` in a second terminal to demonstrate the API independently of the frontend.
6. **Explain the deployment boundary honestly.** Local process mode is for trusted code. Docker mode gives each submission a non-root container, isolated network, read-only filesystem and resource caps. Production refuses to start without Docker mode and an API token. Docker shares the host kernel; stronger hostile multi-tenant workloads need another boundary such as gVisor or microVMs.

## Questions worth being ready for

**Why SQLite?** Simple durable single-host deployment, transactional queue capacity and claims, no Redis dependency. It is a deliberate single-host tradeoff; use a broker plus a server database for a distributed deployment. WAL needs local storage, not a shared network filesystem.

**Is execution exactly once?** No. Claims are exclusive while leases are valid. A crashed or partitioned worker may execute again after lease recovery; the result write is accepted only from the current owner. The design is at-least-once and programs should have no external side effects.

**Do Python filters make execution safe?** No. They reduce obvious misuse, but neither string filters nor reduced builtins are a security boundary. C compiler warnings also do not prevent arbitrary syscalls. Docker provides the optional OS isolation layer.

**How is output bounded?** Two pipe readers share a byte budget. Once stdout plus stderr exceeds that budget, the supervisor kills the process tree and retains a bounded diagnostic. Truncating only after `communicate()` would leave the worker exposed to memory exhaustion.

**What would you build next?** Per-user authentication and ownership, fair scheduling, per-user quotas, distributed workers, container image digests and scanning, stronger syscall policy, and separately measured peak memory. Do not claim these are already implemented.
