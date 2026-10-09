"""The pytest plugin that writes a gate's skip report.

`src/tests/conftest.py` installs it for every session. The report records
every test's outcome, every skip with its reason, phase and location, which
environment variables and tools are present (presence only, since values hold
private paths; configuration words such as BTRC_CC keep their values), and
every capability gate a test evaluated through
`src.tests.runner_capabilities`. It is classified against the runner's
expected-skip manifest before it is written, and ``python3 -m
tools.qualification skip-gate`` fails the gate on any skip that manifest does
not expect. ``--skip-report`` names the file; the default is
``build/skip-report.json``, and the Makefile gives each gate its own. Pass it
as one token (``--skip-report=PATH``): pytest takes a separate existing path
for a test path while it determines the rootdir.

Under xdist the controller receives every worker's reports, so only the
controller collects and writes; a worker forwards its capability gates on
each report's user properties.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from src.tests.runner_capabilities import CapabilityGateLog
from tools.qualification.skips import (
    SKIP_REPORT_SCHEMA,
    ExpectedSkipManifest,
    RunnerIdentity,
    SkipClassifier,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = REPO / "build" / "skip-report.json"
GATES_PROPERTY = "btrc.capability-gates"
GUI_IDENTITY_PROPERTY = "btrc.gui-report-identity"
_GUI_IDENTITY = pytest.StashKey[tuple[str, str]]()

# Variables whose presence decides whether some test runs. Only presence is
# recorded: values hold private paths, and a report is uploaded from CI.
_GATING_VARIABLES = (
    "CC",
    "CXX",
    "DBUS_SESSION_BUS_ADDRESS",
    "DEVELOPER_DIR",
    "DISPLAY",
    "GPU_CFLAGS",
    "GPU_LDFLAGS",
    "PKG_CONFIG_PATH",
    "SDKROOT",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
)
# Values of these are configuration words, not paths, and say which run this was.
_RECORDED_VALUES = frozenset(
    {
        "BTRC_CC",
        "BTRC_CFLAGS",
        "BTRC_SKIP_AUDIO_TESTS",
        "BTRC_TEST_CAPABILITIES",
        "BTRC_TEST_MODULE_UNITS",
        "BTRC_TEST_RUNNER",
    }
)
_TOOLS = (
    "cc",
    "clang",
    "gcc",
    "lldb",
    "naga",
    "pkg-config",
    "podman",
    "wine",
    "wine64",
    "xcrun",
    "zig",
)


class TestReportForwarder:
    """Forward capability verdicts and exact source identities across workers."""

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items):
        originals = {item: item.nodeid for item in items if item.get_closest_marker("macos_gui") is not None}
        result = yield
        for item, original in originals.items():
            if item.nodeid == original:
                continue
            groups = {
                str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                for mark in item.iter_markers("xdist_group")
            }
            if groups != {"macos_gui"} or item.nodeid != original + "@macos_gui":
                raise pytest.UsageError(f"{original}: inconsistent AppKit scheduling identity")
            item.stash[_GUI_IDENTITY] = (original, item.nodeid)
        return result

    @pytest.hookimpl(wrapper=True)
    def pytest_report_to_serializable(self, report):
        data = yield
        identity = getattr(report, "btrc_gui_identity", None)
        if identity is None:
            return data
        original, scheduled = identity
        if (
            scheduled != original + "@macos_gui"
            or report.nodeid != scheduled
            or data is None
            or data.get("nodeid") != scheduled
        ):
            raise ValueError("Inconsistent AppKit report identity")
        # xdist checks the live report against the scheduled item after this
        # hook. Only its serialized copy may carry the canonical source ID.
        copied = dict(data)
        copied["nodeid"] = original
        properties = []
        for name, value in data.get("user_properties", ()):
            if name == GUI_IDENTITY_PROPERTY:
                raise ValueError("Duplicate AppKit report identity")
            if name == GATES_PROPERTY:
                gates = json.loads(value)
                value = json.dumps(
                    [{**gate, "nodeid": original} if gate.get("nodeid") == scheduled else gate for gate in gates]
                )
            properties.append((name, value))
        properties.append((GUI_IDENTITY_PROPERTY, json.dumps({"original": original, "scheduled": scheduled})))
        copied["user_properties"] = properties
        return copied

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        identity = item.stash.get(_GUI_IDENTITY, None)
        if identity is not None:
            if report.nodeid != identity[1]:
                raise ValueError("Changed AppKit report identity")
            report.btrc_gui_identity = identity
        gates = CapabilityGateLog.drain()
        if gates:
            report.user_properties.append((GATES_PROPERTY, json.dumps(gates)))
        return report


class SkipLedger:
    """Collect outcomes, skips and capability gates; write the classified report."""

    def __init__(self, config: pytest.Config, path: Path) -> None:
        self.config = config
        self.path = path
        self.started = datetime.datetime.now(datetime.UTC)
        # The environment the session was started with, before any fixture changes it.
        self.environment = {
            name: (os.environ[name] if name in _RECORDED_VALUES else "set")
            for name in sorted(os.environ)
            if name.startswith("BTRC_") or name in _GATING_VARIABLES
        }
        self.tests: dict[str, str] = {}
        self.skips: dict[str, dict[str, Any]] = {}
        self.gates: dict[tuple[str, str], dict[str, Any]] = {}

    @staticmethod
    def add_options(parser: pytest.Parser) -> None:
        parser.addoption(
            "--skip-report",
            action="store",
            default=None,
            help="where this session writes its skip report (default: build/skip-report.json)",
        )

    @classmethod
    def install(cls, config: pytest.Config) -> None:
        config.pluginmanager.register(TestReportForwarder(), "btrc-test-reports")
        if hasattr(config, "workerinput") or config.option.collectonly:
            return
        raw = config.getoption("--skip-report")
        path = Path(raw) if raw else DEFAULT_REPORT
        if not path.is_absolute():
            path = Path(config.invocation_params.dir) / path
        config.pluginmanager.register(cls(config, path), "btrc-skip-ledger")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._gates(report)
        nodeid = report.nodeid
        current = self.tests.get(nodeid)
        outcome = self._outcome(report)
        if outcome is not None and (current is None or self._rank(outcome) >= self._rank(current)):
            self.tests[nodeid] = outcome
        if report.skipped and not hasattr(report, "wasxfail"):
            self._skip(nodeid, report.when, report.longrepr)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.tests[report.nodeid] = "skipped"
            self._skip(report.nodeid, "collect", report.longrepr)
        elif report.failed:
            self.tests[report.nodeid] = "error"

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        report = self.report(int(exitstatus))
        try:
            runner = report["runner"]
            path = ExpectedSkipManifest.path_for(runner)
            if path.exists():
                SkipClassifier(ExpectedSkipManifest.load(path)).annotate(report)
            else:
                report["classification_error"] = f"no expected-skip manifest for runner {runner!r}"
        except Exception as error:  # the report must still be written; the gate classifies afresh
            report["classification_error"] = f"{type(error).__name__}: {error}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.path.with_name(f".{self.path.name}.{os.getpid()}.partial")
        staged.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        staged.replace(self.path)

    def report(self, exitstatus: int) -> dict[str, Any]:
        counts = Counter(self.tests.values())
        return {
            "schema": SKIP_REPORT_SCHEMA,
            "runner": RunnerIdentity.detect(),
            "created_at": self.started.isoformat(timespec="seconds"),
            "finished_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "revision": self._revision(),
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "invocation": {
                "args": list(self.config.invocation_params.args),
                "workers": getattr(self.config.option, "numprocesses", None),
                "exitstatus": exitstatus,
            },
            "environment": self.environment,
            "tools": {tool: shutil.which(tool) is not None for tool in _TOOLS},
            "counts": {
                name: counts.get(name, 0) for name in ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
            },
            "tests": dict(sorted(self.tests.items())),
            "skips": [self.skips[nodeid] for nodeid in sorted(self.skips)],
            "capability_gates": [self.gates[key] for key in sorted(self.gates)],
        }

    @staticmethod
    def _outcome(report: pytest.TestReport) -> str | None:
        if hasattr(report, "wasxfail"):
            return "xfailed" if report.skipped else "xpassed"
        if report.failed:
            return "failed" if report.when == "call" else "error"
        if report.skipped:
            return "skipped"
        return "passed" if report.when == "call" else None

    @staticmethod
    def _rank(outcome: str) -> int:
        # A teardown error outranks the call's pass; a pass never hides a failure.
        return {"passed": 0, "xpassed": 1, "xfailed": 1, "skipped": 2, "failed": 3, "error": 4}[outcome]

    def _skip(self, nodeid: str, when: str, longrepr: object) -> None:
        location, reason = self._location_and_reason(longrepr)
        gate = next(
            (
                gate
                for (gate_node, _), gate in self.gates.items()
                if gate_node == nodeid and not gate["available"] and gate.get("reason") == reason
            ),
            None,
        )
        self.skips[nodeid] = {
            "nodeid": nodeid,
            "when": when,
            "location": location,
            "reason": reason,
            "capability": gate["capability"] if gate else None,
        }

    def _location_and_reason(self, longrepr: object) -> tuple[str | None, str]:
        if isinstance(longrepr, tuple | list) and len(longrepr) == 3:
            path, line, message = longrepr
            reason = str(message).removeprefix("Skipped: ")
            location = Path(str(path))
            if location.is_absolute() and location.is_relative_to(self.config.rootpath):
                location = location.relative_to(self.config.rootpath)
            return f"{location.as_posix()}:{line}", reason
        return None, str(longrepr).removeprefix("Skipped: ")

    def _gates(self, report: pytest.TestReport) -> None:
        for name, value in report.user_properties:
            if name != GATES_PROPERTY:
                continue
            for gate in json.loads(value):
                nodeid = gate.get("nodeid") or report.nodeid
                self.gates[(nodeid, gate["capability"])] = {**gate, "nodeid": nodeid}

    @staticmethod
    def _revision() -> str | None:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        revision = completed.stdout.strip()
        return revision if completed.returncode == 0 and revision else None
