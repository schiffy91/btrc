"""Canonical recursive identity and symbol spelling for ``TypeExpr`` values."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from .ast_nodes import TypeExpr
from .type_composition import compose_type_expr, nullable_collapses_reference_layer

_SAFE_BASE = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
_RESERVED_PREFIX = "ZQ"
_FORBIDDEN_GENERIC_FLAGS = (
    ("is_const", "const"),
    ("is_static", "static"),
    ("is_extern", "extern"),
    ("is_volatile", "volatile"),
)


class TypeShapeError(ValueError):
    """A type shape cannot be represented as a coherent specialization."""

    def __init__(self, message: str, type_expr: TypeExpr | None = None):
        self.type_expr = type_expr
        super().__init__(message)


def type_shape_key(type_expr: TypeExpr) -> tuple:
    """Return the position-independent semantic identity of ``type_expr``."""
    return (
        type_expr.base,
        tuple(type_shape_key(arg) for arg in (type_expr.generic_args or [])),
        type_expr.pointer_depth,
        bool(type_expr.is_nullable),
        type_expr.nullable_outer_depth,
        bool(type_expr.is_array),
        bool(type_expr.is_const),
        bool(type_expr.is_static),
        bool(type_expr.is_extern),
        bool(type_expr.is_volatile),
    )


def generic_instance_key(base: str, args) -> tuple:
    """Canonical analyzer/IR key for one generic class specialization."""
    return base, tuple(type_shape_key(arg) for arg in args)


def type_references_names(type_expr: TypeExpr, names) -> bool:
    """Return whether a recursive type shape still names a type parameter."""
    names = frozenset(names)
    if type_expr.base in names:
        return True
    return any(type_references_names(argument, names) for argument in type_expr.generic_args or [])


def generic_argument_problem(type_expr: TypeExpr) -> tuple[str, TypeExpr] | None:
    """Return the first unsupported generic-argument modifier, recursively."""
    for attribute, spelling in _FORBIDDEN_GENERIC_FLAGS:
        if getattr(type_expr, attribute, False):
            return f"generic arguments cannot be {spelling}-qualified", type_expr
    for argument in type_expr.generic_args or []:
        problem = generic_argument_problem(argument)
        if problem is not None:
            return problem
    return None


def ensure_supported_generic_arguments(args) -> None:
    """Fail closed when codegen sees an analyzer-rejected generic argument."""
    for argument in args:
        problem = generic_argument_problem(argument)
        if problem is not None:
            message, bad_type = problem
            raise TypeShapeError(message, bad_type)


def substitute_type_expr(
    type_expr: TypeExpr | None,
    substitutions: dict[str, TypeExpr],
    *,
    reference_resolver: Callable[[TypeExpr], TypeExpr | None] | None = None,
) -> TypeExpr | None:
    """Substitute recursively, composing every representable shape modifier.

    ``reference_resolver`` makes typedefs transparent only for shape decisions.
    The returned value keeps the substitution's source spelling so emitted
    specialization identities remain stable.
    """
    if type_expr is None:
        return None
    if type_expr.base in substitutions and not type_expr.generic_args:
        resolved = substitutions[type_expr.base]
        reference_shape = reference_resolver(resolved) if reference_resolver else resolved
        reference_shape = reference_shape or resolved
        if type_expr.is_array and reference_shape.is_array:
            raise TypeShapeError(
                f"nested array composition for type parameter '{type_expr.base}' is not supported",
                type_expr,
            )
        return compose_type_expr(type_expr, resolved, reference_shape=reference_shape)
    if type_expr.generic_args:
        return replace(
            type_expr,
            generic_args=[
                substitute_type_expr(
                    argument,
                    substitutions,
                    reference_resolver=reference_resolver,
                )
                for argument in type_expr.generic_args
            ],
        )
    return type_expr


def is_semantic_scalar_string(type_expr: TypeExpr | None) -> bool:
    """True only for string values represented by one collapsed ``char*``."""
    if type_expr is None or type_expr.base != "string" or type_expr.generic_args or type_expr.is_array:
        return False
    depth = type_expr.pointer_depth
    if nullable_collapses_reference_layer(type_expr, base_is_reference=True):
        depth -= 1
    return depth == 0


def is_semantic_scalar_void(type_expr: TypeExpr | None) -> bool:
    """True only for the scalar ``void`` return domain, never ``void*``."""
    return bool(
        type_expr
        and type_expr.base == "void"
        and type_expr.pointer_depth == 0
        and not type_expr.is_array
        and not type_expr.generic_args
    )


def type_symbol_component(type_expr: TypeExpr) -> str:
    """Injective C-identifier component for one type."""
    legacy = _legacy_component(type_expr)
    return legacy if legacy is not None else _RESERVED_PREFIX + "t" + _encode_type(type_expr)


def mangle_generic_symbol(base: str, args) -> str:
    """Injective C symbol for a parameterized type, preserving safe legacy names.

    This primitive deliberately accepts qualified arguments: structural types
    such as ``Tuple<const int, int>`` and ``__fn_ptr<void, const int>`` can
    represent them coherently.  Class and method monomorphization entry points
    apply the stricter writable-specialization policy before calling it.
    """
    args = tuple(args)
    legacy_args = _legacy_sequence(args)
    if _safe_base(base) and legacy_args is not None:
        suffix = f"_{legacy_args}" if legacy_args else ""
        return f"btrc_{base}{suffix}"
    return "btrc_" + _RESERVED_PREFIX + "g" + _encode_name_and_types(base, args)


def mangle_method_instance_symbol(
    class_base: str,
    class_args,
    method_name: str,
    method_args,
) -> str:
    """Injective symbol for class- and method-level generic substitutions."""
    class_args = tuple(class_args)
    method_args = tuple(method_args)
    ensure_supported_generic_arguments((*class_args, *method_args))
    class_legacy = _legacy_sequence(class_args)
    method_legacy = _legacy_sequence(method_args)
    if _safe_base(class_base) and _safe_base(method_name) and class_legacy is not None and method_legacy is not None:
        class_part = class_base
        if class_args:
            class_part = f"btrc_{class_base}_{class_legacy}"
        method_part = f"_{method_name}"
        if method_legacy:
            method_part += f"_{method_legacy}"
        return class_part + method_part
    payload = _encode_name_and_types(class_base, class_args)
    payload += _field("m", method_name.encode("utf-8").hex())
    payload += _encode_types(method_args)
    return "btrc_" + _RESERVED_PREFIX + "m" + payload


def mangle_function_pointer_symbol(args) -> str:
    """Injective typedef name for a function-pointer signature."""
    args = tuple(args)
    legacy = _legacy_sequence(args)
    if legacy is not None:
        return f"__btrc_fn_{legacy}"
    return f"__btrc_fn_{_RESERVED_PREFIX}f{_encode_types(args)}"


def _safe_base(base: str) -> bool:
    return bool(_SAFE_BASE.fullmatch(base)) and not base.startswith(_RESERVED_PREFIX)


def _legacy_component(type_expr: TypeExpr) -> str | None:
    if (
        type_expr.generic_args
        or not _safe_base(type_expr.base)
        or type_expr.nullable_outer_depth
        or any(getattr(type_expr, flag, False) for flag, _spelling in _FORBIDDEN_GENERIC_FLAGS)
    ):
        return None
    suffix = f"_p{type_expr.pointer_depth}" if type_expr.pointer_depth else ""
    if type_expr.is_nullable:
        suffix += "_n"
    if type_expr.is_array:
        suffix += "_a"
    return type_expr.base + suffix


def _legacy_sequence(args) -> str | None:
    components = [_legacy_component(argument) for argument in args]
    if any(component is None for component in components):
        return None
    if len(args) > 1 and any(argument.pointer_depth or argument.is_nullable or argument.is_array for argument in args):
        return None
    return "_".join(components)


def _field(tag: str, text: str) -> str:
    return f"{tag}{len(text)}_{text}"


def _encode_type(type_expr: TypeExpr) -> str:
    base = type_expr.base.encode("utf-8").hex()
    qualifiers = sum(
        (1 << index) if getattr(type_expr, attribute, False) else 0
        for index, (attribute, _spelling) in enumerate(_FORBIDDEN_GENERIC_FLAGS)
    )
    shape = (
        f"p{type_expr.pointer_depth}n{int(type_expr.is_nullable)}"
        f"o{type_expr.nullable_outer_depth}a{int(type_expr.is_array)}q{qualifiers}"
    )
    return _field("b", base) + shape + _encode_types(type_expr.generic_args or [])


def _encode_types(args) -> str:
    encoded = [_encode_type(argument) for argument in args]
    return f"k{len(encoded)}" + "".join(_field("t", item) for item in encoded)


def _encode_name_and_types(base: str, args) -> str:
    return _field("b", base.encode("utf-8").hex()) + _encode_types(args)
