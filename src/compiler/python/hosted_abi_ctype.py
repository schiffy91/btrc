"""Owned names and exact ABI specs from ``ctype.h``."""

from .hosted_abi_model import INT, VALUE, HostedFunction, abi_type, function

HOSTED_CTYPE_NAMES = frozenset(
    [
        "isalnum",
        "isalpha",
        "isblank",
        "iscntrl",
        "isdigit",
        "isgraph",
        "islower",
        "isprint",
        "ispunct",
        "isspace",
        "isupper",
        "isxdigit",
        "tolower",
        "toupper",
    ]
)
_CONVERSIONS = frozenset({"tolower", "toupper"})
HOSTED_CTYPE_FUNCTIONS: dict[str, HostedFunction] = {
    name: function(
        INT,
        INT,
        effects=(VALUE,),
        semantic_result=None if name in _CONVERSIONS else abi_type("bool"),
    )
    for name in HOSTED_CTYPE_NAMES
}

__all__ = ["HOSTED_CTYPE_FUNCTIONS", "HOSTED_CTYPE_NAMES"]
