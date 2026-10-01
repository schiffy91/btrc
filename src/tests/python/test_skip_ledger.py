"""The skip ledger: the collector, the expected-skip manifests, the gate and target capabilities."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests import runner_capabilities as capabilities
from src.tests.process_limits import TRANSPILE_TIMEOUT
from tools.qualification.skips import (
    MANIFEST_ROOT,
    RUNNERS,
    ExpectedSkipManifest,
    RunnerIdentity,
    SkipClassifier,
    SkipCoverage,
    SkipGate,
    SkipLedgerError,
)

REPO = Path(__file__).resolve().parents[3]

# Representative skips from the 1cadaf4 `make test` record on macOS. That
# record's DAP session skip was lldb's; since stage2/lldbenv the dev shell runs
# those sessions, and the one skip a Mac still expects is developer mode off.
MACOS_SKIPS = [
    (
        "src/tests/debug/test_dap_session.py::test_stop_on_entry",
        "needs macOS developer mode for lldb to launch an inferior (sudo /usr/sbin/DevToolsSecurity -enable)",
    ),
    (
        "src/tests/python/test_native_compiler_context.py::test_context[x]",
        "build native reader and configure its native compiler provider",
    ),
    (
        "src/tests/python/test_native_preprocess_consumer.py::test_consumer",
        "configure the packaged receipt provider and its C/C++ toolchain",
    ),
    (
        "src/tests/python/test_native_unique_resources.py::test_sqlite",
        "actual SQLite SDK proof requires sqlite3.pc in PKG_CONFIG_PATH",
    ),
    ("src/tests/btrc/test_parser_diagnostics.py::test_full", "requires /dev/full"),
    ("src/tests/python/test_artifact_storage.py::test_crt", "requires the native Windows CRT"),
    ("src/tests/python/test_artifact_reparse.py::test_junction", "native junctions require Windows"),
    (
        "src/tests/python/test_native_linux_providers.py::test_linux_image_decoding[False-python]",
        "requires Linux and the explicitly built native header reader",
    ),
    (
        "src/tests/python/test_native_linux_providers.py::test_linux_gui_controls[False-python]",
        "requires Linux and the explicitly built native header reader",
    ),
]


def _report(skips, runner="macos", tests=None, environment=None):
    return {
        "schema": "btrc.skip-report/1",
        "runner": runner,
        "counts": {"passed": 0, "skipped": len(skips)},
        "tests": tests if tests is not None else {nodeid: "skipped" for nodeid, _ in skips},
        "skips": [{"nodeid": nodeid, "when": "setup", "reason": reason} for nodeid, reason in skips],
        "environment": environment or {},
    }


def _manifest(tmp_path: Path, runner: str, rules: list[dict], enforce: bool = True) -> Path:
    path = tmp_path / f"{runner}.json"
    path.write_text(
        json.dumps(
            {
                "schema": "btrc.expected-skips/1",
                "runner": runner,
                "enforce": enforce,
                "description": "test manifest",
                "rules": rules,
            }
        )
    )
    return path


def _rule(**overrides) -> dict:
    return {
        "id": "known-gap",
        "files": ["test_cases.py"],
        "reason": "^tool is not installed$",
        "category": "missing-tool",
        "covered_by": ["linux-devcontainer"],
        "note": "the gap this test expects",
        **overrides,
    }


# --- manifests --------------------------------------------------------------


def test_every_tracked_manifest_is_valid_and_named_for_a_known_runner():
    manifests = {path.stem: ExpectedSkipManifest.load(path) for path in sorted(MANIFEST_ROOT.glob("*.json"))}

    assert {"macos", "linux-devcontainer", "windows"} <= set(manifests)
    assert set(manifests) <= set(RUNNERS)
    assert manifests["macos"].enforce
    for manifest in manifests.values():
        for rule in manifest.rules:
            for pattern in rule.files:
                assert any(REPO.glob(pattern)), f"{manifest.runner}:{rule.id} names no file: {pattern}"


def test_the_macos_manifest_explains_the_recorded_skips_and_names_their_coverage():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json")
    rules = {nodeid: manifest.classify(nodeid, reason) for nodeid, reason in MACOS_SKIPS}

    assert all(rules.values()), [nodeid for nodeid, rule in rules.items() if rule is None]
    assert rules[MACOS_SKIPS[0][0]].covered_by == ()
    assert rules[MACOS_SKIPS[4][0]].covered_by == ("linux-devcontainer",)
    assert rules[MACOS_SKIPS[5][0]].covered_by == ("windows",)
    assert rules[MACOS_SKIPS[7][0]].id == "linux-native-reader-covered"
    assert rules[MACOS_SKIPS[8][0]].id == "linux-native-reader-uncovered"
    # The dev shell provides naga (stage2/nix, e74a3cc), so a naga skip is unexpected again.
    assert (
        manifest.classify("src/tests/python/test_wgsl_semantics.py::test_x", "naga WGSL validator is not installed")
        is None
    )


def test_the_macos_manifest_expects_a_dap_session_skip_only_for_developer_mode():
    """The DAP sessions skip under a reason per cause; on a Mac only developer mode being off is expected.

    The reasons are read from the test module's source: importing it would
    launch the adapter to probe this host.
    """

    module = ast.parse((REPO / "src/tests/debug/test_dap_session.py").read_text(encoding="utf-8"))
    reasons = {
        target.id: node.value.value
        for node in module.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.endswith("_REASON")
    }
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json")
    nodeid = "src/tests/debug/test_dap_session.py::test_full_debug_session"

    assert set(reasons) == {"COMPILER_REASON", "DEVELOPER_MODE_REASON", "LLDB_REASON"}
    assert manifest.classify(nodeid, reasons["DEVELOPER_MODE_REASON"]).id == "dap-session-developer-mode"
    for unexpected in (
        reasons["COMPILER_REASON"],
        reasons["LLDB_REASON"],
        f"{reasons['LLDB_REASON']}: btrc debug adapter: cannot locate lldb (exit status 1).",
        "needs lldb (with Python scripting) and a C compiler",
    ):
        assert manifest.classify(nodeid, unexpected) is None, unexpected


def test_no_macos_rule_expects_a_naga_gated_skip():
    """Every naga-gated test runs in the dev shell, so the macOS manifest must not explain one away."""

    gated = re.compile(r'@pytest\.mark\.skipif\(NAGA is None, reason="([^"]+)"\)\s*\ndef (test_\w+)')
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json")
    skips = [
        (f"{path.relative_to(REPO).as_posix()}::{name}", reason)
        for path in sorted((REPO / "src/tests").rglob("test_*.py"))
        for reason, name in gated.findall(path.read_text(encoding="utf-8"))
    ]

    assert len(skips) >= 5, skips
    assert {nodeid: manifest.classify(nodeid, reason) for nodeid, reason in skips} == dict.fromkeys(
        (nodeid for nodeid, _ in skips), None
    )


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ([_rule(), _rule()], "duplicate id"),
        ([_rule(covered_by=["macos"])], "cannot be covered by macos"),
        ([_rule(covered_by=["solaris"])], "'solaris' is not one of"),
        ([_rule(category="flaky")], "'flaky' is not one of"),
        ([_rule(reason="(")], "reason"),
        ([_rule(id="Known Gap")], "kebab-case"),
        ([_rule(files=[])], "at least one file glob"),
        ([{**_rule(), "surprise": True}], "unknown field"),
        ([{key: value for key, value in _rule().items() if key != "covered_by"}], "covered_by: required"),
    ],
)
def test_malformed_manifests_are_rejected(tmp_path, rules, message):
    with pytest.raises(SkipLedgerError, match=message):
        ExpectedSkipManifest.load(_manifest(tmp_path, "macos", rules))


def test_a_manifest_must_be_named_for_its_runner(tmp_path):
    path = _manifest(tmp_path, "macos", [])
    renamed = path.with_name("windows.json")
    path.rename(renamed)

    with pytest.raises(SkipLedgerError, match=r"must be named macos\.json"):
        ExpectedSkipManifest.load(renamed)


def test_classification_records_gating_environment_presence():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json")
    report = _report(MACOS_SKIPS[1:4], environment={"BTRC_NATIVE_HEADER_READER": "set", "PKG_CONFIG_PATH": "set"})

    classified = {item.nodeid: item for item in SkipClassifier(manifest).classify(report)}

    provider = classified[MACOS_SKIPS[1][0]]
    assert provider.gating_env == {
        "BTRC_NATIVE_HEADER_READER": "set",
        "BTRC_NATIVE_PROVIDER_CC": "unset",
        "BTRC_NATIVE_PROVIDER_CXX": "unset",
    }
    assert classified[MACOS_SKIPS[3][0]].gating_env == {"PKG_CONFIG_PATH": "set"}
    assert SkipClassifier.environment_names("no WAYLAND_DISPLAY or DISPLAY") == ["DISPLAY", "WAYLAND_DISPLAY"]


# --- the gate ---------------------------------------------------------------


def test_the_gate_fails_on_an_unexpected_skip_and_lists_every_skip(tmp_path):
    _manifest(tmp_path, "macos", [_rule(files=["src/tests/python/test_cases.py"])])
    report = tmp_path / "skip-report.json"
    expected = ("src/tests/python/test_cases.py::test_tool", "tool is not installed")
    report.write_text(json.dumps(_report([expected])))

    passing = SkipGate(tmp_path).check([report], list_skips=True)
    assert passing.passed
    assert any("1 expected, 0 unexpected; 1 covered by another runner, 0 uncovered" in line for line in passing.lines)
    assert any("test_tool  [linux-devcontainer]" in line for line in passing.lines)

    report.write_text(json.dumps(_report([expected, ("src/tests/python/test_new.py::test_y", "surprise")])))
    failing = SkipGate(tmp_path).check([report])
    assert not failing.passed
    assert failing.failures == ["src/tests/python/test_new.py::test_y: unexpected skip on macos: surprise"]


def test_a_report_only_manifest_lists_unexpected_skips_without_failing(tmp_path):
    _manifest(tmp_path, "linux-devcontainer", [], enforce=False)
    report = tmp_path / "skip-report.json"
    report.write_text(json.dumps(_report([("src/tests/x.py::test_y", "why")], runner="linux-devcontainer")))

    outcome = SkipGate(tmp_path).check([report])

    assert outcome.passed
    assert "  UNEXPECTED     1  src/tests/x.py: why" in outcome.lines
    listed = SkipGate(tmp_path).check([report], list_skips=True)
    assert any("UNEXPECTED src/tests/x.py::test_y (setup): why" in line for line in listed.lines)


def test_the_gate_fails_without_a_report_or_a_manifest(tmp_path):
    assert not SkipGate(tmp_path).check([tmp_path / "missing.json"]).passed
    report = tmp_path / "skip-report.json"
    report.write_text(json.dumps(_report([], runner="ios")))
    outcome = SkipGate(tmp_path).check([report])
    assert not outcome.passed
    assert "no expected-skip manifest for runner 'ios'" in outcome.failures[0]


def test_skip_coverage_checks_shard_partitions_and_covered_by_claims():
    whole = _report([], tests={"a::t": "passed", "b::t": "skipped", "c::t": "passed"})
    shards = [_report([], tests={"a::t": "passed"}), _report([], tests={"b::t": "skipped", "d::t": "passed"})]
    assert SkipCoverage.partition([whole], shards) == (["c::t"], ["d::t"])

    mac = _report([("x::t", "linux only"), ("y::t", "linux only"), ("z::t", "windows only")])
    for skip, covering in zip(mac["skips"], (["linux-devcontainer"], ["linux-devcontainer"], ["windows"])):
        skip["covered_by"] = covering
    linux = _report([], runner="linux-devcontainer", tests={"x::t": "passed", "y::t": "skipped"})

    contradicted, unchecked, confirmed = SkipCoverage.claims([mac, linux])

    assert confirmed == 1
    assert contradicted == ["y::t: claimed covered by linux-devcontainer, which skipped it"]
    assert unchecked == ["z::t: no windows report"]


# --- the collector, end to end ---------------------------------------------

_INNER_CONFTEST = """
from src.tests.skip_ledger import SkipLedger

