"""Real field-editor input through the native UI2 text owner."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
PROBES = ROOT / "src/tests/native/gui/ui2/probes/macos"
TEXT_PROBE_SYMBOLS = [
    "+[UI2TextProbe open]",
    "+[UI2TextProbe begin:]",
    "+[UI2TextProbe insert:text:]",
    "+[UI2TextProbe mark:text:]",
    "+[UI2TextProbe accept:]",
    "+[UI2TextProbe escape:]",
    "+[UI2TextProbe blur]",
    "+[UI2TextProbe marked:]",
    "+[UI2TextProbe rememberEditor:]",
    "+[UI2TextProbe editorUnchanged:]",
    "+[UI2TextProbe close]",
]


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
def test_native_text_state(native_project, native_compile, gui_provider_root, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / "NativeTextState.btrc").read_text())
    shutil.copyfile(PROBES / "TextProbe.btrc", source.parent / "TextProbe.btrc")
    for name in ("TextProbe.h", "TextProbe.m"):
        shutil.copyfile(PROBES / name, root / name)
    # White-box queue accounting remains private to the fixture's data root.
    data_root = root / "provider-data"
    shutil.copytree(gui_provider_root, data_root, symlinks=True)
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "ui2MacOSText"\n'
        '[[native.bindings]]\nmodule = "TextProbe"\nheader = "TextProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(TEXT_PROBE_SYMBOLS)}\n"
        '[[native.sources]]\npath = "TextProbe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    plan = root / "Text.link.json"
    compiled = native_compile(source, data_root=data_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Text.c"
    generated.write_text(compiled.c_source)
    executable = root / "Text"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    try:
        completed = subprocess.run(
            [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired as error:
        for suffix, output in (("stdout", error.stdout), ("stderr", error.stderr)):
            (root / f"run.{suffix}").write_bytes(output if isinstance(output, bytes) else (output or "").encode())
        raise
    (root / "run.stdout").write_text(completed.stdout)
    (root / "run.stderr").write_text(completed.stderr)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert "UI2 native text preserves draft ownership and ordered terminal eligibility" in completed.stdout
