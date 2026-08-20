"""Storage shape, qualification, and projection provenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.program import DeclarationIndex
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FieldDecl,
    Identifier,
    IndexExpr,
    PropertyDecl,
    SelfExpr,
    SuperExpr,
    TernaryExpr,
    TypeExpr,
    UnaryExpr,
)

if TYPE_CHECKING:
    from src.compiler.python.analyzer.aggregates import AggregateAnalyzer
    from src.compiler.python.analyzer.program import AnalysisSession


@dataclass(frozen=True)
class ProjectionStorageRoot:
    """The nearest managed or temporary-struct backing expression."""

    expression: object
    managed: bool


_IMPLICIT_RAW_POINTER_BASES = frozenset({"Mutex", "Thread", "string"})


class StorageModel:
    """Storage shape, qualification, and projection provenance."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        types: TypeSystem,
        aggregates: AggregateAnalyzer,
    ) -> None:
        self.session = session
        self.index = index
        self.aggregates = aggregates
        self.types = types

    def type_of(self, expression):
        """Read a type fact produced by ExpressionAnalyzer."""
        return self.session.node_types.get(id(expression))

    def is_property_projection(self, expression: FieldAccessExpr) -> bool:
        receiver_type = self.types.canonical_type(self.type_of(expression.obj))
        class_info = self.index.class_table.get(receiver_type.base) if receiver_type else None
        return bool(class_info is not None and expression.field in class_info.properties)

    def is_protocol_index_projection(self, expression: IndexExpr) -> bool:
        receiver_type = self.types.canonical_type(self.type_of(expression.obj))
        if receiver_type is None:
            return False
        if receiver_type.is_array or receiver_type.base == "string" or self.is_raw_pointer_value(receiver_type):
            return False
        return self.types.has_index_protocol(receiver_type)

    def is_virtual_projection(self, expression) -> bool:
        return (isinstance(expression, FieldAccessExpr) and self.is_property_projection(expression)) or (
            isinstance(expression, IndexExpr) and self.is_protocol_index_projection(expression)
        )

    def is_raw_pointer_value(self, type_expr) -> bool:
        type_expr = self.types.canonical_type(type_expr)
        active_type_param = bool(type_expr and type_expr.base in self.active_type_parameters())
        nominal_reference = bool(
            type_expr
            and (not active_type_param)
            and (type_expr.base in self.index.class_table or type_expr.base in self.index.interface_table)
        )
        return bool(
            type_expr
            and (type_expr.pointer_depth > 0 or type_expr.is_array)
            and (type_expr.is_array or not nominal_reference or type_expr.pointer_depth > 1)
        )

    def projection_embeds_storage(self, expression) -> bool:
        """Whether a field/index result retains its receiver's array storage."""
        canonical = self.types.canonical_type(self.aggregates.array_projection_storage_type(expression))
        return bool(canonical and canonical.is_array)

    def validate_mutex_volatile_initializer(self, expected, expression) -> None:
        self.validate_volatile_reference_conversion(
            expected, expression.args[0], "Mutex initializer", expression.line, expression.col
        )

    def validate_volatile_reference_conversion(self, target, value, subject, line=0, col=0) -> bool:
        """Reject implicit conversions that lose a nested volatile object.

        Top-level qualifiers disappear during ordinary lvalue conversion and
        are harmless.  A qualifier below a pointer/array layer is observable
        through the resulting alias and must also exist in the target shape.
        """
        if target is None or value is None:
            return True
        required = {depth for depth in self._expression_volatile_depths(value) if depth > 0}
        available = self.volatile_qualifier_depths(target, self.index.typedef_table)
        missing = sorted(required - set(available))
        if not missing:
            return True
        self.session.error(
            f"{subject} would discard volatile storage qualification at pointer depth {missing[0]}; use a typedef that preserves the qualified pointee instead of unsupported layered pointer qualifiers",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )
        return False

    def _expression_volatile_depths(self, expression) -> frozenset[int]:
        if expression is None:
            return frozenset()
        if isinstance(expression, Identifier):
            symbol = self.session.scope.lookup(expression.name)
            declared = symbol.type if symbol is not None else None
            return self.volatile_qualifier_depths(declared or self.type_of(expression), self.index.typedef_table)
        if isinstance(expression, FieldAccessExpr):
            return self.volatile_qualifier_depths(self.declared_projection_type(expression), self.index.typedef_table)
        if isinstance(expression, IndexExpr):
            if not self._raw_index_removes_storage_layer(expression):
                return self.volatile_qualifier_depths(
                    self.declared_projection_type(expression),
                    self.index.typedef_table,
                )
            return self._remove_volatile_storage_layer(self._expression_volatile_depths(expression.obj))
        if isinstance(expression, UnaryExpr):
            overloaded = self.types.operator_return_type(self.type_of(expression.operand), expression.op, unary=True)
            if overloaded is not None:
                return self.volatile_qualifier_depths(overloaded, self.index.typedef_table)
            depths = self._expression_volatile_depths(expression.operand)
            if expression.op == "&":
                return frozenset(depth + 1 for depth in depths)
            if expression.op == "*":
                return self._remove_volatile_storage_layer(depths)
            if expression.op == "!":
                return frozenset()
            return depths
        if isinstance(expression, CastExpr):
            return self.volatile_qualifier_depths(expression.target_type, self.index.typedef_table)
        if isinstance(expression, TernaryExpr):
            return self._expression_volatile_depths(expression.true_expr) | self._expression_volatile_depths(
                expression.false_expr
            )
        if isinstance(expression, AssignExpr):
            return frozenset(depth for depth in self._expression_volatile_depths(expression.target) if depth > 0)
        if isinstance(expression, BinaryExpr):
            overloaded = self.types.operator_return_type(self.type_of(expression.left), expression.op)
            if overloaded is not None:
                return self.volatile_qualifier_depths(overloaded, self.index.typedef_table)
            if expression.op == "??":
                return self._expression_volatile_depths(expression.left) | self._expression_volatile_depths(
                    expression.right
                )
            if expression.op in {"+", "-"}:
                return self.volatile_qualifier_depths(self.type_of(expression), self.index.typedef_table)
            return frozenset()
        if isinstance(expression, CallExpr):
            declared = self._declared_call_result_type(expression)
            return self.volatile_qualifier_depths(declared or self.type_of(expression), self.index.typedef_table)
        return self.volatile_qualifier_depths(self.type_of(expression), self.index.typedef_table)

    def _raw_index_removes_storage_layer(self, expression) -> bool:
        object_type = self.types.canonical_type(self.type_of(expression.obj))
        if object_type is None:
            return False
        if object_type.is_array:
            return True
        if object_type.pointer_depth <= 0:
            return False
        return bool(
            object_type.base in self.active_type_parameters()
            or object_type.base not in self.index.class_table
            or object_type.pointer_depth > 1
        )

    def declared_projection_type(self, expression):
        return self.type_of(expression)

    def _declared_call_result_type(self, expression):
        return self.type_of(expression)

    @staticmethod
    def _remove_volatile_storage_layer(depths) -> frozenset[int]:
        return frozenset(depth - 1 for depth in depths if depth > 0)

    def _reference_shapes_compatible(self, target, source) -> bool:
        return bool(
            self.types.semantic_pointer_depth(target) == self.types.semantic_pointer_depth(source)
            and target.is_array == source.is_array
            and self._const_conversion_allowed(target, source)
            and self.types.generic_args_equal(target, source)
        )

    def _const_conversion_allowed(self, target, source) -> bool:
        """Whether an implicit conversion preserves pointee constness.

        ``is_const`` qualifies the base type, so it is an object qualifier for
        scalars and a pointee qualifier once one indirection is present. C's
        safe one-level qualification addition is allowed; removing const or
        changing a deeper pointee qualification requires an explicit cast.
        """
        target_depth = self._qualifier_indirection_depth(target)
        source_depth = self._qualifier_indirection_depth(source)
        if target_depth == 0 or source_depth == 0:
            return True
        if source.is_const and (not target.is_const):
            return False
        if target_depth > 1 or source_depth > 1:
            return target.is_const == source.is_const
        return True

    def _qualifier_indirection_depth(self, type_expr) -> int:
        depth = self.types.semantic_pointer_depth(type_expr) + int(type_expr.is_array)
        if type_expr.base == "string" and depth == 0:
            return 1
        return depth

    def active_type_parameters(self):
        active = set(self.session.current_class.generic_params if self.session.current_class else ())
        if self.session.current_method:
            active.update(self.session.current_method.generic_params)
        return active

    @staticmethod
    def instance_storage_name(member) -> str | None:
        """Return the emitted C member name, or None for non-storage members."""
        if isinstance(member, FieldDecl):
            return member.name if member.access != "class" else None
        if isinstance(member, PropertyDecl):
            if member.access == "class" or not StorageModel.property_needs_backing(member):
                return None
            return f"_prop_{member.name}"
        return None

    @staticmethod
    def property_needs_backing(property_decl: PropertyDecl) -> bool:
        return bool(
            (property_decl.has_getter and property_decl.getter_body is None)
            or (property_decl.has_setter and property_decl.setter_body is None)
        )

    @staticmethod
    def custom_property_getter(class_table, receiver_type, field: str) -> bool:
        """Whether a field-shaped read dispatches user-defined getter code."""
        if receiver_type is None:
            return False
        class_info = class_table.get(receiver_type.base)
        property_decl = class_info.properties.get(field) if class_info else None
        return bool(property_decl is not None and property_decl.getter_body is not None)

    def is_managed_value_type(self, type_expr) -> bool:
        """Whether a value has compiler-managed reference storage."""
        canonical = self.types.canonical_type(type_expr)
        active_type_param = bool(canonical and canonical.base in self.active_type_parameters())
        return bool(
            canonical
            and (not canonical.is_array)
            and canonical.pointer_depth <= 1
            and (
                canonical.base in {"string", "Mutex"}
                or (not active_type_param and canonical.base in self.index.class_table)
            )
        )

    def projection_storage_root(self, projection, *, direct: bool = False):
        """Find the nearest storage root of one unconditional projection leaf."""
        if direct:
            projection_type = self.type_of(projection)
            if (
                projection_type is not None
                and self.is_managed_value_type(projection_type)
                and (not isinstance(projection, (SelfExpr, SuperExpr)))
            ):
                return ProjectionStorageRoot(expression=projection, managed=True)
            return None
        if isinstance(projection, CastExpr):
            return self.projection_storage_root(projection.expr)
        if isinstance(projection, UnaryExpr) and projection.op == "*":
            return self.projection_storage_root(projection.operand)
        if isinstance(projection, BinaryExpr) and projection.op in {"+", "-"}:
            candidates = (projection.left, projection.right) if projection.op == "+" else (projection.left,)
            for candidate in candidates:
                candidate_type = self.type_of(candidate)
                if (
                    candidate_type
                    and (not self.is_managed_value_type(candidate_type))
                    and (
                        candidate_type.is_array
                        or candidate_type.pointer_depth > 0
                        or candidate_type.base in {"intptr_t", "uintptr_t"}
                    )
                ):
                    return self.projection_storage_root(candidate)
            return None
        if not isinstance(projection, (FieldAccessExpr, IndexExpr)):
            return None
        receiver = projection.obj
        receiver_type = self.type_of(receiver)
        if (
            receiver_type is not None
            and self.is_managed_value_type(receiver_type)
            and (not isinstance(receiver, (SelfExpr, SuperExpr)))
        ):
            return ProjectionStorageRoot(expression=receiver, managed=True)
        if (
            isinstance(receiver, CallExpr)
            and receiver_type is not None
            and (receiver_type.pointer_depth == 0)
            and (not receiver_type.is_array)
            and (receiver_type.base.removeprefix("struct ") in self.index.struct_table)
        ):
            return ProjectionStorageRoot(expression=receiver, managed=False)
        return self.projection_storage_root(receiver)

    @staticmethod
    def volatile_qualifier_depths(
        type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr], seen: frozenset[str] = frozenset()
    ) -> frozenset[int]:
        """Return every storage depth carrying ``volatile``.

        btrc's explicit ``volatile`` qualifies the represented storage object (or
        each element of an array).  A qualifier inherited from a typedef is shifted
        below any pointer/array shell added at the use site.
        """
        if type_expr is None:
            return frozenset()
        depths: set[int] = set()
        if type_expr.is_volatile:
            depths.add(1 if type_expr.is_array else 0)
        target = StorageModel._typedef_target(type_expr, typedefs, seen)
        if target is not None:
            shift = StorageModel._applied_storage_layers(type_expr, target)
            depths.update(
                depth + shift
                for depth in StorageModel.volatile_qualifier_depths(target, typedefs, seen | {type_expr.base})
            )
        return frozenset(depths)

    @staticmethod
    def const_qualifier_depths(
        type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr], seen: frozenset[str] = frozenset()
    ) -> frozenset[int]:
        """Return every storage depth carrying ``const`` under C declarators."""
        if type_expr is None:
            return frozenset()
        target = StorageModel._typedef_target(type_expr, typedefs, seen)
        shift = StorageModel._applied_storage_layers(type_expr, target)
        depths: set[int] = set()
        if type_expr.is_const:
            implicit = int(target is None and type_expr.base in _IMPLICIT_RAW_POINTER_BASES)
            depths.add(shift + implicit)
        if target is not None:
            depths.update(
                depth + shift
                for depth in StorageModel.const_qualifier_depths(target, typedefs, seen | {type_expr.base})
            )
        return frozenset(depths)

    @staticmethod
    def effective_outer_volatile(
        type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr], seen: frozenset[str] = frozenset()
    ) -> bool:
        """Whether this declarator's represented storage is volatile.

        An array declaration represents its elements, so it inherits volatility
        from an element alias.  A pointer shell is the boundary that makes the
        inherited qualifier belong to a pointee instead (``V*`` is not itself
        volatile when ``V`` aliases ``volatile int``).
        """
        if type_expr is None:
            return False
        if type_expr.is_volatile:
            return True
        target = StorageModel._typedef_target(type_expr, typedefs, seen)
        if target is None or StorageModel._applied_pointer_layers(type_expr, target) > 0:
            return False
        return StorageModel.effective_outer_volatile(target, typedefs, seen | {type_expr.base})

    @staticmethod
    def effective_outer_const(type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr]) -> bool:
        """Whether the declared object itself is effectively const."""
        return 0 in StorageModel.const_qualifier_depths(type_expr, typedefs)

    @staticmethod
    def strip_outer_storage_through_typedef(
        type_expr: TypeExpr | None, typedefs: dict[str, TypeExpr], seen: frozenset[str] = frozenset()
    ) -> TypeExpr | None:
        """Remove one pointer/array layer without flattening its inner alias."""
        if type_expr is None:
            return None
        if type_expr.is_array:
            return TypeSystem.strip_outer_storage(type_expr, array=True)
        if type_expr.pointer_depth > 0:
            return TypeSystem.strip_outer_storage(type_expr)
        target = StorageModel._typedef_target(type_expr, typedefs, seen)
        if target is None:
            return None
        return StorageModel.strip_outer_storage_through_typedef(target, typedefs, seen | {type_expr.base})

    @staticmethod
    def _typedef_target(type_expr: TypeExpr, typedefs: dict[str, TypeExpr], seen: frozenset[str]) -> TypeExpr | None:
        if type_expr.generic_args or type_expr.base in seen:
            return None
        return typedefs.get(type_expr.base)

    @staticmethod
    def _applied_storage_layers(type_expr: TypeExpr, target: TypeExpr | None) -> int:
        reference_shape = TypeSystem.resolved_reference_shape(target) if target is not None else False
        pointer_depth = type_expr.pointer_depth - int(
            TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=reference_shape)
        )
        return pointer_depth + int(type_expr.is_array)

    @staticmethod
    def _applied_pointer_layers(type_expr: TypeExpr, target: TypeExpr | None) -> int:
        reference_shape = TypeSystem.resolved_reference_shape(target) if target is not None else False
        return type_expr.pointer_depth - int(
            TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=reference_shape)
        )


__all__ = ["ProjectionStorageRoot", "StorageModel"]
