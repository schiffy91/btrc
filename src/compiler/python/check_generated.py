"""Verify every checked-in generated source without modifying the checkout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import gen_hosted_abi_btrc
from .ast import gen_builtins

REPO_ROOT = Path(__file__).resolve().parents[3]
ASDL = REPO_ROOT / "src/language/ast.asdl"
GENERATED_SOURCES = (
    (
        REPO_ROOT / "src/compiler/python/ast/asdl_python.py",
        REPO_ROOT / "src/compiler/python/ast_nodes.py",
        "make ast-generate",
    ),
    (
        REPO_ROOT / "src/compiler/python/ast/gen_btrc_ast.py",
        REPO_ROOT / "src/compiler/btrc/ast/node.btrc",
        "make ast-generate-btrc",
    ),
)


def _render_ast(generator: Path) -> bytes | None:
    result = subprocess.run(
        [sys.executable, str(generator), str(ASDL)],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=120,
    )
    if result.returncode == 0:
        return result.stdout
    sys.stderr.buffer.write(result.stderr)
    print(f"generated-source check failed while running {generator}", file=sys.stderr)
    return None


def _matches(path: Path, expected: bytes, regenerate: str) -> bool:
    try:
        current = path.read_bytes()
    except OSError as error:
        print(f"generated source is missing or unreadable: {path}: {error}", file=sys.stderr)
        return False
    # Git may materialize text files with CRLF on Windows even though the
    # generators use the platform's stdout/text conventions independently.
    # Freshness is a source-content contract, not a checkout-EOL contract.
    if current.replace(b"\r\n", b"\n") == expected.replace(b"\r\n", b"\n"):
        return True
    relative = path.relative_to(REPO_ROOT)
    print(f"generated source is stale: {relative}; regenerate with `{regenerate}`", file=sys.stderr)
    return False


def _check_ast_sources() -> bool:
    valid = True
    for generator, generated, regenerate in GENERATED_SOURCES:
        expected = _render_ast(generator)
        valid = expected is not None and _matches(generated, expected, regenerate) and valid
    return valid


def _check_builtins() -> bool:
    expected = gen_builtins.render_current_builtins().encode()
    generated = REPO_ROOT / "src/devex/lsp/builtins.py"
    return _matches(generated, expected, "make stubs-generate")


def main() -> int:
    valid = _check_ast_sources()
    valid = _check_builtins() and valid
    valid = gen_hosted_abi_btrc.check_generated() == 0 and valid
    if valid:
        print("All generated sources are current.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
