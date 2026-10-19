"""The Stage 25 target runner core (CL-P1-17): protocol, registry, applicability, execution and ledger.

Scripted executors stand in for devices; the local executor runs real host
processes. Nothing here is target-device evidence.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.abi.hosted import TargetRepository
from src.tests.c_toolchains import host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.target_runner import (
    BUNDLE_SCHEMA,
    REPORT_SCHEMA,
    STRICT_CFLAGS,
    ApplicabilityManifest,
    BoundedCapture,
    BuildResult,
    ComputeRuntime,
    CorpusProgram,
    ExecutionRequest,
    ExecutionResult,
    ExecutorProtocolError,
    ExecutorRegistry,
    GoldenExpectation,
    InventoryCells,
    LocalExecutor,
    SourceRevision,
    TargetBundle,
    TargetCorpusRunner,
    TargetRows,
    TargetRunnerCommand,
)
from tools.native_plan import TargetToolchain
from tools.qualification.adapters import TargetRunAdapter
from tools.qualification.schema import (
    TARGET_SLICES,
    EvidenceStatus,
    LedgerDocument,
    LedgerSchemaError,
    Parity,
    Platform,
    Provenance,
)

REPO = Path(__file__).resolve().parents[3]
HOST = TargetRepository.host()
PROVENANCE = {"executor": "scripted", "device": "stand-in", "os_build": "none", "toolchain": {}}
needs_host = pytest.mark.skipif(HOST is None, reason="this interpreter's host is no compiler host row")
needs_cc = pytest.mark.skipif(host_c_compiler() is None, reason="requires a host C compiler")
posix_only = pytest.mark.skipif(os.name != "posix", reason="the local executor's process-group checks are POSIX")


def _result(**overrides):
    fields = {
        "exit_status": 0,
        "signal": None,
        "stdout": b"",
        "stderr": b"",
        "timed_out": False,
        "duration_s": 0.1,
        "provenance": dict(PROVENANCE),
    }
    fields.update(overrides)
    return ExecutionResult(**fields)


@dataclass
class ForeignResult:
    """A result type of another module, as the host spikes return."""

    exit_status: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    duration_s: float
    provenance: dict


# The frozen request and result -------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"program_id": "../escape"},
        {"program_id": ""},
        {"argv": ["list", "not", "tuple"]},
        {"argv": ("nul\0",)},
        {"stdin": "text"},
        {"env": {"BAD=NAME": "x"}},
        {"env": {"NAME": "nul\0"}},
        {"timeout_s": 0},
        {"timeout_s": math.nan},
        {"timeout_s": math.inf},
        {"timeout_s": True},
        {"cwd_policy": "ambient"},
        {"launch_mode": "service"},
        {"launch_mode": "app", "app_roots": ("files", "files")},
        {"launch_mode": "app", "app_roots": ("documents",)},
        {"app_roots": ("files",)},
    ],
)
def test_a_request_refuses_what_the_protocol_does_not_admit(overrides):
    with pytest.raises(ValueError):
        ExecutionRequest(**{"program_id": "reference-basics-X", **overrides})


def test_a_request_round_trips_through_its_bundle_pins():
    request = ExecutionRequest(
        "selfhost-stdlib-Fs",
        argv=("a b", ""),
        stdin=b"\0\xff",
        env={"Z": "1", "A": "2"},
        timeout_s=3.5,
        cwd_policy="bundle",
        launch_mode="app",
        app_roots=("files", "cache"),
    )
    pins = json.loads(json.dumps(request.pins()))
    assert ExecutionRequest.from_pins(request.program_id, pins) == request
    assert isinstance(request.env, dict)


def test_results_from_the_host_spikes_are_adopted():
    import tools.target_hosts.android.executor as android
    import tools.target_hosts.windows.executor as windows

    request = ExecutionRequest("reference-basics-X")
    for module in (windows, android):
        foreign = module.ExecutionResult(3, None, b"out", b"err", False, 0.25, dict(PROVENANCE))
        adopted = ExecutionResult.adopt(foreign, request)
        assert (adopted.exit_status, adopted.stdout, adopted.provenance["executor"]) == (3, b"out", "scripted")
        # The spikes accept the runner's request: they read the same fields.
        assert module.ExecutionRequest.__dataclass_fields__.keys() <= ExecutionRequest.__dataclass_fields__.keys()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"exit_status": 1, "signal": 6}, "exactly one"),
        ({"exit_status": None}, "exactly one"),
        ({"exit_status": 0, "timed_out": True}, "no exit status"),
        ({"exit_status": True}, "non-negative integer"),
        ({"exit_status": -1}, "non-negative integer"),
        ({"exit_status": None, "signal": 0}, "signal 0"),
        ({"stdout": "decoded"}, "raw bytes"),
        ({"timed_out": 1}, "bool"),
        ({"duration_s": -1.0}, "negative"),
        ({"duration_s": math.nan}, "finite"),
        ({"provenance": {"executor": "x"}}, "lacks device"),
        ({"provenance": {**PROVENANCE, "toolchain": object()}}, "JSON"),
        ({"provenance": {**PROVENANCE, "app_roots": {"files": "/data/files"}}}, "did not ask"),
    ],
)
def test_a_result_that_breaks_the_protocol_is_refused(overrides, message):
    fields = {
        "exit_status": 0,
        "signal": None,
        "stdout": b"",
        "stderr": b"",
        "timed_out": False,
        "duration_s": 0.1,
        "provenance": dict(PROVENANCE),
    }
    fields.update(overrides)
    with pytest.raises(ExecutorProtocolError, match=message):
        ExecutionResult.adopt(ForeignResult(**fields), ExecutionRequest("reference-basics-X"))


def test_a_result_lacking_a_field_is_refused():
    with pytest.raises(ExecutorProtocolError, match="lacks provenance"):
        ExecutionResult.adopt(
            type(
                "Partial",
                (),
                {"exit_status": 0, "signal": None, "stdout": b"", "stderr": b"", "timed_out": False, "duration_s": 0},
            )(),
            ExecutionRequest("reference-basics-X"),
        )


def test_a_timed_out_result_may_name_how_the_executor_stopped_it():
    adopted = ExecutionResult.adopt(_result(exit_status=None, signal=9, timed_out=True), ExecutionRequest("a"))
    assert adopted.timed_out and adopted.signal == 9


@pytest.mark.parametrize(
    "roots, message",
    [
        ({"files": "/data/app/files"}, "exactly"),
        ({"files": "/data/app/files", "cache": "relative/cache"}, "absolute"),
        ({"files": "/data/app/same", "cache": "/data/app/same"}, "same path"),
        ({"files": "/f", "cache": "/c", "documents": "/d"}, "exactly"),
    ],
)
def test_app_roots_must_match_the_request(roots, message):
    request = ExecutionRequest("a", launch_mode="app", app_roots=("files", "cache"))
    with pytest.raises(ExecutorProtocolError, match=message):
        ExecutionResult.adopt(_result(provenance={**PROVENANCE, "app_roots": roots}), request)
    valid = {"files": "/data/app/files", "cache": "/data/app/cache"}
    assert ExecutionResult.adopt(_result(provenance={**PROVENANCE, "app_roots": valid}), request).provenance[
        "app_roots"
    ]


# The registry ---------------------------------------------------------------


def test_the_registry_discovers_the_host_spikes_by_import():
    registry = ExecutorRegistry()
    assert {"local", "windows-native", "ios-simulator", "android-emulator"} <= set(registry.names())
    assert registry.spec("local") == "src.tests.target_runner:LocalExecutor"
    assert registry.spec("windows-native") == "tools.target_hosts.windows.executor:WindowsNativeExecutor"
    assert registry.spec("ios-simulator") == "tools.target_hosts.ios.executor:IOSSimulatorExecutor"
    assert registry.spec("android-emulator") == "tools.target_hosts.android.executor:AndroidEmulatorExecutor"
    assert registry.load("local") is LocalExecutor


def test_the_registry_constructs_an_executor_from_its_options(tmp_path):
    executor = ExecutorRegistry().create("android-emulator", {"sdk": str(tmp_path), "serial": "emulator-5554"})
    assert executor.serial == "emulator-5554"
    # Constructing the iOS simulator executor boots nothing: prepare does.
    simulator = ExecutorRegistry().create("ios-simulator", {"device_class": "ipad", "launch_timeout_s": "90"})
    assert (simulator.host.device_class, simulator.launch_timeout_s, simulator.host.udid) == ("ipad", 90.0, None)
    modes, policies = simulator.LAUNCH_MODES, simulator.CWD_POLICIES
    assert modes == {"process"} and policies == {"isolated", "bundle"}


def _host_package(tmp_path: Path, monkeypatch, source: str) -> ExecutorRegistry:
    package = tmp_path / "fakehosts"
    (package / "ios").mkdir(parents=True)
    (package / "ios" / "executor.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [module for module in sys.modules if module.startswith("fakehosts")]:
        monkeypatch.delitem(sys.modules, name)
    importlib.invalidate_caches()
    return ExecutorRegistry(root=package, package="fakehosts")


def test_the_registry_honours_a_declared_mapping_and_from_options(tmp_path, monkeypatch):
    registry = _host_package(
        tmp_path,
        monkeypatch,
        "TARGET_EXECUTORS = {'ios-simulator': 'Simulator'}\n"
        "class Simulator:\n"
        "    def __init__(self, mode): self.mode = mode\n"
        "    @classmethod\n"
        "    def from_options(cls, options): return cls(options.get('mode', 'spawn'))\n"
        "    def prepare(self, bundle_dir, label): pass\n"
        "    def run(self, request): pass\n"
        "    def close(self): pass\n",
    )
    assert "ios-simulator" in registry.names()
    assert registry.spec("ios-simulator") == "fakehosts.ios.executor:Simulator"
    assert registry.create("ios-simulator", {"mode": "app"}).mode == "app"
    assert registry.create("fakehosts.ios.executor:Simulator", {}).mode == "spawn"


@pytest.mark.parametrize(
    "source, message",
    [
        ("class Other:\n    pass\n", "no single executor class"),
        ("class IOSSimulatorExecutor:\n    def prepare(self, b, l): pass\n", "prepare, run and close"),
        ("TARGET_EXECUTORS = {}\n", "does not register"),
    ],
)
def test_the_registry_refuses_what_it_cannot_resolve(tmp_path, monkeypatch, source, message):
    registry = _host_package(tmp_path, monkeypatch, source)
    with pytest.raises(LookupError, match=message):
        registry.load("ios-simulator")


def test_the_registry_refuses_unknown_names():
    with pytest.raises(LookupError, match="unknown executor"):
        ExecutorRegistry().spec("toaster")


# Bundles and the local executor ----------------------------------------------

PROBE = r"""
#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "streams")) { fwrite("out\0\xff\n", 1, 6, stdout); fwrite("err\0\xfe\n", 1, 6, stderr); return 0; }
    if (!strcmp(mode, "exit")) return atoi(argv[2]);
    if (!strcmp(mode, "abort")) abort();
    if (!strcmp(mode, "stdin")) { int c; while ((c = getchar()) != EOF) putchar(c); return 0; }
    if (!strcmp(mode, "env")) { const char *value = getenv(argv[2]); printf("%s\n", value ? value : "(unset)"); return 0; }
    if (!strcmp(mode, "cwd")) {
        char path[4096]; int entries = 0; DIR *directory = opendir("."); struct dirent *entry;
        while ((entry = readdir(directory))) entries += strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..");
        closedir(directory);
        printf("%s %d\n", getcwd(path, sizeof path), entries);
        return 0;
    }
    if (!strcmp(mode, "flood")) { for (int i = 0; i < 4096; i++) fputs("0123456789abcdef", stdout); return 0; }
    if (!strcmp(mode, "tree") || !strcmp(mode, "orphan")) {
        pid_t child = fork();
        if (child == 0) { for (;;) pause(); }
        printf("%d\n", (int)child);
        fflush(stdout);
        if (!strcmp(mode, "orphan")) return 0;
        for (;;) pause();
    }
    return 2;
}
"""


def _host_row_document(programs: dict) -> dict:
    return {
        "schema": BUNDLE_SCHEMA,
        "target": {
            "label": HOST.label,
            "triple": HOST.triple,
            "operating_system": HOST.operating_system,
            "architecture": HOST.architecture,
        },
        "source_revision": SourceRevision.current(),
        "source_dirty": False,
        "toolchain": {"cc": ["cc"]},
        "programs": programs,
    }


@pytest.fixture(scope="module")
def probe_bundle(tmp_path_factory) -> Path:
    if HOST is None or host_c_compiler() is None or os.name != "posix":
        pytest.skip("requires a POSIX compiler host with a C compiler")
    directory = tmp_path_factory.mktemp("probe-bundle")
    source = directory / "probe.c"
    source.write_text(PROBE, encoding="utf-8")
    artifact = directory / "reference-probe"
    built = subprocess.run(
        [*host_c_compiler(), "-std=gnu11", str(source), "-o", str(artifact)],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    source.unlink()
    entry = {"source": "basics/X.btrc", "frontend": "reference", "status": "built", "artifact": artifact.name}
    entry.update(
        sha256=TargetBundle.digest(artifact),
        requires=[],
        request=ExecutionRequest("reference-probe").pins(),
        expected={},
    )
    TargetBundle(directory, _host_row_document({"reference-probe": entry})).write()
    return directory


@pytest.fixture
def local(probe_bundle):
    executor = LocalExecutor()
    executor.prepare(probe_bundle, HOST.label)
    yield executor
    executor.close()


def _run(executor, *argv, **options):
    request = ExecutionRequest("reference-probe", argv=argv, **options)
    return ExecutionResult.adopt(executor.run(request), request)


def _gone(pid: int, timeout: float = 5.0) -> bool:
    """Whether `pid` is dead; a zombie awaiting a late reaper counts as dead."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False
        ).stdout.strip()
        if not state or state.startswith("Z"):
            return True
        time.sleep(0.05)
    return False


