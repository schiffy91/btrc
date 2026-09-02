import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.declarations import AbiType
from src.compiler.python.abi.hosted import HOSTED_ABI
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src" / "stdlib" / "core_audio_device"
FIXTURE = ROOT / "src" / "tests" / "native" / "core_audio_device"
CONFORMANCE = FIXTURE / "core_audio_device_conformance.btrc"
SMOKE = FIXTURE / "core_audio_device_smoke.c"
PACKAGE_NAME = "btrc_stdlib_core_audio_device_runtime"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 30

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio is available only on macOS")


def _transpile(frontend: str, generated: Path, plan: Path, request: pytest.FixtureRequest) -> None:
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
            str(CONFORMANCE),
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
            str(CONFORMANCE),
        ]
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if completed.returncode == 0:
            generated.write_text(completed.stdout)
    assert completed.returncode == 0 and generated.is_file() and plan.is_file(), completed.stderr


def test_core_audio_native_callback_and_lifecycle(tmp_path: Path) -> None:
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("Clang is unavailable")
    executable = tmp_path / "core-audio-smoke"
    command = [
        clang,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        f"-I{RUNTIME}",
        str(SMOKE),
        str(RUNTIME / "btrc_core_audio_device.c"),
        "-framework",
        "AudioToolbox",
        "-framework",
        "CoreAudio",
        "-framework",
        "CoreFoundation",
        "-o",
        str(executable),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stderr == ""
    assert ran.stdout in {
        "PASS: CoreAudio device callback and drain barrier\n",
        "SKIP: CoreAudio output capability unavailable\n",
        "SKIP: CoreAudio output session unavailable\n",
    }


def test_core_audio_provider_on_both_frontends(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    clang = shutil.which("clang")
    clangxx = shutil.which("clang++")
    if clang is None or clangxx is None:
        pytest.skip("Clang is unavailable")
    generated = tmp_path / f"core-audio-{compiler}.c"
    plan = tmp_path / f"core-audio-{compiler}.link.json"
    _transpile(compiler, generated, plan, request)
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
    assert payload["units"] == [
        {
            "language": "c",
            "package": PACKAGE_NAME,
            "path": str(RUNTIME / "btrc_core_audio_device.c"),
            "standard": "c11",
        }
    ]
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


def test_core_audio_stored_callback_abi_preserves_borrowed_spans() -> None:
    callback = AbiType(
        "CFunction",
        generic_args=(
            AbiType("void"),
            AbiType("void", 1),
            AbiType("struct AudioBlockView"),
            AbiType("Span", generic_args=(AbiType("float", is_const=True),)),
            AbiType("Span", generic_args=(AbiType("float"),)),
        ),
    )
    opened = HOSTED_ABI.function("std_core_audio_provider_open_duplex")
    assert opened is not None and opened.parameters is not None
    assert opened.parameters[10] == callback
    assert opened.callback_lifetimes[10] == "stored_until_unregister"


def test_core_audio_render_path_contains_no_control_plane_operations() -> None:
    source = (RUNTIME / "btrc_core_audio_device.c").read_text()
    start = source.index("static OSStatus btrc_core_audio_render(")
    end = source.index("static int btrc_core_audio_allocate_buffers", start)
    callback = source[start:end]
    for forbidden in (
        "calloc(",
        "free(",
        "malloc(",
        "nanosleep(",
        "printf(",
        "pthread_",
        "AudioComponentInstanceDispose(",
        "AudioOutputUnitStart(",
        "AudioOutputUnitStop(",
        "AudioUnitInitialize(",
        "AudioUnitUninitialize(",
    ):
        assert forbidden not in callback
