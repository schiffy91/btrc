"""The skip ledger: the collector, the expected-skip manifests, the gate and target capabilities."""

from __future__ import annotations

import ast
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
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
from tools.qualification.tiers import TierManifest

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

    assert {"macos", "macos-hosted", "linux-hosted", "linux-devcontainer", "windows"} <= set(manifests)
    assert set(manifests) <= set(RUNNERS)
    assert all(
        manifests[runner].enforce
        for runner in ("macos", "macos-hosted", "linux-hosted", "linux-devcontainer", "windows")
    )
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


@pytest.mark.parametrize("runner", ["macos", "macos-hosted"])
def test_macos_classifies_only_the_linux_main_stack_limit_cases(runner):
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
    test = "src/tests/btrc/test_deep_expression_parity.py::test_compiler_stack_respects_process_hard_limit"
    reason = "Linux main-stack resource limit"
    for hard_mib in (16, 64):
        rule = manifest.classify(f"{test}[{hard_mib}]", reason)
        assert rule is not None
        assert rule.category == "platform"
        assert rule.covered_by == ("linux-devcontainer",)
    assert manifest.classify(f"{test}[64]", "compiler startup failed") is None
    assert manifest.classify(f"{test}_unrelated[64]", reason) is None
    assert manifest.classify("src/tests/btrc/test_other.py::test_limit[64]", reason) is None


@pytest.mark.parametrize("runner", ["macos", "macos-hosted"])
def test_macos_classifies_only_the_linux_child_subreaper_case(runner):
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
    nodeid = "src/tests/python/test_android_executor.py::test_a_descendant_that_leaves_the_session_is_still_reaped"
    reason = "the child subreaper is Linux's"
    rule = manifest.classify(nodeid, reason)

    assert rule is not None
    assert rule.category == "platform"
    assert rule.covered_by == ("linux-devcontainer",)
    assert manifest.classify(nodeid, "requires a host C compiler") is None
    assert manifest.classify(nodeid + "_unrelated", reason) is None
    assert (
        manifest.classify(
            "src/tests/python/test_android_executor.py::test_descendants_die_with_the_program_even_holding_its_stderr",
            reason,
        )
        is None
    )
    for linux in ("linux-devcontainer", "linux-hosted"):
        assert ExpectedSkipManifest.load(MANIFEST_ROOT / f"{linux}.json").classify(nodeid, reason) is None


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

HOSTED_LINUX_WINDOWS_SKIPS = [
    (
        f"src/tests/python/test_native_ui_shell_windows.py::test_windows_native_shell_runs[{frontend}-{target}-{variant}]",
        "requires Windows: windows.yml's win32-native job runs the executables the build tests publish",
    )
    for frontend in ("python", "selfhost")
    for target in ("windows-arm64", "windows-x64")
    for variant in ("plain", "ubsan")
] + [
    (
        f"src/tests/python/test_windows_http.py::test_preserved_native_executables_run[{frontend}-{target}]",
        "requires the real Windows native runner",
    )
    for frontend in ("failures", "reference", "selfhost")
    for target in ("windows-arm64", "windows-x64")
]

EXPECTED_BY_RUNNER = {
    "macos": dict(zip(("dap-session-developer-mode", "linux-freetype-macro-constants"), MACOS_SKIPS[:2], strict=True)),
    "macos-hosted": HOSTED_SKIPS,
    "linux-hosted": {
        "windows-native-shell-runtime": HOSTED_LINUX_WINDOWS_SKIPS[0],
        "windows-http-runtime": HOSTED_LINUX_WINDOWS_SKIPS[-1],
    },
    "linux-devcontainer": LINUX_SKIPS,
    "windows": WINDOWS_SKIPS,
}


@pytest.mark.parametrize("runner", ["macos-hosted", "linux-hosted", "linux-devcontainer", "windows"])
def test_the_ci_runner_manifests_explain_their_recorded_skips(runner):
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")

    assert manifest.enforce
    assert {rule_id: manifest.classify(*skip).id for rule_id, skip in EXPECTED_BY_RUNNER[runner].items()} == {
        rule_id: rule_id for rule_id in EXPECTED_BY_RUNNER[runner]
    }
    # A Windows-only reason on a Linux file, or a POSIX reason elsewhere, is not explained.
    assert manifest.classify("src/tests/python/test_cases.py::test_x", "requires the native Windows CRT") is None


