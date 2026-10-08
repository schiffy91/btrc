"""Inherited stdlib interface signatures retain their transitive type dependencies."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.sources import StdlibRepository
from src.compiler.python.frontend.stage import FrontendStage
from src.tests.btrc.selfhost_snippet_harness import REPO, strict_build_and_run
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT

STDLIB = """
interface IResult { int read(); }
class Result implements IResult { public int read() { return 23; } }
interface IParent { IResult make(); }
interface IMiddle extends IParent {}
interface ILeaf extends IMiddle { int tag(); }
class Provider implements ILeaf {
    public IResult make() { return Result(); }
    public int tag() { return 7; }
}
interface Orphan { int unused(); }
"""
SOURCE = """
import Library.InterfaceFamily;
int main() {
    ILeaf provider = Provider();
    return provider.tag() == 7 ? 0 : 1;
}
"""


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_stdlib_interface_parent_signatures_compile_and_run(tmp_path: Path, request, frontend: str) -> None:
    data = tmp_path / "data"
    language = data / "language"
    stdlib = data / "stdlib"
    language.mkdir(parents=True)
    stdlib.mkdir()
    shutil.copy2(REPO / "src/language/grammar.ebnf", language / "grammar.ebnf")
    for source in (REPO / "src/stdlib").glob("*.btrc"):
        shutil.copy2(source, stdlib / source.name)
    (stdlib / "InterfaceFamily.btrc").write_text(STDLIB)
    program = tmp_path / "InterfaceParent.btrc"
    program.write_text(SOURCE)
    generated = tmp_path / f"InterfaceParent.{frontend}.c"
    if frontend == "python":
        compiler = Compiler(CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=str(stdlib)))))
        result = compiler.compile(SOURCE, str(program), CompilerOptions(use_ast_cache=False, map_stdlib_positions=True))
        assert result.successful, (result.failure, result.diagnostics)
        generated.write_text(result.c_source)
    else:
        result = subprocess.run(
            [str(request.getfixturevalue("semantic_btrcc")), "--no-cache", str(program)],
            cwd=REPO,
            env={**os.environ, "BTRC_HOME": str(data)},
            capture_output=True,
            text=True,
            timeout=BTRC_TRANSPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        generated.write_text(result.stdout)

    strict_build_and_run(generated, tmp_path / f"InterfaceParent.{frontend}", optimization="-O2")
