"""Collision checks for C symbols synthesized from source declarations."""

from ..ast_nodes import ClassDecl, EnumDecl, FieldDecl, PropertyDecl, RichEnumDecl
from ..class_storage import property_needs_backing
from ..cycle_symbols import cycle_visitor_symbol
from ..type_identity import mangle_generic_symbol, substitute_type_expr

_CYCLE_COLLECTIONS = frozenset({"Vector", "Array", "List", "Map", "Set"})


class GeneratedSymbolContractsMixin:
    def _managed_storage_type(self, type_expr) -> bool:
        type_expr = self._canonical_type(type_expr)
        return bool(
            type_expr is not None
            and not type_expr.is_array
            and type_expr.pointer_depth <= 1
            and type_expr.base in self.class_table
        )

    def _class_needs_cycle_visitor(self, info) -> bool:
        return any(self._managed_storage_type(field.type) for _name, field in info.instance_storage)

    def _generic_needs_cycle_visitor(self, base_name, arguments, info) -> bool:
        if base_name in _CYCLE_COLLECTIONS:
            return base_name == "List" or any(self._managed_storage_type(argument) for argument in arguments)
        substitutions = dict(zip(info.generic_params, arguments))
        return any(
            self._managed_storage_type(
                substitute_type_expr(
                    field.type,
                    substitutions,
                    reference_resolver=self._canonical_type,
                )
            )
            for _name, field in info.instance_storage
        )

    def _validate_generated_c_symbols(self, program) -> None:
        claims: dict[str, str] = {}
        generic_declarations = {}
        for declaration in self._decls_with_file(program):
            if isinstance(declaration, ClassDecl):
                if declaration.generic_params:
                    generic_declarations[declaration.name] = declaration
                else:
                    self._claim_class_symbols(declaration, claims)
            elif isinstance(declaration, EnumDecl) and declaration.name:
                for value in declaration.values:
                    self._claim_generated_symbol(
                        f"{declaration.name}_{value.name}",
                        f"enum value '{declaration.name}.{value.name}'",
                        value.line,
                        value.col,
                        claims,
                    )
                self._claim_generated_symbol(
                    f"{declaration.name}_toString",
                    f"enum helper for '{declaration.name}'",
                    declaration.line,
                    declaration.col,
                    claims,
                )
            elif isinstance(declaration, RichEnumDecl):
                self._claim_rich_enum_symbols(declaration, claims)
        self._claim_generic_instance_symbols(generic_declarations, claims)

    def _claim_generic_instance_symbols(self, declarations, claims) -> None:
        for base_name, instances in self.generic_instances.items():
            declaration = declarations.get(base_name)
            info = self.class_table.get(base_name)
            if declaration is None or info is None:
                continue
            for arguments in instances:
                emitted_name = mangle_generic_symbol(base_name, arguments)
                owner = f"generic instance '{emitted_name}'"
                for suffix, role in (
                    ("init", "initializer"),
                    ("new", "allocator"),
                    ("destroy", "destructor"),
                ):
                    self._claim_generated_symbol(
                        f"{emitted_name}_{suffix}",
                        f"{role} for {owner}",
                        declaration.line,
                        declaration.col,
                        claims,
                    )
                if self._generic_needs_cycle_visitor(base_name, arguments, info):
                    self._claim_generated_symbol(
                        cycle_visitor_symbol(emitted_name),
                        f"cycle visitor for {owner}",
                        declaration.line,
                        declaration.col,
                        claims,
                    )
                self._claim_generic_member_symbols(emitted_name, owner, info, claims)

    def _claim_generic_member_symbols(self, emitted_name, owner, info, claims) -> None:
        for method_name, method in info.methods.items():
            if method.is_constructor or method_name == "__del__" or method.generic_params:
                continue
            self._claim_generated_symbol(
                f"{emitted_name}_{method_name}",
                f"method '{method_name}' for {owner}",
                method.line,
                method.col,
                claims,
            )
        for property_name, prop in info.properties.items():
            for enabled, prefix, role in (
                (prop.has_getter, "get", "getter"),
                (prop.has_setter, "set", "setter"),
            ):
                if enabled:
                    self._claim_generated_symbol(
                        f"{emitted_name}_{prefix}_{property_name}",
                        f"{role} '{property_name}' for {owner}",
                        prop.line,
                        prop.col,
                        claims,
                    )

    def _claim_class_symbols(self, declaration, claims) -> None:
        name = declaration.name
        for suffix, role in (
            ("init", "initializer"),
            ("new", "allocator"),
            ("destroy", "destructor"),
        ):
            self._claim_generated_symbol(
                f"{name}_{suffix}",
                f"{role} for class '{name}'",
                declaration.line,
                declaration.col,
                claims,
            )
        info = self.class_table[name]
        if self._class_needs_cycle_visitor(info):
            self._claim_generated_symbol(
                cycle_visitor_symbol(name),
                f"cycle visitor for class '{name}'",
                declaration.line,
                declaration.col,
                claims,
            )
        for method_name, method in info.methods.items():
            if method.is_constructor or method_name == "__del__":
                continue
            self._claim_generated_symbol(
                f"{name}_{method_name}",
                f"method '{name}.{method_name}'",
                method.line,
                method.col,
                claims,
            )
        for property_name, prop in info.properties.items():
            if prop.has_getter:
                self._claim_generated_symbol(
                    f"{name}_get_{property_name}",
                    f"getter '{name}.{property_name}'",
                    prop.line,
                    prop.col,
                    claims,
                )
            if prop.has_setter:
                self._claim_generated_symbol(
                    f"{name}_set_{property_name}",
                    f"setter '{name}.{property_name}'",
                    prop.line,
                    prop.col,
                    claims,
                )
        for member in declaration.members:
            if isinstance(member, FieldDecl) and member.access == "class":
                self._claim_generated_symbol(
                    f"{name}_{member.name}",
                    f"static field '{name}.{member.name}'",
                    member.line,
                    member.col,
                    claims,
                )
            elif isinstance(member, PropertyDecl) and property_needs_backing(member):
                self._reject_generated_member_macro(
                    f"_prop_{member.name}",
                    f"property backing field '{name}.{member.name}'",
                    member.line,
                    member.col,
                )
        self._reject_generated_member_macro(
            "__arc",
            f"ARC header field for class '{name}'",
            declaration.line,
            declaration.col,
        )
        self._reject_generated_member_macro(
            "__rc", f"reference count field for class '{name}'", declaration.line, declaration.col
        )
        self._reject_generated_member_macro(
            "__cycle_safe_rc",
            f"cycle proof field for class '{name}'",
            declaration.line,
            declaration.col,
        )

    def _claim_rich_enum_symbols(self, declaration, claims) -> None:
        name = declaration.name
        self._claim_generated_symbol(
            f"{name}_Tag",
            f"tag type for rich enum '{name}'",
            declaration.line,
            declaration.col,
            claims,
        )
        for variant in declaration.variants:
            for symbol, role in (
                (f"{name}_{variant.name}_TAG", "tag value"),
                (f"{name}_{variant.name}", "constructor"),
            ):
                self._claim_generated_symbol(
                    symbol,
                    f"{role} for rich-enum variant '{name}.{variant.name}'",
                    variant.line,
                    variant.col,
                    claims,
                )
            if variant.params:
                self._claim_generated_symbol(
                    f"{name}_{variant.name}_Data",
                    f"payload type for rich-enum variant '{name}.{variant.name}'",
                    variant.line,
                    variant.col,
                    claims,
                )
        self._claim_generated_symbol(
            f"{name}_toString",
            f"enum helper for '{name}'",
            declaration.line,
            declaration.col,
            claims,
        )

    def _claim_generated_symbol(self, symbol, owner, line, col, claims) -> None:
        source_kind = self._top_level_kinds.get(symbol)
        if source_kind is not None:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with source {source_kind} '{symbol}'",
                line,
                col,
            )
        if symbol in self._source_macro_names:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with source macro '{symbol}'",
                line,
                col,
            )
        previous = claims.get(symbol)
        if previous is not None:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with {previous}",
                line,
                col,
            )
        else:
            claims[symbol] = owner

    def _reject_generated_member_macro(self, symbol, owner, line, col) -> None:
        if symbol in self._source_macro_names:
            self._error(
                f"Generated C member '{symbol}' for {owner} collides with source macro '{symbol}'",
                line,
                col,
            )


__all__ = ["GeneratedSymbolContractsMixin"]