@posix_only
@needs_cc
def test_the_local_executor_reports_streams_exits_and_signals(local):
    streams = _run(local, "streams")
    assert (streams.exit_status, streams.signal, streams.stdout, streams.stderr) == (
        0,
        None,
        b"out\0\xff\n",
        b"err\0\xfe\n",
    )
    assert _run(local, "exit", "124").exit_status == 124
    assert not _run(local, "exit", "137").timed_out
    aborted = _run(local, "abort")
    assert (aborted.exit_status, aborted.signal) == (None, 6)
    assert _run(local, "stdin", stdin=bytes(range(256)) * 64).stdout == bytes(range(256)) * 64
    assert _run(local, "env", "BTRC_PROBE", env={"BTRC_PROBE": "value with spaces"}).stdout == b"value with spaces\n"
    assert {"executor", "device", "os_build", "toolchain"} <= local.run(
        ExecutionRequest("reference-probe")
    ).provenance.keys()


@posix_only
@needs_cc
def test_the_local_executor_runs_in_an_empty_private_cwd(local, probe_bundle):
    first, second = (_run(local, "cwd").stdout.decode().split() for _ in range(2))
    assert first[1] == "0" and second[1] == "0", "the isolated cwd holds no control files"
    assert first[0] != second[0], "each run gets a fresh directory"
    assert not Path(first[0]).exists(), "the cwd is removed after the run"
    bundle_cwd = _run(local, "cwd", cwd_policy="bundle").stdout.decode().split()[0]
    assert Path(bundle_cwd).resolve() != probe_bundle.resolve(), "bundle cwd is the staged copy's, not the bundle's"


