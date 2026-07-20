"""Managed-return callable provenance inside generic specializations."""

from __future__ import annotations

from ..callable_provenance import (
    AMBIGUOUS_RETURN,
    BORROWED_RETURN,
    OWNED_RETURN,
    begin_callable_scope,
    begin_exceptional_callable_capture,
    finish_callable_scope,
    finish_exceptional_callable_capture,
    join_callable_flows,
    join_return_abis,
    lower_isolated_callable_flow,
    restore_callable_flow,
    snapshot_callable_flow,
)


def reset_generic_callable_state(emitter) -> None:
    """Reset the callable ABI lattice at one generated function boundary."""
    emitter._callable_return_abis = {}
    emitter._callable_types = {}
    emitter._callable_scope_declarations = []
    emitter._callable_exception_captures = []
    emitter._callable_loop_captures = []
    emitter._callable_parameters_seeded = False


def seed_borrowed_callable_parameters(emitter) -> None:
    """Seed bare callback parameters with their C-compatible borrowed ABI."""
    if emitter._callable_parameters_seeded:
        return
    emitter._callable_parameters_seeded = True
    for name, type_expr in emitter._var_types.items():
        if _is_callable_type(emitter, type_expr):
            emitter._callable_types[name] = type_expr
            emitter._callable_return_abis[name] = BORROWED_RETURN


def generic_callable_return_abi(emitter, expression) -> str:
    """Return the proven managed-result ABI of a generic-scope callable."""
    from ....ast_nodes import (
        BinaryExpr,
        CastExpr,
        FieldAccessExpr,
        Identifier,
        LambdaExpr,
        TernaryExpr,
        UnaryExpr,
    )

    if isinstance(expression, LambdaExpr):
        return OWNED_RETURN
    if isinstance(expression, Identifier):
        lexical = emitter._callable_return_abis.get(expression.name)
        if lexical is not None:
            return lexical
        if expression.name in emitter._var_types:
            return BORROWED_RETURN
        declaration = emitter._gen.analyzed.function_table.get(expression.name)
        return OWNED_RETURN if declaration is not None and declaration.body is not None else BORROWED_RETURN
    if isinstance(expression, FieldAccessExpr):
        declaration = _source_static_method(emitter, expression)
        if declaration is not None and declaration.body is not None:
            return OWNED_RETURN
    if isinstance(expression, CastExpr):
        return generic_callable_return_abi(emitter, expression.expr)
    if isinstance(expression, UnaryExpr) and expression.op == "&":
        return generic_callable_return_abi(emitter, expression.operand)
    if isinstance(expression, TernaryExpr):
        return join_return_abis(
            generic_callable_return_abi(emitter, expression.true_expr),
            generic_callable_return_abi(emitter, expression.false_expr),
        )
    if isinstance(expression, BinaryExpr) and expression.op == "??":
        return join_return_abis(
            generic_callable_return_abi(emitter, expression.left),
            generic_callable_return_abi(emitter, expression.right),
        )
    return BORROWED_RETURN


def generic_known_language_call(emitter, expression) -> bool:
    """Whether a generic-body call returns through btrc's owned ABI."""
    from ....ast_nodes import FieldAccessExpr, Identifier, SelfExpr

    callee = expression.callee
    if isinstance(callee, Identifier) and id(expression) in emitter._gen.analyzed.hosted_call_ids:
        return False
    return_abi = generic_callable_return_abi(emitter, expression.callee)
    if return_abi == AMBIGUOUS_RETURN:
        from ..errors import CodegenError

        raise CodegenError(
            "Managed-return __fn_ptr call has ambiguous ownership ABI after "
            "control flow; keep source and foreign callbacks in separate bindings"
        )
    if return_abi == OWNED_RETURN:
        return True

    if isinstance(callee, Identifier):
        if callee.name in emitter._var_types:
            return False
        declaration = emitter._gen.analyzed.function_table.get(callee.name)
        return bool(
            (callee.name == "Mutex" and declaration is None)
            or callee.name in emitter._gen.analyzed.class_table
            or (declaration is not None and declaration.body is not None)
        )
    if not isinstance(callee, FieldAccessExpr):
        return False
    if isinstance(callee.obj, SelfExpr):
        return bool(emitter._cls_info and callee.field in emitter._cls_info.methods)
    receiver_type = emitter._resolve_expr_type(callee.obj)
    if receiver_type is not None and receiver_type.base == "Mutex":
        return callee.field == "get"
    class_info = emitter._gen.analyzed.class_table.get(receiver_type.base) if receiver_type is not None else None
    return bool(class_info and callee.field in class_info.methods)


