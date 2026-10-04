"""Portable native-shell build, execution and ledger transport.

The program imports public GUI interfaces only. C/Objective-C probes are test
injection/observation, never providers. E46 and E47 remain product gaps even
when their baseline/fixture checks pass. All GUI runs are stand-in evidence.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import provider_environment
from src.tests.python.native_import_fixtures import apple_environment
from tools.native_plan import NativePlanBuilder
from tools.qualification.schema import LedgerDocument

ROOT = Path(__file__).resolve().parents[3]
SHELL = ROOT / "src/tests/native/gui/shell"
SYMBOLS = (
    "shellProbeClick",
    "shellProbeTab",
    "shellProbeText",
    "shellProbeEnter",
    "shellProbeScroll",
    "shellProbeClose",
    "shellProbeFocus",
    "shellProbeNativeCount",
    "shellProbePrivateCount",
    "shellProbeDrain",
    "shellProbeObserve",
    "shellProbeDump",
    "shellStateCommit",
    "shellStateCheckpoint",
    "shellStateLoad",
    "shellStateDraft",
    "shellStateAnchor",
    "shellStateCommits",
)


def shell_environment(sanitized):
    environment = apple_environment() if sys.platform == "darwin" else provider_environment(sanitized)
    return {**environment, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}


def transpile(source, generated, plan, frontend, request, target):
    environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    if sys.platform == "darwin" and target.startswith("macos-"):
        sdk = subprocess.check_output(
            ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
            env=apple_environment(),
            text=True,
            timeout=30,
        ).strip()
        architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
        environment.update(BTRC_NATIVE_TARGET=f"{architecture}-apple-macosx14.0.0", BTRC_NATIVE_SYSROOT=sdk)
    arguments = ["--target", target, str(source), "--emit-link-plan", str(plan)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", *arguments, "-o", str(generated)]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc")), *arguments]
    )
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=600)
    if result.returncode == 0 and frontend == "selfhost":
        generated.write_text(result.stdout)
    return result


def build_shell(tmp_path, frontend, sanitized, request):
    NativeBindingPackage.require_reader()
    system = "macos" if sys.platform == "darwin" else "linux"
    architecture = "aarch64" if platform.machine() in {"arm64", "aarch64"} else "x86_64"
    probe = SHELL / "probes" / system / "ShellProbe"
    source = NativeBindingPackage.write(
        SHELL / "NativeShell.btrc", tmp_path / "package", probe.with_suffix(".h"), SYMBOLS
    )
    manifest = tmp_path / "package/btrc.toml"
    manifest.write_text(manifest.read_text() + 'read-only-borrows = ["shellStateCheckpoint.draft"]\n')
    generated, plan = tmp_path / "Shell.c", tmp_path / "Shell.json"
    result = transpile(source, generated, plan, frontend, request, f"{system}-{architecture}")
    assert result.returncode == 0, result.stderr
    assert "warning:" not in result.stderr.lower(), result.stderr
    flags = (
        ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"] if sanitized else []
    )
    compiler = "/usr/bin/clang" if system == "macos" else "cc"
    environment = shell_environment(sanitized)
    sdk_flags = (
        []
        if system == "macos"
        else subprocess.check_output(["pkg-config", "--cflags", "sdl3"], text=True, timeout=TOOL_TIMEOUT).split()
    )
    objects = []
    for unit in [probe.with_suffix(".m" if system == "macos" else ".c"), SHELL / "ShellState.c"]:
        output = tmp_path / f"{unit.stem}.o"
        command = [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            *flags,
            *sdk_flags,
            f"-I{ROOT / 'src/stdlib'}",
            f"-I{probe.parent}",
            "-c",
            str(unit),
            "-o",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=120)
        assert result.returncode == 0, result.stderr
        objects.append(str(output))

    def run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = flags
        elif "-o" in command:
            command.extend([*objects, *flags])
        return subprocess.run(command, env=environment, **kwargs)

    executable = tmp_path / "NativeShell"
    NativePlanBuilder(runner=run).build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=compiler,
        cxx="/usr/bin/clang++" if system == "macos" else "c++",
    )
    return executable


def write_evidence(name, platform_name, frontend, sanitized, observations, status="passed", reason=None):
    path = ROOT / "build/ui-shell" / f"{name}-{platform_name}-{frontend}-{'sanitized' if sanitized else 'plain'}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "btrc.qualification.ledger/1",
        "subject": {
            "kind": "test",
            "id": name,
            "platform": platform_name.split("-")[0],
            "frontend": "reference" if frontend == "python" else frontend,
            "variant": f"{platform_name}-{'sanitized' if sanitized else 'plain'}",
        },
        "evidence": {"status": status, "observed": json.dumps(observations, sort_keys=True), "artifact": str(path)},
        "provenance": {
            "runner": os.environ.get(
                "BTRC_TEST_RUNNER", "macos-hosted" if sys.platform == "darwin" else "linux-devcontainer"
            ),
            "recorded_at": datetime.now(UTC).isoformat(),
            "device_class": "stand-in",
            "btrc_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=TOOL_TIMEOUT
            ).strip(),
            "build_mode": "asan-ubsan" if sanitized else "plain",
            "os_build": platform.platform(),
        },
    }
    if reason:
        record["evidence"]["reason"] = reason
    path.write_text(json.dumps(record) + "\n")
    assert len(LedgerDocument.load(path)) == 1
    return path


def exercise_shell(tmp_path, request, frontend, sanitized, provider):
    executable = build_shell(tmp_path, frontend, sanitized, request)
    cycles = int(os.environ.get("BTRC_UI_SHELL_CYCLES", "100"))
    assert 1 <= cycles <= 100
    state = tmp_path / "state"
    state.mkdir()
    environment = shell_environment(sanitized)
    command = [str(executable), str(cycles), str(state)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=1200)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
        result = subprocess.CompletedProcess(command, 124, stdout, stderr + "\nShell exceeded 1200-second timeout")
    (tmp_path / "shell.stdout").write_text(result.stdout)
    (tmp_path / "shell.stderr").write_text(result.stderr)
    if result.returncode != 0 and sys.platform == "darwin":
        diagnostics = diagnose_macos_retention(executable, tmp_path, environment)
        pytest_message = result.stderr + result.stdout + "\n" + json.dumps(diagnostics, indent=2)
    else:
        pytest_message = result.stderr + result.stdout
    assert result.returncode == 0, pytest_message
    assert "ERROR: AddressSanitizer" not in result.stderr and "runtime error:" not in result.stderr
    summary = re.search(
        r"SHELL cycles=(\d+) frames=(\d+) native=(\d+) private=(\d+) registrations=(\d+) dirty-close=missing",
        result.stdout,
    )
    assert summary and int(summary[1]) == cycles, result.stdout
    native_handles, private_objects, registrations = map(int, summary.group(3, 4, 5))
    assert native_handles == registrations == 0, result.stdout
    teardown = re.findall(r"SHELL teardown provider=(\d+) private=(\d+) registrations=(\d+)", result.stdout)
    assert len(teardown) == cycles and all(int(row[0]) == int(row[2]) == 0 for row in teardown)
    probes = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert len(probes) == cycles
    if provider.startswith("linux"):
        assert all(probe["accessibility"] == "no bridge" for probe in probes)
    else:
        assert all(isinstance(probe["accessibility"], dict) for probe in probes)
    frames = int(summary[2])
    # Hosted AppKit's paravirtual Metal adapter is a correctness provider.
    assert frames == cycles, f"GPU not ready: {frames}/{cycles} frames; {result.stderr}"
    journal = (state / "journal").read_bytes()
    assert journal.decode().splitlines() == [f"commit {index}" for index in range(1, cycles + 1)]
    checkpoint = (state / "checkpoint").read_text().splitlines()
    assert checkpoint[0] == "draft" and int(checkpoint[1]) > 0 and int(checkpoint[2]) == cycles
    expected = f"RESTORE draft=draft anchor={checkpoint[1]} commits={cycles} actions=0"
    for restart in range(100):
        restored = subprocess.run(
            [str(executable), str(state), "restore"], env=environment, capture_output=True, text=True, timeout=30
        )
        (tmp_path / f"restore-{restart}.stdout").write_text(restored.stdout)
        (tmp_path / f"restore-{restart}.stderr").write_text(restored.stderr)
        assert restored.returncode == 0, restored.stderr + restored.stdout
        assert expected in restored.stdout.splitlines(), restored.stdout
        restored_teardown = re.search(
            r"SHELL teardown provider=(\d+) private=(\d+) registrations=(\d+)", restored.stdout
        )
        assert restored_teardown and int(restored_teardown[1]) == int(restored_teardown[3]) == 0
        assert (state / "journal").read_bytes() == journal
    return write_evidence(
        "native-shell" if cycles == 100 else "native-shell-smoke",
        provider,
        frontend,
        sanitized,
        {
            "cycles": cycles,
            "frames": frames,
            "native_handles": native_handles,
            "private_objects": private_objects,
            "live_registrations": registrations,
            "teardown": teardown,
            "fresh_process_restores": 100,
            "e46": "missing",
            "e47": "fixture-only; stdlib missing",
            "probes": probes,
            "gate_cycles": cycles == 100,
        },
    )


def diagnose_macos_retention(executable, tmp_path, environment):
    """Preserve each independent A/B result, even if another probe times out."""
    observations = []
    for no_ax, no_scroll in [(False, False), (True, False), (False, True), (True, True)]:
        name = f"diagnostic-ax-{int(not no_ax)}-wheel-{int(not no_scroll)}"
        state = tmp_path / name
        state.mkdir()
        configured = {**environment}
        for variable, disabled in [("BTRC_UI_SHELL_NO_AX", no_ax), ("BTRC_UI_SHELL_NO_SCROLL", no_scroll)]:
            configured.pop(variable, None)
            if disabled:
                configured[variable] = "1"
        try:
            result = subprocess.run(
                [str(executable), "1", str(state)], env=configured, capture_output=True, text=True, timeout=60
            )
            stdout, stderr, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
            stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
            code = "timeout"
        (state / "stdout").write_text(stdout)
        (state / "stderr").write_text(stderr)
        observations.append(
            {"ax": not no_ax, "wheel": not no_scroll, "returncode": code, "stdout": stdout, "stderr": stderr}
        )
        (tmp_path / "retention-diagnostics.json").write_text(json.dumps(observations, indent=2))
    return observations
