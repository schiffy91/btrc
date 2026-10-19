"""A GitHub step summary from target runs: ``python3 -m tools.target_hosts.summary <target-run.json>...``.

Each ``target-run.json`` (schema ``btrc.target-run/1``, written by
``src/tests/target_runner.py``) becomes a Markdown section: the per-frontend
passed/failed/restricted/missing counts, every failure with its phase and the
first line of its reason, and the restricted and missing programs grouped by
reason. A compile-only run says so: there, passed means built.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

STATUSES = ("passed", "failed", "restricted", "missing")


class TargetRunSummary:
    """One target run's Markdown section."""

    REASON_WIDTH = 200

    def __init__(self, report: Mapping[str, Any]) -> None:
        self.report = report

    @classmethod
    def load(cls, path: Path) -> TargetRunSummary:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def cell(cls, text: object) -> str:
        line = next(iter(str(text or "").splitlines()), "")
        return line[: cls.REASON_WIDTH].replace("|", "\\|")

    def heading(self) -> str:
        label = self.report["target"]["label"]
        if self.report.get("mode") == "compile-only":
            return f"### {label}: the corpus built, never run (compile-only: passed means built)"
        device = (self.report.get("executor_provenance") or {}).get("device", "an unrecorded device")
        return f"### {label}: the corpus on {device} ({self.report.get('executor')})"

    def lines(self) -> list[str]:
        lines = [self.heading(), "", "| frontend | " + " | ".join(STATUSES) + " |", "| --- |" + " ---: |" * 4]
        for frontend, counts in self.report["counts"].items():
            lines.append(f"| {frontend} | " + " | ".join(str(counts[status]) for status in STATUSES) + " |")
        results = self.report.get("results", ())
        failed = [result for result in results if result["status"] == "failed"]
        if failed:
            lines += ["", "| frontend | failed program | phase | reason |", "| --- | --- | --- | --- |"]
            lines += [
                f"| {result['frontend']} | {result['program']} | {result.get('phase')} | {self.cell(result.get('reason'))} |"
                for result in failed
            ]
        excluded = Counter(
            (result["status"], self.cell(result.get("reason")), result.get("cites"))
            for result in results
            if result["status"] in ("restricted", "missing")
        )
        if excluded:
            lines += ["", "| status | programs | reason | cites |", "| --- | ---: | --- | --- |"]
            lines += [
                f"| {status} | {count} | {reason} | {cites} |"
                for (status, reason, cites), count in sorted(excluded.items(), key=lambda item: (-item[1], item[0]))
            ]
        return [*lines, ""]


def main(argv: Sequence[str] | None = None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print("usage: python3 -m tools.target_hosts.summary <target-run.json>...", file=sys.stderr)
        return 2
    for path in paths:
        print("\n".join(TargetRunSummary.load(Path(path)).lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
