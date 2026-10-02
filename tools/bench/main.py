"""Command line: run the suite, check it against the baseline, or record one."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import platform
import subprocess
import sys
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler

from .baseline import BASELINE_PATH, Baseline
from .suite import REPO, Peak, Program, Suite, Workload


class BenchCommand:
    """One `python3 -m tools.bench` invocation: measure, check or record."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    @staticmethod
    def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(prog="python3 -m tools.bench", description=__doc__)
        sub = parser.add_subparsers(dest="command", required=True)

        def common(command: argparse.ArgumentParser) -> None:
            command.add_argument("--btrcc", default=str(REPO / "bin" / "btrcc"), help="self-hosted compiler binary")
            command.add_argument("--cc", default=" ".join(configured_c_compiler()), help="system C compiler command")
            command.add_argument("--repeat", type=int, default=5, help="samples per timing (best wins)")
            command.add_argument("--programs", help="comma-separated program stems (default: all)")
            command.add_argument("--json", help="write results to this path")
            command.add_argument("--out-dir", default=str(REPO / "build" / "bench"), help="scratch directory")
            command.add_argument("--no-reference", action="store_true", help="skip the in-process reference transpile")
            command.add_argument("--results", help="reuse results JSON from an earlier run instead of measuring")
            command.add_argument("--no-peaks", action="store_true", help="skip each program's compile peak memory")
            command.add_argument(
                "--peak-only", action="store_true", help="measure peak memory only: no timings, sizes or runs"
            )
            command.add_argument(
                "--peak-workload",
                action="append",
                metavar="WORKSPACE",
                help="also guard the cold --jobs 1 module-unit compile peak of this pinned workspace (repeatable)",
            )
            command.add_argument("--peak-entry", default="src/BTRSmith.btrc", help="workload entry, relative to it")
            command.add_argument("--peak-target", help="workload --target (default: this host's)")
            command.add_argument("--peak-samples", type=int, default=1, help="workload compiles per peak (lowest wins)")

        run = sub.add_parser("run", help="measure and print a table")
        common(run)
        check = sub.add_parser("check", help="measure, then fail on regressions against the tracked baseline")
        common(check)
        check.add_argument("--baseline", default=str(REPO / BASELINE_PATH))
        check.add_argument("--tolerance", type=float, help="relative slack for timings (default 0.35)")
        check.add_argument("--peak-tolerance", type=float, help="relative slack for peak memory (default 0.02)")
        check.add_argument("--strict", action="store_true", help="fail when this platform has no baseline")
        check.add_argument(
            "--timings",
            choices=("gate", "report"),
            default="gate",
            help="report: compare timings but fail only on sizes, lines, parity and peaks (a hosted runner pool)",
        )
        check.add_argument(
            "--peak-budget-gib",
            type=float,
            help="also fail when a workload's peak exceeds this many GiB (the M11 budget is 3), baseline or not",
        )
        record = sub.add_parser("baseline", help="measure and record this platform's baseline")
        common(record)
        record.add_argument("--baseline", default=str(REPO / BASELINE_PATH))
        record.add_argument("--merge", action="store_true", help="keep this platform's metrics the run did not measure")
        return parser.parse_args(argv)

    def workloads(self) -> list[Workload]:
        target = self.args.peak_target or Workload.host_target()
        return [Workload(Path(path).resolve(), self.args.peak_entry, target) for path in self.args.peak_workload or []]

    def meta(self) -> dict:
        args = self.args
        revision = subprocess.run(
            ["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        return {
            "platform": Baseline.platform_key(),
            "machine": platform.platform(),
            "btrcc": str(args.btrcc),
            "cc": args.cc,
            "repeat": args.repeat,
            "peak_counter": Peak.counter(),
            "peak_workloads": [
                {"workspace": str(workload.workspace), "entry": workload.entry, "target": workload.target}
                for workload in self.workloads()
            ],
            "revision": revision,
            "recorded_at": _datetime.datetime.now(_datetime.UTC).replace(microsecond=0).isoformat(),
        }

    def measure(self) -> tuple[dict[str, float], dict]:
        args = self.args
        programs = Program.discover(args.programs.split(",") if args.programs else None)
        suite = Suite(
            btrcc=Path(args.btrcc).resolve(),
            cc=args.cc.split(),
            repeat=args.repeat,
            out_dir=Path(args.out_dir).resolve(),
            reference=not args.no_reference,
            peaks=not args.no_peaks,
            peak_only=args.peak_only,
            workloads=self.workloads(),
            workload_samples=args.peak_samples,
        )
        metrics = suite.run(programs)
        meta = self.meta()
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"meta": meta, "metrics": metrics}, indent=2) + "\n", encoding="utf-8")
        for note in suite.notes:
            print(f"note: {note}", file=sys.stderr)
        return metrics, meta

    @staticmethod
    def load_results(path: str) -> tuple[dict[str, float], dict]:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return document["metrics"], document["meta"]

    @staticmethod
    def table(metrics: dict[str, float]) -> str:
        width = max(len(name) for name in metrics)
        return "\n".join(f"{name:<{width}}  {Baseline.number(value):>12}" for name, value in sorted(metrics.items()))

    def execute(self) -> int:
        args = self.args

        metrics, meta = self.load_results(args.results) if args.results else self.measure()
        if args.command == "run":
            print(self.table(metrics))
            return 0
        key = meta["platform"]
        path = Path(args.baseline)
        document = Baseline.load(path)
        if args.command == "baseline":
            Baseline.store(document, key, metrics, meta, path, merge=args.merge)
            print(f"recorded {len(metrics)} metrics for {key} in {path}")
            return 0
        recorded = Baseline.platform_metrics(document, key)
        findings = Baseline.compare(
            metrics, recorded, args.tolerance, args.peak_tolerance, gate_timings=args.timings == "gate"
        )
        print(Baseline.render(findings))
        regressions = [finding for finding in findings if finding.status == "regression"]
        lower = [f.name for f in findings if f.status == "improvement" and Baseline.metric_kind(f.name) == "peak"]
        if lower:
            print(
                f"\npeak memory fell past its slack ({', '.join(lower)}); record it again with "
                "`baseline --merge --peak-only` so the guard stays tight",
                file=sys.stderr,
            )
        over = Baseline.over_budget(metrics, args.peak_budget_gib)
        for name in over:
            print(
                f"\n{name} is {metrics[name] / 2**30:.3f} GiB, over its {args.peak_budget_gib:g} GiB budget",
                file=sys.stderr,
            )
        if recorded is None:
            print(f"\nno baseline for {key}; record one with `make bench-baseline`", file=sys.stderr)
            return 1 if args.strict or over else 0
        slower = [finding for finding in findings if finding.status == "slower"]
        if slower:
            print(f"\n{len(slower)} timing(s) past their slack, reported only (--timings report)", file=sys.stderr)
        if regressions:
            print(f"\n{len(regressions)} regression(s) against the {key} baseline", file=sys.stderr)
        if regressions or over:
            return 1
        print(f"\nno regressions against the {key} baseline ({len(findings)} metrics)")
        return 0


def main(argv: list[str] | None = None) -> int:
    return BenchCommand(BenchCommand.parse_arguments(argv)).execute()
