"""Structural planning for target-directed initializer analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..ast_nodes import (
    BraceInitializer,
    FieldDef,
    ListLiteral,
    MapLiteral,
    TypeExpr,
)
from ..type_composition import add_outer_pointer, strip_outer_storage
from .declarations.type_resolution import canonical_declaration_type

if TYPE_CHECKING:
    from .analysis_context import AnalysisContext
    from .declarations.registry import DeclarationRegistry


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

    def __init__(self, registry: DeclarationRegistry) -> None:
        self.registry = registry

    def canonical(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        return canonical_declaration_type(
            type_expr,
            self.registry.typedef_table,
        )

    def array_value(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        canonical = self.canonical(type_expr)
        if type_expr is None or canonical is None or type_expr.is_array or not canonical.is_array:
            return type_expr
        return add_outer_pointer(canonical, clear_array=True)

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
        return add_outer_pointer(canonical, clear_array=True)

    @staticmethod
    def array_element(type_expr: TypeExpr) -> TypeExpr:
        return strip_outer_storage(type_expr, array=True)

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

    def __init__(
        self,
        context: AnalysisContext,
        registry: DeclarationRegistry,
        types: InitializerTypeLayout,
    ) -> None:
        self.context = context
        self.registry = registry
        self.types = types

    def plan_typed(
        self,
        expected: TypeExpr,
        initializer: object,
        subject: str,
        line: int,
        col: int,
    ) -> InitializerPlan:
        """Plan full validation of a value against its declared type."""
        expected = self.types.array_value(expected)
        steps: list[InitializerStep] = [
            InitializerValueCheck(
                expected,
                initializer,
                subject,
                line,
                col,
                validate_fixed_array=True,
                contextualize_constructor=True,
            )
        ]
        contextual = self.plan_aggregate(
            expected,
            initializer,
            subject,
            line,
            col,
        )
        if not contextual.contextual:
            contextual = self.plan_collection(
                expected,
                initializer,
                subject,
                line,
                col,
            )
        steps.extend(contextual.steps)
        if not contextual.contextual:
            steps.append(
                InitializerCompatibilityCheck(
                    expected,
                    initializer,
                    subject,
                    line,
                    col,
                    reject_void=True,
                )
            )
        return InitializerPlan(contextual.contextual, tuple(steps))

    def plan_aggregate(
        self,
        expected: TypeExpr,
        initializer: object,
        subject: str,
        line: int,
        col: int,
    ) -> InitializerPlan:
        """Plan positional struct or tuple initializer contextualization."""
        if not isinstance(initializer, BraceInitializer):
            return InitializerPlan(False)
        canonical = self.types.canonical(expected)
        if canonical is None or canonical.pointer_depth > 0 or canonical.is_array:
            return InitializerPlan(False)

        steps: list[InitializerStep] = []
        struct_name = canonical.base.removeprefix("struct ")
        declaration = self.registry.struct_table.get(struct_name)
        if declaration is not None and not declaration.is_forward:
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
                f"{subject} has {len(initializer.elements)} initializer elements "
                f"but {aggregate_name} has {len(fields)} fields",
                line,
                col,
            )
        for element, (field_name, field_type) in zip(
            initializer.elements,
            fields,
        ):
            element_line = getattr(element, "line", line)
            element_col = getattr(element, "col", col)
            steps.append(
                InitializerStringConversionCheck(
                    field_type,
                    element,
                    "Implicit class-to-string conversion is not supported "
                    f"inside {aggregate_name}; prepare an owned string local "
                    f"for field '{field_name}' first",
                    element_line,
                    element_col,
                )
            )
            nested = self.plan_typed(
                field_type,
                element,
                f"Field '{field_name}'",
                element_line,
                element_col,
            )
            steps.extend(nested.steps)
        steps.append(InitializerTypeContext(initializer, expected))
        return InitializerPlan(True, tuple(steps))

    def plan_collection(
        self,
        expected: TypeExpr,
        initializer: object,
        subject: str,
        line: int,
        col: int,
    ) -> InitializerPlan:
        """Plan sequence or map literal contextualization."""
        element_types = None
        if isinstance(initializer, BraceInitializer):
            if expected.generic_args:
                element_types = expected.generic_args[:1]
            elif expected.is_array:
                element_types = [self.types.array_element(expected)]
        elif isinstance(initializer, ListLiteral):
            if expected.is_array:
                element_types = [self.types.array_element(expected)]
            elif expected.base in ("Vector", "List", "Array") and len(expected.generic_args) == 1:
                element_types = expected.generic_args
        elif isinstance(initializer, MapLiteral) and expected.base == "Map" and len(expected.generic_args) == 2:
            steps: list[InitializerStep] = []
            key_type, value_type = expected.generic_args
            for entry in initializer.entries:
                steps.extend(
                    self._plan_collection_element(
                        key_type,
                        entry.key,
                        f"{subject} key",
                        line,
                        col,
                    )
                )
                steps.extend(
                    self._plan_collection_element(
                        value_type,
                        entry.value,
                        f"{subject} value",
                        line,
                        col,
                    )
                )
            steps.append(InitializerTypeContext(initializer, expected))
            return InitializerPlan(True, tuple(steps))

        if element_types is None:
            return InitializerPlan(False)
        expected_element = element_types[0]
        steps = []
        for element in initializer.elements:
            if expected.is_array:
                steps.append(
                    InitializerStringConversionCheck(
                        expected_element,
                        element,
                        "Implicit class-to-string conversion is not supported "
                        "inside a shallow array initializer; prepare owned "
                        "string locals first",
                        getattr(element, "line", line),
                        getattr(element, "col", col),
                    )
                )
            steps.extend(
                self._plan_collection_element(
                    expected_element,
                    element,
                    subject,
                    line,
                    col,
                )
            )
        steps.append(InitializerTypeContext(initializer, expected))
        return InitializerPlan(True, tuple(steps))

    def _plan_collection_element(
        self,
        expected: TypeExpr,
        element: object,
        subject: str,
        line: int,
        col: int,
    ) -> list[InitializerStep]:
        element_line = getattr(element, "line", line)
        element_col = getattr(element, "col", col)
        steps: list[InitializerStep] = [
            InitializerValueCheck(
                expected,
                element,
                subject,
                element_line,
                element_col,
            )
        ]
        if isinstance(element, (BraceInitializer, ListLiteral, MapLiteral)):
            steps.extend(
                self.plan_typed(
                    expected,
                    element,
                    subject,
                    element_line,
                    element_col,
                ).steps
            )
        else:
            steps.append(
                InitializerCompatibilityCheck(
                    expected,
                    element,
                    subject,
                    element_line,
                    element_col,
                    element=True,
                )
            )
        return steps


__all__ = [
    "InitializerAnalyzer",
    "InitializerArrayFieldCheck",
    "InitializerCompatibilityCheck",
    "InitializerPlan",
    "InitializerStep",
    "InitializerStringConversionCheck",
    "InitializerTypeContext",
    "InitializerTypeLayout",
    "InitializerValueCheck",
]
