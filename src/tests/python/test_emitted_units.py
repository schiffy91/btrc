"""`--emit-units` splits a program into translation units that link and run like the single unit."""

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
PROGRAM = ROOT / "src/tests/collections/ForinInterfaceListLiteral.btrc"
GOLDEN = ROOT / "src/tests/collections/expected/ForinInterfaceListLiteral.stdout"


@pytest.mark.parametrize("split", [False, True])
def test_debug_filename_encoding_is_shared_within_one_emission(monkeypatch, split):
    from collections import Counter

    from src.compiler.python.backend.c_emitter import CEmitter
    from src.compiler.python.ir.nodes import CType, IRBlock, IRFunctionDef, IRLineMarker, IRLiteral, IRModule, IRReturn

    encode = CEmitter._c_line_filename
    calls = []

    def counted(path):
        calls.append(path)
        return encode(path)

    monkeypatch.setattr(CEmitter, "_c_line_filename", staticmethod(counted))
    emitter = CEmitter()
    for generation in range(2):
        calls.clear()
        source = 'source-shared\\"??/line\n.btrc'
        generated = f'generated-{generation}".c'
        module = IRModule(debug=True, debug_cfile=generated)
        module.function_defs = [
            IRFunctionDef(
                name=f"function{index}",
                return_type=CType("int"),
                source_file=f"Module{index}.btrc",
                body=IRBlock(
                    [IRLineMarker(file=source, line=11), IRReturn(IRLiteral(text=str(index)))]
                    if index % 2 == 0
                    else [IRReturn(IRLiteral(text=str(index)))]
                ),
            )
            for index in range(6)
        ]
        units = emitter.emit_units(module, 1, generated) if split else [emitter.emit(module)]
        assert f'#line 11 "{encode(source)}"' in "\n".join(units)
        assert Counter(calls)[source] == 1
        assert calls and all(count == 1 for count in Counter(calls).values())
        assert f'generated-{1 - generation}\\".c' not in "\n".join(units)
        assert "@@BTRC_CLINE@@" not in "\n".join(units)
        for index, unit in enumerate(units):
            filename = generated if index == 0 else f"{generated}.unit-{index}.c"
            for number, line in enumerate(unit.splitlines(), 1):
                if line.startswith("#line ") and line.endswith(f'"{encode(filename)}"'):
                    assert line == f'#line {number + 1} "{encode(filename)}"'


@pytest.mark.skipif(os.name == "nt" or shutil.which("cc") is None, reason="POSIX filenames and a C toolchain")
@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_debug_split_build_preserves_escaped_source_and_output_paths(tmp_path, request, frontend):
    from src.compiler.python.backend.c_emitter import CEmitter

    directory = tmp_path / 'quoted" backslash\\ question?? newline\n'
    directory.mkdir()
    source = directory / "Main.btrc"
    dependency = directory / "Other.btrc"
    dependency.write_text("int answer() { int value = 7; return value; }\n")
    source.write_text("import ./Other.btrc;\nint main() { return answer() - 7; }\n")
    output = directory / "program.c"
    plan = directory / "program.json"
    command = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if frontend == "btrcpy"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    host_os = "macos" if sys.platform == "darwin" else "linux"
    host_arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "x64"
    result = subprocess.run(
        [
            *command,
            "--no-cache",
            "--strict-imports",
            "--no-stdlib",
            "--target",
            f"{host_os}-{host_arch}",
            "--debug",
            "--emit-units",
            str(output),
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(output),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_UNIT_LINES": "1"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    paths = [output, *(Path(path) for path in json.loads(plan.read_text())["emitted-units"])]
    text = "\n".join(path.read_text() for path in paths)
    for path in (source, dependency):
        assert f'"{CEmitter._c_line_filename(str(path))}"' in text
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=output, output=executable, optimization=0, debug_info=True)
    run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("stdout", [False, True])
def test_split_generated_debug_locations_use_secondary_prefix(tmp_path, stdout):
    from src.compiler.python.backend.c_emitter import CEmitter
    from src.compiler.python.ir.nodes import CType, IRBlock, IRFunctionDef, IRLiteral, IRModule, IRReturn

    primary = "" if stdout else str(tmp_path / "primary.c")
    prefix = str(tmp_path / "parts" / "secondary")
    module = IRModule(debug=True, debug_cfile=primary)
    # Generated body lines have no btrc location; they must map to the actual
    # emitted C file rather than inheriting another unit's debug filename.
    module.function_defs = [
        IRFunctionDef(
            name=f"function{index}",
            return_type=CType("int"),
            source_file=f"Module{index}.btrc",
            body=IRBlock([IRReturn(IRLiteral(text=str(index)))]),
        )
        for index in range(3)
    ]
    units = CEmitter().emit_units(module, 1, prefix)
    assert len(units) == 3
    for index, unit in enumerate(units):
        expected = (primary or "<btrc-generated>") if index == 0 else f"{prefix}.unit-{index}.c"
        locations = [line for line in unit.splitlines() if line.startswith("#line ")]
        assert locations and all(line.endswith(f'"{expected}"') for line in locations)


def _compile(frontend: str, out: Path, plan: Path, request, *extra: str, units_prefix: str | None = None) -> None:
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
            units_prefix if units_prefix is not None else str(out),
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
            units_prefix if units_prefix is not None else str(out),
            *extra,
            "-o",
            str(out),
            str(PROGRAM),
        ]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
