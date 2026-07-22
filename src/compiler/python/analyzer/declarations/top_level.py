"""Registration of top-level values, enums, structs, and macros."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ...hosted_abi import hosted_owned_name
from ...type_identity import type_shape_key
from ..core_models import SymbolInfo
from .enums import EnumRegistrar
from .source_macros import collect_source_macros

if TYPE_CHECKING:
    from .registry import DeclarationRegistry


class TopLevelRegistrar:
    def __init__(self, registry: DeclarationRegistry) -> None:
        self.registry = registry
        self.enums = EnumRegistrar(registry, self)

    @property
    def context(self):
        return self.registry.context

    @property
    def policy(self):
        return self.registry.policy

    def initialize(self, program) -> None:
        registry = self.registry
        registry.top_level_kinds = {}
        registry.source_macro_names, registry.source_macro_definitions = collect_source_macros(
            self.context.declarations(program),
            self.context,
        )
        registry.enum_member_owners = {}
        registry.enum_constant_values = {}
        registry.global_declarations = {}
        registry.global_definitions = {}
        registry.struct_definitions = {}

    def register_struct(self, declaration) -> None:
        registry = self.registry
        if not declaration.name:
            self.context.error(
                "anonymous struct at top level must be named",
                declaration.line,
                declaration.col,
            )
            return
        self.claim_name(
            declaration.name,
            "struct",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=self.policy.hosted.type_declaration_allowed(declaration),
        )
        registry.declared_type_names.add(declaration.name)
        if not declaration.is_forward:
            if not declaration.fields:
                self.context.error(
                    f"Struct '{declaration.name}' cannot have an empty body under strict C11",
                    declaration.line,
                    declaration.col,
                )
            seen = set()
            for field in declaration.fields:
                self.policy.validate_name(
                    field.name,
                    "Struct field",
                    field.line,
                    field.col,
                )
                if field.name in seen:
                    self.context.error(
                        f"Duplicate field '{field.name}' in struct '{declaration.name}'",
                        field.line,
                        field.col,
                    )
                seen.add(field.name)
            if declaration.name in registry.struct_definitions:
                self.context.error(
                    f"Duplicate definition of struct '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                )
            else:
                registry.struct_definitions[declaration.name] = declaration
                registry.struct_table[declaration.name] = declaration
        elif declaration.name not in registry.struct_table:
            registry.struct_table[declaration.name] = declaration

    def register_function(self, declaration) -> None:
        registry = self.registry
        self.claim_name(
            declaration.name,
            "function",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_prototype=declaration.body is None,
            c_name_generated=declaration.body is not None,
        )
        self.policy.validate_parameter_names(
            declaration.params,
            f"function '{declaration.name}'",
        )
        existing = registry.function_table.get(declaration.name)
        if existing is None:
            registry.function_table[declaration.name] = declaration
            return
        if not self.policy.callables.declarations_compatible(existing, declaration):
            self.context.error(
                f"Conflicting declarations for function '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        if existing.body is not None and declaration.body is not None:
            self.context.error(
                f"Duplicate function name '{declaration.name}': duplicate definition",
                declaration.line,
                declaration.col,
            )
            return
        if declaration.body is not None:
            self.policy.callables.merge_defaults(declaration, existing)
            registry.function_table[declaration.name] = declaration
        else:
            self.policy.callables.merge_defaults(existing, declaration)

    def register_global(self, declaration) -> None:
        registry = self.registry
        self.claim_name(
            declaration.name,
            "global",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=self.policy.hosted.object_declaration_allowed(declaration),
        )
        previous = registry.global_declarations.get(declaration.name)
        if previous is not None and not self._global_types_compatible(previous.type, declaration.type):
            self.context.error(
                f"Conflicting types for global '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        is_extern = bool(declaration.type and declaration.type.is_extern and declaration.initializer is None)
        if not is_extern:
            if declaration.name in registry.global_definitions:
                self.context.error(
                    f"Duplicate definition of global '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                )
            else:
                registry.global_definitions[declaration.name] = declaration
        chosen = registry.global_definitions.get(declaration.name, previous or declaration)
        registry.global_declarations[declaration.name] = chosen
        symbol_type = chosen.type if chosen is not None else declaration.type
        registry.global_scope.define(
            declaration.name,
            SymbolInfo(
                declaration.name,
                symbol_type,
                "global",
                decl_line=declaration.name_line or declaration.line,
                decl_col=declaration.name_col or declaration.col,
                decl_file=self.context.current_source_file,
            ),
        )

    def claim_name(
        self,
        name,
        kind,
        line,
        col,
        *,
        allow_same=False,
        trusted_prototype=False,
        trusted_hosted=False,
        c_name_generated=False,
    ) -> None:
        registry = self.registry
        if kind != "function" and not trusted_hosted and hosted_owned_name(name):
            self.context.error(
                f"{kind.capitalize()} name '{name}' collides with a compiler-owned hosted C symbol",
                line,
                col,
            )
        self.policy.validate_name(
            name,
            kind.capitalize(),
            line,
            col,
            file_scope=True,
            trusted_prototype=trusted_prototype,
            trusted_hosted=trusted_hosted,
            c_name_generated=c_name_generated,
        )
        existing = registry.top_level_kinds.get(name)
        if existing is None:
            registry.top_level_kinds[name] = kind
        elif existing == kind:
            if not allow_same:
                self.context.error(f"Duplicate {kind} name '{name}'", line, col)
        else:
            self.context.error(
                f"Top-level name '{name}' is declared as both {existing} and {kind}",
                line,
                col,
            )

    @staticmethod
    def _global_types_compatible(left, right) -> bool:
        if left is None or right is None:
            return left is right
        return type_shape_key(replace(left, is_extern=False)) == type_shape_key(replace(right, is_extern=False))


__all__ = ["TopLevelRegistrar"]