def test_hosted_linux_windows_exceptions_do_not_admit_other_cases_or_reasons():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "linux-hosted.json")
    assert len(HOSTED_LINUX_WINDOWS_SKIPS) == 14
    for node, reason in HOSTED_LINUX_WINDOWS_SKIPS:
        rule = manifest.classify(node, reason)
        assert rule is not None and rule.covered_by == ("windows",)
        for changed in (
            node.replace("windows-x64", "windows-x86").replace("windows-arm64", "windows-arm32"),
            node.replace("test_windows_native_shell_runs", "test_windows_native_shell_builds")
            if "native_shell_runs" in node
            else node.replace("test_preserved_native_executables_run", "test_build"),
        ):
            assert manifest.classify(changed, reason) is None
        assert manifest.classify(node, reason + ": missing compiler") is None
        if "windows.yml" in reason:
            assert manifest.classify(node, reason.replace("windows.yml", "windows-yml")) is None
        assert manifest.classify(node, "native compiler is not installed") is None
        assert manifest.classify("src/tests/python/test_native_jni_android.py::test_round_trip[python]", reason) is None
        assert manifest.classify("tools/target_hosts/windows/test_executor.py::test_executor", reason) is None


def test_the_hosted_macos_manifest_expects_only_platform_and_hardware_skips():
    """Hosted macOS runs everything it can: another OS's tests and the hardware tier are all it may skip."""

    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "macos-hosted.json")
    rules = {rule.id: rule for rule in manifest.rules}

    assert HOSTED_RUNNERS == {"macos-hosted": "macos", "linux-hosted": "linux"}
    assert {rule.category for rule in manifest.rules} == set(HOSTED_CATEGORIES)
    hardware = {rule_id: rule for rule_id, rule in rules.items() if rule.category == "hardware"}
    assert set(hardware) == {"coreaudio-output-device", "gpu-compute-adapter"}
    for rule in hardware.values():
        assert rule.covered_by == ("macos",), rule.id
        assert rule.gating_capabilities and set(rule.gating_capabilities) <= set(HARDWARE_CAPABILITIES), rule.id
    # The acceptance Mac's platform rules all apply to the hosted image too.
    mac = {rule.id: rule for rule in ExpectedSkipManifest.load(MANIFEST_ROOT / "macos.json").rules}
    shared = {rule_id for rule_id, rule in mac.items() if rule.category == "platform"}
    assert shared <= set(rules)
    # Kept identical, so the two Mac manifests cannot drift apart.
    for rule_id in shared:
        assert (
            rules[rule_id].files,
            rules[rule_id].nodes,
            rules[rule_id].reason.pattern,
            rules[rule_id].covered_by,
        ) == (
            mac[rule_id].files,
            mac[rule_id].nodes,
            mac[rule_id].reason.pattern,
            mac[rule_id].covered_by,
        ), rule_id
    # Only gcc's sanitizer cases are a platform gap: the same cases through
    # clang run here, so their skips are defects.
    for nodeid, reason in (
        (
            "src/tests/python/test_arc_witness_runtime.py::test_witness_transitions_are_exact[asan-ubsan-clang0]",
            "gcc cannot link ASan+UBSan here: ld: library not found for -lasan",
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
    """Linux and Windows claim macOS coverage from the hosted runner, whose reports every push uploads.

    A rule may also name one of ci/tiers.toml's hardware runners, which CI
    never reports from: the ledger bundle records it as awaiting until its
    evidence arrives. The only such claim is the physical Linux desktop's."""

    awaiting = {runner.runner for runner in TierManifest.load().hardware}
    confirmable = {"macos-hosted", "linux-devcontainer", "windows"}
    for runner in ("linux-devcontainer", "windows"):
        manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
        claimed = {other for rule in manifest.rules for other in rule.covered_by}
        assert "macos-hosted" in claimed, runner
        assert claimed <= confirmable | awaiting, runner
        for rule in manifest.rules:
            if set(rule.covered_by) - confirmable:
                assert rule.id == "linux-real-desktop-session", (runner, rule.id)


def test_macos_ci_classifies_every_session_as_the_hosted_runner():
    """A Darwin host detects as the acceptance Mac, so the workflow names its runner once, for every job."""

    workflow = (REPO / ".github/workflows/macos.yml").read_text(encoding="utf-8")
    code = [line for line in workflow.splitlines() if not line.lstrip().startswith("#")]

    assert re.search(r"(?m)^env:\n(?:  \S.*\n)*?  BTRC_TEST_RUNNER: macos-hosted$", "\n".join(code))
    # No job or step overrides it.
    assert sum("BTRC_TEST_RUNNER" in line for line in code) == 1


def test_the_linux_manifest_names_coverage_for_every_tool_the_mac_alone_has():
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / "linux-devcontainer.json")
    rules = {rule.id: rule for rule in manifest.rules}

    assert rules["native-reader-macos-only"].covered_by == ("macos-hosted",)
    assert rules["windows-junctions"].covered_by == ("windows",)
    # Only a display and a session bus are missing everywhere, and only the
    # acceptance Mac's pinned Xcode runs the Apple macro oracle (MAC-P1-05);
    # the pugixml, SQLite, lldb and native-provider cases Linux skips run on
    # macOS. No CI runner has the NDK, a Windows SDK row toolchain or a
    # Stage 25 executor yet, so the target ABI fixture's rows that need them
    # are uncovered until those lanes exist. The Android JNI round trip runs
    # in host-android.yml's emulator jobs, which write no skip report.
    uncovered = {rule_id for rule_id, rule in rules.items() if not rule.covered_by}
    assert uncovered == {
        "android-device-bound",
        "apple-target-macro-oracle",
        "linux-tray-session-bus",
        "target-abi-ndk-bound",
        "target-abi-msvc-runner-bound",
        "target-abi-stage25-host-lane",
    }
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
        (
            [_rule(category="hardware", gating={"capabilities": ["gpu-adapter"], "tools": ["naga"]})],
            "gated by capabilities only",
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
            "hardware skip must be covered by macos",
        ),
        (_rule(category="platform", covered_by=["macos"]), "platform skip must not be covered by macos"),
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


def _run_inner(tmp_path: Path, *extra: str, runner: str = "macos") -> tuple[subprocess.CompletedProcess, dict]:
    report = tmp_path / "out" / "skip-report.json"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO), os.environ.get("PYTHONPATH")))),
        "BTRC_TEST_RUNNER": runner,
        "BTRC_PRIVATE_PATH": "/Users/someone/private",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("BTRC_TEST_CAPABILITIES", None)
    # The child suite owns its options; workflow options may require plugins
    # this invocation explicitly disables. Caller-supplied argv remains intact.
    environment.pop("PYTEST_ADDOPTS", None)
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