@posix_only
@needs_cc
@pytest.mark.parametrize("mode", ["tree", "orphan"])
def test_the_local_executor_leaves_no_descendant_behind(local, mode):
    result = _run(local, mode, timeout_s=1.0)
    assert result.timed_out is (mode == "tree")
    assert result.exit_status == (None if mode == "tree" else 0)
    child = int(result.stdout.split()[0])
    assert _gone(child), f"descendant {child} outlived its run"


@posix_only
@needs_cc
def test_the_local_executor_bounds_output_by_failing(local, monkeypatch):
    monkeypatch.setattr(BoundedCapture, "LIMIT", 1024)
    with pytest.raises(RuntimeError, match="exceeded 1024 bytes"):
        local.run(ExecutionRequest("reference-probe", argv=("flood",)))


@posix_only
@needs_cc
def test_local_admission_is_atomic_and_checks_digests(probe_bundle, tmp_path):
    executor = LocalExecutor()
    executor.prepare(probe_bundle, HOST.label)
    tampered = tmp_path / "tampered"
    shutil.copytree(probe_bundle, tampered)
    (tampered / "reference-probe").write_bytes(b"replaced")
    with pytest.raises(ValueError, match="does not match"):
        executor.prepare(tampered, HOST.label)
    # The failed admission left the earlier one in force.
    assert _run(executor, "exit", "3").exit_status == 3
    executor.close()
    executor.close()
    with pytest.raises(RuntimeError, match="prepare"):
        executor.run(ExecutionRequest("reference-probe"))
    other = next(row.label for row in TARGET_ROWS if row.label != HOST.label)
    with pytest.raises(ValueError, match="only this host's row"):
        LocalExecutor().prepare(probe_bundle, other)


