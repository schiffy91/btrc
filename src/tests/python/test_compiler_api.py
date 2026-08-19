"""Application-object and public stage API contracts."""

from __future__ import annotations

import ast as python_ast
import importlib.util
from pathlib import Path

from src.compiler.python import Compiler, CompilerOptions, CompilerResult
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOutput

SOURCE = "int main() { return 0; }\n"
REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_COMPILER = REPO_ROOT / "src/compiler/python"


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    module_name = _module_name(path)
    package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    targets: set[str] = set()
    tree = python_ast.parse(path.read_text(), filename=str(path))
    for node in python_ast.walk(tree):
        if isinstance(node, python_ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, python_ast.ImportFrom):
            if node.level:
                target = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            else:
                target = node.module or ""
            targets.add(target)
    return targets


def _compiler_import_graph() -> dict[str, set[str]]:
    paths = [path for path in PYTHON_COMPILER.rglob("*.py") if "__pycache__" not in path.parts]
    modules = {_module_name(path): path for path in paths}
    names = set(modules)
    graph = {}
    for name, path in modules.items():
        targets = set()
        for imported in _imports(path):
            candidate = imported
            while candidate and candidate not in names:
                candidate = candidate.rpartition(".")[0]
            if candidate:
                targets.add(candidate)
        graph[name] = targets
    return graph


def _cyclic_components(graph: dict[str, set[str]]) -> list[set[str]]:
    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    cycles: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in active:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] != indexes[node]:
            return
        component = set()
        while stack:
            member = stack.pop()
            active.remove(member)
            component.add(member)
            if member == node:
                break
        if len(component) > 1 or node in graph[node]:
            cycles.append(component)

    for node in graph:
        if node not in indexes:
            visit(node)
    return cycles


def test_pipeline_owns_the_explicit_stage_five_preparation_cascade() -> None:
    tree = python_ast.parse(
        (PYTHON_COMPILER / "application/pipeline.py").read_text(),
        filename="application/pipeline.py",
    )
    pipeline = next(
        node for node in tree.body if isinstance(node, python_ast.ClassDef) and node.name == "CompilationPipeline"
    )
    methods = {
        node.name: node
        for node in pipeline.body
        if isinstance(node, python_ast.FunctionDef)
    }

    optimize_calls = [python_ast.unparse(node.func) for node in python_ast.walk(methods["optimize"]) if isinstance(node, python_ast.Call)]
    prepare_calls = [
        python_ast.unparse(statement.value.func)
        for statement in methods["_finalize_optimized_ir"].body
        if isinstance(statement, python_ast.Expr) and isinstance(statement.value, python_ast.Call)
    ]
    emit_calls = [python_ast.unparse(node.func) for node in python_ast.walk(methods["emit"]) if isinstance(node, python_ast.Call)]

    assert "IRVerifier(module).validate_schema" in optimize_calls
    assert "IROptimizer" in optimize_calls
    assert "self._finalize_optimized_ir" in optimize_calls
    assert prepare_calls == [
        "IROptimizer.materialize_runtime_dependencies",
        "IROptimizer.refresh_type_declarations",
        "IRVerifier(module).validate",
    ]
    assert not any(call.startswith("IROptimizer") for call in emit_calls)


class MemoryCache:
    def __init__(self) -> None:
        self.value = None
        self.loads = 0
        self.stores = 0

    def load_text(self, source, input_path, *, source_identity=""):
        self.loads += 1
        return self.value

    def store_text(self, source, c_source, input_path=None, *, source_identity=""):
        self.stores += 1
        self.value = c_source


def test_public_compiler_defaults_to_strict_imports_and_emits_c(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)

    result = Compiler().compile(
        SOURCE,
        str(source_path),
        CompilerOptions(include_stdlib=False, use_cache=False),
    )

    assert isinstance(result, CompilerResult)
    assert result.options.strict_imports
    assert result.successful
    assert result.program is not None
    assert result.analyzed is not None
    assert result.ir_module is not None
    assert result.c_source is not None
    assert "int main(void)" in result.c_source


def test_pipeline_exposes_each_terminal_representation(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)
    compiler = Compiler(CompilationPipeline())

    tokens = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.TOKENS,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    ast = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.AST,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    ir = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.IR,
            include_stdlib=False,
            use_cache=False,
        ),
    )
    optimized = compiler.compile(
        SOURCE,
        str(source_path),
        CompilerOptions(
            output=CompilerOutput.OPTIMIZED_IR,
            include_stdlib=False,
            use_cache=False,
        ),
    )

    assert tokens.tokens and tokens.program is None
    assert ast.program is not None and ast.analyzed is None
    assert ir.ir_module is not None and ir.c_source is None
    assert optimized.ir_module is not None and optimized.c_source is None


def test_compiler_uses_injected_cache_without_reentering_pipeline(tmp_path):
    source_path = tmp_path / "main.btrc"
    source_path.write_text(SOURCE)
    cache = MemoryCache()
    compiler = Compiler(cache=cache)
    options = CompilerOptions(include_stdlib=False)

    first = compiler.compile(SOURCE, str(source_path), options)
    second = compiler.compile(SOURCE, str(source_path), options)

    assert first.successful and not first.cache_hit
    assert second.successful and second.cache_hit
    assert second.program is None
    assert second.c_source == first.c_source
    assert cache.loads == 2
    assert cache.stores == 1


