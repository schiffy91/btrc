"""Owned-value classification and sequencing for IR lowering."""

from __future__ import annotations

from ...ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    TernaryExpr,
    UnaryExpr,
)
from ...index_protocol import indexed_protocol_info
from .call_boundary import CallOperand
from .evaluation_order import borrowed_value_can_be_pinned
from .lowering_context import LoweringContext
from .types import is_generic_class_type, mangle_generic_type, type_to_c


class OwnershipLowerer:
    """Classify and sequence managed values for one lowering run."""

    def __init__(
        self,
        context: LoweringContext,
        types,
        order,
        lifetime,
        boundaries,
        expressions,
    ) -> None:
        self.context = context
        self.types = types
        from .ownership_effects import OwnershipEffectResolver

        self.effects = OwnershipEffectResolver(context, types, self)
        self.order = order
        self.lifetime = lifetime
        self.boundaries = boundaries
        self.expressions = expressions

    def owns_result(self, expression) -> bool:
        """Whether evaluating ``expression`` produces caller-owned +1."""
        if isinstance(expression, NewExpr):
            return self.types.is_managed(self.context.type_of(expression))
        if isinstance(expression, (BraceInitializer, ListLiteral, MapLiteral)):
            result_type = self.context.type_of(expression)
            return bool(result_type and result_type.base in self.context.analyzed.class_table)
        if isinstance(expression, CastExpr):
            return self.types.is_managed(self.context.type_of(expression)) and self.owns_result(expression.expr)
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            return self._assignment_owns_result(expression)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            result_type = self.context.type_of(expression)
            custom_getter = self._custom_getter(expression)
            return bool(
                self.types.is_managed(result_type)
                and (self.projection_is_owned_call(expression) or custom_getter or self.owns_result(expression.obj))
            )
        if isinstance(expression, TernaryExpr):
            return self._conditional_result_is_owned(
                expression,
                (expression.true_expr, expression.false_expr),
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._conditional_result_is_owned(
                expression,
                (expression.left, expression.right),
            )
        if isinstance(expression, BinaryExpr):
            result_type = self.context.type_of(expression)
            if self._is_string_concat(expression, result_type):
                return True
            return self._overloaded_result_is_owned(
                expression,
                expression.left,
                expression.op,
            )
        if isinstance(expression, UnaryExpr):
            return self._overloaded_result_is_owned(
                expression,
                expression.operand,
                expression.op,
                unary=True,
            )
        if not isinstance(expression, CallExpr):
            return False
        result_type = self.context.type_of(expression)
        if not self.types.is_managed(result_type):
            return False
        if self.types.is_string(result_type):
            return self._string_call_owns_result(expression)
        return self.effects.call_returns_owned(expression)

    def managed_type_name(self, type_expr) -> str:
        """Return the concrete destructor prefix for a managed source type."""
        from .managed_values import MUTEX_RUNTIME_NAME

        if self.types.is_mutex(type_expr):
            return MUTEX_RUNTIME_NAME
        if is_generic_class_type(type_expr, self.context.analyzed.class_table):
            return mangle_generic_type(type_expr.base, type_expr.generic_args)
        return type_expr.base

    def receiver_pin_required(
        self,
        receiver,
        *,
        declared_call: bool,
        later_effect: bool = False,
    ) -> bool:
        """Whether a borrowed receiver needs a call-scoped owning guard."""
        if receiver is None or not borrowed_value_can_be_pinned(receiver):
            return False
        if (
            isinstance(receiver, Identifier)
            and self.context.managed_local_type(receiver.name) is not None
            and not later_effect
        ):
            return False
        if declared_call or later_effect:
            return True
        return self.types.is_mutex(self.context.type_of(receiver))

    def normalize_branch(self, expression, lowered):
        """Promote a selected borrowed branch when its conditional yields +1."""
        if isinstance(expression, NullLiteral) or self.owns_result(expression):
            return lowered
        type_expr = self.context.type_of(expression)
        if not self.types.is_managed(type_expr):
            return lowered

        from ..nodes import CType, IRBinOp, IRCommaExpr, IRStmtExpr, IRVar, IRVarDecl
        from .types import type_to_c

        declaration = IRVarDecl(
            c_type=CType(text=type_to_c(type_expr)),
            name=self.context.fresh_temp("__btrc_promoted_branch"),
        )
        self.context.record_declaration(declaration)
        value = IRVar(name=declaration.name)
        return IRStmtExpr(
            stmts=[declaration],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=value, op="=", right=lowered),
                    self.lifetime.retain_value(value, type_expr),
                    value,
                ]
            ),
        )

    def projection_is_owned_call(self, expression) -> bool:
        """Whether a projection invokes a managed-return source callable."""
        receiver_type = self.context.type_of(expression.obj)
        if receiver_type is None:
            return False
        if isinstance(expression, IndexExpr):
            return (
                indexed_protocol_info(
                    receiver_type,
                    self.context.analyzed.class_table,
                    method="get",
                )
                is not None
            )
        return bool(self._custom_getter(expression))

    def sequence_operands(
        self,
        nodes,
        *,
        build,
        result_type,
        promote_result: bool = False,
        result_owned: bool = False,
        keep_nodes=(),
        pin_nodes=(),
        force: bool = False,
        allow_trailing_opaque: bool = False,
        opaque_context: str = "expression",
        prepared_values=None,
    ):
        """Evaluate eager source operands once and stabilize managed values."""
        if self.context.is_unevaluated:
            return None
        specs = self._owned_operand_specs(
            nodes,
            keep_nodes,
            pin_nodes,
            prepared_values or {},
        )
        automatic_pins = self.order.source_order_pin_flags(
            nodes,
            [type_expr for _node, type_expr, *_rest in specs],
            [owned for _node, _type_expr, owned, *_rest in specs],
        )
        specs = [
            (node, type_expr, owned, keep, pin or automatic_pins[index], prepared)
            for index, (node, type_expr, owned, keep, pin, prepared) in enumerate(specs)
        ]
        lifetime_required = any(owned or keep or pin for _node, _type, owned, keep, pin, _prepared in specs)
        if not (force or lifetime_required):
            return None
        self._validate_operand_types(
            specs,
            lifetime_required,
            allow_trailing_opaque,
            opaque_context,
        )
        spec_types = {id(node): type_expr for node, type_expr, *_rest in specs}

        def lower_with_overrides(node, overrides):
            types = {key: spec_types[key] for key in overrides if key in spec_types}
            with self.context.operand_scope(overrides, types):
                return self.expressions.lower_expression(node)

        operands = [
            CallOperand(
                node=node,
                type_expr=type_expr,
                c_type=self.order.operand_c_type(
                    node,
                    type_expr,
                    render=type_to_c,
                ),
                keep=keep,
                pin=pin,
                owned=owned,
                lowered=prepared.value if prepared is not None else None,
                lower_with_overrides=(
                    None
                    if prepared is not None
                    else lambda overrides, node=node: lower_with_overrides(
                        node,
                        overrides,
                    )
                ),
            )
            for node, type_expr, owned, keep, pin, prepared in specs
        ]

        def build_with_overrides(overrides):
            types = {id(node): type_expr for node, type_expr, _owned, _keep, _pin, _prepared in specs}
            with self.context.operand_scope(overrides, types):
                return build()

        return self.boundaries.sequence(
            operands,
            lower_expr=self.expressions.lower_expression,
            build_call=build_with_overrides,
            result_c_type=(type_to_c(result_type) if result_type is not None else None),
            result_type=result_type,
            promote_result=promote_result,
            result_owned=bool(result_owned or promote_result),
        )

    def _assignment_owns_result(self, expression: AssignExpr) -> bool:
        result_type = self.context.type_of(expression)
        target = expression.target
        rhs_owned = self.effects.virtual_assignment_owns(
            target,
            expression.value,
        )
        return bool(
            self.types.is_managed(result_type)
            and (
                (
                    isinstance(target, (FieldAccessExpr, IndexExpr))
                    and (self.owns_result(target.obj) or self.effects.assignment_pins_borrowed_target(target))
                )
                or (expression.op == "=" and rhs_owned)
            )
        )

    def _owned_operand_specs(self, nodes, keep_nodes, pin_nodes, prepared_values):
        keep_ids = {id(node) for node in keep_nodes}
        pin_ids = {id(node) for node in pin_nodes}
        specs = []
        for node in nodes:
            prepared = prepared_values.get(id(node))
            type_expr = prepared.effective_type if prepared is not None else self.context.type_of(node)
            owned = bool(
                prepared.owned
                if prepared is not None
                else id(node) not in self.context.owning_overrides and self.owns_result(node)
            )
            keep = id(node) in keep_ids
            pin = bool(id(node) in pin_ids and not owned and borrowed_value_can_be_pinned(node))
            specs.append((node, type_expr, owned, keep, pin, prepared))
        return specs

    @staticmethod
    def _validate_operand_types(
        specs,
        lifetime_required,
        allow_trailing_opaque,
        opaque_context,
    ) -> None:
        missing = [index for index, spec in enumerate(specs) if spec[1] is None]
        if not missing:
            return
        trailing = len(specs) - 1
        if allow_trailing_opaque and missing == [trailing] and trailing > 0:
            node, _type_expr, owned, keep, pin, _prepared = specs[-1]
            if not (owned or keep or pin):
                specs.pop()
                return
            from .evaluation_order import reject_opaque_ordering

            reject_opaque_ordering(node, opaque_context)
            return
        if allow_trailing_opaque:
            from .evaluation_order import reject_opaque_ordering

            reject_opaque_ordering(specs[missing[0]][0], opaque_context)
        elif lifetime_required:
            from .errors import CodegenError

            raise CodegenError("owned expression sequencing requires concrete analyzed operand types")

    def _conditional_result_is_owned(self, expression, branches) -> bool:
        result_type = self.context.type_of(expression)
        return bool(
            self.types.is_managed(result_type)
            and any(self.owns_result(branch) for branch in branches)
            and all(self._promotable_branch(branch) for branch in branches)
        )

    def _promotable_branch(self, expression) -> bool:
        return bool(
            isinstance(expression, NullLiteral)
            or self.owns_result(expression)
            or self.types.is_managed(self.context.type_of(expression))
        )

    def _is_string_concat(self, expression: BinaryExpr, result_type) -> bool:
        if expression.op != "+" or not self.types.is_string(result_type):
            return False
        return self.types.is_string(self.context.type_of(expression.left)) and self.types.is_string(
            self.context.type_of(expression.right)
        )

    def _string_call_owns_result(self, expression: CallExpr) -> bool:
        if self.effects.call_returns_owned(expression):
            return True
        callee = expression.callee
        if isinstance(callee, Identifier):
            return callee.name in {
                "__btrc_str_track",
                "__btrc_string_adopt",
                "__btrc_string_alloc",
            }
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver_type = self.context.type_of(callee.obj)
        if self.types.is_string(receiver_type):
            from ...string_methods import STRING_METHODS

            method = STRING_METHODS.get(callee.field)
            return bool(method and method.tracked)
        if callee.field != "toString" or receiver_type is None:
            return False
        return bool(
            receiver_type.base != "bool"
            and receiver_type.base not in self.context.analyzed.enum_table
            and receiver_type.base not in self.context.analyzed.rich_enum_table
        )

    def _custom_getter(self, expression):
        if not isinstance(expression, FieldAccessExpr):
            return None
        from ...class_storage import custom_property_getter

        return custom_property_getter(
            self.context.analyzed.class_table,
            self.context.type_of(expression.obj),
            expression.field,
        )

    def _overloaded_result_is_owned(
        self,
        expression,
        operand,
        operator: str,
        *,
        unary: bool = False,
    ) -> bool:
        result_type = self.context.type_of(expression)
        expression_type = self.context.type_of(operand)
        if expression_type is None:
            return False
        class_info = self.context.analyzed.class_table.get(expression_type.base)
        magic = {
            "+": "__add__",
            "-": "__sub__",
            "*": "__mul__",
            "/": "__div__",
            "%": "__mod__",
        }.get(operator)
        if unary:
            magic = "__neg__" if operator == "-" else None
        return bool(
            result_type is not None
            and result_type.base in self.context.analyzed.class_table
            and class_info is not None
            and magic in class_info.methods
        )


__all__ = ["OwnershipLowerer"]
