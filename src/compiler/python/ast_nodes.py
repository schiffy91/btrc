"""AST node definitions for the btrc language.

Auto-generated from src/language/ast/ast.asdl by src/language/ast/asdl_python.py.
DO NOT EDIT BY HAND.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Optional, Union


@dataclass(kw_only=True)
class Program:
    declarations: list[decl] = _dc_field(default_factory=list)


@dataclass(kw_only=True)
class PreprocessorDirective:
    text: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class ImportDecl:
    spec: import_spec
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class ClassDecl:
    name: str = ""
    generic_params: list[str] = _dc_field(default_factory=list)
    members: list[class_member] = _dc_field(default_factory=list)
    parent: Optional[str] = None
    interfaces: list[str] = _dc_field(default_factory=list)
    is_abstract: bool = False
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class InterfaceDecl:
    name: str = ""
    methods: list[MethodSig] = _dc_field(default_factory=list)
    parent: Optional[str] = None
    generic_params: list[str] = _dc_field(default_factory=list)
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class FunctionDecl:
    return_type: TypeExpr
    name: str = ""
    params: list[Param] = _dc_field(default_factory=list)
    body: Optional[Block] = None
    is_gpu: bool = False
    keep_return: bool = False
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class StructDecl:
    name: str = ""
    fields: list[FieldDef] = _dc_field(default_factory=list)
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class EnumDecl:
    name: str = ""
    values: list[EnumValue] = _dc_field(default_factory=list)
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class RichEnumDecl:
    name: str = ""
    variants: list[RichEnumVariant] = _dc_field(default_factory=list)
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class TypedefDecl:
    original: TypeExpr
    alias: str = ""
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)
    source_file: Optional[str] = _dc_field(default=None, compare=False)


@dataclass(kw_only=True)
class StdGlob:
    recursive: bool = False


@dataclass(kw_only=True)
class StdModules:
    names: list[str] = _dc_field(default_factory=list)


@dataclass(kw_only=True)
class PackagePath:
    segments: list[str] = _dc_field(default_factory=list)


@dataclass(kw_only=True)
class RelativePath:
    path: str = ""


@dataclass(kw_only=True)
class QuotedPath:
    path: str = ""


@dataclass(kw_only=True)
class TypeExpr:
    base: str = ""
    generic_args: list[TypeExpr] = _dc_field(default_factory=list)
    pointer_depth: int = 0
    is_array: bool = False
    array_size: Optional[expr] = None
    is_const: bool = False
    is_nullable: bool = False
    is_static: bool = False
    is_extern: bool = False
    is_volatile: bool = False
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class Param:
    type: TypeExpr
    name: str = ""
    default: Optional[expr] = None
    keep: bool = False
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class FieldDecl:
    access: str = ""
    type: TypeExpr
    name: str = ""
    initializer: Optional[expr] = None
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class MethodDecl:
    access: str = ""
    return_type: TypeExpr
    name: str = ""
    generic_params: list[str] = _dc_field(default_factory=list)
    params: list[Param] = _dc_field(default_factory=list)
    body: Optional[Block] = None
    is_gpu: bool = False
    is_abstract: bool = False
    keep_return: bool = False
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class PropertyDecl:
    access: str = ""
    type: TypeExpr
    name: str = ""
    has_getter: bool = False
    has_setter: bool = False
    getter_body: Optional[Block] = None
    setter_body: Optional[Block] = None
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class MethodSig:
    return_type: TypeExpr
    name: str = ""
    params: list[Param] = _dc_field(default_factory=list)
    keep_return: bool = False
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class EnumValue:
    name: str = ""
    value: Optional[expr] = None
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class RichEnumVariant:
    name: str = ""
    params: list[Param] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class FieldDef:
    type: TypeExpr
    name: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class Block:
    statements: list[stmt] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class VarDeclStmt:
    type: Optional[TypeExpr] = None
    name: str = ""
    initializer: Optional[expr] = None
    name_line: int = _dc_field(default=0, compare=False)
    name_col: int = _dc_field(default=0, compare=False)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ReturnStmt:
    value: Optional[expr] = None
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class IfStmt:
    condition: expr
    then_block: Block
    else_block: Optional[if_else] = None
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class WhileStmt:
    condition: expr
    body: Block
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class DoWhileStmt:
    body: Block
    condition: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ForInStmt:
    var_name: str = ""
    var_name2: Optional[str] = None
    iterable: expr
    body: Block
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class CForStmt:
    init: Optional[for_init] = None
    condition: Optional[expr] = None
    update: Optional[expr] = None
    body: Block
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ParallelForStmt:
    var_name: str = ""
    iterable: expr
    body: Block
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SwitchStmt:
    value: expr
    cases: list[CaseClause] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class BreakStmt:
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ContinueStmt:
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ExprStmt:
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class DeleteStmt:
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class TryCatchStmt:
    try_block: Block
    catch_var: str = ""
    catch_type: Optional[TypeExpr] = None
    catch_block: Optional[Block] = None
    finally_block: Optional[Block] = None
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ThrowStmt:
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class KeepStmt:
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ReleaseStmt:
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ElseBlock:
    body: Block


@dataclass(kw_only=True)
class ElseIf:
    if_stmt: stmt


@dataclass(kw_only=True)
class ForInitVar:
    var_decl: stmt


@dataclass(kw_only=True)
class ForInitExpr:
    expression: expr


@dataclass(kw_only=True)
class CaseClause:
    value: Optional[expr] = None
    body: list[stmt] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class IntLiteral:
    value: int = 0
    raw: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class FloatLiteral:
    value: float = 0.0
    raw: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class StringLiteral:
    value: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class CharLiteral:
    value: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class BoolLiteral:
    value: bool = False
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class NullLiteral:
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class Identifier:
    name: str = ""
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SelfExpr:
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SuperExpr:
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class BinaryExpr:
    left: expr
    op: str = ""
    right: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class UnaryExpr:
    op: str = ""
    operand: expr
    prefix: bool = False
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class CallExpr:
    callee: expr
    args: list[expr] = _dc_field(default_factory=list)
    arg_names: list[str] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class IndexExpr:
    obj: expr
    index: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class FieldAccessExpr:
    obj: expr
    field: str = ""
    arrow: bool = False
    optional: bool = False
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class CastExpr:
    target_type: TypeExpr
    expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SizeofExpr:
    operand: sizeof_operand
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class TernaryExpr:
    condition: expr
    true_expr: expr
    false_expr: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class AssignExpr:
    target: expr
    op: str = ""
    value: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class ListLiteral:
    elements: list[expr] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class MapLiteral:
    entries: list[MapEntry] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class BraceInitializer:
    elements: list[expr] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class FStringLiteral:
    parts: list[fstring_part] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class NewExpr:
    type: TypeExpr
    args: list[expr] = _dc_field(default_factory=list)
    arg_names: list[str] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class TupleLiteral:
    elements: list[expr] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class LambdaExpr:
    return_type: Optional[TypeExpr] = None
    params: list[Param] = _dc_field(default_factory=list)
    body: lambda_body
    captures: list[Capture] = _dc_field(default_factory=list)
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SpawnExpr:
    fn: expr
    line: int = _dc_field(default=0, compare=False)
    col: int = _dc_field(default=0, compare=False)


@dataclass(kw_only=True)
class SizeofType:
    type: TypeExpr


@dataclass(kw_only=True)
class SizeofExprOp:
    expr: expr


@dataclass(kw_only=True)
class MapEntry:
    key: expr
    value: expr


@dataclass(kw_only=True)
class FStringText:
    text: str = ""


@dataclass(kw_only=True)
class FStringExpr:
    expression: expr


@dataclass(kw_only=True)
class LambdaBlock:
    body: Block


@dataclass(kw_only=True)
class LambdaExprBody:
    expression: expr


@dataclass(kw_only=True)
class Capture:
    name: str = ""
    type: TypeExpr


# --- Union type aliases for sum types ---

decl = Union[PreprocessorDirective, ImportDecl, ClassDecl, InterfaceDecl, FunctionDecl, StructDecl, EnumDecl, RichEnumDecl, TypedefDecl]
import_spec = Union[StdGlob, StdModules, PackagePath, RelativePath, QuotedPath]
class_member = Union[FieldDecl, MethodDecl, PropertyDecl]
stmt = Union[VarDeclStmt, ReturnStmt, IfStmt, WhileStmt, DoWhileStmt, ForInStmt, CForStmt, ParallelForStmt, SwitchStmt, BreakStmt, ContinueStmt, ExprStmt, DeleteStmt, TryCatchStmt, ThrowStmt, KeepStmt, ReleaseStmt]
if_else = Union[ElseBlock, ElseIf]
for_init = Union[ForInitVar, ForInitExpr]
expr = Union[IntLiteral, FloatLiteral, StringLiteral, CharLiteral, BoolLiteral, NullLiteral, Identifier, SelfExpr, SuperExpr, BinaryExpr, UnaryExpr, CallExpr, IndexExpr, FieldAccessExpr, CastExpr, SizeofExpr, TernaryExpr, AssignExpr, ListLiteral, MapLiteral, BraceInitializer, FStringLiteral, NewExpr, TupleLiteral, LambdaExpr, SpawnExpr]
sizeof_operand = Union[SizeofType, SizeofExprOp]
fstring_part = Union[FStringText, FStringExpr]
lambda_body = Union[LambdaBlock, LambdaExprBody]


# --- Product type aliases ---
# These alias lowercase ASDL names to the PascalCase class names

program = Program
type_expr = TypeExpr
param = Param
method_sig = MethodSig
enum_value = EnumValue
rich_enum_variant = RichEnumVariant
field_def = FieldDef
block = Block
case_clause = CaseClause
map_entry = MapEntry
capture = Capture

