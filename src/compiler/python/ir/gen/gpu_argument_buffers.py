"""Immediate data/length snapshots for GPU collection arguments."""

from ..nodes import CType, IRBinOp, IRFieldAccess, IRVar, IRVarDecl


def capture_collection_view(
    gen,
    host,
    parameter,
    stable,
    declarations,
    assignments,
):
    """Capture a collection's view before later arguments can replace it."""

    data_name = gen.fresh_temp("__gpu_data")
    length_name = gen.fresh_temp("__gpu_len")
    data_declaration = IRVarDecl(
        c_type=CType(text=host.type_renderer.render(parameter.type)),
        name=data_name,
    )
    length_declaration = IRVarDecl(
        c_type=CType(text="int"),
        name=length_name,
    )
    declarations.extend((data_declaration, length_declaration))
    host.record_declaration(data_declaration)
    host.record_declaration(length_declaration)
    data = IRVar(name=data_name)
    length = IRVar(name=length_name)
    assignments.extend(
        (
            IRBinOp(
                left=data,
                op="=",
                right=IRFieldAccess(obj=stable, field="data", arrow=True),
            ),
            IRBinOp(
                left=length,
                op="=",
                right=IRFieldAccess(obj=stable, field="len", arrow=True),
            ),
        )
    )
    return data, length


def capture_array_length(gen, host, expression, lowered, declarations, assignments):
    """Snapshot fixed-array capacity beside its data-pointer snapshot."""

    name = gen.fresh_temp("__gpu_len")
    declaration = IRVarDecl(c_type=CType(text="int"), name=name)
    declarations.append(declaration)
    host.record_declaration(declaration)
    length = IRVar(name=name)
    assignments.append(
        IRBinOp(
            left=length,
            op="=",
            right=host.array_length(expression, lowered),
        )
    )
    return length


__all__ = ["capture_array_length", "capture_collection_view"]
