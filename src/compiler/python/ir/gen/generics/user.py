"""User-defined generic class monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type
from .core import _resolve_type

if TYPE_CHECKING:
    from ..generator import IRGenerator


def _emit_user_generic_instance(gen: IRGenerator, base_name: str,
                                 args: list[TypeExpr]):
    """Emit a user-defined generic class instance (struct + methods)."""
    cls_info = gen.analyzed.class_table.get(base_name)
    if not cls_info:
        return
    mangled = mangle_generic_type(base_name, args)

    # Build type parameter mapping
    type_map = {}
    for i, gp in enumerate(cls_info.generic_params):
        if i < len(args):
            type_map[gp] = args[i]

    # Emit struct with resolved types
    fields = []
    for name, fd in cls_info.fields.items():
        resolved = _resolve_type(fd.type, type_map)
        fields.append(IRStructField(c_type=CType(text=type_to_c(resolved)), name=name))
    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=fields))

    # Emit constructor, destructor, and methods
    _emit_user_generic_methods(gen, base_name, mangled, args, type_map, cls_info)


def _emit_user_generic_methods(gen: IRGenerator, base_name: str, mangled: str,
                                args: list[TypeExpr],
                                type_map: dict[str, TypeExpr],
                                cls_info):
    """Emit constructor + methods for a user-defined generic class instance."""
    from ....ast_nodes import MethodDecl, FieldDecl
    from ..types import type_to_c as ttc

    def resolve_c(t):
        return ttc(_resolve_type(t, type_map))

    # Build param list string with resolved types
    ctor = cls_info.constructor
    ctor_params = []
    if ctor:
        for p in ctor.params:
            ctor_params.append(f"{resolve_c(p.type)} {p.name}")

    # Constructor: init + new
    init_params = [f"{mangled}* self"] + ctor_params
    init_body_lines = []
    if ctor and ctor.body:
        # Simple body: just assign params to fields (common pattern)
        for s in ctor.body.statements:
            from ....ast_nodes import ExprStmt, AssignExpr, FieldAccessExpr, SelfExpr, Identifier
            if isinstance(s, ExprStmt) and isinstance(s.expr, AssignExpr):
                tgt = s.expr.target
                val = s.expr.value
                if isinstance(tgt, FieldAccessExpr) and isinstance(tgt.obj, SelfExpr):
                    if isinstance(val, Identifier):
                        init_body_lines.append(f"    self->{tgt.field} = {val.name};")

    methods = f"""
static void {mangled}_init({', '.join(init_params)}) {{
{''.join(init_body_lines) if init_body_lines else '    (void)self;'}
}}
static {mangled}* {mangled}_new({', '.join(ctor_params) if ctor_params else 'void'}) {{
    {mangled}* self = ({mangled}*)malloc(sizeof({mangled}));
    memset(self, 0, sizeof({mangled}));
    {mangled}_init(self{(''.join(', ' + p.name for p in ctor.params)) if ctor else ''});
    return self;
}}
static void {mangled}_destroy({mangled}* self) {{ free(self); }}
"""
    # Emit methods
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or mname == base_name:
            continue
        ret_c = resolve_c(method.return_type) if method.return_type else "void"
        m_params = [f"{mangled}* self"]
        for p in method.params:
            m_params.append(f"{resolve_c(p.type)} {p.name}")
        # Generate simple method body
        m_body = _gen_simple_method_body(method, type_map, mangled)
        methods += f"static {ret_c} {mangled}_{mname}({', '.join(m_params)}) {{\n{m_body}}}\n"

    gen.module.raw_sections.append(methods.strip())


def _gen_simple_method_body(method, type_map, mangled):
    """Generate a simple C method body for user generic methods."""
    from ....ast_nodes import (
        ReturnStmt, ExprStmt, FieldAccessExpr, SelfExpr, Identifier,
        AssignExpr, UnaryExpr, BinaryExpr, BoolLiteral, IntLiteral,
        NullLiteral, CallExpr, StringLiteral, TernaryExpr,
        IfStmt, Block,
    )

    def _expr_c(e) -> str:
        """Render an AST expression to C text."""
        if isinstance(e, FieldAccessExpr) and isinstance(e.obj, SelfExpr):
            return f"self->{e.field}"
        if isinstance(e, FieldAccessExpr):
            inner = _expr_c(e.obj)
            return f"{inner}->{e.field}" if inner else f"/* ? */->{e.field}"
        if isinstance(e, Identifier):
            return e.name
        if isinstance(e, IntLiteral):
            return str(e.value)
        if isinstance(e, BoolLiteral):
            return "true" if e.value else "false"
        if isinstance(e, NullLiteral):
            return "NULL"
        if isinstance(e, StringLiteral):
            return f'"{e.value}"'
        if isinstance(e, UnaryExpr):
            return f"({e.op}{_expr_c(e.operand)})"
        if isinstance(e, BinaryExpr):
            return f"({_expr_c(e.left)} {e.op} {_expr_c(e.right)})"
        if isinstance(e, TernaryExpr):
            return f"({_expr_c(e.condition)} ? {_expr_c(e.true_expr)} : {_expr_c(e.false_expr)})"
        if isinstance(e, CallExpr):
            if isinstance(e.callee, Identifier):
                a = ", ".join(_expr_c(x) for x in e.args)
                return f"{e.callee.name}({a})"
            if isinstance(e.callee, FieldAccessExpr) and isinstance(e.callee.obj, SelfExpr):
                a = ", ".join(_expr_c(x) for x in e.args)
                return f"{mangled}_{e.callee.field}(self{', ' + a if a else ''})"
        if isinstance(e, AssignExpr):
            return f"{_expr_c(e.target)} {e.op} {_expr_c(e.value)}"
        return "0"

    def _stmt_c(s, indent="    ") -> str:
        """Render an AST statement to C text."""
        if isinstance(s, ReturnStmt):
            if s.value:
                return f"{indent}return {_expr_c(s.value)};\n"
            return f"{indent}return;\n"
        if isinstance(s, ExprStmt):
            return f"{indent}{_expr_c(s.expr)};\n"
        if isinstance(s, IfStmt):
            txt = f"{indent}if ({_expr_c(s.condition)}) {{\n"
            if s.then_block:
                for st in s.then_block.statements:
                    txt += _stmt_c(st, indent + "    ")
            txt += f"{indent}}}"
            if s.else_block:
                if isinstance(s.else_block, Block):
                    txt += f" else {{\n"
                    for st in s.else_block.statements:
                        txt += _stmt_c(st, indent + "    ")
                    txt += f"{indent}}}"
            txt += "\n"
            return txt
        return f"{indent}/* unhandled stmt */;\n"

    lines = []
    if method.body:
        for s in method.body.statements:
            lines.append(_stmt_c(s))
    if not lines:
        lines.append("    (void)self;\n")
    return "".join(lines)
