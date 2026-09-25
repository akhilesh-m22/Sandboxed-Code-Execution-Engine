# examples/06_mem_alloc.py
# MALICIOUS: attempt a 1 GB allocation.
#
# Expected behaviour differs by platform (see README "Platform notes"):
#   * POSIX: RLIMIT_AS caps the address space -> MemoryError, exit_code != 0.
#   * win32: a 1 GB commit is legal, so it may SUCCEED -- the sandbox cannot
#     hard-limit per-process memory with the stdlib there, and the honest
#     mitigation is the wall-clock watchdog bounding total burn time.
# Either way the submission is finished in wall_time seconds, never forever.
x = bytearray(1024 * 1024 * 1024 + 1)
print(len(x))