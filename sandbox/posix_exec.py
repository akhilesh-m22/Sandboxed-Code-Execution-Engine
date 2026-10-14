"""Set resource limits before exec without preexec_fn in a threaded worker."""

import math
import os
import resource
import sys


def main():
    cpu_seconds, mem_mb = float(sys.argv[1]), int(sys.argv[2])
    cpu = max(1, math.ceil(cpu_seconds))
    memory = mem_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    os.execvpe(sys.argv[3], sys.argv[3:], os.environ)


if __name__ == "__main__":
    main()
