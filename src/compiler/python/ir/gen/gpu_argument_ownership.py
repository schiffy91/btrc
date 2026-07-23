"""ARC cleanup for caller-owned GPU buffer arguments."""


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
    prefix = [gen.lifetime.retain_value(stable, type_expr)] if pin else []
    gen.lifetime.protect_temporary(
        declaration,
        type_expr,
        declarations,
        prefix,
        "__btrc_gpu_arg_cleanup",
        active=host.cleanup_active(),
        fresh_temp=gen.fresh_temp,
        activate_cleanup=host.activate_cleanup,
    )
    suffix = gen.lifetime.release_and_clear(
        stable,
        type_expr,
        declarations,
        c_type,
        fresh_temp=gen.fresh_temp,
        record_declaration=host.record_declaration,
    )
    return declarations, prefix, suffix


__all__ = ["argument_lifetime_cleanup"]
