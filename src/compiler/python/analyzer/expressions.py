"""Expression traversal and expression-level validation."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.aggregates import InitializerPlan
from src.compiler.python.analyzer.ownership import MutexDestroyReceiverPlan
from src.compiler.python.analyzer.program import DeclarationIndex, Occurrence
from src.compiler.python.analyzer.types import (
    _RUNTIME_AGGREGATE_BASES,
    OperatorTypeError,
)
from src.compiler.python.lexer.lexer import LiteralDecoder
from src.compiler.python.syntax.ast.generated import (
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
    LambdaExprBody,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    ReturnStmt,
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

_MANAGED_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})

if TYPE_CHECKING:
    from src.compiler.python.analyzer.aggregates import AggregateAnalyzer
    from src.compiler.python.analyzer.calls import CallAnalyzer
    from src.compiler.python.analyzer.declarations import DeclarationRegistry
    from src.compiler.python.analyzer.generics import GenericAnalyzer
    from src.compiler.python.analyzer.gpu import GpuAnalyzer
    from src.compiler.python.analyzer.ownership import OwnershipAnalyzer
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.storage import StorageModel
    from src.compiler.python.analyzer.types import TypeSystem


@dataclass(frozen=True)
class ExpressionValuePlan:
    """One already-analyzed value boundary materialized by ExpressionAnalyzer."""

    expected: TypeExpr | None
    value: object
    subject: str
    line: int = 0
    col: int = 0
    explicit_type: bool = True
    callable_storage: bool = False
    callable_escape: bool = False
    managed_string: bool = False


class ExpressionAnalyzer:
    """Expression traversal and expression-level validation."""

    def __init__(
        self,
        session: AnalysisSession,
        declarations: DeclarationRegistry,
        index: DeclarationIndex,
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
        storage: StorageModel,
        ownership: OwnershipAnalyzer,
        calls: CallAnalyzer,
        gpu: GpuAnalyzer,
        generics: GenericAnalyzer,
    ) -> None:
        self.session = session
        self.declarations = declarations
        self.index = index
        self.aggregates = aggregates
        self.calls = calls
        self.generics = generics
        self.gpu = gpu
        self.ownership = ownership
        self.storage = storage
        self.types = types

    def _validate_fixed_array_assignment(self, target, expression) -> bool:
        """Reject array-object rebinding while preserving pointer-valued slots."""
        target = self.aggregates.array_target_value_type(expression.target, target)
        canonical = self.types.canonical_type(target)
        if self.gpu.is_output_assignment(expression):
            if self.aggregates.array_target_has_capacity(expression.target, target):
                return False
            self.session.error(
                "Array-returning @gpu assignment target has no provable writable capacity",
                expression.line,
                expression.col,
            )
            return True
        if canonical is None or not canonical.is_array:
            return False
        if self.aggregates.is_pointer_backed_array_target(expression.target, canonical):
            return False
        subject = "Fixed array" if canonical.array_size is not None else "Array object"
        self.session.error(
            f"{subject} '{self.types.format_type(canonical)}' is not assignable", expression.line, expression.col
        )
        return True

    @staticmethod
    def is_known_numeric_zero(expression) -> bool:
        return isinstance(expression, (IntLiteral, FloatLiteral, BoolLiteral)) and (not expression.value)

    def _validate_spawn_expr(self, expression):
        callable_type = self.types.canonical_type(self.aggregates.type_of(expression.fn))
        if not isinstance(expression.fn, LambdaExpr) and (not (callable_type and callable_type.base in {"__fn_ptr", "__realtime_fn_ptr"})):
            self.session.error("spawn expects a lambda or function pointer", expression.line, expression.col)
        elif not isinstance(expression.fn, LambdaExpr) and self.ownership.callable_value_requires_environment(
            expression.fn
        ):
            self.session.error(
                "A capturing lambda alias cannot be spawned; pass the lambda literal directly",
                expression.line,
                expression.col,
            )
        elif not isinstance(expression.fn, LambdaExpr) and (not self._is_pthread_entry_type(callable_type)):
            self.session.error(
                "Non-lambda spawn requires __fn_ptr<void*, void*>; use a lambda adapter for other signatures",
                expression.line,
                expression.col,
            )
        if isinstance(expression.fn, LambdaExpr):
            self._validate_spawn_captures(expression)

    def _validate_spawn_captures(self, expression) -> None:
        for capture in expression.fn.captures:
            capture_type = self.types.canonical_type(capture.type)
            if (capture_type and capture_type.is_array) or self.types.thread_result_contains_unsized_array(
                capture.type
            ):
                self.session.error(
                    f"spawn cannot capture array storage through '{capture.name}'; copy it into a scalar-only struct or managed collection",
                    expression.line,
                    expression.col,
                )
                continue
            if not self.types.is_direct_managed_thread_result(
                capture.type
            ) and self.types.thread_result_aggregate_contains_managed_reference(capture.type):
                self.session.error(
                    f"spawn cannot capture shallow aggregate '{capture.name}' containing string or class references; capture managed values directly",
                    expression.line,
                    expression.col,
                )

    @classmethod
    def _is_pthread_entry_type(cls, callable_type):
        arguments = callable_type.generic_args if callable_type else []
        return bool(
            callable_type
            and callable_type.base in {"__fn_ptr", "__realtime_fn_ptr"}
            and (len(arguments) == 2)
            and cls._is_void_pointer(arguments[0])
            and cls._is_void_pointer(arguments[1])
        )

    @staticmethod
    def _is_void_pointer(type_expr):
        return bool(
            type_expr
            and type_expr.base == "void"
            and (type_expr.pointer_depth == 1)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def analyze(self, expression) -> None:
        """Recursively analyze one expression whose body/flow facts are prepared."""
        self._analyze_expr(expression)

    def apply_initializer_plan(self, plan: InitializerPlan) -> bool:
        """Materialize an analyzed initializer plan at the expression boundary."""
        return self.calls.apply_initializer_plan(plan)

    def contextualize_value(self, plan: ExpressionValuePlan) -> bool:
        return self.calls.contextualize_generic_constructor(plan.expected, plan.value)

    def validate_value(self, plan: ExpressionValuePlan) -> bool:
        if plan.managed_string:
            self.calls.validate_managed_string_source(plan.expected, plan.value, plan.subject, plan.line, plan.col)
        if plan.callable_storage:
            self.ownership.validate_callable_storage(plan.expected, plan.value, plan.explicit_type, plan.line, plan.col)
        if plan.callable_escape:
            return self.ownership.validate_callable_value(plan.expected, plan.value, plan.line, plan.col)
        return False

    def value_requires_environment(self, value) -> bool:
        return self.ownership.callable_value_requires_environment(value)

    def _validate_indexed_update(self, target, *, require_getter, value, line, col) -> None:
        if not isinstance(target, IndexExpr):
            return
        receiver_type = self.infer_type(target.obj)
        protocol = self.types.resolve_index_protocol(
            receiver_type, active_type_params=self.storage.active_type_parameters()
        )
        if protocol is None:
            return
        setter = protocol.setter
        getter = protocol.getter
        if setter is None:
            self.session.error(
                f"Type '{self.types.format_type(receiver_type)}' has no indexed setter; it has no void instance set(index, value) method",
                line,
                col,
            )
        if require_getter and getter is None:
            self.session.error(
                f"Type '{self.types.format_type(receiver_type)}' has no indexed getter; indexing requires an instance get(index) method",
                line,
                col,
            )
        if setter is None or (require_getter and getter is None):
            return
        self.generics.record_class_method_use(receiver_type, setter.name)
        if require_getter:
            self.generics.record_class_method_use(receiver_type, getter.name)
        self._validate_indexed_method_access(protocol, setter, line, col)
        if require_getter:
            self._validate_indexed_method_access(protocol, getter, line, col)
        substitutions = protocol.substitutions(receiver_type)
        actual_index = self.infer_type(target.index)
        methods = (getter, setter) if require_getter else (setter,)
        for method in methods:
            expected_index = self.types.substitute_type(method.params[0].type, substitutions)
            if actual_index is not None and (not self.types.types_compatible(expected_index, actual_index)):
                self.session.error(
                    f"Indexed {method.name} expects index type '{self.types.format_type(expected_index)}' but got '{self.types.format_type(actual_index)}'",
                    target.index.line,
                    target.index.col,
                )
        expected_value = self.types.substitute_type(setter.params[1].type, substitutions)
        if require_getter:
            actual_value = self.types.substitute_type(getter.return_type, substitutions)
        else:
            actual_value = self.infer_type(value)
            self.session.record_node_type(target, expected_value)
        if actual_value is not None and (not self.types.types_compatible(expected_value, actual_value)):
            self.session.error(
                f"Indexed setter expects value type '{self.types.format_type(expected_value)}' but got '{self.types.format_type(actual_value)}'",
                line,
                col,
            )

    def _validate_indexed_method_access(self, protocol, method, line, col) -> None:
        if method is None or method.access != "private":
            return
        owner = protocol.class_info.method_owners.get(method.name, protocol.class_info.name)
        if self.session.current_class is None or self.session.current_class.name != owner:
            self.session.error(f"Cannot access private indexed method '{method.name}' of class '{owner}'", line, col)

    def is_lvalue(self, expression) -> bool:
        """Whether mutation can write back through this source expression."""
        if isinstance(expression, Identifier):
            return self._identifier_is_storage(expression)
        if isinstance(expression, IndexExpr):
            return self.storage.is_protocol_index_projection(expression) or self._is_addressable_storage(expression)
        if isinstance(expression, UnaryExpr):
            return expression.op == "*"
        if not isinstance(expression, FieldAccessExpr) or expression.optional:
            return False
        if self.storage.is_property_projection(expression):
            return True
        return self._is_addressable_storage(expression)

    def _is_addressable_storage(self, expression) -> bool:
        """Whether an expression denotes physical storage, not a getter copy."""
        if isinstance(expression, Identifier):
            return self._identifier_is_storage(expression)
        if isinstance(expression, UnaryExpr):
            return expression.op == "*"
        if isinstance(expression, IndexExpr):
            if self.storage.is_protocol_index_projection(expression):
                return False
            receiver_type = self.types.canonical_type(self.infer_type(expression.obj))
            if receiver_type is None:
                return True
            if receiver_type.is_array:
                return self._is_addressable_storage(expression.obj)
            if receiver_type.base == "string" or self.storage.is_raw_pointer_value(receiver_type):
                return True
            return self._is_addressable_storage(expression.obj)
        if not isinstance(expression, FieldAccessExpr) or expression.optional:
            return False
        if self.storage.is_property_projection(expression) or self._is_computed_field_projection(expression):
            return False
        if isinstance(expression.obj, Identifier):
            class_info = self.index.class_table.get(expression.obj.name)
            if class_info is not None and expression.field in class_info.static_fields:
                return True
        receiver_type = self.types.canonical_type(self.infer_type(expression.obj))
        if self._is_reference_receiver(receiver_type):
            return True
        return self._is_addressable_storage(expression.obj)

    def is_lifetime_stable_storage(self, expression) -> bool:
        return self._is_addressable_storage(expression) and (not self.has_temporary_managed_owner(expression))

    def _validate_address_operand(self, expression) -> None:
        operand = expression.operand
        if self.ownership.addresses_callable_storage(operand):
            self.session.error(
                "Managed-return callable storage cannot be addressed; an alias cannot preserve flow-sensitive return ownership ABI",
                expression.line,
                expression.col,
            )
            return
        name = getattr(operand, "name", None)
        valid = (
            self.is_lifetime_stable_storage(operand)
            or name in self.index.function_table
            or name in self.session.source_visible_runtime_names
        )
        if valid:
            return
        operand_type = self.infer_type(operand)
        spelling = self.types.format_type(operand_type) if operand_type is not None else "unknown"
        self.session.error(f"Unary operator '&' is not defined for '{spelling}'", expression.line, expression.col)

    def _validate_mutex_destroy_receiver(self, expression: CallExpr) -> None:
        callee = expression.callee
        if not isinstance(callee, FieldAccessExpr) or callee.field != "destroy":
            return
        receiver_type = self.types.canonical_type(self.infer_type(callee.obj))
        if receiver_type is None or receiver_type.base != "Mutex":
            return
        indirect = self.storage.is_virtual_projection(callee.obj)
        stable = self.is_lifetime_stable_storage(callee.obj)
        mutable = True
        if not indirect and stable:
            mutable = self.validate_mutable_target(callee.obj, expression.line, expression.col)
        self.ownership.validate_mutex_destroy_receiver(
            expression,
            MutexDestroyReceiverPlan(
                standalone=expression is self.session.standalone_expression_root,
                optional=callee.optional,
                indirect=indirect,
                stable_storage=stable,
                mutable=mutable,
            ),
        )

    def has_temporary_managed_owner(self, expression) -> bool:
        result_type = self.types.canonical_type(self.infer_type(expression))
        managed_result = bool(
            result_type
            and (
                result_type.base in self.index.class_table
                or result_type.base in _MANAGED_COLLECTION_BASES
                or result_type.base == "Mutex"
                or self.types.is_scalar_string_value(result_type)
            )
        )
        if isinstance(expression, (CallExpr, NewExpr)):
            return managed_result
        if isinstance(expression, (ListLiteral, MapLiteral)):
            return True
        if isinstance(expression, BraceInitializer):
            return managed_result
        if isinstance(expression, CastExpr):
            return self.has_temporary_managed_owner(expression.expr)
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            target = expression.target
            return bool(
                managed_result
                and (
                    (isinstance(target, (FieldAccessExpr, IndexExpr)) and self.has_temporary_managed_owner(target.obj))
                    or (
                        expression.op == "="
                        and self.storage.is_virtual_projection(target)
                        and self.has_temporary_managed_owner(expression.value)
                    )
                )
            )
        if isinstance(expression, BinaryExpr) and expression.op != "??" and managed_result:
            if expression.op == "+" and all(
                self.types.is_scalar_string_value(self.types.canonical_type(self.infer_type(operand)))
                for operand in (expression.left, expression.right)
            ):
                return True
            operand_type = self.infer_type(expression.left)
            return self.types.operator_method(operand_type, expression.op) is not None
        if isinstance(expression, UnaryExpr) and managed_result:
            operand_type = self.infer_type(expression.operand)
            return self.types.operator_method(operand_type, expression.op, unary=True) is not None
        if isinstance(expression, IndexExpr):
            if managed_result and self.storage.is_protocol_index_projection(expression):
                return True
            return self.has_temporary_managed_owner(expression.obj)
        if isinstance(expression, FieldAccessExpr):
            return self.has_temporary_managed_owner(expression.obj)
        if isinstance(expression, TernaryExpr):
            return self.has_temporary_managed_owner(expression.true_expr) or self.has_temporary_managed_owner(
                expression.false_expr
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self.has_temporary_managed_owner(expression.left) or self.has_temporary_managed_owner(
                expression.right
            )
        return False

    def _target_has_const_receiver(self, expression) -> bool:
        if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
            return False
        receiver_type = self.types.canonical_type(self.infer_type(expression.obj))
        if receiver_type is not None and receiver_type.is_const:
            return True
        if isinstance(expression, IndexExpr) and self.storage.is_raw_pointer_value(receiver_type):
            return False
        return self._target_has_const_receiver(expression.obj)

    def _is_computed_field_projection(self, expression: FieldAccessExpr) -> bool:
        receiver_type = self.types.canonical_type(self.infer_type(expression.obj))
        return bool(receiver_type and receiver_type.base == "string")

    def _is_reference_receiver(self, type_expr) -> bool:
        return bool(
            type_expr
            and (
                type_expr.pointer_depth > 0
                or type_expr.is_array
                or type_expr.base == "string"
                or (type_expr.base == "Mutex")
                or (type_expr.base in self.index.class_table)
            )
        )

    def _identifier_is_storage(self, expression: Identifier) -> bool:
        symbol = self.session.scope.lookup(expression.name)
        if symbol is not None:
            return symbol.kind != "function"
        if expression.name in self.index.function_table:
            return False
        if expression.name in self.index.class_table or expression.name in self.index.enum_table:
            return False
        if expression.name in self.index.rich_enum_table:
            return False
        return not bool(self.index.enum_member_owners.get(expression.name))

    def _reject_borrowed_managed_rebind(self, expression, target_type) -> bool:
        if (
            not isinstance(expression.target, Identifier)
            or target_type is None
            or (target_type.base not in {"string", "Mutex"} and target_type.base not in self.index.class_table)
        ):
            return False
        symbol = self.session.scope.lookup(expression.target.name)
        if (
            symbol is None
            or symbol.kind not in {"param", "loop", "parallel", "catch", "capture", "lambda_param"}
            or symbol.owned_storage
        ):
            return False
        borrowed_self_projection = self._is_borrowed_self_projection(expression.value, expression.target.name)
        needs_owner = expression.op != "=" or (
            not borrowed_self_projection and self._managed_rebind_may_need_owner(expression.value, target_type)
        )
        if not needs_owner:
            return False
        self.session.error(
            "Borrowed managed bindings cannot be rebound; declare an owned local before assigning or applying a compound update",
            expression.line,
            expression.col,
        )
        return True

    def _managed_rebind_may_need_owner(self, expression, target_type=None) -> bool:
        if self.types.requires_string_conversion(target_type, self.infer_type(expression)):
            return True
        if isinstance(expression, (NullLiteral, StringLiteral, CharLiteral)):
            return False
        if isinstance(expression, Identifier):
            symbol = self.session.scope.lookup(expression.name)
            return bool(
                symbol is None
                or symbol.owned_storage
                or symbol.kind not in {"param", "loop", "parallel", "catch", "capture", "lambda_param"}
            )
        if isinstance(expression, CastExpr):
            return self._managed_rebind_may_need_owner(expression.expr, target_type)
        if isinstance(expression, TernaryExpr):
            return self._managed_rebind_may_need_owner(
                expression.true_expr, target_type
            ) or self._managed_rebind_may_need_owner(expression.false_expr, target_type)
        return True

    def _is_borrowed_self_projection(self, expression, target_name: str) -> bool:
        """Whether a physical projection remains rooted in the caller's owner."""
        if isinstance(expression, CastExpr):
            return self._is_borrowed_self_projection(expression.expr, target_name)
        if not isinstance(expression, FieldAccessExpr):
            return False
        receiver_type = self.types.canonical_type(self.infer_type(expression.obj))
        if self.storage.custom_property_getter(self.index.class_table, receiver_type, expression.field):
            return False
        root = expression.obj
        while isinstance(root, CastExpr):
            root = root.expr
        if isinstance(root, Identifier):
            return root.name == target_name
        return self._is_borrowed_self_projection(root, target_name)

    def _validate_literal_divisor(self, operator, operand):
        if operator not in {"/", "%", "/=", "%="}:
            return
        zero = (isinstance(operand, IntLiteral) and operand.value == 0) or (
            isinstance(operand, FloatLiteral) and operand.value == 0.0
        )
        if zero:
            self.session.error("Division by zero", operand.line, operand.col)

    def _validate_assignment(self, expression):
        if isinstance(expression.target, FieldAccessExpr) and expression.target.optional:
            self.session.error("Optional-chain expression is not assignable", expression.line, expression.col)
            return
        if not self.is_lvalue(expression.target):
            self.session.error("Assignment target is not assignable", expression.line, expression.col)
            return
        if not self.validate_mutable_target(expression.target, expression.line, expression.col):
            return
        if self.ownership.validate_environment_callable_reassignment(expression):
            return
        self._validate_property_update(
            expression.target,
            require_getter=expression.op != "=",
            allow_getter_storage=self.gpu.is_output_assignment(expression),
            line=expression.line,
            col=expression.col,
        )
        self._validate_indexed_update(
            expression.target,
            require_getter=expression.op != "=",
            value=expression.value,
            line=expression.line,
            col=expression.col,
        )
        target = self.infer_type(expression.target)
        canonical_target = self.types.canonical_type(target)
        if canonical_target is not None and canonical_target.base == "Atomic" and canonical_target.pointer_depth == 0:
            self.session.error(
                "Atomic<T> owner cannot be assigned or copied; use Atomic.init/store on stable storage",
                expression.line,
                expression.col,
            )
            return
        if self._reject_borrowed_managed_rebind(expression, canonical_target):
            return
        virtual_target = self.storage.is_virtual_projection(expression.target)
        if (
            expression.op != "="
            and canonical_target is not None
            and (canonical_target.base in self.index.class_table or canonical_target.base in {"string", "Mutex"})
        ):
            supported_physical = isinstance(expression.target, (Identifier, FieldAccessExpr)) and (not virtual_target)
            if not supported_physical:
                self.session.error(
                    "Managed compound updates require a direct local/global or physical field; use an explicit local value and simple store for virtual or indirect targets",
                    expression.line,
                    expression.col,
                )
                return
        if self._validate_fixed_array_assignment(target, expression):
            return
        target = self.aggregates.array_target_value_type(expression.target, target)
        self.calls.contextualize_generic_constructor(target, expression.value)
        source = self.infer_type(expression.value)
        if target is None:
            return
        if self.ownership.validate_callable_value(target, expression.value, expression.line, expression.col):
            return
        if source is None:
            return
        if isinstance(expression.value, NullLiteral) and self.types.is_active_type_parameter(target):
            return
        if expression.op == "=":
            declared_target = (
                self.storage.declared_projection_type(expression.target)
                if isinstance(expression.target, FieldAccessExpr)
                else self.session.scope.lookup(expression.target.name).type
                if isinstance(expression.target, Identifier)
                and self.session.scope.lookup(expression.target.name) is not None
                else target
            )
            self.storage.validate_volatile_reference_conversion(
                declared_target, expression.value, "Assignment", expression.line, expression.col
            )
            self.calls.validate_managed_string_source(
                target, expression.value, "Assignment", expression.line, expression.col
            )
            if self.aggregates.validate_thread_handle_copy(target, expression.value, expression.line, expression.col):
                return
            canonical_target = self.types.canonical_type(target)
            if canonical_target and canonical_target.base == "Thread":
                self.session.error(
                    "Thread owner variables are single-assignment; declare a new owner for a fresh Thread result",
                    expression.line,
                    expression.col,
                )
                return
            if self.gpu.is_output_assignment(expression) and self.aggregates.array_target_has_capacity(
                expression.target, target
            ):
                if self.gpu.output_element_compatible(target, source):
                    return
                self.session.error(
                    "Array-returning @gpu output element type is not compatible with the target storage",
                    expression.line,
                    expression.col,
                )
                return
            if not self.types.types_compatible(target, source):
                self.session.error(
                    f"Cannot assign '{self.types.format_type(source)}' to '{self.types.format_type(target)}'",
                    expression.line,
                    expression.col,
                )
            return
        operator = expression.op[:-1]
        if target.base == source.base and self.types.is_active_type_parameter(target):
            return
        overload = self.types.operator_method(target, operator)
        if overload is not None:
            self.validate_operator_argument(expression, operator, expression.value, source, overload)
            self.validate_compound_operator_result(expression, operator, target, overload)
            self.validate_operator_access(target, operator, expression)
            return
        canonical_source = self.types.canonical_type(source) or source
        if (
            operator == "+"
            and self.types.is_scalar_string_value(target)
            and (
                self.types.is_scalar_string_value(source)
                or (
                    canonical_source.base == "char"
                    and (canonical_source.pointer_depth > 0 or canonical_source.is_array)
                )
            )
        ):
            return
        if not self._validate_portable_numeric_mix(
            expression, target, source, f"Compound assignment '{expression.op}'"
        ):
            return
        if operator in ("&", "|", "^", "<<", ">>"):
            valid = self.types.is_integral_value(target) and self.types.is_integral_value(source)
        else:
            valid = self.types.is_numeric_value(target) and self.types.is_numeric_value(source)
        if not valid:
            self.session.error(
                f"Operator '{expression.op}' is not defined for '{self.types.format_type(target)}' and '{self.types.format_type(source)}'",
                expression.line,
                expression.col,
            )

    def _validate_unary_expr(self, expression):
        if expression.op == "&":
            self._validate_address_operand(expression)
            return
        operand_type = self.infer_type(expression.operand)
        if operand_type is None:
            return
        if self.types.operator_method(operand_type, expression.op, unary=True) is not None:
            self.validate_operator_access(operand_type, expression.op, expression, unary=True)
            return
        value_type = self.types.canonical_type(operand_type) or operand_type
        if expression.op == "*":
            valid = value_type.pointer_depth > 0 or value_type.is_array
        elif expression.op in ("++", "--"):
            valid = self.is_lvalue(expression.operand) and (
                self.types.is_numeric_value(value_type) or value_type.pointer_depth > 0
            )
            if valid:
                if not self.validate_mutable_target(expression.operand, expression.line, expression.col):
                    return
                self._validate_property_update(
                    expression.operand, require_getter=True, line=expression.line, col=expression.col
                )
                self._validate_indexed_update(
                    expression.operand, require_getter=True, value=None, line=expression.line, col=expression.col
                )
        elif expression.op in ("+", "-"):
            valid = self.types.is_numeric_value(value_type)
        elif expression.op == "~":
            valid = self.types.is_integral_value(value_type)
        elif expression.op == "!":
            valid = value_type.base == "bool" or self.types.is_numeric_value(value_type) or value_type.pointer_depth > 0
        else:
            return
        if not valid:
            self.session.error(
                f"Unary operator '{expression.op}' is not defined for '{self.types.format_type(operand_type)}'",
                expression.line,
                expression.col,
            )

    def _validate_property_update(self, target, *, require_getter, line, col, allow_getter_storage=False):
        if not isinstance(target, FieldAccessExpr):
            return
        receiver_type = self.infer_type(target.obj)
        class_info = self.index.class_table.get(receiver_type.base) if receiver_type else None
        prop = class_info.properties.get(target.field) if class_info else None
        if prop is None:
            return
        if prop.has_setter:
            self.generics.record_class_callable_use(receiver_type, "set", target.field)
        if require_getter and prop.has_getter:
            self.generics.record_class_callable_use(receiver_type, "get", target.field)
        if not prop.has_setter and (not (allow_getter_storage and prop.has_getter)):
            self.session.error(f"Property '{target.field}' has no setter", line, col)
        if require_getter and (not prop.has_getter):
            self.session.error(f"Property '{target.field}' has no getter", line, col)

    def validate_mutable_target(self, target, line, col) -> bool:
        target_type = self.types.canonical_type(self.infer_type(target))
        if target_type is not None and target_type.is_const and (not self.types.is_pointer_value(target_type)):
            self.session.error("Cannot modify const-qualified storage", line, col)
            return False
        if self._target_has_const_receiver(target):
            self.session.error("Cannot modify through a const-qualified receiver", line, col)
            return False
        if self._aggregate_has_const_member(target_type):
            self.session.error("Cannot assign an aggregate containing const-qualified storage", line, col)
            return False
        return True

    def _aggregate_has_const_member(self, type_expr, seen=None) -> bool:
        if type_expr is None or self.types.is_pointer_value(type_expr):
            return False
        name = type_expr.base.removeprefix("struct ")
        declaration = self.index.struct_table.get(name)
        if declaration is None:
            return False
        seen = set() if seen is None else seen
        if name in seen:
            return False
        seen.add(name)
        for field in declaration.fields:
            field_type = self.types.canonical_type(field.type)
            if field_type is None:
                continue
            if field_type.is_const and (not self.types.is_pointer_value(field_type)):
                return True
            if self._aggregate_has_const_member(field_type, seen):
                return True
        return False

    def _analyze_identifier_value(self, expression, *, direct_callee=False, qualification_receiver=False) -> None:
        self._record_lambda_identifier(expression)
        if self.session.record_occurrences:
            self._record_identifier_occurrence(expression)
        name = expression.name
        if (direct_callee and name in {"Atomic", "Span"}) or (qualification_receiver and name == "MemoryOrder"):
            return
        if self.session.scope.lookup(name) is not None:
            return
        if self.ownership.validate_raw_lifetime_value(expression, direct_callee):
            return
        if not direct_callee and self.ownership.hosted_function_value_uses_owned_symbol(name):
            self.session.error(
                f"Hosted function '{name}' cannot be stored or forwarded as a value because bare __fn_ptr does not preserve its exact C ABI and effects; call it directly",
                expression.line,
                expression.col,
            )
            return
        if name in self.index.function_table:
            return
        if name in self.index.class_table:
            if direct_callee or qualification_receiver:
                return
            self.session.error(f"Type name '{name}' cannot be used as a runtime value", expression.line, expression.col)
            return
        if name in self.index.enum_table or name in self.index.rich_enum_table:
            if direct_callee or qualification_receiver:
                return
            self.session.error(f"Type name '{name}' cannot be used as a runtime value", expression.line, expression.col)
            return
        owners = self.index.enum_member_owners.get(name, set())
        if len(owners) == 1:
            return
        if len(owners) > 1:
            enums = ", ".join(sorted(owner or "<anonymous>" for owner in owners))
            self.session.error(
                f"Ambiguous enum member '{name}' belongs to {enums}; qualify it", expression.line, expression.col
            )
            return
        if self.index.source_macros.declared(name) or self.declarations.known_c_global(name):
            return
        if self.calls.validate_constructor_default_member(expression, direct_callee=direct_callee):
            return
        self.session.record_unresolved_symbol(expression, direct_callee=direct_callee)

    def _record_identifier_occurrence(self, expression: Identifier) -> None:
        symbol = self.session.scope.lookup(expression.name)
        if symbol is not None and (symbol.decl_file is not None or symbol.decl_line or symbol.decl_col):
            self.session.occurrences[id(expression)] = Occurrence(
                kind=symbol.kind,
                name=expression.name,
                def_file=symbol.decl_file,
                def_line=symbol.decl_line,
                def_col=symbol.decl_col,
            )
            return
        declaration, kind = self.declarations.definition(expression.name)
        if declaration is None:
            return
        self.session.occurrences[id(expression)] = Occurrence(
            kind=kind,
            name=expression.name,
            def_file=getattr(declaration, "source_file", None),
            def_line=getattr(declaration, "name_line", 0) or getattr(declaration, "line", 0),
            def_col=getattr(declaration, "name_col", 0) or getattr(declaration, "col", 0),
        )

    def infer_type(self, expression) -> TypeExpr | None:
        """Return the type inferred at the recursive expression boundary."""
        return self._infer_type(expression)

    def _claim_local_binding(self, name, kind, line=0, col=0, *, c_name_generated=False) -> bool:
        self.declarations.validate_name(name, kind.capitalize(), line, col, c_name_generated=c_name_generated)
        existing = self.session.scope.symbols.get(name)
        if existing is None or existing.kind == "function":
            outer = self.session.scope.parent.lookup(name) if self.session.scope.parent else None
            if outer is not None and self.types.contains_thread_storage(outer.type):
                self.session.error(f"Binding '{name}' cannot shadow an active Thread owner", line, col)
                return False
            return True
        self.session.error(f"Duplicate {kind} name '{name}' in the same scope", line, col)
        return False

    def _validate_cast_expr(self, expression) -> None:
        if not self.types.validate_cast_target_name(expression):
            return
        target = self.types.canonical_type(expression.target_type)
        source = self.types.canonical_type(self._infer_type(expression.expr))
        if target is None or source is None:
            return
        if target.base == "__realtime_fn_ptr":
            self.session.error(
                "RealtimeFunction cannot be created by a cast; use a direct named @realtime function",
                expression.line,
                expression.col,
            )
            return
        if source.base == "Thread":
            self.aggregates.reject_thread_value_escape(expression.expr, "cast")
            return
        if self._nonportable_callable_cast(source, target, expression.expr):
            self.session.error(
                "Function pointers cannot be cast to or from object pointers or integer values in strict C11",
                expression.line,
                expression.col,
            )
            return
        if self._nonportable_pointer_integer_cast(source, target, expression.expr):
            self.session.error("Pointer/integer casts require intptr_t or uintptr_t", expression.line, expression.col)
            return
        if self.types.is_void_value(source):
            if not self.types.is_void_value(target):
                self.session.error(
                    f"Cannot cast void expression to '{self.types.format_type(target)}'",
                    expression.line,
                    expression.col,
                )
            return
        if not self._is_scalar_cast_value(source):
            return
        struct_name = target.base.removeprefix("struct ")
        if (
            struct_name in self.index.struct_table
            and target.pointer_depth == 0
            and (not target.is_array)
            and (not target.generic_args)
        ):
            self.session.error(
                f"Cannot cast scalar '{self.types.format_type(source)}' to aggregate struct '{struct_name}'",
                expression.line,
                expression.col,
            )
        elif (
            target.base in _RUNTIME_AGGREGATE_BASES
            and target.generic_args
            and (target.pointer_depth == 0)
            and (not target.is_array)
        ):
            self.session.error(
                f"Cannot cast scalar '{self.types.format_type(source)}' to runtime generic value '{self.types.format_type(target)}'",
                expression.line,
                expression.col,
            )

    def _nonportable_callable_cast(self, source, target, value) -> bool:
        source_callable = self.types.function_pointer_signature(source) is not None
        target_callable = self.types.function_pointer_signature(target) is not None
        if source_callable == target_callable:
            return False
        if (
            target_callable
            and (not source_callable)
            and (isinstance(value, NullLiteral) or self.is_known_numeric_zero(value))
        ):
            return False
        return not (source_callable and target.base == "bool" and (target.pointer_depth == 0))

    def _nonportable_pointer_integer_cast(self, source, target, value) -> bool:
        source_pointer = bool(
            source.is_array or source.pointer_depth > 0 or self.ownership.is_managed_result_type(source)
        )
        target_pointer = bool(
            target.is_array or target.pointer_depth > 0 or self.ownership.is_managed_result_type(target)
        )
        if source_pointer == target_pointer:
            return False
        if target_pointer and (not source_pointer) and self.is_known_numeric_zero(value):
            return False
        scalar = target if source_pointer else source
        if scalar.base in {"intptr_t", "uintptr_t"}:
            return False
        return bool(
            scalar.pointer_depth == 0
            and (not scalar.is_array)
            and (
                self.types.is_numeric_value(scalar)
                or self.types.is_opaque_c_scalar(scalar)
                or self.types.is_native_enum_scalar(scalar)
            )
        )

    def _is_scalar_cast_value(self, type_expr) -> bool:
        if type_expr is None:
            return False
        if type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base == "string":
            return True
        return bool(
            type_expr.base == "bool"
            or self.types.is_numeric_value(type_expr)
            or self.types.is_opaque_c_scalar(type_expr)
            or self.types.is_native_enum_scalar(type_expr)
        )

    def validate_operator_argument(self, expression, operator, right_expression, right_type, overload) -> None:
        """Validate an overloaded binary operator's declared RHS contract."""
        method, substitutions = overload
        if not method.params:
            return
        expected = method.params[0].type
        if substitutions:
            expected = self.types.substitute_type(expected, substitutions)
        if self.types.requires_string_conversion(expected, right_type):
            self.generics.record_class_method_use(right_type, "toString")
        self.storage.validate_volatile_reference_conversion(
            expected, right_expression, f"Operator '{operator}' argument", expression.line, expression.col
        )
        if not self.types.types_compatible(expected, right_type):
            self.session.error(
                f"Operator '{operator}' expects '{self.types.format_type(expected)}' but got '{self.types.format_type(right_type)}'",
                expression.line,
                expression.col,
            )

    def validate_compound_operator_result(self, expression, operator, target_type, overload) -> None:
        """Require a compound overload result that can be committed to its slot."""
        method, substitutions = overload
        result_type = method.return_type
        if substitutions:
            result_type = self.types.substitute_type(result_type, substitutions)
        if not self.types.types_compatible(target_type, result_type):
            self.session.error(
                f"Operator '{operator}' returns '{self.types.format_type(result_type)}', which cannot be stored in compound target '{self.types.format_type(target_type)}'",
                expression.line,
                expression.col,
            )

    def infer_index_type(self, expression):
        object_type = self._infer_type(expression.obj)
        canonical = self.types.canonical_type(object_type)
        if canonical and canonical.base in {"Vector", "List", "Array", "Set"} and (len(canonical.generic_args) == 1):
            self.generics.record_class_method_use(
                canonical,
                "set" if self.session.analyzing_assignment_target else "get",
            )
            return canonical.generic_args[0]
        if canonical and canonical.base == "Map" and (len(canonical.generic_args) == 2):
            self.generics.record_class_method_use(
                canonical,
                "set" if self.session.analyzing_assignment_target else "get",
            )
            return canonical.generic_args[1]
        if self.types.is_scalar_string_value(canonical):
            return TypeExpr(base="char", is_const=canonical.is_const)
        if (
            canonical
            and (canonical.is_array or canonical.pointer_depth > 0)
            and (
                canonical.is_array
                or canonical.base in self.storage.active_type_parameters()
                or canonical.base not in self.index.class_table
                or (canonical.pointer_depth > 1)
            )
        ):
            preserved = self.storage.strip_outer_storage_through_typedef(object_type, self.index.typedef_table)
            if preserved is not None:
                return preserved
            return self.types.strip_outer_storage(canonical, array=canonical.is_array)
        protocol = self.types.resolve_index_protocol(
            canonical, active_type_params=self.storage.active_type_parameters()
        )
        if protocol is None:
            return None
        getter = protocol.getter
        setter = protocol.setter
        selected = setter if self.session.analyzing_assignment_target else getter
        if selected is not None:
            self.generics.record_class_method_use(canonical, selected.name)
        value_type = getter.return_type if getter is not None else None
        if value_type is None and setter is not None:
            value_type = setter.params[1].type
        if value_type is not None and canonical.generic_args:
            value_type = self.types.substitute_type(value_type, protocol.substitutions(canonical))
        return value_type

    def validate_operator_access(self, receiver_type, operator, expression, *, unary=False):
        receiver_type = self.types.canonical_type(receiver_type) or receiver_type
        resolved = self.types.operator_method(receiver_type, operator, unary=unary)
        if resolved is None:
            return
        method, _ = resolved
        self.generics.record_class_method_use(receiver_type, method.name)
        cls = self.index.class_table.get(receiver_type.base)
        owner = cls.method_owners.get(method.name, cls.name) if cls else ""
        if method.access == "private" and (
            self.session.current_class is None or self.session.current_class.name != owner
        ):
            self.session.error(
                f"Cannot use private operator '{owner}.{method.name}' outside its class",
                expression.line,
                expression.col,
            )

    def _infer_binary_type(self, expression):
        left = self._infer_type(expression.left)
        right = self._infer_type(expression.right)
        overloaded = self.types.operator_return_type(left, expression.op)
        if overloaded is not None:
            return overloaded
        if expression.op in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
            return TypeExpr(base="bool")
        if left and right:
            pointer_result = self._infer_pointer_arithmetic(expression.op, left, right)
            if pointer_result:
                return pointer_result
            numeric = self.types.numeric_result_type(
                self.types.canonical_type(left), self.types.canonical_type(right), frozenset(self.index.enum_table)
            )
            if numeric is not None:
                return numeric
        return left or right

    def _infer_pointer_arithmetic(self, operator, left, right):
        if operator == "-" and self.storage.is_raw_pointer_value(left):
            if self.storage.is_raw_pointer_value(right):
                return TypeExpr(base="long")
            return left
        if operator == "+":
            if self.storage.is_raw_pointer_value(left):
                return left
            if self.storage.is_raw_pointer_value(right):
                return right
        return None

    def _infer_ternary_type(self, expression):
        true_type = self._infer_type(expression.true_expr)
        false_type = self._infer_type(expression.false_expr)
        if true_type is None or false_type is None:
            return true_type or false_type
        true_is_null = true_type.base == "void" and true_type.pointer_depth > 0 and true_type.is_nullable
        false_is_null = false_type.base == "void" and false_type.pointer_depth > 0 and false_type.is_nullable
        if true_is_null and self.types.is_pointer_value(false_type):
            return replace(false_type, is_nullable=True)
        if false_is_null and self.types.is_pointer_value(true_type):
            return replace(true_type, is_nullable=True)
        numeric = self.types.numeric_result_type(
            self.types.canonical_type(true_type),
            self.types.canonical_type(false_type),
            frozenset(self.index.enum_table),
        )
        if numeric is not None:
            return numeric
        if self.types.types_compatible(true_type, false_type):
            return true_type
        if self.types.types_compatible(false_type, true_type):
            return false_type
        return true_type

    def _infer_type(self, expr) -> TypeExpr | None:
        """Infer a type, memoizing results to avoid quadratic re-inference."""
        if expr is None:
            return None
        cached = self.session.node_types.get(id(expr))
        if cached is not None:
            return self.session.record_node_type(expr, cached)
        result = self._infer_type_uncached(expr)
        if result is None:
            return None
        return self.session.record_node_type(expr, result)

    def _infer_type_uncached(self, expr) -> TypeExpr | None:
        if isinstance(expr, IntLiteral):
            return self.types.infer_integer_literal_type(expr.raw, expr.value)
        elif isinstance(expr, FloatLiteral):
            return self.types.float_literal_type(expr.raw)
        elif isinstance(expr, StringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, CharLiteral):
            return TypeExpr(base="char")
        elif isinstance(expr, BoolLiteral):
            return TypeExpr(base="bool")
        elif isinstance(expr, FStringLiteral):
            return TypeExpr(base="string")
        elif isinstance(expr, SizeofExpr):
            return TypeExpr(base="size_t")
        elif isinstance(expr, NullLiteral):
            return TypeExpr(base="void", pointer_depth=1, is_nullable=True)
        elif isinstance(expr, Identifier):
            if expr.name == "NULL":
                return TypeExpr(base="void", pointer_depth=1, is_nullable=True)
            sym = self.session.scope.lookup(expr.name)
            if sym:
                return self.types.canonical_type(sym.type) or sym.type
            function = self.index.function_table.get(expr.name)
            if function:
                return self.types.function_value_type(function)
            owners = self.index.enum_member_owners.get(expr.name, set())
            if len(owners) == 1:
                owner = next(iter(owners))
                return TypeExpr(base=owner or "int")
            if expr.name in {"stdin", "stdout", "stderr"}:
                return TypeExpr(base="FILE", pointer_depth=1)
            if expr.name == "__func__":
                return TypeExpr(base="char", pointer_depth=1, is_const=True)
            predefined = self.types.c_predefined_identifier_type(expr.name)
            if predefined == "const char*":
                return TypeExpr(base="char", pointer_depth=1, is_const=True)
            if predefined is not None:
                return TypeExpr(base=predefined)
            if self.types.c_opaque_value_identifier(expr.name):
                return None
            if self.types.c_integer_identifier(expr.name):
                return TypeExpr(base="int")
            return None
        elif isinstance(expr, SelfExpr):
            if self.session.current_class:
                return self.types.current_self_type()
            return None
        elif isinstance(expr, SuperExpr):
            if self.session.current_class and self.session.current_class.parent:
                return TypeExpr(base=self.session.current_class.parent, pointer_depth=1)
            return None
        elif isinstance(expr, FieldAccessExpr):
            return self._infer_field_access_type(expr)
        elif isinstance(expr, CallExpr):
            return self.calls.infer_call_type(expr)
        elif isinstance(expr, NewExpr):
            if expr.type.base in ("Thread", "Mutex"):
                return replace(expr.type, pointer_depth=0)
            return TypeExpr(base=expr.type.base, generic_args=expr.type.generic_args, pointer_depth=1)
        elif isinstance(expr, IndexExpr):
            return self.infer_index_type(expr)
        elif isinstance(expr, BinaryExpr):
            return self._infer_binary_type(expr)
        elif isinstance(expr, CastExpr):
            return expr.target_type
        elif isinstance(expr, UnaryExpr):
            operand_type = self._infer_type(expr.operand)
            if operand_type is None:
                return None
            canonical_operand = self.types.canonical_type(operand_type)
            if expr.op == "&":
                if isinstance(expr.operand, Identifier) and expr.operand.name in self.index.function_table:
                    return operand_type
                return self.types.add_outer_pointer(operand_type, clear_array=True)
            if expr.op == "*":
                if canonical_operand and (canonical_operand.is_array or canonical_operand.pointer_depth > 0):
                    preserved = self.storage.strip_outer_storage_through_typedef(operand_type, self.index.typedef_table)
                    if preserved is not None:
                        return preserved
                    return self.types.strip_outer_storage(canonical_operand, array=canonical_operand.is_array)
            if expr.op == "!":
                return TypeExpr(base="bool")
            overloaded = self.types.operator_return_type(operand_type, expr.op, unary=True)
            if overloaded is not None:
                return overloaded
            return operand_type
        elif isinstance(expr, TernaryExpr):
            return self._infer_ternary_type(expr)
        elif isinstance(expr, AssignExpr):
            return self._infer_type(expr.target)
        elif isinstance(expr, LambdaExpr):
            if expr.return_type:
                ret = expr.return_type
            else:
                ret = self._infer_lambda_return(expr)
            param_types = [p.type for p in expr.params]
            return TypeExpr(base="__fn_ptr", generic_args=[ret] + param_types)
        elif isinstance(expr, TupleLiteral):
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            return TypeExpr(base="Tuple", generic_args=elem_types)
        elif isinstance(expr, ListLiteral):
            if expr.elements:
                elem_type = self._infer_type(expr.elements[0])
                if elem_type:
                    return self.types.collection_literal_type("Vector", [elem_type])
            return self.types.collection_literal_type("Vector", [TypeExpr(base="int")])
        elif isinstance(expr, MapLiteral):
            if expr.entries:
                key_type = self._infer_type(expr.entries[0].key)
                val_type = self._infer_type(expr.entries[0].value)
                if key_type and val_type:
                    return self.types.collection_literal_type("Map", [key_type, val_type])
            return self.types.collection_literal_type("Map", [TypeExpr(base="string"), TypeExpr(base="int")])
        elif isinstance(expr, SpawnExpr):
            ret_type = self._infer_spawn_return_type(expr.fn)
            return TypeExpr(base="Thread", generic_args=[ret_type])
        elif isinstance(expr, BraceInitializer):
            if expr.elements:
                first_type = self._infer_type(expr.elements[0])
                return first_type
            return None
        return None

    def _infer_field_access_type(self, expr):
        if isinstance(expr.obj, Identifier):
            if expr.obj.name == "MemoryOrder" and expr.field in {
                "RELAXED",
                "ACQUIRE",
                "RELEASE",
                "ACQ_REL",
                "SEQ_CST",
            }:
                return TypeExpr(base="MemoryOrder")
            enum_values = self.index.enum_table.get(expr.obj.name)
            if enum_values is not None and expr.field in enum_values:
                return TypeExpr(base=expr.obj.name or "int")
            rich_enum = self.index.rich_enum_table.get(expr.obj.name)
            if rich_enum and any(variant.name == expr.field for variant in rich_enum.variants):
                return TypeExpr(base="int")
            class_info = (
                self.index.class_table.get(expr.obj.name) if self.session.scope.lookup(expr.obj.name) is None else None
            )
            if class_info and expr.field in class_info.static_fields:
                return class_info.static_fields[expr.field].type
        obj_type = self._infer_type(expr.obj)
        if obj_type and (obj_type.base == "Tuple" or obj_type.base.startswith("(")):
            if expr.field.startswith("_") and expr.field[1:].isdigit():
                index = int(expr.field[1:])
                if expr.field == f"_{index}" and index < len(obj_type.generic_args):
                    return obj_type.generic_args[index]
            return None
        if obj_type and obj_type.base in self.index.rich_enum_table:
            if expr.field == "tag":
                return TypeExpr(base="int")
            return None
        if obj_type and obj_type.base in {"Array", "List", "Map", "Set", "Vector"}:
            if expr.field in {"len", "length", "size"}:
                return TypeExpr(base="int", is_const=obj_type.is_const)
        if isinstance(expr.obj, FieldAccessExpr) and isinstance(expr.obj.obj, FieldAccessExpr):
            data_expr = expr.obj.obj
            if isinstance(data_expr.obj, (Identifier, FieldAccessExpr)):
                s_type = self._infer_type(data_expr.obj)
                if s_type and s_type.base in self.index.rich_enum_table:
                    enum_decl = self.index.rich_enum_table[s_type.base]
                    variant_name = expr.obj.field
                    for v in enum_decl.variants:
                        if v.name == variant_name:
                            for p in v.params:
                                if p.name == expr.field:
                                    return p.type
        if obj_type and obj_type.base in self.index.class_table:
            cls = self.index.class_table[obj_type.base]
            field_type = None
            is_property = False
            if expr.field in cls.properties:
                field_type = cls.properties[expr.field].type
                is_property = True
            elif expr.field in cls.fields:
                field_type = cls.fields[expr.field].type
            if field_type and cls.generic_params and obj_type.generic_args:
                subs = dict(zip(cls.generic_params, obj_type.generic_args))
                field_type = self.types.substitute_type(field_type, subs)
            return self._const_member_type(obj_type, field_type, is_property)
        if obj_type:
            struct_name = obj_type.base.removeprefix("struct ")
            struct_decl = self.index.struct_table.get(struct_name)
            if struct_decl:
                field_type = next((field.type for field in struct_decl.fields if field.name == expr.field), None)
                return self._const_member_type(obj_type, field_type)
        return None

    @staticmethod
    def _const_member_type(receiver_type, field_type, is_property=False):
        if (
            field_type is not None
            and receiver_type.is_const
            and (not is_property)
            and (field_type.pointer_depth == 0)
            and (field_type.base != "string")
        ):
            return replace(field_type, is_const=True)
        return field_type

    def integer_constant_expression(
        self, expression, *, enum_owner=None, allowed_enum_members=()
    ) -> tuple[bool, int | None]:
        allowed = frozenset(allowed_enum_members)
        return self._integer_constant_node(expression, enum_owner, allowed)

    def _integer_constant_node(self, expression, enum_owner, allowed):
        if isinstance(expression, IntLiteral):
            return (True, expression.value)
        if isinstance(expression, BoolLiteral):
            return (True, int(expression.value))
        if isinstance(expression, CharLiteral):
            return (True, self._character_constant_value(expression.value))
        if isinstance(expression, Identifier):
            return self._constant_identifier(expression.name, enum_owner, allowed)
        if isinstance(expression, FieldAccessExpr):
            return self._constant_field(expression, enum_owner, allowed)
        if isinstance(expression, SizeofExpr):
            return (True, None)
        if isinstance(expression, CastExpr):
            if not self.types.is_integral_value(expression.target_type):
                return (False, None)
            target = self.types.canonical_type(expression.target_type)
            if target is None:
                return (False, None)
            if isinstance(expression.expr, FloatLiteral):
                return (True, self.types.convert_integral_literal(expression.expr.value, target.base))
            valid, value = self._integer_constant_node(expression.expr, enum_owner, allowed)
            if not valid or value is None:
                return (valid, value)
            return (True, self.types.convert_integral_literal(value, target.base))
        if isinstance(expression, UnaryExpr) and expression.op in {"+", "-", "~", "!"}:
            valid, value = self._integer_constant_node(expression.operand, enum_owner, allowed)
            if not valid or value is None:
                return (valid, None)
            return (True, self._apply_constant_unary(expression.op, value))
        if isinstance(expression, BinaryExpr):
            if expression.op not in {
                "+",
                "-",
                "*",
                "/",
                "%",
                "<<",
                ">>",
                "&",
                "|",
                "^",
                "==",
                "!=",
                "<",
                ">",
                "<=",
                ">=",
                "&&",
                "||",
            }:
                return (False, None)
            left_valid, left = self._integer_constant_node(expression.left, enum_owner, allowed)
            right_valid, right = self._integer_constant_node(expression.right, enum_owner, allowed)
            if not left_valid or not right_valid:
                return (False, None)
            if left is None or right is None:
                return (True, None)
            return self._apply_constant_binary(expression.op, left, right)
        if isinstance(expression, TernaryExpr):
            condition_valid, condition = self._integer_constant_node(expression.condition, enum_owner, allowed)
            true_valid, true_value = self._integer_constant_node(expression.true_expr, enum_owner, allowed)
            false_valid, false_value = self._integer_constant_node(expression.false_expr, enum_owner, allowed)
            if not condition_valid or not true_valid or (not false_valid):
                return (False, None)
            if condition is not None:
                return (True, true_value if condition else false_value)
            if true_value == false_value:
                return (True, true_value)
            return (True, None)
        return (False, None)

    def _constant_identifier(self, name, enum_owner, allowed):
        if enum_owner is not None:
            if name in allowed:
                return (True, self.index.enum_constant_values.get((enum_owner, name)))
            if name in self.index.enum_table.get(enum_owner, ()):
                return (False, None)
            if self._is_constant_macro_name(name):
                return (True, None)
            return (False, None)
        owners = self.index.enum_member_owners.get(name, set())
        if len(owners) == 1:
            owner = next(iter(owners))
            return (True, self.index.enum_constant_values.get((owner, name)))
        if self._is_constant_macro_name(name):
            return (True, None)
        return (False, None)

    def _constant_field(self, expression, enum_owner, allowed):
        if not isinstance(expression.obj, Identifier):
            return (False, None)
        owner = expression.obj.name
        values = self.index.enum_table.get(owner)
        if values is None and owner in self.index.rich_enum_table:
            if enum_owner is not None:
                return (False, None)
            for index, variant in enumerate(self.index.rich_enum_table[owner].variants):
                if expression.field == variant.name:
                    return (True, index)
        if values is None or expression.field not in values:
            return (False, None)
        if enum_owner is not None and (owner != enum_owner or expression.field not in allowed):
            return (False, None)
        return (True, self.index.enum_constant_values.get((owner, expression.field)))

    def _is_constant_macro_name(self, name) -> bool:
        return self.index.source_macros.declared(name) or (name.isupper() and name != "NULL")

    def _character_constant_value(self, raw):
        return LiteralDecoder.decode_character(raw)

    @staticmethod
    def _apply_constant_unary(operator, value):
        return {"+": lambda: value, "-": lambda: -value, "~": lambda: ~value, "!": lambda: int(not value)}[operator]()

    @staticmethod
    def _apply_constant_binary(operator, left, right):
        if operator in {"/", "%"} and right == 0:
            return (False, None)
        if operator in {"<<", ">>"} and (not 0 <= right < 64):
            return (False, None)
        if operator == "/":
            quotient = abs(left) // abs(right)
            value = -quotient if (left < 0) != (right < 0) else quotient
            return (True, value)
        if operator == "%":
            _, quotient = ExpressionAnalyzer._apply_constant_binary("/", left, right)
            return (True, left - quotient * right)
        operations = {
            "+": lambda: left + right,
            "-": lambda: left - right,
            "*": lambda: left * right,
            "<<": lambda: left << right,
            ">>": lambda: left >> right,
            "&": lambda: left & right,
            "|": lambda: left | right,
            "^": lambda: left ^ right,
            "==": lambda: int(left == right),
            "!=": lambda: int(left != right),
            "<": lambda: int(left < right),
            ">": lambda: int(left > right),
            "<=": lambda: int(left <= right),
            ">=": lambda: int(left >= right),
            "&&": lambda: int(bool(left) and bool(right)),
            "||": lambda: int(bool(left) or bool(right)),
        }
        try:
            return (True, operations[operator]())
        except (KeyError, OverflowError):
            return (False, None)

    @staticmethod
    def _is_optional_value_expression(expression) -> bool:
        if isinstance(expression, FieldAccessExpr):
            return expression.optional
        return (
            isinstance(expression, CallExpr)
            and isinstance(expression.callee, FieldAccessExpr)
            and expression.callee.optional
        )

    def _validate_binary_expr(self, expression):
        left = self._infer_type(expression.left)
        right = self._infer_type(expression.right)
        if left is None or right is None:
            return
        self.aggregates.reject_thread_observation(expression.left)
        self.aggregates.reject_thread_observation(expression.right)
        operator = expression.op
        if left.base == right.base and self.types.is_active_type_parameter(left):
            return
        overload = self.types.operator_method(left, operator)
        if overload is not None:
            self.validate_operator_argument(expression, operator, expression.right, right, overload)
            self.validate_operator_access(left, operator, expression)
            return
        if operator == "+" and self.types.is_scalar_string_value(left) and self.types.is_scalar_string_value(right):
            return
        if operator in {"+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", "==", "!=", "<", ">", "<=", ">="} and (
            not self._validate_portable_numeric_mix(expression, left, right, f"Operator '{operator}'")
        ):
            return
        if operator == "??":
            try:
                self.types.coalesce_domain(
                    self.types.canonical_type(left),
                    self.types.canonical_type(right),
                    left_is_optional_value=self._is_optional_value_expression(expression.left),
                )
            except OperatorTypeError as error:
                self.session.error(str(error), expression.line, expression.col)
            return
        if operator in ("&&", "||"):
            valid = left.base == right.base == "bool"
        elif operator in ("&", "|", "^", "<<", ">>"):
            valid = self.types.is_integral_value(left) and self.types.is_integral_value(right)
        elif operator in ("+", "-"):
            numeric = self.types.is_numeric_value(left) and self.types.is_numeric_value(right)
            pointer_offset = (self.storage.is_raw_pointer_value(left) and self.types.is_integral_value(right)) or (
                operator == "+" and self.types.is_integral_value(left) and self.storage.is_raw_pointer_value(right)
            )
            pointer_difference = (
                operator == "-"
                and self.storage.is_raw_pointer_value(left)
                and self.storage.is_raw_pointer_value(right)
                and (self.types.types_compatible(left, right) or self.types.types_compatible(right, left))
            )
            valid = numeric or pointer_offset or pointer_difference
        elif operator in ("*", "/", "%"):
            valid = self.types.is_numeric_value(left) and self.types.is_numeric_value(right)
        elif operator in ("==", "!=", "<", ">", "<=", ">="):
            try:
                self.types.comparison_domain(
                    operator, self.types.canonical_type(left), self.types.canonical_type(right)
                )
            except OperatorTypeError as error:
                self.session.error(str(error), expression.line, expression.col)
            return
        else:
            return
        if not valid:
            self.session.error(
                f"Operator '{operator}' is not defined for '{self.types.format_type(left)}' and '{self.types.format_type(right)}'",
                expression.line,
                expression.col,
            )

    def _validate_ternary_expr(self, expression):
        true_type = self._infer_type(expression.true_expr)
        false_type = self._infer_type(expression.false_expr)
        if (
            true_type
            and false_type
            and (not self._validate_portable_numeric_mix(expression, true_type, false_type, "Ternary expression"))
        ):
            return
        if (
            true_type
            and false_type
            and (not self.types.types_compatible(true_type, false_type))
            and (not self.types.types_compatible(false_type, true_type))
        ):
            self.session.error(
                f"Ternary branches have incompatible types '{self.types.format_type(true_type)}' and '{self.types.format_type(false_type)}'",
                expression.line,
                expression.col,
            )

    def _validate_portable_numeric_mix(self, expression, left, right, context) -> bool:
        left = self.types.canonical_type(left)
        right = self.types.canonical_type(right)
        enum_names = frozenset(self.index.enum_table)
        if not (
            self.types.is_numeric_type(left, enum_names) and self.types.is_numeric_type(right, enum_names)
        ) or self.types.integer_mix_is_portable(left, right):
            return True
        self.session.error(
            f"{context} mixes ABI-dependent integer type '{self.types.format_type(left)}' with '{self.types.format_type(right)}'; cast explicitly to a fixed-width or built-in integer type",
            expression.line,
            expression.col,
        )
        return False

    def _inside_generic_declaration(self) -> bool:
        return bool(
            (self.session.current_class and self.session.current_class.generic_params)
            or (self.session.current_method and self.session.current_method.generic_params)
        )

    def _analyze_expr(self, expr):
        if expr is None:
            return
        if isinstance(expr, (IntLiteral, FloatLiteral, StringLiteral, CharLiteral, BoolLiteral, NullLiteral)):
            pass
        elif isinstance(expr, Identifier):
            self.calls.validate_default_macro_context(expr)
            self._analyze_identifier_value(expr)
        elif isinstance(expr, SelfExpr):
            self._record_lambda_self(expr)
            self._validate_self(expr)
        elif isinstance(expr, SuperExpr):
            if self.session.analyzing_constructor_default:
                self.session.error(
                    "Constructor defaults cannot reference 'super' before allocation", expr.line, expr.col
                )
            elif not self.session.current_class:
                self.session.error("'super' can only be used inside a class", expr.line, expr.col)
            elif not self.session.current_class.parent:
                self.session.error(
                    f"'super' cannot be used in class '{self.session.current_class.name}' which does not extend another class",
                    expr.line,
                    expr.col,
                )
        elif isinstance(expr, BinaryExpr):
            spine = [expr]
            while isinstance(spine[-1].left, BinaryExpr):
                spine.append(spine[-1].left)
            self._analyze_expr(spine[-1].left)
            for node in reversed(spine):
                if node.op in ("&&", "||"):
                    before_right = set(self.session.nonnull_paths)
                    seed = self.session.expression_flow_seeds.get(id(node.right), frozenset(before_right))
                    with self.session.nonnull_frame(seed):
                        self._analyze_expr(node.right)
                        right_flow = set(self.session.nonnull_paths)
                    self.session.replace_nonnull_paths(before_right & right_flow)
                else:
                    self._analyze_expr(node.right)
                self._validate_literal_divisor(node.op, node.right)
                self._validate_binary_expr(node)
                if node is not expr:
                    node_t = self._infer_type(node)
                    if node_t:
                        self.session.record_node_type(node, node_t)
        elif isinstance(expr, UnaryExpr):
            self._analyze_expr(expr.operand)
            self._validate_unary_expr(expr)
        elif isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                self.calls.validate_default_macro_context(expr.callee)
                self._analyze_identifier_value(expr.callee, direct_callee=True)
            elif isinstance(expr.callee, FieldAccessExpr):
                self._analyze_field_access(expr.callee, call_target=True)
            else:
                self._analyze_expr(expr.callee)
            self._infer_type(expr.callee)
            for argument in expr.args:
                self._analyze_expr(argument)
            self._validate_mutex_destroy_receiver(expr)
            self.calls.analyze_call(expr)
        elif isinstance(expr, IndexExpr):
            self._analyze_expr(expr.obj)
            self._analyze_expr(expr.index)
            self._validate_index_expr(expr)
        elif isinstance(expr, FieldAccessExpr):
            self._analyze_field_access(expr)
        elif isinstance(expr, AssignExpr):
            with self.session.assignment_target():
                self._analyze_expr(expr.target)
            self._analyze_expr(expr.value)
            self._validate_literal_divisor(expr.op, expr.value)
            if isinstance(expr.value, (ListLiteral, MapLiteral, BraceInitializer)):
                target_type = self._infer_type(expr.target)
                if target_type:
                    self.calls.apply_initializer_plan(
                        self.aggregates.plan_aggregate_initializer(
                            target_type, expr.value, "Assignment", expr.line, expr.col
                        )
                    )
                    self.calls.apply_initializer_plan(
                        self.aggregates.plan_collection_initializer(
                            target_type, expr.value, "Assignment", expr.line, expr.col
                        )
                    )
            self._validate_assignment(expr)
            self.ownership.validate_opaque_borrow_storage(
                self._infer_type(expr.target), expr.value, "Assignment", expr.line, expr.col
            )
        elif isinstance(expr, TernaryExpr):
            self._analyze_expr(expr.condition)
            self.aggregates.reject_thread_observation(expr.condition)
            before_branches = set(self.session.nonnull_paths)
            true_seed = self.session.expression_flow_seeds.get(id(expr.true_expr), frozenset(before_branches))
            with self.session.nonnull_frame(true_seed):
                self._analyze_expr(expr.true_expr)
                true_flow = set(self.session.nonnull_paths)
            false_seed = self.session.expression_flow_seeds.get(id(expr.false_expr), frozenset(before_branches))
            with self.session.nonnull_frame(false_seed):
                self._analyze_expr(expr.false_expr)
                false_flow = set(self.session.nonnull_paths)
            self.session.replace_nonnull_paths(true_flow & false_flow)
            self._validate_ternary_expr(expr)
        elif isinstance(expr, CastExpr):
            expr.target_type = self.types.upgrade_class_type(expr.target_type)
            self.generics.collect_type_instances(expr.target_type)
            self._analyze_expr(expr.expr)
            self._validate_cast_expr(expr)
        elif isinstance(expr, SizeofExpr):
            if isinstance(expr.operand, SizeofType):
                self.generics.collect_type_instances(expr.operand.type)
            elif isinstance(expr.operand, SizeofExprOp):
                self._analyze_expr(expr.operand.expr)
            self.aggregates.validate_sizeof_operand(expr)
        elif isinstance(expr, ListLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
                self.aggregates.reject_thread_value_escape(el, "embedded in aggregate values")
            if len(expr.elements) >= 2:
                first_type = next(
                    (
                        self._infer_type(element)
                        for element in expr.elements
                        if not self.types.is_empty_contextual_literal(element)
                    ),
                    None,
                )
                if first_type:
                    for i, el in enumerate(expr.elements):
                        if self.types.is_empty_contextual_literal(el):
                            continue
                        el_type = self._infer_type(el)
                        if el_type and (not self.types.types_compatible(first_type, el_type)):
                            self.session.error(
                                f"List element {i} has type '{el_type.base}' but expected '{first_type.base}'",
                                getattr(el, "line", 0),
                                getattr(el, "col", 0),
                            )
            inferred_literal = self._infer_type(expr)
            if expr.elements:
                self.generics.record_class_method_use(inferred_literal, "push")
        elif isinstance(expr, MapLiteral):
            for entry in expr.entries:
                self._analyze_expr(entry.key)
                self._analyze_expr(entry.value)
                self.aggregates.reject_thread_value_escape(entry.key, "embedded in aggregate values")
                self.aggregates.reject_thread_value_escape(entry.value, "embedded in aggregate values")
            if expr.entries:
                self.generics.record_class_method_use(self._infer_type(expr), "put")
        elif isinstance(expr, FStringLiteral):
            for part in expr.parts:
                if isinstance(part, FStringExpr):
                    self._analyze_expr(part.expression)
                    self.aggregates.reject_thread_value_escape(part.expression, "formatted as values")
                    part_type = self._infer_type(part.expression)
                    if self.types.has_scalar_to_string(part_type):
                        self.generics.record_class_method_use(part_type, "toString")
        elif isinstance(expr, TupleLiteral):
            for el in expr.elements:
                self._analyze_expr(el)
                self.aggregates.reject_thread_value_escape(el, "embedded in aggregate values")
            elem_types = []
            for el in expr.elements:
                t = self._infer_type(el)
                elem_types.append(t if t else TypeExpr(base="int"))
            tuple_type = TypeExpr(base="Tuple", generic_args=elem_types)
            self.generics.collect_type_instances(tuple_type)
        elif isinstance(expr, LambdaExpr):
            if self._inside_generic_declaration():
                self.session.error(
                    "Lambda expressions are not supported inside generic declarations", expr.line, expr.col
                )
            if id(expr) not in self.session.lambda_body_facts:
                self.session.error("Lambda body was not prepared by statement analysis", expr.line, expr.col)
        elif isinstance(expr, NewExpr):
            expr.type = self.types.upgrade_class_type(expr.type)
            self.generics.collect_type_instances(expr.type)
            for arg in expr.args:
                self._analyze_expr(arg)
                self.aggregates.reject_thread_value_escape(arg, "passed as arguments")
            if expr.type.base == "Mutex":
                if any(expr.arg_names or []):
                    self.session.error("'new Mutex<T>()' does not accept named arguments", expr.line, expr.col)
                if len(expr.args) != 1:
                    self.session.error("'new Mutex<T>()' expects exactly 1 argument", expr.line, expr.col)
                elif expr.type.generic_args:
                    actual = self._infer_type(expr.args[0])
                    expected = expr.type.generic_args[0]
                    self.calls.validate_managed_string_source(
                        expected, expr.args[0], "Mutex initializer", expr.line, expr.col
                    )
                    self.storage.validate_mutex_volatile_initializer(expected, expr)
                    if actual and (not self.types.types_compatible(expected, actual)):
                        self.session.error(
                            f"Mutex initializer expects '{self.types.format_type(expected)}' but got '{self.types.format_type(actual)}'",
                            expr.line,
                            expr.col,
                        )
            if expr.type.base in self.index.class_table:
                cls = self.index.class_table[expr.type.base]
                if cls.is_abstract:
                    self.session.error(f"Cannot instantiate abstract class '{cls.name}'", expr.line, expr.col)
                substitutions = dict(zip(cls.generic_params, expr.type.generic_args))
                self.calls.validate_constructor_args(cls, expr.args, expr.arg_names, expr.line, expr.col, substitutions)
                if cls.name == "CallbackRegistration":
                    self.calls.validate_direct_realtime_callback(cls, expr, "invoke")
                elif cls.name == "RealtimeAudioProgram":
                    self.calls.validate_direct_realtime_callback(cls, expr, "process")
        elif isinstance(expr, SpawnExpr):
            if self._inside_generic_declaration() and (not isinstance(expr.fn, LambdaExpr)):
                self.session.error(
                    "spawn expressions are not supported inside generic declarations", expr.line, expr.col
                )
            self._analyze_expr(expr.fn)
            self._validate_spawn_expr(expr)
            ret_type = self._infer_spawn_return_type(expr.fn)
            thread_type = TypeExpr(base="Thread", generic_args=[ret_type])
            self.generics.collect_type_instances(thread_type)
        elif isinstance(expr, BraceInitializer):
            for el in expr.elements:
                self._analyze_expr(el)
                self.aggregates.reject_thread_value_escape(el, "embedded in aggregate values")
        inferred = self._infer_type(expr)
        if inferred:
            self.session.record_node_type(expr, inferred)

    def _validate_index_expr(self, expression):
        object_type = self.types.canonical_type(self._infer_type(expression.obj))
        index_type = self._infer_type(expression.index)
        if object_type is None:
            return
        if object_type.base == "Tuple":
            self.session.error(
                "Tuple values are not dynamically indexable; use ._N fields", expression.line, expression.col
            )
            return
        expected_index = None
        if object_type.base == "Map" and len(object_type.generic_args) == 2:
            expected_index = object_type.generic_args[0]
        protocol = self.types.resolve_index_protocol(
            object_type, active_type_params=self.storage.active_type_parameters()
        )
        if expected_index is None and protocol is not None:
            assigning = self.session.analyzing_assignment_target
            method = None if assigning else protocol.getter
            if method is not None:
                expected_index = method.params[0].type
                if object_type.generic_args:
                    substitutions = protocol.substitutions(object_type)
                    expected_index = self.types.substitute_type(expected_index, substitutions)
            if not assigning and protocol.getter is None:
                self.session.error(
                    f"Type '{self.types.format_type(object_type)}' has no indexed getter; indexing requires an instance get(index) method",
                    expression.line,
                    expression.col,
                )
            elif not assigning:
                self._validate_indexed_method_access(protocol, protocol.getter, expression.line, expression.col)
        integral_index = (
            object_type.base in ("string", "Vector", "List", "Array")
            or self.storage.is_raw_pointer_value(object_type)
            or object_type.is_array
        )
        if expected_index is not None and index_type:
            if not self.types.types_compatible(expected_index, index_type):
                self.session.error(
                    f"Index expression expects '{self.types.format_type(expected_index)}' but got '{self.types.format_type(index_type)}'",
                    expression.index.line,
                    expression.index.col,
                )
        elif integral_index and index_type and (not self.types.is_integral_value(index_type)):
            self.session.error(
                "Index expression must have an integral type", expression.index.line, expression.index.col
            )
        indexable = expected_index is not None or integral_index or protocol is not None
        if not indexable:
            if object_type.base in self.index.class_table:
                self.session.error(
                    f"Type '{self.types.format_type(object_type)}' has no indexed getter; indexing requires an instance get(index) method",
                    expression.line,
                    expression.col,
                )
            else:
                self.session.error(
                    f"Type '{self.types.format_type(object_type)}' is not indexable", expression.line, expression.col
                )

    def _record_lambda_identifier(self, expression):
        if not self.session.lambda_capture_contexts:
            return
        symbol = self.session.scope.lookup(expression.name)
        if symbol is None:
            return
        for outer_symbols, captures in self.session.lambda_capture_contexts:
            if outer_symbols.get(expression.name) is symbol:
                captures[expression.name] = symbol.type
        current_outer, _current_captures = self.session.lambda_capture_contexts[-1]
        if current_outer.get(expression.name) is symbol:
            self.session.scope.define(expression.name, dataclasses.replace(symbol, kind="capture", owned_storage=False))

    def _record_lambda_self(self, expression):
        if not self.session.lambda_capture_contexts:
            return
        symbol = self.session.scope.lookup("self")
        if symbol is None:
            return
        for outer_symbols, captures in self.session.lambda_capture_contexts:
            if outer_symbols.get("self") is symbol:
                captures["self"] = symbol.type
        current_outer, _current_captures = self.session.lambda_capture_contexts[-1]
        if current_outer.get("self") is symbol:
            self.session.scope.define("self", dataclasses.replace(symbol, kind="capture", owned_storage=False))

    def _infer_spawn_return_type(self, fn_expr) -> TypeExpr:
        """Infer the return type of a spawned callable (usually a lambda)."""
        if isinstance(fn_expr, LambdaExpr):
            if fn_expr.return_type:
                return fn_expr.return_type
            return self._infer_lambda_return(fn_expr)
        fn_type = self.types.canonical_type(self._infer_type(fn_expr))
        if fn_type and fn_type.base in {"__fn_ptr", "__realtime_fn_ptr"} and fn_type.generic_args:
            return fn_type.generic_args[0]
        return TypeExpr(base="void")

    def _infer_lambda_return(self, expr) -> TypeExpr:
        """Infer the return type of a lambda from its body."""
        inferred, _ = self.infer_lambda_return_details(expr)
        return inferred

    def infer_lambda_return_details(self, expr):
        if isinstance(expr.body, LambdaExprBody):
            inferred = self._infer_type(expr.body.expression)
            return (inferred or TypeExpr(base="void"), [])
        return_types = []
        self._collect_lambda_return_types(expr.body, return_types)
        if not return_types:
            return (TypeExpr(base="void"), [])
        inferred = return_types[0]
        conflicts = [
            actual
            for actual in return_types[1:]
            if not self.types.types_compatible(inferred, actual) and (not self.types.types_compatible(actual, inferred))
        ]
        return (inferred, conflicts)

    def _collect_lambda_return_types(self, node, result):
        if node is None:
            return
        if isinstance(node, ReturnStmt):
            result.append(
                self._infer_type(node.value) or TypeExpr(base="void")
                if node.value is not None
                else TypeExpr(base="void")
            )
            return
        if isinstance(node, LambdaExpr):
            return
        if not dataclasses.is_dataclass(node):
            return
        for field in dataclasses.fields(node):
            child = getattr(node, field.name, None)
            if isinstance(child, (list, tuple)):
                for item in child:
                    self._collect_lambda_return_types(item, result)
            else:
                self._collect_lambda_return_types(child, result)

    def _analyze_field_access(self, expr, *, call_target=False):
        if isinstance(expr.obj, Identifier) and expr.obj.name == "MemoryOrder":
            if expr.field not in {"RELAXED", "ACQUIRE", "RELEASE", "ACQ_REL", "SEQ_CST"}:
                self.session.error(f"MemoryOrder has no member '{expr.field}'", expr.line, expr.col)
            return
        if isinstance(expr.obj, Identifier):
            self._analyze_identifier_value(expr.obj, qualification_receiver=True)
        else:
            self._analyze_expr(expr.obj)
        obj_type = self._infer_type(expr.obj)
        if (
            isinstance(expr.obj, Identifier)
            and self.session.scope.lookup(expr.obj.name) is None
            and (expr.obj.name in self.index.rich_enum_table)
        ):
            declaration = self.index.rich_enum_table[expr.obj.name]
            if not call_target and (not any(variant.name == expr.field for variant in declaration.variants)):
                self.session.error(f"Rich enum '{declaration.name}' has no variant '{expr.field}'", expr.line, expr.col)
            return
        if (
            isinstance(expr.obj, Identifier)
            and self.session.scope.lookup(expr.obj.name) is None
            and (expr.obj.name in self.index.class_table)
        ):
            self._validate_static_member_access(expr, self.index.class_table[expr.obj.name])
            return
        if (
            obj_type
            and getattr(obj_type, "is_nullable", False)
            and (not getattr(expr, "optional", False))
            and id(expr.obj) not in self.session.known_nonnull_expression_ids
        ):
            self.session.warning(
                f"Non-optional access '.{expr.field}' on nullable type '{obj_type.base}?' — use '?.{expr.field}' or check for null",
                expr.line,
                expr.col,
            )
        if obj_type and obj_type.base == "Thread":
            valid = {"join"}
            if expr.field not in valid:
                self.session.error(f"Thread<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base == "Mutex":
            valid = {"get", "set", "destroy"}
            if expr.field not in valid:
                self.session.error(f"Mutex<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base == "Atomic":
            if expr.field not in {
                "init",
                "load",
                "store",
                "exchange",
                "fetchAdd",
                "fetchSub",
                "fetchAnd",
                "fetchOr",
                "fetchXor",
                "compareExchangeStrong",
            }:
                self.session.error(f"Atomic<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base == "Span":
            if expr.field not in {"length", "isEmpty", "isValid", "tryGet", "trySet"}:
                self.session.error(f"Span<T> has no method '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base in self.index.rich_enum_table:
            if expr.field not in {"tag", "data"} and (not (call_target and expr.field == "toString")):
                self.session.error(f"Rich enum '{obj_type.base}' has no field '{expr.field}'", expr.line, expr.col)
            return
        if obj_type and obj_type.base == "string":
            if not call_target:
                self.session.error(
                    f"Type 'string' has no field '{expr.field}'; use a string method call", expr.line, expr.col
                )
            return
        if obj_type and self.aggregates.validate_tuple_field_access(expr, obj_type):
            return
        if obj_type and self.aggregates.validate_struct_field_access(expr, obj_type):
            return
        if obj_type and obj_type.base in self.index.class_table:
            cls = self.index.class_table[obj_type.base]
            if expr.field in cls.properties:
                prop = cls.properties[expr.field]
                accessor = "set" if self.session.analyzing_assignment_target else "get"
                self.generics.record_class_callable_use(obj_type, accessor, expr.field)
                if prop.access == "private":
                    owner = cls.property_owners.get(expr.field, cls.name)
                    if self.session.current_class is None or self.session.current_class.name != owner:
                        self.session.error(
                            f"Cannot access private property '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
                if not self.session.analyzing_assignment_target and (not prop.has_getter):
                    self.session.error(f"Property '{expr.field}' has no getter", expr.line, expr.col)
                return
            if expr.field in cls.fields:
                field_decl = cls.fields[expr.field]
                if field_decl.access == "private":
                    owner = cls.field_owners.get(expr.field, cls.name)
                    if self.session.current_class is None or self.session.current_class.name != owner:
                        self.session.error(
                            f"Cannot access private field '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
            elif expr.field in cls.methods:
                method = cls.methods[expr.field]
                if method.access == "class":
                    self.session.error(
                        f"Class method '{expr.field}' must be accessed on '{cls.name}', not on an instance",
                        expr.line,
                        expr.col,
                    )
                if method.access == "private":
                    owner = cls.method_owners.get(expr.field, cls.name)
                    if self.session.current_class is None or self.session.current_class.name != owner:
                        self.session.error(
                            f"Cannot access private method '{expr.field}' of class '{owner}'", expr.line, expr.col
                        )
            else:
                self.session.error(f"Class '{cls.name}' has no field or method '{expr.field}'", expr.line, expr.col)

    def _validate_static_member_access(self, expression, class_info) -> None:
        name = expression.field
        member = class_info.static_fields.get(name)
        if member is not None:
            self._validate_private_member_access(
                member, class_info.field_owners.get(name, class_info.name), "field", name, expression
            )
            return
        method = class_info.methods.get(name)
        if method is not None:
            if method.access != "class":
                self.session.error(
                    f"Method '{name}' is not a class method, cannot access it statically",
                    expression.line,
                    expression.col,
                )
                return
            self._validate_private_member_access(
                method, class_info.method_owners.get(name, class_info.name), "method", name, expression
            )
            return
        if name in class_info.fields or name in class_info.properties:
            self.session.error(
                f"Instance member '{name}' cannot be accessed on class '{class_info.name}'",
                expression.line,
                expression.col,
            )
            return
        self.session.error(
            f"Class '{class_info.name}' has no static field or method '{name}'", expression.line, expression.col
        )

    def _validate_private_member_access(self, member, owner, kind, name, expression):
        if member.access == "private" and (
            self.session.current_class is None or self.session.current_class.name != owner
        ):
            self.session.error(
                f"Cannot access private {kind} '{name}' of class '{owner}'", expression.line, expression.col
            )

    def _validate_self(self, expr):
        if self.session.analyzing_constructor_default:
            self.session.error("Constructor defaults cannot reference 'self' before allocation", expr.line, expr.col)
        elif self.session.current_class is None:
            self.session.error("'self' used outside of a class", expr.line, expr.col)
        elif self.session.current_method is None:
            self.session.error("'self' used outside of a method", expr.line, expr.col)
        elif self.session.current_method.access == "class":
            self.session.error("'self' cannot be used in a class (static) method", expr.line, expr.col)


__all__ = ["ExpressionAnalyzer", "ExpressionValuePlan"]
