"""Registry of all runtime helper categories, aggregated into a single HELPERS dict."""

from .alloc import ALLOC
from .collections import COLLECTIONS
from .core import HelperDef
from .cycles import CYCLES
from .divmod import DIVMOD
from .hash import HASH
from .math import MATH
from .string_pool import STRING_POOL
from .strings import STRING
from .threads import THREADS
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
    "cycles": CYCLES,
    "threads": THREADS,
}

__all__ = [
    "ALLOC",
    "COLLECTIONS",
    "CYCLES",
    "DIVMOD",
    "HASH",
    "HELPERS",
    "MATH",
    "STRING",
    "STRING_POOL",
    "THREADS",
    "TRYCATCH",
    "HelperDef",
]
