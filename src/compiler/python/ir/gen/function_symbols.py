"""C symbols for source-defined top-level functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hosted_abi import source_hosted_function_symbol

if TYPE_CHECKING:
    from ...analyzer.core import AnalyzedProgram


def source_function_c_name(
    analyzed: AnalyzedProgram,
    name: str,
    call=None,
) -> str:
    """Return the C symbol for a resolved source function named ``name``.

    Foreign/body-less declarations retain their ABI spelling.  Only concrete
    source definitions that overlap a hosted-runtime seam are isolated behind
    the compiler-reserved namespace.
    """
    declaration = analyzed.function_table.get(name)
    if declaration is None or declaration.body is None or declaration.is_gpu:
        return name
    if call is not None and id(call) in analyzed.hosted_call_ids:
        return name
    return source_hosted_function_symbol(name)


__all__ = ["source_function_c_name"]