def bind_generic_local_callable(emitter, name: str, type_expr, initializer) -> None:
    """Install a lexical declaration, including non-callable shadowing."""
    if emitter._callable_scope_declarations:
        emitter._callable_scope_declarations[-1].add(name)
    resolved = emitter._resolve(type_expr) if type_expr is not None else None
    if not _is_callable_type(emitter, resolved):
        emitter._callable_return_abis.pop(name, None)
        emitter._callable_types.pop(name, None)
        return
    emitter._callable_types[name] = resolved
    emitter._callable_return_abis[name] = (
        generic_callable_return_abi(emitter, initializer) if initializer is not None else BORROWED_RETURN
    )


def rebind_generic_local_callable(emitter, assignment) -> None:
    """Update provenance after a direct generic-scope callback assignment."""
    from ....ast_nodes import Identifier

    if assignment.op != "=" or not isinstance(assignment.target, Identifier):
        return
    name = assignment.target.name
    if name not in emitter._callable_return_abis:
        return
    if not _is_callable_type(emitter, emitter._resolve_expr_type(assignment.target)):
        return
    emitter._callable_return_abis[name] = generic_callable_return_abi(
        emitter,
        assignment.value,
    )
    record_generic_exceptional_callable_flow(emitter)


def reject_generic_erasing_callable_assignment(emitter, assignment) -> None:
    """Apply the shared persistent-callback contract in generic scope."""
    from ..callable_boundaries import reject_erasing_callable_assignment

    reject_erasing_callable_assignment(
        emitter._gen,
        assignment,
        type_of=emitter._resolve_expr_type,
        callable_abi=lambda value: generic_callable_return_abi(
            emitter,
            value,
        ),
        identifier_is_callable_local=lambda name: name in emitter._callable_return_abis,
        identifier_is_local=lambda name: name in emitter._var_types,
    )


def record_generic_exceptional_callable_flow(emitter) -> None:
    """Record every callback state a throw from the current region may expose."""
    current = emitter._callable_return_abis
    for names, states in emitter._callable_exception_captures:
        state = {name: current.get(name, BORROWED_RETURN) for name in names}
        if not states or states[-1] != state:
            states.append(state)


def _source_static_method(emitter, expression):
    from ....ast_nodes import Identifier

    if not isinstance(expression.obj, Identifier):
        return None
    if expression.obj.name in emitter._var_types:
        return None
    class_info = emitter._gen.analyzed.class_table.get(expression.obj.name)
    if class_info is None:
        return None
    declaration = class_info.methods.get(expression.field)
    if declaration is None or declaration.access != "class":
        return None
    return declaration


def _is_callable_type(emitter, type_expr) -> bool:
    if type_expr is None:
        return False
    from ..type_resolution import canonical_type

    resolved = canonical_type(type_expr, emitter._gen.analyzed.typedef_table)
    return bool(resolved is not None and resolved.base == "__fn_ptr")


__all__ = [
    "begin_callable_scope",
    "begin_exceptional_callable_capture",
    "bind_generic_local_callable",
    "finish_callable_scope",
    "finish_exceptional_callable_capture",
    "generic_callable_return_abi",
    "generic_known_language_call",
    "join_callable_flows",
    "lower_isolated_callable_flow",
    "rebind_generic_local_callable",
    "record_generic_exceptional_callable_flow",
    "reject_generic_erasing_callable_assignment",
    "reset_generic_callable_state",
    "restore_callable_flow",
    "seed_borrowed_callable_parameters",
    "snapshot_callable_flow",
]