@pytest.mark.parametrize("prefix_tail", ["parts", "..", ".", "", "../parts"])
def test_explicit_unit_paths_stay_stable_when_outputs_already_exist(tmp_path, request, frontend, prefix_tail):
    actual = tmp_path / "storage" / "actual"
    actual.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    prefix = f"{alias}/{prefix_tail}"
    out = tmp_path / "primary.c"
    plan = tmp_path / "plan.json"
    _compile(frontend, out, plan, request, "--debug", units_prefix=prefix)
    baseline = plan.read_bytes()
    payload = json.loads(baseline)
    paths = payload["emitted-units"]
    assert payload["schema"] == 4 and paths
    assert paths == [os.path.realpath(f"{prefix}.unit-{index}.c") for index in range(1, len(paths) + 1)]
    contents = {path: Path(path).read_bytes() for path in paths}
    generated_locations = 0
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if line.startswith("#line ") and line.endswith('.c"'):
                assert os.path.samefile(line.split('"', 1)[1][:-1], path)
                generated_locations += 1
    assert generated_locations > 0
    _compile(frontend, out, plan, request, "--debug", units_prefix=prefix)
    assert plan.read_bytes() == baseline
    assert {path: Path(path).read_bytes() for path in paths} == contents


@pytest.mark.skipif(sys.platform != "linux" or shutil.which("cc") is None, reason="needs a Linux C toolchain")
@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_split_units_link_and_run_like_one(tmp_path, request, frontend):
    out = tmp_path / "program.c"
    plan = tmp_path / "program.json"
    _compile(frontend, out, plan, request)
    units = sorted(tmp_path.glob("program.c.unit-*.c"))
    assert len(units) >= 1, "a 120-line target must split this program"
    plan_text = plan.read_text()
    assert json.loads(plan_text)["emitted-units"] == [
        str(path) for path in sorted(units, key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    ]
    assert json.loads(plan_text)["schema"] == 4
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


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C toolchain")
@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("separate_prefix", [False, True])
def test_cached_split_cli_restores_complete_executable_generation(tmp_path, debug, separate_prefix):
    """A fresh CLI process restores all units/plan and preserves source maps."""
    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Values.btrc"
    dependency.write_text("\n".join(f"int value{index}() {{ return {index}; }}" for index in range(40)))
    source.write_text(
        'import ./Values.btrc;\nint main() { printf("%d\\n", '
        + " + ".join(f"value{index}()" for index in range(40))
        + "); return 0; }\n"
    )
    out = tmp_path / "program.c"
    unit_directory = tmp_path / "units with spaces" if separate_prefix else tmp_path
    unit_directory.mkdir(exist_ok=True)
    prefix = unit_directory / "parts" if separate_prefix else out
    plan = tmp_path / "program.json"
    cache = tmp_path / "cache"
    environment = {**os.environ, "BTRC_CACHE_DIR": str(cache), "BTRC_UNIT_LINES": "120"}
    command = [
        sys.executable,
        "-m",
        "src.compiler.python.main",
        str(source),
        "--no-stdlib",
        "--emit-units",
        str(prefix),
        "--emit-link-plan",
        str(plan),
        "-o",
        str(out),
        *(["--debug"] if debug else []),
    ]

    def compile_program(*extra):
        result = subprocess.run(
            [*command, *extra], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        return result

    assert "(cached)" not in compile_program().stdout
    units = sorted(unit_directory.glob(f"{prefix.name}.unit-*.c"))
    assert units
    baseline = {path: path.read_bytes() for path in [out, *units, plan]}
    for path in baseline:
        path.unlink()
    # Byte-identical input touches and missing output files must still reuse C.
    source.touch()
    assert "(cached)" in compile_program().stdout
    assert {path: path.read_bytes() for path in baseline} == baseline
    if debug:
        assert any(str(source) in path.read_text() for path in [out, *units])
        assert any("#line " in unit.read_text() for unit in units)
        for path in [out, *units]:
            resets = {
                line.split('"', 1)[1][:-1]
                for line in path.read_text().splitlines()
                if line.startswith("#line ") and line.endswith('.c"')
            }
            assert resets <= {str(path)}, (path, resets)
    executable = tmp_path / "program"
    report = NativePlanBuilder().build(
        plan_path=plan, generated_c=out, output=executable, cc="cc", cxx="c++", debug_info=debug
    )
    assert len(report.units) == 1 + len(units)
    executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout == "780\n"
    # A damaged secondary invalidates the whole generation, then recovers.
    generation = next(cache.glob("*.artifacts"))
    (generation / "unit-1.c").unlink()
    assert "(cached)" not in compile_program().stdout
    assert "(cached)" in compile_program().stdout
    assert {path: path.read_bytes() for path in baseline} == baseline
    assert "(cached)" not in compile_program("--no-cache").stdout
    assert "(cached)" not in compile_program("--profile").stdout
    # Source edits must resolve again and change actual executable behavior.
    dependency.write_text(dependency.read_text().replace("return 39;", "return 49;"))
    assert "(cached)" not in compile_program().stdout
    NativePlanBuilder().build(plan_path=plan, generated_c=out, output=executable, cc="cc", cxx="c++")
    executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout == "790\n"


def test_compiled_generation_keys_emission_options_and_reresolves_imports(tmp_path, monkeypatch):
    from dataclasses import replace

    from src.compiler.python import Compiler, CompilerOptions
    from src.compiler.python.artifacts.cache import CompilerCache

    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Value.btrc"
    dependency.write_text("int answer() { return 7; }\n")
    program = "import ./Value.btrc;\nint unused() { return 12; }\nint main() { return answer(); }\n"
    source.write_text(program)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("BTRC_UNIT_LINES", "120")
    compiler = Compiler(cache=CompilerCache())
    ordinary = CompilerOptions(include_stdlib=False, generated_c_path=str(tmp_path / "output.c"))
    debug = replace(ordinary, debug=True)
    split = replace(debug, units_prefix=str(tmp_path / "output.c"))
    variants = [
        ordinary,
        replace(ordinary, dce=False),
        debug,
        replace(debug, generated_c_path=str(tmp_path / "other.c")),
        split,
        replace(split, units_prefix=str(tmp_path / "other.c")),
    ]
    for options in variants:
        first = compiler.compile(program, str(source), options)
        assert first.successful and not first.cache_hit
        warm = compiler.compile(program, str(source), options)
        assert warm.successful and warm.cache_hit
        clean = compiler.compile(program, str(source), replace(options, use_cache=False))
        assert (warm.c_source, warm.c_units, warm.native_plan) == (clean.c_source, clean.c_units, clean.native_plan)
    monkeypatch.setenv("BTRC_UNIT_LINES", "200")
    assert not compiler.compile(program, str(source), split).cache_hit
    assert compiler.compile(program, str(source), split).cache_hit
    dependency.write_text("int answer() { return 8; }\n")
    changed = compiler.compile(program, str(source), ordinary)
    assert changed.successful and not changed.cache_hit
    dependency.unlink()
    missing = compiler.compile(program, str(source), ordinary)
    assert not missing.successful and not missing.cache_hit
