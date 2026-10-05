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
Python scan trusts no receiver name: every ``X.fields`` and
``getattr(X, "fields")`` outside the IR modules counts, except
``dataclasses.fields`` and dict-only reads (``.get/.items/.keys/.values``), and
each must be the owner or listed with its reason and count.
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
    "ir/lowering/Declarations.btrc::collectTupleTypesBody": (2, GENERIC_WALK),
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
CLASS_INFO = "a ClassInfo member table (a dict) or class-member list, not a StructDecl"
ACCESS_PATH = "flow analysis AccessPath.fields, the field names along a nullable path"
IR_RECORD = "an IR record (IRStructDef / IRCompoundLiteral / IRTaggedUnionVariant), already lowered"
RICH_ENUM_IR = "IR tagged-union variant fields, already lowered"
PYTHON_ALLOWED = {
    "src/compiler/python/analyzer/declarations.py::DeclarationRegistry._register_class": (1, CLASS_INFO),
    "src/compiler/python/analyzer/declarations.py::InheritanceResolver._merge_parent": (4, CLASS_INFO),
    "src/compiler/python/analyzer/expressions.py::ExpressionAnalyzer._analyze_field_access": (2, CLASS_INFO),
    "src/compiler/python/analyzer/expressions.py::ExpressionAnalyzer._infer_field_access_type": (2, CLASS_INFO),
    "src/compiler/python/analyzer/expressions.py::ExpressionAnalyzer._validate_static_member_access": (1, CLASS_INFO),
    "src/compiler/python/analyzer/flow.py::AccessPath.__eq__": (2, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::AccessPath.__hash__": (1, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::AccessPath.contains": (3, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::ControlFlowAnalyzer._facts_surviving_nodes": (3, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::ControlFlowAnalyzer._facts_surviving_unknown_write": (1, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::ControlFlowAnalyzer.access_path": (1, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::ControlFlowAnalyzer.invalidate_nonnull_target": (2, ACCESS_PATH),
    "src/compiler/python/analyzer/flow.py::ControlFlowAnalyzer.record_nullable_address_escape": (1, ACCESS_PATH),
    "src/compiler/python/analyzer/ownership.py::CallableValueSemantics._is_bound_instance_method": (1, CLASS_INFO),
    "src/compiler/python/analyzer/types.py::TypeSystem.record_declarators": (1, OWNER),
    "src/compiler/python/analyzer/types.py::TypeSystem.record_members": (1, OWNER),
    "src/compiler/python/application/modules.py::SharedDeclarations._provided": (1, RICH_ENUM_IR),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._coalesce": (6, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._cxx_result_record": (
        2,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._layout_identity": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._objective_c_value": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._prepare_cxx_resources": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._prepare_record_fields": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._prepare_string_views": (
        3,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_callback_tables": (
        2,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_callbacks": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_realtime_callbacks": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_record_inputs": (
        2,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_record_outputs": (
        3,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._project_record_snapshots": (
        2,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._reader_arguments": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._realtime_pod": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._record": (3, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._record_contains_resources": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._record_input": (5, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._require_completion_value": (
        2,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._snapshot_path": (1, NATIVE_FRONTEND),
    "src/compiler/python/frontend/native_imports.py::NativeDeclarationImporter._transparent_union_member": (
        1,
        NATIVE_FRONTEND,
    ),
    "src/compiler/python/frontend/native_imports.py::NativeHeaderCodec.decode": (1, NATIVE_FRONTEND),
    "src/compiler/python/ir/lowering/calls.py::CallableProvenance._is_bound_instance_method": (1, CLASS_INFO),
    "src/compiler/python/ir/lowering/exceptions.py::PointerFlow._expression": (1, IR_RECORD),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._emit_cxx_method": (4, NATIVE_CONTRACT),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._emit_one_shot_c_adapter": (1, CLASS_INFO),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._native_record_input": (
        2,
        "a native call-contract record and a ClassInfo member table, not a StructDecl",
    ),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._native_record_output": (2, NATIVE_CONTRACT),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._native_record_snapshot": (1, NATIVE_CONTRACT),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._stored_action_holder": (1, IR_RECORD),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer._stored_delegate_holder": (1, IR_RECORD),
    "src/compiler/python/ir/lowering/functions.py::FunctionLowerer.emit_native_adapter": (1, NATIVE_CONTRACT),
    "src/devex/lsp/features/completion.py::CompletionProvider.class_member_items": (1, CLASS_INFO),
    "src/devex/lsp/features/hover.py::HoverProvider._format_class_info": (1, CLASS_INFO),
    "src/devex/lsp/features/hover.py::HoverProvider._try_member_hover": (2, CLASS_INFO),
    "src/devex/lsp/features/navigation.py::NavigationProvider._classify_symbol": (2, CLASS_INFO),
}

_BTRC_RAW = re.compile(r"\bfields\(\)|\bfieldsStorage\b|\bfieldsMut\(\)")
# A method or constructor header at class-body depth.
_BTRC_METHOD = re.compile(r"^\t(?:(?:public|private|class|static)\s+)*[\w<>?, ]+?\b(\w+)\([^;]*\)\s*\{")
_COMMENT = re.compile(r"^\s*(?:/\*|\*|//)")

_PYTHON_ROOTS = ("src/compiler/python", "src/devex/lsp")
# IR modules hold IRStructDef.fields, never the AST record.
_PYTHON_IR_ONLY = ("backend", "verifier.py", "optimizer.py", "nodes.py")
_DICT_METHODS = frozenset({"get", "items", "keys", "values"})


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


class _PythonRecordReads:
    """Every read of a ``fields`` member list, keyed by ``file::qualname``.

    No receiver name is trusted: any ``X.fields`` or ``getattr(X, "fields")``
    counts, except ``dataclasses.fields`` and the dict-only reads of a
    ClassInfo member table (``X.fields.get/items/keys/values(...)``), which a
    StructDecl's list does not have. A subscript, a slice or an ``in`` test
    works on a list too, so it counts. Everything else must be the owner or
    carry a listed reason.
    """

    def __init__(self, relative: str, source: str) -> None:
        self.relative = relative
        self.found: dict[str, int] = {}
        tree = ast.parse(source)
        self._parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if self._is_member_list_read(node):
                key = f"{relative}::{self._qualname(node)}"
                self.found[key] = self.found.get(key, 0) + 1

    def _is_member_list_read(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "fields":
            if isinstance(node.value, ast.Name) and node.value.id == "dataclasses":
                return False
            return not self._is_dict_read(node)
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "fields"
        )

    def _is_dict_read(self, node: ast.Attribute) -> bool:
        parent = self._parents.get(node)
        return isinstance(parent, ast.Attribute) and parent.value is node and parent.attr in _DICT_METHODS

    def _qualname(self, node: ast.AST) -> str:
        names = []
        while node in self._parents:
            node = self._parents[node]
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names.append(node.name)
        return ".".join(reversed(names))


def python_raw_member_reads() -> dict[str, int]:
    """Raw ``.fields`` reads of AST records in Python, keyed by ``file::qualname``."""
    found: dict[str, int] = {}
    for root in _PYTHON_ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            if path.name == "generated.py" or "__pycache__" in path.parts:
                continue
            if any(part in _PYTHON_IR_ONLY for part in path.parts):
                continue
            found.update(_PythonRecordReads(path.relative_to(REPO).as_posix(), path.read_text()).found)
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

    probes = {
        "struct-table": "def f(self, name):\n    d = self.index.struct_table.get(name)\n    return [x.type for x in d.fields]\n",
        "parent": "def f(self, name):\n    parent = self.index.struct_table.get(name)\n    return [m.type for m in parent.fields]\n",
        "value": "def f(self, name):\n    value = self.struct_table[name]\n    for m in value.fields:\n        g(m)\n",
        "annotated": "def f(self, owner: StructDecl):\n    for m in owner.fields:\n        g(m)\n",
        "any": "def f(owner):\n    return any(m.name == 'x' for m in owner.fields)\n",
        "unmarked": "def f(target):\n    return len(target.fields)\n",
        "getattr": "def f(d):\n    return getattr(d, 'fields')\n",
    }
    for name, python in probes.items():
        assert _PythonRecordReads("probe.py", python).found == {"probe.py::f": 1}, name
    list_shapes = {
        "index": "def f(decl, i):\n    return decl.fields[i].type\n",
        "slice": "def f(decl, last):\n    return decl.fields[last + 1 :]\n",
        "in": "def f(decl, m):\n    return m in decl.fields\n",
        "struct-table-subscript": "def f(self, name):\n    return self.index.struct_table[name].fields[0].type\n",
        "annotated-in": "def f(self, owner: StructDecl, m):\n    return m in owner.fields\n",
        "split-helper": "def f(self, decl, i):\n    return decl.fields[i]\n",
    }
    for name, python in list_shapes.items():
        assert _PythonRecordReads("probe.py", python).found == {"probe.py::f": 1}, name
    dict_reads = "def f(info, k):\n    return (info.fields.get(k), list(info.fields.items()), info.fields.keys())\n"
    assert _PythonRecordReads("probe.py", dict_reads).found == {}


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
