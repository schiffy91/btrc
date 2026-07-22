"""C11 setjmp qualification based on visibility and direct mutation."""

from __future__ import annotations

import dataclasses

from ..nodes import (
    IRAssign,
    IRBlock,
    IRCall,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRIf,
    IRModule,
    IRReturn,
    IRStmtExpr,
    IRSwitch,
    IRVarDecl,
    IRWhile,
)
from .setjmp_mutations import (
    contains_setjmp,
    loop_mutated_names,
    mutated_names,
    switch_fallthrough_mutated_names,
)
from .setjmp_visibility_loops import SetjmpLoopVisibilityMixin


def _automatic(declaration: IRVarDecl) -> bool:
    return not declaration.is_static and not declaration.is_extern


class _LexicalVisibilityPass(SetjmpLoopVisibilityMixin):
    def __init__(self, parameters, effects):
        self._parameters = parameters
        self._effects = effects
        self.inferred_volatile: set[int] = set()

    def _qualify(self, declaration) -> None:
        if not declaration.is_volatile:
            self.inferred_volatile.add(id(declaration))
        declaration.is_volatile = True
        declaration.effective_is_volatile = True

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for index, statement in enumerate(block.stmts):
            if contains_setjmp(statement):
                continuation = IRBlock(stmts=block.stmts[index + 1 :])
                self._mark_visible(
                    visible,
                    mutated_names(continuation, effects=self._effects),
                )
            self._statement(statement, visible)

    @staticmethod
    def _append_visible(visible, declaration, hoist_sink=None) -> None:
        if all(existing is not declaration for existing in visible):
            visible.append(declaration)
        if hoist_sink is not None and all(existing is not declaration for existing in hoist_sink):
            hoist_sink.append(declaration)

    def _mark_visible(self, visible, modified=None) -> None:
        if modified is None:
            remaining = {
                *(id(parameter) for parameter in self._parameters),
                *(id(declaration) for declaration in visible),
            }
        else:
            remaining = {storage.identity for storage in modified}
        # GCC's -Wclobbered conservatively diagnoses compiler-generated
        # statement-expression temporaries that are initialized before a
        # setjmp and consumed after its branch, even when source-level mutation
        # analysis proves that their spelling is not assigned in the branch.
        # These are automatic *objects* (including pointer objects), so marking
        # the declaration volatile is both C11-correct and preserves pointee
        # qualifiers through the structured CType emitter.
        from .setjmp_storage_names import compiler_storage_name

        remaining.update(id(declaration) for declaration in visible if compiler_storage_name(declaration.name))
        # The innermost visible declaration owns a spelling; an outer shadowed
        # declaration must not be qualified for writes to that name.
        for declaration in reversed(visible):
            if id(declaration) in remaining:
                if _automatic(declaration):
                    self._qualify(declaration)
                remaining.remove(id(declaration))
        for parameter in self._parameters:
            if id(parameter) in remaining:
                self._qualify(parameter)

    def _prepare_hoists(self, value: object, visible, modified=None, hoist_sink=None) -> None:
        """Model declarations emitted while the emitter pre-renders an expression."""

        if isinstance(value, IRStmtExpr):
            for statement in value.stmts:
                if isinstance(statement, IRVarDecl):
                    self._prepare_declaration(statement, visible, modified, hoist_sink)
            self._prepare_hoists(value.result, visible, modified, hoist_sink)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                self._prepare_hoists(getattr(value, field.name), visible, modified, hoist_sink)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._prepare_hoists(item, visible, modified, hoist_sink)

    def _scan_expression(
        self,
        value: object,
        visible,
        modified=None,
        *,
        parent=None,
        field_name="",
    ) -> None:
        if isinstance(value, IRCall) and value.callee == "setjmp":
            self._mark_visible(visible, modified)
            return
        if isinstance(value, IRStmtExpr):
            # Setup declarations were emitted and scanned by _prepare_hoists;
            # only the substituted result remains in the containing statement.
            self._scan_expression(
                value.result,
                visible,
                modified,
                parent=parent,
                field_name=field_name,
            )
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                if isinstance(child, (list, tuple)):
                    for item in child:
                        self._scan_expression(
                            item,
                            visible,
                            modified,
                            parent=value,
                            field_name=field.name,
                        )
                else:
                    self._scan_expression(
                        child,
                        visible,
                        modified,
                        parent=value,
                        field_name=field.name,
                    )
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._scan_expression(
                    item,
                    visible,
                    modified,
                    parent=parent,
                    field_name=field_name,
                )

    def _prepare_declaration(self, declaration, visible, modified=None, hoist_sink=None) -> None:
        # A nested statement-expression in an initializer is emitted before
        # the containing declaration line. Its setup therefore cannot see the
        # new name, while the residual initializer can.
        self._prepare_hoists(declaration.array_size, visible, modified, hoist_sink)
        self._prepare_hoists(declaration.init, visible, modified, hoist_sink)
        self._scan_expression(declaration.array_size, visible, modified)
        self._append_visible(visible, declaration, hoist_sink)
        self._scan_expression(declaration.init, visible, modified)

    def _process_expression(self, value, visible, modified=None, hoist_sink=None) -> None:
        self._prepare_hoists(value, visible, modified, hoist_sink)
        self._scan_expression(value, visible, modified)

    def _simple(self, visible, *expressions) -> None:
        for expression in expressions:
            self._prepare_hoists(expression, visible)
        for expression in expressions:
            self._scan_expression(expression, visible)

    def _statement(self, statement, visible) -> None:
        if isinstance(statement, IRVarDecl):
            self._prepare_declaration(statement, visible)
        elif isinstance(statement, IRAssign):
            self._simple(visible, statement.target, statement.value)
        elif isinstance(statement, IRReturn):
            self._simple(visible, statement.value)
        elif isinstance(statement, IRExprStmt):
            self._simple(visible, statement.expr)
        elif isinstance(statement, IRIf):
            modified = (
                mutated_names(statement.then_block, effects=self._effects)
                | mutated_names(statement.else_block, effects=self._effects)
                if contains_setjmp(statement.condition)
                else None
            )
            self._process_expression(statement.condition, visible, modified)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, IRWhile):
            if contains_setjmp(statement):
                self._mark_visible(
                    visible,
                    loop_mutated_names(statement, effects=self._effects),
                )
            self._simple(visible, statement.condition)
            self.block(statement.body, visible)
        elif isinstance(statement, IRDoWhile):
            if contains_setjmp(statement):
                self._mark_visible(
                    visible,
                    loop_mutated_names(statement, effects=self._effects),
                )
            # The emitter renders the condition before writing the `do` line,
            # so statement-expression declarations are textually before it.
            self._process_expression(statement.condition, visible)
            self.block(statement.body, visible)
        elif isinstance(statement, IRFor):
            self._for(statement, visible)
        elif isinstance(statement, IRSwitch):
            self._simple(visible, statement.value)
            for index, case in enumerate(statement.cases):
                case_visible = list(visible)
                self._simple(case_visible, case.value)
                case_block = IRBlock(stmts=case.body)
                if contains_setjmp(case_block) and case.falls_through:
                    self._mark_visible(
                        case_visible,
                        switch_fallthrough_mutated_names(
                            statement,
                            index,
                            effects=self._effects,
                        ),
                    )
                self.block(case_block, case_visible)
        elif isinstance(statement, IRBlock):
            self.block(statement, visible)


