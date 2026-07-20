"""Managed-return ABI provenance for source callable values."""

from __future__ import annotations

from ...ast_nodes import (
    CastExpr,
    FieldAccessExpr,
    Identifier,
    LambdaExpr,
    TernaryExpr,
    UnaryExpr,
)
from .type_resolution import canonical_type

BORROWED_RETURN = "borrowed"
OWNED_RETURN = "owned"
AMBIGUOUS_RETURN = "ambiguous"


def callable_return_abi(gen, expression) -> str:
    """Return the proven managed-return ABI for one callable expression."""
    if isinstance(expression, LambdaExpr):
        return OWNED_RETURN
    if isinstance(expression, Identifier):
        lexical = gen._callable_return_abis.get(expression.name)
        if lexical is not None:
            return lexical
        declaration = gen.analyzed.function_table.get(expression.name)
        if declaration is not None and declaration.body is not None:
            return OWNED_RETURN
        return BORROWED_RETURN
    if isinstance(expression, FieldAccessExpr):
        declaration = _source_static_method(gen, expression)
        if declaration is not None and declaration.body is not None:
            return OWNED_RETURN
    if isinstance(expression, CastExpr):
        return callable_return_abi(gen, expression.expr)
    if isinstance(expression, UnaryExpr) and expression.op == "&":
        return callable_return_abi(gen, expression.operand)
    if isinstance(expression, TernaryExpr):
        return join_return_abis(
            callable_return_abi(gen, expression.true_expr),
            callable_return_abi(gen, expression.false_expr),
        )
    return BORROWED_RETURN


def _source_static_method(gen, expression: FieldAccessExpr):
    """Resolve ``Class.method`` without treating instance projections as fnptrs."""
    receiver = expression.obj
    if not isinstance(receiver, Identifier):
        return None
    class_info = gen.analyzed.class_table.get(receiver.name)
    if class_info is None:
        return None
    declaration = class_info.methods.get(expression.field)
    if declaration is None or declaration.access != "class":
        return None
    return declaration


def callable_has_owned_return_abi(gen, expression) -> bool:
    """Whether a callable is proven to use btrc's caller-owned ABI."""
    return callable_return_abi(gen, expression) == OWNED_RETURN


def known_language_call(gen, expression) -> bool:
    """Whether a call is proven to use btrc's source-callable ABI."""
    callee = expression.callee
    if isinstance(callee, Identifier) and id(expression) in gen.analyzed.hosted_call_ids:
        return False
    return_abi = callable_return_abi(gen, expression.callee)
    if return_abi == AMBIGUOUS_RETURN:
        from .errors import CodegenError

        raise CodegenError(
            "Managed-return __fn_ptr call has ambiguous ownership ABI after "
            "control flow; keep source and foreign callbacks in separate bindings"
        )
    if return_abi == OWNED_RETURN:
        return True
    if isinstance(callee, Identifier):
        if gen.local_ownership_declared(callee.name):
            return False
        return (
            callee.name == "Mutex" and callee.name not in gen.analyzed.function_table
        ) or callee.name in gen.analyzed.class_table
    if not isinstance(callee, FieldAccessExpr):
        return False

    receiver = callee.obj
    if isinstance(receiver, Identifier):
        static_info = gen.analyzed.class_table.get(receiver.name)
        if static_info is not None:
            static_method = static_info.methods.get(callee.field)
            if static_method is not None:
                return bool(static_method.body is not None)
    receiver_type = gen.analyzed.node_types.get(id(receiver))
    if receiver_type is None:
        return False
    receiver_type = canonical_type(receiver_type, gen.analyzed.typedef_table)
    if receiver_type is None:
        return False
    if receiver_type.base == "Thread" and callee.field == "join":
        return True
    if receiver_type.base == "Mutex" and callee.field == "get":
        return True
    class_info = gen.analyzed.class_table.get(receiver_type.base)
    if class_info is not None and callee.field in class_info.methods:
        return True
    interface_info = getattr(gen.analyzed, "interface_table", {}).get(receiver_type.base)
    return bool(interface_info is not None and callee.field in interface_info.methods)


def bind_local_callable(gen, name: str, type_expr, initializer) -> None:
    """Install one lexical declaration, including non-callable shadowing."""
    if gen._callable_scope_declarations:
        gen._callable_scope_declarations[-1].add(name)
    resolved = canonical_type(type_expr, gen.analyzed.typedef_table)
    if resolved is None or resolved.base != "__fn_ptr":
        gen._callable_return_abis.pop(name, None)
        gen._callable_types.pop(name, None)
        return
    gen._callable_types[name] = resolved
    gen._callable_return_abis[name] = (
        callable_return_abi(gen, initializer) if initializer is not None else BORROWED_RETURN
    )


def bind_borrowed_callable(gen, name: str, type_expr) -> None:
    """Declare a C-compatible callback parameter with the borrowed ABI."""
    bind_local_callable(gen, name, type_expr, None)