def _failure_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(
        _INNER_CONFTEST
        + """
import pytest

def pytest_sessionstart(session):
    session.config.addinivalue_line("markers", "macos_gui: canonical identity regression")

@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.failed:
        report.sections.append(("host compiler launch evidence", "retained compiler detail"))
    return report
"""
    )
    return suite


@pytest.mark.parametrize("workers", [None, "2"])
@pytest.mark.parametrize("groups", [("macos_gui",), ("linux_fixture", "linux_sanitized")])
def test_failure_journal_preserves_phases_sections_and_consecutive_sessions(tmp_path, workers, groups):
    suite = _failure_suite(tmp_path)
    marks = [f"pytest.mark.xdist_group(name={group!r})" for group in groups]
    if groups == ("macos_gui",):
        marks.append("pytest.mark.macos_gui")
    (suite / "test_cases.py").write_text(
        """
import pytest
pytestmark = [MARKS]

@pytest.fixture
def setup_error():
    raise ValueError("setup diagnostic")

@pytest.fixture
def teardown_error():
    yield
    raise ValueError("teardown diagnostic")

def test_setup(setup_error):
    pass

def test_call():
    print("captured failure output")
    assert False, "call diagnostic"

def test_teardown(teardown_error):
    pass

def test_pass():
    pass

def test_skip():
    pytest.skip("expected skip")

@pytest.mark.xfail(reason="expected failure")
def test_xfail():
    assert False
""".replace("MARKS", ", ".join(marks))
    )
    options = ("-n", workers, "--dist=loadgroup") if workers else ("-p", "no:xdist")
    journal = tmp_path / "out" / "failures.jsonl"
    baseline, original = _run_inner(tmp_path, *options)
    assert baseline.returncode == 1
    assert "BTRC immediate failure" not in baseline.stdout
    assert not journal.exists()
    sessions = set()
    for iteration in (1, 2):
        completed, report = _run_inner(tmp_path, *options, f"--failure-report={journal}")
        assert completed.returncode == baseline.returncode, completed.stdout + completed.stderr
        assert report["counts"] == original["counts"]
        assert report["tests"] == original["tests"]
        assert completed.stdout.count("BTRC immediate failure") == 3
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        assert len(records) == iteration * 3
        current = records[-3:]
        assert {(row["nodeid"], row["phase"]) for row in current} == {
            ("test_cases.py::test_setup", "setup"),
            ("test_cases.py::test_call", "call"),
            ("test_cases.py::test_teardown", "teardown"),
        }
        for row in current:
            assert row["schema"] == "btrc.failure-report/1"
            assert f"{row['phase']} diagnostic" in row["longrepr"]
            assert ["host compiler launch evidence", "retained compiler detail"] in row["sections"]
            assert row["pid"] > 0 and row["revision"]
        call = next(row for row in current if row["phase"] == "call")
        assert any("captured failure output" in content for _, content in call["sections"])
        assert len({row["session"] for row in current}) == 1
        sessions.add(current[0]["session"])
    assert len(sessions) == 2


