"""Variable declaration lowering and keep-parameter helpers.

Handles ``var`` declarations (including array types, generic constructors,
ARC auto-management) and the ``keep`` param rc++ emission before calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    Identifier,
    NewExpr,
    VarDeclStmt,
)
from ..nodes import CType, IRCall, IRExprStmt, IRRawExpr, IRStmt, IRVar, IRVarDecl
from .expressions import lower_expr
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def _maybe_register_cleanup(gen: IRGenerator, var_name: str,
                             cls_name: str, stmts: list[IRStmt]):
    """If inside a try block, register an ARC cleanup for exception safety.

    When an exception is thrown (longjmp), normal scope-exit release is skipped.
    The cleanup stack ensures managed vars are released even on throw.
    On normal exit, cleanups are discarded (scope release already freed them).
    """
    from .arc import _destroy_fn_for_managed
    if gen.in_try_depth <= 0:
        return
    # Mark the VarDecl volatile so gcc doesn't optimize away the NULL write
    # after delete. Without this, block-scoped vars (e.g. inside a for loop)
    # may have their `var = NULL` eliminated at -O1/-O2, causing the cleanup
    # to read a stale non-NULL pointer and double-free.
    for s in reversed(stmts):
        if isinstance(s, IRVarDecl) and s.name == var_name:
            s.is_volatile = True
            break
    destroy_fn = _destroy_fn_for_managed(gen, cls_name)
    gen.use_helper("__btrc_register_cleanup")
    stmts.append(IRExprStmt(expr=IRCall(
        callee="__btrc_register_cleanup",
        args=[IRRawExpr(text=f"(void**)&{var_name}"),
              IRRawExpr(text=f"(__btrc_cleanup_fn){destroy_fn}")],
        helper_ref="__btrc_register_cleanup")))


def _lower_var_decl(gen: IRGenerator, node: VarDeclStmt) -> list[IRStmt]:
    from ...ast_nodes import BraceInitializer
    from ...ast_nodes import TypeExpr as TE
    from .types import is_generic_class_type, mangle_generic_type

    # Handle array types: int arr[5] or int nums[]
    if node.type and node.type.is_array:
        base_type = TE(base=node.type.base,
                       generic_args=node.type.generic_args,
                       pointer_depth=node.type.pointer_depth)
        base_c = type_to_c(base_type)
        if node.type.array_size:
            from .statements import _quick_text
            size_text = _quick_text(lower_expr(gen, node.type.array_size))
            var_name = f"{node.name}[{size_text}]"
        else:
            var_name = f"{node.name}[]"
        init = lower_expr(gen, node.initializer) if node.initializer else None
        return [IRVarDecl(c_type=CType(text=base_c), name=var_name, init=init)]

    c_type = type_to_c(node.type) if node.type else "int"
    init = None
    if node.initializer:
        from ...ast_nodes import ListLiteral, MapLiteral
        ct = gen.analyzed.class_table
        # Empty brace initializer on generic class types -> TYPE_new()
        if (isinstance(node.initializer, BraceInitializer)
                and not node.initializer.elements
                and node.type and is_generic_class_type(node.type, ct)) or (isinstance(node.initializer, ListLiteral)
              and not node.initializer.elements
              and node.type and is_generic_class_type(node.type, ct)) or (isinstance(node.initializer, MapLiteral)
              and not node.initializer.entries
              and node.type and is_generic_class_type(node.type, ct)):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        else:
            init = lower_expr(gen, node.initializer)
            # Fix generic constructor calls: Box(42) -> btrc_Box_int_new(42)
            if (isinstance(init, IRCall) and node.type
                    and node.type.generic_args
                    and isinstance(node.initializer, CallExpr)
                    and isinstance(node.initializer.callee, Identifier)):
                ctor_name = node.initializer.callee.name
                cls_info = gen.analyzed.class_table.get(ctor_name)
                if cls_info and cls_info.generic_params:
                    mangled = mangle_generic_type(ctor_name, node.type.generic_args)
                    init = IRCall(callee=f"{mangled}_new", args=init.args)
    # ARC: emit rc++ for keep params if initializer is a call
    pre_stmts = _emit_keep_for_call(gen, node.initializer)
    var_decl = IRVarDecl(c_type=CType(text=c_type), name=node.name, init=init)
    gen._func_var_decls.append(var_decl)
    result = pre_stmts + [var_decl]

    # Lambda capture struct allocation: when var = lambda_with_captures,
    # allocate the capture struct on the stack and fill it with captured values.
    # The captured lambda's C function has an extra void* param that doesn't
    # match the typedef, so we cast it for storage and call it directly
    # (bypassing the function pointer) when the variable is invoked.
    from ...ast_nodes import LambdaExpr
    if isinstance(node.initializer, LambdaExpr) and node.initializer.captures:
        from ..nodes import IRAssign, IRCast, IRFieldAccess
        lambda_id = gen._last_lambda_id
        fn_name = f"__btrc_lambda_{lambda_id}"
        env_struct = f"__btrc_lambda_{lambda_id}_env"
        env_var = f"__{node.name}_env"
        # Cast the captured lambda to the typedef type for storage
        var_decl.init = IRCast(target_type=c_type,
                               expr=IRRawExpr(text=fn_name))
        result.append(IRVarDecl(
            c_type=CType(text=f"struct {env_struct}"),
            name=env_var,
        ))
        for cap in node.initializer.captures:
            result.append(IRAssign(
                target=IRFieldAccess(
                    obj=IRVar(name=env_var), field=cap.name, arrow=False),
                value=IRVar(name=cap.name),
            ))
        # Track: variable → (lambda fn name, env var name)
        gen._fn_ptr_envs[node.name] = (fn_name, env_var)

    # ARC: auto-manage variables initialized with `new` or constructor calls.
    # Per plan rule 1: new Foo() -> alloc, rc = 1, auto-managed at declaring scope.
    # Rule 2: Foo() (constructor call) -> same as new.
    # delete sets var = NULL, so scope exit safely skips deleted vars.
    # Skip generic types: collections (Vector, Map, etc.) use explicit .free()
    # which doesn't set the variable to NULL, so auto-management would double-free.
    if (node.initializer and node.type
            and node.type.base in gen.analyzed.class_table
            and not node.type.generic_args):
        cls_info = gen.analyzed.class_table.get(node.type.base)
        # Only auto-manage non-generic classes (not generic templates)
        if cls_info and not cls_info.generic_params:
            arc_type = node.type.base
            if isinstance(node.initializer, NewExpr) or (isinstance(node.initializer, CallExpr)
                  and isinstance(node.initializer.callee, Identifier)
                  and node.initializer.callee.name in gen.analyzed.class_table):
                gen.register_managed_var(node.name, arc_type)
                _maybe_register_cleanup(gen, node.name, arc_type, result)
            elif isinstance(node.initializer, CallExpr):
                from .calls import has_keep_return
                if has_keep_return(gen, node.initializer):
                    ret_type = gen.analyzed.node_types.get(id(node.initializer))
                    if (ret_type and ret_type.base in gen.analyzed.class_table
                            and not ret_type.generic_args):
                        gen.register_managed_var(node.name, ret_type.base)
                        _maybe_register_cleanup(gen, node.name, ret_type.base, result)

    return result


def _managed_type_name(gen: IRGenerator, type_expr) -> str:
    """Get the correct type name for managed var tracking (mangled for generics)."""
    from .types import is_generic_class_type, mangle_generic_type
    ct = gen.analyzed.class_table
    if type_expr.generic_args and is_generic_class_type(type_expr, ct):
        return mangle_generic_type(type_expr.base, type_expr.generic_args)
    return type_expr.base


def _emit_keep_for_call(gen: IRGenerator, expr) -> list[IRStmt]:
    """If expr is a CallExpr with `keep` params, emit rc++ for those args."""
    from ...ast_nodes import CallExpr as CE
    if not isinstance(expr, CE):
        return []
    from .calls import emit_keep_rc_increments
    # We need the lowered args to emit rc++ on. Lower args separately.
    ir_args = [lower_expr(gen, a) for a in expr.args]
    # For method calls, the args in the IR don't include 'self' -- that's
    # prepended by the method call lowering. keep indices refer to the
    # method's declared params (excluding self).
    return emit_keep_rc_increments(gen, expr, ir_args)
