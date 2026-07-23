"""Lower context-typed brace initializers to structured C expressions."""

from ..nodes import CType, IRCall, IRCompoundLiteral, IRInitializerList, IRLiteral
from .types import CTypeRenderer, is_generic_class_type


def lower_brace_initializer(
    gen,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
    *,
    node_type=None,
    lower=None,
):
    """Lower a brace initializer using the analyzer's contextual type stamp."""

    from .expressions import lower_expr

    lower = lower or (
        lambda element: lower_expr(
            gen,
            element,
            type_renderer,
            default_arguments,
        )
    )
    analyzed = gen.analyzed
    node_type = node_type or analyzed.node_types.get(id(node))
    from .aggregate_ownership import reject_shallow_initializer

    reject_shallow_initializer(gen, node, node_type)
    if node_type and is_generic_class_type(node_type, analyzed.class_table):
        if not node.elements:
            mangled = gen.type_identity.specialization_symbol(node_type.base, node_type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
        return IRInitializerList(elements=[lower(element) for element in node.elements])

    canonical = _canonical_type(node_type, analyzed.typedef_table)
    if canonical and canonical.is_array:
        return IRInitializerList(elements=[lower(element) for element in node.elements])
    if canonical and canonical.pointer_depth == 0:
        struct_name = canonical.base.removeprefix("struct ")
        declaration = analyzed.struct_table.get(struct_name)
        if declaration is not None and not declaration.is_forward:
            return IRCompoundLiteral(
                c_type=CType(text=type_renderer.render(node_type)),
                fields=[(field.name, lower(element)) for field, element in zip(declaration.fields, node.elements)],
            )
        if canonical.base == "Tuple":
            return IRCompoundLiteral(
                c_type=CType(text=type_renderer.render(node_type)),
                fields=[(f"_{index}", lower(element)) for index, element in enumerate(node.elements)],
            )

    if node.elements:
        return IRInitializerList(elements=[lower(element) for element in node.elements])
    return IRLiteral(text="NULL")


def _canonical_type(type_expr, typedefs):
    from .type_resolution import canonical_type

    return canonical_type(type_expr, typedefs)


def lower_static_initializer(
    gen,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Preserve nested initializer lists in strict-C static storage."""

    from ...ast_nodes import BraceInitializer, ListLiteral
    from .expressions import lower_expr

    if isinstance(node, (BraceInitializer, ListLiteral)):
        node_type = gen.analyzed.node_types.get(id(node))
        from .aggregate_ownership import reject_shallow_initializer

        reject_shallow_initializer(gen, node, node_type)
        canonical = _canonical_type(node_type, gen.analyzed.typedef_table)
        elements = [
            lower_static_initializer(
                gen,
                element,
                type_renderer,
                default_arguments,
            )
            for element in node.elements
        ]
        field_types = _aggregate_field_types(gen, canonical)
        if field_types is not None and elements:
            elements.extend(_zero_static_initializer(gen, field_type) for field_type in field_types[len(elements) :])
        return IRInitializerList(elements=elements)
    return lower_expr(
        gen,
        node,
        type_renderer,
        default_arguments,
    )


def _aggregate_field_types(gen, type_expr):
    if type_expr is None or type_expr.pointer_depth > 0 or type_expr.is_array:
        return None
    struct_name = type_expr.base.removeprefix("struct ")
    declaration = gen.analyzed.struct_table.get(struct_name)
    if declaration is not None and not declaration.is_forward:
        return [field.type for field in declaration.fields]
    if type_expr.base == "Tuple":
        return list(type_expr.generic_args)
    return None


def _zero_static_initializer(gen, type_expr):
    canonical = _canonical_type(type_expr, gen.analyzed.typedef_table)
    if canonical and (canonical.is_array or _aggregate_field_types(gen, canonical) is not None):
        return IRInitializerList(elements=[])
    return IRLiteral(text="0")


__all__ = ["lower_brace_initializer", "lower_static_initializer"]
