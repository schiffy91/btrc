"""Type utilities for IR generation: btrc TypeExpr → C type string."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType

from ...ast_nodes import TypeExpr
from ...reference_semantics import is_c_string_pointer
from ...type_identity import (
    ensure_supported_generic_arguments,
    is_semantic_scalar_string,
    mangle_function_pointer_symbol,
    mangle_generic_symbol,
    type_symbol_component,
)
from ..nodes import CType, IRFunctionPointerTypedef

# Primitive btrc types → C type strings
_PRIMITIVE_MAP = {
    "int": "int",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "char": "char",
    "string": "char*",
    "void": "void",
    "long": "long",
    "short": "short",
    "byte": "unsigned char",
    "uint": "unsigned int",
    "size_t": "size_t",
}


def type_to_c(t: TypeExpr | None) -> str:
    """Convert a btrc TypeExpr to a C type string."""
    if t is None:
        return "void"
    base = t.base

    # Function pointer types: __fn_ptr(ret, param1, param2, ...) → typedef name
    if base == "__fn_ptr" and t.generic_args:
        return fn_ptr_typedef_name(t)

    # Const qualifier prefix
    prefix = "const " if getattr(t, "is_const", False) else ""

    # Thread<T> → __btrc_thread_t* (opaque handle, no class struct)
    if base == "Thread" and t.generic_args:
        c = "__btrc_thread_t*"

    # Mutex<T> → __btrc_mutex_val_t* (ARC-managed graph node)
    elif base == "Mutex" and t.generic_args:
        c = "__btrc_mutex_val_t*"

    # Primitives
    elif base in _PRIMITIVE_MAP and not t.generic_args:
        c = _PRIMITIVE_MAP[base]
    # Tuple types
    elif base == "Tuple" or base.startswith("("):
        c = mangle_tuple_type(t)
    # Generic types (List<int>, Map<string, int>, user generics)
    elif t.generic_args:
        c = mangle_generic_type(base, t.generic_args)
    else:
        # User-defined class/struct → pointer by convention
        c = base

    # Apply pointer depth. A nullable `?` contributes one pointer level so value
    # types can be boxed (int? → int*), but `string` is already a pointer
    # (char*), so a nullable string must collapse back to char* rather than
    # double-pointering to char** (which older compilers only warned about, but
    # gcc 15 rejects as an incompatible-pointer error).
    depth = t.pointer_depth
    if t.is_nullable and (c.endswith("*") or depth > 1):
        depth -= 1
    c += "*" * depth

    # Array types
    if t.is_array:
        c += "*"

    return prefix + c


# Function-pointer declarations belong to one translation unit. Context-local,
# immutable state keeps nested, async, and concurrent compilations isolated.
_FnPtrSignature = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class _FnPtrTypedefState:
    definitions: Mapping[str, _FnPtrSignature]
    emitted: frozenset[str]


_fn_ptr_typedefs: ContextVar[_FnPtrTypedefState | None] = ContextVar(
    "btrc_fn_ptr_typedefs",
    default=None,
)


def _empty_fn_ptr_state() -> _FnPtrTypedefState:
    return _FnPtrTypedefState(MappingProxyType({}), frozenset())


def _current_fn_ptr_state() -> _FnPtrTypedefState:
    return _fn_ptr_typedefs.get() or _empty_fn_ptr_state()


@contextmanager
def fn_ptr_typedef_scope() -> Iterator[None]:
    """Create and reliably tear down one translation unit's typedef registry."""
    token = _fn_ptr_typedefs.set(_empty_fn_ptr_state())
    try:
        yield
    finally:
        _fn_ptr_typedefs.reset(token)


def fn_ptr_typedef_name(t: TypeExpr) -> str:
    """Get/create a typedef name for a function pointer type."""
    ret_type = type_to_c(t.generic_args[0]) if t.generic_args else "void"
    param_types = [type_to_c(a) for a in t.generic_args[1:]]
    mangled = mangle_function_pointer_symbol(t.generic_args)
    state = _current_fn_ptr_state()
    if mangled not in state.definitions:
        definitions = dict(state.definitions)
        definitions[mangled] = (ret_type, tuple(param_types))
        _fn_ptr_typedefs.set(
            _FnPtrTypedefState(
                definitions=MappingProxyType(definitions),
                emitted=state.emitted,
            )
        )
    return mangled