def pytest_addoption(parser):
    SkipLedger.add_options(parser)

def pytest_configure(config):
    SkipLedger.install(config)
"""

_INNER_TESTS = """
import pytest
from src.tests.runner_capabilities import target_capability_error

def test_passes():
    pass

def test_fails():
    assert False

@pytest.mark.skipif(True, reason="tool is not installed")
def test_expected_skip():
    pass

def test_needs_a_simulator():
    if error := target_capability_error("ios-simulator"):
        pytest.skip(error)

@pytest.mark.xfail(reason="known defect")
def test_known_defect():
    assert False
"""

_INJECTED = """
import pytest

def test_injected():
    pytest.skip("an injected unexpected skip")
"""


def _run_inner(tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess, dict]:
    report = tmp_path / "out" / "skip-report.json"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO), os.environ.get("PYTHONPATH")))),
        "BTRC_TEST_RUNNER": "macos",
        "BTRC_PRIVATE_PATH": "/Users/someone/private",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("BTRC_TEST_CAPABILITIES", None)
    completed = subprocess.run(
        # One token: pytest would otherwise take an existing report path for a
        # test path while it determines the rootdir.
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--skip-report={report}", *extra, "."],
        cwd=tmp_path / "suite",
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert report.is_file(), completed.stdout + completed.stderr
    return completed, json.loads(report.read_text())


@pytest.mark.parametrize("workers", [None, "2"])
def test_the_collector_records_outcomes_skips_and_capability_gates(tmp_path, workers):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(_INNER_CONFTEST)
    (suite / "test_cases.py").write_text(_INNER_TESTS)
    (suite / "test_module_skip.py").write_text('import pytest\npytest.skip("whole module", allow_module_level=True)\n')

    _, report = _run_inner(tmp_path, *(("-n", workers) if workers else ("-p", "no:xdist")))

    assert report["schema"] == "btrc.skip-report/1"
    assert report["runner"] == "macos"
    assert report["counts"] == {"passed": 1, "failed": 1, "error": 0, "skipped": 3, "xfailed": 1, "xpassed": 0}
    assert report["tests"]["test_cases.py::test_fails"] == "failed"
    assert report["tests"]["test_cases.py::test_known_defect"] == "xfailed"
    skips = {skip["nodeid"]: skip for skip in report["skips"]}
    assert set(skips) == {
        "test_cases.py::test_expected_skip",
        "test_cases.py::test_needs_a_simulator",
        "test_module_skip.py",
    }
    assert skips["test_cases.py::test_expected_skip"]["reason"] == "tool is not installed"
    assert skips["test_cases.py::test_expected_skip"]["when"] == "setup"
    assert re.fullmatch(r"test_cases\.py:\d+", skips["test_cases.py::test_expected_skip"]["location"])
    assert skips["test_module_skip.py"]["when"] == "collect"
    simulator = skips["test_cases.py::test_needs_a_simulator"]
    assert simulator["capability"] == "ios-simulator"
    assert "BTRC_TEST_CAPABILITIES=ios-simulator" in simulator["reason"]
    assert report["capability_gates"] == [
        {
            "available": False,
            "capability": "ios-simulator",
            "nodeid": "test_cases.py::test_needs_a_simulator",
            "reason": simulator["reason"],
        }
    ]
    # Classified against the tracked macOS manifest, none of these is expected there.
    assert report["manifest"]["runner"] == "macos"
    assert all(skip["expected"] is False for skip in report["skips"])
    # Variables are recorded by presence; only configuration words keep their values.
    assert report["environment"]["BTRC_TEST_RUNNER"] == "macos"
    assert report["environment"]["BTRC_PRIVATE_PATH"] == "set"
    assert set(report["tools"]) >= {"naga", "lldb", "pkg-config"}


def test_an_injected_unexpected_skip_fails_the_gate(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(_INNER_CONFTEST)
    (suite / "test_cases.py").write_text(
        "import pytest\n\n@pytest.mark.skip(reason='tool is not installed')\ndef test_a():\n    pass\n"
    )
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    _manifest(manifests, "macos", [_rule()])
    gate = [sys.executable, "-m", "tools.qualification", "skip-gate", "--manifests", str(manifests)]
    report = tmp_path / "out" / "skip-report.json"

    _run_inner(tmp_path, "-p", "no:xdist")
    clean = subprocess.run([*gate, str(report)], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    (suite / "test_injected.py").write_text(_INJECTED)
    _run_inner(tmp_path, "-p", "no:xdist")
    injected = subprocess.run([*gate, str(report)], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert injected.returncode == 1
    assert "UNEXPECTED test_injected.py::test_injected" in injected.stdout
    assert "an injected unexpected skip" in injected.stderr


# --- runners and target capabilities ---------------------------------------


@pytest.mark.parametrize(
    ("environ", "host", "containerized", "runner"),
    [
        ({"BTRC_TEST_RUNNER": "ios"}, "darwin", False, "ios"),
        ({}, "darwin", False, "macos"),
        ({}, "win32", False, "windows"),
        ({}, "linux", True, "linux-devcontainer"),
        ({}, "linux", False, "linux"),
    ],
)
def test_runner_identity(environ, host, containerized, runner):
    assert RunnerIdentity.detect(environ, host, containerized) == runner


def test_target_capabilities_are_absent_until_a_runner_grants_them():
    absent = capabilities.TargetCapabilities({}, "darwin")
    for name in sorted(capabilities.TARGET_CAPABILITIES):
        assert absent.error(name) == (
            f"{name} is not granted to this runner: an executor that provides it sets BTRC_TEST_CAPABILITIES={name}"
        )

    granted = capabilities.TargetCapabilities(
        {"BTRC_TEST_CAPABILITIES": "ios-simulator, windows-native,wayland,x11,audio-loopback", "DISPLAY": ":0"},
        "darwin",
    )
    assert granted.error("ios-simulator") is None
    assert granted.error("audio-loopback") is None
    assert granted.error("x11") is None
    assert granted.error("windows-native") == "windows-native is granted but unavailable: the host is not Windows"
    assert granted.error("wayland") == "wayland is granted but unavailable: WAYLAND_DISPLAY is unset"
    assert capabilities.TargetCapabilities({"BTRC_TEST_CAPABILITIES": "ios-simulator"}, "linux").error(
        "ios-simulator"
    ) == ("ios-simulator is granted but unavailable: iOS simulators run only on a macOS host")
    with pytest.raises(ValueError, match="unknown target capability"):
        granted.error("native-tray")


def test_the_corpus_directive_accepts_target_capabilities(tmp_path):
    source = tmp_path / "Program.btrc"
    source.write_text("// BTRC_TEST_REQUIRES: wayland, physical-device\nint main() { return 0; }\n")

    assert capabilities.declared_capabilities(source) == {"wayland", "physical-device"}
    source.write_text("// BTRC_TEST_REQUIRES: holodeck\n")
    with pytest.raises(ValueError, match="holodeck"):
        capabilities.declared_capabilities(source)


def test_capability_probes_record_their_verdicts(monkeypatch):
    capabilities.CapabilityGateLog.drain()
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "src/tests/x.py::test_y[a (b)] (call)")
    monkeypatch.delenv("BTRC_TEST_CAPABILITIES", raising=False)

    assert capabilities.target_capability_error("android-emulator") is not None

    @capabilities.CapabilityGateLog.gate("webgpu-toolchain")
    def probe():
        return ["-lwgpu"], None

    assert probe() == (["-lwgpu"], None)
    gates = capabilities.CapabilityGateLog.drain()
    assert [(gate["capability"], gate["available"], gate["nodeid"]) for gate in gates] == [
        ("android-emulator", False, "src/tests/x.py::test_y[a (b)]"),
        ("webgpu-toolchain", True, "src/tests/x.py::test_y[a (b)]"),
    ]
    assert capabilities.CapabilityGateLog.drain() == []


# --- the Makefile -----------------------------------------------------------


def _dry_run(*args: str) -> list[str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTEST_WORKERS", "PYTEST_ARGS", "PYTEST_SERIAL_ARGS", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"}
    }
    output = subprocess.run(
        ["make", "--dry-run", *args],
        cwd=REPO,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    ).stdout
    return [line.strip() for line in output.replace("\\\n", " ").splitlines()]


@pytest.mark.parametrize(
    "target",
    [
        ("test",),
        ("bootstrap",),
        ("test-shard-unit",),
        ("test-shard-btrc",),
        ("test-shard-corpus-python",),
        ("test-shard-corpus-btrc",),
        ("test-c11-one", "C11_CC=clang", "C11_OPT=O3"),
    ],
)
def test_every_gate_writes_its_own_skip_report_and_gates_it(target):
    lines = _dry_run(*target, "NIX=")
    sessions = [line for line in lines if "python3 -m pytest" in line]
    reports = [re.search(r"--skip-report=(\S+?\.json)", line).group(1) for line in sessions]
    gated = [re.search(r"skip-gate (\S+\.json)", line).group(1) for line in lines if "skip-gate" in line]

    assert sessions and len(set(reports)) == len(reports)
    assert all(report.startswith("build/skip-report") for report in reports)
    assert gated == reports


def test_the_boundary_gate_writes_its_report_for_the_ledger():
    lines = _dry_run("test-boundaries", "NIX=")
    assert any("boundary-check --report build/boundary-report.json" in line for line in lines)


def test_the_c11_matrix_gates_each_configuration():
    makefile = (REPO / "Makefile").read_text()
    recipe = makefile.split("\ntest-c11:", 1)[1].split("\n\n", 1)[0]

    assert "--skip-report=build/skip-report-c11-$$cc-$$opt.json" in recipe
    assert "$(SKIP_GATE) build/skip-report-c11-$$cc-$$opt.json || exit 1" in recipe