@needs_host
@pytest.mark.parametrize("name", ["../outside", "sub/artifact", "..", "missing"])
def test_a_bundle_artifact_must_be_a_regular_file_in_the_bundle(tmp_path, name):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "artifact").write_bytes(b"x")
    (tmp_path.parent / "outside").write_bytes(b"x")
    entry = {"source": "a.btrc", "frontend": "reference", "status": "built", "artifact": name, "sha256": "0" * 64}
    (tmp_path / TargetBundle.MANIFEST).write_text(
        json.dumps(_host_row_document({"reference-x": entry})), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"file name|regular file"):
        TargetBundle.load(tmp_path)


def test_a_bundle_directory_is_replaced_only_when_it_holds_a_bundle(tmp_path):
    (tmp_path / "keep.txt").write_text("precious", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing"):
        TargetBundle.prepare_directory(tmp_path)
    assert (tmp_path / "keep.txt").is_file()


# Golden comparison -------------------------------------------------------------


def test_golden_comparison_matches_the_corpus_runner():
    golden = GoldenExpectation(b"PASS one\nline two\n", b"")
    assert golden.mismatch(_result(stdout=b"PASS one\r\nline two\r\n")) is None, "universal newlines, as text mode"
    assert "line 2" in golden.mismatch(_result(stdout=b"PASS one\nline 2\n"))
    assert "no PASS" in golden.mismatch(_result(stdout=b"FAIL\n"))
    assert "stderr differs" in golden.mismatch(_result(stdout=b"PASS one\nline two\n", stderr=b"warning\n"))
    assert "status 1" in golden.mismatch(_result(exit_status=1))
    assert "signal 11" in golden.mismatch(_result(exit_status=None, signal=11))
    assert "timed out" in golden.mismatch(_result(exit_status=None, timed_out=True))
    assert "not UTF-8" in golden.mismatch(_result(stdout=b"PASS \xff\n"))
    pins = golden.pins()
    assert pins["exit_status"] == 0 and pins["stdout_contains"] == "PASS" and pins["newlines"] == "universal"


# Applicability -------------------------------------------------------------------


def test_the_applicability_manifest_loads_and_its_citations_hold():
    manifest = ApplicabilityManifest.load()
    inventory = manifest.inventory
    for entry in manifest.programs:
        match = ApplicabilityManifest.INVENTORY_CITE.fullmatch(entry["cites"])
        if match is None:
            continue
        cell = inventory.cell(match["row"], match["slice"])
        # A program is missing only where the inventory itself says the topic is incomplete.
        if entry["status"] == "missing":
            assert cell.get("implementation") != "implemented", entry
        # An entry cites the cell of its own target slice, and of no other.
        mapped = {label for label, name in TargetRunAdapter.ROW_SLICES.items() if name == match["slice"]}
        assert entry["targets"] <= mapped | {"windows-aarch64-msvc"}, f"{entry['paths']} cites another slice"
        topics = {path.split("/", 1)[0] for path in entry["paths"]}
        assert {f"corpus.{topic}" for topic in topics} == {match["row"]}, f"{entry['paths']} cites another topic"
    assert manifest.facility(ComputeRuntime.FACILITY) is not None
    assert "loopback-listener" in manifest.capabilities


def _manifest(tmp_path: Path, programs=(), inventory: str | None = None, **extra) -> ApplicabilityManifest:
    document = {"schema": "btrc.target-applicability/1", "programs": list(programs), **extra}
    cells = InventoryCells()
    if inventory is not None:
        path = tmp_path / "inventory.toml"
        path.write_text(inventory, encoding="utf-8")
        cells = InventoryCells(path)
    return ApplicabilityManifest(document, cells, [program.source for program in CorpusProgram.select()])


ENTRY = {
    "paths": ["strings/Regex*.btrc"],
    "targets": ["windows-x86_64"],
    "status": "missing",
    "scope": "build",
    "reason": "regex.h has no Windows provider",
    "cites": "corpus.strings@windows-x64",
}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"reason": " "}, "reason"),
        ({"paths": ["strings/Regex.btrc", "strings/NoSuchProgram.btrc"]}, "matches no corpus program"),
        ({"paths": "strings/Regex.btrc"}, "paths must list"),
        ({"paths": []}, "paths must list"),
        ({"targets": ["windows-x64"]}, "targets.toml labels"),
        ({"status": "skipped"}, "status"),
        ({"scope": "always"}, "scope"),
        ({"cites": "corpus.strings@windows"}, "no platform-inventory cell"),
        ({"cites": "docs/no-such-contract#anchor"}, "does not exist"),
        ({"cites": "because"}, "cite an inventory cell"),
        ({"frontends": ["python"]}, "frontends"),
        ({"unexpected": 1}, "unknown"),
    ],
)
def test_the_manifest_refuses_unsupported_entries(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        _manifest(tmp_path, [{**ENTRY, **change}])


def test_the_manifest_refuses_two_entries_deciding_one_program(tmp_path):
    overlapping = {**ENTRY, "paths": ["strings/Regex.btrc"], "frontends": ["selfhost"], "status": "restricted"}
    with pytest.raises(ValueError, match=r"both decide strings/Regex\.btrc"):
        _manifest(tmp_path, [ENTRY, overlapping])
    other_target = {**overlapping, "targets": ["windows-aarch64"]}
    assert len(_manifest(tmp_path, [ENTRY, other_target]).programs) == 2


def test_verdicts_come_from_the_manifest_then_the_inventory(tmp_path):
    inventory = (
        "[[rows]]\nkind = 'operation'\nid = 'corpus.strings'\n"
        "windows-x64 = { parity = 'os-restricted', implementation = 'implemented', reason = 'no console' }\n"
        "android-arm64 = { parity = 'equivalent', implementation = 'missing', reason = 'not ported' }\n"
    )
    entry = {
        **ENTRY,
        "paths": ["strings/FstringBasic.btrc"],
        "frontends": ["selfhost"],
        "cites": "corpus.strings@android-arm64",
    }
    entry["targets"] = ["android-aarch64"]
    manifest = _manifest(tmp_path, [entry], inventory)
    regex, escapes = CorpusProgram("strings/Regex.btrc"), CorpusProgram("strings/FstringBasic.btrc")
    restricted = manifest.program_verdict(regex, "windows-x86_64", "reference")
    assert (restricted.status, restricted.scope, restricted.cites) == (
        "restricted",
        "build",
        "corpus.strings@windows-x64",
    )
    assert manifest.program_verdict(escapes, "android-aarch64", "selfhost").reason == ENTRY["reason"]
    assert manifest.program_verdict(escapes, "android-aarch64", "reference").status == "missing", "the topic cell"
    assert manifest.program_verdict(regex, "linux-x86_64", "reference") is None


def test_capability_verdicts_follow_the_executor(tmp_path):
    grant = {"name": "loopback-listener", "executors": ["windows-native"], "reason": "sockets", "cites": ENTRY["cites"]}
    manifest = _manifest(tmp_path, capabilities=[grant])
    assert manifest.capability_verdict("loopback-listener", "windows-native", None) is None
    denied = manifest.capability_verdict("loopback-listener", "android-emulator", None)
    assert (denied.status, denied.scope) == ("restricted", "run") and "sockets" in denied.reason
    assert manifest.capability_verdict("loopback-listener", "local", frozenset({"loopback-listener"})) is None
    assert manifest.capability_verdict("loopback-listener", "windows-native", frozenset()) is not None
    assert manifest.capability_verdict("ios-simulator", "ios-simulator", None) is None
    assert manifest.capability_verdict("ios-simulator", "local", frozenset()).scope == "run"


def test_a_row_without_a_compute_runtime_reports_dispatching_programs_missing():
    facility = ApplicabilityManifest.load().facility(ComputeRuntime.FACILITY)
    cross = next(row for row in TARGET_ROWS if row != HOST)
    verdict = ComputeRuntime.verdict(cross, ((), ()), facility)
    assert (verdict.status, verdict.scope, verdict.cites) == ("missing", "build", facility.cites)
    if HOST is not None:
        unbuilt = ComputeRuntime.verdict(HOST, "Compute runtime not built (run make gpu)", facility)
        assert (unbuilt.status, unbuilt.reason) == ("missing", "Compute runtime not built (run make gpu)")
        assert ComputeRuntime.verdict(HOST, (("-Ia",), ("-lb",)), facility) == (("-Ia",), ("-lb",))


def test_compute_flags_split_between_compile_and_link():
    compile_flags, link_flags = ComputeRuntime.split(
        ["-I/a", "-isystem", "/b", "-DX=1", "-L/c", "-lw", "-framework", "Metal"]
    )
    assert compile_flags == ["-I/a", "-isystem", "/b", "-DX=1"]
    assert link_flags == ["-L/c", "-lw", "-framework", "Metal"]


# The runner, end to end ---------------------------------------------------------


class ScriptedExecutor:
    """Answers each program id from a script and records the protocol calls it received."""

    def __init__(self, script):
        self.script = script
        self.events = []

    def prepare(self, bundle_dir, label):
        TargetBundle.load(Path(bundle_dir))
        self.events.append(("prepare", label))

    def run(self, request):
        self.events.append(("run", request.program_id))
        answer = self.script[request.program_id]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        self.events.append(("close",))


class FixedRegistry(ExecutorRegistry):
    def __init__(self, executor):
        super().__init__()
        self.executor = executor

    def create(self, name, options=None):
        return self.executor


def _fake_bundle(directory: Path, label: str, sources: list[str]) -> TargetBundle:
    row = TargetRows.row(label)
    document = {
        "schema": BUNDLE_SCHEMA,
        "target": {
            "label": label,
            "triple": row.triple,
            "operating_system": row.operating_system,
            "architecture": row.architecture,
        },
        "source_revision": SourceRevision.current(),
        "source_dirty": False,
        "selection": sources,
        "toolchain": {"cc": ["stand-in"]},
        "programs": {},
    }
    directory.mkdir(parents=True, exist_ok=True)
    for source in sources:
        program = CorpusProgram(source)
        identifier = program.program_id("reference")
        artifact = directory / f"{identifier}{TargetRows.suffix(row)}"
        artifact.write_bytes(f"stand-in {identifier}".encode())
        build = BuildResult(
            source, "reference", identifier, "built", artifact=artifact.name, sha256=TargetBundle.digest(artifact)
        )
        request = TargetCorpusRunner.request_for(identifier)
        document["programs"][identifier] = build.entry(
            request, GoldenExpectation.of(program).pins(), program.requires()
        )
    bundle = TargetBundle(directory.resolve(), document)
    bundle.write()
    return bundle


SCRIPTED = [
    "basics/AddrDeref.btrc",
    "basics/ArrayOfPointers.btrc",
    "basics/AssignChainAndValue.btrc",
    "basics/AutoInclude.btrc",
    "stdlib/HttpSocketIo.btrc",
]


def _passing(source: str) -> ExecutionResult:
    return _result(stdout=CorpusProgram(source).stdout_golden.read_bytes())


def test_the_runner_reports_every_outcome_and_writes_its_ledger(tmp_path):
    label = "android-x86_64"
    bundle = _fake_bundle(tmp_path / "bundle", label, SCRIPTED)
    executor = ScriptedExecutor(
        {
            "reference-basics-AddrDeref": _passing("basics/AddrDeref.btrc"),
            "reference-basics-ArrayOfPointers": _result(stdout=b"PASS but different\n"),
            "reference-basics-AssignChainAndValue": RuntimeError("adb transport lost"),
            "reference-basics-AutoInclude": ForeignResult(1, 6, b"", b"", False, 0.1, PROVENANCE),
        }
    )
    runner = TargetCorpusRunner(
        label, ("reference",), output=tmp_path / "run", executor="android-emulator", registry=FixedRegistry(executor)
    )
    report = runner.run(execute_bundle=bundle.directory)
    assert report.counts() == {"reference": {"passed": 1, "failed": 3, "restricted": 1, "missing": 0}}
    outcomes = {outcome.program: outcome for outcome in report.outcomes}
    assert outcomes["basics/ArrayOfPointers.btrc"].phase == "compare"
    assert outcomes["basics/AssignChainAndValue.btrc"].observed == "error"
    assert "exactly one" in outcomes["basics/AutoInclude.btrc"].reason
    restricted = outcomes["stdlib/HttpSocketIo.btrc"]
    assert restricted.status == "restricted" and "loopback-listener" in restricted.reason
    assert ("run", "reference-stdlib-HttpSocketIo") not in executor.events, "a restricted program is never run"
    assert executor.events[0] == ("prepare", label) and executor.events[-1] == ("close",)
    assert report.failed

    run = tmp_path / "run"
    assert (run / "reference/basics/AddrDeref.stdout").read_bytes() == CorpusProgram(
        "basics/AddrDeref.btrc"
    ).stdout_golden.read_bytes()
    assert json.loads((run / "reference/stdlib/HttpSocketIo.json").read_text())["status"] == "restricted"
    summary = json.loads((run / "target-run.json").read_text())
    assert summary["schema"] == REPORT_SCHEMA and summary["executor"] == "android-emulator"
    cases = ElementTree.parse(run / "junit.xml").getroot().findall("testcase")
    assert len(cases) == len(SCRIPTED) and sum(case.find("failure") is not None for case in cases) == 3
    records = {record.subject.id: record for record in LedgerDocument.load(run / "ledger.jsonl")}
    passed = records["src/tests/target_runner.py::run[basics/AddrDeref.btrc]"]
    assert (passed.subject.platform, passed.subject.variant) == (Platform.ANDROID, "x86_64")
    assert passed.evidence.status is EvidenceStatus.PASSED and passed.provenance.runner == "android-emulator"
    assert passed.provenance.cpu is None, "a device run never records the ingesting host's hardware"
    assert records["src/tests/target_runner.py::run[basics/AssignChainAndValue.btrc]"].evidence.observed == "error"
    socket = records["src/tests/target_runner.py::run[stdlib/HttpSocketIo.btrc]"]
    assert socket.classification.parity is Parity.OS_RESTRICTED
    assert socket.evidence.status is EvidenceStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "tamper, message",
    [
        (
            lambda document, directory: document["programs"]["reference-basics-AddrDeref"]["expected"].update(
                stdout_sha256="0" * 64
            ),
            "expected outcome",
        ),
        (
            lambda document, directory: document["programs"]["reference-basics-AddrDeref"]["request"].update(
                argv=["extra"]
            ),
            "different request",
        ),
        (
            lambda document, directory: document["programs"]["reference-basics-AddrDeref"].update(
                requires=["loopback-listener"]
            ),
            "requirements",
        ),
        (lambda document, directory: document.update(source_revision="0" * 40), "this checkout is"),
        (lambda document, directory: (directory / "reference-basics-AddrDeref").write_bytes(b"swapped"), "digest"),
        (lambda document, directory: document["programs"].pop("reference-basics-AddrDeref"), "has no"),
        (lambda document, directory: document["target"].update(label="linux-aarch64"), "built for"),
    ],
)
def test_bundle_admission_refuses_changed_pins(tmp_path, tamper, message):
    label = "linux-x86_64"
    bundle = _fake_bundle(tmp_path / "bundle", label, ["basics/AddrDeref.btrc"])
    tamper(bundle.document, bundle.directory)
    bundle.write()
    executor = ScriptedExecutor({})
    runner = TargetCorpusRunner(
        label,
        ("reference",),
        output=tmp_path / "run",
        programs=["basics/AddrDeref.btrc"],
        registry=FixedRegistry(executor),
    )
    with pytest.raises(ExecutorProtocolError, match=message):
        runner.run(execute_bundle=bundle.directory)
    assert executor.events == [], "nothing runs from a refused bundle"


