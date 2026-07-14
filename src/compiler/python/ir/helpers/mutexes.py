"""Composed opaque ``Mutex<T>`` runtime helpers."""

from .mutex_core import MUTEX_CORE
from .mutex_ops import MUTEX_OPS
from .mutex_owner import MUTEX_OWNER

MUTEXES = {
    **MUTEX_CORE,
    **MUTEX_OPS,
    **MUTEX_OWNER,
}

__all__ = ["MUTEXES"]