@pytest.mark.parametrize("workers", [None, "2"])
def test_failure_journal_records_collection_error_once(tmp_path, workers):
    suite = _failure_suite(tmp_path)
    (suite / "test_broken.py").write_text('raise RuntimeError("collection diagnostic")\n')
    journal = tmp_path / "out" / "failures.jsonl"
    options = ("-n", workers) if workers else ("-p", "no:xdist")
    completed, _ = _run_inner(tmp_path, *options, f"--failure-report={journal}")
    assert completed.returncode != 0
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["nodeid"] == "test_broken.py"
    assert records[0]["phase"] == "collect"
    assert "collection diagnostic" in records[0]["longrepr"]
    assert completed.stdout.count("BTRC immediate failure") == 1


@pytest.mark.parametrize("workers", [None, "2"])
def test_failure_journal_survives_controller_kill_before_sessionfinish(tmp_path, workers):
    suite = _failure_suite(tmp_path)
    (suite / "test_cases.py").write_text(
        """
import os
import time
from pathlib import Path
import pytest
pytestmark = [pytest.mark.macos_gui, pytest.mark.xdist_group(name="macos_gui")]

def test_a_failure():
    assert False, "failure before timeout"

def test_b_wait():
    Path("waiting").touch()
    deadline = time.monotonic() + 30
    while not Path("release").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    # A worker outliving its killed controller must still terminate promptly.
    os._exit(0)
"""
    )
    journal = tmp_path / "failures.jsonl"
    final_report = tmp_path / "skip-report.json"
    console = tmp_path / "console.log"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO), os.environ.get("PYTHONPATH")))),
        "BTRC_TEST_RUNNER": "macos",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTEST_ADDOPTS", None)
    options = ("-n", workers, "--dist=loadgroup") if workers else ("-p", "no:xdist")
    with console.open("w") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *options,
                f"--skip-report={final_report}",
                f"--failure-report={journal}",
                ".",
            ],
            cwd=suite,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                text = console.read_text()
                if (suite / "waiting").exists() and journal.exists() and "BTRC immediate failure" in text:
                    break
                assert process.poll() is None, text
                assert time.monotonic() < deadline, text
                time.sleep(0.01)
            # Both sinks must be complete while pytest is still running.
            records = [json.loads(line) for line in journal.read_text().splitlines()]
            assert len(records) == 1
            assert records[0]["nodeid"] == "test_cases.py::test_a_failure"
            assert "failure before timeout" in records[0]["longrepr"]
            assert "failure before timeout" in text and "retained compiler detail" in text
            assert not final_report.exists()
        finally:
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
            (suite / "release").touch()
            process.wait(timeout=10)
    assert not final_report.exists()
    assert len(journal.read_text().splitlines()) == 1


