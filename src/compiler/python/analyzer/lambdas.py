"""Lambda analysis, capture discovery, and callable inference."""

import dataclasses

from ..ast_nodes import (
    Capture,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ReturnStmt,
    TypeExpr,
)


class LambdaAnalysisMixin:
    def _analyze_lambda(self, expr):
        """Analyze a lambda expression."""
        prev_return_type = self.current_return_type
        outer_nonnull_paths = self._nonnull_paths
        # A lambda executes after the enclosing branch may have ended. It may
        # capture bindings, but it cannot capture path-sensitive refinements.
        self._nonnull_paths = set()
        outer_symbols = {}
        scope = self.scope
        while scope is not None and scope is not self.global_scope:
            for name, sym in scope.symbols.items():
                if name not in outer_symbols and sym.kind in (
                    "variable",
                    "param",
                    "lambda_param",
                    "loop",
                    "loop_key",
                    "catch",
                    "capture",
                ):
                    outer_symbols[name] = sym
            scope = scope.parent

        captures: dict[str, TypeExpr] = {}
        self._lambda_contexts.append((outer_symbols, captures))
        self._push_scope()
        self._validate_parameter_names(expr.params, "lambda")
        declared_params = set()
        active_type_params = self._active_storage_type_parameters()
        for param in expr.params:
            param.type = self._upgrade_class_type(param.type)
            self._validate_declared_type(
                param.type,
                f"Lambda parameter '{param.name}'",
                param.line,
                param.col,
                role="parameter",
                active_type_params=active_type_params,
            )
            self._validate_array_bound(
                param.type,
                f"lambda parameter '{param.name}'",
                "parameter",
            )
            if param.default is not None:
                self._error(
                    "Lambda parameters cannot have default arguments",
                    param.line,
                    param.col,
                )
            self._collect_generic_instances(param.type)
            if param.name not in declared_params and self._claim_local_binding(
                param.name,
                "lambda parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                # Lambda parameters are borrowed at this call boundary, but
                # they are not parameters of ``current_callable`` (which still
                # describes the enclosing source declaration).  Keep a
                # distinct kind so ownership-transfer analysis cannot
                # accidentally inherit an enclosing same-named parameter's
                # contract.
                self.scope.define(
                    param.name,
                    dataclasses.replace(
                        self._param_symbol(param),
                        kind="lambda_param",
                        owned_storage=False,
                    ),
                )
                declared_params.add(param.name)
        if expr.return_type:
            expr.return_type = self._upgrade_class_type(expr.return_type)
            self._validate_declared_type(
                expr.return_type,
                "Lambda return type",
                expr.line,
                expr.col,
                role="return",
                active_type_params=active_type_params,
            )
            self._collect_generic_instances(expr.return_type)
            self.current_return_type = self._array_value_type(expr.return_type)
        else:
            self.current_return_type = None
        if isinstance(expr.body, LambdaBlock):
            self._analyze_root_block(expr.body.body)
            if (
                expr.return_type
                and not self._is_nonpointer_void_object(expr.return_type)
                and not self._block_must_terminate(expr.body.body)
            ):
                self._error(
                    "Non-void lambda does not return a value on every path",
                    expr.line,
                    expr.col,
                )
        elif isinstance(expr.body, LambdaExprBody):
            self._analyze_expr(expr.body.expression)
            if expr.return_type is not None:
                self._validate_volatile_reference_conversion(
                    expr.return_type,
                    expr.body.expression,
                    "Lambda return value",
                    expr.line,
                    expr.col,
                )

        if expr.return_type is None:
            inferred, conflicts = self._infer_lambda_return_details(expr)
            for actual in conflicts:
                self._error(
                    "Lambda has inconsistent inferred return types "
                    f"'{self._format_type(inferred)}' and "
                    f"'{self._format_type(actual)}'",
                    expr.line,
                    expr.col,
                )

        self._pop_scope()
        self._lambda_contexts.pop()
        environment_captures = [name for name in captures if outer_symbols[name].captures_environment]
        if environment_captures:
            names = ", ".join(environment_captures)
            self._error(
                f"A lambda cannot capture an environment-bearing callable ({names}); a closure value is required",
                expr.line,
                expr.col,
            )
        thread_captures = [
            name for name, capture_type in captures.items() if self._contains_thread_storage(capture_type)
        ]
        for name in thread_captures:
            self._error(
                f"A lambda cannot capture Thread handle '{name}'; join it "
                "before capture or create a fresh owner inside the lambda",
                expr.line,
                expr.col,
            )
        expr.captures = [Capture(name=name, type=captures[name]) for name in sorted(captures)]
        self.current_return_type = prev_return_type
        self._nonnull_paths = outer_nonnull_paths

    def _record_lambda_identifier(self, expression):
        if not self._lambda_contexts:
            return
        symbol = self.scope.lookup(expression.name)
        if symbol is None:
            return
        # A variable used by a nested lambda may need to be threaded through
        # every enclosing lambda. Mark every context whose outer binding is
        # the exact symbol that resolution selected.
        for outer_symbols, captures in self._lambda_contexts:
            if outer_symbols.get(expression.name) is symbol:
                captures[expression.name] = symbol.type
        current_outer, _current_captures = self._lambda_contexts[-1]
        if current_outer.get(expression.name) is symbol:
            # A capture is copied into the lifted function's environment.  It
            # therefore borrows the outer value even when the source binding
            # owns that value.  Install a lexical proxy after recording the
            # original symbol identity so mutation/ownership validation sees
            # the representation that code generation actually uses.
            self.scope.define(
                expression.name,
                dataclasses.replace(
                    symbol,
                    kind="capture",
                    owned_storage=False,
                ),
            )

    def _record_lambda_self(self, expression):
        if not self._lambda_contexts:
            return
        symbol = self.scope.lookup("self")
        if symbol is None:
            return
        for outer_symbols, captures in self._lambda_contexts:
            if outer_symbols.get("self") is symbol:
                captures["self"] = symbol.type
        current_outer, _current_captures = self._lambda_contexts[-1]
        if current_outer.get("self") is symbol:
            self.scope.define(
                "self",
                dataclasses.replace(
                    symbol,
                    kind="capture",
                    owned_storage=False,
                ),
            )

    def _infer_spawn_return_type(self, fn_expr) -> TypeExpr:
        """Infer the return type of a spawned callable (usually a lambda)."""
        if isinstance(fn_expr, LambdaExpr):
            if fn_expr.return_type:
                return fn_expr.return_type
            return self._infer_lambda_return(fn_expr)
        fn_type = self._canonical_type(self._infer_type(fn_expr))
        if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
            return fn_type.generic_args[0]
        return TypeExpr(base="void")

    def _infer_lambda_return(self, expr) -> TypeExpr:
        """Infer the return type of a lambda from its body."""
        inferred, _ = self._infer_lambda_return_details(expr)
        return inferred

    def _infer_lambda_return_details(self, expr):
        if isinstance(expr.body, LambdaExprBody):
            inferred = self._infer_type(expr.body.expression)
            return inferred or TypeExpr(base="void"), []

        return_types = []
        self._collect_lambda_return_types(expr.body, return_types)
        if not return_types:
            return TypeExpr(base="void"), []
        inferred = return_types[0]
        conflicts = [
            actual
            for actual in return_types[1:]
            if (not self._types_compatible(inferred, actual) and not self._types_compatible(actual, inferred))
        ]
        return inferred, conflicts

    def _collect_lambda_return_types(self, node, result):
        if node is None:
            return
        if isinstance(node, ReturnStmt):
            result.append(
                (self._infer_type(node.value) or TypeExpr(base="void"))
                if node.value is not None
                else TypeExpr(base="void")
            )
            return
        if isinstance(node, LambdaExpr):
            return  # Nested lambda returns belong to the nested callable.
        if not dataclasses.is_dataclass(node):
            return
        for field in dataclasses.fields(node):
            child = getattr(node, field.name, None)
            if isinstance(child, (list, tuple)):
                for item in child:
                    self._collect_lambda_return_types(item, result)
            else:
                self._collect_lambda_return_types(child, result)
