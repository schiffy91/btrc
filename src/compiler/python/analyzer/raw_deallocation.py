"""Semantic boundary between raw C allocation APIs and managed ownership."""

from ..ast_nodes import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    StringLiteral,
    TernaryExpr,
    UnaryExpr,
)
from ..hosted_abi import (
    ALIAS_EXACT,
    RETURN_ALIAS,
    hosted_alias_argument_is_provably_null,
    hosted_consume_deallocator,
    hosted_function,
    hosted_raw_lifetime_arity,
    hosted_return_alias_shape,
    hosted_return_deallocator,
    hosted_return_effect,
)


class RawDeallocationContractsMixin:
    def _raw_lifetime_uses_static_string(self, expression) -> bool:
        if isinstance(expression, StringLiteral):
            return True
        if isinstance(expression, CastExpr):
            return self._raw_lifetime_uses_static_string(expression.expr)
        if isinstance(expression, UnaryExpr):
            return self._raw_lifetime_uses_static_string(expression.operand)
        if isinstance(expression, BinaryExpr):
            return self._raw_lifetime_uses_static_string(expression.left) or self._raw_lifetime_uses_static_string(
                expression.right
            )
        if isinstance(expression, TernaryExpr):
            return self._raw_lifetime_uses_static_string(expression.true_expr) or self._raw_lifetime_uses_static_string(
                expression.false_expr
            )
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self._raw_lifetime_uses_static_string(alias_argument)
        return False

    def _is_hosted_raw_lifetime_value(self, name: str) -> bool:
        if hosted_raw_lifetime_arity(name) is None:
            return False
        symbol = self.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self.declarations.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self._hosted_name_bypasses_source_definition(name)
        )

    def _validate_raw_lifetime_value(self, expression, direct_callee) -> bool:
        if direct_callee or not self._is_hosted_raw_lifetime_value(expression.name):
            return False
        self._error(
            f"Hosted lifetime function '{expression.name}' must be called "
            "directly and cannot be stored or forwarded as a value",
            expression.line,
            expression.col,
        )
        return True

    def _is_raw_lifetime_call(self, call) -> bool:
        callee = call.callee
        if not isinstance(callee, Identifier) or hosted_raw_lifetime_arity(callee.name) is None:
            return False
        symbol = self.scope.lookup(callee.name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self.declarations.function_table.get(callee.name)
        if declaration is not None:
            return declaration.body is None or self._hosted_call_bypasses_source_definition(call)
        return callee.name not in self.declarations.class_table and symbol is None

    def _validate_raw_lifetime_call(self, call) -> None:
        """Reject values whose lifetime is owned by a btrc runtime protocol."""
        name = call.callee.name
        expected = hosted_raw_lifetime_arity(name)
        if expected is None:
            return
        if len(call.args) != expected:
            self._error(
                f"'{name}()' expects {expected} argument(s) but got {len(call.args)}",
                call.line,
                call.col,
            )
            return
        if any(call.arg_names or ()):
            self._error(
                f"'{name}()' does not accept named arguments",
                call.line,
                call.col,
            )
            return

        argument = call.args[0]
        if self._raw_lifetime_uses_static_string(argument):
            self._error(
                f"{name}() cannot consume static string storage; "
                "only heap memory owned by a raw allocator may be consumed",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )
            return
        lifetime_source = argument
        while isinstance(lifetime_source, CastExpr):
            lifetime_source = lifetime_source.expr
        argument_type = self._opaque_managed_origin_type(argument)
        if argument_type is not None and not argument_type.is_array:
            if self._reject_managed_raw_deallocation(
                name,
                argument,
                argument_type,
                lifetime_source,
                call,
            ):
                return
        family = hosted_consume_deallocator(name)
        compatibility, producer = self._hosted_deallocator_compatibility(
            argument,
            family,
        )
        if compatibility is False:
            self._error(
                f"{name}() cannot consume storage returned by "
                f"{producer}() because it is not compatible with the "
                f"'{family}' deallocator family",
                getattr(argument, "line", call.line),
                getattr(argument, "col", call.col),
            )

    def _reject_managed_raw_deallocation(
        self,
        name,
        argument,
        argument_type,
        lifetime_source,
        call,
    ) -> bool:
        active_parameters = self._active_storage_type_parameters()
        unresolved_value = argument_type.base in active_parameters and argument_type.pointer_depth == 0
        managed_value = self._opaque_managed_type(argument_type) is not None
        runtime_handle = argument_type.base == "Thread" and argument_type.pointer_depth == 0
        if not (managed_value or runtime_handle or unresolved_value):
            return False
        indirect = (isinstance(lifetime_source, FieldAccessExpr) and self._is_property_projection(lifetime_source)) or (
            isinstance(lifetime_source, IndexExpr) and self._is_protocol_index_projection(lifetime_source)
        )
        if name != "free":
            guidance = "raw resizing is only valid for raw pointer buffers"
        elif indirect:
            guidance = "bind an owned direct local before managed destruction"
        elif runtime_handle:
            guidance = "join the Thread or let its owning scope clean it up"
        elif unresolved_value:
            guidance = "use a pointer-typed raw buffer or a managed ownership operation"
        elif argument_type.base == "string":
            guidance = "release the string or let its owning scope clean it up"
        elif argument_type.base == "Mutex":
            guidance = "call Mutex.destroy() or let its owning scope clean it up"
        else:
            guidance = "use 'delete' so the owning slot is cleared safely"
        self._error(
            f"{name}() cannot consume managed value of type '{self._format_type(argument_type)}'; {guidance}",
            getattr(argument, "line", call.line),
            getattr(argument, "col", call.col),
        )
        return True

    def _hosted_deallocator_compatibility(self, expression, family):
        while isinstance(expression, CastExpr):
            expression = expression.expr
        if isinstance(expression, UnaryExpr) and expression.op == "&":
            return False, "address-of storage"
        if isinstance(expression, TernaryExpr):
            return self._combined_deallocator_compatibility(
                (expression.true_expr, expression.false_expr),
                family,
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._combined_deallocator_compatibility(
                (expression.left, expression.right),
                family,
            )
        inferred = self._canonical_type(self._infer_type(expression))
        if (
            isinstance(expression, BinaryExpr)
            and expression.op in {"+", "-"}
            and inferred is not None
            and inferred.pointer_depth > 0
        ):
            return False, "pointer arithmetic"
        if inferred is not None and inferred.is_array:
            return False, "array storage"
        if not isinstance(expression, CallExpr) or not isinstance(
            expression.callee,
            Identifier,
        ):
            return None, "raw value"
        if not self._hosted_call_uses_owned_symbol(expression):
            return None, expression.callee.name
        name = expression.callee.name
        alias_is_null = hosted_alias_argument_is_provably_null(
            name,
            expression.args,
        )
        deallocator = hosted_return_deallocator(
            name,
            alias_argument_is_null=alias_is_null,
        )
        if deallocator is not None:
            return deallocator == family, name
        effect = hosted_return_effect(
            name,
            alias_argument_is_null=alias_is_null,
        )
        if effect != RETURN_ALIAS or hosted_return_alias_shape(name) != ALIAS_EXACT:
            return False, name
        spec = hosted_function(name)
        index = spec.return_alias_parameter if spec is not None else None
        if index is None or index >= len(expression.args):
            return False, name
        compatibility, producer = self._hosted_deallocator_compatibility(
            expression.args[index],
            family,
        )
        return compatibility, producer if compatibility is False else name

    def _combined_deallocator_compatibility(self, branches, family):
        results = [self._hosted_deallocator_compatibility(branch, family) for branch in branches]
        invalid = next((item for item in results if item[0] is False), None)
        if invalid is not None:
            return invalid
        if all(item[0] is True for item in results):
            return True, "conditional allocation"
        return None, "conditional raw value"


__all__ = ["RawDeallocationContractsMixin"]
