"""Checked arithmetic and indexing for host-visible GPU failures."""

from __future__ import annotations

from ...ast_nodes import Identifier, IndexExpr
from ...gpu_errors import (
    GPU_STATUS_BOUNDS,
    GPU_STATUS_DIV_OVERFLOW,
    GPU_STATUS_DIV_ZERO,
    GPU_STATUS_MOD_ZERO,
)
from .errors import CodegenError


class WgslChecksMixin:
    def _checked_index_expr(self, expression: IndexExpr) -> str:
        if not isinstance(expression.obj, Identifier):
            raise CodegenError("WGSL checked indexing requires an array parameter")
        source_name = expression.obj.name
        return self._checked_array_access(
            source_name,
            self._expr(expression.index),
        )

    def _checked_array_access(self, source_name: str, index: str) -> str:
        length_field = self._array_lengths.get(source_name)
        if length_field is None:
            raise CodegenError(f"WGSL array '{source_name}' has no length metadata")
        array = self._identifier(source_name)
        index_name = self._fresh_value_name()
        valid_name = self._fresh_value_name()
        safe_name = self._fresh_value_name()
        self._line(f"let {index_name}: i32 = {index};")
        self._line(f"let {valid_name}: bool = ({index_name} >= 0 && {index_name} < uniforms.{length_field});")
        self._line(f"if (!{valid_name}) {{")
        self._indent += 1
        self._signal_status(GPU_STATUS_BOUNDS)
        self._indent -= 1
        self._line("}")
        self._line(f"let {safe_name}: i32 = select(0, {index_name}, {valid_name});")
        return f"{array}[{safe_name}]"

    def _checked_divmod_expr(
        self,
        operator: str,
        left: str,
        right: str,
        result_base: str,
    ) -> str:
        wgsl_type = "f32" if result_base == "float" else "i32"
        zero = "0.0" if result_base == "float" else "0"
        left_name = self._fresh_value_name()
        right_name = self._fresh_value_name()
        result_name = self._fresh_value_name()
        self._line(f"let {left_name}: {wgsl_type} = {left};")
        self._line(f"let {right_name}: {wgsl_type} = {right};")
        self._line(f"var {result_name}: {wgsl_type} = {zero};")
        self._line(f"if ({right_name} == {zero}) {{")
        self._indent += 1
        self._signal_status(GPU_STATUS_DIV_ZERO if operator == "/" else GPU_STATUS_MOD_ZERO)
        self._indent -= 1
        if result_base == "int":
            self._line(f"}} else if ({left_name} == -2147483648 && {right_name} == -1) {{")
            self._indent += 1
            if operator == "/":
                self._signal_status(GPU_STATUS_DIV_OVERFLOW)
            else:
                self._line(f"{result_name} = 0;")
            self._indent -= 1
        self._line("} else {")
        self._indent += 1
        self._line(f"{result_name} = {left_name} {operator} {right_name};")
        self._indent -= 1
        self._line("}")
        return result_name

    def _signal_status(self, code: int) -> None:
        self._line(f"_ = atomicMax(&btrc_status.code, {code}u);")
