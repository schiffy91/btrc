"""Shared lowering for source parameters and object qualifiers."""

from ..nodes import CType, IRParam
from .types import type_to_c


def lower_source_param(parameter, render=type_to_c) -> IRParam:
    return IRParam(
        c_type=CType(text=render(parameter.type)),
        name=parameter.name,
        is_volatile=bool(parameter.type and parameter.type.is_volatile),
    )


__all__ = ["lower_source_param"]
