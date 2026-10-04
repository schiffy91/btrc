"""Every brace element reaches its record member through the initializer-slot owner (C2).

Anonymous members are one positional slot, unnamed bit-fields take none and
designators choose a member out of order, so pairing ``elements[i]`` with the
record's ``fields[i]`` is wrong once those forms parse (docs/design/
c-compatibility.md, "Shared owners"). Python ``TypeSystem.plan_initializer_slots``
and btrc ``SemanticTypeSystem.planInitializerSlots`` map each element to a
member path; the analyzer owners (``InitializerAnalyzer.plan_aggregate``,
``ExpressionValidator.validateStructInitializer``) record the plan, and every
other site reads it through ``initializer_slots``/``initializerSlots``.

The scan refuses a function or method that reads both an initializer's
elements and a record's member list, outside the owners listed below.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
BTRC = REPO / "src/compiler/btrc"
PYTHON = REPO / "src/compiler/python"
LSP = REPO / "src/devex/lsp"

OWNER = "the initializer-slot owner itself"
PADDING = "zero-fills the members after the plan's last slot; elements are only counted for a tuple"

BTRC_ALLOWED = {
    "analyzer/Types.btrc::planInitializerSlots": OWNER,
    "ir/lowering/Expressions.btrc::staticInitializerPadding": PADDING,
}
PYTHON_ALLOWED = {
    "analyzer/types.py::TypeSystem.plan_initializer_slots": OWNER,
    "ir/lowering/collections.py::CollectionLowerer.plan_static": PADDING,
    "ir/lowering/exceptions.py::PointerFlow._expression": "walks IRInitializerList.elements and IRCompoundLiteral.fields, lowered IR",
}

_BTRC_ELEMENTS = re.compile(r"\belements\(\)|\belementsStorage\b")
_BTRC_MEMBERS = re.compile(r"\brecord(?:Fields|Members|Declarators)\(|\bfields\(\)\.get\(")
_BTRC_METHOD = re.compile(r"^\t(?:(?:public|private|class|static)\s+)*[\w<>?, ]+?\b(\w+)\([^;]*\)\s*\{")
_PYTHON_MEMBERS = re.compile(r"\brecord_(?:fields|members|declarators|named_members)\(|(?<!dataclasses)\.fields\b")
_PYTHON_ELEMENTS = re.compile(r"\.elements\b")
_BTRC_INDEXED_MEMBERS = re.compile(r"\brecord(?:Fields|Members|Declarators)\([^()]*\)\.get\(")
_PYTHON_INDEXED_MEMBERS = re.compile(r"\brecord_(?:fields|members|declarators|named_members)\([^()]*\)\[")


def btrc_pairing_methods(source: str) -> list[str]:
    """Methods that read both brace elements and a record's member list."""
    found = []
    method = None
    body: list[str] = []

    def flush() -> None:
        if method is not None and any(_BTRC_ELEMENTS.search(line) for line in body):
            if any(_BTRC_MEMBERS.search(line) for line in body):
                found.append(method)

    for line in source.split("\n"):
        header = _BTRC_METHOD.match(line)
        if header:
            flush()
            method = header.group(1)
            body = []
        body.append(line)
    flush()
    return found


def python_pairing_functions(source: str) -> list[str]:
    """Functions that read both brace elements and a record's member list."""
    found = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, (*scope, child.name))
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                text = ast.get_source_segment(source, child) or ""
                if _PYTHON_ELEMENTS.search(text) and _PYTHON_MEMBERS.search(text):
                    found.append(".".join((*scope, child.name)))
                visit(child, (*scope, child.name))

    visit(ast.parse(source), ())
    return found


def test_btrc_pairs_elements_with_members_only_in_the_owner() -> None:
    found = set()
    for path in sorted(BTRC.rglob("*.btrc")):
        relative = path.relative_to(BTRC).as_posix()
        if relative.startswith("generated/"):
            continue
        found.update(f"{relative}::{method}" for method in btrc_pairing_methods(path.read_text()))
    assert found - set(BTRC_ALLOWED) == set(), "element/field pairing outside SemanticTypeSystem.initializerSlots"
    assert set(BTRC_ALLOWED) - found == set(), "stale allow-list entries"


