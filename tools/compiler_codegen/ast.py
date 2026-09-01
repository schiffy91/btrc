"""Deterministic Python and self-hosted AST catalog generation owners."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from src.compiler.python.syntax.grammar import GrammarRepository

from . import GeneratedArtifact, GeneratedSourceError, format_generated_btrc
from .asdl import (
    AsdlConstructor,
    AsdlField,
    AsdlModule,
    AsdlSchemaParser,
    AsdlType,
)


class PythonAstRenderer:
    """Render one immutable ASDL schema as Python dataclass declarations."""

    _BUILTIN_TYPES: ClassVar[dict[str, str]] = {
        "identifier": "str",
        "string": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
    }
    _POSITION_FIELDS = frozenset({"line", "col", "name_line", "name_col"})
    _PROVENANCE_FIELDS = frozenset({"source_file"})
    _SCALAR_DEFAULTS: ClassVar[dict[str, str]] = {
        "str": '""',
        "int": "0",
        "float": "0.0",
        "bool": "False",
    }

    def __init__(self, schema: AsdlModule):
        self._schema = schema
        self._type_names = self._build_type_name_map()

    def render(self) -> str:
        lines = [
            '"""AST node definitions for the btrc language.',
            "",
            "Auto-generated from src/language/ast.asdl by tools/compiler_codegen/ast.py.",
            "DO NOT EDIT BY HAND.",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass",
            "from dataclasses import field as _dc_field",
            "from typing import Optional, Union",
        ]

        constructors: list[
            tuple[AsdlConstructor, tuple[AsdlField, ...], AsdlType]
        ] = []
        sum_types: list[AsdlType] = []
        product_types: list[AsdlType] = []
        simple_enums: list[AsdlType] = []
        for schema_type in self._schema.types:
            if self._is_simple_enum(schema_type):
                simple_enums.append(schema_type)
            elif self._is_sum_type(schema_type):
                sum_types.append(schema_type)
                for constructor in schema_type.constructors:
                    constructors.append(
                        (constructor, schema_type.attributes, schema_type)
                    )
            else:
                product_types.append(schema_type)
                constructors.append(
                    (
                        schema_type.constructors[0],
                        schema_type.attributes,
                        schema_type,
                    )
                )

        for schema_type in simple_enums:
            lines.extend(("", f"# --- {schema_type.name} (string constants) ---", ""))
            for constructor in schema_type.constructors:
                lines.append(f'{constructor.name} = "{constructor.name}"')

        for constructor, attributes, _schema_type in constructors:
            lines.extend(("", "", "@dataclass(kw_only=True)", f"class {constructor.name}:"))
            if not constructor.fields and not attributes:
                lines.append("    pass")
                continue
            for field in constructor.fields:
                lines.append(f"    {self._field_declaration(field)}")
            for attribute in attributes:
                lines.append(f"    {self._field_declaration(attribute)}")

        lines.extend(("", "", "# --- Union type aliases for sum types ---", ""))
        for schema_type in sum_types:
            names = ", ".join(
                constructor.name for constructor in schema_type.constructors
            )
            lines.append(f"{schema_type.name} = Union[{names}]")

        lines.extend(
            (
                "",
                "",
                "# --- Product type aliases ---",
                "# These alias lowercase ASDL names to the PascalCase class names",
                "",
            )
        )
        for schema_type in product_types:
            class_name = schema_type.constructors[0].name
            if schema_type.name != class_name:
                lines.append(f"{schema_type.name} = {class_name}")
        return "\n".join(lines) + "\n"

    def _is_sum_type(self, schema_type: AsdlType) -> bool:
        return len(schema_type.constructors) > 1

    def _is_simple_enum(self, schema_type: AsdlType) -> bool:
        return self._is_sum_type(schema_type) and all(
            not constructor.fields for constructor in schema_type.constructors
        )

    def _build_type_name_map(self) -> dict[str, str]:
        names = dict(self._BUILTIN_TYPES)
        for schema_type in self._schema.types:
            if self._is_simple_enum(schema_type):
                names[schema_type.name] = "str"
            elif self._is_sum_type(schema_type):
                names[schema_type.name] = schema_type.name
            else:
                names[schema_type.name] = schema_type.constructors[0].name
        return names

    def _python_type(self, field: AsdlField) -> str:
        base = self._type_names.get(field.type_name, field.type_name)
        if field.is_sequence:
            return f"list[{base}]"
        if field.is_optional:
            return f"Optional[{base}]"
        return base

    def _field_declaration(self, field: AsdlField) -> str:
        declaration = f"{field.name}: {self._python_type(field)}"
        if field.name in self._POSITION_FIELDS:
            return f"{declaration} = _dc_field(default=0, compare=False)"
        if field.name in self._PROVENANCE_FIELDS:
            return f"{declaration} = _dc_field(default=None, compare=False)"
        if field.is_sequence:
            return f"{declaration} = _dc_field(default_factory=list)"
        if field.is_optional:
            return f"{declaration} = None"
        base = self._type_names.get(field.type_name, field.type_name)
        default = self._SCALAR_DEFAULTS.get(base)
        if default is not None:
            return f"{declaration} = {default}"
        return declaration


