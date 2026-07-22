"""ARC cleanup for caller-owned GPU buffer arguments."""

from .call_boundary_cleanup import register_temporary, release_and_clear
from .managed_values import retain_value


def argument_lifetime_cleanup(
    gen,
    host,
    declaration,
    stable,
    type_expr,
    c_type,
    *,
    pin,
):
    """Protect an owned or pinned collection through dispatch."""

    declarations = []
    prefix = [retain_value(gen, stable, type_expr)] if pin else []
    register_temporary(
        gen,
        declaration,
        type_expr,
        declarations,
        prefix,
        gen.fresh_temp,
        host.cleanup_active(),
        "__btrc_gpu_arg_cleanup",
        host.activate_cleanup,
    )
    suffix = release_and_clear(
        gen,
        stable,
        type_expr,
        declarations,
        gen.fresh_temp,
        host.record_declaration,
        c_type,
    )
    return declarations, prefix, suffix


__all__ = ["argument_lifetime_cleanup"]
