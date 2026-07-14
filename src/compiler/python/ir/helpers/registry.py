"""Registry of all runtime helper categories, aggregated into a single HELPERS dict."""

from .alloc import ALLOC
from .collections import COLLECTIONS
from .core import HelperDef
from .cycles import CYCLES
from .divmod import DIVMOD
from .gpu import GPU
from .hash import HASH
from .math import MATH
from .string_ownership import STRING_OWNERSHIP
from .string_pool import STRING_POOL
from .strings import STRING
from .threads import THREADS
from .trycatch import TRYCATCH

HELPERS: dict[str, dict[str, HelperDef]] = {
    "alloc": ALLOC,
    "divmod": DIVMOD,
    "gpu": GPU,
    "string_ownership": STRING_OWNERSHIP,
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
    "GPU",
    "HASH",
    "HELPERS",
    "MATH",
    "STRING",
    "STRING_OWNERSHIP",
    "STRING_POOL",
    "THREADS",
    "TRYCATCH",
    "HelperDef",
]
