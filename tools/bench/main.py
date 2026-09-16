"""Command line: run the suite, check it against the baseline, or record one."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import platform
import subprocess
import sys
from pathlib import Path

from . import baseline as _baseline
from .suite import REPO, Suite, default_cc, discover


def _meta(args: argparse.Namespace) -> dict:
    revision = subprocess.run(
        ["git", "-c", "safe.directory=*", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    return {
        "platform": _baseline.platform_key(),
        "machine": platform.platform(),
        "btrcc": str(args.btrcc),
        "cc": args.cc,
        "repeat": args.repeat,
        "revision": revision,
        "recorded_at": _datetime.datetime.now(_datetime.UTC).replace(microsecond=0).isoformat(),
    }


def _run(args: argparse.Namespace) -> tuple[dict[str, float], dict]:
    programs = discover(args.programs.split(",") if args.programs else None)
    suite = Suite(
        btrcc=Path(args.btrcc).resolve(),
        cc=args.cc.split(),
        repeat=args.repeat,
        out_dir=Path(args.out_dir).resolve(),
        reference=not args.no_reference,
    )
    metrics = suite.run(programs)
    meta = _meta(args)
    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"meta": meta, "metrics": metrics}, indent=2) + "\n", encoding="utf-8")
    for note in suite.notes:
        print(f"note: {note}", file=sys.stderr)
    return metrics, meta


def _load_results(path: str) -> tuple[dict[str, float], dict]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return document["metrics"], document["meta"]


def _table(metrics: dict[str, float]) -> str:
    width = max(len(name) for name in metrics)
    return "\n".join(f"{name:<{width}}  {_baseline._number(value):>12}" for name, value in sorted(metrics.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m tools.bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--btrcc", default=str(REPO / "bin" / "btrcc"), help="self-hosted compiler binary")
        command.add_argument("--cc", default=" ".join(default_cc()), help="system C compiler command")
        command.add_argument("--repeat", type=int, default=5, help="samples per timing (best wins)")
        command.add_argument("--programs", help="comma-separated program stems (default: all)")
        command.add_argument("--json", help="write results to this path")
        command.add_argument("--out-dir", default=str(REPO / "build" / "bench"), help="scratch directory")
        command.add_argument("--no-reference", action="store_true", help="skip the in-process reference transpile")
        command.add_argument("--results", help="reuse results JSON from an earlier run instead of measuring")

    run = sub.add_parser("run", help="measure and print a table")
    common(run)
    check = sub.add_parser("check", help="measure, then fail on regressions against the tracked baseline")
    common(check)
    check.add_argument("--baseline", default=str(REPO / _baseline.BASELINE_PATH))
    check.add_argument("--tolerance", type=float, help="relative slack for timings (default 0.35)")
    check.add_argument("--strict", action="store_true", help="fail when this platform has no baseline")
    record = sub.add_parser("baseline", help="measure and record this platform's baseline")
    common(record)
    record.add_argument("--baseline", default=str(REPO / _baseline.BASELINE_PATH))
    args = parser.parse_args(argv)

    metrics, meta = _load_results(args.results) if args.results else _run(args)
    if args.command == "run":
        print(_table(metrics))
        return 0
    key = meta["platform"]
    path = Path(args.baseline)
    document = _baseline.load(path)
    if args.command == "baseline":
        _baseline.store(document, key, metrics, meta, path)
        print(f"recorded {len(metrics)} metrics for {key} in {path}")
        return 0
    recorded = _baseline.platform_metrics(document, key)
    findings = _baseline.compare(metrics, recorded, args.tolerance)
    print(_baseline.render(findings))
    regressions = [finding for finding in findings if finding.status == "regression"]
    if recorded is None:
        print(f"\nno baseline for {key}; record one with `make bench-baseline`", file=sys.stderr)
        return 1 if args.strict else 0
    if regressions:
        print(f"\n{len(regressions)} regression(s) against the {key} baseline", file=sys.stderr)
        return 1
    print(f"\nno regressions against the {key} baseline ({len(findings)} metrics)")
    return 0
