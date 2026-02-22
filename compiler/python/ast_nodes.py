"""AST node definitions for the btrc language."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Union


# ---- Types ----

@dataclass
class TypeExpr:
    base: str                                    # "int", "float", "List", "Vec3", etc.
    generic_args: list[TypeExpr] = field(default_factory=list)
    pointer_depth: int = 0                       # 0 = value, 1 = *, 2 = **, etc.
    is_array: bool = False                       # T[] syntax (for @gpu params)
    array_size: Optional[object] = None          # Fixed-size: T name[N]
    line: int = 0
    col: int = 0

    def __repr__(self):
        s = self.base
        if self.generic_args:
            s += "<" + ", ".join(repr(a) for a in self.generic_args) + ">"
        if self.is_array:
            s += "[]"
        s += "*" * self.pointer_depth
        return s


@dataclass
class Param:
    type: TypeExpr
    name: str
    default: Optional[object] = None              # default value expression
    line: int = 0
    col: int = 0


# ---- Top-level declarations ----

@dataclass
class Program:
    declarations: list = field(default_factory=list)


@dataclass
class PreprocessorDirective:
    text: str
    line: int = 0
    col: int = 0


@dataclass
class ClassDecl:
    name: str
    generic_params: list[str] = field(default_factory=list)
    members: list = field(default_factory=list)   # FieldDecl | MethodDecl
    parent: Optional[str] = None                  # single inheritance: parent class name
    line: int = 0
    col: int = 0


@dataclass
class FunctionDecl:
    return_type: TypeExpr = None
    name: str = ""
    params: list[Param] = field(default_factory=list)
    body: Block = None
    is_gpu: bool = False
    line: int = 0
    col: int = 0


@dataclass
class StructDecl:
    name: str = ""
    fields: list = field(default_factory=list)    # list of (TypeExpr, name) or FieldDecl
    line: int = 0
    col: int = 0


@dataclass
class EnumDecl:
    name: str = ""
    values: list = field(default_factory=list)    # list of (name, Optional[expr])
    line: int = 0
    col: int = 0


@dataclass
class TypedefDecl:
    original: TypeExpr = None
    alias: str = ""
    line: int = 0
    col: int = 0


# ---- Class members ----

@dataclass
class FieldDecl:
    access: str = "private"                       # "public" | "private"
    type: TypeExpr = None
    name: str = ""
    initializer: Optional[object] = None          # expr or None
    line: int = 0
    col: int = 0


@dataclass
class MethodDecl:
    access: str = "public"                        # "public" | "private" | "class"
    return_type: TypeExpr = None
    name: str = ""
    params: list[Param] = field(default_factory=list)
    body: Block = None
    is_gpu: bool = False
    line: int = 0
    col: int = 0


# ---- Statements ----

@dataclass
class Block:
    statements: list = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class VarDeclStmt:
    type: TypeExpr = None
    name: str = ""
    initializer: Optional[object] = None
    line: int = 0
    col: int = 0


@dataclass
class ReturnStmt:
    value: Optional[object] = None
    line: int = 0
    col: int = 0


@dataclass
class IfStmt:
    condition: object = None
    then_block: Block = None
    else_block: Optional[object] = None           # Block | IfStmt | None
    line: int = 0
    col: int = 0


@dataclass
class WhileStmt:
    condition: object = None
    body: Block = None
    line: int = 0
    col: int = 0


@dataclass
class DoWhileStmt:
    body: Block = None
    condition: object = None
    line: int = 0
    col: int = 0


@dataclass
class ForInStmt:
    var_name: str = ""
    iterable: object = None
    body: Block = None
    line: int = 0
    col: int = 0


@dataclass
class ParallelForStmt:
    var_name: str = ""
    iterable: object = None
    body: Block = None
    line: int = 0
    col: int = 0


@dataclass
class CForStmt:
    init: Optional[object] = None                 # VarDeclStmt | expr | None
    condition: Optional[object] = None
    update: Optional[object] = None
    body: Block = None
    line: int = 0
    col: int = 0


@dataclass
class SwitchStmt:
    value: object = None
    cases: list = field(default_factory=list)     # list of CaseClause
    line: int = 0
    col: int = 0


@dataclass
class CaseClause:
    value: Optional[object] = None                # None = default
    body: list = field(default_factory=list)
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
    expr: object = None
    line: int = 0
    col: int = 0


@dataclass
class DeleteStmt:
    expr: object = None
    line: int = 0
    col: int = 0


@dataclass
class TryCatchStmt:
    try_block: Block = None
    catch_var: str = ""                           # variable name for caught error
    catch_block: Block = None
    line: int = 0
    col: int = 0


@dataclass
class ThrowStmt:
    expr: object = None                           # expression to throw (usually a string)
    line: int = 0
    col: int = 0


# ---- Expressions ----

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
class BinaryExpr:
    left: object = None
    op: str = ""
    right: object = None
    line: int = 0
    col: int = 0


@dataclass
class UnaryExpr:
    op: str = ""
    operand: object = None
    prefix: bool = True
    line: int = 0
    col: int = 0


@dataclass
class CallExpr:
    callee: object = None
    args: list = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class IndexExpr:
    obj: object = None
    index: object = None
    line: int = 0
    col: int = 0


@dataclass
class FieldAccessExpr:
    obj: object = None
    field: str = ""
    arrow: bool = False                           # True for ->, False for .
    optional: bool = False                        # True for ?. (optional chaining)
    line: int = 0
    col: int = 0


@dataclass
class CastExpr:
    target_type: TypeExpr = None
    expr: object = None
    line: int = 0
    col: int = 0


@dataclass
class SizeofExpr:
    operand: object = None                        # TypeExpr or expr
    line: int = 0
    col: int = 0


@dataclass
class TernaryExpr:
    condition: object = None
    true_expr: object = None
    false_expr: object = None
    line: int = 0
    col: int = 0


@dataclass
class AssignExpr:
    target: object = None
    op: str = "="
    value: object = None
    line: int = 0
    col: int = 0


@dataclass
class ListLiteral:
    elements: list = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class MapLiteral:
    entries: list = field(default_factory=list)   # list of (key_expr, value_expr)
    line: int = 0
    col: int = 0


@dataclass
class BraceInitializer:
    elements: list = field(default_factory=list)  # C-style {a, b, c} initializer
    line: int = 0
    col: int = 0


@dataclass
class FStringLiteral:
    parts: list = field(default_factory=list)  # list of ("text", str) | ("expr", AST_node)
    line: int = 0
    col: int = 0


@dataclass
class NewExpr:
    type: TypeExpr = None
    args: list = field(default_factory=list)
    line: int = 0
    col: int = 0


@dataclass
class TupleLiteral:
    elements: list = field(default_factory=list)
    line: int = 0
    col: int = 0
