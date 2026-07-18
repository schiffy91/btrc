"""Variable declaration lowering and local ARC registration.

Handles ``var`` declarations, arrays, generic constructors, and ownership of
fresh or explicitly ownership-transferring initializers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import VarDeclStmt
from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRExprStmt,
    IRLiteral,
    IRSizeof,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .cleanup_registration import (
    maybe_register_cleanup as _maybe_register_cleanup,
)
from .cleanup_registration import (
    maybe_register_direct_cleanup as _maybe_register_direct_cleanup,
)
from .expressions import lower_expr
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
    external_declaration = bool(node.type and node.type.is_extern and node.initializer is None)

    # Handle array types: int arr[5] or int nums[]
    if node.type and node.type.is_array:
        from .array_variables import lower_array_var_decl

        result = lower_array_var_decl(gen, node, _storage_metadata(node))
        if external_declaration:
            result.append(_mark_external_declaration_used(node.name))
        gen._fn_ptr_envs.pop(node.name, None)
        return result

    c_type = type_to_c(node.type) if node.type else "int"
    init = None
    prepared = None
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
        if node.type and node.type.is_static:
            from .errors import CodegenError
            from .prepared_values import requires_string_conversion

            if requires_string_conversion(gen, node.type, init_type):
                raise CodegenError("static storage cannot use runtime class-to-string conversion")
        else:
            from .prepared_values import prepare_normal_value

            prepared = prepare_normal_value(
                gen,
                node.initializer,
                node.type,
                lowered=init,
            )
            init = prepared.value

        # Upcast: storing a subclass instance in a base-class variable needs an
        # explicit cast — sibling struct pointers are otherwise incompatible C.
        if node.type:
            from .upcast import upcast_class_pointer

            init_type = (
                prepared.effective_type if prepared is not None else gen.analyzed.node_types.get(id(node.initializer))
            )
            init = upcast_class_pointer(gen, node.type, init_type, init)
    concrete_managed = _is_concrete_managed_type(gen, node.type)
    if init is None and concrete_managed and not external_declaration:
        # An uninitialized managed declaration is still an owned lexical slot.
        # Start it empty so later replacement and exceptional cleanup are safe.
        init = IRLiteral(text="NULL")
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
    from .callable_provenance import bind_local_callable

    bind_local_callable(gen, node.name, node.type, node.initializer)
    if external_declaration:
        # GCC diagnoses an otherwise legal unused block-scope extern under
        # -Wunused-variable. Taking its address inside sizeof is an unevaluated,
        # portable use: it needs neither storage nor a link-time definition.
        result.append(_mark_external_declaration_used(node.name))
        return result

    # Lambda capture struct allocation: when var = lambda_with_captures,
    # allocate the capture struct on the stack and fill it with captured values.
    # The captured lambda's C function has an extra void* param and therefore
    # cannot inhabit the plain function-pointer typedef. Calls use the lifted
    # implementation plus environment directly; semantic analysis rejects
    # every escaping/non-call use of this closure-only binding.
    from ...ast_nodes import LambdaExpr

    if isinstance(node.initializer, LambdaExpr) and node.initializer.captures:
        from ..nodes import IRAssign, IRFieldAccess

        lambda_id = gen._last_lambda_id
        fn_name = f"__btrc_lambda_{lambda_id}"
        env_struct = f"__btrc_lambda_{lambda_id}_env"
        env_var = f"__{node.name}_env"
        result.pop()
        gen._func_var_decls.pop()
        env_decl = IRVarDecl(
            c_type=CType(text=f"struct {env_struct}"),
            name=env_var,
        )
        gen._func_var_decls.append(env_decl)
        result.append(env_decl)
        for cap in node.initializer.captures:
            result.append(
                IRAssign(
                    target=IRFieldAccess(obj=IRVar(name=env_var), field=cap.name, arrow=False),
                    value=IRVar(name=cap.name),
                )
            )
        # Track: variable → (lambda fn name, env var name)
        gen._fn_ptr_envs[node.name] = (fn_name, env_var)

    # A C-compatible raw pointer can still carry managed provenance (notably
    # ``char* value = __btrc_string_alloc(...)`` inside the stdlib). Preserve
    # that initializer domain so scope cleanup and return transfer stay exact.
    managed_slot_type = node.type if concrete_managed else None
    if (
        managed_slot_type is None
        and prepared is not None
        and prepared.owned
        and _is_managed_type(gen, prepared.effective_type)
    ):
        managed_slot_type = prepared.effective_type

    # Every managed declaration owns its slot. A caller-owned +1 initializer
    # transfers directly; a borrowed initializer is retained once.
    if managed_slot_type is not None:
        from .managed_values import (
            retain_value,
            runtime_name,
        )
        from .ownership import owns_result

        arc_type = runtime_name(gen, managed_slot_type)
        owns_initializer = bool(
            node.initializer and (prepared.owned if prepared is not None else owns_result(gen, node.initializer))
        )
        if node.initializer and not owns_initializer:
            result.append(IRExprStmt(expr=retain_value(gen, IRVar(name=node.name), managed_slot_type)))
        gen.register_managed_var(
            node.name,
            arc_type,
            cycle_seed=bool(owns_initializer and not _is_string_type(gen, node.type)),
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


def _mark_external_declaration_used(name: str) -> IRExprStmt:
    return IRExprStmt(expr=IRSizeof(operand=IRAddressOf(expr=IRVar(name=name))))


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


def _is_string_type(gen: IRGenerator, type_expr) -> bool:
    from .managed_values import is_string_type

    return is_string_type(gen, type_expr)


def _is_concrete_managed_type(gen: IRGenerator, type_expr) -> bool:
    concrete = canonical_type(type_expr, gen.analyzed.typedef_table)
    if concrete is None or not _is_managed_type(gen, concrete):
        return False
    if _is_string_type(gen, concrete):
        return True
    from .managed_values import is_mutex_type

    if is_mutex_type(gen, concrete):
        return True
    class_info = gen.analyzed.class_table.get(concrete.base)
    return bool(class_info and (not class_info.generic_params or concrete.generic_args))
