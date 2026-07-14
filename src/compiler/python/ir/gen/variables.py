"""Variable declaration lowering and local ARC registration.

Handles ``var`` declarations, arrays, generic constructors, and ownership of
fresh or explicitly ownership-transferring initializers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import VarDeclStmt
from ..nodes import CType, IRCall, IRExprStmt, IRStmt, IRVar, IRVarDecl
from .cleanup_registration import (
    maybe_register_cleanup as _maybe_register_cleanup,
)
from .cleanup_registration import (
    maybe_register_direct_cleanup as _maybe_register_direct_cleanup,
)
from .expressions import lower_expr
from .stringable import coerce_value_to_string
from .type_resolution import canonical_type
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def _lower_var_decl(gen: IRGenerator, node: VarDeclStmt) -> list[IRStmt]:
    from ...ast_nodes import BraceInitializer
    from .types import is_generic_class_type, mangle_generic_type

    # Record every local, including borrowed values, so a shadowing declaration
    # cannot inherit an outer variable's ownership classification.
    gen.declare_local_ownership(node.name)

    # Handle array types: int arr[5] or int nums[]
    if node.type and node.type.is_array:
        from .array_variables import lower_array_var_decl

        result = lower_array_var_decl(gen, node, _storage_metadata(node))
        gen._fn_ptr_envs.pop(node.name, None)
        return result

    c_type = type_to_c(node.type) if node.type else "int"
    init = None
    if node.initializer:
        from ...ast_nodes import ListLiteral, MapLiteral

        ct = gen.analyzed.class_table
        # Empty brace initializer on generic class types -> TYPE_new()
        if (
            (
                isinstance(node.initializer, BraceInitializer)
                and not node.initializer.elements
                and node.type
                and is_generic_class_type(node.type, ct)
            )
            or (
                isinstance(node.initializer, ListLiteral)
                and not node.initializer.elements
                and node.type
                and is_generic_class_type(node.type, ct)
            )
            or (
                isinstance(node.initializer, MapLiteral)
                and not node.initializer.entries
                and node.type
                and is_generic_class_type(node.type, ct)
            )
        ):
            mangled = mangle_generic_type(node.type.base, node.type.generic_args)
            init = IRCall(callee=f"{mangled}_new", args=[])
        else:
            if node.type and node.type.is_static:
                from .aggregate_initializers import lower_static_initializer

                init = lower_static_initializer(gen, node.initializer)
            else:
                init = lower_expr(gen, node.initializer)
            init_type = gen.analyzed.node_types.get(id(node.initializer))
            init = coerce_value_to_string(gen, node.type, init_type, init)

        # Upcast: storing a subclass instance in a base-class variable needs an
        # explicit cast — sibling struct pointers are otherwise incompatible C.
        if node.type:
            from .upcast import upcast_class_pointer

            init_type = gen.analyzed.node_types.get(id(node.initializer))
            init = upcast_class_pointer(gen, node.type, init_type, init)
    var_decl = IRVarDecl(
        c_type=CType(text=c_type),
        name=node.name,
        init=init,
        **_storage_metadata(node),
    )
    gen._func_var_decls.append(var_decl)
    result = [var_decl]
    # Every declaration shadows an outer closure binding.  Install a new
    # environment mapping below only when this initializer is itself a
    # capturing lambda.
    gen._fn_ptr_envs.pop(node.name, None)

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
        var_decl.init = IRCast(
            target_type=CType(text=c_type),
            expr=IRVar(name=fn_name),
        )
        result.append(
            IRVarDecl(
                c_type=CType(text=f"struct {env_struct}"),
                name=env_var,
            )
        )
        for cap in node.initializer.captures:
            result.append(
                IRAssign(
                    target=IRFieldAccess(obj=IRVar(name=env_var), field=cap.name, arrow=False),
                    value=IRVar(name=cap.name),
                )
            )
        # Track: variable → (lambda fn name, env var name)
        gen._fn_ptr_envs[node.name] = (fn_name, env_var)

    # ARC: every initialized concrete managed local owns its slot. A caller-owned
    # +1 initializer transfers directly; a borrowed parameter/field/property is
    # retained once before any source owner can be replaced.  delete/release
    # null the slot, so later scope cleanup remains safe.
    if node.initializer and node.type and _is_managed_type(gen, node.type):
        from .managed_values import (
            is_string_type,
            retain_value,
            runtime_name,
        )
        from .ownership import owns_result

        cls_info = gen.analyzed.class_table.get(node.type.base)
        concrete = is_string_type(gen, node.type) or bool(
            cls_info and (not cls_info.generic_params or node.type.generic_args)
        )

        if concrete:
            arc_type = runtime_name(gen, node.type)
            owns_initializer = owns_result(gen, node.initializer)
            if not owns_initializer:
                result.append(IRExprStmt(expr=retain_value(gen, IRVar(name=node.name), node.type)))
            gen.register_managed_var(
                node.name,
                arc_type,
                cycle_seed=bool(owns_initializer and not is_string_type(gen, node.type)),
            )
            gen.declare_local_ownership(node.name, arc_type)
            _maybe_register_cleanup(gen, node.name, arc_type, result)

    canonical_type_expr = canonical_type(
        node.type,
        gen.analyzed.typedef_table,
    )
    if (
        node.initializer
        and canonical_type_expr
        and canonical_type_expr.base == "Thread"
        and canonical_type_expr.generic_args
    ):
        gen.register_thread_var(node.name)
        gen.use_helper("__btrc_thread_free")
        _maybe_register_direct_cleanup(
            gen,
            node.name,
            "__btrc_thread_free",
            result,
        )

    return result


def _storage_metadata(node: VarDeclStmt) -> dict[str, bool]:
    type_expr = node.type
    return {
        "is_static": bool(getattr(type_expr, "is_static", False)),
        "is_extern": bool(getattr(type_expr, "is_extern", False)),
        "is_volatile": bool(getattr(type_expr, "is_volatile", False)),
    }


def _managed_type_name(gen: IRGenerator, type_expr) -> str:
    """Get the correct type name for managed var tracking (mangled for generics)."""
    from .types import is_generic_class_type, mangle_generic_type

    ct = gen.analyzed.class_table
    if type_expr.generic_args and is_generic_class_type(type_expr, ct):
        return mangle_generic_type(type_expr.base, type_expr.generic_args)
    return type_expr.base


def _is_managed_type(gen: IRGenerator, type_expr) -> bool:
    from .managed_values import is_managed_type

    return is_managed_type(gen, type_expr)
