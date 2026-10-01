"""Compare two module-unit outputs by unit stem, ignoring paths and path hashes.

    cmp_units.py <tag-or-directory> <tag-or-directory>

A tag names edit_instr.py's ~/.cache/btrc/perf/ei-<tag>; a directory is any
output holding out/ (gen_units.sh's, for one). Two compilers that should emit
the same program list no differing units.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
from pathlib import Path

PERF = Path(os.environ.get("BTRC_BENCH_HOME", Path.home() / ".cache/btrc")) / "perf"


def load(argument: str) -> dict[str, list[str]]:
    root = Path(argument) if Path(argument).is_dir() else PERF / f"ei-{argument}"
    units: dict[str, list[str]] = {}
    for path in (root / "out").iterdir():
        if not path.name.endswith((".c", ".json")):
            continue
        stem = re.sub(r"-[0-9a-f]{12}\.c$", ".c", path.name)
        text = path.read_text().replace(str(root), "<run>")
        text = re.sub(r"p\.unit-([A-Za-z0-9]+)-[0-9a-f]{12}", r"p.unit-\1-H", text)
        text = re.sub(r"BTRC_INCLUDE_[0-9A-F]{16}", "BTRC_INCLUDE_H", text)
        units.setdefault(stem, []).append(text)
    return units


def main() -> None:
    first, second = load(sys.argv[1]), load(sys.argv[2])
    print("units", len(first), len(second), "name differences", set(first) ^ set(second))
    differing = [stem for stem in first if sorted(first[stem]) != sorted(second.get(stem, []))]
    print("differing", len(differing), differing[:10])
    for stem in differing[:2]:
        before = sorted(first[stem])[0].splitlines()
        after = sorted(second.get(stem, [""]))[0].splitlines()
        print("\n".join(list(difflib.unified_diff(before, after, lineterm="", n=1))[:30]))


if __name__ == "__main__":
    main()
