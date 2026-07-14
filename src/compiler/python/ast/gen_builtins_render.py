"""Render scanned stdlib APIs as the generated LSP builtins Python module."""

from __future__ import annotations

import textwrap

from src.compiler.python.ast.gen_builtins_spec import (
    INTRINSIC_COLLECTION_MEMBERS,
    INTRINSIC_FUNCTIONS,
    INTRINSIC_STRING_MEMBERS,
)


def fmt_params(params: list[tuple]) -> str:
    """Format a parameter list as Python source."""
    if not params:
        return "[]"
    items = ", ".join(f'("{param_type}", "{param_name}")' for param_type, param_name in params)
    return f"[{items}]"


def generate_collection_members(
    var_name: str,
    fields: list[tuple],
    methods: list[tuple],
    intrinsics: list[tuple],
) -> str:
    """Render stdlib-parsed and intrinsic members for one collection type."""
    lines = [f"{var_name}: list[BuiltinMember] = ["]
    for name, type_str in fields:
        lines.append(
            f'    BuiltinMember("{name}", "{type_str}", "field", doc="{name}"),',
        )
    for name, return_type, params, _is_static in methods:
        lines.append(
            f'    BuiltinMember("{name}", "{return_type}", "method", {fmt_params(params)}, "{name}"),',
        )
    for name, return_type, _kind, params, doc in intrinsics:
        escaped_doc = doc.replace('"', '\\"')
        lines.append(
            f'    BuiltinMember("{name}", "{return_type}", "method", {fmt_params(params)}, "{escaped_doc}"),',
        )
    lines.append("]")
    return "\n".join(lines)


def generate_intrinsic_members(var_name: str, entries: list[tuple]) -> str:
    """Render a BuiltinMember list from intrinsic tuples."""
    lines = [f"{var_name}: list[BuiltinMember] = ["]
    for name, return_type, kind, params, doc in entries:
        escaped_doc = doc.replace('"', '\\"')
        lines.append(
            f'    BuiltinMember("{name}", "{return_type}", "{kind}", {fmt_params(params)}, "{escaped_doc}"),',
        )
    lines.append("]")
    return "\n".join(lines)


def generate_static_methods(class_name: str, methods: list[tuple]) -> str:
    """Render one entry in ``STDLIB_STATIC_METHODS``."""
    lines = [f'    "{class_name}": [']
    for name, return_type, params, _is_static in methods:
        lines.append(
            f'        BuiltinMember("{name}", "{return_type}", "method", {fmt_params(params)}, "{name}"),',
        )
    lines.append("    ],")
    return "\n".join(lines)


