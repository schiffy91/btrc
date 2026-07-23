"""Typed cleanup-slot registration and take-and-clear adapters."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRDeref,
    IRFunctionDef,
    IRFunctionRef,
    IRIf,
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
    gen.helpers.use(helper)
    args = [
        IRCast(
            target_type=CType(text="void*"),
            expr=IRAddressOf(expr=IRVar(name=declaration.name)),
        ),
        IRFunctionRef(name=take_function),
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
    adapters = _adapter_registry(gen, "_cleanup_take_adapters")
    existing = adapters.get(slot_type.text)
    if existing is not None:
        return existing
    name = f"__btrc_cleanup_take_{len(adapters) + 1}"
    adapters[slot_type.text] = name
    _adapter_definitions(gen).append(_take_adapter(name, slot_type))
    return name


def ensure_arc_slot_adapter(gen, slot_type: CType) -> str:
    """Return an exact-typed transactional access callback for one ARC slot."""

    adapters = _adapter_registry(gen, "_arc_slot_adapters")
    existing = adapters.get(slot_type.text)
    if existing is not None:
        return existing
    name = f"__btrc_arc_slot_access_{len(adapters) + 1}"
    adapters[slot_type.text] = name
    _adapter_definitions(gen).append(_delete_slot_adapter(name, slot_type))
    return name


def ensure_mutex_value_adapter(gen, value_type: CType) -> str:
    """Return an exact-typed load callback for opaque Mutex box storage."""

    adapters = _adapter_registry(gen, "_mutex_value_adapters")
    existing = adapters.get(value_type.text)
    if existing is not None:
        return existing
    name = f"__btrc_mutex_value_access_{len(adapters) + 1}"
    adapters[value_type.text] = name
    _adapter_definitions(gen).append(_mutex_value_adapter(name, value_type))
    return name


def _adapter_registry(gen, attribute: str) -> dict[str, str]:
    registry = getattr(gen, attribute, None)
    if registry is None:
        registry = {}
        setattr(gen, attribute, registry)
    return registry


def _adapter_definitions(gen) -> list[IRFunctionDef]:
    definitions = getattr(gen, "_cleanup_take_adapter_defs", None)
    if definitions is None:
        definitions = []
        gen._cleanup_take_adapter_defs = definitions
    return definitions


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


def _delete_slot_adapter(name: str, slot_type: CType) -> IRFunctionDef:
    typed_slot_type = CType(text=f"{slot_type} volatile*")
    raw_name = "raw_slot"
    expected_name = "expected"
    typed_name = "typed_slot"
    current_name = "current"
    typed_slot = IRVar(name=typed_name)
    current = IRVar(name=current_name)
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void*"),
        params=[
            IRParam(c_type=CType(text="volatile void*"), name=raw_name),
            IRParam(c_type=CType(text="void*"), name=expected_name),
            IRParam(c_type=CType(text="void*"), name="replacement"),
            IRParam(c_type=CType(text="int"), name="replace_if_equal"),
        ],
        body=IRBlock(
            stmts=[
                IRVarDecl(
                    c_type=typed_slot_type,
                    name=typed_name,
                    init=IRCast(target_type=typed_slot_type, expr=IRVar(name=raw_name)),
                ),
                IRVarDecl(c_type=slot_type, name=current_name, init=IRDeref(expr=typed_slot)),
                IRIf(
                    condition=IRBinOp(
                        left=IRVar(name="replace_if_equal"),
                        op="&&",
                        right=IRBinOp(
                            left=current,
                            op="==",
                            right=IRCast(target_type=slot_type, expr=IRVar(name=expected_name)),
                        ),
                    ),
                    then_block=IRBlock(
                        stmts=[
                            IRAssign(
                                target=IRDeref(expr=typed_slot),
                                value=IRCast(
                                    target_type=slot_type,
                                    expr=IRVar(name="replacement"),
                                ),
                            )
                        ]
                    ),
                ),
                IRReturn(value=IRCast(target_type=CType(text="void*"), expr=current)),
            ]
        ),
        is_static=True,
    )


def _mutex_value_adapter(name: str, value_type: CType) -> IRFunctionDef:
    storage_type = CType(text=f"{value_type} const*")
    return IRFunctionDef(
        name=name,
        return_type=CType(text="void*"),
        params=[IRParam(c_type=CType(text="const void*"), name="raw_storage")],
        body=IRBlock(
            stmts=[
                IRReturn(
                    value=IRCast(
                        target_type=CType(text="void*"),
                        expr=IRDeref(
                            expr=IRCast(
                                target_type=storage_type,
                                expr=IRVar(name="raw_storage"),
                            )
                        ),
                    )
                )
            ]
        ),
        is_static=True,
    )


__all__ = [
    "ensure_arc_slot_adapter",
    "ensure_mutex_value_adapter",
    "finalize_cleanup_take_adapters",
    "register_cleanup_slot",
    "require_cleanup_slot_declaration",
]