def apply_setjmp_volatility(module: IRModule) -> None:
    """Qualify automatics directly modified after a generated ``setjmp``.

    Declarations created in a try/catch branch occur after its setjmp, while
    declarations in completed sibling blocks are out of scope. Unmodified
    visible values also retain their pre-setjmp value under C11 and must not be
    needlessly qualified: doing so can make an otherwise valid pointer to an
    aggregate incompatible with its declared C API. Source address/array
    aliases visible across setjmp are treated conservatively and rejected by
    the qualifier-safety pass because layered pointee qualifiers are not yet
    representable in the source type model.
    """

    from .setjmp_qualifier_safety import (
        reject_inferred_volatile_aliases,
        reject_volatile_global_aliases,
    )

    globals_by_name = reject_volatile_global_aliases(module)
    if not any(contains_setjmp(function.body) for function in module.function_defs):
        return
    from .setjmp_call_effects import build_setjmp_call_effects

    call_effects = build_setjmp_call_effects(module)
    for function in module.function_defs:
        from .setjmp_capture_safety import reject_unmodelled_setjmp_captures

        reject_unmodelled_setjmp_captures(function, call_effects[function.name])
        visibility = _LexicalVisibilityPass(
            function.params,
            call_effects[function.name],
        )
        visibility.block(function.body)
        reject_inferred_volatile_aliases(
            function,
            visibility.inferred_volatile,
            globals_by_name,
        )