def test_an_executor_that_refuses_the_bundle_fails_the_run(tmp_path):
    bundle = _fake_bundle(tmp_path / "bundle", "linux-x86_64", ["basics/AddrDeref.btrc"])

    class Refusing(ScriptedExecutor):
        def prepare(self, bundle_dir, label):
            raise ValueError("emulated architecture")

    executor = Refusing({})
    runner = TargetCorpusRunner(
        "linux-x86_64", ("reference",), output=tmp_path / "run", registry=FixedRegistry(executor)
    )
    with pytest.raises(ExecutorProtocolError, match="refused the bundle"):
        runner.run(execute_bundle=bundle.directory)
    assert executor.events == [("close",)], "a refused admission still closes the executor"


@needs_host
@needs_cc
def test_the_runner_builds_runs_and_excludes_through_the_reference_frontend(tmp_path):
    cites = "src/tests/target_runner.py#ApplicabilityManifest"
    entries = [
        {
            "paths": ["strings/BracesInCodeGen.btrc"],
            "targets": [HOST.label],
            "status": "restricted",
            "scope": "run",
            "reason": "stand-in run restriction",
            "cites": cites,
        },
        {
            "paths": ["basics/ArrayOfPointers.btrc"],
            "targets": [HOST.label],
            "status": "missing",
            "scope": "build",
            "reason": "stand-in build gap",
            "cites": cites,
        },
    ]
    programs = ["basics/AddrDeref.btrc", "strings/BracesInCodeGen.btrc", "basics/ArrayOfPointers.btrc"]
    runner = TargetCorpusRunner(
        HOST.label, ("reference",), output=tmp_path / "run", programs=programs, manifest=_manifest(tmp_path, entries)
    )
    report = runner.run()
    assert report.counts() == {"reference": {"passed": 1, "failed": 0, "restricted": 1, "missing": 1}}, report.lines()
    bundle = TargetBundle.load(tmp_path / "run" / "bundle")
    statuses = {identifier: entry["status"] for identifier, entry in bundle.programs.items()}
    assert statuses == {
        "reference-basics-AddrDeref": "built",
        "reference-strings-BracesInCodeGen": "built",
        "reference-basics-ArrayOfPointers": "missing",
    }
    assert bundle.document["toolchain"]["cflags"] == list(STRICT_CFLAGS)
    records = LedgerDocument.load(tmp_path / "run" / "ledger.jsonl")
    assert {record.evidence.observed for record in records} == {"passed", "restricted", "missing"}


