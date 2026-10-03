"""Exact production inventory and class ownership for the Python compiler.

The self-hosted compiler's tree is pinned by
``src/tests/btrc/test_compiler_structure_contract.py``; this module pins the
Python side the same way, reading the normative tree from
``docs/design/compiler-structure.md`` so the document cannot drift from the
files on disk.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PYTHON_COMPILER = REPO / "src/compiler/python"
EXPECTED_FILE_COUNT = 88
INVENTORY_DOCUMENTS = {
    "docs/design/compiler-structure.md": "The Python compiler contains exactly 88 production `.py` files:",
}
# Thin process and package entry points are the only module-level functions.
MODULE_LEVEL_FUNCTIONS = {
    "__init__.py": {"__getattr__"},
    "main.py": {"main"},
}


def _actual_files() -> set[str]:
    return {
        path.relative_to(REPO).as_posix() for path in PYTHON_COMPILER.rglob("*.py") if "__pycache__" not in path.parts
    }


def _documented_files(document: str, marker: str) -> set[str]:
    text = (REPO / document).read_text(encoding="utf-8")
    start = text.index("```text", text.index(marker)) + len("```text")
    block = text[start : text.index("```", start)]
    files: set[str] = set()
    stack: list[tuple[int, str]] = []
    for line in block.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        name = line.split()[0]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if name.endswith("/"):
            stack.append((indent, name.rstrip("/")))
            continue
        files.add("/".join([*(part for _, part in stack), name]))
    return files


def test_python_compiler_tree_is_the_exact_documented_inventory() -> None:
    actual = _actual_files()

    assert len(actual) == EXPECTED_FILE_COUNT
    for document, marker in INVENTORY_DOCUMENTS.items():
        assert _documented_files(document, marker) == actual, document


def test_production_module_behavior_is_class_owned() -> None:
    loose: list[str] = []
    for relative in sorted(_actual_files()):
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"), filename=relative)
        allowed = MODULE_LEVEL_FUNCTIONS.get(relative.removeprefix("src/compiler/python/"), set())
        loose.extend(
            f"{relative}:{node.lineno}:{node.name}"
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in allowed
        )

    assert loose == []
