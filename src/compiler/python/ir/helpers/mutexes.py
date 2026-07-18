"""Composed opaque ``Mutex<T>`` runtime helpers."""

from .mutex_arc import MUTEX_ARC
from .mutex_core import MUTEX_CORE
from .mutex_ops import MUTEX_OPS

MUTEXES = {
    **MUTEX_CORE,
    **MUTEX_ARC,
    **MUTEX_OPS,
}

__all__ = ["MUTEXES"]
