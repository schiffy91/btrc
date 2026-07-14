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
from .setjmp_mutations import contains_setjmp, mutated_names


def _automatic(declaration: IRVarDecl) -> bool:
    return not declaration.is_static and not declaration.is_extern


class _LexicalVisibilityPass:
    def __init__(self, parameters):
        self._parameters = parameters

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for statement in block.stmts:
            self._statement(statement, visible)

    @staticmethod
    def _append_visible(visible, declaration, hoist_sink=None) -> None:
        if not _automatic(declaration):
            return
        if all(existing is not declaration for existing in visible):
            visible.append(declaration)
        if hoist_sink is not None and all(existing is not declaration for existing in hoist_sink):
            hoist_sink.append(declaration)

    def _mark_visible(self, visible, modified: set[str] | None = None) -> None:
        if modified is None:
            modified = {
                *(parameter.name for parameter in self._parameters),
                *(declaration.name for declaration in visible),
            }
        remaining = set(modified)
        # GCC's -Wclobbered conservatively diagnoses compiler-generated
        # statement-expression temporaries that are initialized before a
        # setjmp and consumed after its branch, even when source-level mutation
        # analysis proves that their spelling is not assigned in the branch.
        # These are automatic *objects* (including pointer objects), so marking
        # the declaration volatile is both C11-correct and preserves pointee
        # qualifiers through the structured CType emitter.
        remaining.update(declaration.name for declaration in visible if declaration.name.startswith("__btrc_"))
        # The innermost visible declaration owns a spelling; an outer shadowed
        # declaration must not be qualified for writes to that name.
        for declaration in reversed(visible):
            if declaration.name in remaining:
                declaration.is_volatile = True
                remaining.remove(declaration.name)
        for parameter in self._parameters:
            if parameter.name in remaining:
                parameter.is_volatile = True

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

    def _scan_expression(self, value: object, visible, modified=None) -> None:
        if isinstance(value, IRCall) and value.callee == "setjmp":
            self._mark_visible(visible, modified)
            return
        if isinstance(value, IRStmtExpr):
            # Setup declarations were emitted and scanned by _prepare_hoists;
            # only the substituted result remains in the containing statement.
            self._scan_expression(value.result, visible, modified)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                self._scan_expression(getattr(value, field.name), visible, modified)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._scan_expression(item, visible, modified)

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
            modified = mutated_names(statement.then_block) if contains_setjmp(statement.condition) else None
            self._process_expression(statement.condition, visible, modified)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, IRWhile):
            self._simple(visible, statement.condition)
            self.block(statement.body, visible)
        elif isinstance(statement, IRDoWhile):
            # The emitter renders the condition before writing the `do` line,
            # so statement-expression declarations are textually before it.
            self._process_expression(statement.condition, visible)
            self.block(statement.body, visible)
        elif isinstance(statement, IRFor):
            self._for(statement, visible)
        elif isinstance(statement, IRSwitch):
            self._simple(visible, statement.value)
            for case in statement.cases:
                case_visible = list(visible)
                self._simple(case_visible, case.value)
                for child in case.body:
                    self._statement(child, case_visible)
        elif isinstance(statement, IRBlock):
            self.block(statement, visible)

    def _for(self, statement: IRFor, visible) -> None:
        if isinstance(statement.init, IRVarDecl):
            # Every header is rendered before the `for` line is written. Hoists
            # from a later condition/update therefore precede a setjmp that
            # remains in the init declarator or initializer.
            self._prepare_hoists(statement.init.array_size, visible, hoist_sink=visible)
            self._prepare_hoists(statement.init.init, visible, hoist_sink=visible)
        else:
            for expression in _statement_expressions(statement.init):
                self._prepare_hoists(expression, visible, hoist_sink=visible)
        self._prepare_hoists(statement.condition, visible, hoist_sink=visible)
        self._prepare_hoists(statement.update, visible, hoist_sink=visible)

        loop_visible = list(visible)
        if isinstance(statement.init, IRVarDecl):
            self._scan_expression(statement.init.array_size, visible)
            self._append_visible(loop_visible, statement.init)
            self._scan_expression(statement.init.init, loop_visible)
        else:
            for expression in _statement_expressions(statement.init):
                self._scan_expression(expression, loop_visible)
        self._scan_expression(statement.condition, loop_visible)
        self._scan_expression(statement.update, loop_visible)
        self.block(statement.body, loop_visible)


def _statement_expressions(statement):
    if isinstance(statement, IRVarDecl):
        return (statement.array_size, statement.init)
    if isinstance(statement, IRAssign):
        return (statement.target, statement.value)
    if isinstance(statement, IRExprStmt):
        return (statement.expr,)
    return ()


def apply_setjmp_volatility(module: IRModule) -> None:
    """Qualify automatics directly modified after a generated ``setjmp``.

    Declarations created in a try/catch branch occur after its setjmp, while
    declarations in completed sibling blocks are out of scope. Unmodified
    visible values also retain their pre-setjmp value under C11 and must not be
    needlessly qualified: doing so can make an otherwise valid pointer to an
    aggregate incompatible with its declared C API. Indirect mutation through
    raw C pointers remains the source author's responsibility and can be made
    explicit with btrc's ``volatile`` qualifier.
    """

    for function in module.function_defs:
        _LexicalVisibilityPass(function.params).block(function.body)
