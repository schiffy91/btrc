"""Order-independent validation of registered declaration signatures."""

from ..ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)


class RegisteredDeclarationValidationMixin:
    def _validate_registered_declarations(self, program) -> None:
        declarations = list(self._decls_with_file(program))
        for declaration in declarations:
            if isinstance(declaration, EnumDecl):
                self._validate_enum_declaration(declaration)
        for declaration in declarations:
            if isinstance(declaration, FunctionDecl):
                self._validate_function_signature_types(declaration)
            elif isinstance(declaration, ClassDecl):
                self._validate_class_declaration_types(declaration)
            elif isinstance(declaration, InterfaceDecl):
                self._validate_interface_declaration_types(declaration)
            elif isinstance(declaration, StructDecl) and not declaration.is_forward:
                for field in declaration.fields:
                    self._validate_declared_type(
                        field.type,
                        f"Struct field '{declaration.name}.{field.name}'",
                        field.line,
                        field.col,
                        role="field",
                    )
                    self._validate_array_bound(
                        field.type,
                        f"struct field '{declaration.name}.{field.name}'",
                        "field",
                    )
            elif isinstance(declaration, RichEnumDecl):
                for variant in declaration.variants:
                    for parameter in variant.params:
                        self._validate_declared_type(
                            parameter.type,
                            f"Rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                            parameter.line,
                            parameter.col,
                            role="field",
                        )
                        self._validate_array_bound(
                            parameter.type,
                            f"rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                            "field",
                        )
            elif isinstance(declaration, TypedefDecl):
                self._validate_declared_type(
                    declaration.original,
                    f"Typedef '{declaration.alias}'",
                    declaration.line,
                    declaration.col,
                    role="return",
                )
                self._validate_array_bound(
                    declaration.original,
                    f"typedef '{declaration.alias}'",
                    "global",
                )

    def _validate_function_signature_types(self, function) -> None:
        self._validate_hosted_abi_declaration(function)
        self._validate_declared_type(
            function.return_type,
            f"Return type of function '{function.name}'",
            function.line,
            function.col,
            role="return",
        )
        for parameter in function.params:
            self._validate_declared_type(
                parameter.type,
                f"Parameter '{function.name}.{parameter.name}'",
                parameter.line,
                parameter.col,
                role="parameter",
            )
        self._validate_array_bound(
            function.return_type,
            f"return type of function '{function.name}'",
            "local",
        )
        self._validate_parameter_bounds(function.params, function.name)
        self._validate_main_signature(function)

    def _validate_class_declaration_types(self, declaration) -> None:
        class_parameters = set(declaration.generic_params)
        for member in declaration.members:
            if isinstance(member, FieldDecl):
                self._validate_declared_type(
                    member.type,
                    f"Field '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="field",
                    active_type_params=class_parameters,
                )
                self._validate_class_field_contract(declaration, member)
            elif isinstance(member, PropertyDecl):
                self._validate_declared_type(
                    member.type,
                    f"Property '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="field",
                    active_type_params=class_parameters,
                )
                self._validate_property_storage(declaration, member)
            elif isinstance(member, MethodDecl):
                active = class_parameters | set(member.generic_params)
                return_active = active
                if member.is_constructor and not member.return_type.generic_args:
                    # A generic constructor spells the owning type without
                    # repeating its class arguments: ``Box(T value)`` inside
                    # ``class Box<T>`` constructs the active specialization.
                    return_active = active | {declaration.name}
                self._validate_declared_type(
                    member.return_type,
                    f"Return type of method '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="return",
                    active_type_params=return_active,
                )
                for parameter in member.params:
                    self._validate_declared_type(
                        parameter.type,
                        f"Parameter '{declaration.name}.{member.name}.{parameter.name}'",
                        parameter.line,
                        parameter.col,
                        role="parameter",
                        active_type_params=active,
                    )
                self._validate_array_bound(
                    member.return_type,
                    f"return type of method '{declaration.name}.{member.name}'",
                    "local",
                )
                self._validate_parameter_bounds(
                    member.params,
                    f"{declaration.name}.{member.name}",
                )
                self._validate_class_callable_shape(declaration, member)

    def _validate_interface_declaration_types(self, declaration) -> None:
        active = set(declaration.generic_params)
        for method in declaration.methods:
            self._validate_declared_type(
                method.return_type,
                f"Return type of interface method '{declaration.name}.{method.name}'",
                method.line,
                method.col,
                role="return",
                active_type_params=active,
            )
            for parameter in method.params:
                self._validate_declared_type(
                    parameter.type,
                    f"Parameter '{declaration.name}.{method.name}.{parameter.name}'",
                    parameter.line,
                    parameter.col,
                    role="parameter",
                    active_type_params=active,
                )
            self._validate_array_bound(
                method.return_type,
                f"return type of interface method '{declaration.name}.{method.name}'",
                "local",
            )
            self._validate_parameter_bounds(
                method.params,
                f"{declaration.name}.{method.name}",
            )


__all__ = ["RegisteredDeclarationValidationMixin"]
