"""Direct children of a function, with inclusive counts, in a macOS `sample` call graph.

    sample_children.py <sample-file> <function>

Only the outermost call of a recursive function counts.
"""

import re
import sys
from collections import Counter

FRAME = re.compile(r"^(\s*)([+!:| ]*)(\d+) (.+?)\s+\(in ")
THREAD = re.compile(r"^\s+\d+ Thread_")

path, target = sys.argv[1], sys.argv[2]
with open(path) as stream:
    lines = stream.read().split("Call graph:")[1].split("Total number in stack")[0].splitlines()
children: Counter[str] = Counter()
stack: list[tuple[int, str]] = []
total = 0
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
    inside = [entry for entry in stack if entry[1] == target]
    if stack and stack[-1][1] == target and len(inside) == 1:
        children[name] += count
    if name == target and not inside:
        total += count
    stack.append((depth, name))
print("total", total)
for name, count in children.most_common(25):
    print(f"{count:7d} {name}")
