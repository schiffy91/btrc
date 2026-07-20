"""Hidden source-destructor hook construction."""

from __future__ import annotations

from ...destructor_symbols import destructor_hook_symbol
from ..nodes import (
    CType,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFunctionDef,
    IRParam,
    IRVar,
    IRVarDecl,
)


def build_destructor_hook(
    owner_name: str,
    body: IRBlock,
) -> IRFunctionDef:
    """Build the isolated function containing a source ``__del__`` body."""
    return IRFunctionDef(
        name=destructor_hook_symbol(owner_name),
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text="void*"), name="object")],
        body=IRBlock(
            stmts=[
                IRVarDecl(
                    c_type=CType(text=f"{owner_name}*"),
                    name="self",
                    init=IRCast(
                        target_type=CType(text=f"{owner_name}*"),
                        expr=IRVar(name="object"),
                    ),
                ),
                IRExprStmt(
                    expr=IRCast(
                        target_type=CType(text="void"),
                        expr=IRVar(name="self"),
                    )
                ),
                *body.stmts,
            ]
        ),
        is_static=True,
        archive_export=True,
    )


__all__ = [
    "build_destructor_hook",
]
