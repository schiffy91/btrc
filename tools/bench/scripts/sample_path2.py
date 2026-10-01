"""Direct children of <target> beneath one <parent>-><child> edge of a macOS `sample` call graph.

sample_path2.py <sample-file> <parent> <child> <target>
"""

import re
import sys
from collections import Counter

FRAME = re.compile(r"^(\s*)([+!:| ]*)(\d+) (.+?)\s+\(in ")
THREAD = re.compile(r"^\s+\d+ Thread_")

path, parent, child, target = sys.argv[1:5]
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
    names = [entry[1] for entry in stack]
    inside = any(names[index] == parent and names[index + 1] == child for index in range(len(names) - 1))
    if inside and names and names[-1] == target and names.count(target) == 1:
        children[name] += count
    if inside and name == target and target not in names:
        total += count
    stack.append((depth, name))
print("total", total)
for name, count in children.most_common(20):
    print(f"{count:7d} {name}")
