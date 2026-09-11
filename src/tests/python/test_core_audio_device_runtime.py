import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "core_audio_device"
CONFORMANCE = FIXTURE / "CoreAudioDeviceConformance.btrc"
PACKAGE_NAME = "btrc_stdlib_runtime"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 30

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio is available only on macOS")


def _transpile(
    frontend: str, generated: Path, plan: Path, request: pytest.FixtureRequest, fixture: Path = CONFORMANCE
) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(generated.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--strict-imports",
            "--no-cache",
            "--target",
            "macos-arm64",
            "--emit-link-plan",
            str(plan),
            str(fixture),
            "-o",
            str(generated),
        ]
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [
            str(btrcc),
            "--strict-imports",
            "--target",
            "macos-arm64",
            "--emit-link-plan",
            str(plan),
            str(fixture),
        ]
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if completed.returncode == 0:
            generated.write_text(completed.stdout)
    assert completed.returncode == 0 and generated.is_file() and plan.is_file(), completed.stderr


def test_core_audio_provider_on_both_frontends(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    clang = shutil.which("clang")
    clangxx = shutil.which("clang++")
    if clang is None or clangxx is None:
        pytest.skip("Clang is unavailable")
    generated = tmp_path / f"core-audio-{compiler}.c"
    plan = tmp_path / f"core-audio-{compiler}.link.json"
    _transpile(compiler, generated, plan, request)
    assert "Audio/MacOS/Hardware.h" in generated.read_text()
    assert "CoreAudioNativeDeviceRecord" not in generated.read_text()
    if compiler == "btrc":
        reference_generated = tmp_path / "core-audio-reference.c"
        reference_plan = tmp_path / "core-audio-reference.link.json"
        _transpile("python", reference_generated, reference_plan, request)
        assert plan.read_bytes() == reference_plan.read_bytes()
    payload = json.loads(plan.read_text())
    assert payload["frameworks"] == [
        {"name": "AudioToolbox", "package": PACKAGE_NAME},
        {"name": "CoreAudio", "package": PACKAGE_NAME},
        {"name": "CoreFoundation", "package": PACKAGE_NAME},
    ]
    assert payload["units"] == []
    executable = tmp_path / f"core-audio-{compiler}"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc=clang, cxx=clangxx)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stderr == ""
    assert ran.stdout in {
        "PASS: CoreAudio provider callback and drain barrier\n",
        "SKIP: CoreAudio provider unavailable\n",
        "SKIP: CoreAudio output capability unavailable\n",
        "SKIP: CoreAudio output session unavailable\n",
    }
    if ran.stdout.startswith("SKIP:"):
        pytest.skip(ran.stdout.strip())


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize(
    "fixture_name, adapter, expected",
    [
        (
            "CoreAudioUnitConformance.btrc",
            "UnitFaults",
            "PASS: BTRC CoreAudio unit preserves samples, clocks and retryable ownership",
        ),
        (
            "CoreAudioInventoryConformance.btrc",
            "HardwareFaults",
            "PASS: CoreAudio inventory validates SDK data and publishes stable snapshots",
        ),
        ("CoreAudioResourcesConformance.btrc", "ResourceFaults", "PASS: CoreAudio resource ownership and rollback"),
        (
            "CoreAudioAggregateAllocations.btrc",
            "AggregateAllocationFaults",
            "PASS: CoreAudio aggregate releases every partial allocation",
        ),
        (
            "CoreAudioPendingSession.btrc",
            "HardwareFaults",
            "PASS: CoreAudio provider retains partial sessions until cleanup succeeds",
        ),
    ],
)
def test_core_audio_inventory_sdk_failures(
    compiler: str,
    sanitized: bool,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    fixture_name: str,
    adapter: str,
    expected: str,
) -> None:
    generated = tmp_path / "Inventory.c"
    plan = tmp_path / "Inventory.link.json"
    _transpile(compiler, generated, plan, request, FIXTURE / fixture_name)
    executable = tmp_path / "Inventory"
    environment = {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}
    sdk_flags = ["-isysroot", os.environ["BTRC_NATIVE_SYSROOT"], "-target", os.environ["BTRC_NATIVE_TARGET"]]
    command = [
        "/usr/bin/clang",
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        *sdk_flags,
        *(["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []),
        "-include",
        str(FIXTURE / f"{adapter}.h"),
        str(generated),
        str(FIXTURE / f"{adapter}.c"),
        *(
            ["-include", str(FIXTURE / "UnitFaults.h"), str(FIXTURE / "UnitFaults.c")]
            if fixture_name == "CoreAudioPendingSession.btrc"
            else []
        ),
        "-framework",
        "CoreAudio",
        "-framework",
        "CoreFoundation",
        "-framework",
        "AudioToolbox",
        "-o",
        str(executable),
    ]
    # Link only SDK-shaped fault probes; no handwritten production bridge.
    built = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == expected + "\n"
