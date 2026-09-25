# examples/05_steal_env.py
# MALICIOUS: try to exfiltrate the host's environment variables.
#
# What happens:
#   1. static pre-check flags "import os"? Actually `import os` is NOT on the
#      word-blocklist -- it gets through the cheap filter by design.
#   2. The runtime guarded-__import__ raises
#      `ImportError: import 'os' is forbidden in the sandbox`.
#   3. And even if that guard were bypassed, the child's environment has
#      been stripped by run_command(env=clean_env()), so there is nothing
#      secret to steal.
import os

print(os.environ)