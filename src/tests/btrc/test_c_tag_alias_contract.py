"""C tags: native alias rows, record-tag normalization and strict imports (C row 9).

Registration enters `struct S` and `union U` for a tagged native record in
each compiler's typedef alias index (Python `typedef_table`, btrc
`typedefTable`), through one owner per compiler. The keys hold a space, so
they claim no source name, and every canonicalization resolves a tag in one
place. That only stays true while nothing enumerates the index: a consumer
that iterated it would see each record twice, once under a tag. A source
record needs no row: each registry rewrites its written tag to its name,
except for a record named like a generic parameter, which keeps both
spellings as before C row 9. A tag also names its declaration for strict
imports, in both import reference collectors.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.dual_frontend_harness import build_and_run_strict
from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.process_limits import TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
PYTHON_ROOTS = (REPO / "src/compiler/python", REPO / "src/devex")
BTRC_ROOT = REPO / "src/compiler/btrc"

# The index, and the read-only copy CTypeLowerer keeps; a dict() copy is not
# a read of the keys.
PYTHON_INDEX = r"(?:typedef_table|self\._typedefs)"
BTRC_INDEX = r"(?:typedefTable|typedefs)"
PYTHON_ITERATIONS = (
    re.compile(rf"\b{PYTHON_INDEX}\s*\.\s*(?:items|keys|values)\s*\("),
    re.compile(rf"\bfor\b[^\n]*\bin\s+[\w.]*\b{PYTHON_INDEX}\b\s*[:)\]]"),
    re.compile(rf"\b(?:sorted|list|tuple|set|frozenset|iter|len|enumerate)\(\s*[\w.]*\b{PYTHON_INDEX}\s*\)"),
)
BTRC_ITERATIONS = (
    re.compile(rf"\b{BTRC_INDEX}\s*\.\s*(?:keys|values|entries|items)\s*\("),
    re.compile(rf"\bfor\s+\w+(?:\s*,\s*\w+)?\s+in\s+[\w.]*\b{BTRC_INDEX}\s*\{{"),
    re.compile(rf"\b{BTRC_INDEX}\s*\.\s*len\b"),
)


def _python_sources() -> list[Path]:
    return sorted(path for root in PYTHON_ROOTS for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _btrc_sources() -> list[Path]:
    return sorted(BTRC_ROOT.rglob("*.btrc"))


def _hits(paths: list[Path], patterns) -> list[str]:
    hits = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in patterns):
                hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    return hits


def test_no_consumer_iterates_the_typedef_alias_index() -> None:
    # TypeSubstitution.freeze (ir/lowering/generics.py) copies the table into
    # a frozen resolution snapshot; it reads names through it, never lists them.
    assert _hits(_python_sources(), PYTHON_ITERATIONS) == []
    assert _hits(_btrc_sources(), BTRC_ITERATIONS) == []


def test_the_scan_sees_an_iteration() -> None:
    """Each pattern family catches the shapes it names, so an empty scan means something."""

    for line in (
        "for alias, original in self.index.typedef_table.items():",
        "for name in self._typedefs:",
        "names = sorted(self._analyzed.typedef_table)",
    ):
        assert any(pattern.search(line) for pattern in PYTHON_ITERATIONS), line
    for line in (
        "for key in self.analyzed.typedefTable.keys() {",
        "for name in typedefs {",
        "for key, value in self.analyzed.typedefTable {",
        "int count = analyzed.typedefTable.len;",
    ):
        assert any(pattern.search(line) for pattern in BTRC_ITERATIONS), line


def test_one_owner_per_compiler_writes_tag_rows() -> None:
    """Only the registry's tag owner writes a row keyed by a tag spelling."""

    python = (REPO / "src/compiler/python/analyzer/declarations.py").read_text(encoding="utf-8")
    owner = python[python.index("    def _alias_native_tag(") :]
    owner = owner[: owner.index("\n    def ", 1)]
    assert "self.index.typedef_table.setdefault(spelling" in owner
    writers = [
        hit
        for hit in _hits(_python_sources(), (re.compile(r"typedef_table\s*\.\s*setdefault\s*\("),))
        if "analyzer/declarations.py" not in hit
    ]
    assert writers == []
    assert python.count("typedef_table.setdefault(") == 1

    btrc = (BTRC_ROOT / "analyzer/Declarations.btrc").read_text(encoding="utf-8")
    owner = btrc[btrc.index("	private void aliasNativeTag(") :]
    owner = owner[: owner.index("\n	}\n") + 3]
    assert "typedefTable.put(spelling" in owner
    assert btrc.count("typedefTable.put(spelling") == 1


