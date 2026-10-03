"""Expected-skip manifests, and the gate that fails a run on an unexpected skip.

Every gate's pytest session writes a skip report (``src/tests/skip_ledger.py``
collects it): every test's outcome, every skip with its reason and location,
the environment variables and tools that gate skips, and every capability
gate a test evaluated. This module classifies those skips against the
runner's expected-skip manifest and fails the gate on any skip the manifest
does not explain.

Runners
-------
``macos`` (the acceptance Mac), ``macos-hosted`` (GitHub's hosted macOS
runners, which ``macos.yml`` names), ``linux-devcontainer`` (the CI and
``make linux-ci`` container), ``windows``, and later the ``ios`` and
``android`` executors. A run names its runner through ``BTRC_TEST_RUNNER``,
or it is detected from the host; a Darwin host detects as ``macos``, so a
hosted runner must name itself. Each runner's manifest is
``src/tests/fixtures/expected-skips/<runner>.json``.

A hosted runner is a CI image of a platform whose acceptance host is another
runner (``HOSTED_RUNNERS``). Everything the image can run, it runs: its
manifest may expect only ``platform`` skips (tests for another OS) and
``hardware`` skips (a device the image lacks), and each hardware rule names
the acceptance host in ``covered_by``.

Manifest schema ``btrc.expected-skips/1``
-----------------------------------------
``schema``        ``btrc.expected-skips/1``
``runner``        the runner the manifest qualifies; matches the file name.
``enforce``       true: an unexpected skip fails the gate. false: report only,
                  for a runner whose manifest is still being established.
``description``   what this runner is and how it was qualified.
``rules``         list; a skip takes the first rule that matches it.
  ``id``          unique kebab-case name.
  ``files``       fnmatch globs on the node id's file (the part before ``::``).
  ``nodes``       optional fnmatch globs on the whole node id, to split a
                  file whose skips are covered differently.
  ``reason``      a regular expression searched in the skip reason.
  ``category``    ``platform`` (the test is for another OS) |
                  ``missing-tool`` | ``missing-sdk`` |
                  ``provider-configuration`` (an environment-configured
                  provider is absent) | ``capability`` (a host capability
                  probe found it absent) | ``runtime-probe`` (a sanitizer or
                  runtime does not start here) | ``hardware`` (a device is
                  absent: ``gating.capabilities`` names it from
                  ``HARDWARE_CAPABILITIES``, and ``covered_by`` names a runner
                  that has it).
  ``gating``      optional ``{"env": [...], "tools": [...], "capabilities":
                  [...]}``: what would have to change for the test to run.
  ``covered_by``  the runners that do run these tests; ``[]`` marks them
                  uncovered, which is a gap the report shows, not a pass.
  ``note``        why the skip is expected on this runner.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = "btrc.expected-skips/1"
SKIP_REPORT_SCHEMA = "btrc.skip-report/1"
MANIFEST_ROOT = REPO / "src" / "tests" / "fixtures" / "expected-skips"
RUNNERS = ("macos", "macos-hosted", "linux-devcontainer", "windows", "ios", "android")
CATEGORIES = (
    "platform",
    "missing-tool",
    "missing-sdk",
    "provider-configuration",
    "capability",
    "runtime-probe",
    "hardware",
)
# The devices a hardware-tier skip may wait on: an audio output device, a GPU
# compute adapter, a physical display and a physical (non-simulated) device.
# These name manifest gating, not probes: of them only physical-device is also
# a target capability in src/tests/runner_capabilities.py.
HARDWARE_CAPABILITIES = ("coreaudio-device", "gpu-adapter", "physical-display", "physical-device")
# Each hosted runner, and the acceptance host that runs its hardware tier.
HOSTED_RUNNERS = {"macos-hosted": "macos"}
HOSTED_CATEGORIES = ("platform", "hardware")
_RULE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENVIRONMENT_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9]\b|\b(?:DISPLAY|CC|CXX|SDKROOT)\b")


class SkipLedgerError(ValueError):
    """A manifest or skip report is malformed, or a gate input is missing."""


class RunnerIdentity:
    """Name the runner a test session executes on."""

    VARIABLE = "BTRC_TEST_RUNNER"
    CONTAINER_MARKERS = (Path("/run/.containerenv"), Path("/.dockerenv"))

    @classmethod
    def detect(
        cls,
        environ: Mapping[str, str] | None = None,
        host: str | None = None,
        containerized: bool | None = None,
    ) -> str:
        """The configured runner, or the host's: Linux counts only inside the devcontainer."""

        environ = os.environ if environ is None else environ
        configured = environ.get(cls.VARIABLE, "").strip()
        if configured:
            return configured
        host = sys.platform if host is None else host
        if host == "darwin":
            return "macos"
        if host in {"win32", "cygwin"}:
            return "windows"
        if host.startswith("linux"):
            if containerized is None:
                containerized = any(marker.exists() for marker in cls.CONTAINER_MARKERS)
            return "linux-devcontainer" if containerized else "linux"
        return host


