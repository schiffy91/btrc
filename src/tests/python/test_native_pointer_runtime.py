"""Native view input admission, coordinate mapping, capture and cancellation."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import REPO, apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_pointer_routing(native_project, native_compile, sanitize):
    source, _, _ = native_project
    root = source.parent.parent
    fixture = REPO / "src/tests/native/gui_surface"
    for name in ["NativePointerEvents.h", "NativePointerEvents.m"]:
        (root / name).write_text((fixture / name).read_text())
    (source.parent / "PointerEvents.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "nativePointer"\n'
        '[[native.bindings]]\nmodule = "PointerEvents"\nheader = "NativePointerEvents.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NativePointerEvents view]", "+[NativePointerEvents forwarded]", '
        '"+[NativePointerEvents scroll:x:y:]", "+[NativePointerEvents loseFocus:]", '
        '"NSEventTypeLeftMouseDown", "NSEventTypeLeftMouseDragged", "NSEventTypeLeftMouseUp", "NSEventTypeMouseMoved"]\n'
        '[[native.sources]]\npath = "NativePointerEvents.m"\nlanguage = "objective-c"\n'
        'standard = "c11"\nos = ["macos"]\n'
        '[[native.frameworks]]\nname = "AppKit"\nos = ["macos"]\n'
    )
    source.write_text((fixture / "NativePointer.btrc").read_text())
    plan = source.parent / "Pointer.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / "Pointer"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "pointer routing" in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr
