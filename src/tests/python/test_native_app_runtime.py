import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "app_surface"
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
        options = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if options and sanitized:
            options += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run([command[0], *options, *command[1:]], env=environment, **kwargs)

    executable = tmp_path / "Picker"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    for mode in range(9):
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
        options = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if options and sanitized:
            options += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *options, *command[1:]], env=environment, **kwargs)

    executable = tmp_path / control
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    expected = "scroll view composition" if scrolling else "text field editing"
    assert completed.stdout == f"PASS: AppKit {expected} from BTRC\n"
