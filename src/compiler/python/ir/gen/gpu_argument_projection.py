"""Lifetime roots for array projections passed to GPU dispatch."""

from ...ast_nodes import CallExpr, FieldAccessExpr, IndexExpr
from ..nodes import CType, IRBinOp, IRVar, IRVarDecl


def prepare_projection_roots(
    gen,
    host,
    expression,
    declarations,
    assignments,
    cleanup,
    overrides,
) -> None:
    """Hoist roots whose projected array must outlive argument evaluation."""

    from .assignment_ownership import borrowed_projection_owner_operands

    roots = borrowed_projection_owner_operands(
        expression,
        owns=host.owns_result,
        overridden=lambda value: id(value) in overrides or host.override_value(value) is not None,
    )
    struct_root = _struct_temporary_root(gen, host, expression)
    if struct_root is not None and all(root is not struct_root for root in roots):
        roots.append(struct_root)
    managed_root = _managed_projection_root(host, expression, overrides)
    if managed_root is not None and all(root is not managed_root for root in roots):
        roots.append(managed_root)
    for root in roots:
        if id(root) in overrides:
            continue
        root_type = host.resolve_type(root)
        if root_type is None:
            from .errors import CodegenError

            raise CodegenError("GPU array projection root has no concrete type")
        name = gen.fresh_temp("__gpu_projection_root")
        declaration = IRVarDecl(
            c_type=CType(text=host.type_renderer.render(root_type)),
            name=name,
        )
        declarations.append(declaration)
        host.record_declaration(declaration)
        stable = IRVar(name=name)
        lowered = host.override_value(root)
        if lowered is None:
            lowered = host.lower_argument(root, overrides)
        assignments.append(IRBinOp(left=stable, op="=", right=lowered))
        if host.is_managed(root_type):
            from .gpu_argument_ownership import argument_lifetime_cleanup

            owned = host.owns_result(root)
            extra, prefix, suffix = argument_lifetime_cleanup(
                gen,
                host,
                declaration,
                stable,
                root_type,
                host.type_renderer.render(root_type),
                pin=not owned,
            )
            declarations.extend(extra)
            assignments.extend(prefix)
            cleanup.extend(suffix)
        overrides[id(root)] = stable


def _managed_projection_root(host, expression, overrides):
    """Find borrowed managed storage immediately backing an array view."""

    if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
        return None
    receiver = expression.obj
    if id(receiver) not in overrides and host.override_value(receiver) is None:
        receiver_type = host.resolve_type(receiver)
        if receiver_type is not None and host.is_managed(receiver_type):
            return receiver
    return _managed_projection_root(host, receiver, overrides)


def _struct_temporary_root(gen, host, expression):
    if not isinstance(expression, (FieldAccessExpr, IndexExpr)):
        return None
    receiver = expression.obj
    receiver_type = host.resolve_type(receiver)
    if (
        isinstance(receiver, CallExpr)
        and receiver_type is not None
        and receiver_type.pointer_depth == 0
        and not receiver_type.is_array
        and receiver_type.base in gen.analyzed.struct_table
    ):
        return receiver
    return _struct_temporary_root(gen, host, receiver)


__all__ = ["prepare_projection_roots"]
