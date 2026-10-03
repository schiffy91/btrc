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
    HARDWARE_CAPABILITIES,
    HOSTED_CATEGORIES,
    HOSTED_RUNNERS,
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

# Representative skips from the 1cadaf4 `make test` record on macOS and from
# macOS CI run 36934014516. That record's DAP session skip was lldb's; since
# stage2/lldbenv the dev shell runs those sessions, and the one skip a Mac
# still expects is developer mode off.
MACOS_SKIPS = [
    (
        "src/tests/debug/test_dap_session.py::test_stop_on_entry",
        "needs macOS developer mode for lldb to launch an inferior (sudo /usr/sbin/DevToolsSecurity -enable)",
    ),
    (
        "src/tests/python/test_native_macro_constants.py::test_freetype_macro_constants_build_and_run[python]",
        "the FreeType proof builds against the Linux SDK",
    ),
    (
        "src/tests/python/test_emitted_units.py::test_split_units_link_and_run_like_one[btrcpy]",
        "needs a Linux C toolchain",
    ),
    ("src/tests/python/test_cache_invalidation.py::test_cache_dir_xdg_respected", "XDG only used off-macOS"),
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
    # macOS run 36905763175 (962c7dc) failed its gate on the Linux FreeType case,
    # which skips off Linux. Its pugixml skip predates the Darwin shells' pugixml.
    (
        "src/tests/python/test_native_font_runtime.py::test_linux_freetype_draws_into_owned_pixels[True-selfhost]",
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

    assert {"macos", "macos-hosted", "linux-devcontainer", "windows"} <= set(manifests)
    assert set(manifests) <= set(RUNNERS)
    assert all(manifests[runner].enforce for runner in ("macos", "macos-hosted", "linux-devcontainer", "windows"))
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
    # CI's Linux shards run the GUI windows under Xvfb, so only the tray stays uncovered.
    assert rules[MACOS_SKIPS[8][0]].id == "linux-native-reader-covered"
    assert (
        manifest.classify(
            "src/tests/python/test_native_tray_runtime.py::test_x",
            "requires Linux and the explicitly built native header reader",
        ).id
        == "linux-native-reader-uncovered"
    )
    assert rules[MACOS_SKIPS[1][0]].id == "linux-freetype-macro-constants"
    assert rules[MACOS_SKIPS[9][0]].id == "linux-native-reader-covered"
    # The dev shell provides naga (stage2/nix, e74a3cc), so a naga skip is unexpected again.
    assert (
        manifest.classify("src/tests/python/test_wgsl_semantics.py::test_x", "naga WGSL validator is not installed")
        is None
    )
    # The Darwin dev shells carry pugixml, sqlite3 and the native compiler
    # provider (stage4/tools-ci, 88a5c36), so those skips are unexpected again.
    for nodeid, reason in (
        (
            "src/tests/python/test_native_compiler_context.py::test_x",
            "build native reader and configure its native compiler provider",
        ),
        (
            "src/tests/python/test_native_preprocess_consumer.py::test_x",
            "configure the packaged receipt provider and its C/C++ toolchain",
        ),
        (
            "src/tests/python/test_native_unique_resources.py::test_x",
            "actual SQLite SDK proof requires sqlite3.pc in PKG_CONFIG_PATH",
        ),
        (
            "src/tests/python/test_native_cxx_owners.py::test_x",
            "C++ owner proof requires the pugixml SDK through pkg-config",
        ),
        (
            "src/tests/python/test_module_units.py::test_x[cxx_units_project]",
            "C++ owner proof requires the pugixml SDK through pkg-config",
        ),
    ):
        assert manifest.classify(nodeid, reason) is None, nodeid


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


# Representative skips from CI run 36898564273 (Linux, cf28fe7): the unit and
# btrc shards, by rule. CI run 36935218617 still skips the lldb, pugixml and
# native-provider cases, which macOS run 36934014516 runs.
LINUX_SKIPS = {
    "native-reader-macos-only": (
        "src/tests/python/test_native_callbacks.py::test_x[python]",
        "requires macOS and the explicitly built native header reader",
    ),
    "native-digest-macos-only": (
        "src/tests/btrc/test_native_digest.py::test_x",
        "native SHA requires macOS and the configured SDK reader",
    ),
    "apple-sdk-headers": (
        "src/tests/python/test_native_header_reader.py::test_x",
        "requires the actual macOS CoreFoundation SDK",
    ),
    "core-audio-runtime": ("src/tests/python/test_module_units.py::test_x", "CoreAudio is available only on macOS"),
    "lldb-missing": (
        "src/tests/debug/test_dap_session.py::test_stop_on_entry",
        "needs lldb (with Python scripting): btrc debug adapter: cannot locate lldb "
        "([Errno 2] No such file or directory: '/usr/bin/lldb').",
    ),
    "native-compiler-provider": (
        "src/tests/python/test_native_preprocess_receipts.py::test_x",
        "build native reader and configure its native compiler provider",
    ),
    "windows-junctions": (
        "src/tests/python/test_artifact_reparse.py::test_windows_junction_is_rejected_as_archive_entry_and_destination",
        "native junctions require Windows",
    ),
}

# The Windows steps' recorded skip (run 36898564289) and the os.name skips of
# the files those steps select.
WINDOWS_SKIPS = {
    "posix-process-group": (
        "src/tests/btrc/test_bootstrap_harness.py::test_stage_timeout_kills_spawned_descendants",
        "POSIX process-group contract",
    ),
    "posix-no-follow-utime": (
        "src/tests/python/test_artifact_storage.py::test_normalize_timestamp_uses_no_follow_posix_utime",
        "requires POSIX no-follow utime",
    ),
    "posix-fifo": (
        "src/tests/python/test_artifact_storage.py::test_destination_exists_rejects_a_special_file",
        "FIFOs are unavailable",
    ),
}

# Hosted macos-15 skips from macOS runs 37110991739 (5b57618) and 37099829848
# (379ab93), and the two hardware-tier skips its manifest admits.
HOSTED_SKIPS = {
    "windows-executable-release": (
        "src/tests/btrc/test_bootstrap_harness.py::test_x",
        "native Windows executable-release contract",
    ),
    "dev-full": ("src/tests/btrc/test_frontend_io_boundaries.py::test_x", "requires /dev/full"),
    "linux-glibc-call-shapes": (
        "src/tests/python/test_native_linux_call_shapes.py::test_x[python]",
        "the call shapes are proven against glibc",
    ),
    "darwin-gcc-sanitizer-runtime": (
        "src/tests/python/test_arc_witness_runtime.py::test_witness_transitions_are_exact[asan-ubsan-gcc]",
        "gcc cannot link ASan+UBSan here: ld: library not found for -lasan\ncollect2: error: ld returned 1 exit status",
    ),
    "coreaudio-output-device": (
        "src/tests/python/test_core_audio_device_runtime.py::test_core_audio_provider_on_both_frontends[btrc]",
        "SKIP: CoreAudio output session unavailable",
    ),
    "gpu-compute-adapter": (
        "src/tests/python/test_native_gpu_runtime.py::test_native_gpu_rejects_malformed_wgsl_without_aborting",
        "no native compute adapter is available",
    ),
}

EXPECTED_BY_RUNNER = {
    "macos": dict(zip(("dap-session-developer-mode", "linux-freetype-macro-constants"), MACOS_SKIPS[:2], strict=True)),
    "macos-hosted": HOSTED_SKIPS,
    "linux-devcontainer": LINUX_SKIPS,
    "windows": WINDOWS_SKIPS,
}


@pytest.mark.parametrize("runner", ["macos-hosted", "linux-devcontainer", "windows"])
def test_the_ci_runner_manifests_explain_their_recorded_skips(runner):
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")

    assert manifest.enforce
    assert {rule_id: manifest.classify(*skip).id for rule_id, skip in EXPECTED_BY_RUNNER[runner].items()} == {
        rule_id: rule_id for rule_id in EXPECTED_BY_RUNNER[runner]
    }
    # A Windows-only reason on a Linux file, or a POSIX reason elsewhere, is not explained.
    assert manifest.classify("src/tests/python/test_cases.py::test_x", "requires the native Windows CRT") is None


def test_the_hosted_macos_manifest_expects_only_platform_and_hardware_skips():
    """Hosted macOS runs everything it can: another OS's tests and the hardware tier are all it may skip."""

    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos-hosted.json")
    rules = {rule.id: rule for rule in manifest.rules}

    assert HOSTED_RUNNERS == {"macos-hosted": "macos"}
    assert {rule.category for rule in manifest.rules} == set(HOSTED_CATEGORIES)
    hardware = {rule_id: rule for rule_id, rule in rules.items() if rule.category == "hardware"}
    assert set(hardware) == {"coreaudio-output-device", "gpu-compute-adapter"}
    for rule in hardware.values():
        assert rule.covered_by == ("macos",), rule.id
        assert rule.gating_capabilities and set(rule.gating_capabilities) <= set(HARDWARE_CAPABILITIES), rule.id
    # The acceptance Mac's platform rules all apply to the hosted image too.
    mac = {rule.id: rule for rule in ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json").rules}
    assert {rule_id for rule_id, rule in mac.items() if rule.category == "platform"} <= set(rules)
    # Only gcc's sanitizer cases are a platform gap: the same cases through
    # clang run here, so their skips are defects.
    for nodeid, reason in (
        (
            "src/tests/python/test_arc_witness_runtime.py::test_witness_transitions_are_exact[asan-ubsan-clang0]",
            "clang cannot link ASan+UBSan here: ld: library not found",
        ),
        (
            "src/tests/python/test_freestanding_reference.py::test_reference_runtime_is_strict_and_width_correct"
            "[ubsan-clang]",
            "compiler wrapper does not provide its UBSan runtime",
        ),
        # macos.yml enables developer mode, and ThreadSanitizer starts on the image.
        (
            "src/tests/debug/test_dap_session.py::test_stop_on_entry",
            "needs macOS developer mode for lldb to launch an inferior (sudo /usr/sbin/DevToolsSecurity -enable)",
        ),
        (
            "src/tests/python/test_gpu_async_runtime.py::test_x",
            "ThreadSanitizer runtime crashes on an independent exact-flags probe",
        ),
        # The hardware tier is the device, never the provider or the toolchain.
        (
            "src/tests/python/test_core_audio_device_runtime.py::test_core_audio_provider_on_both_frontends[python]",
            "SKIP: CoreAudio provider unavailable",
        ),
        ("src/tests/python/test_native_gpu_runtime.py::test_x", "WebGPU build flags are unavailable"),
        ("src/tests/python/test_wgsl_semantics.py::test_x", "naga WGSL validator is not installed"),
    ):
        assert manifest.classify(nodeid, reason) is None, nodeid


def test_ci_manifests_name_coverage_that_ci_reports_can_confirm():
    """Linux and Windows claim macOS coverage from the hosted runner, whose reports every push uploads."""

    for runner in ("linux-devcontainer", "windows"):
        manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
        claimed = {other for rule in manifest.rules for other in rule.covered_by}
        assert "macos-hosted" in claimed, runner
        assert claimed <= {"macos-hosted", "linux-devcontainer", "windows"}, runner


def test_macos_ci_classifies_every_session_as_the_hosted_runner():
    """A Darwin host detects as the acceptance Mac, so the workflow names its runner once, for every job."""

    workflow = (REPO / ".github/workflows/macos.yml").read_text(encoding="utf-8")
    code = [line for line in workflow.splitlines() if not line.lstrip().startswith("#")]

    assert re.search(r"(?m)^env:\n  BTRC_TEST_RUNNER: macos-hosted\n(?!  )", "\n".join(code) + "\n")
    # No job or step overrides it.
    assert sum("BTRC_TEST_RUNNER" in line for line in code) == 1


def test_the_linux_manifest_names_coverage_for_every_tool_the_mac_alone_has():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "linux-devcontainer.json")
    rules = {rule.id: rule for rule in manifest.rules}

    assert rules["native-reader-macos-only"].covered_by == ("macos-hosted",)
    assert rules["windows-junctions"].covered_by == ("windows",)
    # Only a display and a session bus are missing everywhere; the pugixml,
    # SQLite, lldb and native-provider cases Linux skips run on macOS.
    uncovered = {rule_id for rule_id, rule in rules.items() if not rule.covered_by}
    assert uncovered == {"linux-tray-session-bus"}
    for rule_id in ("pugixml-sdk", "native-compiler-provider", "native-receipt-provider", "lldb-missing"):
        assert rules[rule_id].covered_by == ("macos-hosted",), rule_id
    # No rule waits on a lane that has landed.
    assert not [rule_id for rule_id, rule in rules.items() if "Delete this rule once" in rule.note]
    # CI runs every shard under tools/virtual-display.sh (Xvfb and Mesa lavapipe),
    # so a missing display or compute adapter is a broken runner, not an expected skip.
    assert (
        manifest.classify(
            "src/tests/python/test_native_linux_providers.py::test_linux_gui_controls[True-python]",
            "native GUI backend is unavailable: no WAYLAND_DISPLAY or DISPLAY",
        )
        is None
    )
    assert (
        manifest.classify(
            "src/tests/python/test_native_gpu_runtime.py::test_x", "no native compute adapter is available"
        )
        is None
    )
    # The macOS-only C++ owner and SQLite proofs are covered by macOS like any other.
    for nodeid in (
        "src/tests/python/test_native_cxx_owners.py::test_x",
        "src/tests/python/test_module_units.py::test_x[cxx_units_project]",
        "src/tests/python/test_native_unique_resources.py::test_unique_owned_output_actual_sqlite_open[x]",
    ):
        rule = manifest.classify(nodeid, "requires macOS and the explicitly built native header reader")
        assert rule.id == "native-reader-macos-only" and rule.covered_by == ("macos-hosted",), nodeid


@pytest.mark.parametrize("runner", sorted(EXPECTED_BY_RUNNER))
def test_each_tracked_manifest_fails_the_gate_on_an_injected_skip(tmp_path, runner):
    """Every qualified runner's real manifest is enforced: its recorded skips pass and an injected one fails."""

    expected = list(EXPECTED_BY_RUNNER[runner].values())
    injected = ("src/tests/python/test_injected.py::test_injected", "an injected unexpected skip")
    report = tmp_path / f"skip-report-{runner}.json"
    gate = [sys.executable, "-m", "tools.qualification", "skip-gate", str(report)]

    report.write_text(json.dumps(_report(expected, runner=runner)))
    assert SkipGate().check([report]).passed
    clean = subprocess.run(gate, cwd=REPO, capture_output=True, text=True, timeout=120)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    report.write_text(json.dumps(_report([*expected, injected], runner=runner)))
    outcome = SkipGate().check([report])
    assert outcome.failures == [f"{injected[0]}: unexpected skip on {runner}: {injected[1]}"]
    failing = subprocess.run(gate, cwd=REPO, capture_output=True, text=True, timeout=120)
    assert failing.returncode == 1
    assert f"UNEXPECTED {injected[0]}" in failing.stdout


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
        ([_rule(category="hardware")], "hardware rule names its devices"),
        ([_rule(category="hardware", gating={"capabilities": ["holodeck"]})], "hardware rule names its devices"),
        (
            [_rule(category="hardware", gating={"capabilities": ["gpu-adapter"]}, covered_by=[])],
            "names a runner that has the device",
        ),
    ],
)
def test_malformed_manifests_are_rejected(tmp_path, rules, message):
    with pytest.raises(SkipLedgerError, match=message):
        ExpectedSkipManifest.load(_manifest(tmp_path, "macos", rules))


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (_rule(category="capability", covered_by=["macos"]), "expects only platform and hardware skips"),
        (_rule(category="runtime-probe"), "not 'runtime-probe'"),
        (
            _rule(category="hardware", gating={"capabilities": ["gpu-adapter"]}, covered_by=["linux-devcontainer"]),
            "hardware skip is covered by macos",
        ),
    ],
)
def test_a_hosted_manifest_admits_only_platform_and_hardware_rules(tmp_path, rule, message):
    with pytest.raises(SkipLedgerError, match=message):
        ExpectedSkipManifest.load(_manifest(tmp_path, "macos-hosted", [rule]))
    hosted = ExpectedSkipManifest.load(
        _manifest(
            tmp_path,
            "macos-hosted",
            [
                _rule(category="platform"),
                _rule(
                    id="no-device", category="hardware", gating={"capabilities": ["gpu-adapter"]}, covered_by=["macos"]
                ),
            ],
        )
    )
    assert [rule.category for rule in hosted.rules] == ["platform", "hardware"]
    # Other runners keep every category.
    assert ExpectedSkipManifest.load(
        _manifest(tmp_path, "linux-devcontainer", [{**rule, "covered_by": ["macos"]}])
    ).rules