def render_builtins(collection_data, static_data) -> str:
    """Return the complete generated builtins module source."""
    out = []
    out.append('"""Single source of truth for built-in type members in the btrc language.')
    out.append("")
    out.append("Auto-generated from stdlib .btrc files by src/compiler/python/ast/gen_builtins.py.")
    out.append("DO NOT EDIT BY HAND — edit the stdlib source or the generator instead.")
    out.append("")
    out.append("Used by completion, hover, and signature help providers to avoid")
    out.append("maintaining separate (and inevitably divergent) copies of the same data.")
    out.append('"""')
    out.append("")
    out.append("from __future__ import annotations")
    out.append("")
    out.append("from dataclasses import dataclass, field")
    out.append("from typing import Optional")
    out.append("")
    out.append("")

    out.append("@dataclass")
    out.append("class BuiltinMember:")
    out.append('    """One member (field or method) of a built-in type."""')
    out.append("")
    out.append("    name: str")
    out.append("    return_type: str")
    out.append('    kind: str  # "field" or "method"')
    out.append("    params: list[tuple[str, str]] = field(default_factory=list)  # [(type, name)]")
    out.append('    doc: str = ""')
    out.append("")
    out.append("")

    out.append("# " + "-" * 75)
    out.append("# Built-in type member tables")
    out.append("# " + "-" * 75)
    out.append("")
    out.append("# String methods are language intrinsics (not defined in any .btrc file)")
    out.append(generate_intrinsic_members("STRING_MEMBERS", INTRINSIC_STRING_MEMBERS))
    out.append("")

    for type_name, (fields, methods) in collection_data.items():
        var_name = f"{type_name.upper()}_MEMBERS"
        out.append(f"# Generated from src/stdlib/{type_name.lower()}.btrc")
        intrinsics = INTRINSIC_COLLECTION_MEMBERS.get(type_name, [])
        out.append(generate_collection_members(var_name, fields, methods, intrinsics))
        out.append("")

    out.append("_MEMBER_TABLES: dict[str, list[BuiltinMember]] = {")
    out.append('    "string": STRING_MEMBERS,')
    for type_name in collection_data:
        out.append(f'    "{type_name}": {type_name.upper()}_MEMBERS,')
    out.append("}")
    out.append("")
    out.append("")

    out.append("# " + "-" * 75)
    out.append("# Stdlib static method tables")
    out.append("# " + "-" * 75)
    out.append("")
    out.append("# Generated from stdlib .btrc files")
    out.append("STDLIB_STATIC_METHODS: dict[str, list[BuiltinMember]] = {")
    for class_name, methods in static_data.items():
        out.append(generate_static_methods(class_name, methods))
    out.append("}")
    out.append("")

    out.append("# Built-in free function signatures: name -> (return_type, [(param_type, param_name)])")
    out.append("BUILTIN_FUNCTION_SIGNATURES: dict[str, tuple[str, list[tuple[str, str]]]] = {")
    for function_name, (return_type, params) in INTRINSIC_FUNCTIONS.items():
        out.append(f'    "{function_name}": ("{return_type}", {fmt_params(params)}),')
    out.append("}")
    out.append("")
    out.append("")

    out.append("# " + "-" * 75)
    out.append("# Accessor functions")
    out.append("# " + "-" * 75)
    out.append("")
    out.append("")
    out.append(_ACCESSOR_FUNCTIONS)
    return "\n".join(out)


_ACCESSOR_FUNCTIONS = textwrap.dedent("""\
        def get_members_for_type(type_name: str) -> list[BuiltinMember]:
            \"\"\"Return the list of built-in members for a type, or empty list.\"\"\"
            return _MEMBER_TABLES.get(base_type_name(type_name), [])


        def base_type_name(type_name: str) -> str:
            \"\"\"Return the member-table owner name for a possibly generic type.\"\"\"
            raw = type_name.strip()
            while raw.endswith("?") or raw.endswith("*"):
                raw = raw[:-1].strip()
            depth = 0
            for index, char in enumerate(raw):
                if char == "<":
                    if depth == 0:
                        return raw[:index].strip()
                    depth += 1
                elif char == ">":
                    depth -= 1
            return raw


        def get_member(type_name: str, member_name: str) -> Optional[BuiltinMember]:
            \"\"\"Look up a specific member on a built-in type.\"\"\"
            for m in get_members_for_type(type_name):
                if m.name == member_name:
                    return m
            return None


        def get_hover_markdown(type_name: str, member_name: str) -> Optional[str]:
            \"\"\"Generate a markdown hover string for a built-in type member.\"\"\"
            m = get_member(type_name, member_name)
            if m is None:
                return None
            if m.kind == "field":
                return f"```btrc\\n{m.return_type} {m.name}\\n```\\n{m.doc}"
            params_str = ", ".join(f"{pt} {pn}" for pt, pn in m.params)
            return f"```btrc\\n{m.return_type} {m.name}({params_str})\\n```\\n{m.doc}"


        def get_signature_params(
            type_name: str, method_name: str
        ) -> Optional[list[tuple[str, str]]]:
            \"\"\"Return the parameter list for a built-in type method, or None.\"\"\"
            m = get_member(type_name, method_name)
            if m is None or m.kind == "field":
                return None
            return m.params


        def get_stdlib_methods(class_name: str) -> Optional[list[BuiltinMember]]:
            \"\"\"Return the list of static methods for a stdlib class, or None.\"\"\"
            return STDLIB_STATIC_METHODS.get(class_name)


        def get_stdlib_signature(
            class_name: str, method_name: str
        ) -> Optional[list[tuple[str, str]]]:
            \"\"\"Return the parameter list for a stdlib static method, or None.\"\"\"
            methods = STDLIB_STATIC_METHODS.get(class_name)
            if methods is None:
                return None
            for m in methods:
                if m.name == method_name:
                    return m.params
            return None
    """)
