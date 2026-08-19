"""Scaling contracts for the self-hosted lexer cursor."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def selfhost_lexer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-lexer-scaling")
    generated = output / "lexer.c"
    binary = output / "lexer"
    transpile = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            "src/compiler/btrc/tools/lex_main.btrc",
            "--no-cache",
            "-o",
            str(generated),
        ],
        env={**os.environ, "BTRC_CACHE_DIR": str(output / "cache")},
        timeout=300,
    )
    assert transpile.returncode == 0, transpile.stderr[:3000]
    compiled = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-O2",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr[:3000]
    return binary


def _lex_time(binary: Path, source: Path) -> float:
    started = time.perf_counter()
    result = _run([str(binary), str(source)], timeout=5)
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return elapsed


def test_operator_scan_scales_linearly(
    selfhost_lexer: Path,
    tmp_path: Path,
) -> None:
    """Doubling operator-heavy input must not rescan the source per token."""
    small = tmp_path / "small.btrc"
    large = tmp_path / "large.btrc"
    small.write_text(";" * 100_000)
    large.write_text(";" * 200_000)

    _lex_time(selfhost_lexer, small)  # Warm process-backed filesystem caches.
    small_time = min(_lex_time(selfhost_lexer, small) for _ in range(2))
    large_time = min(_lex_time(selfhost_lexer, large) for _ in range(2))

    assert large_time < 3.0
    assert large_time <= small_time * 3.0 + 0.1


def test_lexer_cursor_does_not_rescan_source_text() -> None:
    source = (REPO / "src/compiler/btrc/lexer/lexer.btrc").read_text()
    assert "self.sourceLen = source.length();" in source
    assert "self.source.length()" not in source
    assert "self.source.substring(self.pos, oplen)" not in source
