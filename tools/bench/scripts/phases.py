"""Summarize BTRC_TIMING lines: each process's summed phases and its 25 largest.

    phases.py <timing-file>...

Reads budget_bench's timing/*.txt (kept for incremental builds, and for cold
builds with --timing-cold), gen_units.sh's timing.txt or edit_instr.py's
*.timing; one block per owner or worker line. budget_bench's report.json
carries the same lines parsed, with each line's role.
"""

import re
import sys

for path in sys.argv[1:]:
    with open(path) as stream:
        text = stream.read()
    for line in text.splitlines():
        if "timing:" not in line:
            continue
        head = line.split("timing:")[0]
        totals: dict[str, int] = {}
        for name, value in re.findall(r"(\S+?)=(\d+)us", line):
            totals[name] = totals.get(name, 0) + int(value)
        top = sorted(totals.items(), key=lambda item: -item[1])[:25]
        print(path.split("/")[-1], head.strip(), f"sum={sum(totals.values()) / 1e6:.2f}s")
        print("  " + " ".join(f"{name}={value / 1e6:.2f}" for name, value in top))