@dataclass(frozen=True, slots=True)
class SkipRule:
    """One documented, expected class of skips on one runner."""

    id: str
    files: tuple[str, ...]
    reason: re.Pattern[str]
    category: str
    covered_by: tuple[str, ...]
    note: str
    nodes: tuple[str, ...] = ()
    gating_env: tuple[str, ...] = ()
    gating_tools: tuple[str, ...] = ()
    gating_capabilities: tuple[str, ...] = ()

    FIELDS = ("id", "files", "nodes", "reason", "category", "gating", "covered_by", "note")

    def matches(self, nodeid: str, reason: str) -> bool:
        path = nodeid.split("::", 1)[0]
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in self.files):
            return False
        if self.nodes and not any(fnmatch.fnmatchcase(nodeid, pattern) for pattern in self.nodes):
            return False
        return self.reason.search(reason) is not None

    @classmethod
    def from_mapping(cls, data: object, where: str, runner: str) -> SkipRule:
        if not isinstance(data, Mapping):
            raise SkipLedgerError(f"{where}: expected a table")
        unknown = sorted(set(data) - set(cls.FIELDS))
        if unknown:
            raise SkipLedgerError(f"{where}: unknown field(s) {', '.join(unknown)}")
        rule_id = cls._text(data, "id", where)
        if not _RULE_ID.match(rule_id):
            raise SkipLedgerError(f"{where}.id: {rule_id!r} is not kebab-case")
        try:
            reason = re.compile(cls._text(data, "reason", where))
        except re.error as error:
            raise SkipLedgerError(f"{where}.reason: {error}") from None
        category = cls._text(data, "category", where)
        if category not in CATEGORIES:
            raise SkipLedgerError(f"{where}.category: {category!r} is not one of {', '.join(CATEGORIES)}")
        covered_by = cls._texts(data, "covered_by", where, required=True)
        for other in covered_by:
            if other not in RUNNERS:
                raise SkipLedgerError(f"{where}.covered_by: {other!r} is not one of {', '.join(RUNNERS)}")
            if other == runner:
                raise SkipLedgerError(f"{where}.covered_by: a skip on {runner} cannot be covered by {runner}")
        gating = data.get("gating") or {}
        if not isinstance(gating, Mapping) or set(gating) - {"env", "tools", "capabilities"}:
            raise SkipLedgerError(f"{where}.gating: expected env, tools and capabilities lists")
        files = cls._texts(data, "files", where, required=True)
        if not files:
            raise SkipLedgerError(f"{where}.files: name at least one file glob")
        capabilities = cls._texts(gating, "capabilities", f"{where}.gating")
        if category == "hardware":
            if not capabilities or not set(capabilities) <= set(HARDWARE_CAPABILITIES):
                raise SkipLedgerError(
                    f"{where}.gating.capabilities: a hardware rule names its devices from "
                    f"{', '.join(HARDWARE_CAPABILITIES)}"
                )
            if not covered_by:
                raise SkipLedgerError(f"{where}.covered_by: a hardware rule names a runner that has the device")
            # A device is the whole gate: a missing tool or variable is not hardware.
            if gating.get("env") or gating.get("tools"):
                raise SkipLedgerError(f"{where}.gating: a hardware rule is gated by capabilities only")
        return cls(
            id=rule_id,
            files=files,
            nodes=cls._texts(data, "nodes", where),
            reason=reason,
            category=category,
            covered_by=covered_by,
            note=cls._text(data, "note", where),
            gating_env=cls._texts(gating, "env", f"{where}.gating"),
            gating_tools=cls._texts(gating, "tools", f"{where}.gating"),
            gating_capabilities=capabilities,
        )

    @staticmethod
    def _text(data: Mapping[str, Any], name: str, where: str) -> str:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise SkipLedgerError(f"{where}.{name}: required non-empty text")
        return value

    @staticmethod
    def _texts(data: Mapping[str, Any], name: str, where: str, *, required: bool = False) -> tuple[str, ...]:
        value = data.get(name)
        if value is None:
            if required:
                raise SkipLedgerError(f"{where}.{name}: required list")
            return ()
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise SkipLedgerError(f"{where}.{name}: expected a list of strings")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise SkipLedgerError(f"{where}.{name}: expected non-empty strings")
        return tuple(value)


