"""Inclusive and self sample counts per function from a macOS `sample` call graph.

    sample_top.py <sample-file> [limit=60] [thread-filter=main-thread]

Only threads whose header line contains the filter count. The sample_*.py
family reads the call graphs edit_instr.py --sample writes.
"""

import re
import sys
from collections import Counter

FRAME = re.compile(r"^(\s*)([+!:| ]*)(\d+) (.+?)\s+\(in ")
THREAD = re.compile(r"^\s+(\d+) Thread_\d+(.*)$")

path = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
thread_filter = sys.argv[3] if len(sys.argv) > 3 else "main-thread"
with open(path) as stream:
    lines = stream.read().split("Call graph:")[1].split("Total number in stack")[0].splitlines()
inclusive: Counter[str] = Counter()
self_counts: Counter[str] = Counter()
stack: list[list] = []  # [depth, name, count, children's count]
in_thread = False
total = 0
for line in lines:
    thread = THREAD.match(line)
    if thread:
        while stack:
            _, name, count, children = stack.pop()
            self_counts[name] += count - children
        in_thread = thread_filter in line
        if in_thread:
            total += int(thread.group(1))
        continue
    frame = FRAME.match(line)
    if not in_thread or not frame:
        continue
    depth = len(frame.group(1)) + len(frame.group(2))
    count = int(frame.group(3))
    name = frame.group(4).strip()
    while stack and stack[-1][0] >= depth:
        _, popped, popped_count, children = stack.pop()
        self_counts[popped] += popped_count - children
    if stack:
        stack[-1][3] += count
    if name not in {entry[1] for entry in stack}:
        inclusive[name] += count
    stack.append([depth, name, count, 0])
while stack:
    _, name, count, children = stack.pop()
    self_counts[name] += count - children
print("total", total)
print("-- inclusive")
for name, count in inclusive.most_common(limit):
    print(f"{count:7d} {100 * count / total:5.1f}% {name}")
print("-- self")
for name, count in self_counts.most_common(40):
    print(f"{count:7d} {100 * count / total:5.1f}% {name}")
