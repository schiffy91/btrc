import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "src" / "stdlib" / "App"
GPU = ROOT / "src" / "stdlib" / "GPU"
GUI = ROOT / "src" / "stdlib" / "GUI"
FIXTURE = ROOT / "src" / "tests" / "native" / "app_surface"
FAKE_GLFW = FIXTURE / "fake_glfw"
HARNESS = FIXTURE / "actual_app_runtime.c"
COMPILE_TIMEOUT = 120
RUN_TIMEOUT = 30


@pytest.mark.skipif(sys.platform != "darwin", reason="requires real AppKit")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
def test_btrc_directory_picker_appkit(tmp_path, request, frontend, sanitized):
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires the explicitly built native header reader")
    environment = {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    environment.update(
        BTRC_NATIVE_SYSROOT=sdk, BTRC_NATIVE_TARGET=f"{architecture}-apple-macosx14.0.0", BTRC_HOME=str(ROOT / "src")
    )
    for name in ["MacOsDirectoryPickerConformance.btrc", "DirectoryPickerControl.h", "DirectoryPickerControl.m"]:
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "pickerTest"\n'
        '[[native.sources]]\npath = "DirectoryPickerControl.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.include-directories]]\npath = "."\n'
    )
    source = tmp_path / "MacOsDirectoryPickerConformance.btrc"
    generated = tmp_path / "Picker.c"
    plan = tmp_path / "Picker.link.json"
    flags = ["--no-stdlib", "--target", f"macos-{architecture}", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-B", "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(generated)]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc")), *flags]
    )
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout)
    payload = json.loads(plan.read_text())
    assert len(payload["units"]) == 1  # Only the test controller is handwritten.
    assert payload["generated-units"]
    assert "std_app_window_choose_directory" not in generated.read_text()

    def run(command, **kwargs):
        options = ["-O2", *(["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else [])]
        return subprocess.run([command[0], *options, *command[1:]], env=environment, **kwargs)

    executable = tmp_path / "Picker"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    for mode in range(8):
        try:
            completed = subprocess.run(
                [str(executable), str(mode)],
                env={**environment, "ASAN_OPTIONS": "halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
            )
        except subprocess.TimeoutExpired as error:
            pytest.fail(f"directory picker mode {mode} timed out: {error.stderr}")
        assert completed.returncode == 0, f"mode {mode}: {completed.stderr}"
        assert completed.stdout == f"PASS: BTRC directory picker mode {mode}\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="requires real AppKit")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.parametrize("consumer_first", [False, True])
@pytest.mark.parametrize("scrolling", [False, True], ids=["field", "scroll"])
def test_btrc_text_field_appkit(tmp_path, request, frontend, sanitized, consumer_first, scrolling):
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires the explicitly built native header reader")
    environment = {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}
    sdk = subprocess.run(
        ["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
    environment.update(
        BTRC_NATIVE_SYSROOT=sdk, BTRC_NATIVE_TARGET=f"{architecture}-apple-macosx14.0.0", BTRC_HOME=str(ROOT / "src")
    )
    control = "ScrollView" if scrolling else "TextField"
    for name in [f"MacOs{control}Conformance.btrc", f"{control}Control.h", f"{control}Control.m"]:
        shutil.copyfile(FIXTURE / name, tmp_path / name)
    symbols = (
        [
            "+[NativeScrollViewProbe prepare:scroll:header:]",
            "+[NativeScrollViewProbe wheel]",
            "+[NativeScrollViewProbe finish:]",
        ]
        if scrolling
        else [
            "+[NativeTextFieldProbe prepare:]",
            "+[NativeTextFieldProbe mount:]",
            "-[NSView addSubview:]",
            "+[NativeTextFieldProbe replaceSelection]",
            "+[NativeTextFieldProbe selectionUnchanged]",
            "+[NativeTextFieldProbe undo]",
            "+[NativeTextFieldProbe redo]",
            "+[NativeTextFieldProbe queueKey]",
            "+[NativeTextFieldProbe finish:]",
        ]
    )
    (tmp_path / "ControlProbe.btrc").write_text("// Native AppKit test driver declarations.\n")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "textFieldTest"\n'
        f'[[native.sources]]\npath = "{control}Control.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.include-directories]]\npath = "."\n'
        f'[[native.bindings]]\nmodule = "ControlProbe"\nheader = "{control}Control.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[[native.frameworks]]\nname = "CoreGraphics"\nos = ["macos"]\n'
    )
    source = tmp_path / f"MacOs{control}Conformance.btrc"
    if consumer_first:
        source.write_text(
            "import ./ControlProbe.btrc;\n\n" + source.read_text().replace("import ./ControlProbe.btrc;\n", "")
        )
        assert source.read_text().startswith("import ./ControlProbe.btrc;")
    generated = tmp_path / f"{control}.c"
    plan = tmp_path / f"{control}.link.json"
    flags = ["--no-stdlib", "--target", f"macos-{architecture}", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-B", "-m", "src.compiler.python.main", "--no-cache", *flags, "-o", str(generated)]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc")), *flags]
    )
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout)
    payload = json.loads(plan.read_text())
    assert len(payload["units"]) == 1  # Test driver only; the provider is BTRC.
    assert payload["generated-units"]

    def run(command, **kwargs):
        options = ["-O2", *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else [])]
        return subprocess.run([command[0], *options, *command[1:]], env=environment, **kwargs)

    executable = tmp_path / control
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    expected = "scroll view composition" if scrolling else "text field editing"
    assert completed.stdout == f"PASS: AppKit {expected} from BTRC\n"


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
    assert result.stdout == "PASS: actual Library.App runtime state machine\n"
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
    assert result.stdout == "PASS: actual Library.App runtime state machine\n"
    assert result.stderr == ""


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS native provider")
def test_macos_integrated_titlebar_native_provider(tmp_path: Path) -> None:
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        pytest.skip("GLFW pkg-config is unavailable")
    glfw_flags = subprocess.run(
        [pkg_config, "--cflags", "--libs", "glfw3"], capture_output=True, text=True, check=True, timeout=COMPILE_TIMEOUT
    )
    executable = tmp_path / "titlebar-probe"
    subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            f"-I{APP}",
            str(APP / "btrc_app.c"),
            str(APP / "btrc_app_window_macos.m"),
            str(FIXTURE / "titlebar_macos_probe.m"),
            *shlex.split(glfw_flags.stdout),
            "-pthread",
            "-framework",
            "Cocoa",
            "-o",
            str(executable),
        ],
        check=True,
        timeout=COMPILE_TIMEOUT,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: native macOS integrated titlebar, controls, resize, and restoration\n"
