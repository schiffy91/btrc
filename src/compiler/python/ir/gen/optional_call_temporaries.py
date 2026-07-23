"""Temporary declarations used by lazy optional-call lowering."""

from ..nodes import CType, IRVarDecl


def optional_call_temp(gen, prefix: str, c_type: str, init=None) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=gen.fresh_temp(prefix),
        init=init,
    )
    gen.context.function_declarations.append(declaration)
    return declaration


__all__ = ["optional_call_temp"]