@dataclass(frozen=True, slots=True)
class _BtrcConstructorPlan:
    constructor: AsdlConstructor
    fields: tuple[AsdlField, ...]


@dataclass(frozen=True, slots=True)
class _BtrcFieldDeclaration:
    name: str
    declared_type: str
    initializer: str


class BtrcAstRenderer:
    """Render a schema as the self-hosted compiler's data-only fat AST node."""

    _BUILTIN_TYPES: ClassVar[dict[str, str]] = {
        "identifier": "string",
        "string": "string",
        "int": "int",
        "float": "float",
        "bool": "bool",
    }
    _SCALAR_TYPES = frozenset({"int", "bool", "string", "float"})

    def __init__(self, schema: AsdlModule, keywords: frozenset[str]):
        self._schema = schema
        self._keywords = keywords
        self._type_names = self._build_type_name_map()

    def render(self) -> str:
        lines = [
            "/* Self-hosted btrc AST — fat tagged node.",
            " *",
            " * Auto-generated from src/language/ast.asdl by tools/compiler_codegen/ast.py.",
            " * DO NOT EDIT BY HAND. btrc lacks dynamic dispatch/downcast, so the AST",
            " * is one Node with a `kind` tag + the union of all fields.",
            " * This file contains data/schema declarations only; canonical formatting",
            " * belongs to the handwritten owner in syntax/identity.btrc.",
            " */",
            "",
            "import std.vector;",
            "",
        ]
        self._emit_node_kind_enum(lines)
        self._emit_simple_enums(lines)
        declarations = self._build_declarations()

        lines.append("class Node {")
        lines.append("    public int kind;")
        for declaration in declarations:
            lines.append(
                f"    public {declaration.declared_type} {declaration.name};"
            )
        lines.extend(("", "    public Node() {", "        self.kind = NK_NONE;"))
        for declaration in declarations:
            lines.append(
                f"        self.{declaration.name} = {declaration.initializer};"
            )
        lines.extend(("    }", "}"))
        return "\n".join(lines) + "\n"

    def _is_sum_type(self, schema_type: AsdlType) -> bool:
        return len(schema_type.constructors) > 1

    def _is_simple_enum(self, schema_type: AsdlType) -> bool:
        return self._is_sum_type(schema_type) and all(
            not constructor.fields for constructor in schema_type.constructors
        )

    def _to_pascal(self, name: str) -> str:
        return "".join(part[:1].upper() + part[1:] for part in name.split("_"))

    def _to_screaming_snake(self, name: str) -> str:
        result: list[str] = []
        for index, character in enumerate(name):
            if character.isupper() and index > 0:
                previous = name[index - 1]
                next_is_lower = (
                    index + 1 < len(name) and name[index + 1].islower()
                )
                if previous.islower() or previous.isdigit() or (
                    next_is_lower and previous.isupper()
                ):
                    result.append("_")
            result.append(character.upper())
        return "".join(result)

    def _safe_name(self, name: str) -> str:
        return f"{name}_" if name in self._keywords else name

    def _build_type_name_map(self) -> dict[str, str]:
        names = dict(self._BUILTIN_TYPES)
        for schema_type in self._schema.types:
            if self._is_simple_enum(schema_type):
                names[schema_type.name] = "int"
            elif self._is_sum_type(schema_type):
                names[schema_type.name] = self._to_pascal(schema_type.name)
            else:
                names[schema_type.name] = schema_type.constructors[0].name
        return names

    def _btrc_type(self, field: AsdlField) -> str:
        base = self._type_names.get(field.type_name, field.type_name)
        if field.is_sequence:
            return f"List<{base}>"
        return base

    def _fat_type(self, btrc_type: str) -> tuple[str, str]:
        if btrc_type in self._SCALAR_TYPES:
            return "scalar", btrc_type
        if btrc_type.startswith("List<"):
            inner = btrc_type[len("List<") : -1]
            if inner == "string":
                return "strlist", "Vector<string>"
            return "nodelist", "Vector<Node>"
        return "node", "Node"

    def _variant_suffix(self, category: str, declared_type: str) -> str:
        if category == "scalar":
            return declared_type
        return {
            "node": "node",
            "nodelist": "nlist",
            "strlist": "slist",
        }[category]

    def _backing_name(
        self,
        name: str,
        category: str,
        declared_type: str,
        conflicted: frozenset[str],
    ) -> str:
        if name not in conflicted:
            return name
        return f"{name}_{self._variant_suffix(category, declared_type)}"

    def _emit_node_kind_enum(self, lines: list[str]) -> None:
        lines.extend(("enum NodeKind {", "    NK_NONE = 0,"))
        for schema_type in self._schema.types:
            if self._is_simple_enum(schema_type):
                continue
            for constructor in schema_type.constructors:
                lines.append(
                    f"    NK_{self._to_screaming_snake(constructor.name)},"
                )
        lines.extend(("};", ""))

    def _emit_simple_enums(self, lines: list[str]) -> None:
        for schema_type in self._schema.types:
            if not self._is_simple_enum(schema_type):
                continue
            lines.append(f"enum {self._to_pascal(schema_type.name)} {{")
            last_index = len(schema_type.constructors) - 1
            for index, constructor in enumerate(schema_type.constructors):
                comma = "," if index < last_index else ""
                lines.append(
                    f"    {self._to_screaming_snake(constructor.name)} = {index}{comma}"
                )
            lines.extend(("};", ""))

    def _build_declarations(self) -> tuple[_BtrcFieldDeclaration, ...]:
        constructors: list[_BtrcConstructorPlan] = []
        for schema_type in self._schema.types:
            if self._is_simple_enum(schema_type):
                continue
            for constructor in schema_type.constructors:
                constructors.append(
                    _BtrcConstructorPlan(
                        constructor,
                        constructor.fields + schema_type.attributes,
                    )
                )

        seen: dict[str, set[tuple[str, str]]] = {}
        for plan in constructors:
            for field in plan.fields:
                category, declared_type = self._fat_type(self._btrc_type(field))
                seen.setdefault(self._safe_name(field.name), set()).add(
                    (category, declared_type)
                )
        conflicted = frozenset(
            name for name, uses in seen.items() if len(uses) > 1
        )

        optional_strings: dict[str, list[bool]] = {}
        for plan in constructors:
            for field in plan.fields:
                category, declared_type = self._fat_type(self._btrc_type(field))
                if category == "scalar" and declared_type == "string":
                    optional_strings.setdefault(
                        self._safe_name(field.name), []
                    ).append(field.is_optional)
        nullable_strings = frozenset(
            name
            for name, flags in optional_strings.items()
            if all(flags) and name not in conflicted
        )

        declarations: dict[str, tuple[str, str]] = {}
        declaration_order: list[str] = []
        initializers = {
            "int": "0",
            "bool": "false",
            "string": '""',
            "float": "0.0",
            "Vector<Node>": "[]",
            "Vector<string>": "[]",
            "Node": "null",
        }
        for plan in constructors:
            for field in plan.fields:
                name = self._safe_name(field.name)
                category, declared_type = self._fat_type(self._btrc_type(field))
                backing_name = self._backing_name(
                    name, category, declared_type, conflicted
                )
                is_optional_string = backing_name in nullable_strings
                if backing_name not in declarations:
                    if is_optional_string:
                        declarations[backing_name] = ("string?", "null")
                    else:
                        declarations[backing_name] = (
                            declared_type,
                            initializers[declared_type],
                        )
                    declaration_order.append(backing_name)
        return tuple(
            _BtrcFieldDeclaration(name, *declarations[name])
            for name in declaration_order
        )


