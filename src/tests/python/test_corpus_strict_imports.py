"""Repository-corpus contracts for strict, explicit stdlib dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import src.compiler.python.syntax.ast.generated as ast
from src.compiler.python import Compiler
from src.compiler.python.cli.compiler import CompilerCommand
from src.compiler.python.frontend.imports import ImportVisibilityChecker
from src.compiler.python.frontend.sources import SourceDependencyGraph, SourceDirectiveScanner, StdlibRepository
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

REPO = Path(__file__).resolve().parents[3]
TEST_ROOT = REPO / "src/tests"

# This is language-syntax coverage, not an application dependency shortcut.
# Keep the exception path-specific so no other consumer can acquire std.*.
STDLIB_GLOB_EXCLUSIONS = {
    "src/tests/imports/test_import_std_glob.btrc": "exercises the std.* import form",
}

# These implementation dependencies are reached by executable fixtures. They
# remain in the audit even though they do not live in one of the three primary
# consumer trees.
SUPPORTING_CONSUMERS = frozenset(
    {
        "src/compiler/btrc/tools/ast/dump_main.btrc",
        "src/compiler/btrc/tools/ast/generate_main.btrc",
        "src/compiler/btrc/tools/ast/schema.btrc",
        "src/compiler/btrc/generated/ast/node.btrc",
        "src/compiler/btrc/syntax/grammar.btrc",
        "src/compiler/btrc/frontend/source_io.btrc",
        "src/compiler/btrc/lexer/lexer.btrc",
        "src/compiler/btrc/lexer/stage.btrc",
        "src/compiler/btrc/cli/driver.btrc",
        "src/compiler/btrc/syntax/identity.btrc",
        "src/compiler/btrc/syntax/types.btrc",
        "src/stdlib/daemon.btrc",
        "src/stdlib/graph.btrc",
        "src/stdlib/gui/view.btrc",
    }
)

# The raw per-file audit intentionally does not expand legacy includes. This
# example includes gui/view.btrc, whose Ui shadows the unrelated std.ui Ui.
# The fully resolved strict-import audit covers this source without an error.
RAW_INCLUDE_SHADOWS = frozenset(
    {
        (
            "examples/gui/declarative.btrc",
            "'Ui' is defined in ui.btrc but declarative.btrc does not import it",
        )
    }
)


@dataclass(frozen=True)
class CorpusImportAuditResult:
    source_count: int
    direct_owner_diagnostics: tuple[str, ...]
    duplicate_modules: tuple[str, ...]
    unknown_modules: tuple[str, ...]
    glob_consumers: frozenset[str]


class CorpusImportAudit:
    """Audit source dependencies using the compiler's AST and owner checker."""

    def __init__(self, repository: Path = REPO) -> None:
        self.repository = repository
        self.stdlib = StdlibRepository()
        self.directives = SourceDirectiveScanner()
        self.owner_files = self.stdlib.symbol_files()
        self.all_owner_files = frozenset(owner for owners in self.owner_files.values() for owner in owners)

    def consumer_files(self) -> tuple[Path, ...]:
        shared = (
            path for path in TEST_ROOT.rglob("*.btrc") if path.relative_to(TEST_ROOT).parts[0] not in {"python", "btrc"}
        )
        fixtures = (TEST_ROOT / "btrc/fixtures").rglob("*.btrc")
        examples = (self.repository / "examples").rglob("*.btrc")
        supporting = (self.repository / relative for relative in SUPPORTING_CONSUMERS)
        return tuple(sorted({*shared, *fixtures, *examples, *supporting}))

    def direct_import_graph(
        self,
        path: Path,
        program: ast.Program,
    ) -> tuple[SourceDependencyGraph, list[str], list[str]]:
        graph = SourceDependencyGraph()
        graph.ensure_source(str(path))
        imported_modules = set()
        duplicate_modules = []
        unknown_modules = []
        for declaration in program.declarations:
            if not isinstance(declaration, ast.ImportDecl):
                continue
            if isinstance(declaration.spec, ast.StdGlob):
                for owner in self.all_owner_files:
                    graph.add_import(str(path), owner)
                continue
            if not isinstance(declaration.spec, ast.StdModules):
                continue
            for module in declaration.spec.names:
                if module in imported_modules:
                    duplicate_modules.append(f"{path.relative_to(self.repository)}: std.{module}")
                    continue
                imported_modules.add(module)
                owner = self.stdlib.find_file(f"{module}.btrc")
                if owner is None:
                    unknown_modules.append(f"{path.relative_to(self.repository)}: std.{module}")
                else:
                    graph.add_import(str(path), owner)
        return graph, duplicate_modules, unknown_modules

    def glob_consumers(self) -> frozenset[str]:
        consumers = set()
        for root in (self.repository / "src", self.repository / "examples"):
            for path in root.rglob("*.btrc"):
                if any(
                    directive.kind == "import" and isinstance(directive.payload, ast.StdGlob)
                    for directive in self.directives.scan(path.read_text())
                ):
                    consumers.add(path.relative_to(self.repository).as_posix())
        return frozenset(consumers)

    def run(self) -> CorpusImportAuditResult:
        diagnostics = []
        duplicate_modules = []
        unknown_modules = []
        consumers = self.consumer_files()
        for path in consumers:
            source = path.read_text()
            program = Parser(Lexer(source, str(path)).tokenize()).parse()
            graph, duplicates, missing_modules = self.direct_import_graph(path, program)
            duplicate_modules.extend(duplicates)
            unknown_modules.extend(missing_modules)
            provenance = [str(path)] * (source.count("\n") + 1)
            for message, line, _ in ImportVisibilityChecker(
                program,
                provenance,
                graph,
                external_symbol_files=self.owner_files,
            ).check():
                relative = path.relative_to(self.repository).as_posix()
                if (relative, message) in RAW_INCLUDE_SHADOWS:
                    continue
                diagnostics.append(f"{relative}:{line}: {message}")
        return CorpusImportAuditResult(
            source_count=len(consumers),
            direct_owner_diagnostics=tuple(sorted(set(diagnostics))),
            duplicate_modules=tuple(sorted(set(duplicate_modules))),
            unknown_modules=tuple(sorted(set(unknown_modules))),
            glob_consumers=self.glob_consumers(),
        )


@pytest.fixture(scope="module")
def corpus_import_audit() -> CorpusImportAuditResult:
    return CorpusImportAudit().run()


def test_corpus_declares_every_direct_stdlib_owner(
    corpus_import_audit: CorpusImportAuditResult,
) -> None:
    assert corpus_import_audit.source_count == 1114
    assert corpus_import_audit.duplicate_modules == ()
    assert corpus_import_audit.unknown_modules == ()
    assert corpus_import_audit.direct_owner_diagnostics == ()


def test_only_the_import_syntax_fixture_uses_stdlib_glob(
    corpus_import_audit: CorpusImportAuditResult,
) -> None:
    assert corpus_import_audit.glob_consumers == frozenset(STDLIB_GLOB_EXCLUSIONS)


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
def test_real_corpus_source_parses_in_both_strict_cli_modes(capsys, flags) -> None:
    source = TEST_ROOT / "collections/test_vector_bool.btrc"
    CompilerCommand(Compiler()).run([str(source), "--emit-ast", "--no-cache", *flags])
    assert "Program" in capsys.readouterr().out
