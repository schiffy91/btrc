"""Strict stdlib checking diagnoses callables unused by the application."""

import os
import shutil
import subprocess

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.btrc.selfhost_snippet_harness import REPO
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize(
    "dormant",
    [
        "public int dormant() { return missingValue; }",
        "public missingType dormant() { return null; }",
    ],
    ids=["body", "signature"],
)
def test_strict_stdlib_checks_unused_method(tmp_path, request, frontend, dormant):
    data = tmp_path / "data"
    language = data / "language"
    stdlib = data / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for module in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(module, stdlib / module.name)
    (stdlib / "Probe.btrc").write_text("class Probe { public int answer() { return 42; } " + dormant + " }\n")
    source = "import Library.Probe;\nint main() { Probe p = Probe(); return p.answer(); }\n"
    program = tmp_path / "Main.btrc"
    program.write_text(source)
    if frontend == "python":
        compiler = Compiler(CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(stdlib)))))
        result = compiler.compile(
            source, str(program), CompilerOptions(stdlib_strict=True, use_cache=False, map_stdlib_positions=True)
        )
        assert not result.successful
        assert any("missing" in diagnostic.message for diagnostic in result.diagnostics), result
    else:
        result = subprocess.run(
            [str(request.getfixturevalue("semantic_btrcc")), "--stdlib-strict", "--no-cache", str(program)],
            cwd=REPO,
            env={**os.environ, "BTRC_HOME": str(data)},
            capture_output=True,
            text=True,
            timeout=BTRC_TRANSPILE_TIMEOUT,
        )
        assert result.returncode != 0
        assert "missing" in result.stderr
