# examples/02_stdin_sort.py
# SAFE submission: reads numbers from stdin, prints them sorted ascending.
# (`sys` is banned in the sandbox; `input()` is the sanctioned stdin path.)
ints = [int(x) for x in input().split()]
print(*sorted(ints))