"""``python3 -m tools.qualification``: ingest evidence, render the report, gate skips.

report        render the support/coverage report from raw inputs and ledgers;
              with --denominators, fail when a frozen inventory slot is missing
ingest        copy raw inputs under the qualification root and write a ledger
denominators  check the frozen inventory denominators against their sources
skip-gate     fail on a skip the runner's expected-skip manifest does not explain
skip-coverage compare skip reports: shard partitions and covered_by claims
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from tools.qualification.adapters import (
    RUNNER_PLATFORMS,
    BoundaryReportAdapter,
    BudgetBenchAdapter,
    HostProvenance,
    JUnitAdapter,
    SkipReportAdapter,
)
from tools.qualification.denominators import MANIFEST as DENOMINATORS
from tools.qualification.denominators import DenominatorManifest
from tools.qualification.report import QualificationReport
from tools.qualification.schema import (
    Budget,
    Frontend,
    LedgerDocument,
    LedgerRecord,
    LedgerSchemaError,
    Platform,
    Provenance,
)
from tools.qualification.skips import (
    MANIFEST_ROOT,
    RunnerIdentity,
    SkipCoverage,
    SkipGate,
    SkipLedgerError,
    SkipReport,
)
from tools.qualification.statistics import Statistic
from tools.qualification.store import QualificationStore, QualificationStoreError

_STATISTICS = "|".join(re.escape(statistic.value) for statistic in sorted(Statistic, key=len, reverse=True))
_BUDGET = re.compile(rf"^(?P<scenario>[a-z0-9-]+):(?P<statistic>{_STATISTICS})<=(?P<limit>\d+(?:\.\d+)?)$")
_BUDGET_FORM = f"SCENARIO:{'|'.join(statistic.value for statistic in Statistic)}<=LIMIT"
_PROVENANCE_OPTIONS = tuple(name for name in Provenance.TEXT_FIELDS if name != "source")


class QualificationCommand:
    """Parse one command line and run it against a store."""

    def __init__(self, store: QualificationStore | None = None, host: HostProvenance | None = None) -> None:
        self.store = store
        self.host = host or HostProvenance()

    def parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="python3 -m tools.qualification", description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        for name in ("report", "ingest"):
            command = commands.add_parser(name)
            command.add_argument("--budget-bench", type=Path, action="append", default=[], help="budget_bench report")
            command.add_argument("--junit", type=Path, action="append", default=[], help="pytest --junitxml output")
            command.add_argument("--skip-report", type=Path, action="append", default=[], help="a gate's skip report")
            command.add_argument("--boundary-report", type=Path, action="append", default=[])
            command.add_argument("--platform", choices=[platform.value for platform in Platform])
            command.add_argument("--variant", help="artifact variant of bench and JUnit slots: arm64-simulator, ...")
            command.add_argument("--budget", action="append", default=[], help=_BUDGET_FORM)
            command.add_argument("--root", help="qualification root (default ~/.cache/btrc/qualification)")
            command.add_argument(
                "--this-host",
                action="store_true",
                help="the inputs were just produced here: detect runner, OS build, device class, thermal and power",
            )
            command.add_argument("--frontend", choices=[frontend.value for frontend in Frontend])
            for option in _PROVENANCE_OPTIONS:
                command.add_argument(f"--{option.replace('_', '-')}", dest=option)
            if name == "report":
                command.add_argument("--ledger", type=Path, action="append", default=[], help=".jsonl/.json/.toml")
                command.add_argument("--all-ledgers", action="store_true", help="every ledger under the root")
                command.add_argument("--format", choices=("markdown", "json"), default="markdown")
                command.add_argument("--output", type=Path)
                command.add_argument(
                    "--denominators",
                    type=Path,
                    nargs="?",
                    const=DENOMINATORS,
                    help="count against frozen inventory denominators (default: the tracked manifest)",
                )
            else:
                command.add_argument("--run", help="run id (default: a UTC timestamp)")
        frozen = commands.add_parser("denominators")
        frozen.add_argument("--manifest", type=Path, default=DENOMINATORS)
        gate = commands.add_parser("skip-gate")
        gate.add_argument("reports", type=Path, nargs="+")
        gate.add_argument("--runner", help="classify as this runner instead of the one each report names")
        gate.add_argument("--manifests", type=Path, default=MANIFEST_ROOT)
        gate.add_argument("--list", action="store_true", help="list every skipped test with its coverage")
        coverage = commands.add_parser("skip-coverage")
        coverage.add_argument("--whole", type=Path, nargs="*", default=[], help="reports of the whole gate")
        coverage.add_argument("--shards", type=Path, nargs="*", default=[], help="reports of its shards")
        coverage.add_argument("--claims", type=Path, nargs="*", default=[], help="reports whose covered_by to check")
        return parser

    def run(self, argv: list[str] | None = None) -> int:
        arguments = self.parser().parse_args(argv)
        try:
            if arguments.command == "skip-gate":
                return self.skip_gate(arguments)
            if arguments.command == "skip-coverage":
                return self.skip_coverage(arguments)
            if arguments.command == "denominators":
                return self.check_denominators(arguments.manifest)
            records = self.records(arguments)
            if arguments.command == "ingest":
                return self.ingest(arguments, records)
            return self.report(arguments, records)
        except (LedgerSchemaError, SkipLedgerError, QualificationStoreError, OSError, json.JSONDecodeError) as error:
            print(f"qualification: {error}", file=sys.stderr)
            return 2

    def store_for(self, arguments: argparse.Namespace) -> QualificationStore:
        if self.store is None:
            self.store = QualificationStore(QualificationStore.resolve_root(arguments.root))
        return self.store

    def records(self, arguments: argparse.Namespace) -> list[LedgerRecord]:
        explicit = Provenance(
            frontend=Frontend(arguments.frontend) if arguments.frontend else None,
            **{option: value for option in _PROVENANCE_OPTIONS if (value := getattr(arguments, option)) is not None},
        )
        # Evidence produced elsewhere or earlier says nothing about this machine,
        # so only --this-host detects; explicit flags override what it finds.
        detected = self.host.detect(runner=RunnerIdentity.detect()) if arguments.this_host else Provenance()
        provenance = detected.overlay(explicit)
        given_platform = Platform(arguments.platform) if arguments.platform else None
        platform = given_platform or RUNNER_PLATFORMS.get(provenance.runner or "")
        run = getattr(arguments, "run", None) or datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        if arguments.command == "ingest":
            arguments.run = run
        records: list[LedgerRecord] = []
        for path in getattr(arguments, "ledger", []):
            records += LedgerDocument.load(path)
        if getattr(arguments, "all_ledgers", False):
            for path in self.store_for(arguments).ledgers():
                records += LedgerDocument.load(path)
        budgets = self.budgets(arguments.budget)
        for path in arguments.budget_bench:
            adapter = BudgetBenchAdapter(
                detected,
                explicit=explicit,
                platform=given_platform,
                variant=arguments.variant,
                budgets=budgets,
                artifact=self.artifact(arguments, run, path),
                recorded_at=self.modified(path),
            )
            records += adapter.records(json.loads(path.read_text(encoding="utf-8")), str(path))
        for path in arguments.junit:
            adapter = JUnitAdapter(provenance, platform=platform, variant=arguments.variant)
            records += adapter.records(path, self.artifact(arguments, run, path))
        for path in arguments.skip_report:
            report = SkipReport.load(path)
            records += SkipReportAdapter(provenance).records(report, self.artifact(arguments, run, path))
        for path in arguments.boundary_report:
            report = json.loads(path.read_text(encoding="utf-8"))
            adapter = BoundaryReportAdapter(provenance, platform=platform)
            records += adapter.records(report, self.artifact(arguments, run, path))
        return records

    @staticmethod
    def modified(path: Path) -> str:
        """When an input file was last written, which is when its run finished."""

        moment = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.UTC)
        return moment.isoformat(timespec="seconds")

    def artifact(self, arguments: argparse.Namespace, run: str, path: Path) -> str:
        """Where a raw input is kept: copied under the root when ingesting, else its own path."""

        if arguments.command != "ingest":
            return str(path)
        return str(self.store_for(arguments).keep(run, path))

    @staticmethod
    def budgets(raw: list[str]) -> dict[str, tuple[Budget, ...]]:
        budgets: dict[str, list[Budget]] = {}
        for text in raw:
            match = _BUDGET.match(text.replace(" ", ""))
            if match is None:
                raise LedgerSchemaError(f"budget {text!r} is not {_BUDGET_FORM}")
            budgets.setdefault(match["scenario"], []).append(
                Budget(statistic=Statistic(match["statistic"]), limit=float(match["limit"]))
            )
        return {scenario: tuple(items) for scenario, items in budgets.items()}

    def ingest(self, arguments: argparse.Namespace, records: list[LedgerRecord]) -> int:
        if not records:
            raise LedgerSchemaError("nothing to ingest: name at least one raw input")
        path = self.store_for(arguments).write(arguments.run, records)
        print(f"wrote {len(records)} records to {path}")
        return 0

    @staticmethod
    def report(arguments: argparse.Namespace, records: list[LedgerRecord]) -> int:
        if not records:
            raise LedgerSchemaError("nothing to report: name raw inputs, --ledger or --all-ledgers")
        denominators = DenominatorManifest.load(arguments.denominators) if arguments.denominators else None
        report = QualificationReport(records, denominators)
        text = report.render_json() if arguments.format == "json" else report.render_markdown()
        if arguments.output is not None:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        if problems := report.problems():
            print(f"qualification report incomplete: {len(problems)} problem(s)", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        return 0

    @staticmethod
    def check_denominators(path: Path) -> int:
        manifest = DenominatorManifest.load(path)
        for denominator in manifest.denominators:
            print(
                f"{denominator.kind.value}: {len(denominator.ids)} ids from {denominator.source} "
                f"(frozen {denominator.frozen_ids} in {denominator.release}), {denominator.frozen_slots} slots"
            )
        if drift := manifest.drift():
            for problem in drift:
                print(f"  DRIFT {problem}", file=sys.stderr)
            return 1
        return 0

    @staticmethod
    def skip_gate(arguments: argparse.Namespace) -> int:
        outcome = SkipGate(arguments.manifests, arguments.runner).check(arguments.reports, list_skips=arguments.list)
        for line in outcome.lines:
            print(line)
        if outcome.passed:
            return 0
        print(f"skip gate FAILED: {len(outcome.failures)} problem(s)", file=sys.stderr)
        for failure in outcome.failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    @staticmethod
    def skip_coverage(arguments: argparse.Namespace) -> int:
        failed = False
        if arguments.whole or arguments.shards:
            whole = [SkipReport.load(path) for path in arguments.whole]
            shards = [SkipReport.load(path) for path in arguments.shards]
            missing, extra = SkipCoverage.partition(whole, shards)
            print(
                f"shards ran {len(SkipCoverage.tests(shards))} tests; the whole gate ran {len(SkipCoverage.tests(whole))}"
            )
            for nodeid in missing:
                print(f"  only in the whole gate: {nodeid}")
            for nodeid in extra:
                print(f"  only in a shard: {nodeid}")
            failed = failed or bool(missing or extra)
        if arguments.claims:
            contradicted, unchecked, confirmed = SkipCoverage.claims([SkipReport.load(p) for p in arguments.claims])
            print(
                f"covered_by claims: {confirmed} confirmed, {len(contradicted)} contradicted, {len(unchecked)} unchecked"
            )
            for line in contradicted:
                print(f"  CONTRADICTED {line}")
            failed = failed or bool(contradicted)
        return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    return QualificationCommand().run(argv)
