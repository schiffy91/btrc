"""Type utilities for IR generation: btrc TypeExpr → C type string."""

from __future__ import annotations

from ...ast_nodes import TypeExpr


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

# Built-in generic collection types
_BUILTIN_GENERICS = {"List", "Map", "Set"}


def type_to_c(t: TypeExpr | None) -> str:
    """Convert a btrc TypeExpr to a C type string."""
    if t is None:
        return "void"
    base = t.base

    # Function pointer types: __fn_ptr(ret, param1, param2, ...) → typedef name
    if base == "__fn_ptr" and t.generic_args:
        return fn_ptr_typedef_name(t)

    # Const qualifier prefix
    prefix = "const " if getattr(t, 'is_const', False) else ""

    # Primitives
    if base in _PRIMITIVE_MAP and not t.generic_args:
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

    # Apply pointer depth
    c += "*" * t.pointer_depth

    # Array types
    if t.is_array:
        c += "*"

    return prefix + c


# Track emitted function pointer typedefs (mangled_name → typedef text)
_fn_ptr_typedefs: dict[str, str] = {}


def fn_ptr_typedef_name(t: TypeExpr) -> str:
    """Get/create a typedef name for a function pointer type."""
    ret_type = type_to_c(t.generic_args[0]) if t.generic_args else "void"
    param_types = [type_to_c(a) for a in t.generic_args[1:]]
    # Mangle: __btrc_fn_int_int
    parts = [mangle_type_name(a) for a in t.generic_args]
    mangled = f"__btrc_fn_{'_'.join(parts)}"
    if mangled not in _fn_ptr_typedefs:
        params_str = ", ".join(param_types) if param_types else "void"
        _fn_ptr_typedefs[mangled] = (
            f"typedef {ret_type} (*{mangled})({params_str});")
    return mangled


def get_fn_ptr_typedefs() -> list[str]:
    """Return all accumulated function pointer typedef strings and clear the cache."""
    result = list(_fn_ptr_typedefs.values())
    _fn_ptr_typedefs.clear()
    return result


def mangle_generic_type(base: str, args: list[TypeExpr]) -> str:
    """Mangle a generic type to a C-safe name: List<int> → btrc_List_int."""
    parts = [mangle_type_name(a) for a in args]
    return f"btrc_{base}_{'_'.join(parts)}"


def mangle_type_name(t: TypeExpr) -> str:
    """Mangle a single type for use in C identifiers."""
    if t.generic_args:
        inner = "_".join(mangle_type_name(a) for a in t.generic_args)
        return f"{t.base}_{inner}"
    base = t.base
    # Normalize string → str for mangling
    if base == "string":
        return "string"
    if base in _PRIMITIVE_MAP:
        return base
    return base


def mangle_tuple_type(t: TypeExpr) -> str:
    """Mangle a tuple type: (int, string) → btrc_Tuple_int_string."""
    if t.generic_args:
        parts = [mangle_type_name(a) for a in t.generic_args]
        return f"btrc_Tuple_{'_'.join(parts)}"
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
    """Check if a type is a string type."""
    if t is None:
        return False
    return t.base == "string" and not t.generic_args and t.pointer_depth == 0


def is_numeric_type(t: TypeExpr | None) -> bool:
    """Check if a type is numeric."""
    if t is None:
        return False
    return t.base in {"int", "float", "double", "long", "short", "byte", "uint"}


def is_collection_type(t: TypeExpr | None) -> bool:
    """Check if a type is a built-in collection (List, Map, Set).

    DEPRECATED: Use is_generic_class_type() with class_table instead.
    """
    if t is None:
        return False
    return t.base in _BUILTIN_GENERICS and bool(t.generic_args)


def is_generic_class_type(t: TypeExpr | None, class_table: dict) -> bool:
    """Check if a type is a generic class (registered with generic_params)."""
    if t is None or not t.generic_args:
        return False
    info = class_table.get(t.base)
    return info is not None and bool(info.generic_params)


def is_concrete_type(t: TypeExpr) -> bool:
    """Check if a type is fully resolved (no unresolved generic params like T, K, V)."""
    base = t.base
    if base in _PRIMITIVE_MAP or base in _BUILTIN_GENERICS:
        # These are known types
        pass
    elif len(base) == 1 and base.isupper():
        # Single uppercase letter → likely a type parameter
        return False
    # Check generic args recursively
    for arg in t.generic_args:
        if not is_concrete_type(arg):
            return False
    return True


def is_concrete_instance(args: tuple) -> bool:
    """Check if a generic instance tuple has all concrete types."""
    return all(is_concrete_type(a) for a in args)


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
    if t.pointer_depth > 0:
        return "%s"  # Any pointer (char*, etc.) → %s
    if base in ("int", "short", "byte", "uint"):
        return "%d"
    if base == "long":
        return "%ld"
    if base in ("float", "double"):
        return "%f"
    if base == "char":
        return "%c"
    if base == "string":
        return "%s"
    if base == "bool":
        return "%s"  # Needs special handling: val ? "true" : "false"
    return "%d"  # Default to %d for unknown types
