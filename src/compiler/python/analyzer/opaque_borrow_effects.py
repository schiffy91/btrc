"""Conservative source-call proof for borrow-only raw parameters."""

from dataclasses import fields, is_dataclass

from ..ast_nodes import (
    AssignExpr,
    CallExpr,
    LambdaExpr,
    NewExpr,
    ReturnStmt,
    SpawnExpr,
    UnaryExpr,
    VarDeclStmt,
)
from .opaque_borrow_effect_calls import OpaqueBorrowEffectCallsMixin
from .opaque_borrow_effect_expressions import OpaqueBorrowEffectExpressionsMixin
from .opaque_borrow_effect_walk import (
    raw_expression_mentions_parameter,
    raw_local_names,
    raw_statement_consumes_parameter,
)


class OpaqueBorrowEffectsMixin(
    OpaqueBorrowEffectCallsMixin,
    OpaqueBorrowEffectExpressionsMixin,
):
    def _raw_parameter_is_borrow_only(self, declaration, index) -> bool:
        cache = getattr(self, "_raw_borrow_effect_cache", None)
        if cache is None:
            cache = self._raw_borrow_effect_cache = {}
            self._raw_borrow_effect_visiting = set()
        provenance = getattr(declaration, "source_file", None)
        key = (id(declaration), index, provenance)
        if key in cache:
            return cache[key]
        if key in self._raw_borrow_effect_visiting:
            return False
        params = getattr(declaration, "params", ()) or ()
        body = getattr(declaration, "body", None)
        if body is None or index >= len(params):
            return False
        self._raw_borrow_effect_visiting.add(key)
        owner = self._raw_borrow_owner(declaration)
        local_names = raw_local_names(declaration)
        previous_file = self.current_source_file
        previous_locals = getattr(self, "_raw_borrow_proof_local_names", None)
        self.current_source_file = provenance
        self._raw_borrow_proof_local_names = local_names
        try:
            result = self._raw_parameter_uses_are_safe(
                body,
                params[index].name,
                owner,
                local_names,
            )
        finally:
            self.current_source_file = previous_file
            self._raw_borrow_proof_local_names = previous_locals
            self._raw_borrow_effect_visiting.remove(key)
        cache[key] = result
        return result

    def _raw_borrow_owner(self, declaration):
        owners = getattr(self, "_raw_borrow_owner_cache", None)
        if owners is None:
            owners = self._raw_borrow_owner_cache = {}
            for info in self.class_table.values():
                for name, method in info.methods.items():
                    declaring_name = info.method_owners.get(name, info.name)
                    declaring_info = self.class_table.get(declaring_name, info)
                    owners[id(method)] = declaring_info
                if info.constructor is not None:
                    owners[id(info.constructor)] = info
        return owners.get(id(declaration))

    def _raw_parameter_uses_are_safe(self, node, name, owner, local_names) -> bool:
        if node is None:
            return True
        if isinstance(node, VarDeclStmt):
            if self._raw_expression_carries_parameter(node.initializer, name):
                return False
        elif isinstance(node, AssignExpr):
            if raw_expression_mentions_parameter(
                node.target,
                name,
            ) or self._raw_expression_carries_parameter(node.value, name):
                return False
        elif isinstance(node, ReturnStmt):
            if self._raw_expression_carries_parameter(node.value, name):
                return False
        elif isinstance(node, (LambdaExpr, NewExpr, SpawnExpr)):
            if raw_expression_mentions_parameter(node, name):
                return False
        elif isinstance(node, UnaryExpr) and node.op in {"++", "--"}:
            if raw_expression_mentions_parameter(node.operand, name):
                return False
        elif raw_statement_consumes_parameter(node, name):
            return False
        elif isinstance(node, CallExpr):
            if not self._raw_parameter_call_is_safe(
                node,
                name,
                owner,
                local_names,
            ):
                return False

        if isinstance(node, (str, int, float, bool)):
            return True
        if isinstance(node, (list, tuple)):
            return all(
                self._raw_parameter_uses_are_safe(
                    item,
                    name,
                    owner,
                    local_names,
                )
                for item in node
            )
        if not is_dataclass(node):
            return True
        return all(
            self._raw_parameter_uses_are_safe(
                getattr(node, field.name),
                name,
                owner,
                local_names,
            )
            for field in fields(node)
            if field.name not in {"line", "col", "source_file"}
        )


__all__ = ["OpaqueBorrowEffectsMixin"]
