"""Self-hosted lexer token parity over the whole language corpus.

`make test-selfhost` (tools.compiler_codegen verify-lexer) runs the same
comparison by hand; this module puts it in every gate. Each self-contained
corpus source must lex to the same bytes through the self-hosted lex-only
driver as through the reference compiler's --emit-tokens.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.compiler.python import Compiler, CompilerOptions
from src.compiler.python.application.results import CompilerOutput
from tools.compiler_codegen.verification import CompilerBoundaryVerifier

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "src" / "tests"
LEXER_DRIVER = REPO / "src" / "compiler" / "btrc" / "tools" / "LexMain.btrc"

# The verifier's own selection: a source that imports or includes another
# btrc file is lexed as part of that program, not alone.
SOURCES = sorted(
    path.relative_to(REPO).as_posix()
    for path in CORPUS.rglob("*.btrc")
    if not CompilerBoundaryVerifier._SOURCE_DEPENDENCY.search(path.read_text(encoding="utf-8"))
)


@pytest.fixture(scope="module")
def selfhost_lexer(selfhost_driver) -> Path:
    return selfhost_driver(LEXER_DRIVER)


@pytest.fixture(scope="module")
def reference_compiler() -> Compiler:
    return Compiler()


def test_corpus_selection_is_not_empty() -> None:
    assert len(SOURCES) > 500


@pytest.mark.parametrize("source", SOURCES)
def test_selfhost_lexer_matches_reference_tokens(
    source: str,
    selfhost_lexer: Path,
    reference_compiler: Compiler,
) -> None:
    path = REPO / source
    reference = reference_compiler.compile(
        path.read_text(encoding="utf-8"),
        str(path),
        CompilerOptions(output=CompilerOutput.TOKENS, include_stdlib=False, use_cache=False),
    )
    assert reference.failure is None, reference.failure
    expected = "".join(f"{token}\n" for token in reference.tokens)

    selfhost = subprocess.run(
        [str(selfhost_lexer), str(path)],
        cwd=REPO,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert selfhost.returncode == 0, selfhost.stderr
    assert selfhost.stdout == expected
