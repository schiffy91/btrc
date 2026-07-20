"""Declared scalar results for libc/POSIX calls accepted by btrc source."""

C_SCALAR_CALL_RESULTS = {
    "S_ISDIR": "bool",
    "S_ISLNK": "bool",
    "S_ISREG": "bool",
    "WEXITSTATUS": "int",
    "WIFEXITED": "bool",
    "WIFSIGNALED": "bool",
    "WTERMSIG": "int",
}

C_POINTER_CALL_RESULTS = {}

_C_PREDEFINED_STRING_IDENTIFIERS = frozenset({"__DATE__", "__FILE__", "__TIME__"})
_C_PREDEFINED_INT_IDENTIFIERS = frozenset({"__LINE__", "__STDC__", "__STDC_HOSTED__"})


def c_predefined_identifier_type(name: str) -> str | None:
    """Return the strict-C11 scalar type of a guaranteed predefined macro."""
    if name in _C_PREDEFINED_STRING_IDENTIFIERS:
        return "const char*"
    if name == "__STDC_VERSION__":
        return "long"
    if name in _C_PREDEFINED_INT_IDENTIFIERS:
        return "int"
    return None


def c_integer_identifier(name: str) -> bool:
    """Whether an identifier is accepted by the C integer-constant seam."""
    return name == "errno" or (name.isupper() and name != "NULL")


def c_opaque_value_identifier(name: str) -> bool:
    """Whether C, rather than btrc, determines an identifier's value type."""
    return name != "errno" and c_integer_identifier(name)
