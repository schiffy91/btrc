"""C and compiler-owned identifier namespaces used by declarations."""

from ...source_provenance import is_compiler_stdlib_source

C11_RESERVED_NAMES = frozenset(
    {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
        "_Alignas",
        "_Alignof",
        "_Atomic",
        "_Bool",
        "_Complex",
        "_Generic",
        "_Imaginary",
        "_Noreturn",
        "_Static_assert",
        "_Thread_local",
    }
)

_PUBLIC_NATIVE_BINDINGS = frozenset(
    {"btrc_gpu_available", "btrc_gui_surface_width", "btrc_tray_show"},
)
_COMPILER_RESERVED_PREFIXES = ("__btrc_", "__BTRC_", "__gpu_", "btrc_")


def compiler_reserved_prefix(name: str) -> str | None:
    return next(
        (prefix for prefix in _COMPILER_RESERVED_PREFIXES if name.startswith(prefix)),
        None,
    )


def c_reserved_identifier(name: str) -> bool:
    return name.startswith("__") or (len(name) > 1 and name[0] == "_" and "A" <= name[1] <= "Z")


def c_file_scope_reserved_identifier(name: str) -> bool:
    return name.startswith("_")


def trusted_native_binding(name: str, source_file: str | None) -> bool:
    return name in _PUBLIC_NATIVE_BINDINGS or is_compiler_stdlib_source(source_file)


__all__ = [
    "C11_RESERVED_NAMES",
    "c_file_scope_reserved_identifier",
    "c_reserved_identifier",
    "compiler_reserved_prefix",
    "trusted_native_binding",
]
