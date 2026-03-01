"""Call validation, field access checking, self validation, and generics."""

from ..ast_nodes import (
    FieldAccessExpr,
    Identifier,
    TypeExpr,
)


class ValidationMixin:

    def _normalize_type_key(self, t: TypeExpr) -> tuple:
        """Create a position-independent key for a TypeExpr (strips line/col)."""
        generic_args = tuple(
            self._normalize_type_key(a) for a in (t.generic_args or [])
        )
        return (t.base, generic_args, t.pointer_depth,
                getattr(t, 'is_nullable', False),
                getattr(t, 'is_array', False),
                getattr(t, 'array_size', None))

    def _analyze_call(self, expr):
        self._analyze_expr(expr.callee)
        for arg in expr.args:
            self._analyze_expr(arg)

        if isinstance(expr.callee, Identifier) and expr.callee.name in self.class_table:
            cls = self.class_table[expr.callee.name]
            if cls.is_abstract:
                self._error(f"Cannot instantiate abstract class '{cls.name}'",
                            expr.line, expr.col)
            self._validate_constructor_args(cls, expr.args, expr.line, expr.col)
        elif isinstance(expr.callee, Identifier) and expr.callee.name in self.function_table:
            func = self.function_table[expr.callee.name]
            if func.body is not None:
                self._validate_call_arity(func.name, func.params, expr.args,
                                          expr.line, expr.col)
        elif isinstance(expr.callee, FieldAccessExpr):
            obj_type = self._infer_type(expr.callee.obj)
            if obj_type and obj_type.base in self.class_table:
                cls = self.class_table[obj_type.base]
                method_name = expr.callee.field
                if method_name in cls.methods:
                    method = cls.methods[method_name]
                    self._validate_call_arity(
                        f"{cls.name}.{method_name}", method.params, expr.args,
                        expr.line, expr.col)

        # Register generic return types from method calls (e.g. Map.keys() → List<K>)
        if isinstance(expr.callee, FieldAccessExpr):
            obj_type = self._infer_type(expr.callee.obj)
            if obj_type and obj_type.base in self.class_table:
                cls = self.class_table[obj_type.base]
                method_name = expr.callee.field
                if method_name in cls.methods:
                    ret = cls.methods[method_name].return_type
                    if ret and ret.generic_args and cls.generic_params and obj_type.generic_args:
                        subs = dict(zip(cls.generic_params, obj_type.generic_args))
                        resolved = self._substitute_type(ret, subs)
                        if resolved and resolved.generic_args:
                            self._collect_generic_instances(resolved)

    def _validate_call_arity(self, name, params, args, line, col):
        """Validate argument count for function/method calls."""
        required = sum(1 for p in params if p.default is None)
        max_args = len(params)
        if len(args) < required:
            self._error(f"'{name}()' expects at least {required} argument(s) "
                        f"but got {len(args)}", line, col)
        elif len(args) > max_args:
            self._error(f"'{name}()' expects at most {max_args} argument(s) "
                        f"but got {len(args)}", line, col)

    def _validate_constructor_args(self, cls, args, line, col):
        """Validate argument count for constructor calls."""
        if cls.constructor is None:
            if len(args) > 0:
                self._error(f"Class '{cls.name}' has no constructor but was called with "
                            f"{len(args)} argument(s)", line, col)
            return
        params = cls.constructor.params
        required = sum(1 for p in params if p.default is None)
        max_args = len(params)
        if len(args) < required:
            self._error(f"Constructor '{cls.name}()' expects at least {required} "
                        f"argument(s) but got {len(args)}", line, col)
        elif len(args) > max_args:
            self._error(f"Constructor '{cls.name}()' expects at most {max_args} "
                        f"argument(s) but got {len(args)}", line, col)

    def _analyze_field_access(self, expr):
        self._analyze_expr(expr.obj)
        obj_type = self._infer_type(expr.obj)
        # Nullable safety: warn on non-optional access on nullable types
        if (obj_type and getattr(obj_type, 'is_nullable', False)
                and not getattr(expr, 'optional', False)):
            self._warning(
                f"Non-optional access '.{expr.field}' on nullable type "
                f"'{obj_type.base}?' — use '?.{expr.field}' or check for null",
                expr.line, expr.col)
        # Built-in Thread<T> and Mutex<T> method validation
        if obj_type and obj_type.base == "Thread":
            valid = {"join"}
            if expr.field not in valid:
                self._error(f"Thread<T> has no method '{expr.field}'",
                            expr.line, expr.col)
            return
        if obj_type and obj_type.base == "Mutex":
            valid = {"get", "set", "destroy"}
            if expr.field not in valid:
                self._error(f"Mutex<T> has no method '{expr.field}'",
                            expr.line, expr.col)
            return
        if obj_type and obj_type.base in self.class_table:
            cls = self.class_table[obj_type.base]
            if expr.field in cls.properties:
                prop = cls.properties[expr.field]
                if prop.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private property '{expr.field}' "
                            f"of class '{cls.name}'", expr.line, expr.col)
                return
            if expr.field in cls.fields:
                field_decl = cls.fields[expr.field]
                if field_decl.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private field '{expr.field}' "
                            f"of class '{cls.name}'", expr.line, expr.col)
            elif expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access == "private":
                    if self.current_class is None or self.current_class.name != cls.name:
                        self._error(
                            f"Cannot access private method '{expr.field}' "
                            f"of class '{cls.name}'", expr.line, expr.col)
            else:
                self._error(
                    f"Class '{cls.name}' has no field or method '{expr.field}'",
                    expr.line, expr.col)
        elif isinstance(expr.obj, Identifier) and expr.obj.name in self.class_table:
            cls = self.class_table[expr.obj.name]
            if expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access != "class":
                    self._error(
                        f"Method '{expr.field}' is not a class method, "
                        f"cannot call statically", expr.line, expr.col)

    def _validate_self(self, expr):
        if self.current_class is None:
            self._error("'self' used outside of a class", expr.line, expr.col)
        elif self.current_method is None:
            self._error("'self' used outside of a method", expr.line, expr.col)
        elif self.current_method.access == "class":
            self._error("'self' cannot be used in a class (static) method",
                        expr.line, expr.col)

    # ---- Generic instance collection ----

    def _collect_generic_instances(self, type_expr):
        if type_expr is None:
            return
        if type_expr.generic_args:
            key = type_expr.base
            args_tuple = tuple(type_expr.generic_args)
            # Validate generic arg count from class_table
            if key in self.class_table:
                cls = self.class_table[key]
                expected = len(cls.generic_params) if cls.generic_params else None
                if expected is not None and len(type_expr.generic_args) != expected:
                    self._error(
                        f"Type '{key}' expects {expected} generic argument(s) "
                        f"but got {len(type_expr.generic_args)}",
                        getattr(type_expr, 'line', 0), getattr(type_expr, 'col', 0))
            if key not in self.generic_instances:
                self.generic_instances[key] = []
            normalized_new = tuple(self._normalize_type_key(a) for a in args_tuple)
            already_exists = any(
                tuple(self._normalize_type_key(a) for a in existing_args) == normalized_new
                for existing_args in self.generic_instances[key]
            )
            if not already_exists:
                self.generic_instances[key].append(args_tuple)
            # Register transitive deps from method return types
            if key in self.class_table:
                cls = self.class_table[key]
                if cls.generic_params and len(type_expr.generic_args) == len(cls.generic_params):
                    subs = dict(zip(cls.generic_params, type_expr.generic_args))
                    for method in cls.methods.values():
                        if method.return_type and method.return_type.generic_args:
                            resolved = self._substitute_type(method.return_type, subs)
                            if resolved and resolved.generic_args and resolved.base != key:
                                self._collect_generic_instances(resolved)
            for arg in type_expr.generic_args:
                self._collect_generic_instances(arg)
