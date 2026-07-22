"""Inheritance, interface, and override validation."""

from ..ast_nodes import ClassDecl, InterfaceDecl, MethodDecl, TypeExpr


class HierarchyValidationMixin:
    def _validate_inherited_member_names(self, child, parent):
        own_fields = {name for name, owner in child.field_owners.items() if owner == child.name}
        own_methods = {
            name for name, owner in child.method_owners.items() if owner == child.name and name != child.name
        }
        own_properties = {name for name, owner in child.property_owners.items() if owner == child.name}
        conflicts = (
            (own_fields & parent.properties.keys())
            | (own_methods & parent.properties.keys())
            | (own_properties & (parent.fields.keys() | parent.methods.keys()))
        )
        for name in sorted(conflicts):
            member = child.fields.get(name) or child.methods.get(name) or child.properties.get(name)
            self._error(
                f"Member '{name}' in class '{child.name}' conflicts with an inherited member of a different kind",
                getattr(member, "line", 0),
                getattr(member, "col", 0),
            )
        parent_storage = {name for name, _member in parent.instance_storage}
        for storage_name, member in child.instance_storage:
            if storage_name in parent_storage:
                self._error(
                    f"Instance storage '{storage_name}' in class '{child.name}' conflicts with inherited storage",
                    getattr(member, "line", 0),
                    getattr(member, "col", 0),
                )

    def _validate_inheritance(self, program):
        """Check for circular inheritance and missing parent classes."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl) or not decl.parent:
                continue
            if decl.parent not in self.declarations.class_table:
                self._error(f"Parent class '{decl.parent}' not found", decl.line, decl.col)
                continue
            parent_info = self.declarations.class_table[decl.parent]
            if decl.generic_params or parent_info.generic_params:
                self._error(
                    f"Generic class inheritance is not supported: class '{decl.name}' extends '{decl.parent}'",
                    decl.line,
                    decl.col,
                )
                continue
            seen = {decl.name}
            parent = decl.parent
            while parent and parent in self.declarations.class_table:
                if parent in seen:
                    self._error(
                        f"Circular inheritance detected: '{decl.name}' -> '{parent}'",
                        decl.line,
                        decl.col,
                    )
                    break
                seen.add(parent)
                parent = self.declarations.class_table[parent].parent

    def _validate_interfaces(self, program):
        """Validate interface implementations and abstract constraints."""
        self._validate_interface_redeclarations(program)
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl):
                continue
            cls = self.declarations.class_table.get(decl.name)
            if not cls:
                continue
            for interface_name in cls.interfaces:
                self._validate_interface(decl, cls, interface_name)
            self._validate_abstract_parent(decl, cls)

    def _validate_interface_redeclarations(self, program):
        """Require child interfaces to preserve inherited method contracts."""
        for declaration in self._decls_with_file(program):
            if not isinstance(declaration, InterfaceDecl) or not declaration.parent:
                continue
            parent = self.declarations.interface_table.get(declaration.parent)
            if parent is None:
                continue
            for method in declaration.methods:
                inherited = parent.methods.get(method.name)
                if inherited is not None:
                    self._check_signature_compat(
                        declaration.name,
                        method,
                        inherited,
                        f"parent interface '{declaration.parent}'",
                    )

    def _validate_interface(self, decl, cls, interface_name):
        if interface_name not in self.declarations.interface_table:
            self._error(f"Interface '{interface_name}' not found", decl.line, decl.col)
            return
        interface = self.declarations.interface_table[interface_name]
        substitutions = {
            parameter: TypeExpr(base=cls.generic_params[index])
            for index, parameter in enumerate(interface.generic_params)
            if index < len(cls.generic_params)
        }
        for method_name, signature in interface.methods.items():
            if method_name not in cls.methods:
                self._error(
                    f"Class '{decl.name}' does not implement interface method '{method_name}' from '{interface_name}'",
                    decl.line,
                    decl.col,
                )
                continue
            self._check_signature_compat(
                decl.name,
                cls.methods[method_name],
                signature,
                f"interface '{interface_name}'",
                substitutions,
            )

    def _validate_abstract_parent(self, decl, cls):
        if not cls.parent or cls.parent not in self.declarations.class_table or cls.is_abstract:
            return
        parent = self.declarations.class_table[cls.parent]
        if not parent.is_abstract:
            return
        own_methods = {member.name for member in decl.members if isinstance(member, MethodDecl)}
        for method_name, method in parent.methods.items():
            if method.is_abstract and method_name not in own_methods:
                self._error(
                    f"Class '{decl.name}' must implement abstract method '{method_name}' from '{cls.parent}'",
                    decl.line,
                    decl.col,
                )

    def _validate_overrides(self, program):
        """Validate that method overrides have compatible signatures."""
        for decl in self._decls_with_file(program):
            if not isinstance(decl, ClassDecl) or not decl.parent:
                continue
            parent = self.declarations.class_table.get(decl.parent)
            if not parent:
                continue
            for member in decl.members:
                if not isinstance(member, MethodDecl) or member.is_constructor:
                    continue
                parent_method = parent.methods.get(member.name)
                if parent_method:
                    self._check_signature_compat(
                        decl.name,
                        member,
                        parent_method,
                        f"parent class '{decl.parent}'",
                    )

    def _check_signature_compat(self, class_name, impl, expected, source, substitutions=None):
        name = impl.name
        line = getattr(impl, "line", 0)
        col = getattr(impl, "col", 0)
        substitutions = dict(substitutions or {})
        actual_generics = list(getattr(impl, "generic_params", ()))
        expected_generics = list(getattr(expected, "generic_params", ()))
        if len(actual_generics) != len(expected_generics):
            self._error(
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
        actual_static = getattr(impl, "access", "") == "class"
        expected_static = getattr(expected, "access", "") == "class"
        if actual_static != expected_static:
            self._error(
                f"Override '{name}' in '{class_name}' changes the static/instance "
                f"calling convention (expected "
                f"{'static' if expected_static else 'instance'} from {source})",
                line,
                col,
            )
        if bool(getattr(impl, "keep_return", False)) != bool(getattr(expected, "keep_return", False)):
            self._error(
                f"Override '{name}' in '{class_name}' has incompatible keep-return ownership from {source}",
                line,
                col,
            )
        if bool(getattr(impl, "is_gpu", False)) != bool(getattr(expected, "is_gpu", False)):
            self._error(
                f"Override '{name}' in '{class_name}' changes @gpu execution from {source}",
                line,
                col,
            )
        expected_return = getattr(expected, "return_type", None)
        if substitutions:
            expected_return = self._substitute_type(expected_return, substitutions)
        actual_return = getattr(impl, "return_type", None)
        if expected_return and actual_return and not self._types_equal(expected_return, actual_return):
            self._error(
                f"Override '{name}' in '{class_name}' has incompatible "
                f"return type '{actual_return.base}' (expected "
                f"'{expected_return.base}' from {source})",
                line,
                col,
            )
        self._check_parameter_signatures(class_name, impl, expected, source, substitutions)

    def _check_parameter_signatures(self, class_name, impl, expected, source, substitutions):
        actual_params = getattr(impl, "params", [])
        expected_params = getattr(expected, "params", [])
        if len(actual_params) != len(expected_params):
            self._error(
                f"Override '{impl.name}' in '{class_name}' has "
                f"{len(actual_params)} parameter(s) (expected "
                f"{len(expected_params)} from {source})",
                getattr(impl, "line", 0),
                getattr(impl, "col", 0),
            )
            return
        for index, (expected_param, actual_param) in enumerate(zip(expected_params, actual_params), 1):
            expected_type = expected_param.type
            if substitutions:
                expected_type = self._substitute_type(expected_type, substitutions)
            if not self._types_equal(expected_type, actual_param.type):
                self._error(
                    f"Override '{impl.name}' param {index} in '{class_name}' "
                    f"has incompatible type '{actual_param.type.base}' "
                    f"(expected '{expected_type.base}' from {source})",
                    getattr(impl, "line", 0),
                    getattr(impl, "col", 0),
                )
            if bool(getattr(expected_param, "keep", False)) != bool(getattr(actual_param, "keep", False)):
                self._error(
                    f"Override '{impl.name}' param {index} in '{class_name}' "
                    f"has incompatible keep ownership from {source}",
                    getattr(impl, "line", 0),
                    getattr(impl, "col", 0),
                )
