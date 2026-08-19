"""Aggregate, array, enum, and initializer semantics."""

from __future__ import annotations

from dataclasses import dataclass

from src.compiler.python.analyzer.program import AnalysisContext, AnalysisSession, DeclarationIndex
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    CallExpr,
    ClassDecl,
    FieldAccessExpr,
    FieldDecl,
    FieldDef,
    FunctionDecl,
    Identifier,
    IntLiteral,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    NullLiteral,
    PropertyDecl,
    RichEnumDecl,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StructDecl,
    TernaryExpr,
    TypedefDecl,
    TypeExpr,
)


@dataclass(frozen=True)
class InitializerValueCheck:
    expected: TypeExpr
    value: object
    subject: str
    line: int
    col: int
    validate_fixed_array: bool = False
    contextualize_constructor: bool = False


@dataclass(frozen=True)
class InitializerArrayFieldCheck:
    field: FieldDef
    value: object
    subject: str
    line: int
    col: int


@dataclass(frozen=True)
class InitializerStringConversionCheck:
    expected: TypeExpr
    value: object
    message: str
    line: int
    col: int


@dataclass(frozen=True)
class InitializerCompatibilityCheck:
    expected: TypeExpr
    value: object
    subject: str
    line: int
    col: int
    element: bool = False
    reject_void: bool = False


@dataclass(frozen=True)
class InitializerTypeContext:
    value: object
    expected: TypeExpr


type InitializerStep = (
    InitializerValueCheck
    | InitializerArrayFieldCheck
    | InitializerStringConversionCheck
    | InitializerCompatibilityCheck
    | InitializerTypeContext
)


@dataclass(frozen=True)
class InitializerPlan:
    """Ordered semantic work implied by one initializer shape."""

    contextual: bool
    steps: tuple[InitializerStep, ...] = ()


