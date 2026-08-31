"""Transitive, fail-closed realtime-effect analysis."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import ClassVar

from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.syntax.ast import generated as ast

from .program import AnalysisSession, DeclarationIndex
from .types import TypeSystem


@dataclass(frozen=True, slots=True)
class RealtimeEffect:
    """One source operation that is forbidden on a realtime call path."""

    category: str
    operation: str
    line: int
    col: int
    source_file: str | None


@dataclass(frozen=True, slots=True)
class RealtimeEdge:
    """One statically resolved source call."""

    target: str
    line: int
    col: int


RealtimeEvent = RealtimeEffect | RealtimeEdge


@dataclass(slots=True)
class RealtimeCallable:
    key: str
    label: str
    declaration: ast.FunctionDecl | ast.MethodDecl | ast.PropertyDecl
    body: ast.Block | None
    source_file: str | None
    local_names: frozenset[str]
    events: list[RealtimeEvent] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RealtimeWitness:
    effect: RealtimeEffect
    path: tuple[RealtimeEdge, ...] = ()


@dataclass(slots=True)
class RealtimeLoopGuard:
    names: frozenset[str]
    site: ast.CForStmt
    violated: bool = False


class RealtimeAnalyzer:
    """Prove every ``@realtime`` root's complete reachable source call graph."""

    _COLLECTION_TYPES = frozenset({"Array", "List", "Map", "Set", "Vector"})
    _REALTIME_INTRINSIC_METHODS: ClassVar[dict[str, frozenset[str]]] = {
        "Atomic": frozenset(
            {
                "load",
                "store",
                "exchange",
                "fetchAdd",
                "fetchSub",
                "fetchAnd",
                "fetchOr",
                "fetchXor",
                "compareExchangeStrong",
            }
        ),
        "Span": frozenset({"length", "isEmpty", "isValid", "tryGet", "trySet"}),
    }
    _ALLOCATION_CALLS = frozenset({"malloc", "calloc", "realloc", "aligned_alloc", "free", "strdup", "strndup"})
    _LOCK_CALLS = frozenset(
        {
            "pthread_mutex_lock",
            "pthread_mutex_trylock",
            "pthread_mutex_unlock",
            "pthread_cond_wait",
            "pthread_cond_signal",
        }
    )
    _LOG_CALLS = frozenset({"print", "printf", "fprintf", "vprintf", "vfprintf", "syslog"})
    _BLOCKING_CALLS = frozenset({"sleep", "usleep", "nanosleep", "wait", "waitpid", "pthread_join", "thrd_join"})
    _IO_CALLS = frozenset(
        {
            "open",
            "close",
            "read",
            "write",
            "pread",
            "pwrite",
            "fopen",
            "fclose",
            "fread",
            "fwrite",
            "socket",
            "accept",
            "connect",
            "recv",
            "send",
        }
    )

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        runtime: RuntimeHelperCatalog,
    ) -> None:
        self.session = session
        self.index = index
        self.runtime = runtime
        self.hosted = HOSTED_ABI
        self.callables: dict[str, RealtimeCallable] = {}
        self._declaration_keys: dict[int, str] = {}
        self._property_keys: dict[tuple[str, str, str], str] = {}
        self._global_names = frozenset(index.global_declarations)
        self._loop_guards: list[RealtimeLoopGuard] = []

    def analyze(self, program: ast.Program) -> frozenset[str]:
        """Return the callable keys proven free of every forbidden effect."""

        if not self._has_realtime_root(program):
            return frozenset()
        self._index_callables(program)
        for callable_ in self.callables.values():
            self._scan_callable(callable_)
        summaries = self._fixed_point()
        for callable_ in self.callables.values():
            if not getattr(callable_.declaration, "is_realtime", False):
                continue
            witness = summaries.get(callable_.key)
            if witness is not None:
                self._report(callable_, witness)
        return frozenset(key for key in self.callables if key not in summaries)

    @staticmethod
    def _has_realtime_root(program: ast.Program) -> bool:
        for declaration in program.declarations:
            if isinstance(declaration, ast.FunctionDecl) and declaration.is_realtime:
                return True
            if isinstance(declaration, ast.ClassDecl) and any(
                isinstance(member, ast.MethodDecl) and member.is_realtime for member in declaration.members
            ):
                return True
        return False

    def _index_callables(self, program: ast.Program) -> None:
        for declaration in program.declarations:
            source_file = getattr(declaration, "source_file", None)
            if isinstance(declaration, ast.FunctionDecl):
                self._add_callable(
                    f"function:{declaration.name}",
                    declaration.name,
                    declaration,
                    declaration.body,
                    source_file,
                )
            elif isinstance(declaration, ast.ClassDecl):
                for member in declaration.members:
                    if isinstance(member, ast.MethodDecl):
                        label = f"{declaration.name}.{member.name}"
                        self._add_callable(f"method:{label}", label, member, member.body, source_file)
                    elif isinstance(member, ast.PropertyDecl):
                        if member.has_getter:
                            self._add_property_callable(
                                declaration.name, member, "get", member.getter_body, source_file
                            )
                        if member.has_setter:
                            self._add_property_callable(
                                declaration.name, member, "set", member.setter_body, source_file
                            )

    def _add_property_callable(self, owner, declaration, kind, body, source_file) -> None:
        key = f"property:{owner}.{declaration.name}:{kind}"
        label = f"{owner}.{declaration.name}.{kind}"
        self._property_keys[(owner, declaration.name, kind)] = key
        self._add_callable(key, label, declaration, body, source_file, property_accessor=True)

    def _add_callable(
        self,
        key,
        label,
        declaration,
        body,
        source_file,
        *,
        property_accessor=False,
    ) -> None:
        local_names = {parameter.name for parameter in getattr(declaration, "params", ())}
        if property_accessor and key.endswith(":set"):
            local_names.add("value")
        if body is not None:
            for node in self._walk(body):
                if isinstance(node, ast.VarDeclStmt):
                    local_names.add(node.name)
        callable_ = RealtimeCallable(
            key=key,
            label=label,
            declaration=declaration,
            body=body,
            source_file=source_file,
            local_names=frozenset(local_names),
        )
        self.callables[key] = callable_
        self._declaration_keys[id(declaration)] = key

    def _scan_callable(self, callable_: RealtimeCallable) -> None:
        declaration = callable_.declaration
        if isinstance(declaration, ast.PropertyDecl) and self._managed_type(declaration.type):
            kind = "setter" if callable_.key.endswith(":set") else "getter"
            self._effect(callable_, "ARC", f"managed property {kind}", declaration)
        if isinstance(declaration, ast.MethodDecl) and declaration.is_constructor:
            self._effect(callable_, "allocation", "constructor entry", declaration)
        if getattr(declaration, "is_gpu", False):
            self._effect(callable_, "runtime", "GPU dispatch", declaration)
        if not isinstance(declaration, ast.PropertyDecl) and callable_.body is None:
            self._effect(callable_, "unknown", "bodyless or abstract callable", declaration)
            return
        for parameter in getattr(declaration, "params", ()):
            if self._managed_type(parameter.type):
                self._effect(callable_, "ARC", f"managed parameter '{parameter.name}'", parameter)
        return_type = getattr(declaration, "return_type", None)
        if return_type is not None and self._managed_type(return_type):
            self._effect(callable_, "ARC", "managed return type", return_type)
        if callable_.body is not None:
            self._visit(callable_, callable_.body)

    def _visit(self, callable_: RealtimeCallable, node, *, callee=False, assignment_target=False) -> None:
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                self._visit(callable_, item)
            return
        if isinstance(node, ast.TypeExpr):
            return

        if isinstance(node, ast.WhileStmt):
            self._effect(callable_, "blocking", "unproven while loop", node)
            self._visit(callable_, node.condition)
            self._visit(callable_, node.body)
            return
        if isinstance(node, ast.DoWhileStmt):
            self._effect(callable_, "blocking", "unproven do-while loop", node)
            self._visit(callable_, node.body)
            self._visit(callable_, node.condition)
            return
        if isinstance(node, ast.CForStmt):
            protected_names = self._canonical_c_for(node, callable_)
            if protected_names is None:
                self._effect(callable_, "blocking", "unproven C-style loop", node)
                self._visit(callable_, node.init)
                self._visit(callable_, node.condition)
                self._visit(callable_, node.update)
                self._visit(callable_, node.body)
                return
            self._visit(callable_, node.init)
            self._visit(callable_, node.condition)
            self._visit(callable_, node.update)
            guard = RealtimeLoopGuard(protected_names, node)
            self._loop_guards.append(guard)
            try:
                self._visit(callable_, node.body)
            finally:
                self._loop_guards.pop()
            if not guard.violated:
                self.session.realtime_bounded_loop_ids.add(id(node))
            return
        if isinstance(node, ast.CallExpr):
            self._visit(callable_, node.callee, callee=True)
            for argument in node.args:
                self._visit(callable_, argument)
            self._visit_omitted_defaults(callable_, node)
            self._call_event(callable_, node)
            return
        if isinstance(node, ast.NewExpr):
            for argument in node.args:
                self._visit(callable_, argument)
            self._effect(callable_, "allocation", f"new {node.type.base}", node)
            return
        if isinstance(node, ast.AssignExpr):
            self._guard_mutation(callable_, node.target)
            if isinstance(node.target, ast.FieldAccessExpr):
                self._visit(callable_, node.target.obj)
                if node.op != "=":
                    self._property_event(callable_, node.target, "get")
            elif isinstance(node.target, ast.IndexExpr):
                self._visit(callable_, node.target.obj)
                self._visit(callable_, node.target.index)
                if node.op != "=":
                    self._index_event(callable_, node.target, "get")
            else:
                self._visit(callable_, node.target, assignment_target=True)
            self._visit(callable_, node.value)
            if node.op != "=":
                self._operator_event(callable_, node.target, node.op[:-1], node)
            if isinstance(node.target, ast.FieldAccessExpr):
                self._property_event(callable_, node.target, "set")
            elif isinstance(node.target, ast.IndexExpr):
                self._index_event(callable_, node.target, "set")
            value_type = self.session.node_types.get(id(node.value))
            if self._managed_type(value_type):
                self._effect(callable_, "ARC", "managed assignment", node)
            return
        if isinstance(node, ast.FieldAccessExpr):
            self._visit(callable_, node.obj)
            if not callee:
                if not assignment_target:
                    self._value_effect(callable_, node, f"field '{node.field}'")
                self._property_event(callable_, node, "set" if assignment_target else "get")
            return
        if isinstance(node, ast.CastExpr):
            self._visit(callable_, node.expr)
            if not assignment_target:
                self._value_effect(callable_, node, "cast result", fallback=node.target_type)
            return
        if isinstance(node, ast.Identifier):
            if not callee and not assignment_target:
                self._value_effect(callable_, node, f"identifier '{node.name}'")
            return
        if isinstance(node, ast.VarDeclStmt):
            self._guard_mutation_name(callable_, node.name)
            self._visit(callable_, node.initializer)
            declared_type = node.type or self.session.node_types.get(id(node.initializer))
            if self._managed_type(declared_type):
                self._effect(callable_, "ARC", f"managed local '{node.name}'", node)
            return
        if isinstance(node, ast.ReturnStmt):
            self._visit(callable_, node.value)
            if self._managed_type(self.session.node_types.get(id(node.value))):
                self._effect(callable_, "ARC", "managed return value", node)
            return
        if isinstance(node, ast.ForInStmt):
            self._effect(callable_, "blocking", "unproven for-in loop", node)
            self._visit(callable_, node.iterable)
            self._iteration_events(callable_, node)
            self._visit(callable_, node.body)
            return
        if isinstance(node, ast.UnaryExpr) and node.op in {"++", "--"}:
            self._guard_mutation(callable_, node.operand)
            if isinstance(node.operand, ast.FieldAccessExpr):
                self._visit(callable_, node.operand.obj)
                self._property_event(callable_, node.operand, "get")
                self._property_event(callable_, node.operand, "set")
            elif isinstance(node.operand, ast.IndexExpr):
                self._visit(callable_, node.operand.obj)
                self._visit(callable_, node.operand.index)
                self._index_event(callable_, node.operand, "get")
                self._index_event(callable_, node.operand, "set")
            else:
                self._visit(callable_, node.operand)
            return
        if isinstance(node, (ast.StringLiteral, ast.FStringLiteral)):
            self._effect(callable_, "strings", "string value", node)
        elif isinstance(node, (ast.ListLiteral, ast.MapLiteral)):
            self._effect(callable_, "collections", type(node).__name__, node)
        elif isinstance(node, ast.LambdaExpr):
            self._effect(callable_, "allocation", "closure construction", node)
        elif isinstance(node, ast.SpawnExpr):
            self._effect(callable_, "blocking", "thread spawn", node)
        elif isinstance(node, (ast.TryCatchStmt, ast.ThrowStmt)):
            self._effect(callable_, "exceptions", type(node).__name__, node)
        elif isinstance(node, (ast.DeleteStmt, ast.KeepStmt, ast.ReleaseStmt)):
            self._effect(callable_, "ARC", type(node).__name__, node)
        elif isinstance(node, ast.ParallelForStmt):
            self._effect(callable_, "blocking", "parallel for", node)
        elif isinstance(node, ast.BinaryExpr):
            self._visit(callable_, node.left)
            self._visit(callable_, node.right)
            overloaded = self._operator_event(callable_, node.left, node.op, node)
            left_type = self.session.node_types.get(id(node.left))
            right_type = self.session.node_types.get(id(node.right))
            if not overloaded and node.op in {"/", "%"}:
                self._effect(callable_, "runtime", f"checked '{node.op}' operator", node)
            elif self._string_type(left_type) or self._string_type(right_type):
                self._effect(callable_, "strings", f"string '{node.op}' operator", node)
            elif self._collection_type(left_type) or self._collection_type(right_type):
                self._effect(callable_, "collections", f"collection '{node.op}' operator", node)
            return
        elif isinstance(node, ast.UnaryExpr):
            if node.op == "&":
                self._guard_mutation(callable_, node.operand)
            self._visit(callable_, node.operand)
            self._operator_event(callable_, node.operand, node.op, node, unary=True)
            return
        elif isinstance(node, ast.IndexExpr):
            self._visit(callable_, node.obj)
            self._visit(callable_, node.index)
            self._index_event(callable_, node, "set" if assignment_target else "get")
            return

        if dataclasses.is_dataclass(node):
            for node_field in dataclasses.fields(node):
                if node_field.name in {"line", "col", "source_file"}:
                    continue
                self._visit(callable_, getattr(node, node_field.name))

    def _visit_omitted_defaults(self, callable_: RealtimeCallable, call: ast.CallExpr) -> None:
        declaration = self._direct_declaration(call, callable_)
        if declaration is None:
            return
        parameters = list(getattr(declaration, "params", ()))
        names = list(call.arg_names or ())
        names.extend("" for _ in range(len(call.args) - len(names)))
        supplied: set[int] = set()
        positional = 0
        for name in names:
            if name:
                for index, parameter in enumerate(parameters):
                    if parameter.name == name:
                        supplied.add(index)
                        break
            elif positional < len(parameters):
                supplied.add(positional)
                positional += 1
        for index, parameter in enumerate(parameters):
            if index not in supplied and parameter.default is not None:
                self._visit(callable_, parameter.default)

    def _direct_declaration(self, call: ast.CallExpr, callable_: RealtimeCallable):
        callee = call.callee
        if isinstance(callee, ast.Identifier):
            if callee.name in callable_.local_names or callee.name in self._global_names:
                return None
            return self.index.function_table.get(callee.name)
        if isinstance(callee, ast.FieldAccessExpr):
            resolved = self._method_target(callee)
            return resolved[1] if resolved is not None else None
        return None

    def _call_event(self, callable_: RealtimeCallable, call: ast.CallExpr) -> None:
        callee = call.callee
        if isinstance(callee, ast.Identifier):
            name = callee.name
            if name in callable_.local_names or name in self._global_names:
                self._effect(callable_, "unknown", f"indirect call through '{name}'", call)
                return
            declaration = self.index.function_table.get(name)
            if declaration is not None and id(call) not in self.session.hosted_call_ids:
                self._source_call(callable_, declaration, call)
                return
            if name in self.index.class_table:
                self._effect(callable_, "allocation", f"constructor call '{name}'", call)
                return
            self._external_call(callable_, name, call)
            return
        if isinstance(callee, ast.FieldAccessExpr):
            receiver = self.session.node_types.get(id(callee.obj))
            if receiver is not None and callee.field in self._REALTIME_INTRINSIC_METHODS.get(receiver.base, ()):
                return
            if receiver is not None and receiver.base in self._COLLECTION_TYPES:
                self._effect(callable_, "collections", f"{receiver.base}.{callee.field}()", call)
                return
            if receiver is not None and receiver.base == "string":
                self._effect(callable_, "strings", f"string.{callee.field}()", call)
                return
            if receiver is not None and receiver.base == "Mutex":
                self._effect(callable_, "locks", f"Mutex.{callee.field}()", call)
                return
            resolved = self._method_target(callee)
            if resolved is not None:
                self._source_call(callable_, resolved[1], call)
                return
            self._effect(callable_, "unknown", f"unresolved member call '{callee.field}'", call)
            return
        self._effect(callable_, "unknown", "indirect callable value", call)

    def _source_call(self, callable_: RealtimeCallable, declaration, call) -> None:
        target = self._declaration_keys.get(id(declaration))
        if target is None:
            self._effect(callable_, "unknown", f"unindexed source call '{declaration.name}'", call)
            return
        callable_.events.append(RealtimeEdge(target, call.line, call.col))

    def _operator_event(self, callable_, operand, operator, site, *, unary=False) -> bool:
        receiver = self.session.node_types.get(id(operand))
        if receiver is None:
            return False
        names = (
            {"-": "__neg__"}
            if unary
            else {
                "+": "__add__",
                "-": "__sub__",
                "*": "__mul__",
                "/": "__div__",
                "%": "__mod__",
                "==": "__eq__",
                "!=": "__ne__",
                "<": "__lt__",
                ">": "__gt__",
                "<=": "__le__",
                ">=": "__ge__",
            }
        )
        method_name = names.get(operator)
        info = self.index.class_table.get(receiver.base)
        declaration = info.methods.get(method_name) if info is not None and method_name else None
        if declaration is None:
            return False
        self._source_call(callable_, declaration, site)
        return True

    def _index_event(self, callable_, index: ast.IndexExpr, kind: str) -> None:
        indexed_type = self.session.node_types.get(id(index.obj))
        if self._collection_type(indexed_type):
            self._effect(callable_, "collections", "collection indexing", index)
            return
        if self._string_type(indexed_type):
            self._effect(callable_, "strings", "string indexing", index)
            return
        if indexed_type is None:
            return
        info = self.index.class_table.get(indexed_type.base)
        declaration = info.methods.get(kind) if info is not None else None
        if declaration is not None:
            self._source_call(callable_, declaration, index)

    def _iteration_events(self, callable_, loop: ast.ForInStmt) -> None:
        iterable_type = self.session.node_types.get(id(loop.iterable))
        if iterable_type is None:
            return
        if self._collection_type(iterable_type):
            self._effect(callable_, "collections", "collection iteration", loop)
            return
        if self._string_type(iterable_type):
            self._effect(callable_, "strings", "string iteration", loop)
            return
        info = self.index.class_table.get(iterable_type.base)
        if info is None:
            return
        method_names = ["iterLen", "iterGet"]
        if loop.var_name2:
            method_names.append("iterValueAt")
        for method_name in method_names:
            declaration = info.methods.get(method_name)
            if declaration is not None:
                self._source_call(callable_, declaration, loop)

    def _canonical_c_for(self, loop: ast.CForStmt, callable_: RealtimeCallable) -> frozenset[str] | None:
        if not isinstance(loop.init, ast.ForInitVar):
            return None
        declaration = loop.init.var_decl
        if not isinstance(declaration, ast.VarDeclStmt) or not isinstance(declaration.initializer, ast.IntLiteral):
            return None
        induction_type = declaration.type or self.session.node_types.get(id(declaration.initializer))
        if not self._integral_scalar(induction_type):
            return None

        condition = loop.condition
        if not isinstance(condition, ast.BinaryExpr) or condition.op not in {"<", ">"}:
            return None
        direction = ""
        bound = None
        if isinstance(condition.left, ast.Identifier) and condition.left.name == declaration.name:
            bound = condition.right
            direction = "++" if condition.op == "<" else "--"
        elif isinstance(condition.right, ast.Identifier) and condition.right.name == declaration.name:
            bound = condition.left
            direction = "--" if condition.op == "<" else "++"
        if bound is None:
            return None

        protected = {declaration.name}
        if isinstance(bound, ast.Identifier):
            if (
                bound.name == declaration.name
                or bound.name not in callable_.local_names
                or not self._integral_scalar(self.session.node_types.get(id(bound)))
            ):
                return None
            protected.add(bound.name)
        elif not isinstance(bound, ast.IntLiteral):
            return None

        update = loop.update
        if (
            not isinstance(update, ast.UnaryExpr)
            or update.op != direction
            or not isinstance(update.operand, ast.Identifier)
            or update.operand.name != declaration.name
        ):
            return None
        return frozenset(protected)

    def _integral_scalar(self, type_expr, seen=()) -> bool:
        if type_expr is None or type_expr.base in seen:
            return False
        alias = self.index.typedef_table.get(type_expr.base)
        if alias is not None:
            return self._integral_scalar(alias, (*seen, type_expr.base))
        return bool(
            type_expr.pointer_depth == 0
            and not type_expr.is_array
            and not type_expr.generic_args
            and type_expr.base != "bool"
            and type_expr.base not in self.index.enum_table
            and not type_expr.base.startswith("enum ")
            and TypeSystem.is_numeric_type(type_expr)
            and not TypeSystem.is_floating_type(type_expr)
        )

    def _guard_mutation(self, callable_: RealtimeCallable, expression) -> None:
        if isinstance(expression, ast.Identifier):
            self._guard_mutation_name(callable_, expression.name)

    def _guard_mutation_name(self, callable_: RealtimeCallable, name: str) -> None:
        for guard in reversed(self._loop_guards):
            if name not in guard.names:
                continue
            if not guard.violated:
                self._effect(callable_, "blocking", "unproven C-style loop", guard.site)
            guard.violated = True

    def _value_effect(self, callable_: RealtimeCallable, node, operation: str, *, fallback=None) -> None:
        type_expr = self.session.node_types.get(id(node)) or fallback
        category = self._value_category(type_expr)
        if category is None:
            return
        value_kind = {"strings": "string", "collections": "collection", "ARC": "managed"}[category]
        self._effect(callable_, category, f"{value_kind} {operation}", node)

    def _value_category(self, type_expr) -> str | None:
        if self._string_type(type_expr):
            return "strings"
        if self._collection_type(type_expr):
            return "collections"
        if self._managed_type(type_expr):
            return "ARC"
        return None

    def _collection_type(self, type_expr) -> bool:
        return type_expr is not None and type_expr.base in self._COLLECTION_TYPES

    @staticmethod
    def _string_type(type_expr) -> bool:
        return type_expr is not None and type_expr.base == "string"

    def _method_target(self, callee: ast.FieldAccessExpr):
        owner = None
        if isinstance(callee.obj, ast.Identifier) and callee.obj.name in self.index.class_table:
            owner = callee.obj.name
        else:
            receiver = self.session.node_types.get(id(callee.obj))
            if receiver is not None and receiver.base in self.index.class_table:
                owner = receiver.base
        if owner is None:
            return None
        info = self.index.class_table[owner]
        declaration = info.methods.get(callee.field)
        if declaration is None:
            return None
        declared_owner = info.method_owners.get(callee.field, owner)
        return declared_owner, declaration

    def _property_event(self, callable_: RealtimeCallable, access: ast.FieldAccessExpr, kind: str) -> None:
        owner = None
        if isinstance(access.obj, ast.Identifier) and access.obj.name in self.index.class_table:
            owner = access.obj.name
        else:
            receiver = self.session.node_types.get(id(access.obj))
            if receiver is not None and receiver.base in self.index.class_table:
                owner = receiver.base
        if owner is None:
            return
        info = self.index.class_table[owner]
        if access.field not in info.properties:
            return
        declared_owner = info.property_owners.get(access.field, owner)
        target = self._property_keys.get((declared_owner, access.field, kind))
        if target is None:
            self._effect(callable_, "unknown", f"unresolved property {kind} '{access.field}'", access)
        else:
            callable_.events.append(RealtimeEdge(target, access.line, access.col))

    def _external_call(self, callable_: RealtimeCallable, name: str, node) -> None:
        if name in self._ALLOCATION_CALLS:
            category = "allocation"
        elif name in self._LOCK_CALLS:
            category = "locks"
        elif name in self._LOG_CALLS:
            category = "logging"
        elif name in self._BLOCKING_CALLS:
            category = "blocking"
        elif name in self._IO_CALLS:
            category = "I/O"
        elif self.runtime.contains(name):
            category = self._catalog_category(self.runtime.definition(name).realtime_effect)
        elif self.hosted.function_owned_name(name):
            category = self._catalog_category(self.hosted.realtime_effect(name))
        elif name == "len":
            category = "collections"
        else:
            category = "unknown"
        if category != "safe":
            self._effect(callable_, category, f"external call '{name}()'", node)

    @staticmethod
    def _catalog_category(effect: str) -> str:
        return {"arc": "ARC", "io": "I/O"}.get(effect, effect)

    def _managed_type(self, type_expr, seen=()) -> bool:
        if type_expr is None:
            return False
        base = getattr(type_expr, "base", "")
        if base in seen:
            return False
        if base == "string" or base in self._COLLECTION_TYPES or base in self.index.class_table:
            return True
        alias = self.index.typedef_table.get(base)
        if alias is not None:
            return self._managed_type(alias, (*seen, base))
        struct = self.index.struct_table.get(base)
        if struct is not None:
            return any(self._managed_type(field.type, (*seen, base)) for field in struct.fields)
        rich_enum = self.index.rich_enum_table.get(base)
        if rich_enum is not None:
            return any(
                self._managed_type(parameter.type, (*seen, base))
                for variant in rich_enum.variants
                for parameter in variant.params
            )
        return any(self._managed_type(argument, (*seen, base)) for argument in getattr(type_expr, "generic_args", ()))

    def _effect(self, callable_: RealtimeCallable, category: str, operation: str, node) -> None:
        callable_.events.append(
            RealtimeEffect(
                category,
                operation,
                getattr(node, "line", 0),
                getattr(node, "col", 0),
                callable_.source_file,
            )
        )

    def _fixed_point(self) -> dict[str, RealtimeWitness]:
        unsafe = self._recursive_callables() | {
            key
            for key, callable_ in self.callables.items()
            if any(isinstance(event, RealtimeEffect) for event in callable_.events)
        }
        changed = True
        while changed:
            changed = False
            for key, callable_ in self.callables.items():
                if key in unsafe:
                    continue
                if any(isinstance(event, RealtimeEdge) and event.target in unsafe for event in callable_.events):
                    unsafe.add(key)
                    changed = True
        summaries = {}
        for key in self.callables:
            if key in unsafe:
                witness = self._first_witness(key, unsafe, frozenset())
                if witness is None:
                    raise RuntimeError(f"realtime fixed-point lost witness for {key}")
                summaries[key] = witness
        return summaries

    def _recursive_callables(self) -> set[str]:
        recursive = set()
        for key, callable_ in self.callables.items():
            if any(
                isinstance(event, RealtimeEdge) and self._reaches_target(event.target, key, frozenset({key}))
                for event in callable_.events
            ):
                recursive.add(key)
        return recursive

    def _reaches_target(self, key: str, target: str, visiting: frozenset[str]) -> bool:
        if key == target:
            return True
        if key in visiting or key not in self.callables:
            return False
        visiting = visiting | {key}
        return any(
            isinstance(event, RealtimeEdge) and self._reaches_target(event.target, target, visiting)
            for event in self.callables[key].events
        )

    def _first_witness(self, key, unsafe, visiting) -> RealtimeWitness | None:
        if key in visiting:
            return None
        visiting = visiting | {key}
        callable_ = self.callables[key]
        for event in callable_.events:
            if isinstance(event, RealtimeEffect):
                return RealtimeWitness(event)
            if event.target not in unsafe:
                continue
            if event.target in visiting:
                effect = RealtimeEffect(
                    "blocking",
                    "recursive call cycle",
                    event.line,
                    event.col,
                    callable_.source_file,
                )
                return RealtimeWitness(effect, (event,))
            downstream = self._first_witness(event.target, unsafe, visiting)
            if downstream is not None:
                return RealtimeWitness(downstream.effect, (event, *downstream.path))
        return None

    def _report(self, root: RealtimeCallable, witness: RealtimeWitness) -> None:
        labels = [root.label]
        for edge in witness.path:
            target = self.callables.get(edge.target)
            labels.append(target.label if target is not None else edge.target)
        effect = witness.effect
        message = (
            f"@realtime callable '{root.label}' reaches forbidden {effect.category} "
            f"operation '{effect.operation}' via {' -> '.join(labels)}"
        )
        with self.session.source(effect.source_file):
            self.session.error(message, effect.line, effect.col)

    @classmethod
    def _walk(cls, value):
        if value is None or isinstance(value, (str, int, float, bool, ast.TypeExpr)):
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                yield from cls._walk(item)
            return
        yield value
        if dataclasses.is_dataclass(value):
            for node_field in dataclasses.fields(value):
                if node_field.name in {"line", "col", "source_file"}:
                    continue
                yield from cls._walk(getattr(value, node_field.name))


__all__ = ["RealtimeAnalyzer", "RealtimeEffect", "RealtimeWitness"]
