"""Statement traversal, assignments, updates, and declarations."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.expressions import ExpressionValuePlan
from src.compiler.python.analyzer.program import (
    STRING_CONSTANT_NODES,
    ClassCallableIdentity,
    DeclarationIndex,
    LambdaBodyFacts,
    SymbolInfo,
)
from src.compiler.python.analyzer.types import NONESCAPING_RICH_ENUM_REASON
from src.compiler.python.frontend.native_imports import NativeHeaderSource
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    Block,
    BraceInitializer,
    BreakStmt,
    CallExpr,
    Capture,
    CastExpr,
    CForStmt,
    ClassDecl,
    CommaExpr,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    EnumDecl,
    ExprStmt,
    FieldAccessExpr,
    FieldDecl,
    FloatLiteral,
    ForInitExpr,
    ForInitVar,
    ForInStmt,
    FStringLiteral,
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    InterfaceDecl,
    KeepStmt,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    NullLiteral,
    ParallelForStmt,
    PropertyDecl,
    ReleaseStmt,
    ReturnStmt,
    RichEnumDecl,
    SelfExpr,
    StructDecl,
    SwitchStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TypedefDecl,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

if TYPE_CHECKING:
    from src.compiler.python.analyzer.aggregates import AggregateAnalyzer
    from src.compiler.python.analyzer.declarations import DeclarationRegistry
    from src.compiler.python.analyzer.expressions import ExpressionAnalyzer
    from src.compiler.python.analyzer.flow import ControlFlowAnalyzer
    from src.compiler.python.analyzer.generated_symbols import GeneratedSymbolRegistry
    from src.compiler.python.analyzer.generics import GenericAnalyzer
    from src.compiler.python.analyzer.gpu import GpuAnalyzer
    from src.compiler.python.analyzer.ownership import OwnershipAnalyzer
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.storage import StorageModel
    from src.compiler.python.analyzer.types import TypeSystem


_C11_INT_MIN = -(2**31)
_C11_INT_MAX = 2**31 - 1


class StatementAnalyzer:
    """Statement traversal, assignments, updates, and declarations."""

    def __init__(
        self,
        session: AnalysisSession,
        declarations: DeclarationRegistry,
        index: DeclarationIndex,
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
        storage: StorageModel,
        ownership: OwnershipAnalyzer,
        expressions: ExpressionAnalyzer,
        flow: ControlFlowAnalyzer,
        gpu: GpuAnalyzer,
        generics: GenericAnalyzer,
        generated_symbols: GeneratedSymbolRegistry,
    ) -> None:
        self.session = session
        self.declarations = declarations
        self.index = index
        self.aggregates = aggregates
        self.expressions = expressions
        self.flow = flow
        self.generated_symbols = generated_symbols
        self.generics = generics
        self.gpu = gpu
        self.ownership = ownership
        self.storage = storage
        self.types = types

    def _inferred_array_binding_type(self, inferred, initializer):
        """Represent `var alias = arrayValue` as a pointer-valued binding."""
        if isinstance(initializer, BraceInitializer):
            self.session.error(
                "Cannot infer array storage for 'var' from a brace initializer; use an explicit array declaration",
                initializer.line,
                initializer.col,
            )
        inferred = self.aggregates.array_value_type(inferred)
        canonical = self.types.canonical_type(inferred)
        if canonical is None or not canonical.is_array or isinstance(initializer, (BraceInitializer, ListLiteral)):
            return inferred
        if self.gpu.is_array_result(initializer):
            return canonical
        return self.types.add_outer_pointer(canonical, clear_array=True)

    def _validate_enum_declaration(self, declaration) -> None:
        owner = declaration.name or ""
        prior = set()
        previous = -1
        for value in declaration.values:
            if value.value is not None:
                valid, numeric = self.expressions.integer_constant_expression(
                    value.value, enum_owner=owner, allowed_enum_members=prior
                )
                if not valid:
                    self.session.error(
                        f"Enum value '{value.name}' requires an integral constant expression using only earlier members",
                        value.line,
                        value.col,
                    )
                    numeric = None
                elif numeric is not None and (not _C11_INT_MIN <= numeric <= _C11_INT_MAX):
                    self.session.error(
                        f"Enum value '{value.name}' is outside the strict-C11 int range", value.line, value.col
                    )
                    numeric = None
            else:
                numeric = previous + 1 if previous is not None else None
                if numeric is not None and (not _C11_INT_MIN <= numeric <= _C11_INT_MAX):
                    self.session.error(
                        f"Implicit enum value '{value.name}' is outside the strict-C11 int range", value.line, value.col
                    )
                    numeric = None
            self.index.enum_constant_values[owner, value.name] = numeric
            previous = numeric
            prior.add(value.name)

    def _is_static_storage_initializer(self, expression, expected=None) -> bool:
        if expected is not None and self.types.requires_string_conversion(
            expected, self.aggregates.type_of(expression)
        ):
            return False
        if isinstance(expression, BraceInitializer):
            return all(self._is_static_storage_initializer(item) for item in expression.elements)
        if isinstance(expression, ListLiteral):
            return bool(expected and expected.is_array) and all(
                self._is_static_storage_initializer(item) for item in expression.elements
            )
        return self._static_initializer_category(expression) is not None

    def _static_initializer_category(self, expression):
        """Return ``integer``, ``arithmetic``, or ``address`` when valid."""
        valid, _ = self.expressions.integer_constant_expression(expression)
        if valid:
            return "integer"
        if isinstance(expression, FloatLiteral):
            return "arithmetic"
        if isinstance(expression, STRING_CONSTANT_NODES):
            return "address"
        if isinstance(expression, NullLiteral):
            return "address"
        if isinstance(expression, Identifier):
            if not self._names_file_scope(expression.name):
                return None
            if expression.name in self.index.function_table:
                return "address"
            symbol = self.session.global_scope.symbols.get(expression.name)
            if symbol and symbol.type and symbol.type.is_array:
                return "address"
            return None
        if isinstance(expression, UnaryExpr):
            if expression.op == "&" and self._is_static_address_operand(expression.operand):
                return "address"
            if expression.op in {"+", "-"}:
                category = self._static_initializer_category(expression.operand)
                if category == "arithmetic":
                    return category
            return None
        if isinstance(expression, BinaryExpr):
            return self._static_binary_category(expression)
        if isinstance(expression, TernaryExpr):
            return self._static_ternary_category(expression)
        if isinstance(expression, CastExpr):
            return self._static_cast_category(expression)
        return None

    def _static_binary_category(self, expression):
        left = self._static_initializer_category(expression.left)
        right = self._static_initializer_category(expression.right)
        if expression.op == "+" and {left, right} == {"address", "integer"}:
            return "address"
        if expression.op == "-" and left == "address" and (right == "integer"):
            return "address"
        if left in {"integer", "arithmetic"} and right in {"integer", "arithmetic"}:
            if expression.op in {"+", "-", "*", "/", "<", ">", "<=", ">=", "==", "!="}:
                if expression.op == "/" and self.expressions.is_known_numeric_zero(expression.right):
                    return None
                return "integer" if expression.op in {"<", ">", "<=", ">=", "==", "!="} else "arithmetic"
        return None

    def _static_ternary_category(self, expression):
        condition_valid, condition = self.expressions.integer_constant_expression(expression.condition)
        if not condition_valid:
            return None
        if condition is not None:
            selected = expression.true_expr if condition else expression.false_expr
            return self._static_initializer_category(selected)
        true_category = self._static_initializer_category(expression.true_expr)
        false_category = self._static_initializer_category(expression.false_expr)
        return true_category if true_category == false_category else None

    def _static_cast_category(self, expression):
        operand = self._static_initializer_category(expression.expr)
        target = self.types.canonical_type(expression.target_type)
        if target is None or operand is None:
            return None
        if self.types.is_pointer_value(target):
            return "address" if operand in {"integer", "address"} else None
        if self.types.is_numeric_value(target):
            if operand not in {"integer", "arithmetic"}:
                return None
            return "integer" if self.types.is_integral_value(target) else "arithmetic"
        return None

    def _names_file_scope(self, name: str) -> bool:
        """Whether ``name`` resolves past every local scope to file scope.

        A local, parameter or other block binding that shadows a global or
        function has automatic storage, so it is never a C address constant.
        """
        symbol = self.session.scope.lookup(name)
        return symbol is None or symbol is self.session.global_scope.symbols.get(name)

    def _is_static_address_operand(self, expression) -> bool:
        if isinstance(expression, Identifier):
            if not self._names_file_scope(expression.name):
                return False
            declaration = self.index.global_declarations.get(expression.name)
            origin = getattr(declaration, "source_file", None)
            if (
                isinstance(origin, NativeHeaderSource)
                and origin.language == "objective-c"
                and declaration.initializer is None
            ):
                return False
            return bool(
                expression.name in self.index.function_table or expression.name in self.session.global_scope.symbols
            )
        if isinstance(expression, FieldAccessExpr):
            if expression.arrow:
                return False
            if isinstance(expression.obj, Identifier):
                owner = self.index.class_table.get(expression.obj.name)
                if owner and expression.field in owner.static_fields:
                    return True
            return self._is_static_address_operand(expression.obj)
        if isinstance(expression, IndexExpr):
            valid_index, _ = self.expressions.integer_constant_expression(expression.index)
            return valid_index and self._is_static_array_designator(expression.obj)
        return isinstance(expression, STRING_CONSTANT_NODES)

    def _is_static_array_designator(self, expression) -> bool:
        if isinstance(expression, STRING_CONSTANT_NODES):
            return True
        if isinstance(expression, Identifier):
            symbol = self.session.global_scope.symbols.get(expression.name)
            return bool(symbol and symbol.type and symbol.type.is_array and self._names_file_scope(expression.name))
        if isinstance(expression, FieldAccessExpr) and (not expression.arrow):
            field_type = self.aggregates.type_of(expression)
            return bool(field_type and field_type.is_array and self._is_static_address_operand(expression))
        return False

    def _validate_ownership_operand(self, statement):
        expression = statement.expr
        operand_type = self.types.canonical_type(self.aggregates.type_of(expression))
        if isinstance(expression, SelfExpr) and (not isinstance(statement, KeepStmt)):
            self.session.error(
                "Managed method receiver 'self' is borrowed and cannot be consumed", statement.line, statement.col
            )
            return
        if not self.expressions.is_lvalue(expression):
            self.session.error("Ownership operation requires an assignable value", statement.line, statement.col)
            return
        if isinstance(statement, DeleteStmt):
            operation = "delete"
        elif isinstance(statement, KeepStmt):
            operation = "keep"
        else:
            operation = "release"
        indirect = self.storage.is_virtual_projection(expression)
        if indirect:
            self.session.error(
                f"{operation} cannot target a property or protocol index; store it in a direct lvalue first",
                statement.line,
                statement.col,
            )
            return
        if not self.expressions.is_lifetime_stable_storage(expression):
            self.session.error(
                f"{operation} requires storage rooted in a stable owner; bind temporary owners to a local first",
                statement.line,
                statement.col,
            )
            return
        if not isinstance(statement, KeepStmt) and (
            not self.expressions.validate_mutable_target(expression, statement.line, statement.col)
        ):
            return
        self.ownership.validate_managed_parameter_consumption(statement, expression, operand_type)
        if operand_type and operand_type.base == "Thread":
            self.session.error(
                f"{operation} is not valid for type '{self.types.format_type(operand_type)}'",
                statement.line,
                statement.col,
            )
            return
        if (
            isinstance(statement, DeleteStmt)
            and operand_type
            and (not operand_type.is_array)
            and (operand_type.pointer_depth > 0)
            and (operand_type.base not in {"__fn_ptr", "__realtime_fn_ptr"})
        ):
            return
        if operand_type and operand_type.base not in self.index.class_table and (not operand_type.generic_args):
            type_params = set(
                (self.session.current_class.generic_params if self.session.current_class else [])
                + (self.session.current_method.generic_params if self.session.current_method else [])
            )
            if operand_type.base in type_params:
                return
            self.session.error(
                f"Ownership operation is not valid for '{self.types.format_type(operand_type)}'",
                statement.line,
                statement.col,
            )

    def validate_nonescaping_variable(self, declaration, *, is_global) -> None:
        """Refuse a variable that would let a borrowing rich enum outlive its owners.

        A declared type is checked before its initializer, as btrcc checks it,
        and an inferred one after; each site reports once.
        """
        canonical = self.types.canonical_type(declaration.type)
        if canonical is None:
            return
        subject = f"Global '{declaration.name}'" if is_global else f"Variable '{declaration.name}'"
        self.types.validate_nonescaping_rich_enum_role(
            canonical,
            subject,
            "object",
            declaration.type.line or declaration.line,
            declaration.type.col or declaration.col,
        )
        rich_enum = self.types.nonescaping_rich_enum(canonical)
        if rich_enum is None or canonical.pointer_depth != 0 or canonical.is_array:
            return
        if is_global or canonical.is_static or canonical.is_extern:
            message = f"{subject} cannot store nonescaping rich enum '{rich_enum}'; {NONESCAPING_RICH_ENUM_REASON}"
        elif declaration.initializer is None:
            message = f"{subject} must initialize its nonescaping rich enum '{rich_enum}' borrow"
        else:
            return
        self.types.report_type_shape_error(message, None, declaration.line, declaration.col)

    def _validate_variable_storage(self, declaration, *, is_global) -> None:
        type_expr = declaration.type
        if type_expr is None:
            return
        subject = f"Global '{declaration.name}'" if is_global else f"Variable '{declaration.name}'"
        self.types.validate_declared_type(
            type_expr,
            subject,
            declaration.line,
            declaration.col,
            role="object",
            active_type_params=self.storage.active_type_parameters(),
        )
        canonical = self.types.canonical_type(type_expr)
        if canonical and canonical.base == "Span" and canonical.pointer_depth == 0:
            if is_global or canonical.is_static or canonical.is_extern:
                self.session.error(f"{subject} cannot store nonescaping Span<T>", declaration.line, declaration.col)
            if not is_global and declaration.initializer is None:
                self.session.error(f"{subject} must initialize its Span<T> borrow", declaration.line, declaration.col)
        self.validate_nonescaping_variable(declaration, is_global=is_global)
        if canonical and canonical.base == "Atomic" and canonical.pointer_depth == 0:
            initializer = declaration.initializer
            valid_constructor = bool(
                isinstance(initializer, CallExpr)
                and isinstance(initializer.callee, Identifier)
                and initializer.callee.name == "Atomic"
            )
            if initializer is not None and not valid_constructor:
                self.session.error(
                    f"{subject} cannot copy an Atomic<T> owner; initialize with Atomic(value)",
                    declaration.line,
                    declaration.col,
                )
        if canonical and canonical.base == "Mutex" and (is_global or canonical.is_static or canonical.is_extern):
            self.session.error(
                f"{subject} cannot own a Mutex handle with static storage until managed global teardown is supported",
                declaration.line,
                declaration.col,
            )
        if (
            not is_global
            and type_expr.is_static
            and (canonical is not None)
            and (
                canonical.base == "string"
                or canonical.base in self.index.class_table
                or canonical.base in self.storage.active_type_parameters()
            )
        ):
            self.session.error(
                f"{subject} cannot use managed static-local storage; declare an owned lexical value or explicit global owner",
                declaration.line,
                declaration.col,
            )
        contains_thread = self.types.contains_thread_storage(type_expr)
        outer = (
            self.session.scope.parent.lookup(declaration.name) if not is_global and self.session.scope.parent else None
        )
        if contains_thread and outer is not None:
            self.session.error(
                f"Thread owner '{declaration.name}' cannot shadow another active binding",
                declaration.line,
                declaration.col,
            )
        if contains_thread and (is_global or bool(canonical and (canonical.is_static or canonical.is_extern))):
            self.session.error(
                f"{subject} cannot own a Thread handle with static storage; Thread<T> must be an initialized local owner",
                declaration.line,
                declaration.col,
            )
        elif contains_thread and (canonical is None or canonical.base != "Thread"):
            self.session.error(
                f"{subject} cannot embed a Thread handle; Thread<T> must be the variable's direct type",
                declaration.line,
                declaration.col,
            )
        elif (
            canonical and canonical.base == "Thread" and (declaration.initializer is None) and (not canonical.is_extern)
        ):
            self.session.error(f"{subject} must initialize its Thread<T> owner", declaration.line, declaration.col)
        if not (type_expr.is_extern and declaration.initializer is None):
            self.aggregates.validate_complete_aggregate_use(type_expr, subject, declaration.line, declaration.col)
        bound_context = "global" if is_global else "static" if type_expr.is_static else "local"
        self._validate_array_bound(type_expr, subject, bound_context)
        if type_expr.is_extern and declaration.initializer is not None:
            self.session.error(
                f"{subject} cannot have an initializer with extern storage", declaration.line, declaration.col
            )
        if (
            type_expr.is_array
            and type_expr.array_size is None
            and (declaration.initializer is None)
            and (not type_expr.is_extern)
        ):
            self.session.error(f"{subject} requires an array bound or initializer", declaration.line, declaration.col)
        initializer_list = isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
        if (
            type_expr.is_array
            and type_expr.array_size is None
            and initializer_list
            and (not declaration.initializer.elements)
        ):
            self.session.error(
                f"{subject} cannot infer an array bound from an empty initializer", declaration.line, declaration.col
            )
        if (
            type_expr.is_array
            and type_expr.array_size is not None
            and (declaration.initializer is not None)
            and (not self.gpu.is_array_result(declaration.initializer))
        ):
            constant_bound, _ = self.expressions.integer_constant_expression(type_expr.array_size)
            if not constant_bound:
                self.session.error(
                    f"{subject} is a variable-length array and cannot have an initializer",
                    declaration.line,
                    declaration.col,
                )
        has_static_storage = is_global or type_expr.is_static
        if (
            has_static_storage
            and declaration.initializer is not None
            and (not type_expr.is_extern)
            and (not self._is_static_storage_initializer(declaration.initializer, type_expr))
        ):
            self.session.error(
                f"{subject} requires a C constant/address initializer for static storage",
                declaration.line,
                declaration.col,
            )

    def _validate_char_array_initializer(self, type_expr, initializer, *, is_global: bool) -> None:
        """A local bound is analyzed after its initializer, so evaluate it here.

        Storage validation owns a static-storage initializer that is not a
        literal and a non-positive bound, and reports them first.
        """
        if not self.aggregates.char_array_string_initializer(type_expr, initializer):
            return
        if (is_global or type_expr.is_static) and not isinstance(initializer, STRING_CONSTANT_NODES):
            return
        bound = self.types.canonical_type(type_expr).array_size
        value = None
        if bound is not None:
            constant, numeric = self.expressions.integer_constant_expression(bound)
            value = numeric if constant else None
        self.aggregates.validate_char_array_initializer(type_expr, initializer, value)

    def _validate_array_bound(self, type_expr, subject, context) -> None:
        if type_expr is None:
            return
        for argument in type_expr.generic_args or []:
            self._validate_array_bound(argument, subject, context)
        bound = type_expr.array_size
        if not type_expr.is_array or bound is None:
            return
        marker = id(bound)
        # Declaration bounds are validated before bodies, so every body sees
        # which are constant; a later visit of the same bound adds nothing.
        if not self.session.mark_array_bound(bound):
            return
        self.analyze_expression(bound)
        bound_type = self.storage.type_of(bound)
        if bound_type is not None and (not self.types.is_integral_value(bound_type)):
            self.session.error(
                f"Array bound for {subject} must be integral",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )
        constant, numeric = self.expressions.integer_constant_expression(bound)
        if constant:
            self.session.constant_array_bound_ids.add(marker)
            if numeric is not None:
                self.session.record_array_bound_value(bound, numeric)
        if numeric is not None and numeric <= 0:
            self.session.error(
                f"Array bound for {subject} must be positive",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )
        if context in {"field", "global", "static"} and (not constant):
            self.session.error(
                f"Array bound for {subject} must be a constant expression",
                getattr(bound, "line", type_expr.line),
                getattr(bound, "col", type_expr.col),
            )

    def _validate_class_field_contract(self, class_decl, field) -> None:
        subject = f"Field '{class_decl.name}.{field.name}'"
        if field.access == "class" and class_decl.generic_params:
            self.session.error(f"Static {subject.lower()} is not supported on a generic class", field.line, field.col)
        context = "static" if field.access == "class" else "field"
        self._validate_array_bound(field.type, subject, context)
        canonical = self.types.canonical_type(field.type)
        if canonical and canonical.is_array and (canonical.array_size is not None):
            element = self.types.strip_outer_storage(canonical, array=True)
            potentially_managed = element.base in set(class_decl.generic_params)
            if self.ownership.is_managed_result_type(element) or potentially_managed:
                self.session.error(
                    f"{subject} cannot contain managed elements without elementwise ownership support",
                    field.line,
                    field.col,
                )
        if (
            field.access != "class"
            and field.initializer is not None
            and (canonical is not None)
            and canonical.is_array
            and isinstance(field.initializer, (BraceInitializer, ListLiteral))
        ):
            self.session.error(
                f"{subject} has only temporary compound-literal backing; array-valued class field defaults require persistent backing storage",
                field.line,
                field.col,
            )
        if (
            field.access != "class"
            and isinstance(field.initializer, (*STRING_CONSTANT_NODES, FStringLiteral))
            and self.aggregates.char_array_string_initializer(field.type, field.initializer)
        ):
            # An instance field is initialized by assignment after allocation,
            # which a C array cannot take.
            self.session.error(
                "A class field char array cannot take a string literal default; copy the text into it in the constructor",
                field.initializer.line,
                field.initializer.col,
            )
        if field.access == "class" and canonical and (canonical.base == "Mutex"):
            self.session.error(
                f"Static {subject.lower()} cannot own a Mutex handle until managed global teardown is supported",
                field.line,
                field.col,
            )
        if (
            field.access != "class"
            and field.initializer is not None
            and canonical
            and canonical.is_const
            and (not self.types.is_pointer_value(canonical))
        ):
            self.session.error(
                f"{subject} cannot initialize a scalar const class field after allocation", field.line, field.col
            )
        if (
            field.access == "class"
            and field.initializer is not None
            and (not self._is_static_storage_initializer(field.initializer, field.type))
        ):
            self.session.error(
                f"Static {subject.lower()} requires a C constant/address initializer", field.line, field.col
            )

    def _validate_property_storage(self, class_decl, prop) -> None:
        subject = f"Property '{class_decl.name}.{prop.name}'"
        if prop.access == "class":
            self.session.error(
                f"Static property '{class_decl.name}.{prop.name}' is unsupported; use a static field plus static methods",
                prop.line,
                prop.col,
            )
        canonical = self.types.canonical_type(prop.type)
        if canonical and canonical.is_array and (canonical.array_size is not None):
            self.session.error(
                f"{subject} cannot use fixed-size array storage; use an instance field plus accessors",
                prop.line,
                prop.col,
            )
        if prop.has_setter and canonical and canonical.is_const and (not self.types.is_pointer_value(canonical)):
            self.session.error(f"{subject} cannot have a setter for scalar const storage", prop.line, prop.col)
        self._validate_array_bound(prop.type, subject, "field")

    def _validate_parameter_bounds(self, params, owner) -> None:
        """Validate parameter VLAs with earlier parameters in lexical scope."""
        with self.session.scope_frame():
            for parameter in params:
                self._validate_array_bound(parameter.type, f"parameter '{owner}.{parameter.name}'", "parameter")
                self.session.scope.define(
                    parameter.name,
                    self.session.local_symbol(
                        parameter.name,
                        parameter.type,
                        "param",
                        parameter.name_line or parameter.line,
                        parameter.name_col or parameter.col,
                    ),
                )

    def analyze_expression(self, expression) -> None:
        """Prepare statement-owned body/flow facts, then enter expression recursion."""
        if expression is None:
            return
        facts = self.session.nonnull_paths
        self._prepare_expression(expression, facts)
        self.expressions.analyze(expression)
        self._check_nullable_stores(expression, facts)
        self._apply_expression_flow_effects(expression)

    _STORE_WARNING = "Possibly-null value stored in non-nullable {context} of type '{type}' — check for null first"

    def _check_nullable_stores(self, expression, facts) -> None:
        """Warn where an assignment or an argument stores a value that may be null into a non-nullable reference.

        Facts refine exactly as they do for nullable accesses: the right operand of
        ``&&`` and ``||`` and the arms of ``?:`` see what their condition proves.
        """
        if expression is None or not dataclasses.is_dataclass(expression) or isinstance(expression, LambdaExpr):
            return
        if isinstance(expression, AssignExpr) and expression.op == "=":
            self.check_nullable_store(
                self.expressions.infer_type(expression.target), expression.value, "assignment target", facts
            )
        elif isinstance(expression, CallExpr):
            for index, parameter_type, callee in self._store_parameters(expression):
                self.check_nullable_store(
                    parameter_type, expression.args[index], f"argument {index + 1} of '{callee}'", facts
                )
        if isinstance(expression, BinaryExpr) and expression.op in {"&&", "||"}:
            self._check_nullable_stores(expression.left, facts)
            outcome = self.flow.nonnull_facts_for_outcome(expression.left, expression.op == "&&")
            self._check_nullable_stores(expression.right, frozenset(set(facts) | outcome))
            return
        if isinstance(expression, TernaryExpr):
            self._check_nullable_stores(expression.condition, facts)
            true_facts = frozenset(set(facts) | self.flow.nonnull_facts_for_outcome(expression.condition, True))
            false_facts = frozenset(set(facts) | self.flow.nonnull_facts_for_outcome(expression.condition, False))
            self._check_nullable_stores(expression.true_expr, true_facts)
            self._check_nullable_stores(expression.false_expr, false_facts)
            return
        for field in dataclasses.fields(expression):
            child = getattr(expression, field.name, None)
            if isinstance(child, (list, tuple)):
                for item in child:
                    self._check_nullable_stores(item, facts)
            else:
                self._check_nullable_stores(child, facts)

    def check_nullable_store(self, target_type, value, context: str, facts=None) -> None:
        """Warn when a value that may be null is stored into a non-nullable reference."""
        if value is None or not self._nonnull_reference(target_type):
            return
        if not self._may_be_null(value, self.session.nonnull_paths if facts is None else facts):
            return
        self.session.warning(
            self._STORE_WARNING.format(context=context, type=target_type.base),
            getattr(value, "line", 0),
            getattr(value, "col", 0),
        )

    def _nonnull_reference(self, type_expr) -> bool:
        """A source reference that may not hold null: a class, interface or string, not declared nullable."""
        return (
            type_expr is not None
            and not type_expr.is_nullable
            and not type_expr.is_array
            and type_expr.pointer_depth <= 1
            and (
                type_expr.base == "string"
                or type_expr.base in self.index.class_table
                or type_expr.base in self.index.interface_table
            )
        )

    def _may_be_null(self, value, facts) -> bool:
        if self.session.flow_unreachable:
            return False
        if self.flow.is_null_literal(value):
            return True
        if isinstance(value, BinaryExpr) and value.op == "??":
            return self._may_be_null(value.right, facts)
        if isinstance(value, BinaryExpr) and value.op == "+" and self._concatenation(value):
            # A concatenation is null only when one of its operands may be.
            return self._may_be_null(value.left, facts) or self._may_be_null(value.right, facts)
        if isinstance(value, TernaryExpr):
            true_facts = set(facts) | self.flow.nonnull_facts_for_outcome(value.condition, True)
            false_facts = set(facts) | self.flow.nonnull_facts_for_outcome(value.condition, False)
            return self._may_be_null(value.true_expr, true_facts) or self._may_be_null(value.false_expr, false_facts)
        path = self.flow.access_path(value)
        if path is not None and path in facts:
            return False
        value_type = self.expressions.infer_type(value)
        return value_type is not None and value_type.is_nullable

    def _concatenation(self, value) -> bool:
        value_type = self.expressions.infer_type(value)
        return value_type is not None and value_type.base == "string" and value_type.pointer_depth <= 1

    def _store_parameters(self, call) -> list[tuple[int, TypeExpr, str]]:
        """The positional arguments of a call to a source callable, with the parameter type each is stored into.

        Calls resolve by name (a top-level function with a body, or a
        non-generic class's constructor), as a static ``C.m()``, or through the
        receiver's type to a class, interface or generic-instance method, whose
        class type parameters take the instance's arguments. A parameter typed
        by a method's own type parameter has no known target.
        """
        callee = call.callee
        parameters = None
        substitutions: dict[str, TypeExpr] = {}
        method_parameters: set[str] = set()
        if isinstance(callee, Identifier):
            if self.flow.is_local_binding(callee.name):
                return []
            function = self.index.function_table.get(callee.name)
            info = self.index.class_table.get(callee.name)
            if function is not None and function.body is not None:
                parameters = function.params
            elif info is not None and not info.generic_params and info.constructor is not None:
                parameters = info.constructor.params
        elif isinstance(callee, FieldAccessExpr) and not callee.optional:
            method = None
            receiver = callee.obj
            static_owner = (
                self.index.class_table.get(receiver.name)
                if isinstance(receiver, Identifier) and not self.flow.is_local_binding(receiver.name)
                else None
            )
            if static_owner is not None:
                candidate = static_owner.methods.get(callee.field)
                method = candidate if candidate is not None and candidate.access == "class" else None
            else:
                receiver_type = self.expressions.infer_type(receiver)
                info = self.index.class_table.get(receiver_type.base) if receiver_type is not None else None
                if receiver_type is None or receiver_type.is_array:
                    method = None
                elif info is not None and not info.generic_params:
                    candidate = info.methods.get(callee.field)
                    method = candidate if candidate is not None and candidate.access != "class" else None
                elif info is not None and len(receiver_type.generic_args) == len(info.generic_params):
                    candidate = info.methods.get(callee.field)
                    method = candidate if candidate is not None and candidate.access != "class" else None
                    substitutions = dict(zip(info.generic_params, receiver_type.generic_args, strict=True))
                elif receiver_type.base in self.index.interface_table:
                    method = self.index.interface_table[receiver_type.base].methods.get(callee.field)
            if method is not None:
                parameters = method.params
                method_parameters = set(getattr(method, "generic_params", ()) or ())
        if parameters is None:
            return []
        stores = []
        names = call.arg_names or []
        for index in range(min(len(call.args), len(parameters))):
            if index < len(names) and names[index]:
                continue
            declared = parameters[index].type
            if declared is None or declared.base in method_parameters:
                continue
            if declared.base in substitutions:
                argument = substitutions[declared.base]
                declared = dataclasses.replace(argument, is_nullable=argument.is_nullable or declared.is_nullable)
            stores.append((index, declared, callee.name if isinstance(callee, Identifier) else callee.field))
        return stores

    def _prepare_expression(self, expression, facts) -> None:
        if expression is None or not dataclasses.is_dataclass(expression):
            return
        if isinstance(expression, LambdaExpr):
            if id(expression) not in self.session.lambda_body_facts:
                self._analyze_lambda(expression)
            return
        if isinstance(expression, FieldAccessExpr):
            path = self.flow.access_path(expression.obj)
            if self.session.flow_unreachable or (path is not None and path in facts):
                self.session.known_nonnull_expression_ids.add(id(expression.obj))
        if isinstance(expression, BinaryExpr) and expression.op in {"&&", "||"}:
            self._prepare_expression(expression.left, facts)
            outcome = expression.op == "&&"
            right_facts = frozenset(set(facts) | self.flow.nonnull_facts_for_outcome(expression.left, outcome))
            self.session.expression_flow_seeds[id(expression.right)] = right_facts
            self._prepare_expression(expression.right, right_facts)
            return
        if isinstance(expression, TernaryExpr):
            self._prepare_expression(expression.condition, facts)
            true_facts = frozenset(set(facts) | self.flow.nonnull_facts_for_outcome(expression.condition, True))
            false_facts = frozenset(set(facts) | self.flow.nonnull_facts_for_outcome(expression.condition, False))
            self.session.expression_flow_seeds[id(expression.true_expr)] = true_facts
            self.session.expression_flow_seeds[id(expression.false_expr)] = false_facts
            self._prepare_expression(expression.true_expr, true_facts)
            self._prepare_expression(expression.false_expr, false_facts)
            return
        for field in dataclasses.fields(expression):
            child = getattr(expression, field.name, None)
            if isinstance(child, (list, tuple)):
                for item in child:
                    self._prepare_expression(item, facts)
            else:
                self._prepare_expression(child, facts)

    def _apply_expression_flow_effects(self, expression) -> None:
        if isinstance(expression, CommaExpr):
            # A for-header comma list: each operand's effects, in order.
            for element in expression.elements:
                self._apply_expression_flow_effects(element)
        elif isinstance(expression, UnaryExpr) and expression.op == "&":
            self.flow.record_nullable_address_escape(expression.operand)
        elif isinstance(expression, AssignExpr):
            stores_nonnull = (
                expression.op == "="
                and self._is_nullable_binding(self.expressions.infer_type(expression.target))
                and self._stores_nonnull(expression.value)
            )
            # A call or store inside the value runs before the store lands.
            self.flow.invalidate_nonnull_effects(expression.value)
            self.flow.invalidate_nonnull_target(expression.target)
            if stores_nonnull:
                self.flow.record_nonnull_target(expression.target)
        elif isinstance(expression, CallExpr):
            self.flow.invalidate_nonnull_call(expression)
        else:
            self.flow.invalidate_nonnull_effects(expression)

    @staticmethod
    def _is_nullable_binding(binding_type) -> bool:
        """Only a nullable binding's accesses are checked, so only it needs a non-null fact."""
        return binding_type is not None and binding_type.is_nullable

    def _stores_nonnull(self, expression) -> bool:
        """Whether a stored value cannot be null: a path the flow proved, or a non-nullable reference."""
        if expression is None or self.flow.is_null_literal(expression):
            return False
        if self.flow.is_known_nonnull(expression):
            return True
        if isinstance(expression, TernaryExpr):
            return self._stores_nonnull(expression.true_expr) and self._stores_nonnull(expression.false_expr)
        if isinstance(expression, (ListLiteral, MapLiteral, BraceInitializer)):
            return True
        if isinstance(expression, FieldAccessExpr) and getattr(expression, "optional", False):
            return False
        value_type = self.expressions.infer_type(expression)
        if value_type is None or value_type.is_nullable:
            return False
        if value_type.pointer_depth == 0:
            return True
        # A raw C pointer may be NULL without being declared nullable; a
        # source reference (one level of class, interface, string or generic
        # instance) may not.
        return value_type.pointer_depth == 1 and (
            value_type.base == "string"
            or bool(value_type.generic_args)
            or value_type.base in self.index.class_table
            or value_type.base in self.index.interface_table
        )

    def _analyze_lambda(self, expr):
        """Analyze a lambda expression."""
        prev_return_type = self.session.current_return_type
        with self.session.nonnull_frame((), reachable=True):
            self._analyze_lambda_in_flow(expr)
        self.session.current_return_type = prev_return_type

    def _analyze_lambda_in_flow(self, expr) -> None:
        outer_symbols = {}
        scope = self.session.scope
        while scope is not None and scope is not self.session.global_scope:
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
        with self.session.lambda_capture_frame(outer_symbols, captures), self.session.scope_frame():
            self._analyze_lambda_body(expr)
        environment_captures = [name for name in captures if outer_symbols[name].captures_environment]
        if environment_captures:
            names = ", ".join(environment_captures)
            self.session.error(
                f"A lambda cannot capture an environment-bearing callable ({names}); a closure value is required",
                expr.line,
                expr.col,
            )
        thread_captures = [
            name for name, capture_type in captures.items() if self.types.contains_thread_storage(capture_type)
        ]
        for name in thread_captures:
            self.session.error(
                f"A lambda cannot capture Thread handle '{name}'; join it before capture or create a fresh owner inside the lambda",
                expr.line,
                expr.col,
            )
        for name, capture_type in captures.items():
            canonical_capture = self.types.canonical_type(capture_type)
            if canonical_capture is not None and canonical_capture.base == "Span":
                self.session.error(
                    f"A lambda cannot capture nonescaping Span '{name}'",
                    expr.line,
                    expr.col,
                )
            if self.types.nonescaping_rich_enum(canonical_capture) is not None:
                self.session.error(
                    f"A lambda cannot capture nonescaping rich enum '{name}'",
                    expr.line,
                    expr.col,
                )
            if (
                canonical_capture is not None
                and canonical_capture.base == "Atomic"
                and canonical_capture.pointer_depth == 0
            ):
                self.session.error(
                    f"A lambda cannot copy Atomic owner '{name}'; capture an Atomic<T>*",
                    expr.line,
                    expr.col,
                )
        expr.captures = [Capture(name=name, type=captures[name]) for name in sorted(captures)]
        self.session.lambda_body_facts[id(expr)] = LambdaBodyFacts(
            terminates=bool(isinstance(expr.body, LambdaBlock) and self.flow.block_must_terminate(expr.body.body))
        )

    def _analyze_lambda_body(self, expr) -> None:
        self.declarations.validate_parameter_names(expr.params, "lambda")
        declared_params = set()
        active_type_params = self.storage.active_type_parameters()
        for param in expr.params:
            param.type = self.types.upgrade_class_type(param.type)
            self.types.validate_declared_type(
                param.type,
                f"Lambda parameter '{param.name}'",
                param.line,
                param.col,
                role="parameter",
                active_type_params=active_type_params,
            )
            self._validate_array_bound(param.type, f"lambda parameter '{param.name}'", "parameter")
            if param.default is not None:
                self.session.error("Lambda parameters cannot have default arguments", param.line, param.col)
            self.generics.collect_type_instances(param.type)
            if param.name not in declared_params and self._claim_local_binding(
                param.name,
                "lambda parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                self.session.scope.define(
                    param.name,
                    dataclasses.replace(self._param_symbol(param), kind="lambda_param", owned_storage=False),
                )
                declared_params.add(param.name)
        if expr.return_type:
            expr.return_type = self.types.upgrade_class_type(expr.return_type)
            self.types.validate_declared_type(
                expr.return_type,
                "Lambda return type",
                expr.line,
                expr.col,
                role="return",
                active_type_params=active_type_params,
            )
            self.generics.collect_type_instances(expr.return_type)
            self.session.current_return_type = self.aggregates.array_value_type(expr.return_type)
        else:
            self.session.current_return_type = None
        if isinstance(expr.body, LambdaBlock):
            self._analyze_root_block(expr.body.body)
            if (
                expr.return_type
                and (not self.types.is_nonpointer_void_object(expr.return_type))
                and (not self.flow.block_must_terminate(expr.body.body))
            ):
                self.session.error("Non-void lambda does not return a value on every path", expr.line, expr.col)
        elif isinstance(expr.body, LambdaExprBody):
            self.analyze_expression(expr.body.expression)
            if expr.return_type is not None:
                self.storage.validate_volatile_reference_conversion(
                    expr.return_type, expr.body.expression, "Lambda return value", expr.line, expr.col
                )
        if expr.return_type is None:
            inferred, conflicts = self.expressions.infer_lambda_return_details(expr)
            for actual in conflicts:
                self.session.error(
                    f"Lambda has inconsistent inferred return types '{self.types.format_type(inferred)}' and '{self.types.format_type(actual)}'",
                    expr.line,
                    expr.col,
                )
            self.types.validate_nonescaping_rich_enum_role(inferred, "Lambda return type", "return", expr.line, expr.col)

    def _analyze_switch(self, stmt):
        self.analyze_expression(stmt.value)
        before_cases = set(self.session.nonnull_paths)
        case_flows = []
        self.session.break_depth += 1
        has_default = False
        for case in stmt.cases:
            if case.value:
                self.analyze_expression(case.value)
            else:
                has_default = True
            with self._flow_branch(()):
                self._analyze_switch_case(case)
                case_flows.append(self.session.nonnull_flow)
        self.session.break_depth -= 1
        self._validate_switch_contract(stmt)
        # A case that never completes reaches nothing after the switch.
        joined = self.flow.join_nonnull_flows(case_flows)
        self.session.replace_nonnull_paths(before_cases if joined is None else before_cases & joined)
        if not has_default:
            val_type = self.expressions.infer_type(stmt.value)
            if val_type and val_type.base in self.index.enum_table:
                enum_values = set(self.index.enum_table[val_type.base])
                covered = set()
                for case in stmt.cases:
                    if case.value:
                        if isinstance(case.value, Identifier):
                            covered.add(case.value.name)
                        elif isinstance(case.value, FieldAccessExpr):
                            covered.add(case.value.field)
                missing = enum_values - covered
                if missing:
                    names = ", ".join(sorted(missing))
                    self.session.error(
                        f"Switch on enum '{val_type.base}' is not exhaustive, missing: {names}",
                        getattr(stmt, "line", 0),
                        getattr(stmt, "col", 0),
                    )

    def _analyze_switch_case(self, case):
        with self.session.scope_frame():
            self._analyze_statements(case.body)

    def _analyze_parallel_for(self, stmt):
        if self.flow.is_range_call(stmt.iterable):
            for argument in stmt.iterable.args:
                self.analyze_expression(argument)
                self.aggregates.reject_thread_value_escape(argument, "passed as range arguments")
            elem_type = TypeExpr(base="int")
        else:
            self.analyze_expression(stmt.iterable)
            iter_type = self.expressions.infer_type(stmt.iterable)
            elem_type = self.types.element_type(iter_type, stmt.line, stmt.col)
            class_info = self.index.class_table.get(iter_type.base) if iter_type else None
            if class_info and "iterLen" in class_info.methods and "iterGet" in class_info.methods:
                self.generics.record_class_method_use(iter_type, "iterLen")
                self.generics.record_class_method_use(iter_type, "iterGet")
        if self.types.contains_thread_storage(elem_type):
            self.session.error("parallel-for variables cannot own a Thread handle", stmt.line, stmt.col)
        self.session.loop_depth += 1
        self.session.break_depth += 1
        with self.session.scope_frame():
            if elem_type:
                if self._claim_local_binding(stmt.var_name, "parallel variable", stmt.line, stmt.col):
                    self.session.scope.define(
                        stmt.var_name,
                        self.session.local_symbol(stmt.var_name, elem_type, "parallel", stmt.line, stmt.col),
                    )
            self._analyze_nullable_loop_body(stmt.body)
        self.session.loop_depth -= 1
        self.session.break_depth -= 1

    def _analyze_c_for(self, stmt):
        with self.session.scope_frame():
            self._analyze_c_for_scoped(stmt)

    def _analyze_c_for_scoped(self, stmt) -> None:
        if stmt.init:
            if isinstance(stmt.init, ForInitVar):
                for declaration in stmt.init.declarations:
                    self._analyze_var_decl(declaration)
                    if declaration.type and (declaration.type.is_static or declaration.type.is_extern):
                        self.session.error(
                            "C-style for initializer cannot use static or extern storage",
                            declaration.line,
                            declaration.col,
                        )
                    if declaration.type and declaration.type.is_array:
                        self.session.error(
                            "C-style for initializer cannot declare an array", declaration.line, declaration.col
                        )
            elif isinstance(stmt.init, ForInitExpr):
                self.analyze_expression(stmt.init.expression)
                self.aggregates.reject_thread_observation(stmt.init.expression)
        before_iteration = set(self.session.nonnull_paths)
        self.session.replace_nonnull_paths(
            self.flow.facts_surviving_loop(before_iteration, stmt.body, stmt.update, stmt.condition)
        )
        if stmt.condition:
            self.analyze_expression(stmt.condition)
            self.aggregates.reject_thread_observation(stmt.condition)
        self.session.loop_depth += 1
        self.session.break_depth += 1
        body_facts = self.flow.nonnull_facts_for_outcome(stmt.condition, True) if stmt.condition is not None else set()
        with self._flow_branch(body_facts):
            self._analyze_c_for_iteration(stmt)
            iteration_flow = self.session.nonnull_flow
        self.session.replace_nonnull_paths(
            before_iteration if iteration_flow is None else before_iteration & iteration_flow
        )
        self.session.loop_depth -= 1
        self.session.break_depth -= 1

    def _analyze_c_for_iteration(self, statement) -> None:
        self._analyze_block(statement.body)
        if statement.update:
            self.analyze_expression(statement.update)
            self.aggregates.reject_thread_observation(statement.update)

    def _analyze_for_in(self, stmt):
        if self.flow.is_range_call(stmt.iterable):
            for arg in stmt.iterable.args:
                self.analyze_expression(arg)
                self.aggregates.reject_thread_value_escape(arg, "passed as range arguments")
            self.session.loop_depth += 1
            self.session.break_depth += 1
            elem_type = TypeExpr(base="int")
            with self.session.scope_frame():
                if self._claim_local_binding(stmt.var_name, "loop variable", stmt.line, stmt.col):
                    self.session.scope.define(
                        stmt.var_name,
                        self.session.local_symbol(stmt.var_name, elem_type, "loop", stmt.line, stmt.col),
                    )
                self._analyze_nullable_loop_body(stmt.body)
            self.session.loop_depth -= 1
            self.session.break_depth -= 1
            return
        self.analyze_expression(stmt.iterable)
        self.session.loop_depth += 1
        self.session.break_depth += 1
        iter_type = self.expressions.infer_type(stmt.iterable)
        self.generics.collect_type_instances(iter_type)
        if iter_type and iter_type.is_array:
            if self.aggregates.array_target_has_capacity(stmt.iterable, iter_type):
                self.session.array_iteration_capacity_ids.add(id(stmt.iterable))
            else:
                self.session.error("Array for-in iterable has no provable element capacity", stmt.line, stmt.col)
        elem_type = self.types.element_type(iter_type, stmt.line, stmt.col)
        value_type = None
        if stmt.var_name2:
            value_type = self.types.iterable_value_type(iter_type, stmt.line, stmt.col)
        if self.types.contains_thread_storage(elem_type) or self.types.contains_thread_storage(value_type):
            self.session.error(
                "for-in loop variables cannot own a Thread handle; declare a fresh local owner inside the loop",
                stmt.line,
                stmt.col,
            )
        class_info = self.index.class_table.get(iter_type.base) if iter_type else None
        owned_first = bool(class_info and "iterLen" in class_info.methods and ("iterGet" in class_info.methods))
        owned_second = bool(owned_first and "iterValueAt" in class_info.methods)
        if owned_first:
            self.generics.record_class_method_use(iter_type, "iterLen")
            self.generics.record_class_method_use(iter_type, "iterGet")
        if stmt.var_name2 and owned_second:
            self.generics.record_class_method_use(iter_type, "iterValueAt")
        with self.session.scope_frame():
            if elem_type and self._claim_local_binding(stmt.var_name, "loop variable", stmt.line, stmt.col):
                self.session.scope.define(
                    stmt.var_name,
                    self.session.local_symbol(
                        stmt.var_name, elem_type, "loop", stmt.line, stmt.col, owned_storage=owned_first
                    ),
                )
            if (
                stmt.var_name2
                and value_type
                and self._claim_local_binding(stmt.var_name2, "loop variable", stmt.line, stmt.col)
            ):
                self.session.scope.define(
                    stmt.var_name2,
                    self.session.local_symbol(
                        stmt.var_name2, value_type, "loop", stmt.line, stmt.col, owned_storage=owned_second
                    ),
                )
            self._analyze_nullable_loop_body(stmt.body)
        self.session.loop_depth -= 1
        self.session.break_depth -= 1

    def _analyze_nullable_if(self, statement) -> None:
        self.analyze_expression(statement.condition)
        self.aggregates.reject_thread_observation(statement.condition)
        # A branch that never completes (it returns, throws, exits, breaks or
        # continues) contributes no facts to the code after the statement.
        continuing_flows = []
        with self._flow_branch(self.flow.nonnull_facts_for_outcome(statement.condition, True)):
            self._analyze_block(statement.then_block)
            then_flow = self.session.nonnull_flow
        if not self.flow.block_stops_fallthrough(statement.then_block):
            continuing_flows.append(then_flow)
        if isinstance(statement.else_block, ElseIf):
            with self._flow_branch(self.flow.nonnull_facts_for_outcome(statement.condition, False)):
                self._analyze_stmt(statement.else_block.if_stmt)
                else_flow = self.session.nonnull_flow
            if not self.flow.statement_stops_fallthrough(statement.else_block.if_stmt):
                continuing_flows.append(else_flow)
        elif isinstance(statement.else_block, ElseBlock):
            with self._flow_branch(self.flow.nonnull_facts_for_outcome(statement.condition, False)):
                self._analyze_block(statement.else_block.body)
                else_flow = self.session.nonnull_flow
            if not self.flow.block_stops_fallthrough(statement.else_block.body):
                continuing_flows.append(else_flow)
        else:
            entry = self.session.nonnull_flow
            continuing_flows.append(
                None if entry is None else entry | self.flow.nonnull_facts_for_outcome(statement.condition, False)
            )
        self.session.replace_nonnull_flow(self.flow.join_nonnull_flows(continuing_flows))

    def _analyze_nullable_while(self, statement) -> None:
        entry = set(self.session.nonnull_paths)
        self.session.replace_nonnull_paths(self.flow.facts_surviving_loop(entry, statement.body, statement.condition))
        self.analyze_expression(statement.condition)
        self.aggregates.reject_thread_observation(statement.condition)
        self.session.loop_depth += 1
        self.session.break_depth += 1
        self._analyze_nullable_loop_body(
            statement.body, self.flow.nonnull_facts_for_outcome(statement.condition, True), entry=entry
        )
        self.session.loop_depth -= 1
        self.session.break_depth -= 1

    def _analyze_nullable_loop_body(self, body, facts=(), *, back_edge=(), entry=None) -> None:
        """Analyze a loop body once from facts that hold on every iteration.

        ``back_edge`` names what runs between iterations besides the body (a
        do-while condition). ``entry`` is the flow before the loop when its
        head was already narrowed (a while condition).
        """
        before_body = set(self.session.nonnull_paths) if entry is None else set(entry)
        self.session.replace_nonnull_paths(
            self.flow.facts_surviving_loop(set(self.session.nonnull_paths), body, *back_edge)
        )
        with self._flow_branch(facts):
            self._analyze_block(body)
            body_flow = self.session.nonnull_flow
        self.session.replace_nonnull_paths(before_body if body_flow is None else before_body & body_flow)

    @contextmanager
    def _flow_branch(self, facts) -> Iterator[None]:
        initial = set(self.session.nonnull_paths) | set(facts)
        with self.session.nonnull_frame(initial):
            yield

    def _validate_switch_contract(self, statement) -> None:
        subject_type = self.expressions.infer_type(statement.value)
        if subject_type is not None and (not self.types.is_integral_value(subject_type)):
            self.session.error(
                f"Switch subject must be integral, got '{self.types.format_type(subject_type)}'",
                statement.line,
                statement.col,
            )
        default_count = 0
        constants: dict[int, object] = {}
        for case in statement.cases:
            if case.value is None:
                default_count += 1
                continue
            case_type = self.expressions.infer_type(case.value)
            if case_type is not None and (not self.types.is_integral_value(case_type)):
                self.session.error(
                    f"Switch case must be integral, got '{self.types.format_type(case_type)}'",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
            valid, numeric = self.expressions.integer_constant_expression(case.value)
            if not valid:
                self.session.error(
                    "Switch case requires an integral constant expression",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
                continue
            if numeric is None:
                continue
            if numeric in constants:
                self.session.error(
                    f"Duplicate switch case value {numeric}",
                    getattr(case.value, "line", statement.line),
                    getattr(case.value, "col", statement.col),
                )
            else:
                constants[numeric] = case
        if default_count > 1:
            self.session.error("Switch cannot contain more than one default case", statement.line, statement.col)

    def _claim_local_binding(self, name, kind, line=0, col=0, *, c_name_generated=False) -> bool:
        self.declarations.validate_name(name, kind.capitalize(), line, col, c_name_generated=c_name_generated)
        existing = self.session.scope.symbols.get(name)
        # A capture entry only records that this lambda scope read the
        # enclosing binding; a local declared after that read shadows it.
        if existing is None or existing.kind in {"function", "capture"}:
            outer = self.session.scope.parent.lookup(name) if self.session.scope.parent else None
            if outer is not None and self.types.contains_thread_storage(outer.type):
                self.session.error(f"Binding '{name}' cannot shadow an active Thread owner", line, col)
                return False
            return True
        self.session.error(f"Duplicate {kind} name '{name}' in the same scope", line, col)
        return False

    def validate_declarations(self, program) -> None:
        declarations = list(self.session.declarations(program))
        for declaration in declarations:
            if isinstance(declaration, EnumDecl):
                self._validate_enum_declaration(declaration)
        for declaration in declarations:
            if isinstance(declaration, FunctionDecl):
                self._validate_function_signature_types(declaration)
            elif isinstance(declaration, ClassDecl):
                self._validate_class_declaration_types(declaration)
            elif isinstance(declaration, InterfaceDecl):
                self._validate_interface_declaration_types(declaration)
            elif isinstance(declaration, StructDecl) and (not declaration.is_forward):
                for field in self.types.record_fields(declaration):
                    self.types.validate_declared_type(
                        field.type,
                        f"Struct field '{declaration.name}.{field.name}'",
                        field.line,
                        field.col,
                        role="field",
                    )
                    self._validate_array_bound(field.type, f"struct field '{declaration.name}.{field.name}'", "field")
            elif isinstance(declaration, RichEnumDecl):
                for variant in declaration.variants:
                    for parameter in variant.params:
                        self.types.validate_declared_type(
                            parameter.type,
                            f"Rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                            parameter.line,
                            parameter.col,
                            role="field",
                        )
                        if self.storage.effective_outer_const(parameter.type, self.index.typedef_table):
                            self.session.error(
                                f"Rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}' cannot use const storage until rich-enum constructors use structured initialization",
                                parameter.line,
                                parameter.col,
                            )
                        self._validate_array_bound(
                            parameter.type,
                            f"rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                            "field",
                        )
            elif isinstance(declaration, TypedefDecl):
                self.types.validate_declared_type(
                    declaration.original,
                    f"Typedef '{declaration.alias}'",
                    declaration.line,
                    declaration.col,
                    role="alias",
                )
                self._validate_array_bound(declaration.original, f"typedef '{declaration.alias}'", "global")
            elif isinstance(declaration, VarDeclStmt) and declaration.type is not None:
                self._validate_array_bound(declaration.type, f"Global '{declaration.name}'", "global")

    def _validate_function_signature_types(self, function) -> None:
        self.declarations.validate_hosted_function(function)
        self._reject_bodyless_realtime_function_signature(
            function,
            f"Native function declaration '{function.name}'",
        )
        self.types.validate_declared_type(
            function.return_type,
            f"Return type of function '{function.name}'",
            function.line,
            function.col,
            role="return",
        )
        for parameter in function.params:
            self.types.validate_declared_type(
                parameter.type,
                f"Parameter '{function.name}.{parameter.name}'",
                parameter.line,
                parameter.col,
                role="parameter",
            )
        self._validate_array_bound(function.return_type, f"return type of function '{function.name}'", "local")
        self._validate_parameter_bounds(function.params, function.name)
        self.declarations.validate_main_signature(function)

    def _validate_class_declaration_types(self, declaration) -> None:
        class_parameters = set(declaration.generic_params)
        for member in declaration.members:
            if isinstance(member, FieldDecl):
                self.types.validate_declared_type(
                    member.type,
                    f"Field '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="stable_field",
                    active_type_params=class_parameters,
                )
                self._validate_class_field_contract(declaration, member)
            elif isinstance(member, PropertyDecl):
                self.types.validate_declared_type(
                    member.type,
                    f"Property '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="field",
                    active_type_params=class_parameters,
                )
                self._validate_property_storage(declaration, member)
            elif isinstance(member, MethodDecl):
                self._reject_bodyless_realtime_function_signature(
                    member,
                    f"Bodyless method '{declaration.name}.{member.name}'",
                )
                active = class_parameters | set(member.generic_params)
                declared_return_type = self._declared_callable_return_type(declaration, member)
                self.types.validate_declared_type(
                    declared_return_type,
                    f"Return type of method '{declaration.name}.{member.name}'",
                    member.line,
                    member.col,
                    role="return",
                    active_type_params=active,
                )
                for parameter in member.params:
                    self.types.validate_declared_type(
                        parameter.type,
                        f"Parameter '{declaration.name}.{member.name}.{parameter.name}'",
                        parameter.line,
                        parameter.col,
                        role="parameter",
                        active_type_params=active,
                    )
                self._validate_array_bound(
                    member.return_type, f"return type of method '{declaration.name}.{member.name}'", "local"
                )
                self._validate_parameter_bounds(member.params, f"{declaration.name}.{member.name}")
                self.declarations.validate_class_shape(declaration, member)

    @staticmethod
    def _declared_callable_return_type(declaration: ClassDecl, member: MethodDecl) -> TypeExpr:
        if not member.is_constructor or member.return_type.generic_args or not declaration.generic_params:
            return member.return_type
        owner_arguments = [TypeExpr(base=name) for name in declaration.generic_params]
        return dataclasses.replace(member.return_type, generic_args=owner_arguments)

    def _validate_interface_declaration_types(self, declaration) -> None:
        active = set(declaration.generic_params)
        for method in declaration.methods:
            self._reject_bodyless_realtime_function_signature(
                method,
                f"Interface method '{declaration.name}.{method.name}'",
            )
            self.types.validate_declared_type(
                method.return_type,
                f"Return type of interface method '{declaration.name}.{method.name}'",
                method.line,
                method.col,
                role="return",
                active_type_params=active,
            )
            for parameter in method.params:
                self.types.validate_declared_type(
                    parameter.type,
                    f"Parameter '{declaration.name}.{method.name}.{parameter.name}'",
                    parameter.line,
                    parameter.col,
                    role="parameter",
                    active_type_params=active,
                )
            self._validate_array_bound(
                method.return_type, f"return type of interface method '{declaration.name}.{method.name}'", "local"
            )
            self._validate_parameter_bounds(method.params, f"{declaration.name}.{method.name}")

    def _reject_bodyless_realtime_function_signature(self, callable_, label: str) -> None:
        if getattr(callable_, "body", None) is not None:
            return
        origin = getattr(callable_, "source_file", None)
        if (
            isinstance(origin, NativeHeaderSource)
            and origin.call_contract is not None
            and any(getattr(callback, "realtime", None) is not None for callback in origin.call_contract.callbacks)
        ):
            return
        if self.types.contains_realtime_function_storage(callable_.return_type) or any(
            self.types.contains_realtime_function_storage(parameter.type) for parameter in callable_.params
        ):
            self.session.error(
                f"{label} cannot expose RealtimeFunction; downgrade to CFunction at the boundary",
                callable_.line,
                callable_.col,
            )

    def _param_symbol(self, param) -> SymbolInfo:
        """Build a parameter symbol using its represented runtime value."""
        value_type = (
            param.type
            if self.session.in_gpu_function and param.type.is_array
            else self.aggregates.array_parameter_value_type(param.type)
        )
        return self.session.local_symbol(
            param.name, value_type, "param", param.name_line or param.line, param.name_col or param.col
        )

    def analyze_declaration(self, decl):
        # Each declaration's bodies start reachable and know no non-null facts.
        with self.session.nonnull_frame((), reachable=True):
            self._analyze_declaration_body(decl)

    def _analyze_declaration_body(self, decl):
        if isinstance(decl, ClassDecl):
            self._analyze_class(decl)
        elif isinstance(decl, FunctionDecl):
            self._analyze_function(decl)
        elif isinstance(decl, VarDeclStmt):
            self._analyze_var_decl(decl)
        elif isinstance(decl, (EnumDecl, RichEnumDecl)):
            return

    def _analyze_class(self, decl):
        prev_class = self.session.current_class
        prev_class_callable = self.session.current_class_callable
        self.session.current_class = self.index.class_table[decl.name]
        self.session.current_class_callable = None
        for member in decl.members:
            if isinstance(member, FieldDecl):
                member.type = self.types.upgrade_class_type(member.type)
                self.generics.collect_type_instances(member.type)
                if member.initializer:
                    field_value_type = self.aggregates.array_field_value_type(member)
                    if member.access == "class":
                        self.aggregates.validate_pointer_backed_array_field_initializer(
                            member, member.initializer, f"Field '{decl.name}.{member.name}'", member.line, member.col
                        )
                    self.analyze_expression(member.initializer)
                    self.check_nullable_store(member.type, member.initializer, f"field '{decl.name}.{member.name}'")
                    self.expressions.validate_value(
                        ExpressionValuePlan(
                            field_value_type,
                            member.initializer,
                            f"Field '{decl.name}.{member.name}'",
                            member.line,
                            member.col,
                            callable_storage=True,
                        )
                    )
                    self.expressions.apply_initializer_plan(
                        self.aggregates.plan_typed_initializer(
                            field_value_type,
                            member.initializer,
                            f"Field '{decl.name}.{member.name}'",
                            member.line,
                            member.col,
                        )
                    )
            elif isinstance(member, MethodDecl):
                self._analyze_method(member)
            elif isinstance(member, PropertyDecl):
                self._analyze_property(member)
        self.session.current_class = prev_class
        self.session.current_class_callable = prev_class_callable

    def _analyze_method(self, method):
        prev_method = self.session.current_method
        prev_class_callable = self.session.current_class_callable
        prev_callable = self.session.current_callable
        self.session.current_method = method
        owner = self.session.current_class.name if self.session.current_class is not None else ""
        self.session.current_class_callable = (
            None
            if method.is_constructor or method.name == "__del__"
            else ClassCallableIdentity.method(owner, method.name)
        )
        self.session.current_callable = method
        prev_gpu = self.session.in_gpu_function
        self.session.in_gpu_function = method.is_gpu
        prev_return_type = self.session.current_return_type
        if method.is_gpu:
            self.session.error(
                "@gpu is only supported on top-level functions; methods have no WGSL dispatch lowering",
                method.line,
                method.col,
            )
        for param in method.params:
            param.type = self.types.upgrade_class_type(param.type)
        is_constructor = method.is_constructor
        self.session.current_return_type = TypeExpr(base="void") if is_constructor else method.return_type
        if not is_constructor:
            method.return_type = self.types.upgrade_class_type(method.return_type)
            self.declarations.validate_array_return(
                method, self.session.current_class.name if self.session.current_class else None
            )
            self.session.current_return_type = self.aggregates.array_value_type(method.return_type)
        with self.session.scope_frame(), self.session.nonnull_frame((), reachable=True):
            self._analyze_method_body(method, is_constructor)
        self.session.current_method = prev_method
        self.session.current_class_callable = prev_class_callable
        self.session.current_callable = prev_callable
        self.session.in_gpu_function = prev_gpu
        self.session.current_return_type = prev_return_type

    def _analyze_method_body(self, method, is_constructor: bool) -> None:
        self.declarations.validate_default_parameters(method.params, method.line, method.col)
        if method.access != "class":
            self_type = self.types.current_self_type()
            self.session.scope.define("self", SymbolInfo("self", self_type, "param"))
        for param in method.params:
            self.generics.collect_type_instances(param.type)
            if param.default is not None:
                parameter_value_type = self.aggregates.array_parameter_value_type(param.type)
                self.aggregates.validate_array_parameter_default(
                    param.type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or method.line,
                    param.col or method.col,
                )
                with self.session.default_analysis(constructor=is_constructor):
                    self.analyze_expression(param.default)
                self.check_nullable_store(param.type, param.default, f"parameter '{param.name}'")
                self.expressions.validate_value(
                    ExpressionValuePlan(
                        parameter_value_type,
                        param.default,
                        f"Default for parameter '{param.name}'",
                        param.line or method.line,
                        param.col or method.col,
                        callable_storage=True,
                    )
                )
                self.expressions.apply_initializer_plan(
                    self.aggregates.plan_typed_initializer(
                        parameter_value_type,
                        param.default,
                        f"Default for parameter '{param.name}'",
                        param.line or method.line,
                        param.col or method.col,
                    )
                )
            if self._claim_local_binding(
                param.name,
                "parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                self.session.scope.define(param.name, self._param_symbol(param))
        if not is_constructor:
            self.generics.collect_type_instances(method.return_type)
        self._analyze_root_block(method.body)
        if (
            not is_constructor
            and method.return_type
            and (not self.types.is_nonpointer_void_object(method.return_type))
            and method.body
            and (not self.flow.block_must_terminate(method.body))
        ):
            class_name = self.session.current_class.name if self.session.current_class else ""
            self.session.error(
                f"Method '{class_name}.{method.name}' has non-void return type but no return statement",
                method.line,
                method.col,
            )

    def _analyze_property(self, prop):
        """Analyze a C#-style property declaration."""
        self.generics.collect_type_instances(prop.type)
        prop.type = self.types.upgrade_class_type(prop.type)
        prev_method = self.session.current_method
        prev_class_callable = self.session.current_class_callable
        prev_return_type = self.session.current_return_type
        owner = self.session.current_class.name if self.session.current_class is not None else ""
        if prop.getter_body:
            self.session.current_class_callable = ClassCallableIdentity.getter(owner, prop.name)
            self.session.current_method = MethodDecl(
                access=prop.access,
                return_type=prop.type,
                name=f"_prop_get_{prop.name}",
            )
            self.session.current_return_type = self.aggregates.array_value_type(prop.type)
            with self.session.scope_frame(), self.session.nonnull_frame((), reachable=True):
                self_type = self.types.current_self_type()
                self.session.scope.define("self", SymbolInfo("self", self_type, "param"))
                self._analyze_root_block(prop.getter_body)
                if not self.flow.block_must_terminate(prop.getter_body):
                    self.session.error(
                        f"Property getter '{self.session.current_class.name}.{prop.name}' does not return a value on every path",
                        prop.line,
                        prop.col,
                    )
        if prop.setter_body:
            self.session.current_class_callable = ClassCallableIdentity.setter(owner, prop.name)
            self.session.current_method = MethodDecl(
                access=prop.access,
                return_type=TypeExpr(base="void"),
                name=f"_prop_set_{prop.name}",
            )
            self.session.current_return_type = TypeExpr(base="void")
            previous_virtual_setter = self.session.in_virtual_setter
            self.session.in_virtual_setter = True
            with self.session.scope_frame(), self.session.nonnull_frame((), reachable=True):
                self_type = self.types.current_self_type()
                self.session.scope.define("self", SymbolInfo("self", self_type, "param"))
                self.session.scope.define(
                    "value", SymbolInfo("value", self.aggregates.array_parameter_value_type(prop.type), "param")
                )
                self._analyze_root_block(prop.setter_body)
            self.session.in_virtual_setter = previous_virtual_setter
        self.session.current_method = prev_method
        self.session.current_class_callable = prev_class_callable
        self.session.current_return_type = prev_return_type

    def _analyze_function(self, func):
        prev_callable = self.session.current_callable
        self.session.current_callable = func
        prev_gpu = self.session.in_gpu_function
        self.session.in_gpu_function = func.is_gpu
        prev_return_type = self.session.current_return_type
        self.session.current_return_type = func.return_type
        for param in func.params:
            param.type = self.types.upgrade_class_type(param.type)
        func.return_type = self.types.upgrade_class_type(func.return_type)
        self.declarations.validate_array_return(func)
        self.session.current_return_type = self.aggregates.array_value_type(func.return_type)
        with self.session.scope_frame(), self.session.nonnull_frame((), reachable=True):
            self._analyze_function_body(func)
        self.session.current_callable = prev_callable
        self.session.in_gpu_function = prev_gpu
        self.session.current_return_type = prev_return_type

    def _analyze_function_body(self, func) -> None:
        self.declarations.validate_default_parameters(func.params, func.line, func.col)
        self.session.scope.define(
            func.name,
            self.session.local_symbol(
                func.name, func.return_type, "function", func.name_line or func.line, func.name_col or func.col
            ),
        )
        for param in func.params:
            self.generics.collect_type_instances(param.type)
            if param.default is not None:
                parameter_value_type = self.aggregates.array_parameter_value_type(param.type)
                self.aggregates.validate_array_parameter_default(
                    param.type,
                    param.default,
                    f"Default for parameter '{param.name}'",
                    param.line or func.line,
                    param.col or func.col,
                )
                with self.session.default_analysis():
                    self.analyze_expression(param.default)
                self.check_nullable_store(param.type, param.default, f"parameter '{param.name}'")
                self.expressions.validate_value(
                    ExpressionValuePlan(
                        parameter_value_type,
                        param.default,
                        f"Default for parameter '{param.name}'",
                        param.line or func.line,
                        param.col or func.col,
                        callable_storage=True,
                    )
                )
                self.expressions.apply_initializer_plan(
                    self.aggregates.plan_typed_initializer(
                        parameter_value_type,
                        param.default,
                        f"Default for parameter '{param.name}'",
                        param.line or func.line,
                        param.col or func.col,
                    )
                )
            # An unnamed prototype parameter binds nothing.
            if param.name and self._claim_local_binding(
                param.name,
                "parameter",
                param.name_line or param.line,
                param.name_col or param.col,
                c_name_generated=True,
            ):
                self.session.scope.define(param.name, self._param_symbol(param))
        self.generics.collect_type_instances(func.return_type)
        self._analyze_root_block(func.body)
        if func.is_gpu:
            self.gpu.validate_kernel(func)
        if (
            func.return_type
            and (not self.types.is_nonpointer_void_object(func.return_type))
            and func.body
            and (not self.flow.block_must_terminate(func.body))
        ):
            self.session.error(
                f"Function '{func.name}' has non-void return type but no return statement", func.line, func.col
            )

    def analyze_rich_enum_defaults(self, declaration) -> None:
        """Analyze each variant default with only earlier parameters in scope."""
        previous_callable = self.session.current_callable
        previous_return = self.session.current_return_type
        self.session.current_return_type = TypeExpr(base=declaration.name)
        try:
            for variant in declaration.variants:
                self.session.current_callable = variant
                with self.session.scope_frame():
                    self._analyze_rich_enum_variant_defaults(declaration, variant)
        finally:
            self.session.current_callable = previous_callable
            self.session.current_return_type = previous_return

    def _analyze_rich_enum_variant_defaults(self, declaration, variant) -> None:
        self.declarations.validate_default_parameters(variant.params, variant.line, variant.col)
        for parameter in variant.params:
            self.generics.collect_type_instances(parameter.type)
            if parameter.default is not None:
                with self.session.default_analysis():
                    self.analyze_expression(parameter.default)
                self.check_nullable_store(parameter.type, parameter.default, f"parameter '{parameter.name}'")
                self.expressions.validate_value(
                    ExpressionValuePlan(
                        parameter.type,
                        parameter.default,
                        f"Default for rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                        parameter.line or variant.line,
                        parameter.col or variant.col,
                        callable_storage=True,
                    )
                )
                self.expressions.apply_initializer_plan(
                    self.aggregates.plan_typed_initializer(
                        parameter.type,
                        parameter.default,
                        f"Default for rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'",
                        parameter.line or variant.line,
                        parameter.col or variant.col,
                    )
                )
                actual = self.expressions.infer_type(parameter.default)
                if self.ownership.expression_produces_owned_result(
                    parameter.default
                ) or self.types.requires_string_conversion(parameter.type, actual):
                    self.session.rich_enum_unsafe_default_ids.add(id(parameter.default))
            if self._claim_local_binding(
                parameter.name,
                "parameter",
                parameter.name_line or parameter.line,
                parameter.name_col or parameter.col,
                c_name_generated=True,
            ):
                self.session.scope.define(parameter.name, self._param_symbol(parameter))

    def _analyze_try_catch(self, statement) -> None:
        before_try = set(self.session.nonnull_paths)
        with self._flow_branch(()):
            self._analyze_block(statement.try_block)
            try_flow = self.session.nonnull_flow
        catch_flow = None
        if statement.catch_block is not None:
            with self._flow_branch(()):
                self._analyze_catch_body(statement)
                catch_flow = self.session.nonnull_flow
        if statement.finally_block is not None:
            # The finally block runs on every exit, so a body that never
            # completes still reaches it, from facts no stronger than the entry.
            finally_inputs = [try_flow if try_flow is not None else before_try]
            finally_inputs.append(
                catch_flow if statement.catch_block is not None and catch_flow is not None else before_try
            )
            self.session.replace_nonnull_paths(self.flow.join_nonnull_flows(finally_inputs))
            self._analyze_block(statement.finally_block)
            if try_flow is None and (statement.catch_block is None or catch_flow is None):
                self.session.mark_flow_unreachable()
            return
        continuing_flows = []
        if not self.flow.block_stops_fallthrough(statement.try_block):
            continuing_flows.append(try_flow)
        if statement.catch_block is not None and (not self.flow.block_stops_fallthrough(statement.catch_block)):
            continuing_flows.append(catch_flow)
        self.session.replace_nonnull_flow(self.flow.join_nonnull_flows(continuing_flows))

    def _analyze_catch_body(self, statement) -> None:
        with self.session.scope_frame():
            catch_type = statement.catch_type
            if catch_type is not None:
                catch_type = self.types.upgrade_class_type(catch_type)
                self.generics.collect_type_instances(catch_type)
                self.session.record_node_type(statement, catch_type)
                if not (catch_type.base == "string" and catch_type.pointer_depth == 0):
                    self.session.error(
                        f"Catch type '{catch_type.base}' is not supported — exceptions carry a string message; use 'string {statement.catch_var}' or an untyped catch",
                        getattr(catch_type, "line", statement.line),
                        getattr(catch_type, "col", statement.col),
                    )
            if self._claim_local_binding(statement.catch_var, "catch variable", statement.line, statement.col):
                self.session.scope.define(
                    statement.catch_var,
                    self.session.local_symbol(
                        statement.catch_var,
                        TypeExpr(base="string"),
                        "catch",
                        statement.line,
                        statement.col,
                        owned_storage=True,
                    ),
                )
            self._analyze_root_block(statement.catch_block)

    _MANAGED_COLLECTION_BASES = frozenset({"Array", "List", "Map", "Set", "Vector"})

    def _analyze_block(self, block):
        if block is None:
            return
        with self.session.scope_frame():
            self._analyze_statement_sequence(block)

    def _analyze_root_block(self, block):
        """Analyze a callable body in the same scope as its parameters."""
        if block is not None:
            self._analyze_statement_sequence(block)

    def _analyze_statement_sequence(self, block):
        self._analyze_statements(block.statements)

    def _analyze_statements(self, statements):
        found_terminal = False
        with self.session.statement_sequence():
            for stmt in statements:
                if found_terminal:
                    line = getattr(stmt, "line", 0)
                    col = getattr(stmt, "col", 0)
                    self.session.error("Unreachable code after return/throw/break/continue", line, col)
                    break
                reached = not self.session.flow_unreachable
                self._analyze_stmt(stmt)
                self.session.advance_statement(stmt)
                # Code after a return, a throw or a call that never returns is
                # unreachable, and so is everything after unreachable code.
                if not reached or self.flow.statement_ends_flow(stmt):
                    self.session.mark_flow_unreachable()
                if isinstance(stmt, (ReturnStmt, BreakStmt, ContinueStmt, ThrowStmt)):
                    found_terminal = True

    def _analyze_stmt(self, stmt):
        if isinstance(stmt, VarDeclStmt):
            self._analyze_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self.expressions.contextualize_value(
                    ExpressionValuePlan(
                        self.session.current_return_type, stmt.value, "Return value", stmt.line, stmt.col
                    )
                )
                self.analyze_expression(stmt.value)
                self.check_nullable_store(self.session.current_return_type, stmt.value, "return value")
                self.aggregates.validate_thread_transfer_source(stmt.value)
                self.expressions.validate_value(
                    ExpressionValuePlan(
                        self.session.current_return_type,
                        stmt.value,
                        "Return value",
                        stmt.line,
                        stmt.col,
                        managed_string=True,
                    )
                )
                self.ownership.validate_opaque_borrow_storage(
                    self.session.current_return_type, stmt.value, "Return value", stmt.line, stmt.col
                )
                self.storage.validate_volatile_reference_conversion(
                    self.session.current_return_type, stmt.value, "Return value", stmt.line, stmt.col
                )
                if self.session.current_return_type:
                    self.expressions.apply_initializer_plan(
                        self.aggregates.plan_aggregate_initializer(
                            self.session.current_return_type, stmt.value, "Return value", stmt.line, stmt.col
                        )
                    )
                if self.types.is_nonpointer_void_object(self.session.current_return_type):
                    self.session.error("Void function or method cannot return a value", stmt.line, stmt.col)
                elif self.session.current_return_type:
                    ret_type = self.expressions.infer_type(stmt.value)
                    escaping_callable = self.expressions.validate_value(
                        ExpressionValuePlan(
                            self.session.current_return_type,
                            stmt.value,
                            "Return value",
                            stmt.line,
                            stmt.col,
                            callable_escape=True,
                        )
                    )
                    if (
                        not escaping_callable
                        and ret_type
                        and (not self._return_type_compatible(self.session.current_return_type, ret_type))
                    ):
                        self.session.error(
                            f"Return type mismatch: expected '{self.types.format_type(self.session.current_return_type)}' but got '{self.types.format_type(ret_type)}'",
                            stmt.line,
                            stmt.col,
                        )
            elif self.session.current_return_type and (
                not self.types.is_nonpointer_void_object(self.session.current_return_type)
            ):
                self.session.error(
                    f"Non-void function or method must return '{self.types.format_type(self.session.current_return_type)}'",
                    stmt.line,
                    stmt.col,
                )
        elif isinstance(stmt, IfStmt):
            self._analyze_nullable_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._analyze_nullable_while(stmt)
        elif isinstance(stmt, DoWhileStmt):
            self.session.loop_depth += 1
            self.session.break_depth += 1
            self._analyze_nullable_loop_body(stmt.body, back_edge=(stmt.condition,))
            self.session.loop_depth -= 1
            self.session.break_depth -= 1
            self.analyze_expression(stmt.condition)
            self.aggregates.reject_thread_observation(stmt.condition)
        elif isinstance(stmt, ForInStmt):
            self._analyze_for_in(stmt)
        elif isinstance(stmt, ParallelForStmt):
            self._analyze_parallel_for(stmt)
        elif isinstance(stmt, CForStmt):
            self._analyze_c_for(stmt)
        elif isinstance(stmt, SwitchStmt):
            self._analyze_switch(stmt)
        elif isinstance(stmt, ExprStmt):
            with self.session.standalone_expression(stmt.expr):
                boundary = self.gpu.result_statement_boundary(stmt.expr)
                with self.session.gpu_result_context(boundary):
                    self.analyze_expression(stmt.expr)
            self.aggregates.validate_thread_expression_discard(stmt.expr)
        elif isinstance(stmt, DeleteStmt):
            self.analyze_expression(stmt.expr)
            self._validate_ownership_operand(stmt)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)
        elif isinstance(stmt, TryCatchStmt):
            self._analyze_try_catch(stmt)
        elif isinstance(stmt, (ThrowStmt, KeepStmt, ReleaseStmt)):
            self.analyze_expression(stmt.expr)
            if isinstance(stmt, ThrowStmt):
                self.aggregates.reject_thread_observation(stmt.expr)
            if isinstance(stmt, (KeepStmt, ReleaseStmt)):
                self._validate_ownership_operand(stmt)
        elif isinstance(stmt, BreakStmt):
            if self.session.break_depth == 0:
                self.session.error("'break' statement outside of loop or switch", stmt.line, stmt.col)
        elif isinstance(stmt, ContinueStmt):
            if self.session.loop_depth == 0:
                self.session.error("'continue' statement outside of loop", stmt.line, stmt.col)

    def _return_type_compatible(self, expected, actual) -> bool:
        expected = self.aggregates.array_value_type(expected)
        if self.session.in_gpu_function and expected.is_array:
            element_type = TypeExpr(
                base=expected.base,
                generic_args=expected.generic_args,
                pointer_depth=expected.pointer_depth,
                is_const=expected.is_const,
                is_nullable=expected.is_nullable,
                nullable_outer_depth=expected.nullable_outer_depth,
                is_static=expected.is_static,
                is_extern=expected.is_extern,
                is_volatile=expected.is_volatile,
            )
            return self.types.types_compatible(expected, actual) or self.types.types_compatible(element_type, actual)
        return self.types.types_compatible(expected, actual)

    def _analyze_var_decl(self, stmt):
        is_global = self.session.scope is self.session.global_scope
        define_binding = is_global or self._claim_local_binding(
            stmt.name, "variable", stmt.name_line or stmt.line, stmt.name_col or stmt.col
        )
        explicit_type = stmt.type is not None
        if stmt.type is None:
            if stmt.initializer is None:
                self.session.error(f"'var' declaration of '{stmt.name}' requires an initializer", stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.session.scope.define(stmt.name, self._var_symbol(stmt))
                return
            boundary = self.gpu.array_initializer_boundary(stmt.initializer, stmt.type)
            with self.session.gpu_result_context(boundary):
                self.analyze_expression(stmt.initializer)
            inferred = self.expressions.infer_type(stmt.initializer)
            if inferred is not None and self.session.in_gpu_function:
                inferred = self.gpu.contextual_local_type(stmt.initializer)
            if inferred is None:
                # An unresolved name is the cause; report it, not its consequence.
                if not self.generated_symbols.report_unresolved_value(stmt.initializer):
                    self.session.error(f"Cannot infer type for 'var' declaration of '{stmt.name}'", stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.session.scope.define(stmt.name, self._var_symbol(stmt))
                return
            if self.types.is_void_value(inferred):
                self.session.error(f"Cannot assign void expression to variable '{stmt.name}'", stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.session.scope.define(stmt.name, self._var_symbol(stmt))
                return
            stmt.type = self._inferred_array_binding_type(inferred, stmt.initializer)
            self.storage.validate_volatile_reference_conversion(
                stmt.type, stmt.initializer, f"Variable '{stmt.name}'", stmt.line, stmt.col
            )
            if stmt.type.base in self.index.class_table and stmt.type.pointer_depth == 0:
                stmt.type = self.types.upgrade_class_type(stmt.type)
            self.aggregates.validate_thread_handle_copy(stmt.type, stmt.initializer, stmt.line, stmt.col)
            self.generics.collect_type_instances(stmt.type)
            self.expressions.validate_value(
                ExpressionValuePlan(
                    stmt.type,
                    stmt.initializer,
                    f"Initializer for '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                    explicit_type=explicit_type,
                    callable_storage=True,
                )
            )
            if not self.ownership.expression_produces_owned_result(stmt.initializer):
                self.ownership.validate_opaque_borrow_storage(
                    stmt.type, stmt.initializer, f"Variable '{stmt.name}'", stmt.line, stmt.col
                )
            self._validate_variable_storage(stmt, is_global=is_global)
            if define_binding:
                self.session.scope.define(stmt.name, self._var_symbol(stmt))
                if not is_global and self._is_nullable_binding(stmt.type) and self._stores_nonnull(stmt.initializer):
                    self.flow.record_nonnull_binding(self.session.scope.lookup(stmt.name))
            return
        stmt.type = self.types.upgrade_class_type(stmt.type)
        self.validate_nonescaping_variable(stmt, is_global=is_global)
        self.generics.collect_type_instances(stmt.type)
        if stmt.initializer:
            self.expressions.contextualize_ternary_literals(stmt.initializer, stmt.type)
            boundary = self.gpu.array_initializer_boundary(stmt.initializer, stmt.type)
            with self.session.gpu_result_context(boundary):
                self.analyze_expression(stmt.initializer)
            self.check_nullable_store(stmt.type, stmt.initializer, f"variable '{stmt.name}'")
            self.aggregates.validate_array_object_initializer(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
                is_gpu_array_result=self.gpu.is_array_result(stmt.initializer),
            )
            self.expressions.apply_initializer_plan(
                self.aggregates.plan_aggregate_initializer(
                    stmt.type, stmt.initializer, f"Initializer for '{stmt.name}'", stmt.line, stmt.col
                )
            )
            self.aggregates.validate_fixed_array_initializer(
                stmt.type, stmt.initializer, f"Initializer for '{stmt.name}'", stmt.line, stmt.col
            )
            self._validate_char_array_initializer(stmt.type, stmt.initializer, is_global=is_global)
            self.expressions.validate_value(
                ExpressionValuePlan(
                    stmt.type,
                    stmt.initializer,
                    f"Initializer for '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                    explicit_type=explicit_type,
                    callable_storage=True,
                )
            )
            if isinstance(stmt.initializer, (ListLiteral, MapLiteral, BraceInitializer)):
                self.expressions.apply_initializer_plan(
                    self.aggregates.plan_collection_initializer(
                        stmt.type, stmt.initializer, f"Initializer for '{stmt.name}'", stmt.line, stmt.col
                    )
                )
            self.expressions.contextualize_value(
                ExpressionValuePlan(stmt.type, stmt.initializer, f"Initializer for '{stmt.name}'", stmt.line, stmt.col)
            )
            init_type = self.expressions.infer_type(stmt.initializer)
            self.expressions.validate_value(
                ExpressionValuePlan(
                    stmt.type,
                    stmt.initializer,
                    f"Initializer for '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                    managed_string=True,
                )
            )
            self.storage.validate_volatile_reference_conversion(
                stmt.type, stmt.initializer, f"Initializer for '{stmt.name}'", stmt.line, stmt.col
            )
            if not self.ownership.expression_produces_owned_result(stmt.initializer):
                self.ownership.validate_opaque_borrow_storage(
                    stmt.type, stmt.initializer, f"Variable '{stmt.name}'", stmt.line, stmt.col
                )
            self.aggregates.validate_thread_handle_copy(stmt.type, stmt.initializer, stmt.line, stmt.col)
            if self.types.is_void_value(init_type):
                self.session.error(f"Cannot assign void expression to variable '{stmt.name}'", stmt.line, stmt.col)
            elif self.aggregates.char_array_string_initializer(stmt.type, stmt.initializer):
                pass
            elif init_type and stmt.type and (not self.types.types_compatible(stmt.type, init_type)):
                is_empty_literal = (
                    (isinstance(stmt.initializer, ListLiteral) and (not stmt.initializer.elements))
                    or (isinstance(stmt.initializer, MapLiteral) and (not stmt.initializer.entries))
                    or isinstance(stmt.initializer, BraceInitializer)
                )
                if not is_empty_literal:
                    self.session.error(
                        f"Cannot assign '{self.types.format_type(init_type)}' to variable '{stmt.name}' "
                        f"of type '{self.types.format_type(stmt.type)}'"
                        f"{self.types.comma_tuple_hint(stmt.initializer, stmt.type)}",
                        stmt.line,
                        stmt.col,
                    )
            if (
                stmt.type
                and stmt.type.generic_args
                and isinstance(stmt.initializer, (ListLiteral, MapLiteral, BraceInitializer))
            ):
                self.session.record_node_type(stmt.initializer, stmt.type)
                self.generics.collect_type_instances(stmt.type)
        self._validate_variable_storage(stmt, is_global=is_global)
        if define_binding:
            self.session.scope.define(stmt.name, self._var_symbol(stmt))
            if not is_global and self._is_nullable_binding(stmt.type) and self._stores_nonnull(stmt.initializer):
                self.flow.record_nonnull_binding(self.session.scope.lookup(stmt.name))

    def _var_symbol(self, stmt: VarDeclStmt) -> SymbolInfo:
        """SymbolInfo for a local var decl, pinned to its name token span."""
        nl = stmt.name_line or stmt.line
        nc = stmt.name_col or stmt.col
        symbol = self.session.local_symbol(stmt.name, self.aggregates.array_value_type(stmt.type), "variable", nl, nc)
        symbol.captures_environment = self.expressions.value_requires_environment(stmt.initializer)
        return symbol


__all__ = ["StatementAnalyzer"]
