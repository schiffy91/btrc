"""Single-evaluation boundaries for expressions consuming owned operands."""

from __future__ import annotations

from .call_boundary import CallOperand, sequence_call_boundary
from .ownership import owns_result
from .types import type_to_c


def sequence_owned_operands(
    gen,
    nodes,
    *,
    build,
    result_type,
    promote_result: bool = False,
):
    """Evaluate source operands once and consume each caller-owned value.

    Returns ``None`` when no operand owns a reference, letting callers keep a
    minimal direct IR shape. When any operand is owned, every operand is
    hoisted so source evaluation order remains deterministic.
    """
    specs = []
    any_owned = False
    for node in nodes:
        type_expr = gen.analyzed.node_types.get(id(node))
        # An enclosing boundary owns and will consume an installed override.
        # Nested field/index/lvalue lowering must treat that stabilized slot as
        # borrowed or it would wrap an assignable projection in a non-lvalue
        # statement expression and release the same reference twice.
        owned = bool(id(node) not in gen._owning_temp_overrides and owns_result(gen, node))
        any_owned = any_owned or owned
        specs.append((node, type_expr, owned))
    if not any_owned:
        return None
    if any(type_expr is None for _node, type_expr, _owned in specs):
        from .errors import CodegenError

        raise CodegenError("owned expression sequencing requires concrete analyzed operand types")

    operands = [
        CallOperand(
            node=node,
            type_expr=type_expr,
            c_type=type_to_c(type_expr),
            owned=owned,
        )
        for node, type_expr, owned in specs
    ]

    def build_with_overrides(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            return build()
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    from .expressions import lower_expr

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=lambda node: lower_expr(gen, node),
        build_call=build_with_overrides,
        result_c_type=(type_to_c(result_type) if result_type is not None else None),
        result_type=result_type,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
        promote_result=promote_result,
    )


__all__ = ["sequence_owned_operands"]
