"""Application builds check reached stdlib bodies; strict builds check every body."""

import os
import shutil
import subprocess
from dataclasses import replace

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.btrc.selfhost_snippet_harness import REPO, strict_build_and_run
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT


@pytest.fixture
def stdlib_project(tmp_path):
    data = tmp_path / "data"
    language = data / "language"
    stdlib = data / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for module in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(module, stdlib / module.name)
    return data


def compile_project(data, request, frontend, source, *, strict=False, library=None):
    if library is not None:
        (data / "stdlib/Probe.btrc").write_text(library)
    program = data.parent / "Main.btrc"
    program.write_text(source)
    if frontend == "python":
        compiler = Compiler(
            CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(data / "stdlib"))))
        )
        result = compiler.compile(
            source, str(program), CompilerOptions(stdlib_strict=strict, use_cache=False, map_stdlib_positions=True)
        )
        return (
            result.successful,
            "\n".join(
                [
                    *(diagnostic.message for diagnostic in result.diagnostics),
                    *([result.failure.message] if result.failure else []),
                ]
            ),
            result.c_source,
        )
    result = subprocess.run(
        [
            str(request.getfixturevalue("semantic_btrcc")),
            *(["--stdlib-strict"] if strict else []),
            "--no-cache",
            str(program),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_HOME": str(data)},
        capture_output=True,
        text=True,
        timeout=BTRC_TRANSPILE_TIMEOUT,
    )
    return result.returncode == 0, result.stderr, result.stdout


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("strict", [False, True], ids=["application", "strict"])
@pytest.mark.parametrize("reached", [False, True], ids=["unused", "reached"])
def test_stdlib_method_body_selection(stdlib_project, request, frontend, strict, reached):
    library = "class Probe { public int answer() { return 42; } public int dormant() { return missingValue; } }"
    member = "dormant" if reached else "answer"
    source = f"import Library.Probe;\nint main() {{ Probe p = Probe(); return p.{member}() == 42 ? 0 : 1; }}\n"
    success, diagnostics, c_source = compile_project(
        stdlib_project, request, frontend, source, strict=strict, library=library
    )
    assert success == (not strict and not reached), diagnostics
    if success:
        generated = stdlib_project.parent / "main.c"
        generated.write_text(c_source)
        strict_build_and_run(generated, stdlib_project.parent / "main", optimization="-O2")
    else:
        assert "missing" in diagnostics


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("strict", [False, True], ids=["application", "strict"])
@pytest.mark.parametrize(
    "dormant",
    [
        "public missingType dormant() { return null; }",
        "public int dormant(int value = missingValue) { return value; }",
    ],
    ids=["signature", "default"],
)
def test_unused_stdlib_contracts_still_validate(stdlib_project, request, frontend, strict, dormant):
    library = "class Probe { public int answer() { return 42; } " + dormant + " }"
    source = "import Library.Probe;\nint main() { Probe p = Probe(); return p.answer(); }\n"
    success, diagnostics, _ = compile_project(stdlib_project, request, frontend, source, strict=strict, library=library)
    assert not success
    assert "missing" in diagnostics


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("strict", [False, True], ids=["application", "strict"])
def test_unused_user_body_still_validates(stdlib_project, request, frontend, strict):
    source = "class User { public int dormant() { return missingValue; } } int main() { return 0; }"
    success, diagnostics, _ = compile_project(stdlib_project, request, frontend, source, strict=strict)
    assert not success
    assert "missing" in diagnostics


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("strict", [False, True], ids=["application", "strict"])
def test_unused_stdlib_function_body_selection(stdlib_project, request, frontend, strict):
    library = "int dormant() { return missingValue; } int answer() { return 42; }"
    source = "import Library.Probe;\nint main() { return answer() == 42 ? 0 : 1; }"
    success, diagnostics, _ = compile_project(stdlib_project, request, frontend, source, strict=strict, library=library)
    assert success == (not strict), diagnostics
    if strict:
        assert "missing" in diagnostics


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_inferred_collection_reaches_its_constructor(stdlib_project, request, frontend):
    vector = stdlib_project / "stdlib/Vector.btrc"
    vector.write_text(
        vector.read_text().replace("public Vector() {", "public Vector() { int broken = missingValue;", 1)
    )
    source = "import Library.Vector;\nint main() { var values = [1, 2]; return values.get(0); }"
    success, diagnostics, _ = compile_project(stdlib_project, request, frontend, source)
    assert not success
    assert "missing" in diagnostics


def test_reference_cache_preserves_strict_and_changed_body_requirements(stdlib_project, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(stdlib_project.parent / "cache"))
    library = stdlib_project / "stdlib/Probe.btrc"
    library.write_text(
        "class Probe { public int answer() { return 42; } public int dormant() { return missingValue; } }"
    )
    compiler = Compiler(
        CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(library.parent)))),
        cache=CompilerCache(),
    )
    program = stdlib_project.parent / "Main.btrc"
    source = "import Library.Probe;\nint main() { Probe p = Probe(); return p.answer(); }"
    program.write_text(source)
    options = CompilerOptions(module_units=True, units_prefix=str(stdlib_project.parent / "program"))
    first = compiler.compile(source, str(program), options)
    assert first.successful, (first.failure, first.diagnostics)
    assert compiler.compile(source, str(program), options).cache_hit
    strict = compiler.compile(source, str(program), replace(options, stdlib_strict=True))
    assert not strict.successful and not strict.cache_hit
    changed = source.replace("p.answer()", "p.dormant()")
    program.write_text(changed)
    result = compiler.compile(changed, str(program), options)
    assert not result.successful and not result.cache_hit
    assert any("missing" in diagnostic.message for diagnostic in result.diagnostics)
