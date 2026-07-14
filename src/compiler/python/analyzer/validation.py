"""Member access, self validation, and generic instance collection."""

from ..ast_nodes import Identifier


class ValidationMixin:
    def _analyze_field_access(self, expr, *, call_target=False):
        if isinstance(expr.obj, Identifier):
            self._analyze_identifier_value(expr.obj, qualification_receiver=True)
        else:
            self._analyze_expr(expr.obj)
        obj_type = self._infer_type(expr.obj)
        if (
            isinstance(expr.obj, Identifier)
            and self.scope.lookup(expr.obj.name) is None
            and expr.obj.name in self.rich_enum_table
        ):
            declaration = self.rich_enum_table[expr.obj.name]
            if not call_target and not any(variant.name == expr.field for variant in declaration.variants):
                self._error(
                    f"Rich enum '{declaration.name}' has no variant '{expr.field}'",
                    expr.line,
                    expr.col,
                )
            return
        if (
            isinstance(expr.obj, Identifier)
            and self.scope.lookup(expr.obj.name) is None
            and expr.obj.name in self.class_table
        ):
            self._validate_static_member_access(expr, self.class_table[expr.obj.name])
            return
        # Nullable safety: warn on non-optional access on nullable types
        if (
            obj_type
            and getattr(obj_type, "is_nullable", False)
            and not getattr(expr, "optional", False)
            and not self._is_known_nonnull(expr.obj)
        ):
            self._warning(
                f"Non-optional access '.{expr.field}' on nullable type "
                f"'{obj_type.base}?' — use '?.{expr.field}' or check for null",
                expr.line,
                expr.col,
            )
        # Built-in Thread<T> and Mutex<T> method validation
        if obj_type and obj_type.base == "Thread":
            valid = {"join"}
            if expr.field not in valid:
                self._error(f"Thread<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base == "Mutex":
            valid = {"get", "set", "destroy"}
            if expr.field not in valid:
                self._error(f"Mutex<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base in self.rich_enum_table:
            if expr.field not in {"tag", "data"}:
                self._error(
                    f"Rich enum '{obj_type.base}' has no field '{expr.field}'",
                    expr.line,
                    expr.col,
                )
            return
        if obj_type and obj_type.base == "string":
            if not call_target:
                self._error(
                    f"Type 'string' has no field '{expr.field}'; use a string method call",
                    expr.line,
                    expr.col,
                )
            return
        if obj_type and self._validate_tuple_field_access(expr, obj_type):
            return
        if obj_type and self._validate_struct_field_access(expr, obj_type):
            return
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            if expr.field in cls.properties:
                prop = cls.properties[expr.field]
                if prop.access == "private":
                    owner = cls.property_owners.get(expr.field, cls.name)
                    if self.current_class is None or self.current_class.name != owner:
                        self._error(
                            f"Cannot access private property '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
                if self._assignment_target_depth == 0 and not prop.has_getter:
                    self._error(f"Property '{expr.field}' has no getter", expr.line, expr.col)
                return
            if expr.field in cls.fields:
                field_decl = cls.fields[expr.field]
                if field_decl.access == "private":
                    owner = cls.field_owners.get(expr.field, cls.name)
                    if self.current_class is None or self.current_class.name != owner:
                        self._error(
                            f"Cannot access private field '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
            elif expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access == "class":
                    self._error(
                        f"Class method '{expr.field}' must be accessed on '{cls.name}', not on an instance",
                        expr.line,
                        expr.col,
                    )
                if method.access == "private":
                    owner = cls.method_owners.get(expr.field, cls.name)
                    if self.current_class is None or self.current_class.name != owner:
                        self._error(
                            f"Cannot access private method '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
            else:
                self._error(f"Class '{cls.name}' has no field or method '{expr.field}'", expr.line, expr.col)

    def _validate_static_member_access(self, expression, class_info) -> None:
        name = expression.field
        member = class_info.static_fields.get(name)
        if member is not None:
            self._validate_private_member_access(
                member,
                class_info.field_owners.get(name, class_info.name),
                "field",
                name,
                expression,
            )
            return
        method = class_info.methods.get(name)
        if method is not None:
            if method.access != "class":
                self._error(
                    f"Method '{name}' is not a class method, cannot access it statically",
                    expression.line,
                    expression.col,
                )
                return
            self._validate_private_member_access(
                method,
                class_info.method_owners.get(name, class_info.name),
                "method",
                name,
                expression,
            )
            return
        if name in class_info.fields or name in class_info.properties:
            self._error(
                f"Instance member '{name}' cannot be accessed on class '{class_info.name}'",
                expression.line,
                expression.col,
            )
            return
        self._error(
            f"Class '{class_info.name}' has no static field or method '{name}'",
            expression.line,
            expression.col,
        )

    def _validate_private_member_access(self, member, owner, kind, name, expression):
        if member.access == "private" and (self.current_class is None or self.current_class.name != owner):
            self._error(
                f"Cannot access private {kind} '{name}' of class '{owner}'",
                expression.line,
                expression.col,
            )

    def _validate_self(self, expr):
        if self.current_class is None:
            self._error("'self' used outside of a class", expr.line, expr.col)
        elif self.current_method is None:
            self._error("'self' used outside of a method", expr.line, expr.col)
        elif self.current_method.access == "class":
            self._error("'self' cannot be used in a class (static) method", expr.line, expr.col)


__all__ = ["ValidationMixin"]
