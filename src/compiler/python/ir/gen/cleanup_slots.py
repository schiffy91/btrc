"""Owned typed cleanup-slot registration and access-adapter emission."""

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
    IRModule,
    IRParam,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from .helpers import RuntimeHelperRegistry

_MANAGED_REGISTER = "__btrc_register_cleanup"
_DIRECT_REGISTER = "__btrc_register_direct_cleanup"


class CleanupSlotRegistry:
    """Own typed cleanup/access adapters for one generated translation unit."""

    def __init__(
        self,
        module: IRModule,
        helpers: RuntimeHelperRegistry,
    ) -> None:
        self.module = module
        self.helpers = helpers
        self._take_adapters: dict[str, str] = {}
        self._arc_slot_adapters: dict[str, str] = {}
        self._mutex_value_adapters: dict[str, str] = {}
        self._definitions: list[IRFunctionDef] = []
        self._finalized = False

    def register(
        self,
        declaration,
        cleanup_fn,
        *,
        visitor=None,
        direct: bool = False,
    ) -> IRCall:
        """Build a registration that clears a slot through its exact type."""
        if not isinstance(declaration, IRVarDecl):
            raise TypeError("cleanup registration requires its IRVarDecl")
        if declaration.is_static or declaration.is_extern or declaration.array_size is not None:
            raise ValueError(f"cleanup slot {declaration.name!r} must be an automatic pointer object")

        take_function = self._ensure_take_adapter(declaration.c_type)
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
        self.helpers.use(helper)
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

    def require_declaration(
        self,
        statements,
        name: str,
    ) -> IRVarDecl:
        """Resolve the innermost declaration preceding a registration."""
        for statement in reversed(statements):
            if isinstance(statement, IRVarDecl) and statement.name == name:
                return statement
        raise ValueError(f"cleanup registration for {name!r} has no preceding IRVarDecl")

    def finalize(self) -> None:
        """Place typed adapters before every function that references them."""
        if not self._definitions:
            return
        if self._finalized:
            raise ValueError("cleanup take adapters were finalized more than once")
        self.module.function_defs[0:0] = self._definitions
        self._finalized = True

    def ensure_arc_slot_adapter(self, slot_type: CType) -> str:
        """Return an exact-typed transactional callback for one ARC slot."""
        existing = self._arc_slot_adapters.get(slot_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_arc_slot_access_{len(self._arc_slot_adapters) + 1}"
        self._arc_slot_adapters[slot_type.text] = name
        self._definitions.append(self._delete_slot_adapter(name, slot_type))
        return name

    def ensure_mutex_value_adapter(self, value_type: CType) -> str:
        """Return an exact-typed load callback for opaque Mutex storage."""
        existing = self._mutex_value_adapters.get(value_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_mutex_value_access_{len(self._mutex_value_adapters) + 1}"
        self._mutex_value_adapters[value_type.text] = name
        self._definitions.append(self._mutex_value_adapter(name, value_type))
        return name

    def _ensure_take_adapter(self, slot_type: CType) -> str:
        existing = self._take_adapters.get(slot_type.text)
        if existing is not None:
            return existing
        name = f"__btrc_cleanup_take_{len(self._take_adapters) + 1}"
        self._take_adapters[slot_type.text] = name
        self._definitions.append(self._take_adapter(name, slot_type))
        return name

    def _take_adapter(
        self,
        name: str,
        slot_type: CType,
    ) -> IRFunctionDef:
        typed_slot_type = CType(text=f"{slot_type} volatile*")
        typed_slot = IRVar(name="typed_slot")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void*"),
            params=[IRParam(c_type=CType(text="void*"), name="raw_slot")],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=typed_slot_type,
                        name="typed_slot",
                        init=IRCast(
                            target_type=typed_slot_type,
                            expr=IRVar(name="raw_slot"),
                        ),
                    ),
                    IRVarDecl(
                        c_type=slot_type,
                        name="value",
                        init=IRDeref(expr=typed_slot),
                    ),
                    IRAssign(
                        target=IRDeref(expr=typed_slot),
                        value=IRLiteral(text="NULL"),
                    ),
                    IRReturn(
                        value=IRCast(
                            target_type=CType(text="void*"),
                            expr=IRVar(name="value"),
                        )
                    ),
                ]
            ),
            is_static=True,
        )

    def _delete_slot_adapter(
        self,
        name: str,
        slot_type: CType,
    ) -> IRFunctionDef:
        typed_slot_type = CType(text=f"{slot_type} volatile*")
        typed_slot = IRVar(name="typed_slot")
        current = IRVar(name="current")
        return IRFunctionDef(
            name=name,
            return_type=CType(text="void*"),
            params=[
                IRParam(c_type=CType(text="volatile void*"), name="raw_slot"),
                IRParam(c_type=CType(text="void*"), name="expected"),
                IRParam(c_type=CType(text="void*"), name="replacement"),
                IRParam(c_type=CType(text="int"), name="replace_if_equal"),
            ],
            body=IRBlock(
                stmts=[
                    IRVarDecl(
                        c_type=typed_slot_type,
                        name="typed_slot",
                        init=IRCast(
                            target_type=typed_slot_type,
                            expr=IRVar(name="raw_slot"),
                        ),
                    ),
                    IRVarDecl(
                        c_type=slot_type,
                        name="current",
                        init=IRDeref(expr=typed_slot),
                    ),
                    IRIf(
                        condition=IRBinOp(
                            left=IRVar(name="replace_if_equal"),
                            op="&&",
                            right=IRBinOp(
                                left=current,
                                op="==",
                                right=IRCast(
                                    target_type=slot_type,
                                    expr=IRVar(name="expected"),
                                ),
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
                    IRReturn(
                        value=IRCast(
                            target_type=CType(text="void*"),
                            expr=current,
                        )
                    ),
                ]
            ),
            is_static=True,
        )

    def _mutex_value_adapter(
        self,
        name: str,
        value_type: CType,
    ) -> IRFunctionDef:
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


__all__ = ["CleanupSlotRegistry"]