def test_hosted_linux_collector_and_gate_require_every_selected_case(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(_INNER_CONFTEST)
    (suite / "test_cases.py").write_text("def test_round_trip():\n    pass\n")
    report_path = tmp_path / "out" / "skip-report.json"

    baseline, report = _run_inner(tmp_path, "-p", "no:xdist", runner="linux")
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    assert report["classification_error"] == "no expected-skip manifest for runner 'linux'"
    assert not SkipGate().check([report_path]).passed

    completed, report = _run_inner(tmp_path, "-p", "no:xdist", runner="linux-hosted")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["runner"] == report["manifest"]["runner"] == "linux-hosted"
    assert report["manifest"]["enforce"] is True
    assert "classification_error" not in report
    assert report["counts"]["passed"] == 1 and report["counts"]["skipped"] == 0
    assert SkipGate().check([report_path]).passed

    (suite / "test_injected.py").write_text(_INJECTED)
    completed, report = _run_inner(tmp_path, "-p", "no:xdist", runner="linux-hosted")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["counts"]["passed"] == 1 and report["counts"]["skipped"] == 1
    outcome = SkipGate().check([report_path])
    assert not outcome.passed
    assert any("an injected unexpected skip" in line for line in outcome.lines)


def test_hosted_linux_collector_gates_only_the_fourteen_windows_runtime_skips(tmp_path):
    suite = tmp_path / "suite"
    tests = suite / "src" / "tests" / "python"
    tests.mkdir(parents=True)
    (suite / "conftest.py").write_text(_INNER_CONFTEST)
    for filename, function in (
        ("test_native_ui_shell_windows.py", "test_windows_native_shell_runs"),
        ("test_windows_http.py", "test_preserved_native_executables_run"),
    ):
        cases = [
            (node.split("[", 1)[1][:-1], reason) for node, reason in HOSTED_LINUX_WINDOWS_SKIPS if filename in node
        ]
        (tests / filename).write_text(
            "import pytest\n"
            f"@pytest.mark.parametrize('case,reason', {cases!r}, ids={[case for case, _ in cases]!r})\n"
            f"def {function}(case, reason):\n    pytest.skip(reason)\n"
        )
    report_path = tmp_path / "out" / "skip-report.json"
    completed, report = _run_inner(tmp_path, "-p", "no:xdist", runner="linux-hosted")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["counts"]["skipped"] == 14
    assert {row["nodeid"] for row in report["skips"]} == {node for node, _ in HOSTED_LINUX_WINDOWS_SKIPS}
    assert "classification_error" not in report
    assert SkipGate().check([report_path]).passed

    # A JNI skip remains fatal even when its reason matches a Windows exception.
    (tests / "test_native_jni_android.py").write_text(
        "import pytest\ndef test_round_trip():\n    pytest.skip('requires the real Windows native runner')\n"
    )
    completed, report = _run_inner(tmp_path, "-p", "no:xdist", runner="linux-hosted")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert report["counts"]["skipped"] == 15
    outcome = SkipGate().check([report_path])
    assert not outcome.passed
    assert any("test_native_jni_android.py" in failure for failure in outcome.failures)


@pytest.mark.parametrize("workers", [None, "2"])
def test_the_collector_records_outcomes_skips_and_capability_gates(tmp_path, workers, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--dist=loadgroup")
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(_INNER_CONFTEST)
    (suite / "test_cases.py").write_text(_INNER_TESTS)
    (suite / "test_module_skip.py").write_text('import pytest\npytest.skip("whole module", allow_module_level=True)\n')

    _, report = _run_inner(tmp_path, *(("-n", workers, "--dist=loadgroup") if workers else ("-p", "no:xdist")))

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


def test_an_injected_unexpected_skip_fails_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "--dist=loadgroup")
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
        ({"BTRC_TEST_RUNNER": "linux-hosted"}, "linux", False, "linux-hosted"),
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
    # A matrix job's report names its row: ${{ matrix.target }} holds spaces.
    reports = [re.search(r"--skip-report=(\S+?(?:\$\{\{ [a-z.]+ \}\})?\S*?\.json)", line).group(1) for line in sessions]
    gated = [
        line.split("skip-gate ", 1)[1]
        for line in commands
        if line.startswith("python -m tools.qualification skip-gate")
    ]

    assert len(sessions) == 5 and len(set(reports)) == len(reports)
    assert any("src/tests/python/test_windows_http.py" in session for session in sessions)
    assert all(report.startswith("build/skip-report-windows-") for report in reports)
    assert gated == reports
    for report in reports:
        following = commands[commands.index(next(line for line in sessions if report in line)) + 1]
        assert following == f"python -m tools.qualification skip-gate {report}"
    assert "src/tests/python/test_artifact_reparse.py" in workflow
    upload = workflow.split("name: Retain the skip report", 1)[1]
    assert "if: always()" in upload and "path: build/skip-report*.json" in upload


@pytest.mark.parametrize("workers", [None, "2"])
def test_progress_journal_reconstructs_completed_test_outcomes(tmp_path, workers):
    suite = _failure_suite(tmp_path)
    (suite / "test_cases.py").write_text(
        """
import pytest
pytestmark = [pytest.mark.macos_gui, pytest.mark.xdist_group(name="macos_gui")]

def test_pass():
    pass

@pytest.mark.parametrize("name", ["value"], ids=["literal@macos_gui"])
def test_failure(name):
    assert False, "body failure"

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown failure")

def test_teardown(broken_teardown):
    pass
"""
    )
    journal = tmp_path / "progress.jsonl"
    failures = tmp_path / "failures.jsonl"
    options = ("-n", workers, "--dist=loadgroup") if workers else ("-p", "no:xdist")
    completed, final_report = _run_inner(
        tmp_path, *options, f"--progress-report={journal}", f"--failure-report={failures}"
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    failures = [json.loads(line) for line in failures.read_text().splitlines()]
    expected = {
        "test_cases.py::test_pass": ["passed", "passed", "passed"],
        "test_cases.py::test_failure[literal@macos_gui]": ["passed", "failed", "passed"],
        "test_cases.py::test_teardown": ["passed", "passed", "failed"],
    }
    assert set(final_report["tests"]) == set(expected)
    assert len({row["session"] for row in [*records, *failures]}) == 1
    assert len({row["revision"] for row in [*records, *failures]}) == 1
    assert len([row for row in records if row["event"] == "start"]) == 3
    assert len([row for row in records if row["event"] == "finish"]) == 3
    for nodeid, outcomes in expected.items():
        scheduled = nodeid + ("@macos_gui" if workers else "")
        trace = [row for row in records if row["scheduled_nodeid"] == scheduled]
        assert [row["event"] for row in trace] == ["start", "phase", "phase", "phase", "finish"]
        phases = trace[1:-1]
        assert [row["phase"] for row in phases] == ["setup", "call", "teardown"]
        assert [row["outcome"] for row in phases] == outcomes
        assert all(row["nodeid"] == nodeid and row["duration_seconds"] >= 0 for row in phases)


@pytest.mark.parametrize("workers", [None, "2"])
@pytest.mark.parametrize("waiting_phase", ["setup", "call"])
def test_progress_journal_identifies_unfinished_phase_after_controller_kill(tmp_path, workers, waiting_phase):
    suite = _failure_suite(tmp_path)
    (suite / "test_cases.py").write_text(
        """
import os
import time
from pathlib import Path
import pytest
pytestmark = [pytest.mark.macos_gui, pytest.mark.xdist_group(name="macos_gui")]

def wait_for_release():
    Path("waiting").touch()
    deadline = time.monotonic() + 30
    while not Path("release").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    os._exit(0)

@pytest.fixture
def hold():
    WAIT_IN_SETUP

@pytest.mark.parametrize("name", ["value"], ids=["literal@macos_gui"])
def test_wait(name, hold):
    WAIT_IN_CALL
""".replace("WAIT_IN_SETUP", "wait_for_release()" if waiting_phase == "setup" else "pass").replace(
            "WAIT_IN_CALL", "wait_for_release()" if waiting_phase == "call" else "pass"
        )
    )
    journal = tmp_path / "progress.jsonl"
    final_report = tmp_path / "skip-report.json"
    console = tmp_path / "console.log"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, (str(REPO), os.environ.get("PYTHONPATH")))),
        "BTRC_TEST_RUNNER": "macos",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    environment.pop("PYTEST_ADDOPTS", None)
    options = ("-n", workers, "--dist=loadgroup") if workers else ("-p", "no:xdist")
    nodeid = "test_cases.py::test_wait[literal@macos_gui]"
    scheduled = nodeid + ("@macos_gui" if workers else "")
    with console.open("w") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *options,
                f"--skip-report={final_report}",
                f"--progress-report={journal}",
                ".",
            ],
            cwd=suite,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            deadline = time.monotonic() + 20
            while True:
                records = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
                started = any(row["event"] == "start" and row["scheduled_nodeid"] == scheduled for row in records)
                setup_done = any(row["event"] == "phase" and row["phase"] == "setup" for row in records)
                if (suite / "waiting").exists() and started and (waiting_phase == "setup" or setup_done):
                    break
                assert process.poll() is None, console.read_text()
                assert time.monotonic() < deadline, console.read_text()
                time.sleep(0.01)
            assert all(row["schema"] == "btrc.test-progress/1" for row in records)
            assert {row["scheduled_nodeid"] for row in records} == {scheduled}
            assert len({row["session"] for row in records}) == 1
            assert len({row["revision"] for row in records}) == 1
            assert not any(row["event"] == "finish" for row in records)
            phases = [row for row in records if row["event"] == "phase"]
            assert [row["phase"] for row in phases] == (["setup"] if waiting_phase == "call" else [])
            assert all(row["nodeid"] == nodeid and row["outcome"] == "passed" for row in phases)
            assert all(row["duration_seconds"] >= 0 for row in phases)
            assert f"BTRC test started {scheduled}" in console.read_text()
            assert not final_report.exists()
        finally:
            if os.name != "nt":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
            (suite / "release").touch()
            process.wait(timeout=10)
    assert not final_report.exists()
    assert [json.loads(line) for line in journal.read_text().splitlines()] == records