def test_python_pairs_elements_with_members_only_in_the_owner() -> None:
    found = set()
    for path in sorted([*PYTHON.rglob("*.py"), *LSP.rglob("*.py")]):
        if path.name == "generated.py" or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PYTHON if path.is_relative_to(PYTHON) else REPO).as_posix()
        if relative.startswith("backend/") or relative in {"ir/nodes.py", "ir/verifier.py", "ir/optimizer.py"}:
            continue
        found.update(f"{relative}::{name}" for name in python_pairing_functions(path.read_text()))
    assert found - set(PYTHON_ALLOWED) == set(), "element/field pairing outside TypeSystem.initializer_slots"
    assert set(PYTHON_ALLOWED) - found == set(), "stale allow-list entries"


def test_no_site_indexes_a_member_list_directly() -> None:
    """A helper that indexes the owner's member list by an element position
    (the old ``shallowElementType`` shape) pairs elements with members too."""
    btrc_hits = [
        f"{path.relative_to(BTRC).as_posix()}:{number}"
        for path in sorted(BTRC.rglob("*.btrc"))
        if not path.relative_to(BTRC).as_posix().startswith("generated/")
        for number, line in enumerate(path.read_text().split("\n"), 1)
        if _BTRC_INDEXED_MEMBERS.search(line)
    ]
    python_hits = [
        f"{path.relative_to(REPO).as_posix()}:{number}"
        for path in sorted([*PYTHON.rglob("*.py"), *LSP.rglob("*.py")])
        if "__pycache__" not in path.parts
        for number, line in enumerate(path.read_text().split("\n"), 1)
        if _PYTHON_INDEXED_MEMBERS.search(line)
    ]
    assert btrc_hits == []
    assert python_hits == []
    assert _BTRC_INDEXED_MEMBERS.search("return SemanticTypeSystem.recordFields(declaration).get(index).type;")
    assert _PYTHON_INDEXED_MEMBERS.search("return TypeSystem.record_fields(declaration)[index].type")


def test_the_scans_see_index_pairing() -> None:
    """Both scanners recognize the pairing loops the owner replaced."""
    btrc = (
        "class C {\n\tprivate Node? f(Node node, Node declaration) {\n"
        "\t\twhile (i < node.elements().len && i < declaration.fields().len) {\n"
        "\t\t\tg(declaration.fields().get(i), node.elements().get(i));\n\t\t}\n\t}\n}\n"
    )
    assert btrc_pairing_methods(btrc) == ["f"]
    python = (
        "def f(declaration, value):\n    return zip((field.type for field in declaration.fields), value.elements)\n"
    )
    assert python_pairing_functions(python) == ["f"]


def test_python_slot_plan_follows_members_and_designators() -> None:
    from src.compiler.python.analyzer.types import TypeSystem
    from src.compiler.python.syntax.ast.generated import (
        AnonymousMember,
        BraceInitializer,
        Designation,
        FieldDef,
        FieldDesignator,
        IntLiteral,
        StructDecl,
        TypeExpr,
    )

    kind = FieldDef(type=TypeExpr(base="int"), name="kind")
    padding = FieldDef(type=TypeExpr(base="int"), name="", value=IntLiteral(value=0))
    integer = FieldDef(type=TypeExpr(base="int"), name="integer")
    anonymous = AnonymousMember(is_union=True, fields=[integer])
    tail = FieldDef(type=TypeExpr(base="long"), name="tail")
    record = StructDecl(name="Value", fields=[kind, padding, anonymous, tail])
    one, two, three = IntLiteral(value=1), IntLiteral(value=2), IntLiteral(value=3)
    tables = SimpleNamespace(struct_table={"Value": record}, typedef_table={})

    positional = TypeSystem.plan_initializer_slots(record, BraceInitializer(elements=[one, two, three]), tables)
    assert [slot.path for slot in positional.slots] == [(kind,), (anonymous,), (tail,)]
    assert [slot.type for slot in positional.slots] == [kind.type, None, tail.type]
    assert (positional.capacity, positional.excess) == (3, 0)

    designated = BraceInitializer(
        elements=[one, two, three],
        entries=[
            Designation(parts=[FieldDesignator(field="integer")]),
            Designation(parts=[]),
            Designation(parts=[FieldDesignator(field="missing")]),
        ],
    )
    plan = TypeSystem.plan_initializer_slots(record, designated, tables)
    assert [slot.path for slot in plan.slots] == [(anonymous, integer), (tail,)]
    assert plan.excess == 1

    union = StructDecl(name="U", fields=[kind, tail], is_union=True)
    first_member = TypeSystem.plan_initializer_slots(union, BraceInitializer(elements=[one, two]), tables)
    assert [slot.path for slot in first_member.slots] == [(kind,)]
    assert (first_member.capacity, first_member.excess) == (1, 1)
