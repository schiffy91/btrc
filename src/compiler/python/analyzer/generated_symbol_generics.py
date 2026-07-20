"""Generated symbol claims for concrete generic class instances."""

from ..cycle_symbols import cycle_visitor_symbol
from ..type_identity import mangle_generic_symbol, substitute_type_expr
from .generated_symbol_calls import claim_destructor_hook
from .generated_symbol_classes import managed_storage_type

_CYCLE_COLLECTIONS = frozenset({"Vector", "Array", "List", "Map", "Set"})


def claim_generic_instance_symbols(analyzer, declarations, claims) -> None:
    for base_name, instances in analyzer.generic_instances.items():
        declaration = declarations.get(base_name)
        info = analyzer.class_table.get(base_name)
        if declaration is None or info is None:
            continue
        for arguments in instances:
            emitted_name = mangle_generic_symbol(base_name, arguments)
            owner = f"generic instance '{emitted_name}'"
            _claim_generic_lifecycle(analyzer, declaration, emitted_name, owner, claims)
            claim_destructor_hook(analyzer, emitted_name, owner, info, declaration, claims)
            if _generic_needs_cycle_visitor(analyzer, base_name, arguments, info):
                analyzer._claim_generated_symbol(
                    cycle_visitor_symbol(emitted_name),
                    f"cycle visitor for {owner}",
                    declaration.line,
                    declaration.col,
                    claims,
                )
            _claim_generic_members(analyzer, emitted_name, owner, info, claims)


def _claim_generic_lifecycle(analyzer, declaration, emitted_name, owner, claims) -> None:
    for suffix, role in (
        ("init", "initializer"),
        ("new", "allocator"),
        ("destroy", "destructor"),
    ):
        analyzer._claim_generated_symbol(
            f"{emitted_name}_{suffix}",
            f"{role} for {owner}",
            declaration.line,
            declaration.col,
            claims,
        )


def _generic_needs_cycle_visitor(analyzer, base_name, arguments, info) -> bool:
    if base_name in _CYCLE_COLLECTIONS:
        return base_name == "List" or any(managed_storage_type(analyzer, arg) for arg in arguments)
    substitutions = dict(zip(info.generic_params, arguments))
    return any(
        managed_storage_type(
            analyzer,
            substitute_type_expr(
                field.type,
                substitutions,
                reference_resolver=analyzer._canonical_type,
            ),
        )
        for _name, field in info.instance_storage
    )


def _claim_generic_members(analyzer, emitted_name, owner, info, claims) -> None:
    for method_name, method in info.methods.items():
        if method.is_constructor or method_name == "__del__" or method.generic_params:
            continue
        analyzer._claim_generated_symbol(
            f"{emitted_name}_{method_name}",
            f"method '{method_name}' for {owner}",
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
                    f"{emitted_name}_{prefix}_{property_name}",
                    f"{role} '{property_name}' for {owner}",
                    prop.line,
                    prop.col,
                    claims,
                )


__all__ = ["claim_generic_instance_symbols"]