@needs_host
@needs_cc
def test_both_frontends_build_a_bundle_the_local_executor_runs(tmp_path, immutable_btrcc):
    programs = ["basics/AddrDeref.btrc"]
    build = TargetCorpusRunner(
        HOST.label, ("reference", "selfhost"), output=tmp_path / "built", programs=programs, btrcc=immutable_btrcc
    )
    compiled = build.run(compile_only=True)
    assert compiled.counts() == {
        frontend: {"passed": 1, "failed": 0, "restricted": 0, "missing": 0} for frontend in ("reference", "selfhost")
    }
    ledger = LedgerDocument.load(tmp_path / "built" / "ledger.jsonl")
    assert {record.subject.id for record in ledger} == {"src/tests/target_runner.py::build[basics/AddrDeref.btrc]"}
    assert {record.evidence.observed for record in ledger} == {"built"}
    executed = TargetCorpusRunner(HOST.label, ("reference", "selfhost"), output=tmp_path / "ran").run(
        execute_bundle=tmp_path / "built" / "bundle"
    )
    assert executed.counts() == compiled.counts(), executed.lines()
    assert {outcome.result.provenance["executor"] for outcome in executed.outcomes} == {"local"}


@pytest.mark.parametrize("label", ["windows-x86_64", "windows-aarch64"])
def test_the_strict_flags_keep_every_assert_live_under_zig(tmp_path, label):
    """zig cc's -O2 defines NDEBUG; a corpus program's asserts must still run on the target."""

    if shutil.which("zig") is None:
        pytest.skip("requires zig for the windows-gnu rows")
    source = tmp_path / "probe.c"
    source.write_text(
        "#include <assert.h>\n#ifdef NDEBUG\n#error NDEBUG compiles out the program's asserts\n#endif\n"
        "int main(void) { assert(1); return 0; }\n",
        encoding="utf-8",
    )
    toolchain = TargetToolchain(TargetRows.row(label))
    for flags, compiles in (
        (STRICT_CFLAGS, True),
        (tuple(flag for flag in STRICT_CFLAGS if flag != "-UNDEBUG"), False),
    ):
        command = toolchain.compile_command(source, tmp_path / "probe.o", generated=True, flags=list(flags))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert (completed.returncode == 0) == compiles, (flags, completed.stderr)


