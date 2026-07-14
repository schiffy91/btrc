"""Typed cleanup-slot registration and take-and-clear adapters."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRDeref,
    IRFunctionDef,
    IRLiteral,
    IRParam,
    IRReturn,
    IRVar,
    IRVarDecl,
)

_MANAGED_REGISTER = "__btrc_register_cleanup"
_DIRECT_REGISTER = "__btrc_register_direct_cleanup"


def register_cleanup_slot(gen, declaration, cleanup_fn, *, visitor=None, direct=False) -> IRCall:
    """Build one registration whose runtime can clear the slot through its exact type."""

    if not isinstance(declaration, IRVarDecl):
        raise TypeError("cleanup registration requires its IRVarDecl")
    if declaration.is_static or declaration.is_extern or declaration.array_size is not None:
        raise ValueError(f"cleanup slot {declaration.name!r} must be an automatic pointer object")

    take_function = _ensure_take_adapter(gen, declaration.c_type)
    proposed = IRCleanupSlot(
        name=declaration.name,
        c_type=declaration.c_type,
        take_function=take_function,
    )
    metadata = declaration.cleanup_slot
    if metadata is not None and metadata != proposed:
        raise ValueError(f"cleanup slot {declaration.name!r} has conflicting typed metadata")
    if metadata is None:
        metadata = proposed
        declaration.cleanup_slot = metadata
    declaration.is_volatile = True

    helper = _DIRECT_REGISTER if direct else _MANAGED_REGISTER
    gen.use_helper(helper)
    args = [
        IRCast(
            target_type=CType(text="void*"),
            expr=IRAddressOf(expr=IRVar(name=declaration.name)),
        ),
        IRVar(name=take_function),
        cleanup_fn,
    ]
    if not direct:
        if visitor is None:
            raise ValueError("managed cleanup registration requires a visitor expression")
        args.append(visitor)
    return IRCall(
        callee=helper,
        args=args,
        helper_ref=helper,
        cleanup_slot=metadata,
    )


def require_cleanup_slot_declaration(statements, name: str) -> IRVarDecl:
    """Resolve the innermost declaration immediately preceding registration."""

    for statement in reversed(statements):
        if isinstance(statement, IRVarDecl) and statement.name == name:
            return statement
    raise ValueError(f"cleanup registration for {name!r} has no preceding IRVarDecl")


def finalize_cleanup_take_adapters(gen) -> None:
    """Place typed adapters before every function that can reference them."""

    definitions = getattr(gen, "_cleanup_take_adapter_defs", None)
    if not definitions:
        return
    if getattr(gen, "_cleanup_take_adapters_finalized", False):
        raise ValueError("cleanup take adapters were finalized more than once")
    gen.module.function_defs[0:0] = definitions
    gen._cleanup_take_adapters_finalized = True


def _ensure_take_adapter(gen, slot_type: CType) -> str:
    adapters = gen._cleanup_take_adapters
    existing = adapters.get(slot_type.text)
    if existing is not None:
        return existing
    name = f"__btrc_cleanup_take_{len(adapters) + 1}"
    adapters[slot_type.text] = name
    gen._cleanup_take_adapter_defs.append(_take_adapter(name, slot_type))
    return name


def _take_adapter(name: str, slot_type: CType) -> IRFunctionDef:
    typed_slot_type = CType(text=f"{slot_type} volatile*")
    raw_name = "raw_slot"
    typed_name = "typed_slot"
    value_name = "value"
    typed_slot = IRVar(name=typed_name)
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void*"),
        params=[IRParam(c_type=CType(text="void*"), name=raw_name)],
        body=IRBlock(
            stmts=[
                IRVarDecl(
                    c_type=typed_slot_type,
                    name=typed_name,
                    init=IRCast(
                        target_type=typed_slot_type,
                        expr=IRVar(name=raw_name),
                    ),
                ),
                IRVarDecl(
                    c_type=slot_type,
                    name=value_name,
                    init=IRDeref(expr=typed_slot),
                ),
                IRAssign(
                    target=IRDeref(expr=typed_slot),
                    value=IRLiteral(text="NULL"),
                ),
                IRReturn(
                    value=IRCast(
                        target_type=CType(text="void*"),
                        expr=IRVar(name=value_name),
                    )
                ),
            ]
        ),
        is_static=True,
    )


__all__ = [
    "finalize_cleanup_take_adapters",
    "register_cleanup_slot",
    "require_cleanup_slot_declaration",
]
