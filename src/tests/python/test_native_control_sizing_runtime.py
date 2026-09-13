"""Real native bezel sizing and title containment at the supported font limit."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import REPO, apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitize", [False, True])
def test_native_control_sizing(native_project, native_compile, sanitize):
    source, _, _ = native_project
    source.write_text((REPO / "src/tests/native/gui_surface/NativeControlSizing.btrc").read_text())
    plan = source.with_suffix(".link.json")
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(str(item) for item in compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)
    executable = source.parent / "ControlSizing"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run(
        [str(executable)], cwd=source.parent, env=apple_environment(), capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert "contained 20-point ink" in completed.stdout
    assert "ERROR: AddressSanitizer" not in completed.stderr
