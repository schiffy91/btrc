"""C symbols for source-defined top-level functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...analyzer.core import AnalyzedProgram


_SOURCE_SYMBOLS = {
    # ``printf`` is also a raw language builtin backed by <stdio.h>.  A source
    # definition must not redeclare libc's incompatible variadic prototype.
    "printf": "__btrc_source_printf",
}


def source_function_c_name(analyzed: AnalyzedProgram, name: str) -> str:
    """Return the C symbol for a resolved source function named ``name``.

    Foreign/body-less declarations retain their ABI spelling.  Only concrete
    source definitions that overlap a hosted-runtime seam are isolated behind
    the compiler-reserved namespace.
    """
    declaration = analyzed.function_table.get(name)
    if declaration is None or declaration.body is None or declaration.is_gpu:
        return name
    return _SOURCE_SYMBOLS.get(name, name)


__all__ = ["source_function_c_name"]
