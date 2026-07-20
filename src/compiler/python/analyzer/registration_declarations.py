"""Pass-one registration for top-level values and C-facing types."""

from dataclasses import replace

from ..hosted_abi import hosted_owned_name
from ..type_identity import type_shape_key
from .core import SymbolInfo
from .preprocessor_names import collect_source_macro_names


class DeclarationRegistrationMixin:
    def _initialize_registration_state(self, program) -> None:
        self._top_level_kinds: dict[str, str] = {}
        self._source_macro_names = collect_source_macro_names(
            self,
            self._decls_with_file(program),
        )
        self._enum_member_owners: dict[str, set[str]] = {}
        self._enum_constant_values: dict[tuple[str, str], int | None] = {}
        self._global_declarations: dict[str, object] = {}
        self._global_definitions: dict[str, object] = {}
        self._struct_definitions: dict[str, object] = {}

    def _register_simple_enum(self, declaration) -> None:
        if not declaration.values:
            self._error(
                f"Enum '{declaration.name or '<anonymous>'}' requires at least one value",
                declaration.line,
                declaration.col,
            )
        if declaration.name:
            self._claim_top_level_name(
                declaration.name,
                "enum",
                declaration.name_line or declaration.line,
                declaration.name_col or declaration.col,
            )
            self.declared_type_names.add(declaration.name)
        values = []
        seen = set()
        for value in declaration.values:
            valid_name = self._validate_declared_name(
                value.name,
                "Enum value",
                value.line,
                value.col,
                c_name_generated=bool(declaration.name),
            )
            if valid_name and not declaration.name and hosted_owned_name(value.name):
                self._error(
                    f"Enum value name '{value.name}' collides with a compiler-owned hosted C symbol",
                    value.line,
                    value.col,
                )
            if value.name in seen:
                self._error(
                    f"Duplicate enum value '{value.name}' in enum '{declaration.name}'",
                    value.line,
                    value.col,
                )
            seen.add(value.name)
            values.append(value.name)
            self._enum_member_owners.setdefault(value.name, set()).add(declaration.name)
            if not declaration.name:
                self._claim_top_level_name(
                    value.name,
                    "anonymous enum value",
                    value.line,
                    value.col,
                )
        key = declaration.name or ""
        if key in self.enum_table and declaration.name:
            return
        if declaration.name:
            self.enum_table[key] = values
        else:
            self.enum_table.setdefault("", []).extend(values)

    def _register_rich_enum(self, declaration) -> None:
        if not declaration.variants:
            self._error(
                f"Rich enum '{declaration.name}' requires at least one variant",
                declaration.line,
                declaration.col,
            )
        self._claim_top_level_name(
            declaration.name,
            "enum",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
        )
        self.declared_type_names.add(declaration.name)
        variants = set()
        for variant in declaration.variants:
            self._validate_declared_name(
                variant.name,
                "Rich-enum variant",
                variant.line,
                variant.col,
                c_name_generated=True,
            )
            if variant.name in variants:
                self._error(
                    f"Duplicate variant '{variant.name}' in rich enum '{declaration.name}'",
                    variant.line,
                    variant.col,
                )
            variants.add(variant.name)
            self._validate_parameter_names(
                variant.params,
                f"rich-enum variant '{declaration.name}.{variant.name}'",
            )
        self.rich_enum_table[declaration.name] = declaration

    def _register_struct(self, declaration) -> None:
        if not declaration.name:
            self._error("anonymous struct at top level must be named", declaration.line, declaration.col)
            return
        self._claim_top_level_name(
            declaration.name,
            "struct",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=self._hosted_type_declaration_allowed(declaration),
        )
        self.declared_type_names.add(declaration.name)
        if not declaration.is_forward:
            if not declaration.fields:
                self._error(
                    f"Struct '{declaration.name}' cannot have an empty body under strict C11",
                    declaration.line,
                    declaration.col,
                )
            seen = set()
            for field in declaration.fields:
                self._validate_declared_name(field.name, "Struct field", field.line, field.col)
                if field.name in seen:
                    self._error(
                        f"Duplicate field '{field.name}' in struct '{declaration.name}'",
                        field.line,
                        field.col,
                    )
                seen.add(field.name)
            if declaration.name in self._struct_definitions:
                self._error(
                    f"Duplicate definition of struct '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                )
            else:
                self._struct_definitions[declaration.name] = declaration
                self.struct_table[declaration.name] = declaration
        elif declaration.name not in self.struct_table:
            self.struct_table[declaration.name] = declaration

    def _register_function(self, declaration) -> None:
        self._claim_top_level_name(
            declaration.name,
            "function",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_prototype=declaration.body is None,
            c_name_generated=declaration.body is not None,
        )
        self._validate_parameter_names(declaration.params, f"function '{declaration.name}'")
        existing = self.function_table.get(declaration.name)
        if existing is None:
            self.function_table[declaration.name] = declaration
            return
        compatible = self._function_declarations_compatible(existing, declaration)
        if not compatible:
            self._error(
                f"Conflicting declarations for function '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        if existing.body is not None and declaration.body is not None:
            self._error(
                f"Duplicate function name '{declaration.name}': duplicate definition",
                declaration.line,
                declaration.col,
            )
            return
        if declaration.body is not None:
            self._merge_function_defaults(declaration, existing)
            self.function_table[declaration.name] = declaration
        else:
            self._merge_function_defaults(existing, declaration)

    def _register_global(self, declaration) -> None:
        self._claim_top_level_name(
            declaration.name,
            "global",
            declaration.name_line or declaration.line,
            declaration.name_col or declaration.col,
            allow_same=True,
            trusted_hosted=self._hosted_object_declaration_allowed(declaration),
        )
        previous = self._global_declarations.get(declaration.name)
        if previous is not None and not self._global_types_compatible(previous.type, declaration.type):
            self._error(
                f"Conflicting types for global '{declaration.name}'",
                declaration.line,
                declaration.col,
            )
        is_extern_declaration = bool(
            declaration.type and declaration.type.is_extern and declaration.initializer is None
        )
        if not is_extern_declaration:
            if declaration.name in self._global_definitions:
                self._error(
                    f"Duplicate definition of global '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                )
            else:
                self._global_definitions[declaration.name] = declaration
        chosen = self._global_definitions.get(declaration.name, previous or declaration)
        self._global_declarations[declaration.name] = chosen
        symbol_type = chosen.type if chosen is not None else declaration.type
        self.global_scope.define(
            declaration.name,
            SymbolInfo(
                declaration.name,
                symbol_type,
                "global",
                decl_line=declaration.name_line or declaration.line,
                decl_col=declaration.name_col or declaration.col,
                decl_file=self.current_source_file,
            ),
        )

    @staticmethod
    def _global_types_compatible(left, right) -> bool:
        if left is None or right is None:
            return left is right
        left = replace(left, is_extern=False)
        right = replace(right, is_extern=False)
        return type_shape_key(left) == type_shape_key(right)

    def _claim_top_level_name(
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
        if kind != "function" and not trusted_hosted and hosted_owned_name(name):
            self._error(
                f"{kind.capitalize()} name '{name}' collides with a compiler-owned hosted C symbol",
                line,
                col,
            )
        self._validate_declared_name(
            name,
            kind.capitalize(),
            line,
            col,
            file_scope=True,
            trusted_prototype=trusted_prototype,
            trusted_hosted=trusted_hosted,
            c_name_generated=c_name_generated,
        )
        existing = self._top_level_kinds.get(name)
        if existing is None:
            self._top_level_kinds[name] = kind
        elif existing == kind:
            if not allow_same:
                self._error(f"Duplicate {kind} name '{name}'", line, col)
        else:
            self._error(
                f"Top-level name '{name}' is declared as both {existing} and {kind}",
                line,
                col,
            )


__all__ = ["DeclarationRegistrationMixin"]
