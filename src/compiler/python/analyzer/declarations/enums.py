"""Registration of simple and payload-carrying enum declarations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hosted_abi import hosted_owned_name

if TYPE_CHECKING:
    from .registry import DeclarationRegistry
    from .top_level import TopLevelRegistrar


class EnumRegistrar:
    def __init__(
        self,
        registry: DeclarationRegistry,
        names: TopLevelRegistrar,
    ) -> None:
        self.registry = registry
        self.names = names

    def register_simple(self, declaration) -> None:
        registry = self.registry
        context = registry.context
        policy = registry.policy
        if not declaration.values:
            context.error(
                f"Enum '{declaration.name or '<anonymous>'}' requires at least one value",
                declaration.line,
                declaration.col,
            )
        if declaration.name:
            self.names.claim_name(
                declaration.name,
                "enum",
                declaration.name_line or declaration.line,
                declaration.name_col or declaration.col,
            )
            registry.declared_type_names.add(declaration.name)
        values = []
        seen = set()
        for value in declaration.values:
            valid_name = policy.validate_name(
                value.name,
                "Enum value",
                value.line,
                value.col,
                c_name_generated=bool(declaration.name),
            )
            if valid_name and not declaration.name and hosted_owned_name(value.name):
                context.error(
                    f"Enum value name '{value.name}' collides with a compiler-owned hosted C symbol",
                    value.line,
                    value.col,
                )
            if value.name in seen:
                context.error(
                    f"Duplicate enum value '{value.name}' in enum '{declaration.name}'",
                    value.line,
                    value.col,
                )
            seen.add(value.name)
            values.append(value.name)
            registry.enum_member_owners.setdefault(value.name, set()).add(
                declaration.name,
            )
            if not declaration.name:
                self.names.claim_name(
                    value.name,
                    "anonymous enum value",
                    value.line,
                    value.col,
                )
        key = declaration.name or ""
        if key in registry.enum_table and declaration.name:
            return
        if declaration.name:
            registry.enum_table[key] = values
        else:
            registry.enum_table.setdefault("", []).extend(values)

    def register_rich(self, declaration) -> None:
        registry = self.registry
        context = registry.context
        policy = registry.policy
        if not declaration.variants:
            context.error(
                f"Rich enum '{declaration.name}' requires at least one variant",
                declaration.line,
                declaration.col,
            )
        self.names.claim_name(
            declaration.name,
            "enum",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        registry.declared_type_names.add(declaration.name)
        variants = set()
        for variant in declaration.variants:
            policy.validate_name(
                variant.name,
                "Rich-enum variant",
                variant.line,
                variant.col,
                c_name_generated=True,
            )
            if variant.name in variants:
                context.error(
                    f"Duplicate variant '{variant.name}' in rich enum '{declaration.name}'",
                    variant.line,
                    variant.col,
                )
            variants.add(variant.name)
            policy.validate_parameter_names(
                variant.params,
                f"rich-enum variant '{declaration.name}.{variant.name}'",
            )
        registry.rich_enum_table[declaration.name] = declaration


__all__ = ["EnumRegistrar"]
