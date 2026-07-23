"""Owned cycle classification, visitor identity, and emitted metadata state."""

from __future__ import annotations

from dataclasses import dataclass

from ...analyzer.core import AnalyzedProgram
from ...ast_nodes import TypeExpr
from ...type_identity import TypeIdentity, TypeShapeError
from .errors import CodegenError
from .managed_values import MUTEX_RUNTIME_NAME, ManagedValueSemantics

BUILTIN_COLLECTION_LAYOUTS = {
    "Vector": (1, frozenset({"data", "len"})),
    "Array": (1, frozenset({"data", "len"})),
    "List": (1, frozenset({"head", "tail", "len"})),
    "Map": (2, frozenset({"keys", "values", "occupied", "cap"})),
    "Set": (1, frozenset({"keys", "occupied", "cap"})),
}


@dataclass(frozen=True)
class DirectVisitAction:
    """A managed slot whose target must join the collector candidate graph."""

    emitted_name: str


class CycleMetadata:
    """Own cycle graph queries and one lowering run's emitted classifications."""

    def __init__(
        self,
        analyzed: AnalyzedProgram,
        values: ManagedValueSemantics,
        type_identity: TypeIdentity,
    ) -> None:
        self.analyzed = analyzed
        self.values = values
        self.type_identity = type_identity
        self._visitor_types: set[str] = set()
        self._emitted_may_cycle: dict[str, bool] = {}
        self._may_cycle_cache: dict[str, bool] = {}

    def visitor_symbol(self, emitted_name: str) -> str:
        return f"__btrc_arc_visit_{emitted_name}"

    def generic_instance_needs_visitor(
        self,
        base: str,
        arguments: list[TypeExpr],
        seen: set[tuple] | None = None,
    ) -> bool:
        """Whether a concrete generic representation owns managed slots."""
        info = self.analyzed.class_table.get(base)
        if info is None or not info.generic_params:
            return False
        key = self.type_identity.generic_instance_key(base, arguments)
        seen = set() if seen is None else seen
        if key in seen:
            return False
        seen.add(key)
        try:
            if base in BUILTIN_COLLECTION_LAYOUTS:
                arity, _fields = BUILTIN_COLLECTION_LAYOUTS[base]
                if len(arguments) != arity:
                    return False
                return base == "List" or any(self.visit_action(argument, seen) is not None for argument in arguments)
            substitutions = dict(zip(info.generic_params, arguments))
            return any(
                field.type is not None
                and self._type_has_visit_action(
                    self._substitute_type(field.type, substitutions),
                    seen,
                )
                for _name, field in info.instance_storage
            )
        finally:
            seen.remove(key)

    def visitor_for(self, type_expr: TypeExpr) -> str | None:
        """Return the concrete cycle visitor for a managed source type."""
        type_expr = self.values.canonical(type_expr) or type_expr
        if self.values.is_mutex(type_expr):
            return "__btrc_mutex_arc_visit"
        if not self.type_needs_visitor(type_expr, set()):
            return None
        emitted = (
            self.type_identity.specialization_symbol(
                type_expr.base,
                type_expr.generic_args,
            )
            if type_expr.generic_args
            else type_expr.base
        )
        return self.visitor_symbol(emitted)

    def register_visitor(self, emitted_name: str) -> None:
        self._visitor_types.add(emitted_name)

    def emitted_has_visitor(self, emitted_name: str) -> bool:
        """Check metadata without confusing a source method named ``visit``."""
        if emitted_name == MUTEX_RUNTIME_NAME:
            return True
        if emitted_name in self._visitor_types:
            return True
        info = self.lookup_class_info(emitted_name)
        return bool(
            info is not None and not info.generic_params and self.type_needs_visitor(TypeExpr(base=info.name), set())
        )

    def emitted_visitor_symbol(self, emitted_name: str) -> str | None:
        if emitted_name == MUTEX_RUNTIME_NAME:
            return "__btrc_mutex_arc_visit"
        if not self.emitted_has_visitor(emitted_name):
            return None
        return self.visitor_symbol(emitted_name)

    def register_classification(
        self,
        emitted_name: str,
        may_cycle: bool,
    ) -> None:
        self._emitted_may_cycle[emitted_name] = may_cycle

    def emitted_may_cycle(self, emitted_name: str) -> bool:
        """Whether an emitted representation can join a retain cycle."""
        if emitted_name in self._emitted_may_cycle:
            return self._emitted_may_cycle[emitted_name]
        info = self.analyzed.class_table.get(emitted_name)
        if info is not None and not info.generic_params:
            return self.type_may_cycle(TypeExpr(base=emitted_name))
        return True

    def visit_action(
        self,
        type_expr: TypeExpr,
        seen: set[tuple] | None = None,
    ) -> DirectVisitAction | None:
        """Return one typed heap edge, or ``None`` for unmanaged storage."""
        type_expr = self.values.canonical(type_expr) or type_expr
        if type_expr.is_array:
            return None
        if self.values.is_mutex(type_expr):
            return DirectVisitAction(MUTEX_RUNTIME_NAME)
        if not self.values.is_class(type_expr):
            return None
        info = self.analyzed.class_table.get(type_expr.base)
        if info is None:
            return None
        emitted = (
            self.type_identity.specialization_symbol(
                type_expr.base,
                type_expr.generic_args,
            )
            if type_expr.generic_args
            else type_expr.base
        )
        return DirectVisitAction(emitted)

    def type_needs_visitor(
        self,
        type_expr: TypeExpr,
        seen: set[tuple] | None = None,
    ) -> bool:
        """Whether this concrete representation has managed outgoing edges."""
        type_expr = self.values.canonical(type_expr) or type_expr
        if type_expr.is_array:
            return False
        if self.values.is_mutex(type_expr):
            return True
        if not self.values.is_class(type_expr):
            return False
        info = self.analyzed.class_table.get(type_expr.base)
        if info is None:
            return False
        if type_expr.generic_args:
            return self.generic_instance_needs_visitor(
                type_expr.base,
                list(type_expr.generic_args),
                seen,
            )
        return any(
            getattr(field, "type", None) is not None and self._type_has_visit_action(field.type, set())
            for _name, field in info.instance_storage
        )

    def generic_instance_may_cycle(
        self,
        base: str,
        arguments: list[TypeExpr],
    ) -> bool:
        return self.type_may_cycle(TypeExpr(base=base, generic_args=list(arguments)))

    def type_may_cycle(self, type_expr: TypeExpr) -> bool:
        """Return whether any runtime value of this type may join a cycle."""
        return any(self._concrete_type_may_cycle(candidate) for candidate in self._runtime_type_candidates(type_expr))

    def lookup_class_info(self, class_name: str):
        """Look up class metadata by source or concrete specialization name."""
        info = self.analyzed.class_table.get(class_name)
        if info is not None:
            return info
        for source_name, candidate in self.analyzed.class_table.items():
            if class_name.startswith(f"btrc_{source_name}"):
                return candidate
        return None

    def _concrete_type_may_cycle(self, type_expr: TypeExpr) -> bool:
        type_expr = self.values.canonical(type_expr) or type_expr
        if not self.values.is_arc(type_expr):
            return False
        info = self.analyzed.class_table.get(type_expr.base)
        if info is not None and info.generic_params and not type_expr.generic_args:
            return True
        root = self._emitted_name(type_expr)
        cached = self._may_cycle_cache.get(root)
        if cached is not None:
            return cached

        visited: set[str] = set()
        stack = self._outgoing_managed_types(type_expr)
        while stack:
            current = stack.pop()
            emitted = self._emitted_name(current)
            if emitted == root:
                self._may_cycle_cache[root] = True
                return True
            if emitted in visited:
                continue
            visited.add(emitted)
            stack.extend(self._outgoing_managed_types(current))
        self._may_cycle_cache[root] = False
        return False

    def _outgoing_managed_types(
        self,
        type_expr: TypeExpr,
    ) -> list[TypeExpr]:
        type_expr = self.values.canonical(type_expr) or type_expr
        if not self.values.is_arc(type_expr):
            return []
        if self.values.is_mutex(type_expr):
            payload = type_expr.generic_args[0]
            if not self.values.is_arc(payload):
                return []
            return self._runtime_type_candidates(payload)

        info = self.analyzed.class_table[type_expr.base]
        arguments = list(type_expr.generic_args)
        if arguments and type_expr.base in BUILTIN_COLLECTION_LAYOUTS:
            candidates = (
                [TypeExpr(base="ListNode", generic_args=[arguments[0]])] if type_expr.base == "List" else arguments
            )
            return [
                runtime_type
                for candidate in candidates
                if self.values.is_arc(candidate)
                for runtime_type in self._runtime_type_candidates(candidate)
            ]

        substitutions = dict(zip(info.generic_params, arguments))
        candidates = (
            [
                self._substitute_type(field.type, substitutions)
                for _name, field in info.instance_storage
                if field.type is not None
            ]
            if substitutions
            else [field.type for _name, field in info.instance_storage if field.type is not None]
        )
        outgoing = []
        for candidate in candidates:
            if self.values.is_arc(candidate):
                outgoing.extend(self._runtime_type_candidates(candidate))
        return outgoing

    def _runtime_type_candidates(
        self,
        static_type: TypeExpr,
    ) -> list[TypeExpr]:
        candidates = [static_type]
        if static_type.generic_args or static_type.base not in self.analyzed.class_table:
            return candidates
        candidates.extend(
            TypeExpr(base=name)
            for name in self.analyzed.class_table
            if name != static_type.base and self._is_subclass(name, static_type.base)
        )
        return candidates

    def _is_subclass(self, child: str, parent: str) -> bool:
        current = child
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            info = self.analyzed.class_table.get(current)
            current = info.parent if info is not None else None
            if current == parent:
                return True
        return False

    def _substitute_type(
        self,
        type_expr: TypeExpr,
        substitutions: dict[str, TypeExpr],
    ) -> TypeExpr:
        try:
            result = self.type_identity.substitute(
                type_expr,
                substitutions,
                reference_resolver=self.values.canonical,
            )
        except TypeShapeError as error:
            raise CodegenError(str(error)) from error
        if result is None:
            raise CodegenError("cycle metadata requires a concrete field type")
        return result

    def _type_has_visit_action(
        self,
        type_expr: TypeExpr,
        seen: set[tuple],
    ) -> bool:
        return self.visit_action(type_expr, seen) is not None

    def _emitted_name(self, type_expr: TypeExpr) -> str:
        if type_expr.generic_args:
            return self.type_identity.specialization_symbol(
                type_expr.base,
                type_expr.generic_args,
            )
        return type_expr.base


__all__ = [
    "BUILTIN_COLLECTION_LAYOUTS",
    "CycleMetadata",
    "DirectVisitAction",
]