@needs_cc
def test_a_windows_bundle_is_admitted_by_the_windows_host_spike(tmp_path):
    if shutil.which("zig") is None:
        pytest.skip("requires zig for the windows-gnu rows")
    from tools.target_hosts.windows.executor import WindowsNativeExecutor

    runner = TargetCorpusRunner(
        "windows-x86_64", ("reference",), output=tmp_path / "run", programs=["basics/AddrDeref.btrc"]
    )
    report = runner.run(compile_only=True)
    assert report.counts()["reference"]["passed"] == 1, report.lines()
    bundle = tmp_path / "run" / "bundle"
    # The executor admits the runner's bundle.json itself, for its own row only.
    executor = WindowsNativeExecutor(machine=lambda: 0x8664)
    try:
        executor.prepare(bundle, "windows-x86_64")
        assert set(executor.programs) == {"reference-basics-AddrDeref"}
        staged = executor.programs["reference-basics-AddrDeref"].path
        assert staged.read_bytes() == (bundle / "reference-basics-AddrDeref.exe").read_bytes()
        assert bundle not in staged.parents, "only the private staged copy is launched"
        with pytest.raises(ValueError, match="built for"):
            executor.prepare(bundle, "windows-aarch64")
        assert executor.label == "windows-x86_64", "a refused admission keeps the admitted bundle"
    finally:
        executor.close()
    with pytest.raises(ValueError, match="emulated"):
        WindowsNativeExecutor(machine=lambda: 0xAA64).prepare(bundle, "windows-x86_64")
    records = LedgerDocument.load(tmp_path / "run" / "ledger.jsonl")
    assert [(record.subject.platform, record.subject.variant) for record in records] == [(Platform.WINDOWS, "x86_64")]


# The ledger adapter -----------------------------------------------------------------


def test_every_target_row_maps_to_one_ledger_slot():
    labels = {row.label for row in TARGET_ROWS}
    assert set(TargetRunAdapter.ROW_SLICES) | set(TargetRunAdapter.OTHER_ROWS) == labels
    assert not set(TargetRunAdapter.ROW_SLICES) & set(TargetRunAdapter.OTHER_ROWS)
    assert sorted(TargetRunAdapter.ROW_SLICES.values()) == sorted(TARGET_SLICES)
    for label, slice_name in TargetRunAdapter.ROW_SLICES.items():
        assert TargetRunAdapter.slot(label) == TARGET_SLICES[slice_name]
    slots = {TargetRunAdapter.slot(label) for label in labels}
    assert len(slots) == len(labels), "two rows would overwrite each other's results"


