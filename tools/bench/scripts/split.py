"""Rebuild one combined diff as a stack of reviewed commits on a tree's HEAD.

    split.py <tree> <full.diff> <plan.json> [--patches <dir>]

The plan lists each commit's hunks by index (in the diff's file-then-hunk
order), title and body. Every hunk belongs to exactly one commit except those
of `generated_paths`, which are regenerated with `regenerate_command` after
the commits named in `regenerate_after`; `trailer` ends every message.
Commits are unsigned, as the agent rules require. split-m12.json is the plan
that built the M12 stack; each commit's patch is kept in --patches (default:
beside the diff).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def hunks(diff: str) -> list[tuple[str, str, str]]:
    """(file, file header, hunk) for every hunk, in order."""
    result = []
    for section in re.split(r"(?m)^(?=diff --git )", diff):
        if not section.strip():
            continue
        header, *parts = re.split(r"(?m)^(?=@@ )", section)
        match = re.search(r"^diff --git a/(\S+)", header)
        if match is None:
            sys.exit(f"unparsable diff section: {header[:200]!r}")
        result.extend((match.group(1), header, part) for part in parts)
    return result


def run(tree: Path, *command: str) -> str:
    completed = subprocess.run(command, cwd=tree, capture_output=True, text=True, timeout=1800)
    if completed.returncode:
        sys.exit(f"{command}: {completed.stdout}{completed.stderr}")
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tree", type=Path)
    parser.add_argument("diff", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--patches", type=Path)
    options = parser.parse_args()
    plan = json.loads(options.plan.read_text())
    every = hunks(options.diff.read_text())
    generated = set(plan.get("generated_paths", []))
    used = sorted(index for commit in plan["commits"] for index in commit["hunks"])
    regenerated = [index for index, (name, _, _) in enumerate(every) if name in generated]
    if sorted(used + regenerated) != list(range(len(every))):
        sys.exit(f"the plan must use every hunk once: missing {set(range(len(every))) - set(used) - set(regenerated)}")
    patches = options.patches or options.diff.parent
    patches.mkdir(parents=True, exist_ok=True)
    trailer = plan.get("trailer", "")
    for number, commit in enumerate(plan["commits"]):
        by_file: dict[str, list[str]] = {}
        for index in commit["hunks"]:
            name, header, hunk = every[index]
            by_file.setdefault(name, [header]).append(hunk)
        patch = patches / f"c{number:02d}.patch"
        patch.write_text("".join("".join(parts) for parts in by_file.values()))
        run(options.tree, "git", "apply", "--whitespace=nowarn", str(patch))
        if number in plan.get("regenerate_after", []):
            run(options.tree, *plan["regenerate_command"])
        run(options.tree, "git", "add", "-A")
        message = f"{commit['title']}\n\n{commit['body']}" + (f"\n\n{trailer}\n" if trailer else "\n")
        run(options.tree, "git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
        print("committed", number, commit["title"], flush=True)


if __name__ == "__main__":
    main()
