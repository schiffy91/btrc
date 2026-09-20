"""`--emit-units` splits a program into translation units that link and run like the single unit."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "src/tests/collections/ForinInterfaceListLiteral.btrc"
GOLDEN = ROOT / "src/tests/collections/expected/ForinInterfaceListLiteral.stdout"


def _compile(frontend: str, out: Path, plan: Path, request, *extra: str) -> None:
    env = {**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_UNIT_LINES": "120"}
    if frontend == "btrcpy":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--strict-imports",
            "--target",
            "linux-x86_64",
            "--emit-link-plan",
            str(plan),
            "--emit-units",
            str(out),
            *extra,
            str(PROGRAM),
            "-o",
            str(out),
        ]
    else:
        command = [
            str(request.getfixturevalue("immutable_btrcc")),
            "--strict-imports",
            "--target",
            "linux-x86_64",
            "--emit-link-plan",
            str(plan),
            "--emit-units",
            str(out),
            *extra,
            "-o",
            str(out),
            str(PROGRAM),
        ]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(sys.platform != "linux" or shutil.which("cc") is None, reason="needs a Linux C toolchain")
@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_split_units_link_and_run_like_one(tmp_path, request, frontend):
    out = tmp_path / "program.c"
    plan = tmp_path / "program.json"
    _compile(frontend, out, plan, request)
    units = sorted(tmp_path.glob("program.c.unit-*.c"))
    assert len(units) >= 1, "a 120-line target must split this program"
    plan_text = plan.read_text()
    assert f'"emitted-units":{len(units)}' in plan_text and '"schema":3' in plan_text
    primary = out.read_text()
    assert "\n_Thread_local __btrc_tls_record __btrc_tls = {" in primary
    assert "static _Thread_local __btrc_tls_record __btrc_tls" not in primary
    secondary = units[0].read_text()
    assert "\nextern _Thread_local __btrc_tls_record __btrc_tls;" in secondary
    assert "__btrc_tls = {" not in secondary
    assert "static void* __btrc_cleanup_take" not in secondary
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=out, output=executable, cc="cc", cxx="c++")
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == GOLDEN.read_text()


def test_single_unit_output_keeps_static_runtime_state(tmp_path):
    out = tmp_path / "program.c"
    env = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    command = [
        sys.executable,
        "-m",
        "src.compiler.python.main",
        "--no-cache",
        "--strict-imports",
        "--target",
        "linux-x86_64",
        str(PROGRAM),
        "-o",
        str(out),
    ]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr
    text = out.read_text()
    assert "static _Thread_local __btrc_tls_record __btrc_tls = {" in text
    assert "extern _Thread_local" not in text
    assert not list(tmp_path.glob("program.c.unit-*.c"))


@pytest.mark.skipif(sys.platform != "linux" or shutil.which("cc") is None, reason="needs a Linux C toolchain")
@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_debug_split_units_map_lines_and_run(tmp_path, request, frontend):
    """--debug stamps #line back to the .btrc source in every unit, each unit
    names itself for synthesized code, and -g binaries still match the golden."""
    out = tmp_path / "program.c"
    plan = tmp_path / "program.json"
    _compile(frontend, out, plan, request, "--debug")
    units = sorted(tmp_path.glob("program.c.unit-*.c"))
    assert units
    program_lines = 0
    for path in [out, *units]:
        directives = [line for line in path.read_text().splitlines() if line.startswith("#line ")]
        program_lines += sum(line.endswith(f'"{PROGRAM}"') for line in directives)
        generated = {line.rsplit(" ", 1)[1] for line in directives if line.endswith('.c"')}
        assert generated <= {f'"{path}"'}, f"{path.name} resets #line to another unit: {generated}"
    assert program_lines > 0, "no unit maps a line back to the program"
    executable = tmp_path / "program"
    NativePlanBuilder().build(
        plan_path=plan, generated_c=out, output=executable, cc="cc", cxx="c++", optimization=0, debug_info=True
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout == GOLDEN.read_text()
    with_debug = subprocess.run(["readelf", "--debug-dump=line", str(executable)], capture_output=True, text=True)
    if with_debug.returncode == 0:
        assert "ForinInterfaceListLiteral.btrc" in with_debug.stdout
