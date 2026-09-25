# examples/07_infinite_loop.py
# MALICIOUS: busy-wait. The wall-clock watchdog must kill the process (~2s)
# and report timed_out=True with a non-zero exit code.
while True:
    pass