def test_analyzer_failure_stops_before_ir_lowering(tmp_path):
    source = 'int main() { int value = "wrong"; return value; }\n'
    source_path = tmp_path / "bad.btrc"
    source_path.write_text(source)

    result = Compiler().compile(
        source,
        str(source_path),
        CompilerOptions(include_stdlib=False, use_cache=False),
    )

    assert not result.successful
    assert result.analyzed is not None and result.analyzed.errors
    assert result.ir_module is None
    assert result.c_source is None


def test_application_dependency_boundaries_are_explicit_and_acyclic():
    for path in (PYTHON_COMPILER / "application").glob("*.py"):
        assert not any(
            target.startswith("src.compiler.python.artifacts")
            for target in _imports(path)
        ), path

    frontend_forbidden = ("src.compiler.python.application", "src.compiler.python.artifacts")
    for path in (PYTHON_COMPILER / "frontend").glob("*.py"):
        assert not any(target.startswith(frontend_forbidden) for target in _imports(path)), path

    for path in (PYTHON_COMPILER / "cli").glob("*.py"):
        compiler_imports = {
            target for target in _imports(path) if target.startswith("src.compiler.python.")
        }
        assert all(target.startswith("src.compiler.python.application") for target in compiler_imports), path

    artifact_forbidden = tuple(
        f"src.compiler.python.{package}"
        for package in ("analyzer", "application", "backend", "frontend", "ir", "lexer", "parser", "runtime")
    )
    for path in (PYTHON_COMPILER / "artifacts").glob("*.py"):
        assert not any(target.startswith(artifact_forbidden) for target in _imports(path)), path

    stage_tree = python_ast.parse((PYTHON_COMPILER / "frontend/stage.py").read_text())
    result_tree = python_ast.parse((PYTHON_COMPILER / "application/results.py").read_text())
    artifact_tree = python_ast.parse((PYTHON_COMPILER / "artifacts/stdlib.py").read_text())
    pipeline_tree = python_ast.parse((PYTHON_COMPILER / "application/pipeline.py").read_text())
    publication_tree = python_ast.parse((PYTHON_COMPILER / "artifacts/publication.py").read_text())
    archive_tree = python_ast.parse((PYTHON_COMPILER / "artifacts/archive.py").read_text())
    command_tree = python_ast.parse((PYTHON_COMPILER / "cli/compiler.py").read_text())
    main_imports = _imports(PYTHON_COMPILER / "main.py")
    assert "FrontendParseResult" in {
        node.name for node in stage_tree.body if isinstance(node, python_ast.ClassDef)
    }
    assert "FrontendParseResult" not in {
        node.name for node in result_tree.body if isinstance(node, python_ast.ClassDef)
    }
    assert "StdlibArtifactRepository" in {
        node.name for node in artifact_tree.body if isinstance(node, python_ast.ClassDef)
    }
    assert "StdlibArchiveAdapter" in {
        node.name for node in pipeline_tree.body if isinstance(node, python_ast.ClassDef)
    }
    for tree, owner_name in (
        (stage_tree, "FrontendStage"),
        (pipeline_tree, "CompilationPipeline"),
    ):
        owner = next(
            node for node in tree.body if isinstance(node, python_ast.ClassDef) and node.name == owner_name
        )
        initializer = next(
            node for node in owner.body if isinstance(node, python_ast.FunctionDef) and node.name == "__init__"
        )
        assert not any(argument.arg.endswith("_factory") for argument in initializer.args.args)
        assert not any(argument.arg.endswith("_factory") for argument in initializer.args.kwonlyargs)
    publisher = next(
        node for node in publication_tree.body if isinstance(node, python_ast.ClassDef) and node.name == "ArtifactPublisher"
    )
    publish = next(
        node for node in publisher.body if isinstance(node, python_ast.FunctionDef) and node.name == "publish"
    )
    assert [argument.arg for argument in publish.args.args] == ["self", "name", "artifacts"]
    assert [argument.arg for argument in publish.args.kwonlyargs] == ["policy"]
    assert "StagedPublicationPolicy" in {
        node.name for node in publication_tree.body if isinstance(node, python_ast.ClassDef)
    }
    target_catalog = next(
        node for node in archive_tree.body if isinstance(node, python_ast.ClassDef) and node.name == "TargetCatalog"
    )
    target_init = next(
        node for node in target_catalog.body if isinstance(node, python_ast.FunctionDef) and node.name == "__init__"
    )
    assert {argument.arg for argument in target_init.args.args} == {"self", "targets", "host_targets"}
    command = next(
        node for node in command_tree.body if isinstance(node, python_ast.ClassDef) and node.name == "CompilerCommand"
    )
    command_init = next(
        node for node in command.body if isinstance(node, python_ast.FunctionDef) and node.name == "__init__"
    )
    assert [argument.arg for argument in command_init.args.args] == ["self", "compiler"]
    assert command_init.args.defaults == []
    assert {
        "src.compiler.python.artifacts.cache",
        "src.compiler.python.artifacts.selfhost",
        "src.compiler.python.artifacts.stdlib",
    } <= main_imports
    assert _cyclic_components(_compiler_import_graph()) == []
