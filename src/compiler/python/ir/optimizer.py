"""Public entry point for IR dead-code elimination."""

from __future__ import annotations

from .cycle_boundaries import install_program_cycle_boundary
from .nodes import IRInclude, IRModule
from .optimizer_functions import eliminate_dead_functions as _eliminate_dead_functions
from .optimizer_globals import eliminate_dead_globals as _eliminate_dead_globals
from .optimizer_gpu import eliminate_dead_gpu_kernels as _eliminate_dead_gpu_kernels
from .optimizer_helpers import eliminate_dead_helpers as _eliminate_dead_helpers
from .optimizer_types import eliminate_dead_externs as _eliminate_dead_externs
from .optimizer_types import eliminate_dead_type_declarations as _eliminate_dead_type_declarations
from .parameter_usage import consume_unused_parameters as _consume_unused_parameters


def optimize(module: IRModule, *, dce: bool = True) -> IRModule:
    """Run every dead-code-elimination pass on ``module`` in dependency order.

    ``dce=False`` preserves the uneliminated module for reproducible ``--no-dce``
    output and archive partitioning. The module is mutated in place and returned,
    matching the original optimizer API.
    """
    module.validate_declarations()
    if dce:
        _eliminate_dead_globals(module)
        _eliminate_dead_functions(module)
    if install_program_cycle_boundary(module):
        _materialize_cycle_boundary_helpers(module)
    if dce:
        _eliminate_dead_gpu_kernels(module)
        _eliminate_dead_helpers(module)
        _eliminate_dead_externs(module)
        _eliminate_dead_type_declarations(module)
    _consume_unused_parameters(module)
    module.refresh_type_declarations()
    from .runtime_dependencies import refresh_runtime_dependencies

    refresh_runtime_dependencies(module)
    return module


def _materialize_cycle_boundary_helpers(module: IRModule) -> None:
    """Merge helper closure introduced after initial IR helper collection."""

    from .gen.helpers import helper_decls_for_roots

    existing = {helper.name for helper in module.helper_decls}
    boundary = helper_decls_for_roots({"__btrc_flush_cycles"})
    missing = [helper for helper in boundary if helper.name not in existing]
    module.helper_decls.extend(missing)
    if module.freestanding:
        return
    for helper in missing:
        for header in helper.required_headers:
            include = IRInclude(header=header)
            if include not in module.preprocessor_decls:
                module.preprocessor_decls.append(include)


__all__ = ["optimize"]
