"""Expression analysis, lambda analysis, and identifier collection."""

from ..ast_nodes import (
    AssignExpr, BinaryExpr, BoolLiteral, CallExpr, Capture, CastExpr,
    CharLiteral, FieldAccessExpr, FloatLiteral, FStringExpr, FStringLiteral,
    Identifier, IndexExpr, IntLiteral, LambdaBlock, LambdaExpr, LambdaExprBody,
    ListLiteral, MapLiteral, NewExpr, NullLiteral, SizeofExpr, SizeofExprOp,
    SizeofType, SpawnExpr, StringLiteral, SuperExpr, SelfExpr, TernaryExpr,
    TupleLiteral, TypeExpr, UnaryExpr,
)
from .core import SymbolInfo


class ExpressionsMixin:

    def _analyze_expr(self, expr):
        if expr is None:
            return

        if isinstance(expr, (IntLiteral, FloatLiteral, StringLiteral,
                             CharLiteral, BoolLiteral, NullLiteral)):
            pass
        elif isinstance(expr, Identifier):
            pass
        elif isinstance(expr, SelfExpr):
            self._validate_self(expr)
        elif isinstance(expr, SuperExpr):
            if not self.current_class:
                self._error("'super' can only be used inside a class", expr.line, expr.col)
            elif not self.current_class.parent:
                self._error(
                    f"'super' cannot be used in class '{self.current_class.name}' "
                    f"which does not extend another class", expr.line, expr.col)
        elif isinstance(expr, BinaryExpr):
            self._analyze_expr(expr.left)
            self._analyze_expr(expr.right)
            if expr.op in ("/", "%", "/=", "%="):
                r = expr.right
                if (isinstance(r, IntLiteral) and r.value == 0) or \
                   (isinstance(r, FloatLiteral) and r.value == 0.0):
                    self._error("Division by zero", r.line, r.col)
        elif isinstance(expr, UnaryExpr):
            self._analyze_expr(expr.operand)
        elif isinstance(expr, CallExpr):
            self._analyze_call(expr)
        elif isinstance(expr, IndexExpr):
            self._analyze_expr(expr.obj)
            self._analyze_expr(expr.index)
        elif isinstance(expr, FieldAccessExpr):
            self._analyze_field_access(expr)
        elif isinstance(expr, AssignExpr):
            self._analyze_expr(expr.target)
            self._analyze_expr(expr.value)
        elif isinstance(expr, TernaryExpr):
            self._analyze_expr(expr.condition)
            self._analyze_expr(expr.true_expr)
            self._analyze_expr(expr.false_expr)
        elif isinstance(expr, CastExpr):
            self._collect_generic_instances(expr.target_type)
            self._analyze_expr(expr.expr)
        elif isinstance(expr, SizeofExpr):
            if isinstance(expr.operand, SizeofType):
                self._collect_generic_instances(expr.operand.type)
            elif isinstance(expr.operand, SizeofExprOp):
                self._analyze_expr(expr.operand.expression)
        elif isinstance(expr, ListLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
            if len(expr.elements) >= 2:
                first_type = self._infer_type(expr.elements[0])
                if first_type:
                    for i, el in enumerate(expr.elements[1:], 1):
                        el_type = self._infer_type(el)
                        if el_type and not self._types_compatible(first_type, el_type):
                            self._error(
                                f"List element {i} has type '{el_type.base}' "
                                f"but expected '{first_type.base}'",
                                getattr(el, 'line', 0), getattr(el, 'col', 0))
        elif isinstance(expr, MapLiteral):
            for entry in expr.entries:
                self._analyze_expr(entry.key)
                self._analyze_expr(entry.value)
        elif isinstance(expr, FStringLiteral):
            for part in expr.parts:
                if isinstance(part, FStringExpr):
                    self._analyze_expr(part.expression)
        elif isinstance(expr, TupleLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            tuple_type = TypeExpr(base="Tuple", generic_args=elem_types)
            self._collect_generic_instances(tuple_type)
        elif isinstance(expr, LambdaExpr):
            self._analyze_lambda(expr)
        elif isinstance(expr, NewExpr):
            self._collect_generic_instances(expr.type)
            for arg in expr.args:
                self._analyze_expr(arg)
            if expr.type.base in self.class_table:
                cls = self.class_table[expr.type.base]
                self._validate_constructor_args(cls, expr.args, expr.line, expr.col)
        elif isinstance(expr, SpawnExpr):
            self._analyze_expr(expr.fn)
            # Infer Thread<T> where T is the return type of the spawned callable
            ret_type = self._infer_spawn_return_type(expr.fn)
            thread_type = TypeExpr(base="Thread", generic_args=[ret_type])
            self._collect_generic_instances(thread_type)

        inferred = self._infer_type(expr)
        if inferred:
            self.node_types[id(expr)] = inferred

    def _analyze_lambda(self, expr):
        """Analyze a lambda expression."""
        prev_return_type = self.current_return_type
        outer_vars: dict[str, TypeExpr] = {}
        scope = self.scope
        while scope is not None and scope is not self.global_scope:
            for name, sym in scope.symbols.items():
                if name not in outer_vars and sym.kind in ("variable", "param"):
                    outer_vars[name] = sym.type
            scope = scope.parent

        self._push_scope()
        param_names = set()
        for param in expr.params:
            param.type = self._upgrade_class_type(param.type)
            self._collect_generic_instances(param.type)
            self.scope.define(param.name, SymbolInfo(param.name, param.type, "param"))
            param_names.add(param.name)
        if expr.return_type:
            expr.return_type = self._upgrade_class_type(expr.return_type)
            self._collect_generic_instances(expr.return_type)
            self.current_return_type = expr.return_type
        else:
            self.current_return_type = None
        if isinstance(expr.body, LambdaBlock):
            self._analyze_block(expr.body.body)
        elif isinstance(expr.body, LambdaExprBody):
            self._analyze_expr(expr.body.expression)

        used_names: set[str] = set()
        self._collect_identifiers(expr.body, used_names)
        captures = []
        for name in sorted(used_names):
            if name in param_names:
                continue
            if name in outer_vars:
                captures.append(Capture(name=name, type=outer_vars[name]))
        expr.captures = captures

        self._pop_scope()
        self.current_return_type = prev_return_type

    def _collect_identifiers(self, node, names):
        """Walk AST subtree and collect all Identifier names."""
        if node is None:
            return
        if isinstance(node, Identifier):
            names.add(node.name)
            return
        for attr in ('declarations', 'members', 'statements', 'body', 'then_block',
                     'else_block', 'args', 'elements', 'entries', 'cases'):
            child = getattr(node, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                for item in child:
                    if isinstance(item, tuple):
                        for sub in item:
                            if hasattr(sub, '__dict__'):
                                self._collect_identifiers(sub, names)
                    elif hasattr(item, '__dict__'):
                        self._collect_identifiers(item, names)
            elif hasattr(child, '__dict__'):
                self._collect_identifiers(child, names)
        for attr in ('left', 'right', 'operand', 'callee', 'obj', 'expr', 'value',
                     'target', 'condition', 'true_expr', 'false_expr', 'iterable',
                     'init', 'update', 'initializer', 'index', 'expression',
                     'key', 'if_stmt', 'var_decl', 'fn'):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, '__dict__'):
                self._collect_identifiers(child, names)

    def _infer_spawn_return_type(self, fn_expr) -> TypeExpr:
        """Infer the return type of a spawned callable (usually a lambda)."""
        if isinstance(fn_expr, LambdaExpr):
            if fn_expr.return_type:
                return fn_expr.return_type
            return self._infer_lambda_return(fn_expr)
        fn_type = self._infer_type(fn_expr)
        if fn_type and fn_type.base == "__fn_ptr" and fn_type.generic_args:
            return fn_type.generic_args[0]
        return TypeExpr(base="void")