class InitializerTypeLayout:
    """Resolve the target storage shapes needed while planning initializers."""

    def __init__(self, index: DeclarationIndex) -> None:
        self.index = index

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return TypeSystem.canonical_declaration_type(type_expr, self.index.typedef_table)

    def array_value(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        canonical = self.canonical(type_expr)
        if type_expr is None or canonical is None or type_expr.is_array or (not canonical.is_array):
            return type_expr
        return TypeSystem.add_outer_pointer(canonical, clear_array=True)

    def array_field_value(self, field: FieldDef) -> TypeExpr:
        value_type = self.array_value(field.type)
        canonical = self.canonical(value_type)
        if (
            canonical is None
            or not canonical.is_array
            or canonical.array_size is not None
            or (field.access == "class" and isinstance(field.initializer, (BraceInitializer, ListLiteral)))
        ):
            return value_type
        return TypeSystem.add_outer_pointer(canonical, clear_array=True)

    @staticmethod
    def array_element(type_expr: TypeExpr) -> TypeExpr:
        return TypeSystem.strip_outer_storage(type_expr, array=True)

    def format(self, type_expr: TypeExpr) -> str:
        result = type_expr.base
        if type_expr.generic_args:
            arguments = ", ".join(self.format(argument) for argument in type_expr.generic_args)
            result += f"<{arguments}>"
        result += "*" * type_expr.pointer_depth
        if type_expr.is_array:
            result += "[]"
        return result


class InitializerAnalyzer:
    """Plan initializer structure without reaching into semantic policies."""

    _BRACE_SEQUENCE_COLLECTIONS = frozenset({"Array", "List", "Set", "Vector"})

    def __init__(self, context: AnalysisContext, index: DeclarationIndex, types: InitializerTypeLayout) -> None:
        self.context = context
        self.index = index
        self.types = types

    def plan_typed(self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int) -> InitializerPlan:
        """Plan full validation of a value against its declared type."""
        expected = self.types.array_value(expected)
        steps: list[InitializerStep] = [
            InitializerValueCheck(
                expected, initializer, subject, line, col, validate_fixed_array=True, contextualize_constructor=True
            )
        ]
        contextual = self.plan_aggregate(expected, initializer, subject, line, col)
        if not contextual.contextual:
            contextual = self.plan_collection(expected, initializer, subject, line, col)
        steps.extend(contextual.steps)
        if not contextual.contextual:
            steps.append(InitializerCompatibilityCheck(expected, initializer, subject, line, col, reject_void=True))
        return InitializerPlan(contextual.contextual, tuple(steps))

    def plan_aggregate(
        self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int
    ) -> InitializerPlan:
        """Plan positional struct or tuple initializer contextualization."""
        if not isinstance(initializer, BraceInitializer):
            return InitializerPlan(False)
        canonical = self.types.canonical(expected)
        if canonical is None or canonical.pointer_depth > 0 or canonical.is_array:
            return InitializerPlan(False)
        steps: list[InitializerStep] = []
        struct_name = canonical.base.removeprefix("struct ")
        declaration = self.index.struct_table.get(struct_name)
        if declaration is not None and (not declaration.is_forward):
            for field, element in zip(declaration.fields, initializer.elements):
                steps.append(
                    InitializerArrayFieldCheck(
                        field,
                        element,
                        f"Field '{field.name}'",
                        getattr(element, "line", line),
                        getattr(element, "col", col),
                    )
                )
            fields = [(field.name, self.types.array_field_value(field)) for field in declaration.fields]
            aggregate_name = f"struct '{struct_name}'"
        elif canonical.base == "Tuple":
            fields = [(f"_{index}", argument) for index, argument in enumerate(canonical.generic_args)]
            aggregate_name = f"tuple '{self.types.format(canonical)}'"
        else:
            return InitializerPlan(False)
        if len(initializer.elements) > len(fields):
            self.context.error(
                f"{subject} has {len(initializer.elements)} initializer elements but {aggregate_name} has {len(fields)} fields",
                line,
                col,
            )
        for element, (field_name, field_type) in zip(initializer.elements, fields):
            element_line = getattr(element, "line", line)
            element_col = getattr(element, "col", col)
            steps.append(
                InitializerStringConversionCheck(
                    field_type,
                    element,
                    f"Implicit class-to-string conversion is not supported inside {aggregate_name}; prepare an owned string local for field '{field_name}' first",
                    element_line,
                    element_col,
                )
            )
            nested = self.plan_typed(field_type, element, f"Field '{field_name}'", element_line, element_col)
            steps.extend(nested.steps)
        steps.append(InitializerTypeContext(initializer, expected))
        return InitializerPlan(True, tuple(steps))

    def plan_collection(
        self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int
    ) -> InitializerPlan:
        """Plan sequence or map literal contextualization."""
        element_types = None
        canonical = self.types.canonical(expected) or expected
        if isinstance(initializer, BraceInitializer):
            if canonical.base in self._BRACE_SEQUENCE_COLLECTIONS and len(canonical.generic_args) == 1:
                element_types = canonical.generic_args
            elif canonical.is_array:
                element_types = [self.types.array_element(canonical)]
            elif self._is_generic_heap_class(canonical):
                if initializer.elements:
                    self.context.error(
                        f"{subject} cannot use a non-empty brace initializer for heap class '{self.types.format(canonical)}'; use an explicit constructor call",
                        line,
                        col,
                    )
                return InitializerPlan(True, (InitializerTypeContext(initializer, expected),))
        elif isinstance(initializer, ListLiteral):
            if canonical.is_array:
                element_types = [self.types.array_element(canonical)]
            elif canonical.base in self._BRACE_SEQUENCE_COLLECTIONS and len(canonical.generic_args) == 1:
                element_types = canonical.generic_args
        elif isinstance(initializer, MapLiteral) and canonical.base == "Map" and (len(canonical.generic_args) == 2):
            steps: list[InitializerStep] = []
            key_type, value_type = canonical.generic_args
            for entry in initializer.entries:
                steps.extend(self._plan_collection_element(key_type, entry.key, f"{subject} key", line, col))
                steps.extend(self._plan_collection_element(value_type, entry.value, f"{subject} value", line, col))
            steps.append(InitializerTypeContext(initializer, expected))
            return InitializerPlan(True, tuple(steps))
        if element_types is None:
            return InitializerPlan(False)
        expected_element = element_types[0]
        steps = []
        for element in initializer.elements:
            if canonical.is_array:
                steps.append(
                    InitializerStringConversionCheck(
                        expected_element,
                        element,
                        "Implicit class-to-string conversion is not supported inside a shallow array initializer; prepare owned string locals first",
                        getattr(element, "line", line),
                        getattr(element, "col", col),
                    )
                )
            steps.extend(self._plan_collection_element(expected_element, element, subject, line, col))
        steps.append(InitializerTypeContext(initializer, expected))
        return InitializerPlan(True, tuple(steps))

    def _is_generic_heap_class(self, type_expr: TypeExpr) -> bool:
        declaration = self.index.class_table.get(type_expr.base)
        return bool(declaration is not None and declaration.generic_params and type_expr.generic_args)

    def _plan_collection_element(
        self, expected: TypeExpr, element: object, subject: str, line: int, col: int
    ) -> list[InitializerStep]:
        element_line = getattr(element, "line", line)
        element_col = getattr(element, "col", col)
        steps: list[InitializerStep] = [InitializerValueCheck(expected, element, subject, element_line, element_col)]
        if isinstance(element, (BraceInitializer, ListLiteral, MapLiteral)):
            steps.extend(self.plan_typed(expected, element, subject, element_line, element_col).steps)
        else:
            steps.append(
                InitializerCompatibilityCheck(expected, element, subject, element_line, element_col, element=True)
            )
        return steps


class AggregateAnalyzer:
    """Aggregate, array, enum, and initializer semantics."""

    def __init__(self, session: AnalysisSession, index: DeclarationIndex, types: TypeSystem) -> None:
        self.session = session
        self.index = index
        self.types = types
        self._initializers = InitializerAnalyzer(
            session,
            index,
            InitializerTypeLayout(index),
        )

    def plan_typed_initializer(
        self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int
    ) -> InitializerPlan:
        """Plan complete validation for a typed initializer boundary."""
        return self._initializers.plan_typed(expected, initializer, subject, line, col)

    def plan_aggregate_initializer(
        self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int
    ) -> InitializerPlan:
        """Plan positional aggregate initializer validation."""
        return self._initializers.plan_aggregate(expected, initializer, subject, line, col)

    def plan_collection_initializer(
        self, expected: TypeExpr, initializer: object, subject: str, line: int, col: int
    ) -> InitializerPlan:
        """Plan sequence or map initializer validation."""
        return self._initializers.plan_collection(expected, initializer, subject, line, col)

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def validate_tuple_field_access(self, expression, object_type) -> bool:
        """Validate and recognize the canonical zero-based tuple field API."""
        canonical = self.types.canonical_type(object_type)
        if canonical is None or not (canonical.base == "Tuple" or canonical.base.startswith("(")):
            return False
        suffix = expression.field[1:] if expression.field.startswith("_") else ""
        if not suffix.isdigit() or expression.field != f"_{int(suffix)}":
            self.session.error(
                f"Tuple has no field '{expression.field}'; use '_N' for a zero-based element index",
                expression.line,
                expression.col,
            )
            return True
        index = int(suffix)
        if index >= len(canonical.generic_args):
            self.session.error(
                f"Tuple field '{expression.field}' is out of range for {len(canonical.generic_args)} element(s)",
                expression.line,
                expression.col,
            )
        return True

    def validate_struct_field_access(self, expression, object_type) -> bool:
        """Validate a member access when its receiver is a known C struct."""
        canonical = self.types.canonical_type(object_type)
        if canonical is None:
            return False
        struct_name = canonical.base.removeprefix("struct ")
        declaration = self.index.struct_table.get(struct_name)
        if declaration is None:
            return False
        if not any(field.name == expression.field for field in declaration.fields):
            self.session.error(
                f"Struct '{struct_name}' has no field '{expression.field}'", expression.line, expression.col
            )
        return True

    def validate_declarations(self, program) -> None:
        """Reject source layouts that no strict-C declaration order can satisfy."""
        declarations = list(self.session.declarations(program))
        self._validate_typedef_cycles(declarations)
        graph: dict[str, set[str]] = {}
        owners = {}
        for declaration in declarations:
            with self.session.source(getattr(declaration, "source_file", None)):
                self._collect_aggregate_dependencies(declaration, graph, owners)
        self._report_dependency_cycles(graph, owners, "Aggregate")

    def _collect_aggregate_dependencies(self, declaration, graph, owners) -> None:
        if isinstance(declaration, StructDecl) and (not declaration.is_forward):
            owners[declaration.name] = declaration
            graph[declaration.name] = set()
            for field in declaration.fields:
                subject = f"Struct field '{declaration.name}.{field.name}'"
                self.validate_complete_aggregate_use(field.type, subject, field.line, field.col)
                graph[declaration.name].update(self._value_aggregate_names(field.type))
        elif isinstance(declaration, RichEnumDecl):
            owners[declaration.name] = declaration
            graph[declaration.name] = set()
            for variant in declaration.variants:
                for parameter in variant.params:
                    subject = f"Rich-enum payload '{declaration.name}.{variant.name}.{parameter.name}'"
                    self.validate_complete_aggregate_use(parameter.type, subject, parameter.line, parameter.col)
                    graph[declaration.name].update(self._value_aggregate_names(parameter.type))
        elif isinstance(declaration, FunctionDecl) and declaration.body:
            self._validate_callable_complete_types(declaration, declaration.name)
        elif isinstance(declaration, ClassDecl):
            self._validate_class_complete_types(declaration)

    def _validate_callable_complete_types(self, declaration, owner) -> None:
        if not getattr(declaration, "is_constructor", False):
            self.validate_complete_aggregate_use(
                declaration.return_type, f"Return type of '{owner}'", declaration.line, declaration.col
            )
        for parameter in declaration.params:
            self.validate_complete_aggregate_use(
                parameter.type, f"Parameter '{owner}.{parameter.name}'", parameter.line, parameter.col
            )

    def _validate_class_complete_types(self, declaration) -> None:
        for member in declaration.members:
            if isinstance(member, FieldDecl):
                self.validate_complete_aggregate_use(
                    member.type, f"Field '{declaration.name}.{member.name}'", member.line, member.col
                )
            elif isinstance(member, PropertyDecl):
                self.validate_complete_aggregate_use(
                    member.type, f"Property '{declaration.name}.{member.name}'", member.line, member.col
                )
            elif isinstance(member, MethodDecl) and member.body:
                self._validate_callable_complete_types(member, f"{declaration.name}.{member.name}")

    def validate_complete_aggregate_use(self, type_expr, subject, line=0, col=0, *, sizeof=False) -> bool:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or canonical.pointer_depth > 0:
            return True
        if canonical.base == "Tuple":
            return all(
                self.validate_complete_aggregate_use(argument, subject, line, col, sizeof=sizeof)
                for argument in canonical.generic_args
            )
        name = canonical.base.removeprefix("struct ")
        if name not in self.index.struct_table or name in self.index.struct_definitions:
            return True
        if sizeof:
            self.session.error(f"{subject} cannot use incomplete type '{name}'", line, col)
        else:
            self.session.error(f"{subject} uses incomplete struct '{name}'", line, col)
        return False

    def _value_aggregate_names(self, type_expr) -> set[str]:
        canonical = self.types.canonical_type(type_expr)
        if canonical is None or canonical.pointer_depth > 0:
            return set()
        if canonical.base == "Tuple":
            return {name for argument in canonical.generic_args for name in self._value_aggregate_names(argument)}
        name = canonical.base.removeprefix("struct ")
        if name in self.index.struct_definitions or name in self.index.rich_enum_table:
            return {name}
        return set()

    def _validate_typedef_cycles(self, declarations) -> None:
        typedefs = {
            declaration.alias: declaration for declaration in declarations if isinstance(declaration, TypedefDecl)
        }
        graph = {
            name: self._referenced_aliases(declaration.original, set(typedefs))
            for name, declaration in typedefs.items()
        }
        self._report_dependency_cycles(graph, typedefs, "Cyclic typedef")

    def _referenced_aliases(self, type_expr, aliases) -> set[str]:
        result = {type_expr.base} & aliases
        for argument in type_expr.generic_args:
            result.update(self._referenced_aliases(argument, aliases))
        return result

    def _report_dependency_cycles(self, graph, owners, label) -> None:
        state: dict[str, int] = {}
        stack: list[str] = []
        reported: set[frozenset[str]] = set()

        def visit(name):
            state[name] = 1
            stack.append(name)
            for dependency in sorted(graph.get(name, ())):
                if dependency not in graph:
                    continue
                if state.get(dependency, 0) == 0:
                    visit(dependency)
                elif state.get(dependency) == 1:
                    cycle = stack[stack.index(dependency) :] + [dependency]
                    key = frozenset(cycle)
                    if key not in reported:
                        reported.add(key)
                        owner = owners[name]
                        with self.session.source(getattr(owner, "source_file", None)):
                            self.session.error(
                                f"{label} dependency cycle involving " + " -> ".join(f"'{item}'" for item in cycle),
                                owner.line,
                                owner.col,
                            )
            stack.pop()
            state[name] = 2

        for name in graph:
            if state.get(name, 0) == 0:
                visit(name)

    def validate_sizeof_operand(self, expression) -> None:
        operand = expression.operand
        if isinstance(operand, SizeofType):
            type_expr = operand.type
            line, col = (type_expr.line or expression.line, type_expr.col or expression.col)
        elif isinstance(operand, SizeofExprOp):
            type_expr = self.type_of(operand.expr)
            line, col = (expression.line, expression.col)
        else:
            return
        canonical = self.types.canonical_type(type_expr)
        if canonical is None:
            return
        if self.types.is_void_value(canonical):
            self.session.error("sizeof cannot be applied to void", line, col)
            return
        self.validate_complete_aggregate_use(canonical, "sizeof", line, col, sizeof=True)

    @staticmethod
    def _array_element_type(array_type):
        return TypeSystem.strip_outer_storage(array_type, array=True)

    def validate_fixed_array_initializer(self, expected, initializer, subject, line, col) -> None:
        """Reject initializer lists that exceed a statically known bound."""
        if expected is None or not expected.is_array:
            return
        bound = expected.array_size
        if not isinstance(bound, IntLiteral):
            return
        if not isinstance(initializer, (BraceInitializer, ListLiteral)):
            return
        count = len(initializer.elements)
        if count > bound.value:
            self.session.error(f"{subject} has {count} elements but fixed array bound is {bound.value}", line, col)

    def validate_array_object_initializer(
        self, expected, initializer, subject, line, col, *, is_gpu_array_result: bool
    ) -> None:
        """Validate array representation using an outward GPU-result fact."""
        canonical = self.types.canonical_type(expected)
        represented = self.types.canonical_type(self.array_value_type(expected))
        aggregate = isinstance(initializer, (BraceInitializer, ListLiteral))
        if canonical is not None and canonical.is_array and represented is not None and not represented.is_array:
            if is_gpu_array_result:
                self.session.error(
                    f"{subject} cannot materialize an array-returning @gpu result through a pointer-valued array alias",
                    line,
                    col,
                )
            elif aggregate:
                self.session.error(
                    f"{subject} cannot use an array initializer for a pointer-valued array alias", line, col
                )
            return
        if canonical is not None and canonical.is_array and not aggregate and not is_gpu_array_result:
            self.session.error(f"{subject} requires an array initializer", line, col)

    def array_value_type(self, type_expr):
        """Preserve raw array declarators versus pointer-valued array aliases."""
        canonical = self.types.canonical_type(type_expr)
        if type_expr is None or canonical is None or type_expr.is_array or (not canonical.is_array):
            return type_expr
        return self.types.add_outer_pointer(canonical, clear_array=True)

    def array_parameter_value_type(self, type_expr):
        value_type = self.array_value_type(type_expr)
        canonical = self.types.canonical_type(value_type)
        if canonical is None or not canonical.is_array:
            return value_type
        return self.types.add_outer_pointer(canonical, clear_array=True)

    def array_parameter_initializer_type(self, type_expr, initializer):
        if isinstance(initializer, (BraceInitializer, ListLiteral)):
            return self.array_value_type(type_expr)
        return self.array_parameter_value_type(type_expr)

    def validate_array_parameter_default(self, type_expr, initializer, subject, line, col) -> None:
        canonical = self.types.canonical_type(type_expr)
        if canonical is not None and canonical.is_array and isinstance(initializer, (BraceInitializer, ListLiteral)):
            self.session.error(f"{subject} cannot use temporary aggregate backing for an array parameter", line, col)

    def array_field_value_type(self, field, resolved_type=None):
        """Apply field storage representation after generic resolution."""
        value_type = self.array_value_type(field.type if resolved_type is None else resolved_type)
        canonical = self.types.canonical_type(value_type)
        if canonical is not None and (not canonical.is_array):
            return value_type
        if (
            canonical is None
            or not canonical.is_array
            or canonical.array_size is not None
            or (
                getattr(field, "access", None) == "class"
                and isinstance(getattr(field, "initializer", None), (BraceInitializer, ListLiteral))
            )
        ):
            return value_type
        return self.types.add_outer_pointer(canonical, clear_array=True)

    def array_projection_storage_type(self, expression):
        """Return the value representation projected from field storage."""
        inferred = self.type_of(expression)
        if isinstance(expression, FieldAccessExpr):
            member, _ = self._array_target_member(expression)
            if member is not None:
                return self.array_field_value_type(member)
        return inferred

    def validate_pointer_backed_array_field_initializer(self, field, initializer, subject, line, col) -> None:
        canonical = self.types.canonical_type(field.type)
        represented = self.types.canonical_type(self.array_field_value_type(field))
        if (
            canonical is not None
            and canonical.is_array
            and (represented is not None)
            and (not represented.is_array)
            and isinstance(initializer, (BraceInitializer, ListLiteral))
        ):
            self.session.error(f"{subject} cannot use aggregate backing for a pointer-valued array field", line, col)

    def array_target_value_type(self, target, inferred):
        if isinstance(target, Identifier):
            symbol = self.session.scope.lookup(target.name)
            if symbol is not None:
                if symbol.kind in {"param", "lambda_param"}:
                    return self.array_parameter_value_type(symbol.type)
                return self.array_value_type(symbol.type)
        member, _ = self._array_target_member(target)
        if member is not None:
            return self.array_field_value_type(member, inferred)
        return self.array_value_type(inferred)

    def is_pointer_backed_array_target(self, target, inferred) -> bool:
        canonical = self.types.canonical_type(inferred)
        if canonical is None or not canonical.is_array:
            return False
        if isinstance(target, Identifier):
            symbol = self.session.scope.lookup(target.name)
            return bool(symbol and symbol.kind == "param")
        member, storage = self._array_target_member(target)
        if member is None:
            return False
        if storage == "property":
            return member.access != "class" and canonical.array_size is None
        if canonical.array_size is not None:
            return False
        if storage in {"instance-field", "struct-field"}:
            return True
        return storage == "static-field" and (not isinstance(member.initializer, (BraceInitializer, ListLiteral)))

    def array_target_has_capacity(self, target, inferred) -> bool:
        inferred = self.array_target_value_type(target, inferred)
        canonical = self.types.canonical_type(inferred)
        if canonical is None:
            return False
        if canonical.base in {"Array", "Vector"} and canonical.generic_args:
            return True
        if not canonical.is_array:
            return False
        if isinstance(target, FieldAccessExpr):
            member, storage = self._array_target_member(target)
            if canonical.array_size is not None and storage in {"instance-field", "struct-field"}:
                return True
            return bool(
                member
                and storage == "static-field"
                and member.type.is_array
                and isinstance(member.initializer, (BraceInitializer, ListLiteral))
            )
        if not isinstance(target, Identifier):
            return False
        symbol = self.session.scope.lookup(target.name)
        if symbol and symbol.kind == "param":
            return False
        if canonical.is_extern and canonical.array_size is None:
            return False
        return not self.is_pointer_backed_array_target(target, canonical)

    def _array_target_member(self, target):
        if not isinstance(target, FieldAccessExpr) or target.optional:
            return (None, None)
        if isinstance(target.obj, Identifier) and self.session.scope.lookup(target.obj.name) is None:
            class_info = self.index.class_table.get(target.obj.name)
            if class_info is not None:
                member = class_info.static_fields.get(target.field)
                if member is not None:
                    return (member, "static-field")
                prop = class_info.properties.get(target.field)
                if prop is not None and prop.access == "class":
                    return (prop, "property")
        receiver = self.types.canonical_type(self.type_of(target.obj))
        if receiver is None:
            return (None, None)
        class_info = self.index.class_table.get(receiver.base)
        if class_info is not None:
            prop = class_info.properties.get(target.field)
            if prop is not None:
                return (prop, "property")
            member = class_info.fields.get(target.field)
            if member is not None:
                return (member, "instance-field")
        struct_name = receiver.base.removeprefix("struct ")
        structure = self.index.struct_table.get(struct_name)
        if structure is not None:
            member = next((field for field in structure.fields if field.name == target.field), None)
            if member is not None:
                return (member, "struct-field")
        return (None, None)

    _FRESH_THREAD_RESULT_DIAGNOSTIC = (
        "Fresh Thread result must be joined, returned, discarded directly, or bound to a direct Thread<T> owner"
    )

    def validate_thread_handle_copy(self, target_type, value, line, col) -> bool:
        """Reject aliases to the raw, single-consumer pthread handle."""
        target = self.types.canonical_type(target_type)
        source = self.types.canonical_type(self.type_of(value))
        if (
            target is None
            or target.base != "Thread"
            or source is None
            or (source.base != "Thread")
            or (not self._thread_copy_source(value))
        ):
            return False
        self.session.error(
            "Thread handles cannot be copied; transfer a fresh spawn() or function-call result instead", line, col
        )
        return True

    def _thread_copy_source(self, value) -> bool:
        if isinstance(value, (SpawnExpr, CallExpr, NullLiteral)):
            return False
        if isinstance(value, TernaryExpr):
            return self._thread_copy_source(value.true_expr) or self._thread_copy_source(value.false_expr)
        return True

    def _is_fresh_thread_result(self, expression) -> bool:
        result_type = self.types.canonical_type(self.type_of(expression))
        return bool(result_type and result_type.base == "Thread" and (not self._thread_copy_source(expression)))

    def _is_thread_value(self, expression) -> bool:
        value_type = self.types.canonical_type(self.type_of(expression))
        return bool(value_type and value_type.base == "Thread")

    def _reject_fresh_thread_result(self, expression) -> bool:
        if expression is None or not self._is_fresh_thread_result(expression):
            return False
        self.session.error(self._FRESH_THREAD_RESULT_DIAGNOSTIC, expression.line, expression.col)
        return True

    def reject_thread_observation(self, expression) -> bool:
        if expression is None or not self._is_thread_value(expression):
            return False
        if isinstance(expression, Identifier):
            return False
        if self._reject_fresh_thread_result(expression):
            return True
        self.session.error(
            "Thread-producing expression must be a direct spawn() or Thread-returning call before it can be consumed",
            expression.line,
            expression.col,
        )
        return True

    def validate_thread_transfer_source(self, expression) -> None:
        if (
            not self._is_thread_value(expression)
            or isinstance(expression, Identifier)
            or self._is_fresh_thread_result(expression)
        ):
            return
        self.session.error(
            "Thread transfer must use one unique local owner or a direct fresh result", expression.line, expression.col
        )

    def validate_thread_expression_discard(self, expression) -> None:
        if (
            not self._is_thread_value(expression)
            or isinstance(expression, Identifier)
            or self._is_fresh_thread_result(expression)
        ):
            return
        self.session.error("Only a direct fresh Thread result can be discarded safely", expression.line, expression.col)

    def reject_thread_value_escape(self, expression, destination) -> bool:
        if not self._is_thread_value(expression):
            return False
        self.session.error(
            f"Thread handles cannot be {destination}; join or return the unique owner instead",
            expression.line,
            expression.col,
        )
        return True

    def validate_thread_join_receiver(self, expression) -> None:
        """Require a receiver whose unique handle is consumed exactly once."""
        callee = expression.callee
        receiver = callee.obj
        consumable = isinstance(receiver, (Identifier, SpawnExpr, CallExpr))
        if isinstance(receiver, TernaryExpr):
            consumable = not self._thread_copy_source(receiver)
        if callee.optional or not consumable:
            self.session.error(
                "Thread.join() receiver must be a unique local owner or a fresh Thread result",
                expression.line,
                expression.col,
            )


__all__ = [
    "AggregateAnalyzer",
    "InitializerAnalyzer",
    "InitializerArrayFieldCheck",
    "InitializerCompatibilityCheck",
    "InitializerPlan",
    "InitializerStringConversionCheck",
    "InitializerTypeContext",
    "InitializerTypeLayout",
    "InitializerValueCheck",
]
