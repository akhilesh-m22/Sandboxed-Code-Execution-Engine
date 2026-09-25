# examples/04_fork_bomb.py
# MALICIOUS: fork as fast as possible. Should never escape the sandbox.
#
# Defense stack that stops it:
#   1. static pre-check: "os" + "fork" are both in the blocklist -> rejected
#      before it even reaches a worker (http://localhost:5000/submit returns
#      a submission with stderr "static pre-check flagged...").
#   2. even if written around (e.g. 'getattr(..., "fork")'), the runtime
#      guarded-import blocks `import os`, and RLIMIT_NPROC/RLIMIT_CPU and the
#      wall-clock watchdog terminate the tree.
import os

while True:
    os.fork()