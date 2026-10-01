"""Repository-corpus contracts for strict, explicit stdlib dependencies."""

from __future__ import annotations

import subprocess
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
# Keep the exception path-specific so no other consumer can acquire Library.*.
STDLIB_GLOB_EXCLUSIONS = {
    "src/tests/imports/ImportStdGlob.btrc": "exercises the Library.* import form",
}

# These implementation dependencies are reached by executable fixtures. They
# remain in the audit even though they do not live in one of the three primary
# consumer trees.
SUPPORTING_CONSUMERS = frozenset(
    {
        "src/compiler/btrc/tools/ast/DumpMain.btrc",
        "src/compiler/btrc/tools/ast/GenerateMain.btrc",
        "src/compiler/btrc/tools/ast/Schema.btrc",
        "src/compiler/btrc/generated/ast/Node.btrc",
        "src/compiler/btrc/syntax/Grammar.btrc",
        "src/compiler/btrc/frontend/SourceIo.btrc",
        "src/compiler/btrc/lexer/Lexer.btrc",
        "src/compiler/btrc/lexer/Stage.btrc",
        "src/compiler/btrc/cli/Driver.btrc",
        "src/compiler/btrc/syntax/Identity.btrc",
        "src/compiler/btrc/syntax/Types.btrc",
        "src/stdlib/Daemon/Daemon.btrc",
        "src/stdlib/Graph/Graph.btrc",
    }
)

# Every source outside these trees is a consumer the audit must parse. The
# stdlib holds the owners that imports resolve to, and the bootstrap compiles
# the self-hosted compiler whole; SUPPORTING_CONSUMERS names the files from
# both trees that executable fixtures reach.
OWNER_TREES = {
    "src/stdlib/": "the owners stdlib imports resolve to",
    "src/compiler/btrc/": "compiled whole by the bootstrap",
}


@dataclass(frozen=True)
class CorpusImportAuditResult:
    source_count: int
    expected_source_count: int
    unaudited_sources: tuple[str, ...]
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

    def expected_consumers(self) -> frozenset[str]:
        """Every consumer source, listed by git rather than by the consumer walk.

        Untracked sources count so a test written before ``git add`` is not
        reported; a tracked source deleted from the worktree does not.
        """
        # A container mounts the checkout under another uid; git refuses such a
        # repository unless told the directory is safe.
        listing = subprocess.run(
            ["git", "-c", "safe.directory=*", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.btrc"],
            capture_output=True,
            check=True,
            cwd=self.repository,
            text=True,
        ).stdout.split("\0")
        consumers = (
            path
            for path in listing
            if path and not path.startswith(tuple(OWNER_TREES)) and (self.repository / path).is_file()
        )
        return frozenset({*consumers, *SUPPORTING_CONSUMERS})

    def unaudited_sources(self, consumers: tuple[Path, ...]) -> tuple[str, ...]:
        audited = {path.relative_to(self.repository).as_posix() for path in consumers}
        return tuple(sorted(self.expected_consumers() - audited))

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
            if isinstance(declaration.spec, ast.LibraryGlob):
                for owner in self.all_owner_files:
                    graph.add_import(str(path), owner)
                continue
            if not isinstance(declaration.spec, ast.LibraryModules):
                continue
            for module in declaration.spec.names:
                if module in imported_modules:
                    duplicate_modules.append(f"{path.relative_to(self.repository)}: Library.{module}")
                    continue
                imported_modules.add(module)
                owner = self.stdlib.find_file(module.replace(".", "/") + ".btrc")
                if owner is None:
                    unknown_modules.append(f"{path.relative_to(self.repository)}: Library.{module}")
                else:
                    graph.add_import(str(path), owner)
        return graph, duplicate_modules, unknown_modules

    def glob_consumers(self) -> frozenset[str]:
        consumers = set()
        for root in (self.repository / "src", self.repository / "examples"):
            for path in root.rglob("*.btrc"):
                if any(
                    directive.kind == "import" and isinstance(directive.payload, ast.LibraryGlob)
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
                diagnostics.append(f"{relative}:{line}: {message}")
        return CorpusImportAuditResult(
            source_count=len(consumers),
            expected_source_count=len(self.expected_consumers()),
            unaudited_sources=self.unaudited_sources(consumers),
            direct_owner_diagnostics=tuple(sorted(set(diagnostics))),
            duplicate_modules=tuple(sorted(set(duplicate_modules))),
            unknown_modules=tuple(sorted(set(unknown_modules))),
            glob_consumers=self.glob_consumers(),
        )


@pytest.fixture(scope="module")
def corpus_audit() -> CorpusImportAudit:
    return CorpusImportAudit()


@pytest.fixture(scope="module")
def corpus_import_audit(corpus_audit: CorpusImportAudit) -> CorpusImportAuditResult:
    return corpus_audit.run()


def test_corpus_declares_every_direct_stdlib_owner(
    corpus_import_audit: CorpusImportAuditResult,
) -> None:
    # The count is derived from git, not kept by hand: adding or removing a
    # corpus file needs no edit here, but a consumer walk that narrows as
    # providers move packages fails by naming each source it stopped auditing.
    assert corpus_import_audit.unaudited_sources == ()
    assert corpus_import_audit.source_count == corpus_import_audit.expected_source_count
    assert corpus_import_audit.duplicate_modules == ()
    assert corpus_import_audit.unknown_modules == ()
    assert corpus_import_audit.direct_owner_diagnostics == ()


@pytest.mark.parametrize("tree", ("src/tests/collections", "src/tests/native", "src/tests/btrc/fixtures", "examples"))
def test_coverage_names_a_source_the_consumer_walk_drops(corpus_audit: CorpusImportAudit, tree: str) -> None:
    consumers = corpus_audit.consumer_files()
    dropped = next(path for path in consumers if path.is_relative_to(corpus_audit.repository / tree))
    narrowed = tuple(path for path in consumers if path != dropped)
    assert corpus_audit.unaudited_sources(narrowed) == (dropped.relative_to(corpus_audit.repository).as_posix(),)


def test_only_the_import_syntax_fixture_uses_stdlib_glob(
    corpus_import_audit: CorpusImportAuditResult,
) -> None:
    assert corpus_import_audit.glob_consumers == frozenset(STDLIB_GLOB_EXCLUSIONS)


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
def test_real_corpus_source_parses_in_both_strict_cli_modes(capsys, flags) -> None:
    source = TEST_ROOT / "collections/VectorBool.btrc"
    CompilerCommand(Compiler()).run([str(source), "--emit-ast", "--no-cache", *flags])
    assert "Program" in capsys.readouterr().out
