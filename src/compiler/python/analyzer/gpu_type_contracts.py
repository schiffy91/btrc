"""Resolution policy for calls that have a WGSL intrinsic spelling."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import CallExpr, Identifier
from ..gpu_builtins import WGSL_CALL_BUILTINS
from ..hosted_abi import hosted_owned_name
from ..source_provenance import is_compiler_stdlib_source

if TYPE_CHECKING:
    from .analysis_context import AnalysisContext
    from .core_models import Scope
    from .declarations.registry import DeclarationRegistry


class GpuIntrinsicResolver:
    """Own source-symbol versus WGSL-intrinsic call resolution."""

    def __init__(
        self,
        context: AnalysisContext,
        declarations: DeclarationRegistry,
    ) -> None:
        self._context = context
        self._declarations = declarations

    def call_uses_intrinsic(
        self,
        call: CallExpr,
        scope: Scope,
        *,
        in_gpu_function: bool,
    ) -> bool:
        """Whether a direct call resolves to the GPU intrinsic."""
        if not in_gpu_function or not isinstance(call.callee, Identifier):
            return False
        name = call.callee.name
        if name not in WGSL_CALL_BUILTINS:
            return False
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self._declarations.function_table.get(name)
        return declaration is None or self._hosted_call_uses_owned_symbol(name, scope)

    def call_resolves_to_source_symbol(
        self,
        call: CallExpr,
        scope: Scope,
        *,
        in_gpu_function: bool,
    ) -> bool:
        """Whether a WGSL-shaped call is owned by a source declaration."""
        return bool(
            isinstance(call.callee, Identifier)
            and call.callee.name in self._declarations.function_table
            and not self.call_uses_intrinsic(
                call,
                scope,
                in_gpu_function=in_gpu_function,
            )
        )

    def _hosted_call_uses_owned_symbol(self, name: str, scope: Scope) -> bool:
        if not hosted_owned_name(name):
            return False
        symbol = scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self._declarations.function_table.get(name)
        return bool(
            declaration is None or declaration.body is None or self._hosted_name_bypasses_source_definition(name)
        )

    def _hosted_name_bypasses_source_definition(self, name: str) -> bool:
        declaration = self._declarations.function_table.get(name)
        return bool(
            declaration is not None
            and declaration.body is not None
            and hosted_owned_name(name)
            and is_compiler_stdlib_source(self._context.current_source_file)
            and not is_compiler_stdlib_source(
                getattr(declaration, "source_file", None),
            )
        )


__all__ = ["GpuIntrinsicResolver"]
