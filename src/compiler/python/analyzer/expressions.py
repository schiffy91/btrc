"""Expression analysis, lambda analysis, and identifier collection."""

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BoolLiteral,
    BraceInitializer,
    CallExpr,
    CastExpr,
    CharLiteral,
    FieldAccessExpr,
    FloatLiteral,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    IntLiteral,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TernaryExpr,
    TupleLiteral,
    TypeExpr,
    UnaryExpr,
)
from .expression_shapes import is_empty_contextual_literal


class ExpressionsMixin:
    def _inside_generic_declaration(self) -> bool:
        return bool(
            (self.current_class and self.current_class.generic_params)
            or (self.current_method and self.current_method.generic_params)
        )

    def _analyze_expr(self, expr):
        if expr is None:
            return

        if isinstance(expr, (IntLiteral, FloatLiteral, StringLiteral, CharLiteral, BoolLiteral, NullLiteral)):
            pass
        elif isinstance(expr, Identifier):
            from .default_argument_contracts import (
                validate_default_macro_context,
            )

            validate_default_macro_context(self, expr)
            self._analyze_identifier_value(expr)
        elif isinstance(expr, SelfExpr):
            self._record_lambda_self(expr)
            self._validate_self(expr)
        elif isinstance(expr, SuperExpr):
            if self._analyzing_constructor_default:
                self.context.error(
                    "Constructor defaults cannot reference 'super' before allocation",
                    expr.line,
                    expr.col,
                )
            elif not self.current_class:
                self.context.error("'super' can only be used inside a class", expr.line, expr.col)
            elif not self.current_class.parent:
                self.context.error(
                    f"'super' cannot be used in class '{self.current_class.name}' which does not extend another class",
                    expr.line,
                    expr.col,
                )
        elif isinstance(expr, BinaryExpr):
            # Left-leaning chains (a+a+...+a) can be thousands of nodes deep;
            # walk the left spine iteratively to avoid one recursion frame
            # per term, then process bottom-up so _infer_type memo hits.
            spine = [expr]
            while isinstance(spine[-1].left, BinaryExpr):
                spine.append(spine[-1].left)
            self._analyze_expr(spine[-1].left)
            for node in reversed(spine):
                if node.op in ("&&", "||"):
                    before_right = set(self._nonnull_paths)
                    outcome = node.op == "&&"
                    right_flow = self._analyze_flow_branch(
                        self._nonnull_facts_for_outcome(node.left, outcome),
                        lambda node=node: self._analyze_expr(node.right),
                    )
                    # The RHS may be skipped. Only facts preserved by both the
                    # short-circuit path and the evaluated path remain known.
                    self._nonnull_paths = before_right & right_flow
                else:
                    self._analyze_expr(node.right)
                self._validate_literal_divisor(node.op, node.right)
                self._validate_binary_expr(node)
                if node is not expr:
                    node_t = self._infer_type(node)
                    if node_t:
                        self._record_node_type(node, node_t)
        elif isinstance(expr, UnaryExpr):
            self._analyze_expr(expr.operand)
            if expr.op == "&":
                self._record_nullable_address_escape(expr.operand)
            self._validate_unary_expr(expr)
        elif isinstance(expr, CallExpr):
            self._analyze_call(expr)
        elif isinstance(expr, IndexExpr):
            self._analyze_expr(expr.obj)
            self._analyze_expr(expr.index)
            self._validate_index_expr(expr)
        elif isinstance(expr, FieldAccessExpr):
            self._analyze_field_access(expr)
        elif isinstance(expr, AssignExpr):
            self._assignment_target_depth += 1
            self._analyze_expr(expr.target)
            self._assignment_target_depth -= 1
            self._analyze_expr(expr.value)
            self._validate_literal_divisor(expr.op, expr.value)
            if isinstance(expr.value, (ListLiteral, MapLiteral, BraceInitializer)):
                target_type = self._infer_type(expr.target)
                if target_type:
                    self._contextualize_aggregate_initializer(
                        target_type,
                        expr.value,
                        "Assignment",
                        expr.line,
                        expr.col,
                    )
                    self._contextualize_collection_initializer(
                        target_type,
                        expr.value,
                        "Assignment",
                        expr.line,
                        expr.col,
                    )
            self._validate_assignment(expr)
            self._validate_opaque_borrow_storage(
                self._infer_type(expr.target),
                expr.value,
                "Assignment",
                expr.line,
                expr.col,
            )
            self._invalidate_nonnull_target(expr.target)
        elif isinstance(expr, TernaryExpr):
            self._analyze_expr(expr.condition)
            self._reject_thread_observation(expr.condition)
            true_flow = self._analyze_flow_branch(
                self._nonnull_facts_for_outcome(expr.condition, True),
                lambda: self._analyze_expr(expr.true_expr),
            )
            false_flow = self._analyze_flow_branch(
                self._nonnull_facts_for_outcome(expr.condition, False),
                lambda: self._analyze_expr(expr.false_expr),
            )
            self._nonnull_paths = self._join_nonnull_flows([true_flow, false_flow])
            self._validate_ternary_expr(expr)
        elif isinstance(expr, CastExpr):
            expr.target_type = self._upgrade_class_type(expr.target_type)
            self._collect_generic_instances(expr.target_type)
            self._analyze_expr(expr.expr)
            self._validate_cast_expr(expr)
        elif isinstance(expr, SizeofExpr):
            if isinstance(expr.operand, SizeofType):
                self._collect_generic_instances(expr.operand.type)
            elif isinstance(expr.operand, SizeofExprOp):
                self._analyze_expr(expr.operand.expr)
            self._validate_sizeof_operand(expr)
        elif isinstance(expr, ListLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
                self._reject_thread_value_escape(el, "embedded in aggregate values")
            if len(expr.elements) >= 2:
                first_type = next(
                    (
                        self._infer_type(element)
                        for element in expr.elements
                        if not is_empty_contextual_literal(element)
                    ),
                    None,
                )
                if first_type:
                    for i, el in enumerate(expr.elements):
                        if is_empty_contextual_literal(el):
                            continue
                        el_type = self._infer_type(el)
                        if el_type and not self._types_compatible(first_type, el_type):
                            self.context.error(
                                f"List element {i} has type '{el_type.base}' but expected '{first_type.base}'",
                                getattr(el, "line", 0),
                                getattr(el, "col", 0),
                            )
        elif isinstance(expr, MapLiteral):
            for entry in expr.entries:
                self._analyze_expr(entry.key)
                self._analyze_expr(entry.value)
                self._reject_thread_value_escape(entry.key, "embedded in aggregate values")
                self._reject_thread_value_escape(entry.value, "embedded in aggregate values")
        elif isinstance(expr, FStringLiteral):
            for part in expr.parts:
                if isinstance(part, FStringExpr):
                    self._analyze_expr(part.expression)
                    self._reject_thread_value_escape(part.expression, "formatted as values")
        elif isinstance(expr, TupleLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
                self._reject_thread_value_escape(el, "embedded in aggregate values")
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            tuple_type = TypeExpr(base="Tuple", generic_args=elem_types)
            self._collect_generic_instances(tuple_type)
        elif isinstance(expr, LambdaExpr):
            if self._inside_generic_declaration():
                self.context.error(
                    "Lambda expressions are not supported inside generic declarations",
                    expr.line,
                    expr.col,
                )
            self._analyze_lambda(expr)
        elif isinstance(expr, NewExpr):
            # Upgrade class-typed generic args to pointers before collecting, so
            # `new List<OwnedItem>()` registers the same `List<OwnedItem*>`
            # instance every other site does (declared vars, return types).
            # Without this, a spurious un-upgraded `List<OwnedItem>` instance
            # gets monomorphized into a struct with an incomplete-type field.
            expr.type = self._upgrade_class_type(expr.type)
            self._collect_generic_instances(expr.type)
            for arg in expr.args:
                self._analyze_expr(arg)
                self._reject_thread_value_escape(arg, "passed as arguments")
            if expr.type.base == "Mutex":
                if any(expr.arg_names or []):
                    self.context.error(
                        "'new Mutex<T>()' does not accept named arguments",
                        expr.line,
                        expr.col,
                    )
                if len(expr.args) != 1:
                    self.context.error(
                        "'new Mutex<T>()' expects exactly 1 argument",
                        expr.line,
                        expr.col,
                    )
                elif expr.type.generic_args:
                    actual = self._infer_type(expr.args[0])
                    expected = expr.type.generic_args[0]
                    self._validate_managed_string_source(
                        expected,
                        expr.args[0],
                        "Mutex initializer",
                        expr.line,
                        expr.col,
                    )
                    self._validate_mutex_volatile_initializer(expected, expr)
                    if actual and not self._types_compatible(expected, actual):
                        self.context.error(
                            f"Mutex initializer expects "
                            f"'{self._format_type(expected)}' but got "
                            f"'{self._format_type(actual)}'",
                            expr.line,
                            expr.col,
                        )
            if expr.type.base in self.declarations.class_table:
                cls = self.declarations.class_table[expr.type.base]
                if cls.is_abstract:
                    self.context.error(
                        f"Cannot instantiate abstract class '{cls.name}'",
                        expr.line,
                        expr.col,
                    )
                substitutions = dict(zip(cls.generic_params, expr.type.generic_args))
                self._validate_constructor_args(cls, expr.args, expr.arg_names, expr.line, expr.col, substitutions)
        elif isinstance(expr, SpawnExpr):
            if self._inside_generic_declaration() and not isinstance(expr.fn, LambdaExpr):
                self.context.error(
                    "spawn expressions are not supported inside generic declarations",
                    expr.line,
                    expr.col,
                )
            self._analyze_expr(expr.fn)
            self._validate_spawn_expr(expr)
            # Infer Thread<T> where T is the return type of the spawned callable
            ret_type = self._infer_spawn_return_type(expr.fn)
            thread_type = TypeExpr(base="Thread", generic_args=[ret_type])
            self._collect_generic_instances(thread_type)
        elif isinstance(expr, BraceInitializer):
            for el in expr.elements:
                self._analyze_expr(el)
                self._reject_thread_value_escape(el, "embedded in aggregate values")

        inferred = self._infer_type(expr)
        if inferred:
            self._record_node_type(expr, inferred)
