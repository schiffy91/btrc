"""Generated symbol claims for concrete classes and their members."""

from ..ast_nodes import FieldDecl, PropertyDecl
from ..class_storage import property_needs_backing
from ..cycle_symbols import cycle_visitor_symbol
from .generated_symbol_calls import claim_destructor_hook


def managed_storage_type(analyzer, type_expr) -> bool:
    type_expr = analyzer._canonical_type(type_expr)
    return bool(
        type_expr is not None
        and not type_expr.is_array
        and type_expr.pointer_depth <= 1
        and type_expr.base in analyzer.declarations.class_table
    )


def claim_class_symbols(analyzer, declaration, claims) -> None:
    name = declaration.name
    info = analyzer.declarations.class_table[name]
    for suffix, role in (
        ("init", "initializer"),
        ("new", "allocator"),
        ("destroy", "destructor"),
    ):
        analyzer._claim_generated_symbol(
            f"{name}_{suffix}",
            f"{role} for class '{name}'",
            declaration.line,
            declaration.col,
            claims,
        )
    claim_destructor_hook(
        analyzer,
        name,
        f"class '{name}'",
        info,
        declaration,
        claims,
    )
    if any(managed_storage_type(analyzer, field.type) for _name, field in info.instance_storage):
        analyzer._claim_generated_symbol(
            cycle_visitor_symbol(name),
            f"cycle visitor for class '{name}'",
            declaration.line,
            declaration.col,
            claims,
        )
    _claim_class_members(analyzer, declaration, info, claims)


def _claim_class_members(analyzer, declaration, info, claims) -> None:
    name = declaration.name
    for method_name, method in info.methods.items():
        if method.is_constructor or method_name == "__del__" or method.generic_params:
            continue
        analyzer._claim_generated_symbol(
            f"{name}_{method_name}",
            f"method '{name}.{method_name}'",
            method.line,
            method.col,
            claims,
        )
    for property_name, prop in info.properties.items():
        for enabled, prefix, role in (
            (prop.has_getter, "get", "getter"),
            (prop.has_setter, "set", "setter"),
        ):
            if enabled:
                analyzer._claim_generated_symbol(
                    f"{name}_{prefix}_{property_name}",
                    f"{role} '{name}.{property_name}'",
                    prop.line,
                    prop.col,
                    claims,
                )
    for member in declaration.members:
        if isinstance(member, FieldDecl) and member.access == "class":
            analyzer._claim_generated_symbol(
                f"{name}_{member.name}",
                f"static field '{name}.{member.name}'",
                member.line,
                member.col,
                claims,
            )
        elif isinstance(member, PropertyDecl) and property_needs_backing(member):
            analyzer._reject_generated_member_macro(
                f"_prop_{member.name}",
                f"property backing field '{name}.{member.name}'",
                member.line,
                member.col,
            )
    for symbol, role in (
        ("__arc", "ARC header"),
        ("__rc", "reference count"),
        ("__cycle_safe_rc", "cycle proof"),
    ):
        analyzer._reject_generated_member_macro(
            symbol,
            f"{role} field for class '{name}'",
            declaration.line,
            declaration.col,
        )


__all__ = ["claim_class_symbols", "managed_storage_type"]