def test_a_manifest_must_be_named_for_its_runner(tmp_path):
    path = _manifest(tmp_path, "macos", [])
    renamed = path.with_name("windows.json")
    path.rename(renamed)

    with pytest.raises(SkipLedgerError, match=r"must be named macos\.json"):
        ExpectedSkipManifest.load(renamed)


def test_classification_records_gating_environment_presence():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "linux-devcontainer.json")
    provider_skip = LINUX_SKIPS["native-compiler-provider"]
    pugixml_skip = (
        "src/tests/python/test_native_header_reader.py::test_cpp_pugixml_sdk_resource_metadata[python]",
        "pugixml SDK is not installed",
    )
    report = _report(
        [provider_skip, pugixml_skip],
        runner="linux-devcontainer",
        environment={"BTRC_NATIVE_HEADER_READER": "set", "PKG_CONFIG_PATH": "set"},
    )

    classified = {item.nodeid: item for item in SkipClassifier(manifest).classify(report)}

    assert classified[provider_skip[0]].gating_env == {
        "BTRC_NATIVE_HEADER_READER": "set",
        "BTRC_NATIVE_PROVIDER_CC": "unset",
        "BTRC_NATIVE_PROVIDER_CXX": "unset",
    }
    assert classified[pugixml_skip[0]].gating_env == {"PKG_CONFIG_PATH": "set"}
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
    one = makefile.split("\ntest-c11-one:", 1)[1].split("\n\n", 1)[0]

    # The local matrix runs each CI configuration's own target, which gates
    # the report it writes.
    assert "$(MAKE) --no-print-directory test-c11-one C11_CC=$$cc C11_OPT=$$opt || exit 1" in recipe
    assert "--skip-report=build/skip-report-c11-$(C11_CC)-$(C11_OPT).json" in one
    assert "$(SKIP_GATE) build/skip-report-c11-$(C11_CC)-$(C11_OPT).json" in one


def test_every_windows_pytest_step_writes_its_own_skip_report_and_gates_it():
    """windows.yml has no Makefile: each pytest step names its report and gates it before the next command."""

    workflow = (REPO / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    commands = [line.strip() for line in workflow.replace("\\\n", " ").splitlines()]
    sessions = [line for line in commands if line.startswith("python -m pytest")]
    reports = [re.search(r"--skip-report=(\S+?\.json)", line).group(1) for line in sessions]
    gated = [line.split()[-1] for line in commands if line.startswith("python -m tools.qualification skip-gate")]

    assert len(sessions) == 3 and len(set(reports)) == len(reports)
    assert all(report.startswith("build/skip-report-windows-") for report in reports)
    assert gated == reports
    for report in reports:
        following = commands[commands.index(next(line for line in sessions if report in line)) + 1]
        assert following == f"python -m tools.qualification skip-gate {report}"
    assert "src/tests/python/test_artifact_reparse.py" in workflow
    upload = workflow.split("name: Retain the skip report", 1)[1]
    assert "if: always()" in upload and "path: build/skip-report*.json" in upload
