"""Fail-closed diagnostics for structured call-operand planning."""


def missing_operand_type(argument):
    from .evaluation_order import reject_opaque_ordering

    reject_opaque_ordering(
        argument,
        "call arguments",
        typed_declaration=True,
    )


def missing_default_target():
    from .errors import CodegenError

    raise CodegenError("default argument lowering requires a resolved call target")


def reject_opaque_result_cleanup(call):
    from .errors import CodegenError

    raise CodegenError(
        f"opaque C call result at {call.line}:{call.col} cannot cross an ownership cleanup boundary; "
        "provide a typed declaration or exact hosted ABI contract"
    )


__all__ = ["missing_default_target", "missing_operand_type", "reject_opaque_result_cleanup"]