@pytest.mark.parametrize("runner", ["macos", "macos-hosted"])
@pytest.mark.parametrize(
    "node",
    [
        "src/tests/python/test_native_ui2_capture_linux.py::test_linux_capture_admission",
        "src/tests/python/test_native_ui2_fairness_linux.py::test_linux_e40_repeated_bursts",
        "src/tests/python/test_native_ui2_fairness_linux.py::test_linux_e40_sustained_load",
        "src/tests/python/test_native_ui2_fairness_linux.py::test_linux_e40_diagnostic",
        "src/tests/python/test_native_ui2_images.py::test_linux_image_publication",
        "src/tests/python/test_native_ui2_images.py::test_linux_image_lifetime",
        "src/tests/python/test_native_ui2_linux_resource_lifetime.py::test_linux_ui2_native_resource_lifetime",
        "src/tests/python/test_native_ui_core_linux.py::test_linux_ui2_executor_and_lifecycle",
        "src/tests/python/test_native_ui_core_linux.py::test_linux_ui2_callback_scope_release_requires_executor",
        "src/tests/python/test_native_ui_core_linux.py::test_linux_ui2_final_release_requires_executor",
    ],
)
def test_macos_classifies_linux_ui2_provider_skips(runner, node):
    reason = "requires Linux and the explicitly built native header reader"
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
    rule = manifest.classify(node + "[case]", reason)
    assert rule is not None
    assert rule.id == "linux-ui2-native-reader"
    assert rule.category == "platform" and rule.covered_by == ("linux-devcontainer",)
    assert manifest.classify(node + "[case]", "native GUI backend is unavailable: no DISPLAY") is None
    for linux_runner in ("linux-hosted", "linux-devcontainer"):
        assert (
            ExpectedSkipManifest.load(MANIFEST_ROOT / f"{linux_runner}.json").classify(node + "[case]", reason) is None
        )


@pytest.mark.parametrize("runner", ["macos", "macos-hosted"])
def test_linux_ui2_platform_skip_does_not_cover_other_tests(runner):
    manifest = ExpectedSkipManifest.load(MANIFEST_ROOT / f"{runner}.json")
    reason = "requires Linux and the explicitly built native header reader"
    for node in (
        "src/tests/python/test_native_ui2_images.py::test_macos_image_publication[case]",
        "src/tests/python/test_native_ui_core_linux.py::test_new_unreviewed_case[case]",
        "src/tests/python/test_native_tray_runtime.py::test_linux_capture_admission[case]",
    ):
        rule = manifest.classify(node, reason)
        assert rule is None or rule.id != "linux-ui2-native-reader"
