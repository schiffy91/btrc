"""Both corpus consumers build declared native units and libraries."""

import json
import subprocess

import pytest

from src.compiler.python.abi.hosted import TargetRepository
from src.tests import runner, target_runner
from src.tests.native_build import NativeCorpusBuild
from src.tests.process_limits import RUN_TIMEOUT
from tools.native_plan import NativePlanError


@pytest.fixture
def native_program(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    library = "kernel32" if TargetRepository.host().operating_system == "windows" else "m"
    (project / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "corpusNative"\n'
        '[[native.sources]]\npath = "Answer.cpp"\nlanguage = "c++"\nstandard = "c++20"\n'
        'modules = ["Main"]\n[[native.libraries]]\n'
        f'name = "{library}"\nmodules = ["Main"]\n'
    )
    (project / "Answer.cpp").write_text(
        "consteval int configuredAnswer() { return CORPUS_NATIVE_VALUE; }\n"
        'extern "C" int nativeAnswer(void) { return configuredAnswer(); }\n'
    )
    source = project / "Main.btrc"
    source.write_text(
        "#include <stdio.h>\nextern int nativeAnswer();\n"
        'int main() { if (nativeAnswer() != 42) { return 1; } puts("PASS: native corpus"); return 0; }\n'
    )
    (project / "expected").mkdir()
    (project / "expected/Main.stdout").write_text("PASS: native corpus\n")
    return source


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("module_units", [False, True])
def test_unified_corpus_retains_native_plan(frontend, module_units, native_program, tmp_path, request, monkeypatch):
    generation = tmp_path / "generation"
    generation.mkdir()
    flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-DCORPUS_NATIVE_VALUE=42", "-O1"]
    monkeypatch.setattr(runner, "BTRC_CFLAGS", flags)
    source = str(native_program)
    if frontend == "reference":
        artifact, warnings = (
            runner._transpile_python_module_units(source, str(generation))
            if module_units
            else runner._transpile_python_with_warnings(source, native_program.name, generation)
        )
    else:
        compiler = str(request.getfixturevalue("immutable_btrcc"))
        artifact, warnings = (
            runner._transpile_btrc_module_units(compiler, source, str(generation))
            if module_units
            else runner._transpile_btrc_with_warnings(compiler, source, generation)
        )
    assert isinstance(artifact, NativeCorpusBuild) and warnings == []
    runner._compile_run_check(artifact, source, native_program.name)


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_target_corpus_retains_native_plan(frontend, native_program, tmp_path, request, monkeypatch):
    monkeypatch.setattr(target_runner, "CORPUS", native_program.parent)
    row = TargetRepository.host()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    compiler = request.getfixturevalue("immutable_btrcc") if frontend == "selfhost" else None
    flags = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-DCORPUS_NATIVE_VALUE=42", "-O1")
    configuration = target_runner.BuildConfiguration(
        row.label, tmp_path / "work", bundle, compiler, flags, "unused", None
    )
    builder = target_runner.ProgramBuilder(configuration, target_runner.TargetRows.toolchain(row))
    result = builder.build(target_runner.CorpusProgram("Main.btrc"), frontend)
    assert result.status == "built", result.reason
    ran = subprocess.run([str(bundle / result.artifact)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0 and ran.stdout == "PASS: native corpus\n" and not ran.stderr
    report = json.loads((tmp_path / "work" / frontend / f"{result.program_id}.native-build.json").read_text())
    # A C standard requested for generated C must not replace C++20 on the
    # separately compiled native source. Both commands retain caller defines.
    commands = [unit["command"] for unit in report["units"]]
    assert any("-std=c++20" in command and "-std=c11" not in command for command in commands)
    assert all("-DCORPUS_NATIVE_VALUE=42" in command for command in commands)
    assert any(flag in report["link_command"] for flag in ("-lm", "-lkernel32"))


def test_native_builder_rejects_a_flat_flags_string(tmp_path):
    from tools.native_plan import NativePlanBuilder

    with pytest.raises(NativePlanError, match="argument sequences"):
        NativePlanBuilder().build(
            plan_path=tmp_path / "absent.json",
            generated_c=tmp_path / "absent.c",
            output=tmp_path / "unused",
            compile_flags="-O3",
        )
