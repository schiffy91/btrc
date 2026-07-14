"""Concrete ARC metadata attached to every managed object instance."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRFieldAccess,
    IRGlobalDecl,
    IRInitializerList,
    IRLiteral,
    IRStructField,
    IRVar,
)

ARC_HEADER_FIELD = "__arc"


def descriptor_symbol(emitted_name: str) -> str:
    """Return the interned descriptor symbol for one concrete C type."""
    return f"__btrc_{emitted_name}_arc_type"


def arc_header_field(gen) -> IRStructField:
    """Return the mandatory first field for a managed representation."""
    gen.use_helper("__btrc_arc_callback_types")
    gen.module.runtime_roots.add("__btrc_arc_callback_types")
    return IRStructField(
        c_type=CType(text="__btrc_arc_header"),
        name=ARC_HEADER_FIELD,
    )


def arc_header_member(value, member: str):
    """Project one member from a pointer's embedded ARC header."""
    header = IRFieldAccess(obj=value, field=ARC_HEADER_FIELD, arrow=True)
    return IRFieldAccess(obj=header, field=member, arrow=False)


def arc_header_initialization(emitted_name: str, self_name: str = "self"):
    """Initialize refcounts and concrete metadata before user constructor code."""
    self_value = IRVar(name=self_name)
    return [
        IRAssign(
            target=arc_header_member(self_value, "rc"),
            value=IRLiteral(text="1"),
        ),
        IRAssign(
            target=arc_header_member(self_value, "edge_rc"),
            value=IRLiteral(text="0"),
        ),
        IRAssign(
            target=arc_header_member(self_value, "live_witness"),
            value=IRLiteral(text="NULL"),
        ),
        IRAssign(
            target=arc_header_member(self_value, "type"),
            value=descriptor_pointer(emitted_name),
        ),
        IRAssign(
            target=arc_header_member(self_value, "incoming"),
            value=IRLiteral(text="NULL"),
        ),
    ]


def descriptor_pointer(emitted_name: str):
    return IRAddressOf(expr=IRVar(name=descriptor_symbol(emitted_name)))


def emit_arc_descriptor(
    gen,
    emitted_name: str,
    visitor_name: str | None,
) -> None:
    """Emit one process-lifetime descriptor for a concrete managed type."""
    emitted = getattr(gen, "_arc_descriptor_types", None)
    if emitted is None:
        emitted = set()
        gen._arc_descriptor_types = emitted
    if emitted_name in emitted:
        return
    emitted.add(emitted_name)
    gen.use_helper("__btrc_arc_callback_types")
    gen.module.runtime_roots.add("__btrc_arc_callback_types")
    gen.module.global_decls.append(
        IRGlobalDecl(
            c_type=CType(text="const __btrc_arc_type"),
            name=descriptor_symbol(emitted_name),
            init=IRInitializerList(
                elements=[
                    (IRVar(name=visitor_name) if visitor_name is not None else IRLiteral(text="NULL")),
                    IRVar(name=f"{emitted_name}_destroy"),
                ]
            ),
        )
    )


__all__ = [
    "ARC_HEADER_FIELD",
    "arc_header_field",
    "arc_header_initialization",
    "arc_header_member",
    "descriptor_pointer",
    "descriptor_symbol",
    "emit_arc_descriptor",
]
