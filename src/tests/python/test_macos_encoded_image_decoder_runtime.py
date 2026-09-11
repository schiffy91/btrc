"""Real ImageIO provider behavior, typed SDK binding and failure cleanup."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/macos_encoded_image_decoder"
APPLE_CLANG = "/usr/bin/clang"
PACKAGE_NAME = "btrc_stdlib_runtime"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 60

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="ImageIO is available only on macOS")


def _apple_environment() -> dict[str, str]:
    # Do not select Nix's compiler-rt through the Apple developer-tool shim.
    return {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}


@pytest.fixture
def sdk_environment():
    reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not reader or not Path(reader).is_file():
        pytest.skip("requires the explicitly built native header reader")
    environment = _apple_environment()
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    return {
        **environment,
        "BTRC_NATIVE_SYSROOT": sdk,
        "BTRC_NATIVE_TARGET": f"{architecture}-apple-macosx14.0.0",
        "BTRC_HOME": str(ROOT / "src"),
    }


def _transpile(frontend, fixture, generated, plan, request, environment):
    target = "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64"
    flags = ["--strict-imports", "--target", target, "--emit-link-plan", str(plan), str(fixture)]
    if frontend == "python":
        command = [sys.executable, "-B", "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), *flags]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**environment, "BTRC_CACHE_DIR": str(generated.parent / "cache")},
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    if frontend != "python":
        generated.write_text(completed.stdout)
    payload = json.loads(plan.read_text())
    assert payload["units"] == []  # No handwritten decoder implementation.
    assert payload["frameworks"] == [
        {"name": name, "package": PACKAGE_NAME} for name in ("CoreFoundation", "CoreGraphics", "ImageIO")
    ]
    return payload


def _build(source, executable, frameworks, *, sanitized=False, hooks=False):
    command = [APPLE_CLANG, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
    if sanitized:
        command.extend(["-fsanitize=address,undefined", "-fno-omit-frame-pointer"])
    if hooks:
        command.extend(["-include", str(FIXTURES / "ImageIoFaults.h")])
    command.extend([f"-I{FIXTURES}", str(source)])
    for framework in frameworks:
        command.extend(["-framework", framework["name"]])
    command.extend(["-lm", "-o", str(executable)])
    built = subprocess.run(
        command,
        cwd=ROOT,
        env=_apple_environment(),
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert built.returncode == 0, built.stderr


def _run(executable, *arguments):
    ran = subprocess.run(
        [str(executable), *(str(argument) for argument in arguments)],
        env={**_apple_environment(), "ASAN_OPTIONS": "halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert ran.returncode == 0, ran.stderr
    return ran


@pytest.mark.parametrize(
    "fixture,hooks",
    [
        ("MacOsEncodedImageDecoderConformance", False),
        ("ImageIoCleanup", True),
    ],
)
def test_imageio_provider(compiler, fixture, hooks, tmp_path, request, sdk_environment):
    generated = tmp_path / f"{fixture}-{compiler}.c"
    plan = tmp_path / f"{fixture}-{compiler}.json"
    payload = _transpile(compiler, FIXTURES / f"{fixture}.btrc", generated, plan, request, sdk_environment)
    if compiler == "btrc":
        reference_plan = tmp_path / "reference.json"
        _transpile(
            "python", FIXTURES / f"{fixture}.btrc", tmp_path / "reference.c", reference_plan, request, sdk_environment
        )
        assert plan.read_bytes() == reference_plan.read_bytes()
    arguments = []
    if not hooks:
        fixture_encoder = tmp_path / "tiff-encoder"
        _build(FIXTURES / "ImageIoTiffFixture.c", fixture_encoder, payload["frameworks"])
        tiff = tmp_path / "two-frames.tiff"
        _run(fixture_encoder, tiff)
        assert tiff.is_file()
        arguments.append(tiff)
    for sanitized in (False, True):
        executable = tmp_path / f"{fixture}-{compiler}-{sanitized}"
        _build(generated, executable, payload["frameworks"], sanitized=sanitized, hooks=hooks)
        assert _run(executable, *arguments).stdout == f"PASS {fixture}\n"


def test_imageio_binding_requires_reader_before_emitting_code(tmp_path, monkeypatch):
    from src.compiler.python import Compiler, CompilerOptions

    monkeypatch.delenv("BTRC_NATIVE_HEADER_READER", raising=False)
    source = FIXTURES / "MacOsEncodedImageDecoderConformance.btrc"
    result = Compiler().compile(source.read_text(), str(source), CompilerOptions(use_cache=False, target="macos-arm64"))
    assert not result.successful and not result.c_source
    assert "BTRC_NATIVE_HEADER_READER" in str(result.failure)
