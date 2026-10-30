"""Control-flow, termination, and nullable-flow analysis."""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
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
    CaseClause,
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
    GotoStmt,
    Identifier,
    IfStmt,
    IndexExpr,
    LabelStmt,
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


@dataclass(frozen=True, eq=False)
class JumpList:
    """One lexical statement list in a callable's jump scope."""

    node: Block | CaseClause
    kind: str
    parent: JumpList | None
    parent_index: int

    @property
    def statements(self) -> list:
        return self.node.body if isinstance(self.node, CaseClause) else self.node.statements


@dataclass(frozen=True)
class JumpSite:
    node: GotoStmt | LabelStmt
    path: tuple[tuple[JumpList, int], ...]
    ordinal: int


class JumpScopeIndex:
    """Lexical jump relationships, independent of semantic and lowering state."""

    def __init__(self) -> None:
        self.lists: dict[int, JumpList] = {}
        self.sites: dict[int, JumpSite] = {}
        self.labels: dict[str, JumpSite] = {}
        self.gotos: list[JumpSite] = []
        self.targeted_names: set[str] = set()
        self._nested_labels: dict[str, LabelStmt] = {}

    @classmethod
    def build(cls, root: Block) -> JumpScopeIndex:
        result = cls()
        result._walk_list(root, "body", ())
        result._collect_nested(root, False)
        return result

    def target(self, jump: GotoStmt) -> JumpSite | None:
        return self.labels.get(jump.name)

    def targeted(self, name: str) -> bool:
        return name in self.targeted_names

    def is_backward(self, jump: GotoStmt) -> bool:
        target = self.target(jump)
        return target is not None and target.ordinal < self.sites[id(jump)].ordinal

    def enclosing(self, jump: GotoStmt) -> tuple[JumpList, int, int] | None:
        target = self.target(jump)
        if target is not None:
            target_list, target_index = target.path[-1]
            for source_list, source_index in self.sites[id(jump)].path:
                if source_list is target_list:
                    return target_list, source_index, target_index
        return None

    def _common_depth(self, jump: GotoStmt) -> int:
        target = self.target(jump)
        if target is None:
            return 0
        depth = 0
        for source, destination in zip(self.sites[id(jump)].path, target.path):
            if source[0] is not destination[0]:
                break
            depth += 1
        return depth

    def left_lists(self, jump: GotoStmt) -> tuple[JumpList, ...]:
        if self.target(jump) is None:
            return ()
        return tuple(item[0] for item in reversed(self.sites[id(jump)].path[self._common_depth(jump) :]))

    def entered_lists(self, jump: GotoStmt) -> tuple[JumpList, ...]:
        target = self.target(jump)
        if target is None:
            return ()
        return tuple(item[0] for item in target.path[self._common_depth(jump) :])

    def entered_declarations(self, jump: GotoStmt) -> list[VarDeclStmt]:
        enclosing = self.enclosing(jump)
        if enclosing is None:
            return []
        scope, start, end = enclosing
        result: list[VarDeclStmt] = []
        if start < end:
            self._collect_declarations(scope.statements[start + 1 : end], result)
        return result

    @classmethod
    def _collect_declarations(cls, statements: list, result: list[VarDeclStmt]) -> None:
        for statement in statements:
            if isinstance(statement, VarDeclStmt):
                result.append(statement)
            elif isinstance(statement, TryCatchStmt) and statement.finally_block is not None:
                cls._collect_declarations(statement.finally_block.statements, result)

    def nested_lambda_label(self, name: str) -> LabelStmt | None:
        return self._nested_labels.get(name)

    def reach_start(self, scope: JumpList, declaration_index: int, label_index: int) -> int:
        """Earliest direct label reachable from the suffix, stopping at the declaration."""
        start = label_index
        while True:
            previous = start
            for jump in self.gotos:
                if not any(item is scope and index >= start for item, index in jump.path):
                    continue
                target = self.target(jump.node)
                if target is not None:
                    target_list, target_index = target.path[-1]
                    if target_list is scope and declaration_index < target_index < start:
                        start = target_index
            if start == previous:
                return start

    def _walk_list(self, node: Block | CaseClause, kind: str, path: tuple) -> None:
        parent, parent_index = path[-1] if path else (None, -1)
        scope = JumpList(node, kind, parent, parent_index)
        self.lists[id(node)] = scope
        for index, statement in enumerate(scope.statements):
            self._walk_statement(statement, (*path, (scope, index)))

    def _walk_statement(self, statement, path: tuple) -> None:
        if isinstance(statement, (GotoStmt, LabelStmt)):
            site = JumpSite(statement, path, len(self.sites))
            self.sites[id(statement)] = site
            if isinstance(statement, GotoStmt):
                self.gotos.append(site)
                self.targeted_names.add(statement.name)
            else:
                self.labels.setdefault(statement.name, site)
        elif isinstance(statement, Block):
            self._walk_list(statement, "block", path)
        elif isinstance(statement, IfStmt):
            self._walk_list(statement.then_block, "if", path)
            if isinstance(statement.else_block, ElseBlock):
                self._walk_list(statement.else_block.body, "else", path)
            elif isinstance(statement.else_block, ElseIf):
                self._walk_statement(statement.else_block.if_stmt, path)
        elif isinstance(statement, (WhileStmt, DoWhileStmt, CForStmt, ForInStmt, ParallelForStmt)):
            self._walk_list(statement.body, "parallel" if isinstance(statement, ParallelForStmt) else "loop", path)
        elif isinstance(statement, SwitchStmt):
            for case in statement.cases:
                self._walk_list(case, "case", path)
        elif isinstance(statement, TryCatchStmt):
            self._walk_list(statement.try_block, "try", path)
            if statement.catch_block is not None:
                self._walk_list(statement.catch_block, "catch", path)
            if statement.finally_block is not None:
                self._walk_list(statement.finally_block, "finally", path)

    def _collect_nested(self, node, nested: bool) -> None:
        if not dataclasses.is_dataclass(node):
            return
        nested = nested or isinstance(node, LambdaExpr)
        if nested and isinstance(node, LabelStmt):
            self._nested_labels.setdefault(node.name, node)
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            if isinstance(value, list):
                for child in value:
                    self._collect_nested(child, nested)
            else:
                self._collect_nested(value, nested)


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
        self._jump_roots: list[Block] = []
        self._jump_indexes: dict[int, JumpScopeIndex] = {}
        self._valid_gotos: set[int] = set()
        self._jump_flows: dict[int, list[frozenset | None]] = {}

    def reset_jump_scopes(self) -> None:
        self._jump_roots.clear()
        self._jump_indexes.clear()
        self._valid_gotos.clear()
        self._jump_flows.clear()

    @contextmanager
    def callable_jump_scope(self, body):
        self._jump_roots.append(body)
        try:
            yield
        finally:
            self._jump_roots.pop()

    def jump_index(self, body=None) -> JumpScopeIndex:
        root = body if body is not None else self._jump_roots[-1]
        key = id(root)
        if key not in self._jump_indexes:
            self._jump_indexes[key] = JumpScopeIndex.build(root)
        return self._jump_indexes[key]

    def goto_is_valid(self, jump) -> bool:
        return id(jump) in self._valid_gotos

    def targeted_label(self, statement) -> bool:
        return isinstance(statement, LabelStmt) and self.jump_index().targeted(statement.name)

    def active_jump_targets(self) -> set[str] | frozenset[str]:
        index = self._jump_indexes.get(id(self._jump_roots[-1])) if self._jump_roots else None
        return index.targeted_names if index is not None else frozenset()

    def callable_must_terminate(self, body) -> bool:
        index = self._jump_indexes.get(id(body))
        return self.block_must_terminate(body, index.targeted_names if index is not None else frozenset())

    def record_goto_flow(self, jump) -> None:
        target = self.jump_index().target(jump)
        if target is not None and not self.jump_index().is_backward(jump):
            self._jump_flows.setdefault(id(target.node), []).append(self.session.nonnull_flow)

    def enter_label_flow(self, label) -> None:
        index = self.jump_index()
        if not index.targeted(label.name):
            return
        if any(site.node.name == label.name and index.is_backward(site.node) for site in index.gotos):
            self.session.replace_nonnull_flow(set())
            return
        flows = [self.session.nonnull_flow, *self._jump_flows.get(id(label), ())]
        joined = self.join_nonnull_flows(flows)
        if joined is not None:
            joined = {
                fact
                for fact in joined
                if self.session.scope.lookup(fact.root.name) is fact.root
                or self._class_roots.get(fact.root.name) is fact.root
            }
        self.session.replace_nonnull_flow(joined)

    @staticmethod
    def decisive_suffix(statements, targeted_names):
        if not targeted_names:
            return statements
        start = 0
        for position, statement in enumerate(statements):
            if isinstance(statement, LabelStmt) and statement.name in targeted_names:
                start = position + 1
        return statements[start:] if start else statements

    def mark_jump_body(self) -> None:
        self.session.jump_body_ids.add(id(self._jump_roots[-1]))

    def validate_goto(self, jump: GotoStmt) -> None:
        self.mark_jump_body()
        index = self.jump_index()
        target = index.target(jump)
        message = None
        if target is None:
            for root in reversed(self._jump_roots[:-1]):
                outer = self.jump_index(root).labels.get(jump.name)
                if outer is not None:
                    message = (
                        f"goto '{jump.name}' cannot leave a lambda body (label at {outer.node.line}:{outer.node.col})"
                    )
                    break
            if message is None:
                nested = index.nested_lambda_label(jump.name)
                message = (
                    f"goto '{jump.name}' cannot enter a lambda body (label at {nested.line}:{nested.col})"
                    if nested is not None
                    else f"Label '{jump.name}' is not defined in this function"
                )
        else:
            for scope in index.left_lists(jump):
                if scope.kind in {"try", "catch", "finally"}:
                    message = f"goto '{jump.name}' cannot leave a {scope.kind} block; set a flag and test it after the try statement"
                    break
                if scope.kind == "parallel":
                    message = f"goto '{jump.name}' cannot leave a parallel for body"
                    break
            entered = index.entered_lists(jump)
            if message is None:
                for scope in entered:
                    if scope.kind in {"try", "catch", "finally"}:
                        message = f"goto '{jump.name}' cannot enter a {scope.kind} block"
                        break
                if message is None and entered:
                    message = f"goto '{jump.name}' cannot jump into a nested block; jump only to a label in the same block or an enclosing one"
        if message is not None:
            self.session.error(message, jump.line, jump.col)
        else:
            self._valid_gotos.add(id(jump))

    def valid_forward_gotos(self, label: LabelStmt) -> list[JumpSite]:
        index = self.jump_index()
        target = index.sites[id(label)]
        return [
            site
            for site in index.gotos
            if id(site.node) in self._valid_gotos and site.node.name == label.name and site.ordinal < target.ordinal
        ]

    def validate_label_identity(self, label: LabelStmt) -> bool:
        self.mark_jump_body()
        first = self.jump_index().labels[label.name].node
        if first is not label:
            self.session.error(
                f"Duplicate label '{label.name}' in this function (first at {first.line}:{first.col})",
                label.line,
                label.col,
            )
            return False
        return True

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
        if self.statement_must_terminate(statement, self.active_jump_targets()):
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
            if self._contains_return_or_jump(statement):
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

    def _contains_return_or_jump(self, statement) -> bool:
        """Whether a return or jump (outside any lambda) can bypass a later statement."""
        if isinstance(statement, (ReturnStmt, GotoStmt)):
            return True
        return any(self._contains_return_or_jump(child) for child in self._child_statements(statement))

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
        return any(
            self.statement_stops_fallthrough(statement)
            for statement in self.decisive_suffix(block.statements, self.active_jump_targets())
        )

    def statement_stops_fallthrough(self, statement) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt, GotoStmt)):
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
    def block_must_terminate(block, targeted_names=frozenset()) -> bool:
        """Whether the decisive suffix leaves the block on every path."""
        return block is not None and any(
            ControlFlowAnalyzer.statement_must_terminate(statement, targeted_names)
            for statement in ControlFlowAnalyzer.decisive_suffix(block.statements, targeted_names)
        )

    @staticmethod
    def statement_must_terminate(statement, targeted_names=frozenset()) -> bool:
        if isinstance(statement, (ReturnStmt, ThrowStmt, GotoStmt)):
            return True
        if isinstance(statement, Block):
            return ControlFlowAnalyzer.block_must_terminate(statement, targeted_names)
        if isinstance(statement, IfStmt):
            if not ControlFlowAnalyzer.block_must_terminate(statement.then_block, targeted_names):
                return False
            if isinstance(statement.else_block, ElseBlock):
                return ControlFlowAnalyzer.block_must_terminate(statement.else_block.body, targeted_names)
            if isinstance(statement.else_block, ElseIf):
                return ControlFlowAnalyzer.statement_must_terminate(statement.else_block.if_stmt, targeted_names)
            return False
        if isinstance(statement, SwitchStmt):
            return (
                bool(statement.cases)
                and any(case.value is None for case in statement.cases)
                and all(
                    ControlFlowAnalyzer.statement_sequence_must_terminate(case.body, targeted_names)
                    for case in statement.cases
                )
            )
        if isinstance(statement, TryCatchStmt):
            if ControlFlowAnalyzer.block_must_terminate(statement.finally_block, targeted_names):
                return True
            try_terminates = ControlFlowAnalyzer.block_must_terminate(statement.try_block, targeted_names)
            return (
                try_terminates
                if statement.catch_block is None
                else try_terminates and ControlFlowAnalyzer.block_must_terminate(statement.catch_block, targeted_names)
            )
        if isinstance(statement, WhileStmt):
            return (
                isinstance(statement.condition, BoolLiteral)
                and statement.condition.value
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body, targeted_names)
            )
        if isinstance(statement, DoWhileStmt):
            return not ControlFlowAnalyzer.contains_loop_break(
                statement.body
            ) and ControlFlowAnalyzer.block_must_terminate(statement.body, targeted_names)
        if isinstance(statement, CForStmt):
            return (
                statement.condition is None
                and (not ControlFlowAnalyzer.contains_loop_break(statement.body))
                and ControlFlowAnalyzer.block_must_terminate(statement.body, targeted_names)
            )
        return False

    @staticmethod
    def statement_sequence_must_terminate(statements, targeted_names=frozenset()) -> bool:
        return any(
            ControlFlowAnalyzer.statement_must_terminate(statement, targeted_names)
            for statement in ControlFlowAnalyzer.decisive_suffix(statements, targeted_names)
        )

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
