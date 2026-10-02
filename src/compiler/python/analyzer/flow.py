"""Control-flow, termination, and nullable-flow analysis."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import AnalysisSession, DeclarationIndex, SymbolInfo
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BreakStmt,
    CallExpr,
    CForStmt,
    ClassDecl,
    ContinueStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ExprStmt,
    FieldAccessExpr,
    ForInStmt,
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    LambdaExpr,
    MethodDecl,
    NullLiteral,
    ParallelForStmt,
    ReturnStmt,
    SelfExpr,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)


@dataclass(frozen=True, eq=False)
class AccessPath:
    """A stable local binding followed by zero or more named fields."""

    root: SymbolInfo
    fields: tuple[str, ...] = ()

    def __hash__(self) -> int:
        return hash((id(self.root), self.fields))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AccessPath) and self.root is other.root and (self.fields == other.fields)

    def contains(self, other: AccessPath) -> bool:
        """Whether assigning this path can change *other*."""
        return self.root is other.root and other.fields[: len(self.fields)] == self.fields


class ControlFlowAnalyzer:
    """Control-flow, termination, and nullable-flow analysis."""

    def __init__(self, session: AnalysisSession, types: TypeSystem, index: DeclarationIndex) -> None:
        self.session = session
        self.types = types
        self.index = index
        # Identities of the function and method declarations no call to which returns.
        self._nonreturning_callables: set[int] = set()
        # One root per class whose static fields a path names, global like a global variable.
        self._class_roots: dict[str, SymbolInfo] = {}

    def compute_nonreturning_callables(self, program) -> None:
        """Find every function and method that cannot return to its caller.

        A callable never returns when every path through its body ends in a
        ``throw`` or in a call that never returns: a hosted ``noreturn``
        function such as ``exit``, or another such callable. The set is the
        least fixed point over the call graph, so mutual recursion with no exit
        is not assumed to diverge. Calls resolve syntactically: ``f()`` to a
        top-level function, ``C.m()`` to a static method of class ``C``,
        ``self.m()`` to every implementation of ``m`` the receiver's class or a
        subclass of it can dispatch to, and ``self.field.m()`` likewise through
        the class the field is declared as. A local binding of the same name
        shadows the callee.
        """
        self._nonreturning_callables = set()
        candidates = []
        for declaration in program.declarations:
            if isinstance(declaration, FunctionDecl) and declaration.body is not None:
                candidates.append((declaration, None))
            elif isinstance(declaration, ClassDecl):
                for member in declaration.members:
                    if (
                        isinstance(member, MethodDecl)
                        and member.body is not None
                        and (not member.is_constructor)
                        and member.name != "__del__"
                    ):
                        candidates.append((member, declaration.name))
        bodies = [
            (callable_, owner, frozenset(self._callable_local_names(callable_))) for callable_, owner in candidates
        ]
        changed = True
        while changed:
            changed = False
            for callable_, owner, local_names in bodies:
                if id(callable_) in self._nonreturning_callables:
                    continue
                if self._statements_diverge(callable_.body.statements, owner, local_names):
                    self._nonreturning_callables.add(id(callable_))
                    changed = True

    def call_never_returns(self, call) -> bool:
        """Whether a call in the body being analyzed cannot return."""
        owner = self.session.current_class.name if self.session.current_class is not None else None
        return self._call_diverges(call, owner, None)

    def statement_ends_flow(self, statement) -> bool:
        """Whether no statement after this one in its sequence can run."""
        if isinstance(statement, (ReturnStmt, ThrowStmt)):
            return True
        return (
            isinstance(statement, ExprStmt)
            and isinstance(statement.expr, CallExpr)
            and self.call_never_returns(statement.expr)
        )

    def is_local_binding(self, name: str) -> bool:
        symbol = self.session.scope.lookup(name)
        return symbol is not None and symbol.kind != "function"

    def _shadowed(self, name: str, local_names: frozenset[str] | None) -> bool:
        """Whether a local binding hides a callee: one the pre-pass collected, or (None) one in scope now."""
        return self.is_local_binding(name) if local_names is None else name in local_names

    def _call_diverges(self, call, owner: str | None, local_names: frozenset[str] | None) -> bool:
        callee = call.callee
        if isinstance(callee, Identifier):
            if self._shadowed(callee.name, local_names):
                return False
            if callee.name in HOSTED_ABI.noreturn_function_names:
                return True
            function = self.index.function_table.get(callee.name)
            return function is not None and id(function) in self._nonreturning_callables
        if not isinstance(callee, FieldAccessExpr) or callee.optional or callee.arrow:
            return False
        if isinstance(callee.obj, SelfExpr):
            return owner is not None and self._dispatch_never_returns(owner, callee.field)
        if isinstance(callee.obj, FieldAccessExpr) and isinstance(callee.obj.obj, SelfExpr):
            field_class = self._self_field_class(owner, callee.obj) if owner is not None else None
            return field_class is not None and self._dispatch_never_returns(field_class, callee.field)
        if isinstance(callee.obj, Identifier) and (not self._shadowed(callee.obj.name, local_names)):
            info = self.index.class_table.get(callee.obj.name)
            method = info.methods.get(callee.field) if info is not None else None
            return method is not None and method.access == "class" and id(method) in self._nonreturning_callables
        return False

    def _dispatch_never_returns(self, owner: str, name: str) -> bool:
        """Whether every method ``self.name()`` can dispatch to from class ``owner`` diverges."""
        found = False
        for info in self.index.class_table.values():
            if not self._descends_from(info, owner):
                continue
            method = info.methods.get(name)
            if method is None:
                continue
            if method.access == "class" or id(method) not in self._nonreturning_callables:
                return False
            found = True
        return found

    def _self_field_class(self, owner: str, access) -> str | None:
        """The class `self.field` is declared as in non-generic class `owner`, if it is one."""
        info = self.index.class_table.get(owner)
        if info is None or info.generic_params or access.optional or access.arrow:
            return None
        field = info.fields.get(access.field)
        declared = field.type if field is not None and field.access != "class" else None
        if declared is None or declared.is_array:
            return None
        target = self.index.class_table.get(declared.base)
        return declared.base if target is not None and not target.generic_params else None

    def _descends_from(self, info, owner: str) -> bool:
        seen = set()
        current = info
        while current is not None and current.name not in seen:
            if current.name == owner:
                return True
            seen.add(current.name)
            current = self.index.class_table.get(current.parent) if current.parent else None
        return False

    def _statements_diverge(self, statements, owner, local_names) -> bool:
        """Whether a statement sequence can neither complete nor return."""
        for statement in statements:
            if self._statement_diverges(statement, owner, local_names):
                return True
            if self._contains_return(statement):
                return False
        return False

    def _statement_diverges(self, statement, owner, local_names) -> bool:
        if isinstance(statement, ThrowStmt):
            return True
        if isinstance(statement, ExprStmt):
            return isinstance(statement.expr, CallExpr) and self._call_diverges(statement.expr, owner, local_names)
        if isinstance(statement, Block):
            return self._statements_diverge(statement.statements, owner, local_names)
        if isinstance(statement, IfStmt):
            if not self._statements_diverge(statement.then_block.statements, owner, local_names):
                return False
            if isinstance(statement.else_block, ElseBlock):
                return self._statements_diverge(statement.else_block.body.statements, owner, local_names)
            if isinstance(statement.else_block, ElseIf):
                return self._statement_diverges(statement.else_block.if_stmt, owner, local_names)
            return False
        if isinstance(statement, SwitchStmt):
            return any(case.value is None for case in statement.cases) and all(
                self._statements_diverge(case.body, owner, local_names) for case in statement.cases
            )
        if isinstance(statement, TryCatchStmt):
            if statement.finally_block is not None and self._statements_diverge(
                statement.finally_block.statements, owner, local_names
            ):
                return True
            if not self._statements_diverge(statement.try_block.statements, owner, local_names):
                return False
            return statement.catch_block is None or self._statements_diverge(
                statement.catch_block.statements, owner, local_names
            )
        # A loop whose body always runs once diverges with that body, unless a
        # break leaves the loop first.
        enters_body = (
            (
                isinstance(statement, WhileStmt)
                and isinstance(statement.condition, BoolLiteral)
                and statement.condition.value
            )
            or isinstance(statement, DoWhileStmt)
            or (isinstance(statement, CForStmt) and statement.condition is None)
        )
        return (
            enters_body
            and (not self.contains_loop_break(statement.body))
            and self._statements_diverge(statement.body.statements, owner, local_names)
        )

    def _contains_return(self, statement) -> bool:
        """Whether a return statement (outside any lambda) is nested in a statement."""
        if isinstance(statement, ReturnStmt):
            return True
        return any(self._contains_return(child) for child in self._child_statements(statement))

    @staticmethod
    def _child_statements(statement) -> list:
        if isinstance(statement, Block):
            return list(statement.statements)
        if isinstance(statement, IfStmt):
            children = [statement.then_block]
            if isinstance(statement.else_block, ElseBlock):
                children.append(statement.else_block.body)
            elif isinstance(statement.else_block, ElseIf):
                children.append(statement.else_block.if_stmt)
            return children
        if isinstance(statement, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt)):
            return [statement.body]
        if isinstance(statement, SwitchStmt):
            return [child for case in statement.cases for child in case.body]
        if isinstance(statement, TryCatchStmt):
            return [block for block in (statement.try_block, statement.catch_block, statement.finally_block) if block]
        return []

    def _callable_local_names(self, callable_) -> set[str]:
        """Every name a callable's parameters or body binds, which shadows a callee of that name."""
        names = {parameter.name for parameter in callable_.params}
        stack = [callable_.body]
        while stack:
            node = stack.pop()
            if node is None or not dataclasses.is_dataclass(node):
                continue
            if isinstance(node, VarDeclStmt):
                names.add(node.name)
            elif isinstance(node, (ForInStmt, ParallelForStmt)):
                names.add(node.var_name)
                if isinstance(node, ForInStmt) and node.var_name2:
                    names.add(node.var_name2)
            elif isinstance(node, TryCatchStmt) and node.catch_var:
                names.add(node.catch_var)
            elif isinstance(node, LambdaExpr):
                names.update(parameter.name for parameter in node.params)
            for field in dataclasses.fields(node):
                child = getattr(node, field.name)
                if isinstance(child, (list, tuple)):
                    stack.extend(child)
                elif dataclasses.is_dataclass(child):
                    stack.append(child)
        return names

    def is_range_call(self, expr) -> bool:
        return isinstance(expr, CallExpr) and isinstance(expr.callee, Identifier) and (expr.callee.name == "range")

    def block_stops_fallthrough(self, block) -> bool:
        if block is None:
            return False
        return any(self.statement_stops_fallthrough(statement) for statement in block.statements)

    def statement_stops_fallthrough(self, statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt)):
            return True
        if isinstance(statement, Block):
            return self.block_stops_fallthrough(statement)
        if not isinstance(statement, IfStmt):
            return False
        if not self.block_stops_fallthrough(statement.then_block):
            return False
        if isinstance(statement.else_block, ElseBlock):
            return self.block_stops_fallthrough(statement.else_block.body)
        if isinstance(statement.else_block, ElseIf):
            return self.statement_stops_fallthrough(statement.else_block.if_stmt)
        return False

    def access_path(self, expression) -> AccessPath | None:
        if isinstance(expression, Identifier):
            symbol = self.session.scope.lookup(expression.name)
            if symbol is None and expression.name in self.index.class_table:
                symbol = self._class_root(expression.name)
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, SelfExpr):
            symbol = self.session.scope.lookup("self")
            return AccessPath(symbol) if symbol is not None else None
        if isinstance(expression, FieldAccessExpr):
            parent = self.access_path(expression.obj)
            if parent is not None:
                return AccessPath(parent.root, (*parent.fields, expression.field))
        return None

    def _class_root(self, name: str) -> SymbolInfo:
        """The root of `C.field` paths: a class's static storage, which any call can change."""
        root = self._class_roots.get(name)
        if root is None:
            root = SymbolInfo(name, TypeExpr(base=name), "class")
            self._class_roots[name] = root
        return root

    def is_known_nonnull(self, expression) -> bool:
        path = self.access_path(expression)
        return path is not None and path in self.session.nonnull_paths

    def nonnull_facts_for_outcome(self, expression, truth: bool) -> set[AccessPath]:
        if isinstance(expression, UnaryExpr) and expression.op == "!":
            return self.nonnull_facts_for_outcome(expression.operand, not truth)
        if not isinstance(expression, BinaryExpr):
            return set()
        if expression.op in ("==", "!="):
            path = self._null_comparison_path(expression)
            proves_nonnull = (expression.op == "!=" and truth) or (expression.op == "==" and (not truth))
            return {path} if path is not None and proves_nonnull else set()
        if expression.op == "&&":
            left = self.nonnull_facts_for_outcome(expression.left, truth)
            right = self.nonnull_facts_for_outcome(expression.right, truth)
            if truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        if expression.op == "||":
            left = self.nonnull_facts_for_outcome(expression.left, truth)
            right = self.nonnull_facts_for_outcome(expression.right, truth)
            if not truth:
                return self._facts_surviving(left, expression.right) | right
            return left & right
        return set()

    def _null_comparison_path(self, expression: BinaryExpr) -> AccessPath | None:
        if self.is_null_literal(expression.left):
            return self.access_path(expression.right)
        if self.is_null_literal(expression.right):
            return self.access_path(expression.left)
        return None

    @staticmethod
    def is_null_literal(expression) -> bool:
        return isinstance(expression, NullLiteral) or (isinstance(expression, Identifier) and expression.name == "NULL")

    @staticmethod
    def join_nonnull_flows(flows) -> set[AccessPath] | None:
        """Join the flows that reach one point; None (unreachable) when none does."""
        reaching = [flow for flow in flows if flow is not None]
        if not reaching:
            return None
        joined = set(reaching[0])
        for flow in reaching[1:]:
            joined.intersection_update(flow)
        return joined

    def invalidate_nonnull_target(self, target) -> None:
        assigned = self.access_path(target)
        if assigned is None:
            # An index, dereference or static-field store reaches a local only
            # through an escaped address, exactly as a call does.
            self.session.replace_nonnull_paths(self._facts_surviving_unknown_write(self.session.nonnull_paths))
            return
        if assigned.fields:
            self.session.replace_nonnull_paths(fact for fact in self.session.nonnull_paths if not fact.fields)
            return
        self.session.replace_nonnull_paths(fact for fact in self.session.nonnull_paths if not assigned.contains(fact))

    def record_nonnull_target(self, target) -> None:
        """A store of a value known to be non-null makes its stable target path non-null."""
        self._record_nonnull_path(self.access_path(target))

    def record_nonnull_binding(self, symbol: SymbolInfo | None) -> None:
        """A local initialized with a value known to be non-null starts non-null."""
        self._record_nonnull_path(AccessPath(symbol) if symbol is not None else None)

    def _record_nonnull_path(self, path: AccessPath | None) -> None:
        if path is not None and (not self.session.address_escaped(path.root)):
            self.session.replace_nonnull_paths({*self.session.nonnull_paths, path})

    def invalidate_nonnull_call(self, call: CallExpr) -> None:
        surviving = self._facts_surviving(set(self.session.nonnull_paths), call)
        self.session.replace_nonnull_paths(fact for fact in surviving if not self.session.address_escaped(fact.root))

    def record_nullable_address_escape(self, expression) -> None:
        path = self.access_path(expression)
        if path is not None and (not path.fields):
            self.session.mark_address_escaped(path.root)

    def invalidate_nonnull_effects(self, expression) -> None:
        """Drop the facts any call, store or address escape nested in an expression can kill."""
        surviving = self._facts_surviving(set(self.session.nonnull_paths), expression)
        self.session.replace_nonnull_paths(fact for fact in surviving if not self.session.address_escaped(fact.root))

    def facts_surviving_loop(self, facts, *parts) -> set[AccessPath]:
        """The facts that still hold at a loop head, before the body is analyzed once.

        A later iteration enters the loop from its back edge, so every fact that
        the body, the condition or the update could kill is dropped up front.
        Stores to locals the body itself declares cannot kill an outer fact.
        """
        nodes = [
            node
            for part in parts
            for node in self._walk_effect_nodes(part)
            if not (isinstance(node, AssignExpr) and self._is_undeclared_store(node.target))
        ]
        return self._facts_surviving_nodes(set(facts), nodes)

    def _is_undeclared_store(self, target) -> bool:
        root = target
        while isinstance(root, (FieldAccessExpr, IndexExpr)):
            root = root.obj
        return (
            isinstance(root, Identifier)
            and self.session.scope.lookup(root.name) is None
            and root.name not in self.index.class_table
        )

    def _facts_surviving(self, facts: set[AccessPath], expression) -> set[AccessPath]:
        return self._facts_surviving_nodes(facts, self._walk_effect_nodes(expression))

    def _facts_surviving_nodes(self, facts: set[AccessPath], nodes) -> set[AccessPath]:
        surviving = set(facts)
        assignments: list[AccessPath] = []
        has_unknown_assignment = False
        address_escapes: list[AccessPath] = []
        has_call = False
        for node in nodes:
            if isinstance(node, AssignExpr):
                path = self.access_path(node.target)
                if path is not None:
                    assignments.append(path)
                else:
                    has_unknown_assignment = True
            elif isinstance(node, CallExpr):
                has_call = True
                for argument in node.args:
                    if isinstance(argument, UnaryExpr) and argument.op == "&":
                        path = self.access_path(argument.operand)
                        if path is not None:
                            address_escapes.append(path)
        if has_unknown_assignment:
            surviving = self._facts_surviving_unknown_write(surviving)
        elif any(path.fields for path in assignments):
            surviving = {fact for fact in surviving if not fact.fields}
        surviving = {
            fact
            for fact in surviving
            if not any(path.contains(fact) for path in assignments)
            and (not any(path.contains(fact) for path in address_escapes))
        }
        if has_call:
            surviving = {fact for fact in surviving if not fact.fields and (not self._is_global_symbol(fact.root))}
        return surviving

    def _facts_surviving_unknown_write(self, facts) -> set[AccessPath]:
        return {
            fact
            for fact in facts
            if not fact.fields
            and (not self._is_global_symbol(fact.root))
            and (not self.session.address_escaped(fact.root))
        }

    def _walk_effect_nodes(self, expression):
        stack = [expression]
        while stack:
            node = stack.pop()
            if node is None or isinstance(node, LambdaExpr):
                continue
            if not dataclasses.is_dataclass(node):
                continue
            yield node
            for field in dataclasses.fields(node):
                child = getattr(node, field.name)
                if isinstance(child, (list, tuple)):
                    stack.extend(child)
                elif dataclasses.is_dataclass(child):
                    stack.append(child)

    def _is_global_symbol(self, symbol: SymbolInfo) -> bool:
        return symbol.kind == "class" or any(
            candidate is symbol for candidate in self.session.global_scope.symbols.values()
        )

    def _forget_nonnull_symbols(self, symbols) -> None:
        forgotten = tuple(symbols)
        self.session.forget_address_escaped(forgotten)
        self.session.replace_nonnull_paths(
            fact for fact in self.session.nonnull_paths if not any(fact.root is symbol for symbol in forgotten)
        )

    @staticmethod
    def block_must_terminate(block) -> bool:
        """Whether every path through a block returns or throws."""
        return block is not None and any(
            ControlFlowAnalyzer.statement_must_terminate(statement) for statement in block.statements
        )

    @staticmethod
    def statement_must_terminate(statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt)):
            return True
        if isinstance(statement, Block):
            return ControlFlowAnalyzer.block_must_terminate(statement)
        if isinstance(statement, IfStmt):
            if not ControlFlowAnalyzer.block_must_terminate(statement.then_block):
                return False
            if isinstance(statement.else_block, ElseBlock):
                return ControlFlowAnalyzer.block_must_terminate(statement.else_block.body)
            if isinstance(statement.else_block, ElseIf):
                return ControlFlowAnalyzer.statement_must_terminate(statement.else_block.if_stmt)
            return False
        if isinstance(statement, SwitchStmt):
            return (
                bool(statement.cases)
                and any(case.value is None for case in statement.cases)
                and all(ControlFlowAnalyzer.statement_sequence_must_terminate(case.body) for case in statement.cases)
            )
        if isinstance(statement, TryCatchStmt):
            if ControlFlowAnalyzer.block_must_terminate(statement.finally_block):
                return True
            try_terminates = ControlFlowAnalyzer.block_must_terminate(statement.try_block)
            return (
                try_terminates
                if statement.catch_block is None
                else try_terminates and ControlFlowAnalyzer.block_must_terminate(statement.catch_block)
            )
        if isinstance(statement, WhileStmt):
            return (
                isinstance(statement.condition, BoolLiteral)
                and statement.condition.value
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body)
            )
        if isinstance(statement, DoWhileStmt):
            return not ControlFlowAnalyzer.contains_loop_break(
                statement.body
            ) and ControlFlowAnalyzer.block_must_terminate(statement.body)
        if isinstance(statement, CForStmt):
            return (
                statement.condition is None
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body)
            )
        return False

    @staticmethod
    def statement_sequence_must_terminate(statements) -> bool:
        return any(ControlFlowAnalyzer.statement_must_terminate(statement) for statement in statements)

    @staticmethod
    def contains_loop_break(node) -> bool:
        """Find a break targeting this loop, ignoring nested loop/switch scopes."""
        if node is None:
            return False
        if isinstance(node, BreakStmt):
            return True
        if isinstance(node, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt, SwitchStmt)):
            return False
        if isinstance(node, Block):
            return any(ControlFlowAnalyzer.contains_loop_break(statement) for statement in node.statements)
        if isinstance(node, IfStmt):
            if ControlFlowAnalyzer.contains_loop_break(node.then_block):
                return True
            if isinstance(node.else_block, ElseBlock):
                return ControlFlowAnalyzer.contains_loop_break(node.else_block.body)
            if isinstance(node.else_block, ElseIf):
                return ControlFlowAnalyzer.contains_loop_break(node.else_block.if_stmt)
        if isinstance(node, TryCatchStmt):
            return any(
                ControlFlowAnalyzer.contains_loop_break(child)
                for child in (node.try_block, node.catch_block, node.finally_block)
            )
        return False


__all__ = ["AccessPath", "ControlFlowAnalyzer"]
