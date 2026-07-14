"""Dependency-ordered class member and storage inheritance."""


class InheritanceRegistrationMixin:
    def _resolve_class_parents(self, pre_resolved_classes=frozenset()):
        """Merge newly registered parent metadata in dependency order.

        ``pre_resolved_classes`` contains identities seeded by an incremental
        client such as the LSP.  Those objects already include inherited
        members and storage, so merging them again would misdiagnose inherited
        storage as a fresh child declaration.
        """
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(name: str):
            if name in done or name in visiting:
                return
            visiting.add(name)
            info = self.class_table.get(name)
            if info and info.parent and info.parent in self.class_table:
                visit(info.parent)
            visiting.discard(name)
            done.add(name)
            order.append(name)

        for name in self.class_table:
            visit(name)
        for name in order:
            info = self.class_table[name]
            if id(info) not in pre_resolved_classes:
                self._merge_class_parent(info)

    def _merge_class_parent(self, info) -> None:
        if not info.parent or info.parent not in self.class_table:
            return
        parent = self.class_table[info.parent]
        self._validate_inherited_member_names(info, parent)

        own_fields = {name: field for name, field in info.fields.items() if name not in parent.fields}
        info.fields = {**parent.fields, **own_fields}
        own_field_owners = {name: owner for name, owner in info.field_owners.items() if name not in parent.fields}
        info.field_owners = {**parent.field_owners, **own_field_owners}

        inherited_methods = {name: method for name, method in parent.methods.items() if not method.is_constructor}
        inherited_method_owners = {
            name: owner for name, owner in parent.method_owners.items() if not parent.methods[name].is_constructor
        }
        info.methods = {**inherited_methods, **info.methods}
        info.method_owners = {
            **inherited_method_owners,
            **info.method_owners,
        }
        info.properties = {**parent.properties, **info.properties}
        info.property_owners = {
            **parent.property_owners,
            **info.property_owners,
        }

        parent_storage_names = {storage_name for storage_name, _member in parent.instance_storage}
        info.instance_storage = [
            *parent.instance_storage,
            *(entry for entry in info.instance_storage if entry[0] not in parent_storage_names),
        ]

    def _claim_member_name(self, declaration, member, kind, declared):
        existing = declared.get(member.name)
        if existing and existing != kind and "property" in (existing, kind):
            self._error(
                f"Member '{member.name}' in class '{declaration.name}' is declared as both {existing} and {kind}",
                member.line,
                member.col,
            )
        declared[member.name] = kind


__all__ = ["InheritanceRegistrationMixin"]