def bind_callable_abi(gen, name: str, type_expr, return_abi: str) -> None:
    """Declare a callback whose ABI was preserved across a safe boundary."""
    bind_local_callable(gen, name, type_expr, None)
    resolved = canonical_type(type_expr, gen.analyzed.typedef_table)
    if resolved is not None and resolved.base == "__fn_ptr":
        gen._callable_return_abis[name] = return_abi


def declare_callable_shadow(gen, name: str) -> None:
    """Hide an outer callable behind a non-callable lexical binding."""
    if gen._callable_scope_declarations:
        gen._callable_scope_declarations[-1].add(name)
    gen._callable_return_abis.pop(name, None)
    gen._callable_types.pop(name, None)


def rebind_local_callable(gen, assignment) -> None:
    """Update provenance after a direct function-pointer assignment."""
    if assignment.op != "=" or not isinstance(assignment.target, Identifier):
        return
    if assignment.target.name not in gen._callable_return_abis:
        return
    target_type = gen.analyzed.node_types.get(id(assignment.target))
    resolved = canonical_type(target_type, gen.analyzed.typedef_table)
    if resolved is None or resolved.base != "__fn_ptr":
        return
    gen._callable_return_abis[assignment.target.name] = callable_return_abi(gen, assignment.value)
    _record_exceptional_callable_flow(gen)


def begin_exceptional_callable_capture(gen):
    """Capture outer callback states that a throw from this region may expose."""
    capture = (frozenset(gen._callable_return_abis), [])
    gen._callable_exception_captures.append(capture)
    _record_exceptional_callable_flow(gen)
    return capture


def finish_exceptional_callable_capture(gen, capture) -> list[dict[str, str]]:
    """Close the innermost exceptional-flow capture and return reached states."""
    if not gen._callable_exception_captures or gen._callable_exception_captures[-1] is not capture:
        raise RuntimeError("callable exceptional-flow captures must be properly nested")
    gen._callable_exception_captures.pop()
    return capture[1]


def _record_exceptional_callable_flow(gen) -> None:
    current = gen._callable_return_abis
    for names, states in gen._callable_exception_captures:
        state = {name: current.get(name, BORROWED_RETURN) for name in names}
        if not states or states[-1] != state:
            states.append(state)


def begin_callable_scope(gen):
    """Open a lexical scope and return its enclosing ABI state."""
    enclosing = (
        gen._callable_return_abis.copy(),
        gen._callable_types.copy(),
    )
    gen._callable_scope_declarations.append(set())
    return enclosing


def finish_callable_scope(gen, enclosing) -> None:
    """Drop inner declarations while preserving mutations of outer slots."""
    enclosing_abis, enclosing_types = enclosing
    declared = gen._callable_scope_declarations.pop()
    current = gen._callable_return_abis
    result = enclosing_abis.copy()
    for name in enclosing_abis.keys() - declared:
        result[name] = current.get(name, enclosing_abis[name])
    gen._callable_return_abis = result
    gen._callable_types = enclosing_types


def snapshot_callable_flow(gen) -> dict[str, str]:
    return gen._callable_return_abis.copy()


def restore_callable_flow(gen, state: dict[str, str]) -> None:
    gen._callable_return_abis = state.copy()


def join_callable_flows(gen, *states: dict[str, str]) -> None:
    """Install the conservative join of mutually exclusive control paths."""
    if not states:
        return
    keys = set().union(*(state.keys() for state in states))
    joined = {}
    for name in keys:
        values = {state.get(name, BORROWED_RETURN) for state in states}
        joined[name] = values.pop() if len(values) == 1 else AMBIGUOUS_RETURN
    gen._callable_return_abis = joined


def lower_isolated_callable_flow(gen, lower):
    """Lower one control path, returning its IR and abstract exit state."""
    incoming = snapshot_callable_flow(gen)
    try:
        lowered = lower()
        outgoing = snapshot_callable_flow(gen)
    finally:
        restore_callable_flow(gen, incoming)
    return lowered, outgoing


def join_return_abis(left: str, right: str) -> str:
    return left if left == right else AMBIGUOUS_RETURN


__all__ = [
    "AMBIGUOUS_RETURN",
    "BORROWED_RETURN",
    "OWNED_RETURN",
    "begin_callable_scope",
    "begin_exceptional_callable_capture",
    "bind_borrowed_callable",
    "bind_callable_abi",
    "bind_local_callable",
    "callable_has_owned_return_abi",
    "callable_return_abi",
    "declare_callable_shadow",
    "finish_callable_scope",
    "finish_exceptional_callable_capture",
    "join_callable_flows",
    "known_language_call",
    "lower_isolated_callable_flow",
    "rebind_local_callable",
    "restore_callable_flow",
    "snapshot_callable_flow",
]
