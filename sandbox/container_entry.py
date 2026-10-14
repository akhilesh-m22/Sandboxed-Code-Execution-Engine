"""Trusted container entrypoint: one request, one bounded result, then exit."""
import json
import math
import signal
import sys

from sandbox.runtime import _run_process


def main():
    signal.alarm(30)  # Includes incomplete stdin if the attaching worker dies.
    request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024))
    # Independent lifetime bound if the worker or attached Docker client dies.
    signal.alarm(math.ceil(request["timeout"]) + 15)
    result = _run_process(
        request["language"], request["source"], request["stdin"].encode(),
        request["timeout"], request["cpu_seconds"], request["mem_mb"], request["max_output_bytes"],
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
