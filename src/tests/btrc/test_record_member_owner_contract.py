"""Every walk over a struct's or union's members goes through the record-member owner (C2).

C11 anonymous members (``AnonymousMember``) belong to the enclosing record
and unnamed bit-fields are not members, so a walker that iterates
``StructDecl.fields`` directly silently skips or misreads members once those
forms parse (docs/design/c-compatibility.md, "Shared owners"). Each compiler
therefore has one stateless owner -- Python ``TypeSystem.record_*`` and btrc
``SemanticTypeSystem.record*`` class methods -- and this test refuses a raw
member-list read anywhere else.

The btrc scan is exact: only the AST ``Node`` spells ``fields()``,
``fieldsStorage`` and ``fieldsMut()`` (IR records use the ``fields`` vector
field). Each hit is keyed by its file and enclosing method and must be listed
below with its count, so a new raw walk in a listed method fails too. The
Python scan reads every ``.fields`` attribute whose receiver is not a known
non-record (class info, IR, native layouts) and that sits in a function
naming a record (``struct_table``, ``StructDecl``, ``AnonymousMember``,
``FieldDef``) or whose receiver is spelled like one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BTRC = REPO / "src/compiler/btrc"

OWNER = "the record-member owner itself"
GENERIC_WALK = "a kind-independent AST child walk; it reaches anonymous members as ordinary children"
NATIVE_FRONTEND = (
    "the native importer builds and compares imported C records; native records refuse anonymous "
    "members and bit-fields (ref:3191-3192), and the frontend sits below the analyzer"
)

BTRC_ALLOWED = {
    "analyzer/Types.btrc::recordDeclarators": (1, OWNER),
    "analyzer/Types.btrc::recordIsFlat": (1, OWNER),
    "analyzer/Types.btrc::recordMembers": (2, OWNER),
    "analyzer/Types.btrc::recordFields": (1, OWNER),
    "analyzer/Types.btrc::appendRecordFields": (1, OWNER),
    "analyzer/Types.btrc::recordMemberPath": (1, OWNER),
    "analyzer/Types.btrc::recordMember": (1, OWNER),
    "analyzer/Expressions.btrc::collectIdentifiers": (1, GENERIC_WALK),
    "analyzer/Expressions.btrc::visit": (1, GENERIC_WALK),
    "analyzer/Realtime.btrc::collectChildren": (2, GENERIC_WALK),
    "frontend/Visibility.btrc::visit": (2, GENERIC_WALK),
    "ir/lowering/Reachability.btrc::pushChildren": (2, GENERIC_WALK),
    "ir/lowering/Statements.btrc::nodeUsesTrycatch": (2, GENERIC_WALK),
    "syntax/Identity.btrc::children": (2, "AstStructure.children, the structural walk itself"),
    "syntax/Identity.btrc::renderAtDepth": (
        2,
        "the canonical AST renderer prints StructDecl and AnonymousMember fields",
    ),
    "parser/Parser.btrc::parseStructDecl": (1, "the parser builds the member list"),
    "frontend/NativeImports.btrc::record": (2, NATIVE_FRONTEND),
    "frontend/NativeImports.btrc::coalesce": (6, NATIVE_FRONTEND),
    "frontend/NativeImports.btrc::recordInput": (1, NATIVE_FRONTEND),
}

NATIVE_CONTRACT = "a native call-contract record (record_types, result_record), not a StructDecl"
PYTHON_ALLOWED = {
    "src/compiler/python/analyzer/types.py::TypeSystem.record_declarators": (1, OWNER),
    "src/compiler/python/analyzer/types.py::TypeSystem.record_members": (1, OWNER),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._realtime_pod": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._record_input": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._layout_identity": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._coalesce": (6, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._record": (2, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeHeaderCodec.decode": (1, NATIVE_FRONTEND),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer.emit_native_adapter": (1, NATIVE_CONTRACT),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._native_record_output": (2, NATIVE_CONTRACT),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._emit_cxx_method": (4, NATIVE_CONTRACT),
}

_BTRC_RAW = re.compile(r"\bfields\(\)|\bfieldsStorage\b|\bfieldsMut\(\)")
# A method or constructor header at class-body depth.
_BTRC_METHOD = re.compile(r"^\t(?:(?:public|private|class|static)\s+)*[\w<>?, ]+?\b(\w+)\([^;]*\)\s*\{")
_COMMENT = re.compile(r"^\s*(?:/\*|\*|//)")

_PYTHON_ROOTS = ("src/compiler/python", "src/devex/lsp")
# IR modules hold IRStructDef.fields, never the AST record.
_PYTHON_IR_ONLY = ("backend", "verifier.py", "optimizer.py", "nodes.py")
_RECORD_MARKERS = ("struct_table", "StructDecl", "AnonymousMember", "FieldDef")
_RECORD_RECEIVERS = frozenset(
    {"declaration", "decl", "struct", "structure", "struct_decl", "record", "prior", "previous", "d"}
)
_NON_RECORD_RECEIVERS = frozenset(
    {
        "assigned",
        "child",
        "child_layout",
        "cinfo",
        "class_info",
        "cls",
        "contract",
        "dataclasses",
        "fact",
        "holder",
        "info",
        "layout",
        "output",
        "owner",
        "parent",
        "path",
        "pc",
        "projection",
        "selected",
        "self",
        "snapshot",
        "value",
        "variant",
    }
)


def btrc_raw_member_reads() -> dict[str, int]:
    """Raw member-list reads in btrc, keyed by ``file::enclosing method``."""
    found: dict[str, int] = {}
    for path in sorted(BTRC.rglob("*.btrc")):
        relative = path.relative_to(BTRC).as_posix()
        if relative.startswith("generated/"):
            continue
        method = "<top>"
        for line in path.read_text().split("\n"):
            header = _BTRC_METHOD.match(line)
            if header:
                method = header.group(1)
            if _COMMENT.match(line):
                continue
            count = len(_BTRC_RAW.findall(line))
            if count:
                key = f"{relative}::{method}"
                found[key] = found.get(key, 0) + count
    return found


class _PythonRecordReads(ast.NodeVisitor):
    def __init__(self, relative: str, source: str) -> None:
        self.relative = relative
        self.source = source
        self.scopes: list[ast.AST] = []
        self.found: dict[str, int] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = visit_ClassDef
    visit_AsyncFunctionDef = visit_ClassDef

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "fields":
            receiver = node.value
            name = receiver.id if isinstance(receiver, ast.Name) else getattr(receiver, "attr", "")
            function = next(
                (scope for scope in reversed(self.scopes) if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef)),
                None,
            )
            text = ast.get_source_segment(self.source, function) or "" if function is not None else ""
            if name not in _NON_RECORD_RECEIVERS and (
                name in _RECORD_RECEIVERS or any(marker in text for marker in _RECORD_MARKERS)
            ):
                key = f"{self.relative}::" + ".".join(getattr(scope, "name", "") for scope in self.scopes)
                self.found[key] = self.found.get(key, 0) + 1
        self.generic_visit(node)


def python_raw_member_reads() -> dict[str, int]:
    """Raw ``.fields`` reads of AST records in Python, keyed by ``file::qualname``."""
    found: dict[str, int] = {}
    for root in _PYTHON_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if path.name == "generated.py" or "__pycache__" in path.parts:
                continue
            if any(part in _PYTHON_IR_ONLY for part in path.parts):
                continue
            source = path.read_text()
            visitor = _PythonRecordReads(path.relative_to(REPO).as_posix(), source)
            visitor.visit(ast.parse(source))
            found.update(visitor.found)
    return found


def test_btrc_reads_record_members_only_through_the_owner() -> None:
    found = btrc_raw_member_reads()
    allowed = {key: count for key, (count, _reason) in BTRC_ALLOWED.items()}
    unexpected = {key: count for key, count in found.items() if allowed.get(key) != count}
    stale = sorted(key for key in allowed if key not in found)
    assert not unexpected, f"raw StructDecl.fields walks outside SemanticTypeSystem.record*: {unexpected}"
    assert not stale, f"allow-list entries with no raw read left: {stale}"


def test_python_reads_record_members_only_through_the_owner() -> None:
    found = python_raw_member_reads()
    allowed = {key: count for key, (count, _reason) in PYTHON_ALLOWED.items()}
    unexpected = {key: count for key, count in found.items() if allowed.get(key) != count}
    stale = sorted(key for key in allowed if key not in found)
    assert not unexpected, f"raw StructDecl.fields walks outside TypeSystem.record_*: {unexpected}"
    assert not stale, f"allow-list entries with no raw read left: {stale}"


def test_the_scans_see_a_raw_walk() -> None:
    """Both scanners recognize the walk shapes the owners replaced."""
    btrc = "class C {\n\tpublic bool f(Node declaration) {\n\t\twhile (i < declaration.fields().len) {}\n\t}\n}\n"
    method = "<top>"
    hits = []
    for line in btrc.split("\n"):
        header = _BTRC_METHOD.match(line)
        if header:
            method = header.group(1)
        if _BTRC_RAW.search(line):
            hits.append(method)
    assert hits == ["f"]

    python = "def f(self, name):\n    declaration = self.index.struct_table.get(name)\n    return [x.type for x in declaration.fields]\n"
    visitor = _PythonRecordReads("probe.py", python)
    visitor.visit(ast.parse(python))
    assert visitor.found == {"probe.py::f": 1}


def test_python_owner_flattens_anonymous_members_and_skips_unnamed_bit_fields() -> None:
    from src.compiler.python.analyzer.types import TypeSystem
    from src.compiler.python.syntax.ast.generated import AnonymousMember, FieldDef, IntLiteral, StructDecl, TypeExpr

    kind = FieldDef(type=TypeExpr(base="int"), name="kind")
    padding = FieldDef(type=TypeExpr(base="int"), name="", value=IntLiteral(value=0))
    integer = FieldDef(type=TypeExpr(base="int"), name="integer")
    real = FieldDef(type=TypeExpr(base="double"), name="real")
    anonymous = AnonymousMember(is_union=True, fields=[integer, real])
    record = StructDecl(name="Value", fields=[kind, padding, anonymous])

    assert TypeSystem.record_declarators(record) == (kind, padding, anonymous)
    assert TypeSystem.record_members(record) == (kind, anonymous)
    assert TypeSystem.record_fields(record) == (kind, integer, real)
    assert TypeSystem.record_member_path(record, "real") == (anonymous, real)
    assert TypeSystem.record_member(record, "integer") is integer
    assert TypeSystem.record_member(record, "") is None
    assert TypeSystem.record_member(record, "missing") is None
