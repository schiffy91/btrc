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


__all__ = ["missing_default_target", "missing_operand_type"]
