import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src" / "stdlib" / "app"
GPU = ROOT / "src" / "stdlib" / "gpu"
GUI = ROOT / "src" / "stdlib" / "gui"
FIXTURE = ROOT / "src" / "tests" / "native" / "app_surface"
FAKE_GLFW = FIXTURE / "fake_glfw"
HARNESS = FIXTURE / "actual_app_runtime.c"
DIRECTORY_PICKER_PROBE = FIXTURE / "directory_picker_macos_probe.c"
COMPILE_TIMEOUT = 120
RUN_TIMEOUT = 30


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


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_hosted_capability_abi_matches_linux_uint64_typedef(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    compiler = shutil.which(c_compiler)
    if not compiler:
        pytest.skip(f"{c_compiler} is unavailable")

    fake_system = tmp_path / "fake-system"
    fake_system.mkdir()
    (fake_system / "stdint.h").write_text(
        "#ifndef TEST_STDINT_H\n#define TEST_STDINT_H\ntypedef unsigned long uint64_t;\n#endif\n"
    )
    consumer = tmp_path / "capability-abi.c"
    consumer.write_text(
        "#include <btrc_app.h>\n"
        "#include <btrc_gpu.h>\n"
        "unsigned long long std_app_create(unsigned long long*);\n"
        "unsigned long long std_app_window_open(\n"
        "    unsigned long long, char*, int, int, unsigned long long*);\n"
        "unsigned long long std_app_surface_generation(unsigned long long);\n"
        "int std_app_poll(unsigned long long);\n"
        "int std_app_close(unsigned long long, unsigned long long);\n"
        "int std_gpu_attach_surface(\n"
        "    unsigned long long, unsigned long long*, unsigned long long*);\n"
        "int std_gpu_pipeline_create(\n"
        "    unsigned long long, unsigned long long, char*, char*,\n"
        "    unsigned long long*, unsigned long long*);\n"
        "int std_gpu_draw_uniform(\n"
        "    unsigned long long, unsigned long long, int,\n"
        "    unsigned long long);\n"
    )
    for header, prefix in [
        (APP / "btrc_app.h", "std_app_"),
        (GPU / "btrc_gpu.h", "std_gpu_"),
    ]:
        declarations = re.sub(r"/\*.*?\*/", "", header.read_text(), flags=re.DOTALL)
        for declaration in declarations.split(";"):
            if prefix in declaration:
                assert "uint64_t" not in declaration

    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{fake_system}",
            f"-I{APP}",
            f"-I{GPU}",
            "-c",
            str(consumer),
            "-o",
            str(tmp_path / f"capability-abi-{c_compiler}.o"),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize(
    "includes",
    [
        "#include <btrc_app.h>\n#include <btrc_gui_window.h>\n",
        "#include <btrc_gui_window.h>\n#include <btrc_app.h>\n",
    ],
)
def test_legacy_gui_window_cannot_compose_with_std_app(
    tmp_path: Path,
    includes: str,
) -> None:
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("C compiler is unavailable")
    source = tmp_path / "mixed-window-owners.c"
    source.write_text(includes)
    result = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{APP}",
            f"-I{GUI}",
            "-c",
            str(source),
            "-o",
            str(tmp_path / "mixed-window-owners.o"),
        ],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode != 0
    assert "cannot be composed" in result.stderr


def _compile_actual_app_runtime(
    compiler: str,
    output: Path,
    extra_flags: list[str] | None = None,
) -> None:
    flags = [
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        "-pthread",
        *(extra_flags or []),
        f"-I{FAKE_GLFW}",
        f"-I{FIXTURE}",
        f"-I{APP}",
    ]
    app_object = output.with_suffix(".app.o")
    fake_object = output.with_suffix(".fake-glfw.o")
    harness_object = output.with_suffix(".harness.o")
    subprocess.run(
        [
            compiler,
            *flags,
            "-Dcalloc=btrc_app_test_calloc",
            "-Dfree=btrc_app_test_free",
            "-c",
            str(APP / "btrc_app.c"),
            "-o",
            str(app_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            compiler,
            *flags,
            "-c",
            str(FIXTURE / "fake_glfw_runtime.c"),
            "-o",
            str(fake_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            compiler,
            *flags,
            "-c",
            str(HARNESS),
            "-o",
            str(harness_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [
            compiler,
            *(extra_flags or []),
            app_object,
            fake_object,
            harness_object,
            "-pthread",
            "-o",
            output,
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_actual_app_runtime_state_machine(tmp_path: Path, c_compiler: str) -> None:
    compiler = shutil.which(c_compiler)
    if not compiler:
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"actual-app-{c_compiler}"
    _compile_actual_app_runtime(compiler, executable)
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: actual std.app runtime state machine\n"
    assert result.stderr == ""


def test_actual_app_runtime_state_machine_under_clang_sanitizers(
    tmp_path: Path,
) -> None:
    compiler = "/usr/bin/clang" if sys.platform == "darwin" else shutil.which("clang")
    if not compiler or not Path(compiler).is_file():
        pytest.skip("clang is unavailable")
    executable = tmp_path / "actual-app-sanitized"
    _compile_actual_app_runtime(compiler, executable, _sanitizer_flags())
    result = subprocess.run(
        [str(executable)],
        env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: actual std.app runtime state machine\n"
    assert result.stderr == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native provider")
def test_macos_directory_picker_native_provider(tmp_path: Path) -> None:
    compiler = "/usr/bin/clang"
    provider_object = tmp_path / "directory-picker-provider.o"
    probe_object = tmp_path / "directory-picker-probe.o"
    executable = tmp_path / "directory-picker-probe"
    strict = [
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        f"-I{APP}",
    ]
    subprocess.run(
        [
            compiler,
            *strict,
            "-x",
            "objective-c",
            "-c",
            str(APP / "btrc_app_directory_picker_macos.m"),
            "-o",
            str(provider_object),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [compiler, *strict, "-c", str(DIRECTORY_PICKER_PROBE), "-o", str(probe_object)],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    subprocess.run(
        [compiler, str(provider_object), str(probe_object), "-pthread", "-framework", "Cocoa", "-o", str(executable)],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: macOS directory picker native provider\n"
    assert result.stderr == ""
