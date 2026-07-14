"""Concrete ARC metadata attached to every managed object instance."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRFieldAccess,
    IRFunctionDecl,
    IRGlobalDecl,
    IRInitializerList,
    IRLiteral,
    IRParam,
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
        IRAssign(
            target=arc_header_member(self_value, "deferred_next"),
            value=IRLiteral(text="NULL"),
        ),
        IRAssign(
            target=arc_header_member(self_value, "suppress_hook"),
            value=IRLiteral(text="0"),
        ),
        # Publish LIVE only after every other header member is initialized.
        IRAssign(
            target=arc_header_member(self_value, "state"),
            value=IRVar(name="__BTRC_ARC_LIVE"),
        ),
    ]


def descriptor_pointer(emitted_name: str):
    return IRAddressOf(expr=IRVar(name=descriptor_symbol(emitted_name)))


def emit_arc_descriptor(
    gen,
    emitted_name: str,
    visitor_name: str | None,
    hook_name: str | None = None,
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
    from .constructor_cleanup import program_uses_exceptions

    raise_name = None
    guard_name = None
    if hook_name is not None:
        guard_name = "__btrc_arc_guard_hook"
        raise_name = "__btrc_throw"
        gen.use_helper(guard_name)
        gen.use_helper(raise_name)
        declaration = IRFunctionDecl(
            name=hook_name,
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="object")],
            is_static=True,
        )
        if declaration not in gen.module.function_decls:
            gen.module.function_decls.append(declaration)
    elif program_uses_exceptions(gen):
        raise_name = "__btrc_throw"
        gen.use_helper(raise_name)
    gen.module.global_decls.append(
        IRGlobalDecl(
            c_type=CType(text="const __btrc_arc_type"),
            name=descriptor_symbol(emitted_name),
            init=IRInitializerList(
                elements=[
                    (IRVar(name=visitor_name) if visitor_name is not None else IRLiteral(text="NULL")),
                    IRVar(name=f"{emitted_name}_destroy"),
                    (IRVar(name=hook_name) if hook_name is not None else IRLiteral(text="NULL")),
                    (IRVar(name=guard_name) if guard_name is not None else IRLiteral(text="NULL")),
                    (IRVar(name=raise_name) if raise_name is not None else IRLiteral(text="NULL")),
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
