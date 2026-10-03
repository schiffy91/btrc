"""Every ``Lexer(`` in the composing layers reads conditioned text (C4).

c-preprocessor-conditionals.md, "Shared owners": a file's conditioned text is
the only text composition, the LSP, the generators and the corpus audits may
lex. Each construction site below is reviewed: it either reads conditioned
text, or it is an exception with its reason. A new site fails this test until
it is classified here.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCANNED = (
    "src/compiler/python/frontend",
    "src/compiler/python/application",
    "src/devex/lsp",
    "tools/compiler_codegen",
    "src/tests/python/test_corpus_strict_imports.py",
    "src/tests/python/test_hosted_abi_contract.py",
)

CONDITIONED = "reads conditioned text"
SITES = {
    # Conditioned text.
    ("src/compiler/python/frontend/sources.py", "SourceDirectiveScanner._scan"): CONDITIONED,
    ("src/compiler/python/frontend/sources.py", "StdlibRepository._parse_declarations"): CONDITIONED,
    ("src/compiler/python/frontend/sources.py", "StdlibRepository.parsed_symbol_owners"): CONDITIONED,
    ("src/compiler/python/frontend/stage.py", "FrontendStage.parse"): CONDITIONED,
    ("src/compiler/python/application/pipeline.py", "CompilationPipeline.build_stdlib_archive"): CONDITIONED,
    ("src/devex/lsp/workspace/units.py", "FileUnit.parse"): CONDITIONED,
    ("src/devex/lsp/analysis/resolution.py", "LexicalScopeIndex.find_closing_brace_line"): CONDITIONED,
    ("src/devex/lsp/analysis/resolution.py", "LexicalScopeIndex.find_enclosing_class_from_source"): CONDITIONED,
    ("tools/compiler_codegen/builtins.py", "BuiltinStdlibScanner._parse_file"): CONDITIONED,
    ("src/tests/python/test_corpus_strict_imports.py", "CorpusImportAudit.run"): CONDITIONED,
    (
        "src/tests/python/test_hosted_abi_contract.py",
        "test_every_shipped_native_source_prototype_has_an_exact_spec",
    ): CONDITIONED,
    # Exceptions.
    ("src/compiler/python/frontend/sources.py", "ConditionalExpression.lex"): "conditioning's own payload lex",
    ("src/compiler/python/frontend/sources.py", "ConditionalExpression._replacement"): "conditioning's replacement lex",
    ("src/compiler/python/frontend/sources.py", "_ConditionalWalk.run"): "conditioning's own raw lex",
    (
        "src/devex/lsp/features/signature_help.py",
        "SignatureHelpProvider._tokens_for_position",
    ): "text before the cursor",
    (
        "src/devex/lsp/analysis/resolution.py",
        "SemanticResolver._fstring_expression_tokens",
    ): "an f-string interpolation",
    ("tools/compiler_codegen/verification.py", "CompilerBoundaryVerifier.canonical_ast"): "the verifier's raw dump",
    ("src/tests/python/test_hosted_abi_contract.py", "_analyze"): "an inline snippet without directives",
    (
        "src/tests/python/test_hosted_abi_contract.py",
        "test_cfunction_is_public_syntax_for_one_word_noncapturing_callback",
    ): "an inline snippet without directives",
    (
        "src/tests/python/test_hosted_abi_contract.py",
        "test_stdlib_cannot_take_hosted_lifetime_value_through_user_shadow",
    ): "an inline snippet without directives",
    (
        "src/tests/python/test_hosted_abi_contract.py",
        "test_stdlib_source_owner_stamps_nested_declaration_provenance",
    ): "an inline snippet without directives",
}


class LexerSites(ast.NodeVisitor):
    """Collect ``(file, qualified function)`` for every ``Lexer(...)`` call."""

    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.scope: list[str] = []
        self.sites: set[tuple[str, str]] = set()

    def _scoped(self, node) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _scoped
    visit_FunctionDef = _scoped
    visit_AsyncFunctionDef = _scoped

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "Lexer":
            self.sites.add((self.relative, ".".join(self.scope[-2:])))
        self.generic_visit(node)


def lexer_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for root in SCANNED:
        path = REPO / root
        for source in [path] if path.is_file() else sorted(path.rglob("*.py")):
            relative = source.relative_to(REPO).as_posix()
            visitor = LexerSites(relative)
            visitor.visit(ast.parse(source.read_text(encoding="utf-8")))
            sites |= visitor.sites
    return sites


def test_every_lexer_site_is_classified() -> None:
    assert lexer_sites() == set(SITES)
