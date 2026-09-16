"""Which stdlib callables a program can reach, decided before lowering.

Dead-code elimination runs on lowered IR, so every method of every imported
stdlib class used to be lowered first and discarded afterwards; on a program
that imports JSON, Regex, TOML and the collections that was most of the
compile. This pass answers the same question on the analyzed program instead,
as an over-approximation by name: starting from every user and native
declaration, it collects the names a subtree mentions (identifiers, member
accesses, type bases, class parents and interfaces, interface method
signatures) and closes over them. A stdlib declaration is reachable once its
name is mentioned; a method of a reachable stdlib class is lowered once its
name is mentioned, and its body then contributes names of its own. Members
that are not ordinary methods (fields, properties, constructors, destructors)
and the method names lowering itself implies (iteration, string coercion,
sizes, operators) always stay.

The IR-level elimination still runs afterwards and removes exactly what it
removed before, so the emitted C does not change; this pass only avoids
lowering work. It is conservative by construction: every symbol the lowerer
emits for a stdlib callable is derived from a name the analyzed program
mentions, and that mention keeps the callable.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from src.compiler.python.frontend.sources import CompilerStdlibSource
from src.compiler.python.syntax.ast.generated import (
    ClassDecl,
    FieldAccessExpr,
    Identifier,
    MethodDecl,
    MethodSig,
    PropertyDecl,
    TypeExpr,
    decl,
)

# Method names either lowerer may call without the source spelling them: every
# stdlib method name that appears as a literal in a lowerer (list literals push,
# destructor hooks free, iteration protocols, string coercion, sizes, ...).
# The self-hosted compiler carries the same list; a contract test keeps them equal.
IMPLIED_METHOD_NAMES = frozenset(
    {
        "abortActivation",
        "abs",
        "activate",
        "activationGate",
        "active",
        "alias",
        "any",
        "arg",
        "args",
        "attachment",
        "before",
        "borrow",
        "boundary",
        "bounded",
        "box",
        "callbacks",
        "capacity",
        "capitalize",
        "capture",
        "center",
        "checked",
        "child",
        "clamp",
        "clear",
        "close",
        "code",
        "compareTo",
        "complete",
        "completed",
        "contains",
        "context",
        "copy",
        "count",
        "create",
        "createNative",
        "current",
        "data",
        "depth",
        "empty",
        "enabled",
        "end",
        "enter",
        "entries",
        "entry",
        "equals",
        "error",
        "escape",
        "failure",
        "field",
        "file",
        "fill",
        "find",
        "finishActivation",
        "floating",
        "format",
        "frame",
        "frames",
        "free",
        "freeze",
        "fromRaw",
        "get",
        "hash",
        "header",
        "i32",
        "id",
        "identity",
        "indexOf",
        "invoke",
        "isAlnum",
        "isAlpha",
        "isAlphaStr",
        "isBlank",
        "isDigit",
        "isDigitStr",
        "isEmpty",
        "isOpen",
        "isValid",
        "iterGet",
        "iterKey",
        "iterLen",
        "iterValue",
        "iterValueAt",
        "join",
        "key",
        "keys",
        "kind",
        "label",
        "lastIndexOf",
        "lease",
        "leave",
        "left",
        "len",
        "length",
        "line",
        "list",
        "load",
        "loop",
        "lstrip",
        "map",
        "marker",
        "max",
        "maximum",
        "message",
        "min",
        "name",
        "next",
        "node",
        "offset",
        "opened",
        "operand",
        "operation",
        "order",
        "padLeft",
        "padRight",
        "path",
        "payload",
        "pitch",
        "pointer",
        "pop",
        "print",
        "property",
        "publish",
        "push",
        "put",
        "read",
        "record",
        "removePrefix",
        "repeat",
        "replace",
        "request",
        "resolve",
        "result",
        "reverse",
        "rows",
        "rstrip",
        "run",
        "seed",
        "session",
        "set",
        "size",
        "slot",
        "snapshot",
        "source",
        "split",
        "start",
        "state",
        "status",
        "stderr",
        "str",
        "swapCase",
        "system",
        "targets",
        "text",
        "title",
        "toDouble",
        "toFloat",
        "toInt",
        "toString",
        "token",
        "top",
        "track",
        "transfer",
        "tryGet",
        "trySet",
        "u32",
        "unknown",
        "unregister",
        "update",
        "value",
        "values",
        "visible",
        "visit",
        "width",
        "write",
    }
)


@dataclass(frozen=True)
class StdlibReachabilityPlan:
    """The closure's answer: which stdlib declarations and method names a program reaches.

    A frozen value the lowering session carries; `StdlibReachability` computes it.
    """

    names: frozenset[str]
    reached: frozenset[int]
    unreached_names: frozenset[str]

    def reaches_name(self, name: str) -> bool:
        """True unless every stdlib declaration of that name is unreached (interfaces are emitted by name)."""

        return name not in self.unreached_names

    def reaches(self, declaration: object) -> bool:
        """User and native declarations always; a stdlib declaration once its name is mentioned."""

        return not StdlibReachability.is_stdlib_declaration(declaration) or id(declaration) in self.reached

    def lowers_method(self, declaration: ClassDecl, member: MethodDecl) -> bool:
        return (
            not StdlibReachability.is_stdlib_declaration(declaration)
            or StdlibReachability.always_lowered(member)
            or member.name in self.names
        )

    def selected_callables(
        self, declaration: ClassDecl, selected: frozenset[tuple[str, str]] | None
    ) -> frozenset[tuple[str, str]] | None:
        """Narrow a class's callable selection to the methods this program reaches."""

        if not StdlibReachability.is_stdlib_declaration(declaration):
            return selected
        chosen: set[tuple[str, str]] = set()
        for member in declaration.members:
            if isinstance(member, MethodDecl):
                if self.lowers_method(declaration, member):
                    chosen.add(("method", member.name))
            elif isinstance(member, PropertyDecl):
                chosen.add(("get", member.name))
                chosen.add(("set", member.name))
        return frozenset(chosen) if selected is None else frozenset(chosen & selected)


