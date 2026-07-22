"""Registration of top-level values, enums, structs, and macros."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ...ast_nodes import PreprocessorDirective
from ...hosted_abi import hosted_owned_name
from ...source_macros import source_macro_name, source_symbol_directive, source_undef_name
from ...type_identity import type_shape_key
from ..core_models import SymbolInfo
from ..declaration_names import c_file_scope_reserved_identifier, compiler_reserved_prefix

if TYPE_CHECKING:
    from .registry import DeclarationRegistry


class TopLevelRegistrar:
    def __init__(self, registry: DeclarationRegistry) -> None:
        self.registry = registry

    @property
    def services(self):
        return self.registry.services

    def initialize(self, program) -> None:
        registry = self.registry
        registry.top_level_kinds = {}
        registry.source_macro_names, registry.source_macro_definitions = self._collect_source_macros(
            self.services.declarations(program)
        )
        registry.enum_member_owners = {}
        registry.enum_constant_values = {}
        registry.global_declarations = {}
        registry.global_definitions = {}
        registry.struct_definitions = {}

    def register_simple_enum(self, declaration) -> None:
        registry = self.registry
        services = self.services
        if not declaration.values:
            services.error(
                f"Enum '{declaration.name or '<anonymous>'}' requires at least one value",
                declaration.line,
                declaration.col,
            )
        if declaration.name:
            self.claim_name(
                declaration.name,
                "enum",
                declaration.name_line or declaration.line,
                declaration.name_col or declaration.col,
            )
            registry.declared_type_names.add(declaration.name)
        values = []
        seen = set()
        for value in declaration.values:
            valid_name = services.validate_declared_name(
                value.name,
                "Enum value",
                value.line,
                value.col,
                c_name_generated=bool(declaration.name),
            )
            if valid_name and not declaration.name and hosted_owned_name(value.name):
                services.error(
                    f"Enum value name '{value.name}' collides with a compiler-owned hosted C symbol",
                    value.line,
                    value.col,
                )
            if value.name in seen:
                services.error(
                    f"Duplicate enum value '{value.name}' in enum '{declaration.name}'",
                    value.line,
                    value.col,
                )
            seen.add(value.name)
            values.append(value.name)
            registry.enum_member_owners.setdefault(value.name, set()).add(declaration.name)
            if not declaration.name:
                self.claim_name(value.name, "anonymous enum value", value.line, value.col)
        key = declaration.name or ""
        if key in registry.enum_table and declaration.name:
            return
        if declaration.name:
            registry.enum_table[key] = values
        else:
            registry.enum_table.setdefault("", []).extend(values)

    def register_rich_enum(self, declaration) -> None:
        registry = self.registry
        services = self.services
        if not declaration.variants:
            services.error(
                f"Rich enum '{declaration.name}' requires at least one variant",
                declaration.line,
                declaration.col,
            )
        self.claim_name(
            declaration.name,
            "enum",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        registry.declared_type_names.add(declaration.name)
        variants = set()
        for variant in declaration.variants:
            services.validate_declared_name(
                variant.name,
                "Rich-enum variant",
                variant.line,
                variant.col,
                c_name_generated=True,
            )
            if variant.name in variants:
                services.error(
                    f"Duplicate variant '{variant.name}' in rich enum '{declaration.name}'",
                    variant.line,
                    variant.col,
                )
            variants.add(variant.name)
            services.validate_parameter_names(
                variant.params,
                f"rich-enum variant '{declaration.name}.{variant.name}'",
            )
        registry.rich_enum_table[declaration.name] = declaration

    def register_struct(self, declaration) -> None:
        registry = self.registry
        services = self.services
        if not declaration.name:
            services.error("anonymous struct at top level must be named", declaration.line, declaration.col)
            return
        self.claim_name(
            declaration.name,
            "struct",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=services.hosted_type_declaration_allowed(declaration),
        )
        registry.declared_type_names.add(declaration.name)
        if not declaration.is_forward:
            if not declaration.fields:
                services.error(
                    f"Struct '{declaration.name}' cannot have an empty body under strict C11",
                    declaration.line,
                    declaration.col,
                )
            seen = set()
            for field in declaration.fields:
                services.validate_declared_name(field.name, "Struct field", field.line, field.col)
                if field.name in seen:
                    services.error(
                        f"Duplicate field '{field.name}' in struct '{declaration.name}'",
                        field.line,
                        field.col,
                    )
                seen.add(field.name)
            if declaration.name in registry.struct_definitions:
                services.error(
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
        services = self.services
        self.claim_name(
            declaration.name,
            "function",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_prototype=declaration.body is None,
            c_name_generated=declaration.body is not None,
        )
        services.validate_parameter_names(declaration.params, f"function '{declaration.name}'")
        existing = registry.function_table.get(declaration.name)
        if existing is None:
            registry.function_table[declaration.name] = declaration
            return
        if not services.function_declarations_compatible(existing, declaration):
            services.error(
                f"Conflicting declarations for function '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        if existing.body is not None and declaration.body is not None:
            services.error(
                f"Duplicate function name '{declaration.name}': duplicate definition",
                declaration.line,
                declaration.col,
            )
            return
        if declaration.body is not None:
            services.merge_function_defaults(declaration, existing)
            registry.function_table[declaration.name] = declaration
        else:
            services.merge_function_defaults(existing, declaration)

    def register_global(self, declaration) -> None:
        registry = self.registry
        services = self.services
        self.claim_name(
            declaration.name,
            "global",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=services.hosted_object_declaration_allowed(declaration),
        )
        previous = registry.global_declarations.get(declaration.name)
        if previous is not None and not self._global_types_compatible(previous.type, declaration.type):
            services.error(
                f"Conflicting types for global '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        is_extern = bool(declaration.type and declaration.type.is_extern and declaration.initializer is None)
        if not is_extern:
            if declaration.name in registry.global_definitions:
                services.error(
                    f"Duplicate definition of global '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                )
            else:
                registry.global_definitions[declaration.name] = declaration
        chosen = registry.global_definitions.get(declaration.name, previous or declaration)
        registry.global_declarations[declaration.name] = chosen
        symbol_type = chosen.type if chosen is not None else declaration.type
        services.global_scope.define(
            declaration.name,
            SymbolInfo(
                declaration.name,
                symbol_type,
                "global",
                decl_line=declaration.name_line or declaration.line,
                decl_col=declaration.name_col or declaration.col,
                decl_file=services.current_source_file(),
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
        services = self.services
        if kind != "function" and not trusted_hosted and hosted_owned_name(name):
            services.error(
                f"{kind.capitalize()} name '{name}' collides with a compiler-owned hosted C symbol",
                line,
                col,
            )
        services.validate_declared_name(
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
                services.error(f"Duplicate {kind} name '{name}'", line, col)
        else:
            services.error(
                f"Top-level name '{name}' is declared as both {existing} and {kind}",
                line,
                col,
            )

    def _collect_source_macros(self, declarations) -> tuple[set[str], dict[str, object]]:
        names: set[str] = set()
        definitions: dict[str, object] = {}
        for declaration in declarations:
            if not isinstance(declaration, PreprocessorDirective):
                continue
            name = source_macro_name(declaration.text)
            if name is not None:
                names.add(name)
                definitions[name] = source_symbol_directive(declaration.text)
                self._validate_macro_mutation(declaration, name, define=True)
                continue
            name = source_undef_name(declaration.text)
            if name is not None:
                definitions.pop(name, None)
                self._validate_macro_mutation(declaration, name, define=False)
        return names, definitions

    def _validate_macro_mutation(self, declaration, name, *, define) -> None:
        prefix = compiler_reserved_prefix(name)
        if prefix is not None:
            message = (
                f"Macro name '{name}' uses the compiler-reserved '{prefix}' prefix"
                if define
                else f"Source #undef of compiler-owned C symbol '{name}' is not allowed"
            )
        elif c_file_scope_reserved_identifier(name):
            subject = "Macro name" if define else "Source #undef name"
            message = f"{subject} '{name}' is reserved by C11 at file scope"
        elif hosted_owned_name(name):
            action = "Macro name" if define else "Source #undef of"
            message = f"{action} compiler-owned hosted C symbol '{name}' is not allowed"
        else:
            return
        self.services.error(message, declaration.line, declaration.col)

    @staticmethod
    def _global_types_compatible(left, right) -> bool:
        if left is None or right is None:
            return left is right
        return type_shape_key(replace(left, is_extern=False)) == type_shape_key(replace(right, is_extern=False))


__all__ = ["TopLevelRegistrar"]
