"""Durable public API for the Python reference compiler.

The API resolves on first use, so a tool that imports one leaf module (the
native plan builder needs only the artifact publisher and the header reader)
does not load the whole compiler first.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application.compiler import Compiler
    from .application.results import CompilerOptions, CompilerResult

__all__ = ("Compiler", "CompilerOptions", "CompilerResult")

_OWNERS = {
    "Compiler": ".application.compiler",
    "CompilerOptions": ".application.results",
    "CompilerResult": ".application.results",
}


def __getattr__(name: str) -> object:
    owner = _OWNERS.get(name)
    if owner is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(owner, __name__), name)
    globals()[name] = value
    return value
