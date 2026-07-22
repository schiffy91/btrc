"""Discovery and emission of generated tuple aggregate declarations."""

from ...ast_nodes import (
    ClassDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    VarDeclStmt,
)
from ...qualifier_provenance import effective_outer_volatile
from ..nodes import CType, IRStructDef, IRStructField, IRStructForward
from .types import mangle_tuple_type, type_to_c


def emit_tuple_structs(gen) -> None:
    seen = {}
    for declaration in gen.analyzed.program.declarations:
        for type_expr in _declaration_types(declaration):
            _collect_tuple_types(type_expr, seen)
    for type_expr in gen.analyzed.node_types.values():
        _collect_tuple_types(type_expr, seen)

    for mangled, arguments in seen.items():
        gen.module.struct_defs.append(
            IRStructDef(
                name=mangled,
                fields=[
                    IRStructField(
                        c_type=CType(text=type_to_c(argument)),
                        name=f"_{index}",
                        is_volatile=bool(argument.is_volatile),
                        effective_is_volatile=effective_outer_volatile(
                            argument,
                            gen.analyzed.typedef_table,
                        ),
                    )
                    for index, argument in enumerate(arguments)
                ],
            )
        )
        forward = IRStructForward(name=mangled)
        if forward not in gen.module.struct_forwards:
            gen.module.struct_forwards.append(forward)


def _declaration_types(declaration):
    if isinstance(declaration, FunctionDecl):
        yield declaration.return_type
        yield from (parameter.type for parameter in declaration.params)
    elif isinstance(declaration, ClassDecl):
        for member in declaration.members:
            if isinstance(member, (FieldDecl, PropertyDecl)):
                yield member.type
            elif isinstance(member, MethodDecl):
                yield member.return_type
                yield from (parameter.type for parameter in member.params)
    elif isinstance(declaration, InterfaceDecl):
        for method in declaration.methods:
            yield method.return_type
            yield from (parameter.type for parameter in method.params)
    elif isinstance(declaration, StructDecl):
        yield from (field.type for field in declaration.fields)
    elif isinstance(declaration, RichEnumDecl):
        for variant in declaration.variants:
            yield from (parameter.type for parameter in variant.params)
    elif isinstance(declaration, TypedefDecl):
        yield declaration.original
    elif isinstance(declaration, VarDeclStmt) and declaration.type is not None:
        yield declaration.type


def _collect_tuple_types(type_expr, seen) -> None:
    if type_expr is None:
        return
    for argument in type_expr.generic_args:
        _collect_tuple_types(argument, seen)
    if type_expr.base == "Tuple" and type_expr.generic_args:
        seen.setdefault(mangle_tuple_type(type_expr), list(type_expr.generic_args))


__all__ = ["emit_tuple_structs"]