@dataclass(frozen=True, slots=True)
class ExpectedSkipManifest:
    """The skips one runner is allowed to have, each with its covering runners."""

    runner: str
    enforce: bool
    description: str
    rules: tuple[SkipRule, ...]
    path: Path | None = None

    @classmethod
    def path_for(cls, runner: str, root: Path = MANIFEST_ROOT) -> Path:
        return root / f"{runner}.json"

    @classmethod
    def load(cls, path: Path) -> ExpectedSkipManifest:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SkipLedgerError(f"no expected-skip manifest at {path}") from None
        except json.JSONDecodeError as error:
            raise SkipLedgerError(f"{path}: {error.msg} at line {error.lineno}") from None
        return cls.from_mapping(data, path)

    @classmethod
    def from_mapping(cls, data: object, path: Path | None = None) -> ExpectedSkipManifest:
        where = str(path) if path is not None else "manifest"
        if not isinstance(data, Mapping):
            raise SkipLedgerError(f"{where}: expected a table")
        unknown = sorted(set(data) - {"schema", "runner", "enforce", "description", "rules"})
        if unknown:
            raise SkipLedgerError(f"{where}: unknown field(s) {', '.join(unknown)}")
        if data.get("schema") != MANIFEST_SCHEMA:
            raise SkipLedgerError(f"{where}.schema: expected {MANIFEST_SCHEMA!r}")
        runner = SkipRule._text(data, "runner", where)
        if path is not None and path.stem != runner:
            raise SkipLedgerError(f"{where}: manifest for {runner!r} must be named {runner}.json")
        enforce = data.get("enforce")
        if not isinstance(enforce, bool):
            raise SkipLedgerError(f"{where}.enforce: expected true or false")
        rules_data = data.get("rules")
        if not isinstance(rules_data, Sequence) or isinstance(rules_data, str):
            raise SkipLedgerError(f"{where}.rules: expected a list")
        rules = tuple(
            SkipRule.from_mapping(rule, f"{where}.rules[{index}]", runner) for index, rule in enumerate(rules_data)
        )
        duplicates = sorted(name for name, count in Counter(rule.id for rule in rules).items() if count > 1)
        if duplicates:
            raise SkipLedgerError(f"{where}.rules: duplicate id(s) {', '.join(duplicates)}")
        acceptance = HOSTED_RUNNERS.get(runner)
        for index, rule in enumerate(rules if acceptance is not None else ()):
            if rule.category not in HOSTED_CATEGORIES:
                raise SkipLedgerError(
                    f"{where}.rules[{index}].category: the hosted runner {runner} expects only "
                    f"{' and '.join(HOSTED_CATEGORIES)} skips, not {rule.category!r}"
                )
            if rule.category == "hardware" and acceptance not in rule.covered_by:
                raise SkipLedgerError(
                    f"{where}.rules[{index}].covered_by: a {runner} hardware skip must be covered by {acceptance}"
                )
            # A test for another OS cannot run on this one's acceptance host either.
            if rule.category == "platform" and acceptance in rule.covered_by:
                raise SkipLedgerError(
                    f"{where}.rules[{index}].covered_by: a {runner} platform skip must not be covered by {acceptance}"
                )
        return cls(
            runner=runner,
            enforce=enforce,
            description=SkipRule._text(data, "description", where),
            rules=rules,
            path=path,
        )

    def classify(self, nodeid: str, reason: str) -> SkipRule | None:
        return next((rule for rule in self.rules if rule.matches(nodeid, reason)), None)