class BtrcCanonicalRendererContract:
    """Verify that the handwritten canonical renderer exhausts the ASDL data."""

    _NODE_KIND = re.compile(r"^    (NK_[A-Z0-9_]+)(?: = 0)?,?$", re.MULTILINE)
    _NODE_FIELD = re.compile(
        r"^    public (?P<type>[^;]+) (?P<name>[A-Za-z_][A-Za-z0-9_]*);$",
        re.MULTILINE,
    )
    _RENDER_BRANCH = re.compile(
        r"(?:if|else if) \(node\.kind == (?P<kind>NK_[A-Z0-9_]+)\) \{"
    )
    _RENDERED_NAME = re.compile(r'string out = "\((?P<name>[A-Za-z0-9_]+)";')
    _RENDERED_FIELD = re.compile(
        r'"(?P<label>[A-Za-z_][A-Za-z0-9_]*)=" \+ '
        r'self\.(?P<formatter>canon[A-Za-z0-9_]+)\('
        r'node\.(?P<backing>[A-Za-z_][A-Za-z0-9_]*)'
    )
    _FORMATTER_BY_TYPE: ClassVar[dict[str, str]] = {
        "int": "canonInt",
        "bool": "canonBool",
        "string": "canonStr",
        "string?": "canonOptStr",
        "float": "canonFloat",
        "Node": "canonNode",
        "Vector<Node>": "canonNodeList",
        "Vector<string>": "canonStrList",
    }

    def __init__(self, schema: AsdlModule, generated_node: str):
        self._schema = schema
        self._generated_node = generated_node

    def verify(self, renderer_source: str) -> None:
        """Reject missing constructors, fields, or type-incompatible formatters."""

        renderer = self._renderer_class(renderer_source)
        constructors = self._rendered_constructors()
        expected_kinds = tuple(
            kind
            for kind in self._NODE_KIND.findall(self._generated_node)
            if kind != "NK_NONE"
        )
        branches = tuple(self._RENDER_BRANCH.finditer(renderer))
        actual_kinds = tuple(branch.group("kind") for branch in branches)
        if actual_kinds != expected_kinds:
            self._mismatch("constructor branches", expected_kinds, actual_kinds)
        if len(branches) != len(constructors):
            raise GeneratedSourceError(
                "AstCanonicalRenderer constructor count differs from ast.asdl"
            )

        node_fields = {
            match.group("name"): match.group("type")
            for match in self._NODE_FIELD.finditer(self._generated_node)
        }
        for index, (constructor, fields) in enumerate(constructors):
            start = branches[index].end()
            end = branches[index + 1].start() if index + 1 < len(branches) else len(renderer)
            body = renderer[start:end]
            rendered_name = self._RENDERED_NAME.search(body)
            if rendered_name is None or rendered_name.group("name") != constructor.name:
                actual = None if rendered_name is None else rendered_name.group("name")
                self._mismatch(
                    f"{branches[index].group('kind')} display name",
                    (constructor.name,),
                    (() if actual is None else (actual,)),
                )

            rendered_fields = tuple(self._RENDERED_FIELD.finditer(body))
            expected_labels = tuple(field.name for field in fields)
            actual_labels = tuple(field.group("label") for field in rendered_fields)
            if actual_labels != expected_labels:
                self._mismatch(
                    f"{constructor.name} rendered fields",
                    expected_labels,
                    actual_labels,
                )
            for rendered_field in rendered_fields:
                backing = rendered_field.group("backing")
                declared_type = node_fields.get(backing)
                expected_formatter = self._FORMATTER_BY_TYPE.get(declared_type or "")
                actual_formatter = rendered_field.group("formatter")
                if expected_formatter != actual_formatter:
                    raise GeneratedSourceError(
                        "AstCanonicalRenderer field formatter mismatch: "
                        f"{constructor.name}.{rendered_field.group('label')} uses "
                        f"{actual_formatter} for Node.{backing} ({declared_type!r}); "
                        f"expected {expected_formatter!r}"
                    )

    def _renderer_class(self, source: str) -> str:
        marker = "class AstCanonicalRenderer {"
        _, found, remainder = source.partition(marker)
        if not found:
            raise GeneratedSourceError("missing handwritten AstCanonicalRenderer")
        renderer, separator, _ = remainder.partition("\nclass TypeIdentity {")
        if not separator:
            raise GeneratedSourceError(
                "AstCanonicalRenderer must remain a cohesive owner before TypeIdentity"
            )
        if "public string render(Node node)" not in renderer:
            raise GeneratedSourceError("AstCanonicalRenderer must expose render(Node)")
        return renderer

    def _rendered_constructors(
        self,
    ) -> tuple[tuple[AsdlConstructor, tuple[AsdlField, ...]], ...]:
        constructors: list[tuple[AsdlConstructor, tuple[AsdlField, ...]]] = []
        for schema_type in self._schema.types:
            is_simple_enum = len(schema_type.constructors) > 1 and all(
                not constructor.fields for constructor in schema_type.constructors
            )
            if is_simple_enum:
                continue
            for constructor in schema_type.constructors:
                constructors.append(
                    (constructor, constructor.fields + schema_type.attributes)
                )
        return tuple(constructors)

    def _mismatch(
        self,
        subject: str,
        expected: tuple[str, ...],
        actual: tuple[str, ...],
    ) -> None:
        raise GeneratedSourceError(
            f"AstCanonicalRenderer {subject} differ from ast.asdl: "
            f"expected {expected!r}, got {actual!r}"
        )


