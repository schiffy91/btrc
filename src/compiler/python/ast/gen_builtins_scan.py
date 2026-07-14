"""Parse stdlib classes and extract the API data used by builtins generation."""

from __future__ import annotations

import os

from src.compiler.python.ast_nodes import (
    ClassDecl,
    FieldDecl,
    MethodDecl,
    PropertyDecl,
    TypeExpr,
)
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

_ALWAYS_HIDDEN_FIELDS = {"cap", "occupied"}
_ALWAYS_HIDDEN_METHODS = {"resize"}


def classify_stdlib(stdlib_dir):
    """Return collection and all-static class APIs found in ``stdlib_dir``."""
    collection_data = {}
    static_data = {}

    for filename in sorted(os.listdir(stdlib_dir)):
        if not filename.endswith(".btrc"):
            continue
        classes = parse_file(filename, stdlib_dir)
        for class_name, cls in classes.items():
            methods = [member for member in cls.members if isinstance(member, MethodDecl) and member.name != class_name]
            static_methods = [member for member in methods if member.access == "class"]
            instance_methods = [member for member in methods if member.access in ("public", "private")]

            if cls.generic_params and instance_methods:
                fields, extracted_methods = extract_members(cls)
                instance_api = [method for method in extracted_methods if not method[3]]
                collection_data[class_name] = (fields, instance_api)
            elif static_methods and not instance_methods:
                _fields, extracted_methods = extract_members(cls)
                static_data[class_name] = extracted_methods

    return collection_data, static_data


def type_repr(type_expr: TypeExpr | None) -> str:
    """Convert a type-expression node to its generated source spelling."""
    if type_expr is None:
        return "void"
    result = type_expr.base
    if type_expr.generic_args:
        args = ", ".join(type_repr(argument) for argument in type_expr.generic_args)
        result += f"<{args}>"
    if type_expr.pointer_depth > 0:
        result += "*" * type_expr.pointer_depth
    return result


def parse_file(filename: str, stdlib_dir) -> dict[str, ClassDecl]:
    """Parse one stdlib file and return its class declarations by name."""
    path = os.path.join(stdlib_dir, filename)
    with open(path) as source_file:
        source = source_file.read()
    source = "\n".join("" if line.strip().startswith("import ") else line for line in source.splitlines())
    tokens = Lexer(source, filename).tokenize()
    program = Parser(tokens).parse()
    return {declaration.name: declaration for declaration in program.declarations if isinstance(declaration, ClassDecl)}


def _is_hidden_field(member: FieldDecl) -> bool:
    """Whether a field is an implementation detail rather than public API."""
    if member.name in _ALWAYS_HIDDEN_FIELDS:
        return True
    return bool(member.type and member.type.pointer_depth > 0)


def extract_members(cls: ClassDecl) -> tuple[list[tuple], list[tuple]]:
    """Extract generated field and method tuples from one class declaration."""
    fields = []
    methods = []
    for member in cls.members:
        if isinstance(member, FieldDecl) and member.access == "public":
            if not _is_hidden_field(member):
                fields.append((member.name, type_repr(member.type)))
        elif isinstance(member, MethodDecl):
            if member.is_constructor or member.name.startswith("__"):
                continue
            if member.access not in ("public", "class"):
                continue
            if member.name in _ALWAYS_HIDDEN_METHODS:
                continue
            params = [(type_repr(param.type), param.name) for param in member.params]
            methods.append(
                (
                    member.name,
                    type_repr(member.return_type),
                    params,
                    member.access == "class",
                )
            )
        elif isinstance(member, PropertyDecl) and member.access == "public":
            if member.name not in _ALWAYS_HIDDEN_FIELDS:
                fields.append((member.name, type_repr(member.type)))
    return fields, methods