@dataclass(frozen=True, slots=True)
class SkipClassification:
    """One skip, and the rule that expects it (or None)."""

    nodeid: str
    when: str
    location: str | None
    reason: str
    rule: SkipRule | None
    gating_env: Mapping[str, str] = field(default_factory=dict)

    @property
    def expected(self) -> bool:
        return self.rule is not None

    @property
    def covered_by(self) -> tuple[str, ...] | None:
        return self.rule.covered_by if self.rule is not None else None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "rule": self.rule.id if self.rule else None,
            "category": self.rule.category if self.rule else None,
            "covered_by": list(self.rule.covered_by) if self.rule else None,
            "expected": self.expected,
            "gating_env": dict(self.gating_env),
        }


class SkipClassifier:
    """Classify every skip in a skip report against a runner's manifest."""

    def __init__(self, manifest: ExpectedSkipManifest) -> None:
        self.manifest = manifest

    @staticmethod
    def environment_names(reason: str) -> list[str]:
        """Environment variables a skip reason names, such as BTRC_NATIVE_PROVIDER_CC."""

        return sorted(set(_ENVIRONMENT_NAME.findall(reason)))

    def classify(self, report: Mapping[str, Any]) -> list[SkipClassification]:
        presence = report.get("environment") or {}
        result = []
        for skip in report.get("skips") or ():
            reason = skip.get("reason") or ""
            rule = self.manifest.classify(skip["nodeid"], reason)
            names = set(self.environment_names(reason))
            if rule is not None:
                names.update(rule.gating_env)
            result.append(
                SkipClassification(
                    nodeid=skip["nodeid"],
                    when=skip.get("when") or "call",
                    location=skip.get("location"),
                    reason=reason,
                    rule=rule,
                    gating_env={name: presence.get(name, "unset") for name in sorted(names)},
                )
            )
        return result

    def annotate(self, report: dict[str, Any]) -> None:
        """Record each skip's rule, coverage and gating environment in the report itself."""

        for skip, classification in zip(report.get("skips") or (), self.classify(report)):
            skip.update(classification.to_mapping())
        report["manifest"] = {
            "path": self.manifest.path.relative_to(REPO).as_posix()
            if self.manifest.path is not None and self.manifest.path.is_relative_to(REPO)
            else (str(self.manifest.path) if self.manifest.path else None),
            "runner": self.manifest.runner,
            "enforce": self.manifest.enforce,
        }


class SkipReport:
    """Read one skip report written by the collector."""

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SkipLedgerError(f"no skip report at {path}; the gate's pytest session writes it") from None
        except json.JSONDecodeError as error:
            raise SkipLedgerError(f"{path}: {error.msg}") from None
        if not isinstance(data, dict) or data.get("schema") != SKIP_REPORT_SCHEMA:
            raise SkipLedgerError(f"{path}: not a {SKIP_REPORT_SCHEMA} report")
        for name in ("runner", "tests", "skips", "counts"):
            if name not in data:
                raise SkipLedgerError(f"{path}: missing {name!r}")
        return data


@dataclass
class GateOutcome:
    """What one gate run found across its reports."""

    lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


