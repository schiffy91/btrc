"""Composition root for structured IR optimization."""

from __future__ import annotations

from .cycle_boundaries import FunctionCycleBoundary
from .module import IRModule
from .parameter_usage import UnusedParameterConsumer
from .reachability import (
    DeclarationReachability,
    ProgramReachability,
    RuntimeSupportReachability,
)
from .runtime_dependencies import RuntimeDependencyMaterializer
from .top_nodes import IRInclude


class IROptimizer:
    """Own the ordered optimization cascade for one mutable IR module."""

    def __init__(self, module: IRModule, *, dce: bool = True):
        self._module = module
        self._dce = dce

    def optimize(self) -> IRModule:
        """Apply all enabled passes and return the optimized module."""

        self._module.validate_declarations()
        if self._dce:
            ProgramReachability(self._module).prune()
        if self._install_program_cycle_boundary():
            self._materialize_cycle_boundary_helpers()
        if self._dce:
            RuntimeSupportReachability(self._module).prune()
            DeclarationReachability(self._module).prune()
        UnusedParameterConsumer(self._module).normalize()
        self._module.refresh_type_declarations()
        RuntimeDependencyMaterializer(self._module).refresh()
        return self._module

    def _install_program_cycle_boundary(self) -> bool:
        """Drain suspects before live executable entry points return."""

        boundaries = [FunctionCycleBoundary(function) for function in self._module.function_defs]
        if not any(boundary.has_cyclable_release for boundary in boundaries):
            return False
        installed = False
        for boundary in boundaries:
            if boundary.is_program_entry:
                installed = boundary.install(force=True) or installed
        return installed

    def _materialize_cycle_boundary_helpers(self) -> None:
        """Merge helper closure introduced after initial helper collection."""

        from .gen.helpers import RuntimeHelperRegistry

        existing = {helper.name for helper in self._module.helper_decls}
        boundary = RuntimeHelperRegistry().declarations_for({"__btrc_flush_cycles"})
        missing = [helper for helper in boundary if helper.name not in existing]
        self._module.helper_decls.extend(missing)
        if self._module.freestanding:
            return
        for helper in missing:
            for header in helper.required_headers:
                include = IRInclude(header=header)
                if include not in self._module.preprocessor_decls:
                    self._module.preprocessor_decls.append(include)


__all__ = ["IROptimizer"]
