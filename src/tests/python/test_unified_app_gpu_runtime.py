import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src" / "stdlib" / "app"
GPU = ROOT / "src" / "stdlib" / "gpu"
FIXTURE = ROOT / "src" / "tests" / "native" / "app_surface"
CONFORMANCE = FIXTURE / "app_surface_conformance.btrc"
REAL_SMOKE = FIXTURE / "real_app_gpu_smoke.btrc"
COMPILE_TIMEOUT = 180
RUN_TIMEOUT = 90


def _sanitizer_flags() -> list[str]:
    # macOS 26's ASan runtime deadlocks before main; UBSan remains runnable.
    macos_major = platform.mac_ver()[0].split(".", 1)[0]
    asan_deadlocks = sys.platform == "darwin" and macos_major.isdigit() and int(macos_major) >= 26
    sanitizer = "undefined" if asan_deadlocks else "address,undefined"
    return [
        "-O1",
        "-g",
        "-fno-omit-frame-pointer",
        f"-fsanitize={sanitizer}",
    ]


def _transpile(
    frontend: str,
    source: Path,
    output: Path,
    request: pytest.FixtureRequest,
) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(output.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(output),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(btrcc), str(source)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr


def _compile_conformance(
    generated: Path,
    executable: Path,
    c_compiler: str,
    extra_flags: list[str] | None = None,
) -> None:
    strict = [
        c_compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        *(extra_flags or []),
        f"-I{FIXTURE}",
        f"-I{APP}",
        f"-I{GPU}",
    ]
    generated_object = executable.with_suffix(".generated.o")
    runtime_object = executable.with_suffix(".runtime.o")
    subprocess.run(
        [*strict, "-c", str(generated), "-o", str(generated_object)],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            *strict,
            "-c",
            str(FIXTURE / "fake_app_gpu_runtime.c"),
            "-o",
            str(runtime_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            c_compiler,
            *(extra_flags or []),
            str(generated_object),
            str(runtime_object),
            "-pthread",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_unified_app_gpu_contract_on_both_frontends_and_c_compilers(
    compiler: str,
    c_compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"app-gpu-{compiler}-{c_compiler}.c"
    executable = tmp_path / f"app-gpu-{compiler}-{c_compiler}"
    _transpile(compiler, CONFORMANCE, generated, request)
    _compile_conformance(generated, executable, c_compiler)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: unified application surface conformance\n"
    assert result.stderr == ""


def test_unified_app_gpu_contract_under_clang_sanitizers(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    clang = "/usr/bin/clang" if sys.platform == "darwin" else shutil.which("clang")
    if not clang:
        pytest.skip("clang is unavailable")
    generated = tmp_path / "app-gpu-sanitized.c"
    executable = tmp_path / "app-gpu-sanitized"
    _transpile("python", CONFORMANCE, generated, request)
    _compile_conformance(
        generated,
        executable,
        clang,
        _sanitizer_flags(),
    )
    result = subprocess.run(
        [str(executable)],
        env={
            **os.environ,
            "ASAN_OPTIONS": "halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1",
        },
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: unified application surface conformance\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("owner", "construction"),
    [
        (
            "ApplicationWindow",
            "Application app = new Application(); ApplicationWindow value = new ApplicationWindow(app, 1ULL, 2ULL);",
        ),
        (
            "AppSurfaceAttachment",
            "AppSurfaceAttachment value = new AppSurfaceAttachment(null, 3ULL, 4ULL);",
        ),
        ("GPU", "GPU value = new GPU(5ULL, 6ULL, null);"),
        ("GPUShader", "GPUShader value = new GPUShader(null, 7ULL, 8ULL);"),
        (
            "GPURenderPipeline",
            "GPURenderPipeline value = new GPURenderPipeline(null, null, 9ULL, 10ULL);",
        ),
        ("GPUUniform", "GPUUniform value = new GPUUniform(null, 11ULL, 12ULL);"),
    ],
)
def test_native_owner_wrapper_constructors_are_private_on_both_frontends(
    compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    owner: str,
    construction: str,
) -> None:
    app_directory = tmp_path / "app"
    gpu_directory = tmp_path / "gpu"
    app_directory.mkdir()
    gpu_directory.mkdir()
    (app_directory / "app.btrc").write_text((APP / "app.btrc").read_text())
    (gpu_directory / "gpu.btrc").write_text((GPU / "gpu.btrc").read_text())
    source = tmp_path / "forged-owners.btrc"
    source.write_text(f"import ./gpu/gpu.btrc;\nint main() {{\n    {construction}\n    return 0;\n}}\n")
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(tmp_path / f"cache-private-{compiler}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if compiler == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--no-cache",
            "-o",
            str(tmp_path / "forged.c"),
        ]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), str(source)]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode != 0
    assert f"Cannot call private constructor of class '{owner}'" in result.stderr


def test_real_window_and_present_smoke_when_explicitly_enabled(
    compiler: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    if os.environ.get("BTRC_REAL_WINDOW_TEST") != "1":
        pytest.skip("set BTRC_REAL_WINDOW_TEST=1 to open a real window")
    cflags = os.environ.get("GPU_CFLAGS")
    ldflags = os.environ.get("GPU_LDFLAGS")
    if not cflags or not ldflags:
        pytest.skip("real WebGPU/GLFW build flags are unavailable")
    app_archive = ROOT / "build" / "stdlib" / "app" / "libbtrc_app.a"
    gpu_archive = ROOT / "build" / "stdlib" / "gpu" / "libbtrc_gpu.a"
    if not app_archive.is_file() or not gpu_archive.is_file():
        pytest.skip("build the std.app and std.gpu archives first")

    generated = tmp_path / f"real-app-gpu-{compiler}.c"
    executable = tmp_path / f"real-app-gpu-{compiler}"
    _transpile(compiler, REAL_SMOKE, generated, request)
    subprocess.run(
        [
            os.environ.get("CC", "cc"),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            *shlex.split(cflags),
            f"-I{APP}",
            f"-I{GPU}",
            str(generated),
            str(gpu_archive),
            str(app_archive),
            *shlex.split(ldflags),
            "-lm",
            "-pthread",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    if result.returncode == 77:
        pytest.skip(result.stdout.strip() or "real window/GPU backend unavailable")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: real application window GPU presentation\n"
