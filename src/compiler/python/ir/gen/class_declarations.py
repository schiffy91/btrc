"""Typed callable declarations for concrete classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...analyzer.core import ClassInfo
from ...ast_nodes import ClassDecl, MethodDecl, PropertyDecl
from ..nodes import CType, IRFunctionDecl, IRParam
from .parameters import lower_named_source_type_param, lower_source_param
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_class_callable_declarations(
    gen: IRGenerator,
    declaration: ClassDecl,
    class_info: ClassInfo,
) -> None:
    """Register declarations for a class's own and inherited callables."""

    for function in class_callable_declarations(
        declaration,
        class_info,
        gen.analyzed.class_table,
        gen.analyzed,
    ):
        if function not in gen.module.function_decls:
            gen.module.function_decls.append(function)


def class_callable_declarations(
    declaration: ClassDecl,
    class_info: ClassInfo,
    class_table: dict,
    analyzed,
) -> list[IRFunctionDecl]:
    """Describe every callable prototype exposed by one concrete class."""

    name = declaration.name
    constructor_params = _parameters(
        class_info.constructor.params if class_info.constructor else [],
        analyzed,
    )
    declarations = [
        IRFunctionDecl(
            name=f"{name}_init",
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text=f"{name}*"), name="self")] + constructor_params,
        ),
        IRFunctionDecl(
            name=f"{name}_new",
            return_type=CType(text=f"{name}*"),
            params=list(constructor_params),
        ),
    ]

    for member in declaration.members:
        if (
            isinstance(member, MethodDecl)
            and not member.is_constructor
            and member.name != "__del__"
            and not member.generic_params
        ):
            params = []
            if member.access != "class":
                params.append(IRParam(c_type=CType(text=f"{name}*"), name="self"))
            params.extend(_parameters(member.params, analyzed))
            declarations.append(
                IRFunctionDecl(
                    name=f"{name}_{member.name}",
                    return_type=CType(text=type_to_c(member.return_type)),
                    params=params,
                )
            )
        elif isinstance(member, PropertyDecl):
            declarations.extend(_property_declarations(name, member, analyzed))

    declarations.extend(
        _inherited_property_declarations(
            name,
            declaration,
            class_info,
            class_table,
            analyzed,
        )
    )
    declarations.extend(
        _inherited_method_declarations(
            name,
            declaration,
            class_info,
            class_table,
            analyzed,
        )
    )
    return declarations


def _parameters(parameters, analyzed) -> list[IRParam]:
    return [lower_source_param(parameter, analyzed=analyzed) for parameter in parameters]


def _property_declarations(
    class_name: str,
    declaration: PropertyDecl,
    analyzed,
) -> list[IRFunctionDecl]:
    prop_type = CType(text=type_to_c(declaration.type))
    self_param = IRParam(c_type=CType(text=f"{class_name}*"), name="self")
    result = []
    if declaration.has_getter:
        result.append(
            IRFunctionDecl(
                name=f"{class_name}_get_{declaration.name}",
                return_type=prop_type,
                params=[self_param],
            )
        )
    if declaration.has_setter:
        result.append(
            IRFunctionDecl(
                name=f"{class_name}_set_{declaration.name}",
                return_type=CType(text="void"),
                params=[
                    self_param,
                    lower_named_source_type_param(
                        declaration.type,
                        prop_type,
                        "value",
                        analyzed,
                    ),
                ],
            )
        )
    return result


def _inherited_property_declarations(
    class_name: str,
    declaration: ClassDecl,
    class_info: ClassInfo,
    class_table: dict,
    analyzed,
) -> list[IRFunctionDecl]:
    parent = class_table.get(class_info.parent) if class_info.parent else None
    if parent is None:
        return []
    own = {member.name for member in declaration.members if isinstance(member, PropertyDecl)}
    result = []
    for name, prop in parent.properties.items():
        if name not in own:
            result.extend(_property_declarations(class_name, prop, analyzed))
    return result


def _inherited_method_declarations(
    class_name: str,
    declaration: ClassDecl,
    class_info: ClassInfo,
    class_table: dict,
    analyzed,
) -> list[IRFunctionDecl]:
    declarations = []
    seen = {member.name for member in declaration.members if isinstance(member, MethodDecl)}
    parent_name = class_info.parent
    while parent_name and parent_name in class_table:
        parent_info = class_table[parent_name]
        for method_name, method in parent_info.methods.items():
            if method_name in seen or method_name in {"__del__", parent_name} or method.generic_params:
                continue
            seen.add(method_name)
            params = []
            if method.access != "class":
                params.append(
                    IRParam(
                        c_type=CType(text=f"{class_name}*"),
                        name="self",
                    )
                )
            params.extend(_parameters(method.params, analyzed))
            declarations.append(
                IRFunctionDecl(
                    name=f"{class_name}_{method_name}",
                    return_type=CType(text=type_to_c(method.return_type)),
                    params=params,
                )
            )
        parent_name = parent_info.parent
    return declarations
