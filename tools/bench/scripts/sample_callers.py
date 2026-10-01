"""Caller chains of a function in a macOS `sample` call graph, by sample count.

    sample_callers.py <sample-file> <function> [levels=1]

Recursive frames count once, at their outermost call.
"""

import re
import sys
from collections import Counter

FRAME = re.compile(r"^(\s*)([+!:| ]*)(\d+) (.+?)\s+\(in ")
THREAD = re.compile(r"^\s+\d+ Thread_")

path, target = sys.argv[1], sys.argv[2]
levels = int(sys.argv[3]) if len(sys.argv) > 3 else 1
with open(path) as stream:
    lines = stream.read().split("Call graph:")[1].split("Total number in stack")[0].splitlines()
callers: Counter[str] = Counter()
stack: list[tuple[int, str]] = []
for line in lines:
    if THREAD.match(line):
        stack = []
        continue
    frame = FRAME.match(line)
    if not frame:
        continue
    depth = len(frame.group(1)) + len(frame.group(2))
    count = int(frame.group(3))
    name = frame.group(4).strip()
    while stack and stack[-1][0] >= depth:
        stack.pop()
    if name == target and not any(entry[1] == target for entry in stack):
        callers[" <- ".join(entry[1] for entry in stack[-levels:][::-1])] += count
    stack.append((depth, name))
for chain, count in callers.most_common(25):
    print(f"{count:7d} {chain}")
