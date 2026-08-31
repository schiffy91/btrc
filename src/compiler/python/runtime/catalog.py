"""Owned runtime-helper indexing, validation, and selection."""

from __future__ import annotations

from collections.abc import Set

from .generated import RUNTIME_HELPER_ROWS, GeneratedRuntimeHelperRow


class RuntimeHelperCatalog:
    """Immutable indexed view of the generated runtime-helper specification."""

    def __init__(
        self,
        rows: tuple[GeneratedRuntimeHelperRow, ...] = RUNTIME_HELPER_ROWS,
    ) -> None:
        self._rows = rows
        self._index: dict[str, GeneratedRuntimeHelperRow] = {}
        type_providers: dict[str, str] = {}
        object_providers: dict[str, str] = {}
        categories: dict[str, list[GeneratedRuntimeHelperRow]] = {}
        stable_order: list[str] = []
        for definition in rows:
            if definition.name in self._index:
                raise ValueError(f"duplicate runtime helper registration: {definition.name}")
            self._index[definition.name] = definition
            for provided_type in definition.provided_types:
                previous = type_providers.get(provided_type)
                if previous is not None:
                    raise ValueError(
                        f"runtime type {provided_type} is provided by both {previous} and {definition.name}"
                    )
                type_providers[provided_type] = definition.name
            for provided_object in definition.provided_objects:
                previous = object_providers.get(provided_object)
                if previous is not None:
                    raise ValueError(
                        f"runtime object {provided_object} is provided by both {previous} and {definition.name}"
                    )
                object_providers[provided_object] = definition.name
            categories.setdefault(definition.category, []).append(definition)
            stable_order.append(definition.name)
        self._stable_order = tuple(stable_order)
        self._type_providers = type_providers
        self._object_providers = object_providers
        self._categories = {name: tuple(definitions) for name, definitions in categories.items()}
        self._source_visible_names = frozenset(definition.name for definition in rows if definition.source_visible)

    @property
    def definitions(self) -> tuple[GeneratedRuntimeHelperRow, ...]:
        """Definitions in the generated Python compiler's canonical order."""

        return self._rows

    @property
    def source_visible_names(self) -> frozenset[str]:
        """Helpers intentionally exposed to direct btrc source calls."""

        return self._source_visible_names

    @property
    def realtime_safe_names(self) -> frozenset[str]:
        """External helper symbols explicitly safe on realtime paths."""

        return frozenset(definition.name for definition in self._rows if definition.realtime_effect == "safe")

    def contains(self, name: str) -> bool:
        """Whether ``name`` is a generated runtime helper."""

        return name in self._index

    def definition(self, name: str) -> GeneratedRuntimeHelperRow:
        """Return one immutable definition, rejecting unknown helper names."""

        definition = self._index.get(name)
        if definition is None:
            raise ValueError(f"unknown runtime helper: {name}")
        return definition

    def definitions_in_category(self, category: str) -> tuple[GeneratedRuntimeHelperRow, ...]:
        """Return one generated runtime family in canonical Python order."""

        definitions = self._categories.get(category)
        if definitions is None:
            raise ValueError(f"unknown runtime helper category: {category}")
        return definitions

    def is_source_visible(self, name: str) -> bool:
        """Whether source code may name this runtime helper directly."""

        return name in self._source_visible_names

    def helper_names_providing_types(self, type_names: Set[str]) -> frozenset[str]:
        """Return the catalog helpers that own any requested C type."""

        return frozenset(
            provider for type_name in type_names if (provider := self._type_providers.get(type_name)) is not None
        )

    def helper_names_providing_objects(self, object_names: Set[str]) -> frozenset[str]:
        """Return the catalog helpers that own any requested C object."""

        return frozenset(
            provider
            for object_name in object_names
            if (provider := self._object_providers.get(object_name)) is not None
        )

    def definitions_for(
        self,
        roots: Set[str],
    ) -> tuple[GeneratedRuntimeHelperRow, ...]:
        """Return reachable definitions in dependency-first canonical order."""

        unknown = set(roots) - self._index.keys()
        if unknown:
            raise ValueError(f"unknown runtime helper(s): {', '.join(sorted(unknown))}")

        state: dict[str, int] = {}
        ordered: list[GeneratedRuntimeHelperRow] = []

        def visit(name: str, path: tuple[str, ...]) -> None:
            current = state.get(name, 0)
            if current == 2:
                return
            if current == 1:
                cycle = " -> ".join((*path, name))
                raise ValueError(f"runtime helper dependency cycle: {cycle}")
            state[name] = 1
            definition = self._index[name]
            for dependency in definition.depends_on:
                if dependency not in self._index:
                    raise ValueError(f"runtime helper {name} has unknown dependency {dependency}")
                visit(dependency, (*path, name))
            state[name] = 2
            ordered.append(definition)

        for name in self._stable_order:
            if name in roots:
                visit(name, ())
        return tuple(ordered)

    def selection(self) -> RuntimeHelperSelection:
        """Create isolated mutable roots for one lowering run."""

        return RuntimeHelperSelection(self)


class RuntimeHelperSelection:
    """Own helper roots selected by one compiler lowering run."""

    def __init__(self, catalog: RuntimeHelperCatalog | None = None) -> None:
        self._catalog = catalog or RuntimeHelperCatalog()
        self._roots: set[str] = set()

    @property
    def roots(self) -> frozenset[str]:
        return frozenset(self._roots)

    @property
    def source_visible_names(self) -> frozenset[str]:
        return self._catalog.source_visible_names

    def is_source_visible(self, name: str) -> bool:
        return self._catalog.is_source_visible(name)

    def use(self, name: str) -> None:
        """Select one root, rejecting misspellings at the call site."""

        if not self._catalog.contains(name):
            raise ValueError(f"unknown runtime helper: {name}")
        self._roots.add(name)

    def uses_any(self, names: Set[str]) -> bool:
        """Whether any selected root belongs to ``names``."""

        return not self._roots.isdisjoint(names)

    def definitions(self) -> tuple[GeneratedRuntimeHelperRow, ...]:
        """Materialize this selection's dependency-complete definition order."""

        return self._catalog.definitions_for(self._roots)


__all__ = ["RuntimeHelperCatalog", "RuntimeHelperSelection"]
