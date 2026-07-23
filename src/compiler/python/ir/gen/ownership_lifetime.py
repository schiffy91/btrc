"""Managed-value lifetime lowering for ownership boundaries."""

from __future__ import annotations

from typing import Protocol

from ...analyzer.core import AnalyzedProgram
from ..nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCommaExpr,
    IRCompoundLiteral,
    IRFunctionDef,
    IRFunctionRef,
    IRLiteral,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .helpers import RuntimeHelperRegistry
from .lowering_context import LoweringContext


class ArcLifetimeOwner(Protocol):
    """Explicit state and cleanup capabilities required by ARC lowering."""

    analyzed: AnalyzedProgram
    context: LoweringContext
    helpers: RuntimeHelperRegistry
    _cleanup_take_adapters: dict[str, str]
    _cleanup_take_adapter_defs: list[IRFunctionDef]

    def exception_cleanup_active(self) -> bool: ...

    def mark_cleanup_registration(self) -> None: ...


class ManagedLifetimeLowerer:
    """Lower retain, release, cleanup, and cycle-poll operations."""

    def __init__(self, owner: ArcLifetimeOwner, types) -> None:
        self.owner = owner
        self.analyzed = owner.analyzed
        self.context = owner.context
        self.helpers = owner.helpers
        self.types = types
        # Cleanup-slot IR primitives use these registries directly. Sharing
        # their data keeps every adapter in the composition root's one
        # finalization pass without routing behavior through the root.
        self._cleanup_take_adapters = owner._cleanup_take_adapters
        self._cleanup_take_adapter_defs = owner._cleanup_take_adapter_defs

    def is_managed_type(self, type_expr) -> bool:
        return self.types.is_managed(type_expr)

    def is_arc_type(self, type_expr) -> bool:
        return self.types.is_arc(type_expr)

    def cleanup_active(self) -> bool:
        return self.owner.exception_cleanup_active()

    def retain_value(self, value, type_expr):
        helper = "__btrc_string_retain" if self.types.is_string(type_expr) else "__btrc_arc_retain"
        self.helpers.use(helper)
        return IRCall(callee=helper, args=[value], helper_ref=helper)

    def release_value(self, value, type_expr):
        if self.types.is_string(type_expr):
            helper = "__btrc_string_release"
            self.helpers.use(helper)
            return IRCall(callee=helper, args=[value], helper_ref=helper)
        helper = "__btrc_arc_release" if self._type_may_cycle(type_expr) else "__btrc_arc_release_acyclic"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value, self._arc_type_descriptor(type_expr)],
            helper_ref=helper,
        )

    def cleanup_registration(
        self,
        declaration,
        type_expr,
        prefix,
        *,
        active: bool | None = None,
        fresh_temp=None,
        activate_cleanup=None,
    ):
        """Build one exception cleanup registration guarded by a local flag."""
        if active is None:
            active = self.cleanup_active()
        if not active:
            return [], []
        (activate_cleanup or self.owner.mark_cleanup_registration)()
        fresh_temp = fresh_temp or self.context.fresh_temp
        flag_decl = IRVarDecl(
            c_type=CType(text="bool"),
            name=fresh_temp(prefix),
            init=IRLiteral(text="false"),
        )
        self.context.record_declaration(flag_decl)
        flag = IRVar(name=flag_decl.name)
        emitted_name = self._runtime_name(type_expr)
        from .managed_values import (
            STRING_RUNTIME_NAME,
            cleanup_destroy_symbol,
        )

        destroy = cleanup_destroy_symbol(emitted_name)
        string_cleanup = emitted_name == STRING_RUNTIME_NAME
        if string_cleanup:
            self.helpers.use(destroy)
        from .cleanup_slots import register_cleanup_slot

        register = register_cleanup_slot(
            self,
            declaration,
            IRFunctionRef(name=destroy),
            visitor=(None if string_cleanup else self._visitor_expression(type_expr)),
            direct=string_cleanup,
        )
        register_once = IRTernary(
            condition=flag,
            true_expr=IRLiteral(text="0"),
            false_expr=IRCommaExpr(
                expressions=[
                    register,
                    IRBinOp(
                        left=flag,
                        op="=",
                        right=IRLiteral(text="true"),
                    ),
                    IRLiteral(text="0"),
                ]
            ),
        )
        return [flag_decl], [register_once]

    def protect_temporary(
        self,
        declaration,
        type_expr,
        declarations,
        prefix,
        flag_prefix,
        *,
        active: bool | None = None,
        fresh_temp=None,
        activate_cleanup=None,
    ) -> None:
        """Register an owned temporary for exceptional unwinding."""
        cleanup_decls, cleanup_exprs = self.cleanup_registration(
            declaration,
            type_expr,
            flag_prefix,
            active=active,
            fresh_temp=fresh_temp,
            activate_cleanup=activate_cleanup,
        )
        declarations.extend(cleanup_decls)
        prefix.extend(cleanup_exprs)

    def release_and_clear(
        self,
        value,
        type_expr,
        declarations,
        c_type,
        *,
        fresh_temp=None,
        record_declaration=None,
    ) -> list:
        """Move an owned slot to a saved value, clear it, then release it."""
        fresh_temp = fresh_temp or self.context.fresh_temp
        record_declaration = record_declaration or self.context.record_declaration
        saved_decl = IRVarDecl(
            c_type=CType(text=c_type),
            name=fresh_temp("__btrc_released_operand"),
        )
        record_declaration(saved_decl)
        declarations.append(saved_decl)
        saved = IRVar(name=saved_decl.name)
        expressions = [
            IRBinOp(left=saved, op="=", right=value),
            IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
            self.release_value(saved, type_expr),
        ]
        poll = self.poll_release_batch(
            types=[type_expr] if self.types.is_arc(type_expr) else [],
        )
        if poll is not None:
            expressions.append(poll)
        return expressions

    def poll_release_batch(self, *, types=()):
        """Bound deferred cycle work after a release-bearing batch."""
        if not any(self._type_may_cycle(item) for item in types):
            return None
        helper = "__btrc_poll_cycles"
        self.helpers.use(helper)
        # The optimizer may install the sibling force boundary at program exit.
        self.helpers.use("__btrc_flush_cycles")
        return IRCall(callee=helper, args=[], helper_ref=helper)

    def _arc_type_descriptor(self, type_expr):
        if self.types.is_mutex(type_expr):
            self.helpers.use("__btrc_mutex_arc_type")
            return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
        visitor = self._visitor_name(type_expr)
        from .arc_type_names import destroy_name

        return IRAddressOf(
            expr=IRCompoundLiteral(
                c_type=CType(text="__btrc_arc_type"),
                fields=[
                    (
                        "visit",
                        IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL"),
                    ),
                    (
                        "destroy",
                        IRFunctionRef(name=destroy_name(self, type_expr)),
                    ),
                    ("hook", IRLiteral(text="NULL")),
                    ("guard", IRLiteral(text="NULL")),
                    ("raise", IRLiteral(text="NULL")),
                ],
            )
        )

    def _runtime_name(self, type_expr) -> str:
        from .managed_values import MUTEX_RUNTIME_NAME, STRING_RUNTIME_NAME
        from .types import is_generic_class_type, mangle_generic_type

        if self.types.is_string(type_expr):
            return STRING_RUNTIME_NAME
        if self.types.is_mutex(type_expr):
            return MUTEX_RUNTIME_NAME
        canonical = self.types.canonical(type_expr)
        if is_generic_class_type(canonical, self.analyzed.class_table):
            return mangle_generic_type(
                canonical.base,
                canonical.generic_args,
            )
        return canonical.base

    def _visitor_expression(self, type_expr):
        visitor = self._visitor_name(type_expr)
        return IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL")

    def _visitor_name(self, type_expr) -> str | None:
        from .cycle_metadata import visitor_for_type

        return visitor_for_type(self, type_expr)

    def _type_may_cycle(self, type_expr) -> bool:
        from .cycle_metadata import type_may_cycle

        return type_may_cycle(self, type_expr)


__all__ = ["ArcLifetimeOwner", "ManagedLifetimeLowerer"]