# Strict-import visibility is transitive through a program's own imports, so
# the declaring module is a stdlib one the program does not import.
SPSC = "import Library.SPSC;\n"
JSON = "import Library.JSON;\n"


def _compile_pair(semantic_btrcc: Path, directory: Path, head: str, body: str, owner_import: str):
    """`Leaf.btrc` spells the tag; `Owner.btrc` brings its module into the
    program, so the tag names a declaration the program contains."""
    directory.mkdir()
    (directory / "Owner.btrc").write_text(f"{owner_import}int ownerReady() {{ return 0; }}\n", encoding="utf-8")
    (directory / "Leaf.btrc").write_text(f"{head}int leaf() {{\n\t{body}\n\treturn 0;\n}}\n", encoding="utf-8")
    main = directory / "Main.btrc"
    main.write_text(
        "import ./Leaf.btrc;\nimport ./Owner.btrc;\nint main() { return leaf() + ownerReady(); }\n", encoding="utf-8"
    )
    environment = {**os.environ, "BTRC_CACHE_DIR": str(directory / "cache")}
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(main), "--no-cache", "-o", str(directory / "r.c")],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    selfhost = subprocess.run(
        [str(semantic_btrcc), str(main), "--no-cache"],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    return reference, selfhost


# `enum JSONKind` for a btrc enum is the enum lane's row (x-enum-tag);
# until it lands only the visibility refusal is pinned for it.
@pytest.mark.parametrize(
    ("body", "name", "owner", "head", "accepted"),
    [
        ("struct SPSCQueueStorage* storage = null;", "SPSCQueueStorage", "SPSC.btrc", SPSC, True),
        ("int size = (int)sizeof(struct SPSCQueueStorage);", "SPSCQueueStorage", "SPSC.btrc", SPSC, True),
        ("enum JSONKind* kind = null;", "JSONKind", "JSON.btrc", JSON, False),
    ],
)
def test_a_tag_needs_its_declarations_import(
    semantic_btrcc: Path, tmp_path: Path, body: str, name: str, owner: str, head: str, accepted: bool
) -> None:
    """A tag naming a type the program contains needs that type's import,
    as the bare name does, in the module that spells it."""

    for result in _compile_pair(semantic_btrcc, tmp_path / "unimported", "", body, head):
        assert result.returncode != 0
        assert f"'{name}' is defined in {owner} but Leaf.btrc does not import it" in result.stderr, result.stderr
    if accepted:
        for result in _compile_pair(semantic_btrcc, tmp_path / "imported", head, body, head):
            assert result.returncode == 0, result.stderr


def test_a_tag_never_names_a_function(semantic_btrcc: Path, tmp_path: Path) -> None:
    """C keeps tags in their own namespace: `struct timeval` from a system
    header does not need the module that declares a function `timeval`."""

    (tmp_path / "Defs.btrc").write_text("int timeval(int a) { return a; }\n", encoding="utf-8")
    (tmp_path / "Leaf.btrc").write_text(
        "#include <sys/time.h>\nint leaf() { struct timeval tv; tv.tv_sec = 0; return (int)tv.tv_sec; }\n",
        encoding="utf-8",
    )
    main = tmp_path / "Main.btrc"
    main.write_text("import ./Defs.btrc;\nimport ./Leaf.btrc;\nint main() { return leaf() + timeval(0); }\n")
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")}
    for command in (
        [sys.executable, "-m", "src.compiler.python.main", str(main), "--no-cache", "-o", str(tmp_path / "r.c")],
        [str(semantic_btrcc), str(main), "--no-cache"],
    ):
        result = subprocess.run(
            command, cwd=REPO, env=environment, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT
        )
        assert result.returncode == 0, result.stderr


LIST = "import Library.List;\n"
RESULT = "import Library.Result;\n"
LIST_NODE = "struct ListNode { int value; struct ListNode* next; };"
RESULT_ENUM = "enum Result { RESULT_OK = 7, RESULT_FAIL = 8 };"
NODE_CLASS = "class Node<T> { public T value; public Node(T value) { self.value = value; } }\n"
LIST_USE = "List<int> numbers = new List<int>(); numbers.push(1); "


@pytest.mark.parametrize(
    ("head", "header", "declarations", "body"),
    [
        ("", "struct Timer { long ticks; };", "", "struct Timer timer; timer.ticks = 3; return (int)timer.ticks - 3;"),
        ("", LIST_NODE, "", "struct ListNode node; node.value = 2; node.next = NULL; return node.value - 2;"),
        ("", RESULT_ENUM, "", "enum Result result = RESULT_OK; return (int)result - 7;"),
        ("", "union Path { int i; float f; };", "", "union Path path; path.i = 5; return path.i - 5;"),
        (LIST, LIST_NODE, "", LIST_USE + "struct ListNode tail = {3, null}; return tail.value + numbers.len - 4;"),
        (RESULT, RESULT_ENUM, "", "enum Result result = RESULT_OK; return (int)result - 7;"),
        (
            "",
            "struct Node { int weight; };",
            NODE_CLASS,
            "struct Node n = {4}; Node<int> k = new Node<int>(2); return n.weight + k.value - 6;",
        ),
    ],
    ids=[
        "struct-Timer",
        "struct-ListNode",
        "enum-Result",
        "union-Path",
        "struct-ListNode-beside-List",
        "enum-Result-beside-Result",
        "struct-Node-beside-user-Node",
    ],
)
def test_a_headers_own_tag_needs_no_stdlib_import(
    semantic_btrcc: Path, tmp_path: Path, head: str, header: str, declarations: str, body: str
) -> None:
    """A C header's own `struct Timer` is not the stdlib's Timer: a tag
    resolves only among types the program declares, never through the stdlib
    symbol index for a module the program does not contain. A generic class
    (`List`'s `ListNode<T>`, `Result<T, E>`, a user `Node<T>`) owns no C tag,
    so a header's tag of that name stays the header's."""

    (tmp_path / "linked.h").write_text(f"#ifndef LINKED_H\n#define LINKED_H\n{header}\n#endif\n", encoding="utf-8")
    main = tmp_path / "Main.btrc"
    main.write_text(f'{head}#include "linked.h"\n{declarations}int main() {{ {body} }}\n', encoding="utf-8")
    _run_strict_pair(semantic_btrcc, tmp_path, main)


def test_a_leaf_spells_a_header_tag_beside_an_imported_generic(semantic_btrcc: Path, tmp_path: Path) -> None:
    """The module that spells a header's `struct ListNode` needs no
    `import Library.List;` because the program imports List elsewhere."""

    (tmp_path / "linked.h").write_text(f"#ifndef LINKED_H\n#define LINKED_H\n{LIST_NODE}\n#endif\n", encoding="utf-8")
    (tmp_path / "Leaf.btrc").write_text(
        '#include "linked.h"\nint leafValue() { struct ListNode node = {6, null}; return node.value; }\n',
        encoding="utf-8",
    )
    main = tmp_path / "Main.btrc"
    main.write_text(f"{LIST}import ./Leaf.btrc;\nint main() {{ {LIST_USE}return leafValue() + numbers.len - 7; }}\n")
    _run_strict_pair(semantic_btrcc, tmp_path, main)


def _run_strict_pair(semantic_btrcc: Path, tmp_path: Path, main: Path) -> None:
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")}
    reference_c, selfhost_c = tmp_path / "reference.c", tmp_path / "selfhost.c"
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(main), "--no-cache", "-o", str(reference_c)],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert reference.returncode == 0, reference.stderr
    selfhost = subprocess.run(
        [str(semantic_btrcc), str(main), "--no-cache"],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_c.write_text(selfhost.stdout, encoding="utf-8")
    for generated in (reference_c, selfhost_c):
        for compiler in HOST_C_COMPILERS:
            build_and_run_strict(generated, tmp_path / f"{generated.stem}-{Path(compiler).name}", compiler)
