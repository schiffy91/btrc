"""Context-bound lowering for managed retain, release, edge, and cleanup IR."""

from __future__ import annotations

from typing import Protocol

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRExprStmt,
    IRFunctionRef,
    IRLiteral,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from .cleanup_slots import CleanupSlotRegistry
from .cycle_metadata import CycleMetadata
from .helpers import RuntimeHelperRegistry
from .lowering_context import LoweringContext
from .managed_values import (
    MUTEX_RUNTIME_NAME,
    STRING_RUNTIME_NAME,
    ManagedValueSemantics,
)
from .types import CTypeRenderer


class CleanupScope(Protocol):
    """The lexical cleanup state used by one context-bound lowerer."""

    def exception_cleanup_active(self) -> bool: ...

    def mark_cleanup_registration(self) -> None: ...


class ManagedLifetimeLowerer:
    """Lower every managed-value lifetime transition for one lexical context."""

    def __init__(
        self,
        *,
        context: LoweringContext,
        helpers: RuntimeHelperRegistry,
        values: ManagedValueSemantics,
        cycles: CycleMetadata,
        cleanup_slots: CleanupSlotRegistry,
        cleanup_scope: CleanupScope,
        type_renderer: CTypeRenderer,
    ) -> None:
        self.context = context
        self.helpers = helpers
        self.values = values
        self.cycles = cycles
        self.cleanup_slots = cleanup_slots
        self.cleanup_scope = cleanup_scope
        self.type_renderer = type_renderer

    def bind(
        self,
        context: LoweringContext,
        cleanup_scope: CleanupScope,
    ) -> ManagedLifetimeLowerer:
        """Bind shared lifetime services to another lexical lowering context."""
        return ManagedLifetimeLowerer(
            context=context,
            helpers=self.helpers,
            values=self.values,
            cycles=self.cycles,
            cleanup_slots=self.cleanup_slots,
            cleanup_scope=cleanup_scope,
            type_renderer=self.type_renderer,
        )

    def retain_value(self, value, type_expr):
        helper = "__btrc_string_retain" if self.values.is_string(type_expr) else "__btrc_arc_retain"
        self.helpers.use(helper)
        return IRCall(callee=helper, args=[value], helper_ref=helper)

    def retain_edge_value(self, value, type_expr, owner):
        if self.values.is_string(type_expr):
            return self.retain_value(value, type_expr)
        helper = "__btrc_arc_retain_edge"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value, owner],
            helper_ref=helper,
        )

    def adopt_edge_value(self, value, type_expr, owner):
        if self.values.is_string(type_expr):
            return self._no_op()
        helper = "__btrc_arc_adopt_edge"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value, owner],
            helper_ref=helper,
        )

    def unlink_edge_value(self, value, type_expr, owner=None):
        if self.values.is_string(type_expr):
            return self._no_op()
        helper = "__btrc_arc_unlink_edge"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[
                value,
                owner if owner is not None else IRLiteral(text="NULL"),
            ],
            helper_ref=helper,
        )

    def replace_edge_value(
        self,
        slot,
        replacement,
        type_expr,
        owner,
        *,
        adopt: bool,
    ):
        """Replace one persistent class edge as one topology transaction."""
        if not self.values.is_arc(type_expr):
            raise ValueError("transactional edge replacement requires an ARC type")
        from .lvalues import value_c_type

        access = self.cleanup_slots.ensure_arc_slot_adapter(
            CType(
                text=value_c_type(
                    type_expr,
                    self.context.analyzed.class_table,
                    self.type_renderer.render,
                )
            )
        )
        helper = "__btrc_arc_replace_edge"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            helper_ref=helper,
            args=[
                IRCast(
                    target_type=CType(text="volatile void*"),
                    expr=IRAddressOf(expr=slot),
                ),
                IRFunctionRef(name=access),
                replacement,
                owner,
                self.arc_type_descriptor(type_expr),
                IRLiteral(text="1" if adopt else "0"),
            ],
        )

    def release_value(self, value, type_expr):
        if self.values.is_string(type_expr):
            helper = "__btrc_string_release"
            self.helpers.use(helper)
            return IRCall(callee=helper, args=[value], helper_ref=helper)
        helper = "__btrc_arc_release" if self.cycles.type_may_cycle(type_expr) else "__btrc_arc_release_acyclic"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value, self.arc_type_descriptor(type_expr)],
            helper_ref=helper,
        )

    def release_edge_value(
        self,
        value,
        type_expr,
        replacement=None,
    ):
        if self.values.is_string(type_expr):
            return self.release_value(value, type_expr)
        helper = "__btrc_arc_release_edge"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            helper_ref=helper,
            args=[
                value,
                self.arc_type_descriptor(type_expr),
                replacement if replacement is not None else IRLiteral(text="NULL"),
            ],
        )

    def release_emitted_value(
        self,
        value,
        emitted_name: str,
    ):
        if emitted_name == STRING_RUNTIME_NAME:
            helper = "__btrc_string_release"
            self.helpers.use(helper)
            return IRCall(callee=helper, args=[value], helper_ref=helper)
        helper = (
            "__btrc_arc_release" if self.emitted_release_can_enqueue(emitted_name) else "__btrc_arc_release_acyclic"
        )
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value, self.emitted_type_descriptor(emitted_name)],
            helper_ref=helper,
        )

    def release_scope(
        self,
        managed,
        *,
        force: bool = True,
    ) -> list[IRStmt]:
        """Clear and release every owner leaving one lexical scope."""
        statements: list[IRStmt] = []
        for local in reversed(managed):
            local_c_name = local.c_name or local.name
            if local.cleanup_kind == "thread":
                self.helpers.use("__btrc_thread_free")
                statements.append(
                    IRExprStmt(
                        expr=IRCall(
                            callee="__btrc_thread_free",
                            args=[self._take_thread_handle(IRVar(name=local_c_name))],
                            helper_ref="__btrc_thread_free",
                        )
                    )
                )
                continue
            value_decl = IRVarDecl(
                c_type=CType(text=self.values.emitted_value_c_type(local.type_name)),
                name=self.context.fresh_temp("__btrc_scope_released"),
                init=IRVar(name=local_c_name),
            )
            self.context.record_declaration(value_decl)
            statements.extend(
                [
                    value_decl,
                    IRAssign(
                        target=IRVar(name=local_c_name),
                        value=IRLiteral(text="NULL"),
                    ),
                    IRExprStmt(
                        expr=self.release_emitted_value(
                            IRVar(name=value_decl.name),
                            local.type_name,
                        )
                    ),
                ]
            )
        boundary = self.flush_release_batch if force else self.poll_release_batch
        flush = boundary(
            emitted_names=[
                local.type_name
                for local in managed
                if local.cleanup_kind == "arc" and local.type_name != STRING_RUNTIME_NAME
            ],
        )
        if flush is not None:
            statements.append(IRExprStmt(expr=flush))
        return statements

    def arc_type_descriptor(self, type_expr):
        """Build the copied runtime descriptor for one concrete managed type."""
        if self.values.is_mutex(type_expr):
            self.helpers.use("__btrc_mutex_arc_type")
            return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
        visitor = self.cycles.visitor_for(type_expr)
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
                        IRFunctionRef(name=self.values.destroy_symbol(type_expr)),
                    ),
                    ("hook", IRLiteral(text="NULL")),
                    ("guard", IRLiteral(text="NULL")),
                    ("raise", IRLiteral(text="NULL")),
                ],
            )
        )

    def emitted_type_descriptor(self, emitted_name: str):
        if emitted_name == MUTEX_RUNTIME_NAME:
            self.helpers.use("__btrc_mutex_arc_type")
            return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
        visitor = self.cycles.emitted_visitor_symbol(emitted_name)
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
                        IRFunctionRef(name=f"{emitted_name}_destroy"),
                    ),
                    ("hook", IRLiteral(text="NULL")),
                    ("guard", IRLiteral(text="NULL")),
                    ("raise", IRLiteral(text="NULL")),
                ],
            )
        )

    def poll_released_values(self, *type_exprs):
        return self.release_batch_boundary(
            types=[value for value in type_exprs if self.values.is_arc(value)],
            force=False,
        )

    def flush_released_values(self, *type_exprs):
        return self.release_batch_boundary(
            types=[value for value in type_exprs if self.values.is_arc(value)],
            force=True,
        )

    def poll_release_batch(
        self,
        *,
        types=(),
        emitted_names=(),
    ):
        return self.release_batch_boundary(
            types=types,
            emitted_names=emitted_names,
            force=False,
        )

    def flush_release_batch(
        self,
        *,
        types=(),
        emitted_names=(),
    ):
        return self.release_batch_boundary(
            types=types,
            emitted_names=emitted_names,
            force=True,
        )

    def release_batch_boundary(
        self,
        *,
        types=(),
        emitted_names=(),
        force: bool,
    ):
        can_enqueue = any(self.cycles.type_may_cycle(item) for item in types) or any(
            self.emitted_release_can_enqueue(item) for item in emitted_names
        )
        if not can_enqueue:
            return None
        helper = "__btrc_flush_cycles" if force else "__btrc_poll_cycles"
        self.helpers.use(helper)
        if not force:
            self.helpers.use("__btrc_flush_cycles")
        return IRCall(callee=helper, args=[], helper_ref=helper)

    def emitted_release_can_enqueue(self, emitted_name: str) -> bool:
        if emitted_name == MUTEX_RUNTIME_NAME:
            return True
        return self.cycles.emitted_may_cycle(emitted_name)

    def invalidate_cycle_proof(self, value):
        helper = "__btrc_arc_invalidate"
        self.helpers.use(helper)
        return IRCall(
            callee=helper,
            args=[value],
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
            active = self.cleanup_scope.exception_cleanup_active()
        if not active:
            return [], []
        (activate_cleanup or self.cleanup_scope.mark_cleanup_registration)()
        fresh_temp = fresh_temp or self.context.fresh_temp
        flag_decl = IRVarDecl(
            c_type=CType(text="bool"),
            name=fresh_temp(prefix),
            init=IRLiteral(text="false"),
        )
        self.context.record_declaration(flag_decl)
        flag = IRVar(name=flag_decl.name)
        emitted_name = self.values.runtime_name(type_expr)
        destroy = self.values.cleanup_destroy_symbol(emitted_name)
        string_cleanup = emitted_name == STRING_RUNTIME_NAME
        if string_cleanup:
            self.helpers.use(destroy)
        visitor = None if string_cleanup else self._visitor_expression(type_expr)
        register = self.cleanup_slots.register(
            declaration,
            IRFunctionRef(name=destroy),
            visitor=visitor,
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

    def register_named_cleanup(
        self,
        var_name: str,
        emitted_name: str,
        statements: list[IRStmt],
    ) -> None:
        """Register one named managed local with the active cleanup scope."""
        if not self.cleanup_scope.exception_cleanup_active():
            return
        self.cleanup_scope.mark_cleanup_registration()
        declaration = self.cleanup_slots.require_declaration(
            statements,
            var_name,
        )
        destroy = self.values.cleanup_destroy_symbol(emitted_name)
        if emitted_name == STRING_RUNTIME_NAME:
            self.helpers.use(destroy)
            statements.append(
                IRExprStmt(
                    expr=self.cleanup_slots.register(
                        declaration,
                        IRFunctionRef(name=destroy),
                        direct=True,
                    )
                )
            )
            return
        visitor_name = self.cycles.emitted_visitor_symbol(emitted_name)
        if emitted_name == MUTEX_RUNTIME_NAME:
            self.helpers.use("__btrc_mutex_arc_type")
        visitor = IRFunctionRef(name=visitor_name) if visitor_name else IRLiteral(text="NULL")
        statements.append(
            IRExprStmt(
                expr=self.cleanup_slots.register(
                    declaration,
                    IRFunctionRef(name=destroy),
                    visitor=visitor,
                )
            )
        )

    def register_direct_cleanup(
        self,
        var_name: str,
        cleanup_fn: str,
        statements: list[IRStmt],
    ) -> None:
        if not self.cleanup_scope.exception_cleanup_active():
            return
        self.cleanup_scope.mark_cleanup_registration()
        declaration = self.cleanup_slots.require_declaration(
            statements,
            var_name,
        )
        self.helpers.use(cleanup_fn)
        statements.append(
            IRExprStmt(
                expr=self.cleanup_slots.register(
                    declaration,
                    IRFunctionRef(name=cleanup_fn),
                    direct=True,
                )
            )
        )

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
            IRBinOp(
                left=value,
                op="=",
                right=IRLiteral(text="NULL"),
            ),
            self.release_value(saved, type_expr),
        ]
        poll = self.poll_release_batch(
            types=[type_expr] if self.values.is_arc(type_expr) else [],
        )
        if poll is not None:
            expressions.append(poll)
        return expressions

    def _visitor_expression(self, type_expr):
        visitor = self.cycles.visitor_for(type_expr)
        if self.values.is_mutex(type_expr):
            self.helpers.use("__btrc_mutex_arc_type")
        return IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL")

    def _take_thread_handle(self, value):
        """Move one addressable thread handle before runtime disposal."""
        slot_name = self.context.fresh_temp("__btrc_thread_slot")
        handle_name = self.context.fresh_temp("__btrc_thread_handle")
        slot = IRVar(name=slot_name)
        handle = IRVar(name=handle_name)
        return IRStmtExpr(
            stmts=[
                IRVarDecl(
                    c_type=CType(text="__btrc_thread_t* volatile*"),
                    name=slot_name,
                ),
                IRVarDecl(
                    c_type=CType(text="__btrc_thread_t*"),
                    name=handle_name,
                ),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(
                        left=slot,
                        op="=",
                        right=IRAddressOf(expr=value),
                    ),
                    IRBinOp(
                        left=handle,
                        op="=",
                        right=IRDeref(expr=slot),
                    ),
                    IRBinOp(
                        left=IRDeref(expr=slot),
                        op="=",
                        right=IRLiteral(text="NULL"),
                    ),
                    handle,
                ]
            ),
        )

    def _no_op(self):
        return IRCast(
            target_type=CType(text="void"),
            expr=IRLiteral(text="0"),
        )


__all__ = ["CleanupScope", "ManagedLifetimeLowerer"]
