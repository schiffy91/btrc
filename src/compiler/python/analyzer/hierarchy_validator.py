"""Pass-two inheritance, interface, and override validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import ClassDecl, InterfaceDecl, MethodDecl, Program, TypeExpr

if TYPE_CHECKING:
    from .analysis_context import AnalysisContext
    from .declarations.registry import DeclarationRegistry
    from .declarations.signature_types import SignatureTypePolicy


class HierarchyValidator:
    """Validate registered hierarchy contracts without analyzer inheritance."""

    def __init__(
        self,
        context: AnalysisContext,
        registry: DeclarationRegistry,
        signature_types: SignatureTypePolicy,
    ) -> None:
        self.context = context
        self.registry = registry
        self.signature_types = signature_types

    def validate(self, program: Program) -> None:
        self._validate_inheritance(program)
        self._validate_interfaces(program)
        self._validate_overrides(program)

    def _validate_inheritance(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl) or not declaration.parent:
                continue
            if declaration.parent not in self.registry.class_table:
                self.context.error(
                    f"Parent class '{declaration.parent}' not found",
                    declaration.line,
                    declaration.col,
                )
                continue
            parent_info = self.registry.class_table[declaration.parent]
            if declaration.generic_params or parent_info.generic_params:
                self.context.error(
                    "Generic class inheritance is not supported: "
                    f"class '{declaration.name}' extends '{declaration.parent}'",
                    declaration.line,
                    declaration.col,
                )
                continue
            seen = {declaration.name}
            parent = declaration.parent
            while parent and parent in self.registry.class_table:
                if parent in seen:
                    self.context.error(
                        f"Circular inheritance detected: '{declaration.name}' -> '{parent}'",
                        declaration.line,
                        declaration.col,
                    )
                    break
                seen.add(parent)
                parent = self.registry.class_table[parent].parent

    def _validate_interfaces(self, program: Program) -> None:
        self._validate_interface_redeclarations(program)
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl):
                continue
            class_info = self.registry.class_table.get(declaration.name)
            if class_info is None:
                continue
            for interface_name in class_info.interfaces:
                self._validate_interface(
                    declaration,
                    class_info,
                    interface_name,
                )
            self._validate_abstract_parent(declaration, class_info)

    def _validate_interface_redeclarations(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, InterfaceDecl) or not declaration.parent:
                continue
            parent = self.registry.interface_table.get(declaration.parent)
            if parent is None:
                continue
            for method in declaration.methods:
                inherited = parent.methods.get(method.name)
                if inherited is not None:
                    self._validate_signature(
                        declaration.name,
                        method,
                        inherited,
                        f"parent interface '{declaration.parent}'",
                    )

    def _validate_interface(self, declaration, class_info, interface_name) -> None:
        if interface_name not in self.registry.interface_table:
            self.context.error(
                f"Interface '{interface_name}' not found",
                declaration.line,
                declaration.col,
            )
            return
        interface = self.registry.interface_table[interface_name]
        substitutions = {
            parameter: TypeExpr(base=class_info.generic_params[index])
            for index, parameter in enumerate(interface.generic_params)
            if index < len(class_info.generic_params)
        }
        for method_name, signature in interface.methods.items():
            if method_name not in class_info.methods:
                self.context.error(
                    f"Class '{declaration.name}' does not implement interface "
                    f"method '{method_name}' from '{interface_name}'",
                    declaration.line,
                    declaration.col,
                )
                continue
            self._validate_signature(
                declaration.name,
                class_info.methods[method_name],
                signature,
                f"interface '{interface_name}'",
                substitutions,
            )

    def _validate_abstract_parent(self, declaration, class_info) -> None:
        if not class_info.parent or class_info.parent not in self.registry.class_table or class_info.is_abstract:
            return
        parent = self.registry.class_table[class_info.parent]
        if not parent.is_abstract:
            return
        own_methods = {member.name for member in declaration.members if isinstance(member, MethodDecl)}
        for method_name, method in parent.methods.items():
            if method.is_abstract and method_name not in own_methods:
                self.context.error(
                    f"Class '{declaration.name}' must implement abstract method "
                    f"'{method_name}' from '{class_info.parent}'",
                    declaration.line,
                    declaration.col,
                )

    def _validate_overrides(self, program: Program) -> None:
        for declaration in self.context.declarations(program):
            if not isinstance(declaration, ClassDecl) or not declaration.parent:
                continue
            parent = self.registry.class_table.get(declaration.parent)
            if parent is None:
                continue
            for member in declaration.members:
                if not isinstance(member, MethodDecl) or member.is_constructor:
                    continue
                parent_method = parent.methods.get(member.name)
                if parent_method is not None:
                    self._validate_signature(
                        declaration.name,
                        member,
                        parent_method,
                        f"parent class '{declaration.parent}'",
                    )

    def _validate_signature(
        self,
        class_name,
        implementation,
        expected,
        source,
        substitutions=None,
    ) -> None:
        name = implementation.name
        line = getattr(implementation, "line", 0)
        col = getattr(implementation, "col", 0)
        substitutions = dict(substitutions or {})
        actual_generics = list(getattr(implementation, "generic_params", ()))
        expected_generics = list(getattr(expected, "generic_params", ()))
        if len(actual_generics) != len(expected_generics):
            self.context.error(
                f"Override '{name}' in '{class_name}' has "
                f"{len(actual_generics)} generic parameter(s) (expected "
                f"{len(expected_generics)} from {source})",
                line,
                col,
            )
        elif expected_generics:
            substitutions.update(
                {
                    expected_name: TypeExpr(base=actual_name)
                    for expected_name, actual_name in zip(
                        expected_generics,
                        actual_generics,
                    )
                }
            )
        actual_static = getattr(implementation, "access", "") == "class"
        expected_static = getattr(expected, "access", "") == "class"
        if actual_static != expected_static:
            self.context.error(
                f"Override '{name}' in '{class_name}' changes the static/instance "
                f"calling convention (expected "
                f"{'static' if expected_static else 'instance'} from {source})",
                line,
                col,
            )
        if bool(getattr(implementation, "keep_return", False)) != bool(
            getattr(expected, "keep_return", False),
        ):
            self.context.error(
                f"Override '{name}' in '{class_name}' has incompatible keep-return ownership from {source}",
                line,
                col,
            )
        if bool(getattr(implementation, "is_gpu", False)) != bool(
            getattr(expected, "is_gpu", False),
        ):
            self.context.error(
                f"Override '{name}' in '{class_name}' changes @gpu execution from {source}",
                line,
                col,
            )
        expected_return = getattr(expected, "return_type", None)
        if substitutions:
            expected_return = self.signature_types.substitute(
                expected_return,
                substitutions,
            )
        actual_return = getattr(implementation, "return_type", None)
        if expected_return and actual_return and not self.signature_types.equal(expected_return, actual_return):
            self.context.error(
                f"Override '{name}' in '{class_name}' has incompatible "
                f"return type '{actual_return.base}' (expected "
                f"'{expected_return.base}' from {source})",
                line,
                col,
            )
        self._validate_parameters(
            class_name,
            implementation,
            expected,
            source,
            substitutions,
        )

    def _validate_parameters(
        self,
        class_name,
        implementation,
        expected,
        source,
        substitutions,
    ) -> None:
        actual_parameters = getattr(implementation, "params", [])
        expected_parameters = getattr(expected, "params", [])
        if len(actual_parameters) != len(expected_parameters):
            self.context.error(
                f"Override '{implementation.name}' in '{class_name}' has "
                f"{len(actual_parameters)} parameter(s) (expected "
                f"{len(expected_parameters)} from {source})",
                getattr(implementation, "line", 0),
                getattr(implementation, "col", 0),
            )
            return
        pairs = enumerate(zip(expected_parameters, actual_parameters), 1)
        for index, (expected_parameter, actual_parameter) in pairs:
            expected_type = expected_parameter.type
            if substitutions:
                expected_type = self.signature_types.substitute(
                    expected_type,
                    substitutions,
                )
            if not self.signature_types.equal(expected_type, actual_parameter.type):
                self.context.error(
                    f"Override '{implementation.name}' param {index} in "
                    f"'{class_name}' has incompatible type "
                    f"'{actual_parameter.type.base}' (expected "
                    f"'{expected_type.base}' from {source})",
                    getattr(implementation, "line", 0),
                    getattr(implementation, "col", 0),
                )
            if bool(getattr(expected_parameter, "keep", False)) != bool(
                getattr(actual_parameter, "keep", False),
            ):
                self.context.error(
                    f"Override '{implementation.name}' param {index} in "
                    f"'{class_name}' has incompatible keep ownership from "
                    f"{source}",
                    getattr(implementation, "line", 0),
                    getattr(implementation, "col", 0),
                )


__all__ = ["HierarchyValidator"]
