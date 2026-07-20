"""Resolved call parameters with target-owned default substitutions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedCallParameter:
    name: str
    type: object
    default: object | None
    keep: bool
    default_type_map: dict[str, object]


def resolved_parameter(param, resolved_type, substitutions=None):
    return ResolvedCallParameter(
        name=param.name,
        type=resolved_type,
        default=param.default,
        keep=param.keep,
        default_type_map=dict(substitutions or {}),
    )


__all__ = ["ResolvedCallParameter", "resolved_parameter"]
