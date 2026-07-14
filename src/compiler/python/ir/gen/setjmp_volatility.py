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


def _hoisted_declarations(value: object):
    """Yield declarations that the emitter hoists before an expression."""

    if isinstance(value, IRStmtExpr):
        for statement in value.stmts:
            if isinstance(statement, IRVarDecl):
                yield statement
                yield from _hoisted_declarations(statement.init)
        yield from _hoisted_declarations(value.result)
        return
    if dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _hoisted_declarations(getattr(value, field.name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _hoisted_declarations(item)


class _LexicalVisibilityPass:
    def __init__(self, parameters):
        self._parameters = parameters

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for statement in block.stmts:
            self._statement(statement, visible)

    def _add_hoists(self, visible, *expressions) -> None:
        known = {id(declaration) for declaration in visible}
        for expression in expressions:
            for declaration in _hoisted_declarations(expression):
                if _automatic(declaration) and id(declaration) not in known:
                    visible.append(declaration)
                    known.add(id(declaration))

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

    def _expression(self, value: object, visible, modified=None) -> None:
        if isinstance(value, IRCall) and value.callee == "setjmp":
            self._mark_visible(visible, modified)
            return
        if isinstance(value, IRStmtExpr):
            for statement in value.stmts:
                if isinstance(statement, IRVarDecl):
                    self._expression(statement.init, visible)
            self._expression(value.result, visible, modified)
            return
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                self._expression(getattr(value, field.name), visible, modified)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._expression(item, visible, modified)

    def _simple(self, visible, *expressions) -> None:
        # _expr renders every IRStmtExpr setup before it writes the containing
        # C statement. All such declarations are therefore visible to every
        # setjmp in that statement, and remain in the surrounding block.
        self._add_hoists(visible, *expressions)
        for expression in expressions:
            self._expression(expression, visible)

    def _statement(self, statement, visible) -> None:
        if isinstance(statement, IRVarDecl):
            self._simple(visible, statement.init)
            if _automatic(statement):
                visible.append(statement)
        elif isinstance(statement, IRAssign):
            self._simple(visible, statement.target, statement.value)
        elif isinstance(statement, IRReturn):
            self._simple(visible, statement.value)
        elif isinstance(statement, IRExprStmt):
            self._simple(visible, statement.expr)
        elif isinstance(statement, IRIf):
            self._add_hoists(visible, statement.condition)
            modified = (
                mutated_names(statement.then_block) | mutated_names(statement.else_block)
                if contains_setjmp(statement.condition)
                else None
            )
            self._expression(statement.condition, visible, modified)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, IRWhile):
            self._simple(visible, statement.condition)
            self.block(statement.body, visible)
        elif isinstance(statement, IRDoWhile):
            self._add_hoists(visible, statement.condition)
            self.block(statement.body, visible)
            self._expression(statement.condition, visible)
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
        init_expressions = _statement_expressions(statement.init)
        # Every header expression is formatted before the `for` line is
        # written, so statement-expression setup declarations live in the
        # enclosing scope. The ordinary initializer declaration does not.
        self._add_hoists(visible, *init_expressions, statement.condition, statement.update)
        loop_visible = list(visible)
        for expression in init_expressions:
            self._expression(expression, loop_visible)
        if isinstance(statement.init, IRVarDecl) and _automatic(statement.init):
            loop_visible.append(statement.init)
        self._expression(statement.condition, loop_visible)
        self.block(statement.body, loop_visible)
        self._expression(statement.update, loop_visible)


def _statement_expressions(statement):
    if isinstance(statement, IRVarDecl):
        return (statement.init,)
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
