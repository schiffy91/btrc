"""Inclusive counts beneath one caller->callee edge of a macOS `sample` call graph.

    sample_path.py <sample-file> <parent> <child> [limit=40]

Reports the functions (inclusive, once per stack) beneath <child> frames whose
direct parent is <parent>.
"""

import re
import sys
from collections import Counter

FRAME = re.compile(r"^(\s*)([+!:| ]*)(\d+) (.+?)\s+\(in ")
THREAD = re.compile(r"^\s+\d+ Thread_")

path, parent, child = sys.argv[1], sys.argv[2], sys.argv[3]
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 40
with open(path) as stream:
    lines = stream.read().split("Call graph:")[1].split("Total number in stack")[0].splitlines()
inclusive: Counter[str] = Counter()
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
    names = [entry[1] for entry in stack]
    inside = any(names[index] == parent and names[index + 1] == child for index in range(len(names) - 1))
    if not inside and name == child and names and names[-1] == parent:
        total += count
    if inside and name not in names[names.index(child) :]:
        inclusive[name] += count
    stack.append((depth, name))
print("total", total)
for name, count in inclusive.most_common(limit):
    print(f"{count:7d} {name}")