class SkipGate:
    """Fail when a report has a skip its runner's manifest does not expect."""

    def __init__(self, manifest_root: Path = MANIFEST_ROOT, runner: str | None = None) -> None:
        self.manifest_root = manifest_root
        self.runner = runner
        self._manifests: dict[str, ExpectedSkipManifest] = {}

    def manifest(self, runner: str) -> ExpectedSkipManifest:
        if runner not in self._manifests:
            path = ExpectedSkipManifest.path_for(runner, self.manifest_root)
            if not path.exists():
                raise SkipLedgerError(
                    f"no expected-skip manifest for runner {runner!r} ({path}); "
                    f"set {RunnerIdentity.VARIABLE} to a qualified runner or add the manifest"
                )
            self._manifests[runner] = ExpectedSkipManifest.load(path)
        return self._manifests[runner]

    def check(self, paths: Iterable[Path], *, list_skips: bool = False) -> GateOutcome:
        outcome = GateOutcome()
        matched: dict[str, set[str]] = {}
        for path in paths:
            try:
                report = SkipReport.load(path)
                runner = self.runner or report["runner"]
                manifest = self.manifest(runner)
            except SkipLedgerError as error:
                outcome.failures.append(str(error))
                outcome.lines.append(f"skip gate: {error}")
                continue
            # The gate classifies afresh: the collector's own annotation, or its
            # classification_error, describes the manifest as it was then.
            classifications = SkipClassifier(manifest).classify(report)
            matched.setdefault(runner, set()).update(item.rule.id for item in classifications if item.rule)
            self._summarize(path, report, manifest, classifications, outcome, list_skips)
        for runner, used in sorted(matched.items()):
            idle = [rule.id for rule in self.manifest(runner).rules if rule.id not in used]
            if idle:
                outcome.lines.append(f"  rules with no skip in these reports ({runner}): {', '.join(idle)}")
        return outcome

    @staticmethod
    def _summarize(
        path: Path,
        report: Mapping[str, Any],
        manifest: ExpectedSkipManifest,
        classifications: list[SkipClassification],
        outcome: GateOutcome,
        list_skips: bool,
    ) -> None:
        counts = report.get("counts") or {}
        unexpected = [item for item in classifications if not item.expected]
        covered = sum(1 for item in classifications if item.covered_by)
        uncovered = sum(1 for item in classifications if item.expected and not item.covered_by)
        mode = "enforced" if manifest.enforce else "report-only"
        outcome.lines.append(
            f"skip gate: {path} (runner {manifest.runner}, {mode}): "
            f"{counts.get('passed', 0)} passed, {counts.get('failed', 0)} failed, "
            f"{counts.get('error', 0)} errors, {len(classifications)} skipped "
            f"({len(classifications) - len(unexpected)} expected, {len(unexpected)} unexpected; "
            f"{covered} covered by another runner, {uncovered} uncovered)"
        )
        by_rule = Counter(item.rule.id for item in classifications if item.rule)
        for rule in manifest.rules:
            if by_rule[rule.id]:
                covering = ", ".join(rule.covered_by) or "uncovered"
                outcome.lines.append(f"  {by_rule[rule.id]:5d}  {rule.id:42} {rule.category:22} {covering}")
        if manifest.enforce or list_skips:
            for item in unexpected:
                where = f" at {item.location}" if item.location else ""
                outcome.lines.append(f"  UNEXPECTED {item.nodeid} ({item.when}){where}: {item.reason}")
                if manifest.enforce:
                    outcome.failures.append(f"{item.nodeid}: unexpected skip on {manifest.runner}: {item.reason}")
        else:
            # A manifest still being established would print thousands of
            # lines; group what it does not yet explain by file and reason.
            groups = Counter((item.nodeid.split("::", 1)[0], item.reason.splitlines()[0][:160]) for item in unexpected)
            for (path, reason), count in sorted(groups.items()):
                outcome.lines.append(f"  UNEXPECTED {count:5d}  {path}: {reason}")
        if list_skips:
            for item in classifications:
                covering = (", ".join(item.covered_by) or "uncovered") if item.expected else "UNEXPECTED"
                outcome.lines.append(f"  {item.nodeid}  [{covering}]")


class SkipCoverage:
    """Check skip reports against each other: shard partitions and covered_by claims."""

    @staticmethod
    def tests(reports: Iterable[Mapping[str, Any]]) -> dict[str, str]:
        merged: dict[str, str] = {}
        for report in reports:
            merged.update(report.get("tests") or {})
        return merged

    @classmethod
    def partition(cls, whole: list[Mapping[str, Any]], shards: list[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
        """Node ids the shards miss, and node ids only the shards ran."""

        expected = set(cls.tests(whole))
        actual = set(cls.tests(shards))
        return sorted(expected - actual), sorted(actual - expected)

    @staticmethod
    def claims(reports: list[Mapping[str, Any]]) -> tuple[list[str], list[str], int]:
        """Contradicted claims, claims with no report to check, and the count confirmed."""

        by_runner: dict[str, dict[str, str]] = {}
        for report in reports:
            by_runner.setdefault(report["runner"], {}).update(report.get("tests") or {})
        contradicted, unchecked, confirmed = [], [], 0
        for report in reports:
            for skip in report.get("skips") or ():
                for runner in skip.get("covered_by") or ():
                    outcomes = by_runner.get(runner)
                    if outcomes is None:
                        unchecked.append(f"{skip['nodeid']}: no {runner} report")
                    elif outcomes.get(skip["nodeid"]) == "passed":
                        confirmed += 1
                    else:
                        state = outcomes.get(skip["nodeid"], "not collected")
                        contradicted.append(f"{skip['nodeid']}: claimed covered by {runner}, which {state} it")
        return contradicted, unchecked, confirmed
