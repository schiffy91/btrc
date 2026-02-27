"""Registry of C runtime helper functions emitted by the btrc code generator.

Each helper is stored as a :class:`HelperDef` containing the exact C source text
that codegen produces (via ``_emit``) and an optional list of helpers it depends on.

Helpers are grouped into categories that mirror the emission order in
``CodeGen._emit_header`` and related methods.

**Note:** Collection helpers (List, Map, Set functional methods) are *templates* --
their C source contains ``{name}`` / ``{c_type}`` / etc. placeholders that must be
filled in with ``.format(...)`` for each monomorphised type.
"""

from .alloc import ALLOC
from .collections import COLLECTIONS
from .core import HelperDef
from .divmod import DIVMOD
from .hash import HASH
from .math import MATH
from .string_pool import STRING_POOL
from .strings import STRING
from .trycatch import TRYCATCH

HELPERS: dict[str, dict[str, HelperDef]] = {
    "alloc": ALLOC,
    "divmod": DIVMOD,
    "string_pool": STRING_POOL,
    "string": STRING,
    "math": MATH,
    "trycatch": TRYCATCH,
    "hash": HASH,
    "collections": COLLECTIONS,
}

__all__ = [
    "ALLOC",
    "COLLECTIONS",
    "DIVMOD",
    "HASH",
    "HELPERS",
    "HelperDef",
    "MATH",
    "STRING",
    "STRING_POOL",
    "TRYCATCH",
]
