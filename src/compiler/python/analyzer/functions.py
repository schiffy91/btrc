"""Declaration, class, method, property, and function analysis."""

from ..ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    TypeExpr,
    VarDeclStmt,
)
from .core import SymbolInfo


class FunctionsMixin:
    def _analyze_decl(self, decl):
        if isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._analyze_var_decl(decl)
        elif isinstance(decl, (EnumDecl, RichEnumDecl)):
            # Registration owns enum tables; pass two must not append members
            # a second time.
            return

    def _analyze_class(self, decl):
        prev_class = self.current_class
        self.current_class = self.declarations.class_table[decl.name]
        for member in decl.members:
            if isinstance(member, FieldDecl):
                member.type = self._upgrade_class_type(member.type)
                self._collect_generic_instances(member.type)
                if member.initializer:
                    field_value_type = self._array_field_value_type(member)
                    if member.access == "class":
                        self._validate_pointer_backed_array_field_initializer(
                            member,
                            member.initializer,
                            f"Field '{decl.name}.{member.name}'",
                            member.line,
                            member.col,
                        )
                    self._analyze_expr(member.initializer)
                    self._validate_callable_storage(
                        field_value_type,
                        member.initializer,
                        True,
                        member.line,
                        member.col,
                    )
                    self._validate_typed_initializer(
                        field_value_type,
                        member.initializer,
                        f"Field '{decl.name}.{member.name}'",
                        member.line,
                        member.col,
                    )
            elif isinstance(member, MethodDecl):
                self._analyze_method(member)
            elif isinstance(member, PropertyDecl):
                self._analyze_property(member)
        self.current_class = prev_class

    def _analyze_method(self, method):
        prev_method = self.current_method
        prev_callable = self.current_callable
        self.current_method = method
        self.current_callable = method
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = method.is_gpu
        prev_return_type = self.current_return_type

        if method.is_gpu:
            self._error(
                "@gpu is only supported on top-level functions; methods have no WGSL dispatch lowering",
                method.line,
                method.col,
            )

        for param in method.params:
            param.type = self._upgrade_class_type(param.type)
        is_constructor = method.is_constructor
        self.current_return_type = TypeExpr(base="void") if is_constructor else method.return_type
        if not is_constructor:
            method.return_type = self._upgrade_class_type(method.return_type)
            self._validate_array_return_declaration(
                method,
                self.current_class.name if self.current_class else None,
            )
            self.current_return_type = self._array_value_type(method.return_type)

        self._push_scope()
        self._validate_default_params(method.params, method.line, method.col)

        if method.access != "class":
            self_type = self._current_self_type()
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
        for param in method.params:
            self._collect_generic_instances(param.type)
            if param.default is not None:
                parameter_value_type = self._array_parameter_value_type(param.type)
                self._validate_array_parameter_default(
                    param.type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or method.line,
                    param.col or method.col,
                )
                previous_parameter_default = self._analyzing_parameter_default
                previous_constructor_default = self._analyzing_constructor_default
                self._analyzing_parameter_default = True
                self._analyzing_constructor_default = is_constructor
                try:
                    self._analyze_expr(param.default)
                finally:
                    self._analyzing_parameter_default = previous_parameter_default
                    self._analyzing_constructor_default = previous_constructor_default
                self._validate_callable_storage(
                    parameter_value_type,
                    param.default,
                    True,
                    param.line or method.line,
                    param.col or method.col,
                )
                self._validate_typed_initializer(
                    parameter_value_type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or method.line,
                    param.col or method.col,
                )
            if self._claim_local_binding(
                param.name,
                "parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                self.scope.define(param.name, self._param_symbol(param))
        if not is_constructor:
            self._collect_generic_instances(method.return_type)
        self._analyze_root_block(method.body)

        if (
            not is_constructor
            and method.return_type
            and not self._is_nonpointer_void_object(method.return_type)
            and method.body
            and not self._block_must_terminate(method.body)
        ):
            class_name = self.current_class.name if self.current_class else ""
            self._error(
                f"Method '{class_name}.{method.name}' has non-void return type but no return statement",
                method.line,
                method.col,
            )

        self._pop_scope()
        self.current_method = prev_method
        self.current_callable = prev_callable
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type

    def _analyze_property(self, prop):
        """Analyze a C#-style property declaration."""
        self._collect_generic_instances(prop.type)
        prop.type = self._upgrade_class_type(prop.type)
        synthetic_method = MethodDecl(access=prop.access, return_type=prop.type, name=f"_prop_{prop.name}")
        prev_method = self.current_method
        prev_return_type = self.current_return_type
        self.current_method = synthetic_method
        if prop.getter_body:
            self.current_return_type = self._array_value_type(prop.type)
            self._push_scope()
            self_type = self._current_self_type()
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self._analyze_root_block(prop.getter_body)
            if not self._block_must_terminate(prop.getter_body):
                self._error(
                    f"Property getter '{self.current_class.name}.{prop.name}' does not return a value on every path",
                    prop.line,
                    prop.col,
                )
            self._pop_scope()
        if prop.setter_body:
            self.current_return_type = TypeExpr(base="void")
            previous_virtual_setter = self.in_virtual_setter
            self.in_virtual_setter = True
            self._push_scope()
            self_type = self._current_self_type()
            self.scope.define("self", SymbolInfo("self", self_type, "param"))
            self.scope.define(
                "value",
                SymbolInfo(
                    "value",
                    self._array_parameter_value_type(prop.type),
                    "param",
                ),
            )
            self._analyze_root_block(prop.setter_body)
            self._pop_scope()
            self.in_virtual_setter = previous_virtual_setter
        self.current_method = prev_method
        self.current_return_type = prev_return_type

    def _current_self_type(self):
        generic_args = [TypeExpr(base=name) for name in self.current_class.generic_params]
        return TypeExpr(
            base=self.current_class.name,
            generic_args=generic_args,
            pointer_depth=1,
        )

    def _analyze_function(self, func):
        prev_callable = self.current_callable
        self.current_callable = func
        prev_gpu = self.in_gpu_function
        self.in_gpu_function = func.is_gpu
        prev_return_type = self.current_return_type
        self.current_return_type = func.return_type

        for param in func.params:
            param.type = self._upgrade_class_type(param.type)
        func.return_type = self._upgrade_class_type(func.return_type)
        self._validate_array_return_declaration(func)
        self.current_return_type = self._array_value_type(func.return_type)

        self._push_scope()
        self._validate_default_params(func.params, func.line, func.col)
        self.scope.define(
            func.name,
            self._local_symbol(
                func.name, func.return_type, "function", func.name_line or func.line, func.name_col or func.col
            ),
        )
        for param in func.params:
            self._collect_generic_instances(param.type)
            if param.default is not None:
                parameter_value_type = self._array_parameter_value_type(param.type)
                self._validate_array_parameter_default(
                    param.type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or func.line,
                    param.col or func.col,
                )
                previous_parameter_default = self._analyzing_parameter_default
                self._analyzing_parameter_default = True
                try:
                    self._analyze_expr(param.default)
                finally:
                    self._analyzing_parameter_default = previous_parameter_default
                self._validate_callable_storage(
                    parameter_value_type,
                    param.default,
                    True,
                    param.line or func.line,
                    param.col or func.col,
                )
                self._validate_typed_initializer(
                    parameter_value_type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or func.line,
                    param.col or func.col,
                )
            if self._claim_local_binding(
                param.name,
                "parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                self.scope.define(param.name, self._param_symbol(param))
        self._collect_generic_instances(func.return_type)
        self._analyze_root_block(func.body)

        # GPU validation consumes inferred local/expression types, so it runs
        # after ordinary body analysis while the function scope is still live.
        if func.is_gpu:
            from .gpu import validate_gpu_function

            validate_gpu_function(self, func)

        if (
            func.return_type
            and not self._is_nonpointer_void_object(func.return_type)
            and func.body
            and not self._block_must_terminate(func.body)
        ):
            self._error(f"Function '{func.name}' has non-void return type but no return statement", func.line, func.col)

        self._pop_scope()
        self.current_callable = prev_callable
        self.in_gpu_function = prev_gpu
        self.current_return_type = prev_return_type