def get_fn_ptr_typedefs() -> list[IRFunctionPointerTypedef]:
    """Return declarations not yet emitted in this translation unit."""
    state = _current_fn_ptr_state()
    result = [
        IRFunctionPointerTypedef(
            name=name,
            return_type=CType(text=return_type),
            param_types=[CType(text=parameter) for parameter in parameters],
        )
        for name, (return_type, parameters) in state.definitions.items()
        if name not in state.emitted
    ]
    _fn_ptr_typedefs.set(
        _FnPtrTypedefState(
            definitions=state.definitions,
            emitted=frozenset(state.definitions),
        )
    )
    return result


def reset_fn_ptr_typedefs() -> None:
    """Reset the function-pointer registry in the current execution context."""
    _fn_ptr_typedefs.set(_empty_fn_ptr_state())


def mangle_generic_type(base: str, args: list[TypeExpr]) -> str:
    """Mangle a generic type to a C-safe name: List<int> → btrc_List_int."""
    ensure_supported_generic_arguments(args)
    return mangle_generic_symbol(base, args)


def mangle_type_name(t: TypeExpr) -> str:
    """Mangle a single type for use in C identifiers."""
    return type_symbol_component(t)


def mangle_tuple_type(t: TypeExpr) -> str:
    """Mangle a tuple type: (int, string) → btrc_Tuple_int_string."""
    if t.generic_args:
        return mangle_generic_symbol("Tuple", t.generic_args)
    return "btrc_Tuple"


def is_pointer_type(t: TypeExpr | None) -> bool:
    """Check if a type is a pointer (class instance, pointer depth > 0)."""
    if t is None:
        return False
    if t.pointer_depth > 0:
        return True
    if t.base in _PRIMITIVE_MAP and not t.generic_args:
        return t.base == "string"
    # User classes and generic collections are heap-allocated (pointers)
    return t.base not in _PRIMITIVE_MAP or t.generic_args


def is_string_type(t: TypeExpr | None) -> bool:
    """Check for a semantic scalar string, excluding arrays/raw pointers."""
    return is_semantic_scalar_string(t)


def is_numeric_type(t: TypeExpr | None) -> bool:
    """Check if a type is numeric."""
    if t is None:
        return False
    return t.base in {"int", "float", "double", "long", "short", "byte", "uint"}


def is_generic_class_type(t: TypeExpr | None, class_table: dict) -> bool:
    """Check if a type is a generic class (registered with generic_params)."""
    if t is None or not t.generic_args:
        return False
    info = class_table.get(t.base)
    return info is not None and bool(info.generic_params)


def is_direct_generic_instance_reference(
    t: TypeExpr | None,
    class_table: dict,
) -> bool:
    """Whether ``t`` is one generic heap reference, not storage around it."""
    if not is_generic_class_type(t, class_table) or t.is_array:
        return False
    # Analyzer normalization upgrades class values from semantic depth 0 to C
    # reference depth 1.  A composed/raw pointer around that value is depth 2+.
    depth = t.pointer_depth - int(t.is_nullable and t.pointer_depth > 1)
    return depth <= 1


def element_type_c(t: TypeExpr) -> str:
    """Get the C type for a collection's element type."""
    if t.generic_args:
        return type_to_c(t.generic_args[0])
    return "void*"


def format_spec_for_type(t: TypeExpr | None) -> str:
    """Get printf format specifier for a type."""
    if t is None:
        return "%d"  # Default: most untracked expressions are int
    base = t.base
    if base == "__fn_ptr":
        return "%s"  # Rendered as a fixed token; never cast to void*.
    if is_string_type(t) or is_c_string_pointer(t):
        return "%s"
    if type_to_c(t).rstrip().endswith("*") or t.is_array:
        return "%p"
    if base in ("int", "short", "short int", "signed int", "signed short", "signed short int"):
        return "%d"
    if base in ("byte", "uint", "unsigned int", "unsigned short", "unsigned short int", "unsigned char"):
        return "%u"
    if base in ("long", "long int", "signed long", "signed long int"):
        return "%ld"
    if base in ("unsigned long", "unsigned long int"):
        return "%lu"
    if base in ("long long", "long long int", "signed long long", "signed long long int"):
        return "%lld"
    if base in ("unsigned long long", "unsigned long long int"):
        return "%llu"
    if base == "size_t":
        return "%zu"
    if base in ("float", "double"):
        return "%f"
    if base == "long double":
        return "%Lf"
    if base == "char":
        return "%c"
    if base == "bool":
        return "%s"  # Needs special handling: val ? "true" : "false"
    return "%d"  # Default to %d for unknown types
