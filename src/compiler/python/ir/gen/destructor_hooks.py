"""Hidden source-destructor hook construction."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFunctionDef,
    IRParam,
    IRVar,
    IRVarDecl,
)


def destructor_hook_name(owner_name: str) -> str:
    """Return the compiler-reserved hook symbol for one concrete class."""
    return f"__btrc_{owner_name}_destructor_hook"


def build_destructor_hook(
    owner_name: str,
    body: IRBlock,
) -> IRFunctionDef:
    """Build the isolated function containing a source ``__del__`` body."""
    return IRFunctionDef(
        name=destructor_hook_name(owner_name),
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
    )


def call_destructor_hook(owner_name: str) -> IRExprStmt:
    """Call one hidden hook from its compiler-owned terminal destructor."""
    return IRExprStmt(
        expr=IRCall(
            callee=destructor_hook_name(owner_name),
            args=[IRVar(name="self")],
        )
    )


__all__ = [
    "build_destructor_hook",
    "call_destructor_hook",
    "destructor_hook_name",
]
