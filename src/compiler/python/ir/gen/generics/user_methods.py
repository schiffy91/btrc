"""Method emission for user-defined generic class instances."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import (
    CType, IRAssign, IRBinOp, IRBlock, IRCall, IRCast, IRExprStmt,
    IRFieldAccess, IRFunctionDef, IRIf, IRLiteral, IRParam, IRReturn,
    IRUnaryOp, IRVar, IRVarDecl,
)
from ..types import type_to_c, mangle_generic_type
from .core import _resolve_type
from .user_emitter import _UserGenericEmitter
from .user_emitter_stmts import _ir_stmts_to_text

if TYPE_CHECKING:
    from ..generator import IRGenerator

# Runtime helpers to register when referenced in emitted code
_KNOWN_HELPERS = {"__btrc_safe_realloc", "__btrc_safe_calloc"}


def _is_type_incompatible(body_text: str, first_arg_c: str) -> bool:
    """Check if emitted method body uses ops incompatible with the type.

    C doesn't have templates -- all static functions must type-check even if
    unused.  This skips methods like sum() for pointer types (pointer + pointer
    is invalid) and join() for non-string types (strlen on non-string).
    """
    is_pointer = first_arg_c.endswith("*")
    if not is_pointer:
        # strlen/memcpy on non-string element data (join/joinToString)
        if "strlen(self->" in body_text or "memcpy(" in body_text:
            return True
    if is_pointer:
        # ptr + ptr is invalid C (sum-like methods use T + T arithmetic)
        if "+ self->data[" in body_text:
            return True
        # strlen/strncmp/memcpy on non-string pointer types
        if first_arg_c != "char*":
            if "strlen(self->" in body_text or "memcpy(" in body_text:
                return True
    return False


def _format_params_text(mangled: str, ctor_params: list[IRParam]) -> str:
    """Format parameter list text for forward declarations."""
    parts = [f"{mangled}* self"]
    for p in ctor_params:
        parts.append(f"{p.c_type} {p.name}")
    return ", ".join(parts)


def _format_ctor_params_text(ctor_params: list[IRParam]) -> str:
    """Format constructor parameter list text for forward declarations."""
    if not ctor_params:
        return "void"
    return ", ".join(f"{p.c_type} {p.name}" for p in ctor_params)


def _emit_user_generic_methods(gen: IRGenerator, base_name: str, mangled: str,
                                args: list[TypeExpr],
                                type_map: dict[str, TypeExpr],
                                cls_info):
    """Emit constructor + methods for a user-defined generic class instance."""
    from ..types import type_to_c as ttc

    first_arg_c = ttc(args[0]) if args else "int"
    emitter = _UserGenericEmitter(type_map, mangled, ttc, gen=gen)

    ctor = cls_info.constructor
    ctor_params_ir = []
    if ctor:
        for p in ctor.params:
            ctor_params_ir.append(
                IRParam(c_type=CType(text=emitter.resolve_c(p.type)),
                        name=p.name))

    # Constructor body stmts
    init_body_stmts = []
    if ctor and ctor.body:
        init_body_stmts = emitter.emit_stmts(ctor.body.statements)
    # If body is empty, add (void)self to avoid unused parameter warning
    if not init_body_stmts:
        init_body_stmts = [IRExprStmt(
            expr=IRCast(target_type=CType(text="void"),
                        expr=IRVar(name="self")))]

    # Collect forward declarations for all methods to avoid order issues
    fwd_decls = []
    init_params_text = _format_params_text(mangled, ctor_params_ir)
    fwd_decls.append(f"static void {mangled}_init({init_params_text});")
    ctor_params_text = _format_ctor_params_text(ctor_params_ir)
    fwd_decls.append(
        f"static {mangled}* {mangled}_new({ctor_params_text});")
    fwd_decls.append(f"static void {mangled}_destroy({mangled}* self);")
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or mname == base_name:
            continue
        ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
        m_params = [f"{mangled}* self"]
        for p in method.params:
            m_params.append(f"{emitter.resolve_c(p.type)} {p.name}")
        fwd_decls.append(
            f"static {ret_c} {mangled}_{mname}({', '.join(m_params)});")

    # These go into raw_sections (not forward_decls) because they may
    # reference function pointer typedefs that aren't emitted yet.
    gen.module.raw_sections.append("\n".join(fwd_decls))

    # --- _init() function ---
    init_func = IRFunctionDef(
        name=f"{mangled}_init",
        return_type=CType(text="void"),
        params=([IRParam(c_type=CType(text=f"{mangled}*"), name="self")]
                + ctor_params_ir),
        body=IRBlock(stmts=[
            IRAssign(
                target=IRFieldAccess(obj=IRVar(name="self"),
                                     field="__rc", arrow=True),
                value=IRLiteral(text="1")),
        ] + init_body_stmts),
        is_static=True,
    )
    gen.module.function_defs.append(init_func)

    # --- _new() function ---
    ctor_arg_names = []
    if ctor:
        ctor_arg_names = [IRVar(name=p.name) for p in ctor.params]
    new_func = IRFunctionDef(
        name=f"{mangled}_new",
        return_type=CType(text=f"{mangled}*"),
        params=list(ctor_params_ir),
        body=IRBlock(stmts=[
            IRVarDecl(
                c_type=CType(text=f"{mangled}*"), name="self",
                init=IRCast(
                    target_type=CType(text=f"{mangled}*"),
                    expr=IRCall(callee="malloc",
                                args=[IRCall(callee="sizeof",
                                             args=[IRVar(name=mangled)])]))),
            IRExprStmt(
                expr=IRCall(callee="memset",
                            args=[IRVar(name="self"),
                                  IRLiteral(text="0"),
                                  IRCall(callee="sizeof",
                                         args=[IRVar(name=mangled)])])),
            IRExprStmt(
                expr=IRCall(callee=f"{mangled}_init",
                            args=[IRVar(name="self")] + ctor_arg_names)),
            IRReturn(value=IRVar(name="self")),
        ]),
        is_static=True,
    )
    gen.module.function_defs.append(new_func)

    # --- _destroy() function ---
    dtor_stmts = _build_generic_destructor_stmts(cls_info, type_map,
                                                   mangled, gen)
    dtor_stmts.append(IRExprStmt(
        expr=IRCall(callee="free", args=[IRVar(name="self")])))
    destroy_func = IRFunctionDef(
        name=f"{mangled}_destroy",
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text=f"{mangled}*"), name="self")],
        body=IRBlock(stmts=dtor_stmts),
        is_static=True,
    )
    gen.module.function_defs.append(destroy_func)

    # --- Emit methods ---
    # Two-phase: emit all, then filter out incompatible ones
    emitted = {}
    skipped = set()
    for mname, method in cls_info.methods.items():
        if mname == "__del__" or mname == base_name:
            continue
        emitter.reset_var_types(method.params)
        ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
        m_params_ir = [IRParam(c_type=CType(text=f"{mangled}*"), name="self")]
        for p in method.params:
            m_params_ir.append(
                IRParam(c_type=CType(text=emitter.resolve_c(p.type)),
                        name=p.name))
        body_stmts = (emitter.emit_stmts(method.body.statements)
                      if method.body else [])
        if not body_stmts:
            body_stmts = [IRExprStmt(
                expr=IRCast(target_type=CType(text="void"),
                            expr=IRVar(name="self")))]

        # Check type compatibility using rough text rendering
        body_text = _ir_stmts_to_text(body_stmts)
        if _is_type_incompatible(body_text, first_arg_c):
            skipped.add(mname)
            continue

        func_def = IRFunctionDef(
            name=f"{mangled}_{mname}",
            return_type=CType(text=ret_c),
            params=m_params_ir,
            body=IRBlock(stmts=body_stmts),
            is_static=True,
        )
        emitted[mname] = func_def

    # Second pass: skip methods that call skipped methods
    for mname, func_def in list(emitted.items()):
        body_text = _ir_stmts_to_text(func_def.body.stmts)
        for sk in skipped:
            if f"{mangled}_{sk}(" in body_text:
                del emitted[mname]
                break

    for func_def in emitted.values():
        gen.module.function_defs.append(func_def)

    # Register any runtime helpers referenced in the emitted code
    all_stmts = []
    for func_def in [init_func, new_func, destroy_func] + list(emitted.values()):
        if func_def.body:
            all_stmts.extend(func_def.body.stmts)
    all_text = _ir_stmts_to_text(all_stmts)
    for h in _KNOWN_HELPERS:
        if h in all_text:
            gen.use_helper(h)


def _build_generic_destructor_stmts(cls_info, type_map, mangled, gen):
    """Build the destructor body as IR statements with ARC-aware field release.

    For each class-type field: if (field) { if (--field->__rc <= 0) destroy(field); }
    For other fields: nothing (primitives don't need cleanup).
    """
    stmts = []

    # Check for user-defined __del__ method
    dtor = cls_info.methods.get("__del__")
    if dtor and dtor.body:
        emitter = _UserGenericEmitter(type_map, mangled,
                                       lambda t: type_to_c(_resolve_type(t, type_map)),
                                       gen=gen)
        stmts.extend(emitter.emit_stmts(dtor.body.statements))

    for fname, fd in cls_info.fields.items():
        if not fd.type:
            continue
        resolved = _resolve_type(fd.type, type_map)
        # Only release class instance fields (pointer_depth == 0).
        if resolved.pointer_depth > 0:
            continue
        # Generic class field -> mangled destroy/free
        if resolved.generic_args and resolved.base in gen.analyzed.class_table:
            target = mangle_generic_type(resolved.base, resolved.generic_args)
            field_cls = gen.analyzed.class_table.get(resolved.base)
            dtor_name = "free" if field_cls and "free" in field_cls.methods else "destroy"
            stmts.append(IRIf(
                condition=IRFieldAccess(
                    obj=IRVar(name="self"), field=fname, arrow=True),
                then_block=IRBlock(stmts=[IRIf(
                    condition=IRBinOp(
                        left=IRUnaryOp(
                            op="--",
                            operand=IRFieldAccess(
                                obj=IRFieldAccess(
                                    obj=IRVar(name="self"),
                                    field=fname, arrow=True),
                                field="__rc", arrow=True),
                            prefix=True),
                        op="<=",
                        right=IRLiteral(text="0")),
                    then_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRCall(
                            callee=f"{target}_{dtor_name}",
                            args=[IRFieldAccess(
                                obj=IRVar(name="self"),
                                field=fname, arrow=True)]))]),
                )]),
            ))
        # Plain class field -> ClassName_destroy
        elif resolved.base in gen.analyzed.class_table:
            stmts.append(IRIf(
                condition=IRFieldAccess(
                    obj=IRVar(name="self"), field=fname, arrow=True),
                then_block=IRBlock(stmts=[IRIf(
                    condition=IRBinOp(
                        left=IRUnaryOp(
                            op="--",
                            operand=IRFieldAccess(
                                obj=IRFieldAccess(
                                    obj=IRVar(name="self"),
                                    field=fname, arrow=True),
                                field="__rc", arrow=True),
                            prefix=True),
                        op="<=",
                        right=IRLiteral(text="0")),
                    then_block=IRBlock(stmts=[IRExprStmt(
                        expr=IRCall(
                            callee=f"{resolved.base}_destroy",
                            args=[IRFieldAccess(
                                obj=IRVar(name="self"),
                                field=fname, arrow=True)]))]),
                )]),
            ))
    return stmts