def _report(**overrides) -> dict:
    report = {
        "schema": REPORT_SCHEMA,
        "target": {"label": "ios-aarch64-simulator", "triple": "arm64-apple-ios17.0.0-simulator"},
        "mode": "execute",
        "executor": "ios-simulator",
        "executor_provenance": {"executor": "ios-simulator", "device": "iPhone", "os_build": "iOS 26.4"},
        "frontends": ["reference", "selfhost"],
        "source_revision": "a" * 40,
        "finished_at": "2026-10-17T00:00:00+00:00",
        "compilers": {"selfhost": {"btrcc_sha256": "b" * 64}},
        "counts": {
            "reference": {"passed": 1, "failed": 0, "restricted": 0, "missing": 1},
            "selfhost": {"passed": 0, "failed": 1, "restricted": 1, "missing": 0},
        },
        "results": [
            {
                "program": "basics/A.btrc",
                "frontend": "reference",
                "status": "passed",
                "observed": "passed",
                "artifact": "reference/basics/A.json",
            },
            {
                "program": "basics/B.btrc",
                "frontend": "reference",
                "status": "missing",
                "observed": "missing",
                "reason": "no regex.h",
                "cites": "corpus.strings@ios-simulator",
            },
            {
                "program": "basics/A.btrc",
                "frontend": "selfhost",
                "status": "failed",
                "observed": "error",
                "phase": "execute",
                "reason": "simctl lost",
            },
            {
                "program": "basics/B.btrc",
                "frontend": "selfhost",
                "status": "restricted",
                "observed": "restricted",
                "reason": "fork",
                "cites": "corpus.stdlib@ios-simulator",
            },
        ],
    }
    report.update(overrides)
    return report


def test_the_target_run_adapter_records_every_program():
    records = TargetRunAdapter(Provenance(btrc_revision="ignored")).records(
        _report(), artifact="build/target-runs/x/target-run.json"
    )
    assert len(records) == 4
    by = {(record.subject.id, record.subject.frontend.value): record for record in records}
    passed = by[("src/tests/target_runner.py::run[basics/A.btrc]", "reference")]
    assert (passed.subject.platform, passed.subject.variant) == (Platform.IOS, "arm64-simulator")
    assert passed.evidence.artifact == "build/target-runs/x/reference/basics/A.json"
    assert passed.provenance.btrc_revision == "a" * 40 and passed.provenance.os_build == "iOS 26.4"
    assert passed.provenance.compiler_digest is None
    failed = by[("src/tests/target_runner.py::run[basics/A.btrc]", "selfhost")]
    assert failed.evidence.observed == "error" and failed.provenance.compiler_digest == "sha256:" + "b" * 64
    missing = by[("src/tests/target_runner.py::run[basics/B.btrc]", "reference")]
    assert (
        missing.classification.parity is Parity.MISSING
        and missing.classification.decision == "corpus.strings@ios-simulator"
    )
    compile_only = TargetRunAdapter(Provenance()).records(
        _report(mode="compile-only", executor=None, executor_provenance=None)
    )
    assert (
        compile_only[0].subject.id.startswith("src/tests/target_runner.py::build[")
        and compile_only[0].evidence.observed == "built"
    )
    assert compile_only[0].provenance.runner == "compile-only"


@pytest.mark.parametrize(
    "change, message",
    [
        ({"schema": "other"}, "not a btrc.target-run/1"),
        ({"surprise": 1}, "unknown field"),
        ({"mode": "dry"}, "mode"),
        ({"target": {"label": "plan9-mips"}}, "no platform slice"),
        ({"counts": {"reference": {"passed": 2}, "selfhost": {}}}, "disagrees"),
        ({"frontends": ["python"]}, "frontends"),
    ],
)
def test_the_target_run_adapter_refuses_inconsistent_reports(change, message):
    with pytest.raises(LedgerSchemaError, match=message):
        TargetRunAdapter(Provenance()).records(_report(**change))


def test_the_target_run_adapter_refuses_duplicate_or_unreasoned_results():
    report = _report()
    report["results"].append(dict(report["results"][0]))
    with pytest.raises(LedgerSchemaError, match="twice"):
        TargetRunAdapter(Provenance()).records(report)
    report = _report()
    report["results"][1] = {**report["results"][1], "cites": None}
    with pytest.raises(LedgerSchemaError, match="reason and what it cites"):
        TargetRunAdapter(Provenance()).records(report)
    report = _report()
    report["results"].pop()
    report["counts"]["selfhost"]["restricted"] = 0
    with pytest.raises(LedgerSchemaError, match="same programs"):
        TargetRunAdapter(Provenance()).records(report)


# The command line -------------------------------------------------------------------


def test_the_command_lists_executors(capsys):
    assert TargetRunnerCommand.main(["--list-executors"]) == 0
    listed = dict(line.split("\t") for line in capsys.readouterr().out.splitlines())
    assert listed["windows-native"] == "tools.target_hosts.windows.executor:WindowsNativeExecutor"


@pytest.mark.parametrize(
    "argv",
    [
        ["--execute-bundle", "x", "--compile-only"],
        ["--frontend", "reference"],
        ["--target", "linux-x86_64", "--executor-option", "novalue"],
    ],
)
def test_the_command_refuses_contradictory_arguments(argv):
    with pytest.raises(SystemExit) as raised:
        TargetRunnerCommand.main(argv)
    assert raised.value.code == 2


def test_the_command_reports_usage_errors_without_a_traceback(capsys):
    assert TargetRunnerCommand.main(["--target", "plan9-mips", "--frontend", "reference"]) == 2
    assert "unknown target" in capsys.readouterr().err


def test_the_module_docstring_freezes_protocol_version_one():
    from src.tests import target_runner

    text = target_runner.__doc__
    assert "Executor protocol, version 1 (frozen" in text
    for name in (
        *ExecutionRequest.__dataclass_fields__,
        *ExecutionResult.FIELDS,
        "prepare(bundle_dir, label)",
        "close()",
    ):
        assert name in text, name
    manifest = tomllib.loads((REPO / "src/tests/fixtures/target-applicability.toml").read_text(encoding="utf-8"))
    assert manifest["schema"] == ApplicabilityManifest.SCHEMA
