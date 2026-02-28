"""AST node definitions for the btrc language.

Auto-generated from spec/ast/ast.asdl by spec/ast/asdl_python.py.
DO NOT EDIT BY HAND.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union



@dataclass
class Program:
    declarations: list[decl] = field(default_factory=list)

@dataclass
class PreprocessorDirective:
    text: str = ""
    line: int = 0
    col: int = 0

@dataclass
class ClassDecl:
    name: str = ""
    generic_params: list[str] = field(default_factory=list)
    members: list[class_member] = field(default_factory=list)
    parent: Optional[str] = None
    interfaces: list[str] = field(default_factory=list)
    is_abstract: bool = False
    line: int = 0
    col: int = 0

@dataclass
class InterfaceDecl:
    name: str = ""
    methods: list[MethodSig] = field(default_factory=list)
    parent: Optional[str] = None
    generic_params: list[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class FunctionDecl:
    return_type: TypeExpr = None
    name: str = ""
    params: list[Param] = field(default_factory=list)
    body: Optional[Block] = None
    is_gpu: bool = False
    keep_return: bool = False
    line: int = 0
    col: int = 0

@dataclass
class StructDecl:
    name: str = ""
    fields: list[FieldDef] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class EnumDecl:
    name: str = ""
    values: list[EnumValue] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class RichEnumDecl:
    name: str = ""
    variants: list[RichEnumVariant] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class TypedefDecl:
    original: TypeExpr = None
    alias: str = ""
    line: int = 0
    col: int = 0

@dataclass
class TypeExpr:
    base: str = ""
    generic_args: list[TypeExpr] = field(default_factory=list)
    pointer_depth: int = 0
    is_array: bool = False
    array_size: Optional[expr] = None
    is_const: bool = False
    line: int = 0
    col: int = 0

@dataclass
class Param:
    type: TypeExpr = None
    name: str = ""
    default: Optional[expr] = None
    keep: bool = False
    line: int = 0
    col: int = 0

@dataclass
class FieldDecl:
    access: str = ""
    type: TypeExpr = None
    name: str = ""
    initializer: Optional[expr] = None
    line: int = 0
    col: int = 0

@dataclass
class MethodDecl:
    access: str = ""
    return_type: TypeExpr = None
    name: str = ""
    params: list[Param] = field(default_factory=list)
    body: Optional[Block] = None
    is_gpu: bool = False
    is_abstract: bool = False
    keep_return: bool = False
    line: int = 0
    col: int = 0

@dataclass
class PropertyDecl:
    access: str = ""
    type: TypeExpr = None
    name: str = ""
    has_getter: bool = False
    has_setter: bool = False
    getter_body: Optional[Block] = None
    setter_body: Optional[Block] = None
    line: int = 0
    col: int = 0

@dataclass
class MethodSig:
    return_type: TypeExpr = None
    name: str = ""
    params: list[Param] = field(default_factory=list)
    keep_return: bool = False
    line: int = 0
    col: int = 0

@dataclass
class EnumValue:
    name: str = ""
    value: Optional[expr] = None

@dataclass
class RichEnumVariant:
    name: str = ""
    params: list[Param] = field(default_factory=list)

@dataclass
class FieldDef:
    type: TypeExpr = None
    name: str = ""

@dataclass
class Block:
    statements: list[stmt] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class VarDeclStmt:
    type: Optional[TypeExpr] = None
    name: str = ""
    initializer: Optional[expr] = None
    line: int = 0
    col: int = 0

@dataclass
class ReturnStmt:
    value: Optional[expr] = None
    line: int = 0
    col: int = 0

@dataclass
class IfStmt:
    condition: expr = None
    then_block: Block = None
    else_block: Optional[if_else] = None
    line: int = 0
    col: int = 0

@dataclass
class WhileStmt:
    condition: expr = None
    body: Block = None
    line: int = 0
    col: int = 0

@dataclass
class DoWhileStmt:
    body: Block = None
    condition: expr = None
    line: int = 0
    col: int = 0

@dataclass
class ForInStmt:
    var_name: str = ""
    var_name2: Optional[str] = None
    iterable: expr = None
    body: Block = None
    line: int = 0
    col: int = 0

@dataclass
class CForStmt:
    init: Optional[for_init] = None
    condition: Optional[expr] = None
    update: Optional[expr] = None
    body: Block = None
    line: int = 0
    col: int = 0

@dataclass
class ParallelForStmt:
    var_name: str = ""
    iterable: expr = None
    body: Block = None
    line: int = 0
    col: int = 0

@dataclass
class SwitchStmt:
    value: expr = None
    cases: list[CaseClause] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class BreakStmt:
    line: int = 0
    col: int = 0

@dataclass
class ContinueStmt:
    line: int = 0
    col: int = 0

@dataclass
class ExprStmt:
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class DeleteStmt:
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class TryCatchStmt:
    try_block: Block = None
    catch_var: str = ""
    catch_block: Block = None
    finally_block: Optional[Block] = None
    line: int = 0
    col: int = 0

@dataclass
class ThrowStmt:
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class KeepStmt:
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class ReleaseStmt:
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class ElseBlock:
    body: Block = None

@dataclass
class ElseIf:
    if_stmt: stmt = None

@dataclass
class ForInitVar:
    var_decl: stmt = None

@dataclass
class ForInitExpr:
    expression: expr = None

@dataclass
class CaseClause:
    value: Optional[expr] = None
    body: list[stmt] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class IntLiteral:
    value: int = 0
    raw: str = ""
    line: int = 0
    col: int = 0

@dataclass
class FloatLiteral:
    value: float = 0.0
    raw: str = ""
    line: int = 0
    col: int = 0

@dataclass
class StringLiteral:
    value: str = ""
    line: int = 0
    col: int = 0

@dataclass
class CharLiteral:
    value: str = ""
    line: int = 0
    col: int = 0

@dataclass
class BoolLiteral:
    value: bool = False
    line: int = 0
    col: int = 0

@dataclass
class NullLiteral:
    line: int = 0
    col: int = 0

@dataclass
class Identifier:
    name: str = ""
    line: int = 0
    col: int = 0

@dataclass
class SelfExpr:
    line: int = 0
    col: int = 0

@dataclass
class SuperExpr:
    line: int = 0
    col: int = 0

@dataclass
class BinaryExpr:
    left: expr = None
    op: str = ""
    right: expr = None
    line: int = 0
    col: int = 0

@dataclass
class UnaryExpr:
    op: str = ""
    operand: expr = None
    prefix: bool = False
    line: int = 0
    col: int = 0

@dataclass
class CallExpr:
    callee: expr = None
    args: list[expr] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class IndexExpr:
    obj: expr = None
    index: expr = None
    line: int = 0
    col: int = 0

@dataclass
class FieldAccessExpr:
    obj: expr = None
    field: str = ""
    arrow: bool = False
    optional: bool = False
    line: int = 0
    col: int = 0

@dataclass
class CastExpr:
    target_type: TypeExpr = None
    expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class SizeofExpr:
    operand: sizeof_operand = None
    line: int = 0
    col: int = 0

@dataclass
class TernaryExpr:
    condition: expr = None
    true_expr: expr = None
    false_expr: expr = None
    line: int = 0
    col: int = 0

@dataclass
class AssignExpr:
    target: expr = None
    op: str = ""
    value: expr = None
    line: int = 0
    col: int = 0

@dataclass
class ListLiteral:
    elements: list[expr] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class MapLiteral:
    entries: list[MapEntry] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class BraceInitializer:
    elements: list[expr] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class FStringLiteral:
    parts: list[fstring_part] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class NewExpr:
    type: TypeExpr = None
    args: list[expr] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class TupleLiteral:
    elements: list[expr] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class LambdaExpr:
    return_type: Optional[TypeExpr] = None
    params: list[Param] = field(default_factory=list)
    body: lambda_body = None
    captures: list[Capture] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class SizeofType:
    type: TypeExpr = None

@dataclass
class SizeofExprOp:
    expr: expr = None

@dataclass
class MapEntry:
    key: expr = None
    value: expr = None

@dataclass
class FStringText:
    text: str = ""

@dataclass
class FStringExpr:
    expression: expr = None

@dataclass
class LambdaBlock:
    body: Block = None

@dataclass
class LambdaExprBody:
    expression: expr = None

@dataclass
class Capture:
    name: str = ""
    type: TypeExpr = None


# --- Union type aliases for sum types ---

decl = Union[PreprocessorDirective, ClassDecl, InterfaceDecl, FunctionDecl, StructDecl, EnumDecl, RichEnumDecl, TypedefDecl]
class_member = Union[FieldDecl, MethodDecl, PropertyDecl]
stmt = Union[VarDeclStmt, ReturnStmt, IfStmt, WhileStmt, DoWhileStmt, ForInStmt, CForStmt, ParallelForStmt, SwitchStmt, BreakStmt, ContinueStmt, ExprStmt, DeleteStmt, TryCatchStmt, ThrowStmt, KeepStmt, ReleaseStmt]
if_else = Union[ElseBlock, ElseIf]
for_init = Union[ForInitVar, ForInitExpr]
expr = Union[IntLiteral, FloatLiteral, StringLiteral, CharLiteral, BoolLiteral, NullLiteral, Identifier, SelfExpr, SuperExpr, BinaryExpr, UnaryExpr, CallExpr, IndexExpr, FieldAccessExpr, CastExpr, SizeofExpr, TernaryExpr, AssignExpr, ListLiteral, MapLiteral, BraceInitializer, FStringLiteral, NewExpr, TupleLiteral, LambdaExpr]
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


# --- Visitor ---

class NodeVisitor:
    """Base class for AST visitors. Override visit_* methods."""

    def visit(self, node):
        method = f"visit_{type(node).__name__}"
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        pass

    def visit_Program(self, node: Program):
        return self.generic_visit(node)

    def visit_PreprocessorDirective(self, node: PreprocessorDirective):
        return self.generic_visit(node)

    def visit_ClassDecl(self, node: ClassDecl):
        return self.generic_visit(node)

    def visit_InterfaceDecl(self, node: InterfaceDecl):
        return self.generic_visit(node)

    def visit_FunctionDecl(self, node: FunctionDecl):
        return self.generic_visit(node)

    def visit_StructDecl(self, node: StructDecl):
        return self.generic_visit(node)

    def visit_EnumDecl(self, node: EnumDecl):
        return self.generic_visit(node)

    def visit_RichEnumDecl(self, node: RichEnumDecl):
        return self.generic_visit(node)

    def visit_TypedefDecl(self, node: TypedefDecl):
        return self.generic_visit(node)

    def visit_TypeExpr(self, node: TypeExpr):
        return self.generic_visit(node)

    def visit_Param(self, node: Param):
        return self.generic_visit(node)

    def visit_FieldDecl(self, node: FieldDecl):
        return self.generic_visit(node)

    def visit_MethodDecl(self, node: MethodDecl):
        return self.generic_visit(node)

    def visit_PropertyDecl(self, node: PropertyDecl):
        return self.generic_visit(node)

    def visit_MethodSig(self, node: MethodSig):
        return self.generic_visit(node)

    def visit_EnumValue(self, node: EnumValue):
        return self.generic_visit(node)

    def visit_RichEnumVariant(self, node: RichEnumVariant):
        return self.generic_visit(node)

    def visit_FieldDef(self, node: FieldDef):
        return self.generic_visit(node)

    def visit_Block(self, node: Block):
        return self.generic_visit(node)

    def visit_VarDeclStmt(self, node: VarDeclStmt):
        return self.generic_visit(node)

    def visit_ReturnStmt(self, node: ReturnStmt):
        return self.generic_visit(node)

    def visit_IfStmt(self, node: IfStmt):
        return self.generic_visit(node)

    def visit_WhileStmt(self, node: WhileStmt):
        return self.generic_visit(node)

    def visit_DoWhileStmt(self, node: DoWhileStmt):
        return self.generic_visit(node)

    def visit_ForInStmt(self, node: ForInStmt):
        return self.generic_visit(node)

    def visit_CForStmt(self, node: CForStmt):
        return self.generic_visit(node)

    def visit_ParallelForStmt(self, node: ParallelForStmt):
        return self.generic_visit(node)

    def visit_SwitchStmt(self, node: SwitchStmt):
        return self.generic_visit(node)

    def visit_BreakStmt(self, node: BreakStmt):
        return self.generic_visit(node)

    def visit_ContinueStmt(self, node: ContinueStmt):
        return self.generic_visit(node)

    def visit_ExprStmt(self, node: ExprStmt):
        return self.generic_visit(node)

    def visit_DeleteStmt(self, node: DeleteStmt):
        return self.generic_visit(node)

    def visit_TryCatchStmt(self, node: TryCatchStmt):
        return self.generic_visit(node)

    def visit_ThrowStmt(self, node: ThrowStmt):
        return self.generic_visit(node)

    def visit_KeepStmt(self, node: KeepStmt):
        return self.generic_visit(node)

    def visit_ReleaseStmt(self, node: ReleaseStmt):
        return self.generic_visit(node)

    def visit_ElseBlock(self, node: ElseBlock):
        return self.generic_visit(node)

    def visit_ElseIf(self, node: ElseIf):
        return self.generic_visit(node)

    def visit_ForInitVar(self, node: ForInitVar):
        return self.generic_visit(node)

    def visit_ForInitExpr(self, node: ForInitExpr):
        return self.generic_visit(node)

    def visit_CaseClause(self, node: CaseClause):
        return self.generic_visit(node)

    def visit_IntLiteral(self, node: IntLiteral):
        return self.generic_visit(node)

    def visit_FloatLiteral(self, node: FloatLiteral):
        return self.generic_visit(node)

    def visit_StringLiteral(self, node: StringLiteral):
        return self.generic_visit(node)

    def visit_CharLiteral(self, node: CharLiteral):
        return self.generic_visit(node)

    def visit_BoolLiteral(self, node: BoolLiteral):
        return self.generic_visit(node)

    def visit_NullLiteral(self, node: NullLiteral):
        return self.generic_visit(node)

    def visit_Identifier(self, node: Identifier):
        return self.generic_visit(node)

    def visit_SelfExpr(self, node: SelfExpr):
        return self.generic_visit(node)

    def visit_SuperExpr(self, node: SuperExpr):
        return self.generic_visit(node)

    def visit_BinaryExpr(self, node: BinaryExpr):
        return self.generic_visit(node)

    def visit_UnaryExpr(self, node: UnaryExpr):
        return self.generic_visit(node)

    def visit_CallExpr(self, node: CallExpr):
        return self.generic_visit(node)

    def visit_IndexExpr(self, node: IndexExpr):
        return self.generic_visit(node)

    def visit_FieldAccessExpr(self, node: FieldAccessExpr):
        return self.generic_visit(node)

    def visit_CastExpr(self, node: CastExpr):
        return self.generic_visit(node)

    def visit_SizeofExpr(self, node: SizeofExpr):
        return self.generic_visit(node)

    def visit_TernaryExpr(self, node: TernaryExpr):
        return self.generic_visit(node)

    def visit_AssignExpr(self, node: AssignExpr):
        return self.generic_visit(node)

    def visit_ListLiteral(self, node: ListLiteral):
        return self.generic_visit(node)

    def visit_MapLiteral(self, node: MapLiteral):
        return self.generic_visit(node)

    def visit_BraceInitializer(self, node: BraceInitializer):
        return self.generic_visit(node)

    def visit_FStringLiteral(self, node: FStringLiteral):
        return self.generic_visit(node)

    def visit_NewExpr(self, node: NewExpr):
        return self.generic_visit(node)

    def visit_TupleLiteral(self, node: TupleLiteral):
        return self.generic_visit(node)

    def visit_LambdaExpr(self, node: LambdaExpr):
        return self.generic_visit(node)

    def visit_SizeofType(self, node: SizeofType):
        return self.generic_visit(node)

    def visit_SizeofExprOp(self, node: SizeofExprOp):
        return self.generic_visit(node)

    def visit_MapEntry(self, node: MapEntry):
        return self.generic_visit(node)

    def visit_FStringText(self, node: FStringText):
        return self.generic_visit(node)

    def visit_FStringExpr(self, node: FStringExpr):
        return self.generic_visit(node)

    def visit_LambdaBlock(self, node: LambdaBlock):
        return self.generic_visit(node)

    def visit_LambdaExprBody(self, node: LambdaExprBody):
        return self.generic_visit(node)

    def visit_Capture(self, node: Capture):
        return self.generic_visit(node)