class StdlibReachability:
    """The stdlib declarations and methods a program reaches, by name closure."""

    def __init__(
        self,
        declarations: Iterable[decl],
        instantiated: Iterable[ClassDecl | MethodDecl] = (),
        instantiated_owners: Iterable[str] = (),
        instantiated_types: Iterable[TypeExpr] = (),
    ) -> None:
        """``instantiated`` names the generic declarations the analyzer specialized.

        A generic instance can exist without its class ever being spelled (a
        list literal infers ``Vector<T>``), so every specialized declaration is
        a root as well.
        """

        self._names: set[str] = set()
        self._reached: set[int] = set()
        self._pushed_methods: set[tuple[int, str]] = set()
        self._reached_classes: list[ClassDecl] = []
        by_name: dict[str, list[object]] = {}
        self._stdlib_by_name = by_name
        implementers: dict[str, list[ClassDecl]] = {}
        worklist: list[object] = []
        for declaration in declarations:
            if not StdlibReachability.is_stdlib_declaration(declaration):
                worklist.append(declaration)
                continue
            name = getattr(declaration, "name", None) or getattr(declaration, "alias", None)
            if isinstance(name, str) and name:
                by_name.setdefault(name, []).append(declaration)
            if isinstance(declaration, ClassDecl):
                for interface in declaration.interfaces:
                    implementers.setdefault(interface, []).append(declaration)
        for declaration in instantiated:
            if StdlibReachability.is_stdlib_declaration(declaration):
                self._reach(declaration, worklist)
        worklist.extend(Identifier(name=owner) for owner in instantiated_owners)
        # A specialization's type arguments name classes the instance's fields
        # and helpers need even when no lowered body spells them.
        worklist.extend(instantiated_types)
        while worklist:
            node = worklist.pop()
            fresh: set[str] = set()
            StdlibReachability.mentioned_names(node, fresh)
            fresh -= self._names
            if not fresh:
                continue
            self._names |= fresh
            for name in fresh:
                for declaration in by_name.get(name, ()):
                    self._reach(declaration, worklist)
                for implementer in implementers.get(name, ()):
                    self._reach(implementer, worklist)
            for reached in self._reached_classes:
                self._push_methods(reached, fresh, worklist)

        self.plan = StdlibReachabilityPlan(
            names=frozenset(self._names),
            reached=frozenset(self._reached),
            unreached_names=frozenset(
                name
                for name, declarations in by_name.items()
                if not any(id(declaration) in self._reached for declaration in declarations)
            ),
        )

    def reaches_name(self, name: str) -> bool:
        return self.plan.reaches_name(name)

    def reaches(self, declaration: object) -> bool:
        return self.plan.reaches(declaration)

    def lowers_method(self, declaration: ClassDecl, member: MethodDecl) -> bool:
        return self.plan.lowers_method(declaration, member)

    def selected_callables(
        self, declaration: ClassDecl, selected: frozenset[tuple[str, str]] | None
    ) -> frozenset[tuple[str, str]] | None:
        return self.plan.selected_callables(declaration, selected)

    def _reach(self, declaration: object, worklist: list[object]) -> None:
        if id(declaration) in self._reached:
            return
        self._reached.add(id(declaration))
        if not isinstance(declaration, ClassDecl):
            worklist.append(declaration)
            return
        self._reached_classes.append(declaration)
        skeleton: list[object] = [Identifier(name=declaration.parent)] if declaration.parent else []
        skeleton.extend(Identifier(name=interface) for interface in declaration.interfaces)
        for member in declaration.members:
            if isinstance(member, MethodDecl):
                if StdlibReachability.always_lowered(member):
                    self._push_method(declaration, member, worklist)
            else:
                skeleton.append(member)
        worklist.append(skeleton)
        self._push_methods(declaration, self._names, worklist)

    def _push_methods(self, declaration: ClassDecl, names: set[str], worklist: list[object]) -> None:
        for member in declaration.members:
            if isinstance(member, MethodDecl) and member.name in names:
                self._push_method(declaration, member, worklist)

    def _push_method(self, declaration: ClassDecl, member: MethodDecl, worklist: list[object]) -> None:
        key = (id(declaration), member.name)
        if key in self._pushed_methods:
            return
        self._pushed_methods.add(key)
        worklist.append(member)

    @staticmethod
    def is_stdlib_declaration(declaration: object) -> bool:
        return isinstance(getattr(declaration, "source_file", None), CompilerStdlibSource)

    @staticmethod
    def always_lowered(member: MethodDecl) -> bool:
        """Constructors, destructors, operators and lowering-implied methods never prune."""

        return (
            member.is_constructor
            or member.name.startswith("__")
            or member.name in IMPLIED_METHOD_NAMES
            or bool(member.generic_params)
        )

    @staticmethod
    def mentioned_names(root: object, names: set[str]) -> None:
        """Add every identifier, member, type, parent, interface and signature name a subtree mentions."""

        stack = [root]
        while stack:
            node = stack.pop()
            if isinstance(node, (list, tuple)):
                stack.extend(node)
                continue
            if not dataclasses.is_dataclass(node) or isinstance(node, type):
                continue
            if isinstance(node, Identifier):
                names.add(node.name)
            elif isinstance(node, FieldAccessExpr):
                names.add(node.field)
            elif isinstance(node, TypeExpr):
                names.add(node.base)
                # `struct S*` / `enum E` spell a tagged declaration by its bare name.
                names.add(node.base.split(" ", 1)[1] if " " in node.base else node.base)
            elif isinstance(node, MethodSig):
                names.add(node.name)
            elif isinstance(node, ClassDecl):
                if node.parent:
                    names.add(node.parent)
                names.update(node.interfaces)
            for field in dataclasses.fields(node):
                if field.name in {"line", "col", "source_file", "name_line", "name_col"}:
                    continue
                value = getattr(node, field.name)
                if isinstance(value, (list, tuple)) or dataclasses.is_dataclass(value):
                    stack.append(value)