class AstCatalogGenerator:
    """Own the ASDL input and both generated compiler AST artifacts."""

    _PYTHON_OUTPUT = PurePosixPath(
        "src/compiler/python/syntax/ast/generated.py"
    )
    _SELFHOST_OUTPUT = PurePosixPath(
        "src/compiler/btrc/generated/ast/node.btrc"
    )
    _SELFHOST_RENDERER = PurePosixPath(
        "src/compiler/btrc/syntax/identity.btrc"
    )

    def __init__(self, repository_root: Path):
        self._repository_root = repository_root

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        schema_path = self._repository_root / "src/language/ast.asdl"
        schema = AsdlSchemaParser(schema_path.read_text(encoding="utf-8")).parse()
        grammar = GrammarRepository(
            str(self._repository_root / "src/language/grammar.ebnf")
        ).load()
        selfhost = BtrcAstRenderer(schema, grammar.keywords).render()
        renderer_path = self._repository_root.joinpath(*self._SELFHOST_RENDERER.parts)
        BtrcCanonicalRendererContract(schema, selfhost).verify(
            renderer_path.read_text(encoding="utf-8")
        )
        return (
            GeneratedArtifact(
                path=self._PYTHON_OUTPUT,
                content=PythonAstRenderer(schema).render().encode("utf-8"),
            ),
            GeneratedArtifact(
                path=self._SELFHOST_OUTPUT,
                content=format_generated_btrc(selfhost, self._SELFHOST_OUTPUT),
            ),
        )
