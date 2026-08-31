"""Call binding, callable values, signatures, and hosted calls."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from src.compiler.python.abi.declarations import DEALLOC_FREE, RETURN_ALIAS, RETURN_FRESH, RETURN_INDEPENDENT
from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.aggregates import (
    InitializerArrayFieldCheck,
    InitializerCompatibilityCheck,
    InitializerPlan,
    InitializerStringConversionCheck,
    InitializerTypeContext,
    InitializerValueCheck,
)
from src.compiler.python.analyzer.generics import GenericMethodInferencePlan
from src.compiler.python.analyzer.gpu import WGSL_SAME_TYPE_BUILTINS
from src.compiler.python.analyzer.ownership import ConsumptionArgumentPlan
from src.compiler.python.analyzer.program import DeclarationIndex
from src.compiler.python.analyzer.types import (
    C_POINTER_CALL_RESULTS,
    C_SCALAR_CALL_RESULTS,
    GENERIC_COMPARISON_INTRINSICS,
    GENERIC_INTRINSICS,
    STRING_METHODS,
    OperatorTypeError,
    TypeSystem,
)
from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    Identifier,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    TernaryExpr,
    TypeExpr,
)

if TYPE_CHECKING:
    from src.compiler.python.analyzer.aggregates import AggregateAnalyzer
    from src.compiler.python.analyzer.generics import GenericAnalyzer
    from src.compiler.python.analyzer.gpu import GpuAnalyzer
    from src.compiler.python.analyzer.macros import SourceMacroAnalyzer
    from src.compiler.python.analyzer.ownership import OwnershipAnalyzer
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.storage import StorageModel


_CONTEXT_SENSITIVE_PREDEFINED = frozenset({"__func__", "__LINE__", "__FILE__"})
_MEMORY_ORDERS = frozenset({"RELAXED", "ACQUIRE", "RELEASE", "ACQ_REL", "SEQ_CST"})
_ATOMIC_METHODS = frozenset(
    {
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
    }
)
_ATOMIC_ORDER_DOMAINS = {
    "load": frozenset({"RELAXED", "ACQUIRE", "SEQ_CST"}),
    "store": frozenset({"RELAXED", "RELEASE", "SEQ_CST"}),
}
_CAS_FAILURE_ORDERS = {
    "RELAXED": frozenset({"RELAXED"}),
    "ACQUIRE": frozenset({"RELAXED", "ACQUIRE"}),
    "RELEASE": frozenset({"RELAXED"}),
    "ACQ_REL": frozenset({"RELAXED", "ACQUIRE"}),
    "SEQ_CST": frozenset({"RELAXED", "ACQUIRE", "SEQ_CST"}),
}


class CallAnalyzer:
    """Call binding, callable values, signatures, and hosted calls."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
        storage: StorageModel,
        ownership: OwnershipAnalyzer,
        gpu: GpuAnalyzer,
        macros: SourceMacroAnalyzer,
        generics: GenericAnalyzer,
    ) -> None:
        self.session = session
        self.index = index
        self.aggregates = aggregates
        self.generics = generics
        self.gpu = gpu
        self.macros = macros
        self.ownership = ownership
        self.storage = storage
        self.types = types

    def apply_initializer_plan(self, plan: InitializerPlan) -> bool:
        """Apply an initializer shape plan through the active semantic policies."""
        for step in plan.steps:
            if isinstance(step, InitializerValueCheck):
                self.validate_managed_string_source(step.expected, step.value, step.subject, step.line, step.col)
                self.ownership.validate_opaque_borrow_storage(
                    step.expected, step.value, step.subject, step.line, step.col
                )
                self.storage.validate_volatile_reference_conversion(
                    step.expected, step.value, step.subject, step.line, step.col
                )
                if step.validate_fixed_array:
                    self.aggregates.validate_fixed_array_initializer(
                        step.expected, step.value, step.subject, step.line, step.col
                    )
                if step.contextualize_constructor:
                    self.contextualize_generic_constructor(step.expected, step.value)
            elif isinstance(step, InitializerArrayFieldCheck):
                self.aggregates.validate_pointer_backed_array_field_initializer(
                    step.field, step.value, step.subject, step.line, step.col
                )
            elif isinstance(step, InitializerStringConversionCheck):
                if self.types.requires_string_conversion(step.expected, self.type_of(step.value)):
                    self.session.error(step.message, step.line, step.col)
            elif isinstance(step, InitializerCompatibilityCheck):
                actual = self.type_of(step.value)
                if actual is None:
                    continue
                if step.reject_void and self.types.is_void_value(actual):
                    self.session.error(
                        f"{step.subject} cannot be initialized from a void expression", step.line, step.col
                    )
                elif not self.types.types_compatible(step.expected, actual):
                    suffix = " elements" if step.element else ""
                    self.session.error(
                        f"{step.subject} expects '{self.types.format_type(step.expected)}'{suffix} but got '{self.types.format_type(actual)}'",
                        step.line,
                        step.col,
                    )
            elif isinstance(step, InitializerTypeContext):
                self.session.record_node_type(step.value, step.expected)
                self.generics.collect_type_instances(step.expected)
                if isinstance(step.value, ListLiteral) and step.value.elements:
                    self.generics.record_class_method_use(step.expected, "push")
                elif isinstance(step.value, MapLiteral) and step.value.entries:
                    self.generics.record_class_method_use(step.expected, "put")
        return plan.contextual

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def _validate_source_macro_call(self, call) -> bool:
        plan = self.macros.plan_call(call)
        if plan is None:
            return False
        for argument_plan in plan.arguments:
            argument = argument_plan.argument
            if argument_plan.callable_value:
                self.session.error(
                    f"Source macro '{plan.name}' cannot accept callable argument {argument_plan.index + 1} because macro expansion bypasses semantic call analysis",
                    getattr(argument, "line", call.line),
                    getattr(argument, "col", call.col),
                )
                continue
            needs_boundary = argument_plan.type_requires_boundary or self.ownership.expression_is_opaque_borrow(
                argument
            )
            if not needs_boundary:
                continue
            expected = argument_plan.read_only_type
            actual = self.type_of(argument)
            safe = bool(
                expected is not None
                and (not self.ownership.expression_produces_owned_result(argument))
                and actual is not None
                and (
                    self._hosted_argument_type_is_deferred(expected, actual)
                    or self.types.types_compatible(expected, actual)
                )
            )
            if safe:
                continue
            self.session.error(
                f"Source macro '{plan.name}' cannot accept managed or opaque-borrow argument {argument_plan.index + 1} because its expansion is not a proven read-only hosted call",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
        return True

    def _generic_method_plan(self, expression, parameters) -> GenericMethodInferencePlan:
        names = self._arg_names(expression.args, expression.arg_names)
        return GenericMethodInferencePlan(
            arguments=tuple(expression.args),
            bindings=tuple(self._bound_arguments(parameters, names)),
        )

    def _consumption_argument_plan(self, parameters, arguments, argument_names) -> ConsumptionArgumentPlan:
        names = self._arg_names(arguments, argument_names)
        return ConsumptionArgumentPlan(
            arguments=tuple(arguments),
            bindings=tuple(self._bound_arguments(parameters, names)),
        )

    def _validate_builtin_method_call(self, expression, receiver_type) -> bool:
        callee = expression.callee
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.index.rich_enum_table:
            self._validate_rich_enum_constructor(expression)
            return True
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.index.class_table:
            return False
        receiver_type = self.types.canonical_type(receiver_type)
        if self.types.is_scalar_string_value(receiver_type):
            spec = STRING_METHODS.get(callee.field)
            if spec is None:
                self.session.error(f"String has no method '{callee.field}'", expression.line, expression.col)
            else:
                expected = [TypeExpr(base=name) for name in spec.argument_types]
                self._validate_builtin_signature(f"String.{callee.field}", expected, expression)
            return True
        if receiver_type and receiver_type.base == "Thread":
            if callee.field == "join":
                self._validate_builtin_signature("Thread.join", [], expression)
                self.aggregates.validate_thread_join_receiver(expression)
            else:
                self.session.error(f"Thread<T> has no method '{callee.field}'", expression.line, expression.col)
            return True
        if receiver_type and receiver_type.base == "Mutex":
            signatures = {"get": [], "destroy": [], "set": list(receiver_type.generic_args[:1])}
            if callee.field in signatures:
                self._validate_builtin_signature(f"Mutex.{callee.field}", signatures[callee.field], expression)
            else:
                self.session.error(f"Mutex<T> has no method '{callee.field}'", expression.line, expression.col)
            return True
        if receiver_type and receiver_type.base == "Atomic" and receiver_type.generic_args:
            self._validate_atomic_method(expression, receiver_type)
            return True
        if receiver_type and receiver_type.base == "Span" and receiver_type.generic_args:
            element = receiver_type.generic_args[0]
            output_element = replace(element, is_const=False, is_volatile=False)
            signatures = {
                "length": [],
                "isEmpty": [],
                "isValid": [],
                "tryGet": [TypeExpr(base="size_t"), self.types.add_outer_pointer(output_element)],
                "trySet": [TypeExpr(base="size_t"), element],
            }
            if callee.field not in signatures:
                self.session.error(f"Span<T> has no method '{callee.field}'", expression.line, expression.col)
            else:
                self._validate_builtin_signature(f"Span.{callee.field}", signatures[callee.field], expression)
                if callee.field == "trySet" and element.is_const:
                    self.session.error("Span<const T>.trySet is not available", expression.line, expression.col)
            return True
        if receiver_type and receiver_type.base in self.index.rich_enum_table:
            if callee.field != "toString":
                self.session.error(
                    f"Rich enum '{receiver_type.base}' has no method '{callee.field}'", expression.line, expression.col
                )
            else:
                self._validate_builtin_signature(f"{receiver_type.base}.toString", [], expression)
            return True
        if self._is_builtin_scalar_receiver(receiver_type):
            if callee.field != "toString":
                self.session.error(
                    f"Type '{self.types.format_type(receiver_type)}' has no method '{callee.field}'",
                    expression.line,
                    expression.col,
                )
            else:
                self._validate_builtin_signature(f"{self.types.format_type(receiver_type)}.toString", [], expression)
            return True
        return False

    def _validate_atomic_method(self, expression, receiver_type) -> None:
        method = expression.callee.field
        if method not in _ATOMIC_METHODS:
            self.session.error(f"Atomic<T> has no method '{method}'", expression.line, expression.col)
            return
        payload = receiver_type.generic_args[0]
        order = TypeExpr(base="MemoryOrder")
        signatures = {
            "init": [payload],
            "load": [order],
            "store": [payload, order],
            "exchange": [payload, order],
            "fetchAdd": [payload, order],
            "fetchSub": [payload, order],
            "fetchAnd": [payload, order],
            "fetchOr": [payload, order],
            "fetchXor": [payload, order],
            "compareExchangeStrong": [self.types.add_outer_pointer(payload), payload, order, order],
        }
        self._validate_builtin_signature(f"Atomic.{method}", signatures[method], expression)
        if method.startswith("fetch") and not self.types.is_integral_value(payload):
            self.session.error(f"Atomic.{method} requires an integral payload", expression.line, expression.col)
        order_indices = {
            "load": (0,),
            "store": (1,),
            "exchange": (1,),
            "fetchAdd": (1,),
            "fetchSub": (1,),
            "fetchAnd": (1,),
            "fetchOr": (1,),
            "fetchXor": (1,),
            "compareExchangeStrong": (2, 3),
        }.get(method, ())
        names = [
            self._literal_memory_order(expression.args[index], f"Atomic.{method}")
            for index in order_indices
            if index < len(expression.args)
        ]
        if method in _ATOMIC_ORDER_DOMAINS and names:
            accepted = _ATOMIC_ORDER_DOMAINS[method]
            if names[0] is not None and names[0] not in accepted:
                self.session.error(
                    f"Atomic.{method} does not accept MemoryOrder.{names[0]}",
                    expression.line,
                    expression.col,
                )
        if method == "compareExchangeStrong" and len(names) == 2 and all(name is not None for name in names):
            success, failure = names
            if failure not in _CAS_FAILURE_ORDERS[success]:
                self.session.error(
                    f"Atomic.compareExchangeStrong failure order MemoryOrder.{failure} is not allowed with success order MemoryOrder.{success}",
                    expression.line,
                    expression.col,
                )

    def _literal_memory_order(self, argument, operation: str) -> str | None:
        if (
            not isinstance(argument, FieldAccessExpr)
            or not isinstance(argument.obj, Identifier)
            or argument.obj.name != "MemoryOrder"
            or argument.field not in _MEMORY_ORDERS
        ):
            self.session.error(f"{operation} requires a literal MemoryOrder member", argument.line, argument.col)
            return None
        return argument.field

    def _is_builtin_scalar_receiver(self, type_expr) -> bool:
        return bool(
            type_expr
            and (
                type_expr.base in self.types.NUMERIC_TYPES
                or type_expr.base == "bool"
                or type_expr.base in self.index.enum_table
            )
            and (type_expr.pointer_depth == 0)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def _validate_builtin_signature(self, name, expected_types, expression):
        if any(expression.arg_names or []):
            self.session.error(f"'{name}()' does not accept named arguments", expression.line, expression.col)
        if len(expression.args) != len(expected_types):
            self.session.error(
                f"'{name}()' expects {len(expected_types)} argument(s) but got {len(expression.args)}",
                expression.line,
                expression.col,
            )
        for index, (expected, argument) in enumerate(zip(expected_types, expression.args), 1):
            self.ownership.validate_opaque_call_argument(None, index - 1, expected, argument, name)
            self.storage.validate_volatile_reference_conversion(
                expected,
                argument,
                f"Argument {index} to '{name}()'",
                getattr(argument, "line", expression.line),
                getattr(argument, "col", expression.col),
            )
            actual = self.type_of(argument)
            if actual and (not self.types.types_compatible(expected, actual)):
                self.session.error(
                    f"Argument {index} to '{name}()' expects '{self.types.format_type(expected)}' but got '{self.types.format_type(actual)}'",
                    getattr(argument, "line", expression.line),
                    getattr(argument, "col", expression.col),
                )

    def _validate_rich_enum_constructor(self, expression):
        callee = expression.callee
        enum_decl = self.index.rich_enum_table[callee.obj.name]
        variant = next((item for item in enum_decl.variants if item.name == callee.field), None)
        if variant is None:
            self.session.error(
                f"Rich enum '{enum_decl.name}' has no variant '{callee.field}'", expression.line, expression.col
            )
            return
        self._validate_call_signature(
            f"{enum_decl.name}.{variant.name}",
            variant.params,
            expression.args,
            expression.arg_names,
            expression.line,
            expression.col,
        )
        self._reject_owned_rich_enum_defaults(expression, enum_decl, variant)

    def _reject_owned_rich_enum_defaults(self, expression, enum_decl, variant):
        names = self._arg_names(expression.args, expression.arg_names)
        supplied = {
            parameter_index for parameter_index, _argument_index in self._bound_arguments(variant.params, names)
        }
        for index, parameter in enumerate(variant.params):
            default = parameter.default
            if default is None or index in supplied:
                continue
            if id(default) not in self.session.rich_enum_unsafe_default_ids:
                continue
            self.session.error(
                f"Omitted default for rich-enum payload '{enum_decl.name}.{variant.name}.{parameter.name}' produces a caller-owned temporary; rich-enum payloads are shallow borrowed references, so pass a prebound owner explicitly",
                expression.line,
                expression.col,
            )

    def _arg_names(self, args, arg_names):
        names = list(arg_names or [])
        while len(names) < len(args):
            names.append("")
        return names

    def _validate_call_arity(self, name, params, args, names, line, col):
        if any(names):
            self._validate_named_call(name, params, args, names, line, col)
            return
        required = sum(1 for param in params if getattr(param, "default", None) is None)
        if len(args) < required:
            self.session.error(f"'{name}()' expects at least {required} argument(s) but got {len(args)}", line, col)
        elif len(args) > len(params):
            self.session.error(f"'{name}()' expects at most {len(params)} argument(s) but got {len(args)}", line, col)

    def _validate_named_call(self, name, params, args, names, line, col):
        parameter_names = [param.name for param in params]
        supplied = set()
        positional_index = 0
        saw_named = False
        for argument_name in names:
            if argument_name:
                saw_named = True
                if argument_name not in parameter_names:
                    self.session.error(f"'{name}()' has no parameter named '{argument_name}'", line, col)
                    continue
                parameter_index = parameter_names.index(argument_name)
                if parameter_index in supplied:
                    self.session.error(f"'{name}()' got argument '{argument_name}' more than once", line, col)
                supplied.add(parameter_index)
                continue
            if saw_named:
                self.session.error(f"'{name}()' positional argument follows named argument", line, col)
                continue
            if positional_index >= len(params):
                self.session.error(
                    f"'{name}()' expects at most {len(params)} argument(s) but got {len(args)}", line, col
                )
                continue
            supplied.add(positional_index)
            positional_index += 1
        for index, param in enumerate(params):
            if index not in supplied and getattr(param, "default", None) is None:
                self.session.error(f"'{name}()' missing required argument '{param.name}'", line, col)

    def _bound_arguments(self, params, names):
        parameter_names = [param.name for param in params]
        positional_index = 0
        saw_named = False
        for argument_index, argument_name in enumerate(names):
            if argument_name:
                saw_named = True
                if argument_name in parameter_names:
                    yield (parameter_names.index(argument_name), argument_index)
                continue
            if saw_named or positional_index >= len(params):
                continue
            yield (positional_index, argument_index)
            positional_index += 1

    def _validate_call_signature(
        self,
        name,
        params,
        args,
        arg_names,
        line,
        col,
        substitutions=None,
        unresolved=(),
        gpu_dispatch=False,
        declaration=None,
        bodyless_ffi=False,
    ):
        names = self._arg_names(args, arg_names)
        self._validate_call_arity(name, params, args, names, line, col)
        bound_argument_indices = {
            argument_index for _parameter_index, argument_index in self._bound_arguments(params, names)
        }
        transferred = frozenset()
        if declaration is not None:
            transferred = self.ownership.owned_transfer_param_indices(declaration)
        for param_index, arg_index in self._bound_arguments(params, names):
            if arg_index >= len(args):
                continue
            expected = params[param_index].type
            if substitutions:
                expected = self.types.substitute_type(expected, substitutions)
            if expected.base in unresolved:
                continue
            gpu_array_parameter = bool(
                gpu_dispatch
                and (canonical_expected := self.types.canonical_type(expected))
                and canonical_expected.is_array
            )
            argument = args[arg_index]
            if isinstance(argument, (BraceInitializer, ListLiteral)):
                self.aggregates.validate_array_object_initializer(
                    expected,
                    argument,
                    f"Argument '{params[param_index].name}' to '{name}()'",
                    getattr(argument, "line", line),
                    getattr(argument, "col", col),
                    is_gpu_array_result=self.gpu.is_array_result(argument),
                )
            if not gpu_array_parameter:
                expected = self.aggregates.array_parameter_initializer_type(expected, argument)
            self.ownership.validate_opaque_call_argument(
                declaration, param_index, expected, argument, name, bodyless_ffi=bodyless_ffi
            )
            self.storage.validate_volatile_reference_conversion(
                expected,
                argument,
                f"Argument '{params[param_index].name}' to '{name}()'",
                getattr(argument, "line", line),
                getattr(argument, "col", col),
            )
            argument_line = getattr(argument, "line", line)
            argument_col = getattr(argument, "col", col)
            if params[param_index].keep or param_index in transferred:
                self.validate_managed_string_source(
                    expected,
                    argument,
                    f"Argument '{params[param_index].name}' to '{name}()'",
                    argument_line,
                    argument_col,
                )
            self.contextualize_generic_constructor(expected, argument)
            self.apply_initializer_plan(
                self.aggregates.plan_aggregate_initializer(
                    expected,
                    argument,
                    f"Argument '{params[param_index].name}' to '{name}()'",
                    argument_line,
                    argument_col,
                )
            )
            if self.ownership.validate_callable_value(expected, argument, argument_line, argument_col):
                continue
            actual = self.type_of(argument)
            if actual and gpu_array_parameter:
                if not self.aggregates.array_target_has_capacity(argument, actual):
                    self.session.error(
                        f"Argument '{params[param_index].name}' to '{name}()' has no provable readable GPU buffer capacity",
                        argument_line,
                        argument_col,
                    )
                elif not self.gpu.input_has_compatible_storage(expected, actual):
                    self.session.error(
                        f"Argument '{params[param_index].name}' to '{name}()' does not have an ABI-compatible GPU buffer element type",
                        argument_line,
                        argument_col,
                    )
                continue
            compatible = actual and self.types.types_compatible(expected, actual)
            if actual and (not compatible):
                self.session.error(
                    f"Argument '{params[param_index].name}' to '{name}()' expects '{self.types.format_type(expected)}' but got '{self.types.format_type(actual)}'",
                    argument_line,
                    argument_col,
                )
        for argument_index, argument in enumerate(args):
            if argument_index in bound_argument_indices:
                continue
            self.ownership.validate_callable_value(
                None, argument, getattr(argument, "line", line), getattr(argument, "col", col)
            )

    def _validate_callable_target(self, call) -> None:
        callee = call.callee
        if isinstance(callee, LambdaExpr):
            return
        if isinstance(callee, Identifier):
            self._validate_identifier_callable(callee)
            return
        if isinstance(callee, FieldAccessExpr):
            abstract_owner = self._abstract_method_owner(callee)
            if abstract_owner is not None:
                self.session.error(
                    f"Abstract method '{abstract_owner}.{callee.field}' cannot be called without runtime dispatch",
                    call.line,
                    call.col,
                )
                return
            if self._known_field_callable(callee):
                return
            inferred = self.type_of(callee)
            if inferred is not None and self.types.function_pointer_signature(inferred) is None:
                self.session.error(
                    f"Expression of type '{self.types.format_type(inferred)}' is not callable", call.line, call.col
                )
            return
        inferred = self.type_of(callee)
        if inferred is not None and self.types.function_pointer_signature(inferred) is None:
            self.session.error(
                f"Expression of type '{self.types.format_type(inferred)}' is not callable", call.line, call.col
            )

    def _validate_identifier_callable(self, identifier) -> None:
        name = identifier.name
        symbol = self.session.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            if self.types.function_pointer_signature(symbol.type) is not None:
                return
            rendered = self.types.format_type(symbol.type) if symbol.type else "unknown"
            self.session.error(
                f"Resolved value '{name}' of type '{rendered}' is not callable", identifier.line, identifier.col
            )
            return
        if name in self.index.function_table or name in self.index.class_table:
            return
        if symbol is not None:
            return
        if name in self.index.enum_table or name in self.index.rich_enum_table:
            self.session.error(f"Type '{name}' is not directly callable", identifier.line, identifier.col)
            return
        if name in self.index.enum_member_owners:
            self.session.error(f"Enum member '{name}' is not callable", identifier.line, identifier.col)

    def _known_field_callable(self, callee) -> bool:
        if isinstance(callee.obj, Identifier):
            owner = callee.obj.name
            rich = self.index.rich_enum_table.get(owner)
            if rich and any(variant.name == callee.field for variant in rich.variants):
                return True
            cls = self.index.class_table.get(owner)
            if cls:
                method = cls.methods.get(callee.field)
                if method is not None:
                    return True
                field = cls.static_fields.get(callee.field)
                return bool(field and self.types.function_pointer_signature(field.type) is not None)
        receiver = self.type_of(callee.obj)
        if (
            receiver
            and receiver.base not in self.index.class_table
            and (receiver.base in {"Array", "List", "Map", "Set", "Vector"})
        ):
            if callee.field == "size":
                return True
        if receiver and receiver.base in self.index.class_table:
            cls = self.index.class_table[receiver.base]
            if callee.field in cls.methods:
                return True
            field = cls.fields.get(callee.field)
            if field is None and callee.field in cls.properties:
                field = cls.properties[callee.field]
            return bool(field and self.types.function_pointer_signature(field.type) is not None)
        return False

    def _abstract_method_owner(self, callee) -> str | None:
        receiver = self.type_of(callee.obj)
        if receiver is not None and receiver.base in self.index.class_table:
            cls = self.index.class_table[receiver.base]
        elif (
            isinstance(callee.obj, Identifier)
            and self.session.scope.lookup(callee.obj.name) is None
            and (callee.obj.name in self.index.class_table)
        ):
            cls = self.index.class_table[callee.obj.name]
        else:
            return None
        method = cls.methods.get(callee.field)
        return cls.name if method is not None and method.is_abstract else None

    def infer_call_type(self, expr):
        if isinstance(expr.callee, LambdaExpr):
            callable_type = self.type_of(expr.callee)
            if callable_type and callable_type.generic_args:
                return callable_type.generic_args[0]
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            symbol = self.session.scope.lookup(name)
            signature = self.types.function_pointer_signature(symbol.type if symbol else None)
            if signature is not None:
                return signature[0]
            if symbol is not None and symbol.kind != "function":
                return None
            if self.gpu.call_uses_intrinsic(expr):
                if name in WGSL_SAME_TYPE_BUILTINS and expr.args:
                    return self.type_of(expr.args[0])
                return TypeExpr(base="float")
            if self.ownership.hosted_call_uses_owned_symbol(expr):
                result = HOSTED_ABI.semantic_result(name)
                if result is not None:
                    return result
            if name in self.index.function_table:
                return self.index.function_table[name].return_type
            if name == "Mutex" and expr.args:
                argument_type = self.type_of(expr.args[0])
                return TypeExpr(base="Mutex", generic_args=[argument_type or TypeExpr(base="int")])
            if name == "Atomic" and expr.args:
                argument_type = self.type_of(expr.args[0])
                return TypeExpr(base="Atomic", generic_args=[argument_type or TypeExpr(base="int")])
            if name == "Span" and expr.args:
                argument_type = self.types.canonical_type(self.type_of(expr.args[0]))
                if argument_type is not None and argument_type.is_array:
                    element = self.types.strip_outer_storage(argument_type, array=True)
                elif argument_type is not None and argument_type.pointer_depth > 0:
                    element = self.types.strip_outer_storage(argument_type)
                else:
                    element = TypeExpr(base="int")
                return TypeExpr(base="Span", generic_args=[element])
            if name in self.index.class_table:
                return self._infer_constructor_call_type(expr, self.index.class_table[name])
            if name == "len":
                return TypeExpr(base="int")
            if name == "print":
                return TypeExpr(base="void")
            if name in C_SCALAR_CALL_RESULTS:
                return TypeExpr(base=C_SCALAR_CALL_RESULTS[name])
            if name in C_POINTER_CALL_RESULTS:
                base, depth = C_POINTER_CALL_RESULTS[name]
                return TypeExpr(base=base, pointer_depth=depth)
            hosted_result = HOSTED_ABI.semantic_result(name)
            if hosted_result is not None:
                return hosted_result
            if name in GENERIC_COMPARISON_INTRINSICS:
                return TypeExpr(base="bool")
            if name == "__btrc_hash":
                return TypeExpr(base="uint")
            if name == "gpu_id":
                return TypeExpr(base="int")
        if isinstance(expr.callee, FieldAccessExpr):
            result = self._infer_method_call_type(expr)
            if (
                expr.callee.optional
                and result is not None
                and (result.pointer_depth > 0 or result.is_array or result.base == "string")
            ):
                return replace(result, is_nullable=True)
            return result
        signature = self.types.function_pointer_signature(self.type_of(expr.callee))
        if signature is not None:
            return signature[0]
        return None

    def _infer_method_call_type(self, expr):
        callee = expr.callee
        if isinstance(callee.obj, Identifier) and callee.obj.name in self.index.rich_enum_table:
            enum_decl = self.index.rich_enum_table[callee.obj.name]
            if any(variant.name == callee.field for variant in enum_decl.variants):
                return TypeExpr(base=enum_decl.name)
        signature = self.types.function_pointer_signature(self.type_of(callee))
        if signature is not None:
            return signature[0]
        object_type = self.type_of(callee.obj)
        if (
            object_type
            and (
                object_type.base in self.types.NUMERIC_TYPES
                or object_type.base == "bool"
                or object_type.base in self.index.enum_table
                or (object_type.base in self.index.rich_enum_table)
            )
            and (object_type.pointer_depth == 0)
            and (not object_type.is_array)
            and (not object_type.generic_args)
            and (callee.field == "toString")
        ):
            return TypeExpr(base="string")
        if object_type and (
            object_type.base == "string" or (object_type.base == "char" and object_type.pointer_depth >= 1)
        ):
            return self.types.string_method_return_type(callee.field)
        if object_type and object_type.base == "Thread" and object_type.generic_args and (callee.field == "join"):
            return object_type.generic_args[0]
        if object_type and object_type.base == "Mutex" and object_type.generic_args:
            if callee.field == "get":
                return object_type.generic_args[0]
            if callee.field in ("set", "destroy"):
                return TypeExpr(base="void")
        if object_type and object_type.base == "Atomic" and object_type.generic_args:
            if callee.field in {"load", "exchange", "fetchAdd", "fetchSub", "fetchAnd", "fetchOr", "fetchXor"}:
                return object_type.generic_args[0]
            if callee.field == "compareExchangeStrong":
                return TypeExpr(base="bool")
            if callee.field in {"init", "store"}:
                return TypeExpr(base="void")
        if object_type and object_type.base == "Span" and object_type.generic_args:
            if callee.field == "length":
                return TypeExpr(base="size_t")
            if callee.field in {"isEmpty", "isValid", "tryGet", "trySet"}:
                return TypeExpr(base="bool")
        if object_type and object_type.base in {"Array", "List", "Map", "Set", "Vector"} and (callee.field == "size"):
            return TypeExpr(base="int")
        if object_type and object_type.base in self.index.class_table:
            cls = self.index.class_table[object_type.base]
            method = cls.methods.get(callee.field)
            if method is not None:
                substitutions = {}
                if cls.generic_params and object_type.generic_args:
                    substitutions.update(zip(cls.generic_params, object_type.generic_args))
                if method.generic_params:
                    inferred = self.generics.infer_method_type_args(
                        self._generic_method_plan(expr, method.params), method, substitutions
                    )
                    if inferred:
                        substitutions.update(inferred)
                if substitutions:
                    return self.types.substitute_type(method.return_type, substitutions)
                return method.return_type
        if (
            isinstance(callee.obj, Identifier)
            and self.session.scope.lookup(callee.obj.name) is None
            and (callee.obj.name in self.index.class_table)
        ):
            method = self.index.class_table[callee.obj.name].methods.get(callee.field)
            if method is not None:
                return method.return_type
        return None

    def _validate_fn_ptr_call(self, name, expected_types, args, line, col, arg_names=None):
        if any(arg_names or ()):
            self.session.error(f"'{name}()' function-pointer calls do not support named arguments", line, col)
        if len(args) != len(expected_types):
            self.session.error(f"'{name}()' expects {len(expected_types)} argument(s) but got {len(args)}", line, col)
            return
        for index, (expected, arg) in enumerate(zip(expected_types, args), 1):
            self.validate_managed_string_source(
                expected, arg, f"Argument {index} to '{name}()'", getattr(arg, "line", line), getattr(arg, "col", col)
            )
            self.ownership.validate_opaque_call_argument(None, index - 1, expected, arg, name)
            self.storage.validate_volatile_reference_conversion(
                expected, arg, f"Argument {index} to '{name}()'", getattr(arg, "line", line), getattr(arg, "col", col)
            )
            self.apply_initializer_plan(
                self.aggregates.plan_aggregate_initializer(
                    expected,
                    arg,
                    f"Argument {index} to '{name}()'",
                    getattr(arg, "line", line),
                    getattr(arg, "col", col),
                )
            )
            actual = self.type_of(arg)
            if actual and (not self.types.types_compatible(expected, actual)):
                self.session.error(
                    f"Argument {index} to '{name}()' expects '{self.types.format_type(expected)}' but got '{self.types.format_type(actual)}'",
                    getattr(arg, "line", line),
                    getattr(arg, "col", col),
                )

    def analyze_call(self, expr):
        self.gpu.validate_result_context(expr)
        raw_lifetime = self.ownership.is_raw_lifetime_call(expr)
        for index, arg in enumerate(expr.args):
            if not raw_lifetime or index != 0:
                self.aggregates.reject_thread_value_escape(arg, "passed as arguments")
        self.ownership.validate_conditional_raw_projection_call(expr)
        if (
            isinstance(expr.callee, Identifier)
            and expr.callee.name == "gpu_id"
            and (expr.callee.name not in self.index.function_table)
            and ((symbol := self.session.scope.lookup(expr.callee.name)) is None or symbol.kind == "function")
        ):
            if not self.session.in_gpu_function:
                self.session.error("gpu_id() can only be called inside @gpu functions", expr.line, expr.col)
            if expr.args:
                self.session.error("gpu_id() takes no arguments", expr.line, expr.col)
        if isinstance(expr.callee, Identifier):
            self._validate_source_macro_call(expr)
            self._validate_identifier_call(expr)
        elif isinstance(expr.callee, FieldAccessExpr):
            self._validate_method_call(expr)
        elif isinstance(expr.callee, LambdaExpr):
            self._validate_call_signature(
                "lambda", expr.callee.params, expr.args, expr.arg_names, expr.line, expr.col, declaration=expr.callee
            )
        self._validate_callable_target(expr)

    def _validate_identifier_call(self, expr):
        name = expr.callee.name
        if self.ownership.is_raw_lifetime_call(expr):
            self.ownership.validate_raw_lifetime_call(expr)
        if self.gpu.call_uses_intrinsic(expr):
            if name in self.index.function_table:
                self.session.record_hosted_call(expr)
            return
        hosted_call_validated = self._validate_hosted_abi_call(expr)
        if self.ownership.hosted_call_bypasses_source_definition(expr):
            return
        if hosted_call_validated:
            return
        symbol = self.session.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            signature = self.types.function_pointer_signature(symbol.type)
            if signature is not None:
                self._validate_fn_ptr_call(name, signature[1:], expr.args, expr.line, expr.col, expr.arg_names)
            return
        if name in self.index.function_table:
            function = self.index.function_table[name]
            self._validate_call_signature(
                function.name,
                function.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                gpu_dispatch=function.is_gpu,
                declaration=function,
                bodyless_ffi=function.body is None,
            )
            self.ownership.validate_consuming_arguments(
                function,
                self._consumption_argument_plan(function.params, expr.args, expr.arg_names),
                function.name,
            )
            return
        if name == "Mutex":
            if any(expr.arg_names or []):
                self.session.error("'Mutex()' does not accept named arguments", expr.line, expr.col)
            if len(expr.args) != 1:
                self.session.error(f"'Mutex()' expects 1 argument but got {len(expr.args)}", expr.line, expr.col)
            return
        if name in {"Atomic", "Span"}:
            self._validate_realtime_constructor(expr, name)
            return
        if name in GENERIC_INTRINSICS:
            self._validate_generic_intrinsic_call(expr)
            return
        if name in self.index.class_table:
            cls = self.index.class_table[name]
            if cls.is_abstract:
                self.session.error(f"Cannot instantiate abstract class '{cls.name}'", expr.line, expr.col)
            inferred = self._infer_constructor_call_type(expr, cls)
            if len(inferred.generic_args) == len(cls.generic_params):
                self.generics.collect_type_instances(inferred)
            substitutions = None
            if len(inferred.generic_args) == len(cls.generic_params):
                substitutions = dict(zip(cls.generic_params, inferred.generic_args))
            self.validate_constructor_args(cls, expr.args, expr.arg_names, expr.line, expr.col, substitutions)
            return

    def _validate_realtime_constructor(self, expression, name: str) -> None:
        if any(expression.arg_names or []):
            self.session.error(f"'{name}()' does not accept named arguments", expression.line, expression.col)
        if name == "Atomic":
            if len(expression.args) != 1:
                self.session.error(
                    f"'Atomic()' expects 1 argument but got {len(expression.args)}", expression.line, expression.col
                )
                return
            argument_type = self.types.canonical_type(self.type_of(expression.args[0]))
            if argument_type is not None and not self.types.is_atomic_payload(argument_type):
                self.session.error(
                    "Atomic<T> payload must be bool, int, uint, or a raw pointer",
                    expression.line,
                    expression.col,
                )
            return
        if len(expression.args) not in {1, 2}:
            self.session.error(
                f"'Span()' expects 1 or 2 arguments but got {len(expression.args)}", expression.line, expression.col
            )
            return
        source = self.types.canonical_type(self.type_of(expression.args[0]))
        if source is None or (not source.is_array and source.pointer_depth == 0):
            self.session.error("Span() backing must be a fixed array or raw pointer", expression.line, expression.col)
        if len(expression.args) == 1 and (source is None or not source.is_array):
            self.session.error("Span(pointer) requires an explicit element count", expression.line, expression.col)
        if (
            len(expression.args) == 1
            and source is not None
            and source.is_array
            and (source.array_size is None or id(source.array_size) not in self.session.constant_array_bound_ids)
        ):
            self.session.error(
                "Span(array) requires a fixed constant extent",
                expression.line,
                expression.col,
            )
        if len(expression.args) == 2:
            count_type = self.types.canonical_type(self.type_of(expression.args[1]))
            if count_type is not None and not self.types.is_integral_value(count_type):
                self.session.error("Span() element count must be integral", expression.line, expression.col)

    def _validate_method_call(self, expr):
        callee = expr.callee
        signature = self.types.function_pointer_signature(self.type_of(callee))
        if signature is not None:
            self._validate_fn_ptr_call(callee.field, signature[1:], expr.args, expr.line, expr.col, expr.arg_names)
            return
        receiver_type = self.type_of(callee.obj)
        if self._validate_builtin_method_call(expr, receiver_type):
            return
        if (
            isinstance(callee.obj, Identifier)
            and self.session.scope.lookup(callee.obj.name) is None
            and (callee.obj.name in self.index.class_table)
        ):
            cls = self.index.class_table[callee.obj.name]
            method = cls.methods.get(callee.field)
            if method is None:
                self.session.error(f"Class '{cls.name}' has no class method '{callee.field}'", expr.line, expr.col)
                return
            substitutions = self._method_substitutions(expr, cls, method, receiver_type=None)
            self._validate_call_signature(
                f"{cls.name}.{callee.field}",
                method.params,
                expr.args,
                expr.arg_names,
                expr.line,
                expr.col,
                substitutions,
                (*cls.generic_params, *method.generic_params),
                declaration=method,
            )
            self.ownership.validate_consuming_arguments(
                method,
                self._consumption_argument_plan(method.params, expr.args, expr.arg_names),
                f"{cls.name}.{callee.field}",
            )
            self._collect_method_instance(expr, cls, method, None, substitutions)
            return
        if not receiver_type or receiver_type.base not in self.index.class_table:
            return
        cls = self.index.class_table[receiver_type.base]
        method = cls.methods.get(callee.field)
        if method is None:
            return
        if method.access == "class":
            self.session.error(
                f"Class method '{callee.field}' must be called on '{cls.name}', not on an instance", expr.line, expr.col
            )
            return
        substitutions = self._method_substitutions(expr, cls, method, receiver_type)
        self._validate_call_signature(
            f"{cls.name}.{callee.field}",
            method.params,
            expr.args,
            expr.arg_names,
            expr.line,
            expr.col,
            substitutions,
            (*cls.generic_params, *method.generic_params),
            declaration=method,
        )
        self.ownership.validate_consuming_arguments(
            method,
            self._consumption_argument_plan(method.params, expr.args, expr.arg_names),
            f"{cls.name}.{callee.field}",
        )
        self._collect_method_instance(expr, cls, method, receiver_type, substitutions)

    def _method_substitutions(self, expr, cls, method, receiver_type):
        substitutions = {}
        if receiver_type and cls.generic_params and receiver_type.generic_args:
            substitutions.update(zip(cls.generic_params, receiver_type.generic_args))
        if method.generic_params:
            inferred = self.generics.infer_method_type_args(
                self._generic_method_plan(expr, method.params), method, substitutions
            )
            if inferred:
                substitutions.update(inferred)
            else:
                self.session.error(
                    f"Cannot infer consistent type arguments for generic method '{method.name}()'", expr.line, expr.col
                )
        return substitutions

    def _collect_method_instance(self, expr, cls, method, receiver_type, substitutions):
        ret = method.return_type
        if ret and ret.generic_args and substitutions:
            resolved = self.types.substitute_type(ret, substitutions)
            if resolved and resolved.generic_args:
                self.generics.collect_type_instances(resolved)
        if method.generic_params and receiver_type is not None:
            self.generics.record_method_instance(
                expr, cls, method, receiver_type, self._generic_method_plan(expr, method.params)
            )
        elif receiver_type is not None:
            self.generics.record_class_method_use(receiver_type, method.name)

    def validate_constructor_args(self, cls, args, arg_names, line, col, substitutions=None):
        if (
            cls.constructor is not None
            and cls.constructor.access == "private"
            and (self.session.current_class is None or self.session.current_class.name != cls.name)
        ):
            self.session.error(f"Cannot call private constructor of class '{cls.name}'", line, col)
        if cls.constructor is None:
            if args:
                self.session.error(
                    f"Class '{cls.name}' has no constructor but was called with {len(args)} argument(s)", line, col
                )
            return
        self._validate_call_signature(
            cls.name,
            cls.constructor.params,
            args,
            arg_names,
            line,
            col,
            substitutions,
            cls.generic_params,
            declaration=cls.constructor,
        )
        self.ownership.validate_consuming_arguments(
            cls.constructor,
            self._consumption_argument_plan(cls.constructor.params, args, arg_names),
            cls.name,
        )

    def contextualize_generic_constructor(self, expected, expression) -> bool:
        """Stamp generic constructor calls with an exact expected type."""
        if expected is None:
            return False
        if isinstance(expression, TernaryExpr):
            left = self.contextualize_generic_constructor(expected, expression.true_expr)
            right = self.contextualize_generic_constructor(expected, expression.false_expr)
            return left or right
        if not (isinstance(expression, CallExpr) and isinstance(expression.callee, Identifier)):
            return False
        if expression.callee.name in {"Atomic", "Span"} and expected.base == expression.callee.name:
            self.session.record_node_type(expression, expected)
            return True
        cls = self.index.class_table.get(expression.callee.name)
        if not (
            cls
            and cls.generic_params
            and (expected.base == cls.name)
            and (len(expected.generic_args) == len(cls.generic_params))
        ):
            return False
        self.session.record_node_type(expression, expected)
        self.generics.collect_type_instances(expected)
        if cls.constructor:
            substitutions = dict(zip(cls.generic_params, expected.generic_args))
            names = self._arg_names(expression.args, expression.arg_names)
            for param_index, arg_index in self._bound_arguments(cls.constructor.params, names):
                if arg_index >= len(expression.args):
                    continue
                argument_type = self.types.substitute_type(cls.constructor.params[param_index].type, substitutions)
                self.contextualize_generic_constructor(argument_type, expression.args[arg_index])
        return True

    def _infer_constructor_call_type(self, expression, cls):
        """Infer ``Box<T>`` from constructor arguments to ``Box(...)``."""
        if not cls.generic_params:
            return TypeExpr(base=cls.name, pointer_depth=1)
        substitutions = self._infer_constructor_type_args(expression, cls)
        if substitutions is not None:
            return TypeExpr(
                base=cls.name, generic_args=[substitutions[name] for name in cls.generic_params], pointer_depth=1
            )
        if self.session.current_class is cls:
            return self.types.current_self_type()
        return TypeExpr(base=cls.name, pointer_depth=1)

    def _infer_constructor_type_args(self, expression, cls):
        constructor = cls.constructor
        if constructor is None:
            return None
        type_params = set(cls.generic_params)
        substitutions = {}
        names = self._arg_names(expression.args, expression.arg_names)
        for param_index, arg_index in self._bound_arguments(constructor.params, names):
            if arg_index >= len(expression.args):
                continue
            declared = constructor.params[param_index].type
            actual = self.generics.argument_type_for_inference(expression.args[arg_index])
            if (
                declared is not None
                and actual is not None
                and (not self.generics.unify_type_parameter(declared, actual, type_params, substitutions))
            ):
                return None
        if any(name not in substitutions for name in cls.generic_params):
            return None
        return substitutions

    def validate_default_macro_context(self, identifier) -> None:
        """Reject macros whose expansion context cannot survive helper lifting."""
        if not self.session.analyzing_parameter_default:
            return
        if not self.index.source_macros.expands_to_any(identifier.name, _CONTEXT_SENSITIVE_PREDEFINED):
            return
        self.session.error(
            f"Source macro '{identifier.name}' cannot be used in a default argument because it expands to a context-sensitive predefined identifier",
            identifier.line,
            identifier.col,
        )

    def validate_constructor_default_member(self, identifier, *, direct_callee=False) -> bool:
        """Reject implicit instance dependencies before a constructor allocates self."""
        if not self.session.analyzing_constructor_default or self.session.current_class is None:
            return False
        name = identifier.name
        owner = self.session.current_class
        if direct_callee:
            member = owner.methods.get(name)
            if member is None:
                member = owner.properties.get(name) or owner.fields.get(name)
        else:
            member = owner.properties.get(name) or owner.fields.get(name) or owner.methods.get(name)
        if member is None or member.access == "class" or getattr(member, "is_constructor", False):
            return False
        self.session.error(
            f"Constructor defaults cannot reference instance member '{name}' before allocation",
            identifier.line,
            identifier.col,
        )
        return True

    def _validate_generic_intrinsic_call(self, expr):
        name = expr.callee.name
        expected = 1 if name == "__btrc_hash" else 2
        if len(expr.args) != expected:
            self.session.error(f"{name} expects {expected} operand(s), got {len(expr.args)}", expr.line, expr.col)
            return
        if any(expr.arg_names or []):
            self.session.error(f"{name} accepts positional operands only", expr.line, expr.col)
            return
        operand_types = [self.types.canonical_type(self.type_of(argument)) for argument in expr.args]
        if any(item is None for item in operand_types):
            self.session.error(f"cannot resolve all operand types for {name}", expr.line, expr.col)
            return
        if any(self.types.is_active_type_parameter(item) for item in operand_types):
            return
        try:
            self._validate_generic_intrinsic_types(name, operand_types)
        except OperatorTypeError as error:
            self.session.error(str(error), expr.line, expr.col)

    def _validate_generic_intrinsic_types(self, name, operand_types):
        if name in GENERIC_COMPARISON_INTRINSICS:
            self.types.comparison_domain(GENERIC_COMPARISON_INTRINSICS[name], operand_types[0], operand_types[1])
            return
        self.types.hash_domain(operand_types[0])

    def _validate_hosted_abi_call(self, call) -> bool:
        """Validate direct calls whose declaration comes from a hosted header."""
        if not self.ownership.hosted_call_uses_owned_symbol(call):
            return False
        name = call.callee.name
        self.session.record_hosted_call(call)
        if name == "assert":
            if any(call.arg_names or ()) or len(call.args) != 1:
                self.session.error("'assert()' expects exactly 1 positional argument", call.line, call.col)
            return True
        spec = HOSTED_ABI.function(name)
        if spec is None or spec.parameters is None:
            for argument in call.args:
                self.ownership.validate_callable_value(
                    None, argument, getattr(argument, "line", call.line), getattr(argument, "col", call.col)
                )
                if self.ownership.expression_is_opaque_borrow(argument):
                    self.session.error(
                        f"Argument to hosted function '{name}()' cannot forward a managed value as a raw representation because its ABI effect is not proven read-only",
                        getattr(argument, "line", call.line),
                        getattr(argument, "col", call.col),
                    )
            return self.index.function_table.get(name) is None
        if any(call.arg_names or ()):
            self.session.error(f"Hosted function '{name}()' does not accept named arguments", call.line, call.col)
            return True
        expected_count = len(spec.parameters)
        valid_arity = len(call.args) >= expected_count if spec.variadic else len(call.args) == expected_count
        if not valid_arity:
            qualifier = "at least " if spec.variadic else ""
            self.session.error(
                f"'{name}()' expects {qualifier}{expected_count} argument(s) but got {len(call.args)}",
                call.line,
                call.col,
            )
            return True
        for index, (argument, expected_shape) in enumerate(zip(call.args, spec.parameters)):
            expected = expected_shape.as_type_expr()
            self.ownership.validate_opaque_call_argument(None, index, expected, argument, name, bodyless_ffi=True)
            if self.ownership.validate_callable_value(
                expected,
                argument,
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            ):
                continue
            self.storage.validate_volatile_reference_conversion(
                expected,
                argument,
                f"Argument {index + 1} to hosted function '{name}()'",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            actual = self.type_of(argument)
            if (
                actual is not None
                and (not self._hosted_argument_type_is_deferred(expected, actual))
                and (not self.types.types_compatible(expected, actual))
            ):
                self.session.error(
                    f"Argument {index + 1} to hosted function '{name}()' expects '{self.types.format_type(expected)}' but got '{self.types.format_type(actual)}'",
                    getattr(argument, "line", call.line),
                    getattr(argument, "col", call.col),
                )
            self._validate_source_helper_consumer(call, index, argument)
        for argument in call.args[len(spec.parameters) :]:
            self.ownership.validate_callable_value(
                None, argument, getattr(argument, "line", call.line), getattr(argument, "col", call.col)
            )
        return True

    def _hosted_argument_type_is_deferred(self, expected, actual) -> bool:
        canonical = self.types.canonical_type(actual)
        if canonical is None:
            return True
        if canonical.base in self.storage.active_type_parameters():
            return True
        return bool(
            expected.base == "void"
            and expected.pointer_depth == 1
            and (canonical.base == "string" or canonical.pointer_depth > 0 or canonical.is_array)
        )

    def _validate_source_helper_consumer(self, call, index, argument) -> None:
        name = call.callee.name
        if not HOSTED_ABI.source_helper_adopts_raw_string(name, index):
            return
        if self.ownership.raw_lifetime_uses_static_string(argument):
            self.session.error(
                f"{name}() cannot adopt static string storage; pass fresh raw heap storage",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        managed = self.ownership.opaque_managed_origin_type(argument)
        if managed is not None:
            self.session.error(
                f"{name}() cannot adopt an already-managed value of type '{self.types.format_type(managed)}'; pass fresh raw heap storage",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        producer = argument
        while isinstance(producer, CastExpr):
            producer = producer.expr
        if not isinstance(producer, CallExpr) or not isinstance(producer.callee, Identifier):
            return
        if not self.ownership.hosted_call_uses_owned_symbol(producer):
            return
        producer_name = producer.callee.name
        alias_is_null = HOSTED_ABI.alias_argument_is_provably_null(producer_name, producer.args)
        effect = HOSTED_ABI.return_effect(producer_name, alias_argument_is_null=alias_is_null)
        deallocator = HOSTED_ABI.return_deallocator(producer_name, alias_argument_is_null=alias_is_null)
        if effect == RETURN_FRESH and deallocator == DEALLOC_FREE:
            return
        self.session.error(
            f"{name}() cannot adopt storage returned by {producer_name}() because it is not proven fresh free-compatible allocation",
            getattr(argument, "line", call.line),
            getattr(argument, "col", call.col),
        )

    def _direct_hosted_return_contract(self, expression) -> tuple[str, str | None] | None:
        if not isinstance(expression, CallExpr) or not isinstance(expression.callee, Identifier):
            return None
        if not self.ownership.hosted_call_uses_owned_symbol(expression):
            return None
        name = expression.callee.name
        spec = HOSTED_ABI.function(name)
        if spec is None:
            return None
        alias_is_null = HOSTED_ABI.alias_argument_is_provably_null(name, expression.args)
        return (
            HOSTED_ABI.return_effect(name, alias_argument_is_null=alias_is_null),
            HOSTED_ABI.return_deallocator(name, alias_argument_is_null=alias_is_null),
        )

    def validate_managed_string_source(self, expected, value, subject, line=0, col=0) -> None:
        target = self.types.canonical_type(expected)
        actual = self.types.canonical_type(self.type_of(value))
        if self.types.requires_string_conversion(target, actual):
            self.generics.record_class_method_use(actual, "toString")
        if not self._managed_string_target(target) or not self._raw_c_string(actual):
            return
        contract = self._direct_hosted_return_contract(value)
        if contract is not None and (
            contract[0] in {RETURN_ALIAS, RETURN_INDEPENDENT}
            or (contract[0] == RETURN_FRESH and contract[1] == DEALLOC_FREE)
        ):
            return
        self.session.error(
            f"{subject} cannot implicitly convert raw 'char*' storage to managed 'string' because its ownership is not proven; transfer fresh storage with __btrc_str_track() or make an explicit copy",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )

    @staticmethod
    def _managed_string_target(type_expr) -> bool:
        return bool(
            type_expr and type_expr.base == "string" and (type_expr.pointer_depth == 0) and (not type_expr.is_array)
        )

    @staticmethod
    def _raw_c_string(type_expr) -> bool:
        return bool(
            type_expr and type_expr.base == "char" and (type_expr.pointer_depth == 1) and (not type_expr.is_array)
        )


__all__ = ["CallAnalyzer"]
