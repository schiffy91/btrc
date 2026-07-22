"""Dependency-ordered class metadata inheritance."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import DeclarationRegistry


class InheritanceResolver:
    def __init__(self, registry: DeclarationRegistry) -> None:
        self.registry = registry

    def resolve(self, pre_resolved_classes=frozenset()) -> None:
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(name: str) -> None:
            if name in done or name in visiting:
                return
            visiting.add(name)
            info = self.registry.class_table.get(name)
            if info and info.parent and info.parent in self.registry.class_table:
                visit(info.parent)
            visiting.discard(name)
            done.add(name)
            order.append(name)

        for name in self.registry.class_table:
            visit(name)
        for name in order:
            info = self.registry.class_table[name]
            if id(info) not in pre_resolved_classes:
                self._merge_parent(info)

    def claim_member_name(self, declaration, member, kind, declared) -> None:
        existing = declared.get(member.name)
        if existing and existing != kind and "property" in (existing, kind):
            self.registry.services.error(
                f"Member '{member.name}' in class '{declaration.name}' is declared as both {existing} and {kind}",
                member.line,
                member.col,
            )
        declared[member.name] = kind

    def _merge_parent(self, info) -> None:
        registry = self.registry
        if not info.parent or info.parent not in registry.class_table:
            return
        parent = registry.class_table[info.parent]
        registry.services.validate_inherited_member_names(info, parent)
        own_fields = {name: field for name, field in info.fields.items() if name not in parent.fields}
        info.fields = {**parent.fields, **own_fields}
        own_field_owners = {name: owner for name, owner in info.field_owners.items() if name not in parent.fields}
        info.field_owners = {**parent.field_owners, **own_field_owners}
        inherited_methods = {name: method for name, method in parent.methods.items() if not method.is_constructor}
        inherited_method_owners = {
            name: owner for name, owner in parent.method_owners.items() if not parent.methods[name].is_constructor
        }
        info.methods = {**inherited_methods, **info.methods}
        info.method_owners = {**inherited_method_owners, **info.method_owners}
        info.properties = {**parent.properties, **info.properties}
        info.property_owners = {**parent.property_owners, **info.property_owners}
        parent_storage_names = {name for name, _member in parent.instance_storage}
        info.instance_storage = [
            *parent.instance_storage,
            *(entry for entry in info.instance_storage if entry[0] not in parent_storage_names),
        ]


__all__ = ["InheritanceResolver"]
