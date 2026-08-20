"""Compiler-owned generation of the data-only LSP builtin catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import ClassDecl, FieldDecl, MethodDecl, PropertyDecl, TypeExpr

from . import GeneratedArtifact

INTRINSIC_STRING_MEMBERS = (
    ("len", "int", "field", (), "Length of the string (bytes)"),
    ("charAt", "char", "method", (("int", "index"),), "Character at index"),
    ("trim", "string", "method", (), "Remove leading/trailing whitespace"),
    ("lstrip", "string", "method", (), "Remove leading whitespace"),
    ("rstrip", "string", "method", (), "Remove trailing whitespace"),
    ("toUpper", "string", "method", (), "Convert to uppercase"),
    ("toLower", "string", "method", (), "Convert to lowercase"),
    ("contains", "bool", "method", (("string", "sub"),), "Check if contains substring"),
    ("startsWith", "bool", "method", (("string", "prefix"),), "Check prefix"),
    ("endsWith", "bool", "method", (("string", "suffix"),), "Check suffix"),
    ("indexOf", "int", "method", (("string", "sub"),), "Index of first occurrence"),
    (
        "lastIndexOf",
        "int",
        "method",
        (("string", "sub"),),
        "Index of last occurrence",
    ),
    (
        "substring",
        "string",
        "method",
        (("int", "start"), ("int", "end")),
        "Extract substring",
    ),
    ("equals", "bool", "method", (("string", "other"),), "Compare strings"),
    ("split", "Vector<string>", "method", (("string", "delim"),), "Split into list"),
    (
        "replace",
        "string",
        "method",
        (("string", "old"), ("string", "replacement")),
        "Replace occurrences",
    ),
    ("repeat", "string", "method", (("int", "count"),), "Repeat N times"),
    (
        "count",
        "int",
        "method",
        (("string", "sub"),),
        "Count non-overlapping occurrences",
    ),
    (
        "find",
        "int",
        "method",
        (("string", "sub"), ("int", "start")),
        "Find from start index",
    ),
    ("capitalize", "string", "method", (), "Uppercase first char"),
    ("title", "string", "method", (), "Capitalize each word"),
    ("swapCase", "string", "method", (), "Swap upper/lower case"),
    (
        "padLeft",
        "string",
        "method",
        (("int", "width"), ("char", "fill")),
        "Left-pad",
    ),
    (
        "padRight",
        "string",
        "method",
        (("int", "width"), ("char", "fill")),
        "Right-pad",
    ),
    (
        "center",
        "string",
        "method",
        (("int", "width"), ("char", "fill")),
        "Center with padding",
    ),
    ("charLen", "int", "method", (), "UTF-8 character count"),
    ("byteLen", "int", "method", (), "Byte length"),
    ("isDigitStr", "bool", "method", (), "All chars are digits"),
    ("isAlphaStr", "bool", "method", (), "All chars are alphabetic"),
    ("isBlank", "bool", "method", (), "Empty or all whitespace"),
    ("isAlnum", "bool", "method", (), "All chars are alphanumeric"),
    ("isUpper", "bool", "method", (), "All chars are uppercase"),
    ("isLower", "bool", "method", (), "All chars are lowercase"),
    ("reverse", "string", "method", (), "Reverse the string"),
    ("isEmpty", "bool", "method", (), "True if string is empty"),
    (
        "removePrefix",
        "string",
        "method",
        (("string", "prefix"),),
        "Remove prefix if present",
    ),
    (
        "removeSuffix",
        "string",
        "method",
        (("string", "suffix"),),
        "Remove suffix if present",
    ),
    ("toInt", "int", "method", (), "Parse as integer"),
    ("toFloat", "float", "method", (), "Parse as float"),
    ("toDouble", "double", "method", (), "Parse as double"),
    ("toLong", "long", "method", (), "Parse as long"),
    (
        "toBool",
        "bool",
        "method",
        (),
        'Parse as bool (false for empty, "false", "0")',
    ),
    (
        "zfill",
        "string",
        "method",
        (("int", "width"),),
        "Left-pad with zeros (preserves sign)",
    ),
)


INTRINSIC_COLLECTION_MEMBERS = MappingProxyType(
    {
        # Vector and Set higher-order methods live in stdlib source. Map.forEach is
        # an IR-generation intrinsic and therefore has no stdlib declaration.
        "Map": (
            (
                "forEach",
                "void",
                "method",
                (("fn", "callback"),),
                "Call fn(key, value) for each entry",
            ),
        ),
    }
)


INTRINSIC_FUNCTIONS = MappingProxyType(
    {
        "println": ("void", (("string", "message"),)),
        "print": ("void", (("string", "message"),)),
        "input": ("string", (("string", "prompt"),)),
        "toString": ("string", (("int", "value"),)),
        "toInt": ("int", (("string", "value"),)),
        "toFloat": ("float", (("string", "value"),)),
        "len": ("int", (("string", "s"),)),
        "range": ("Vector<int>", (("int", "n"),)),
        "exit": ("void", (("int", "code"),)),
    }
)


class BuiltinCatalogGenerationError(ValueError):
    """The stdlib cannot be represented as a deterministic builtin catalog."""


@dataclass(frozen=True, slots=True)
class BuiltinFieldSpec:
    """One public field exposed by a builtin collection type."""

    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class BuiltinMethodSpec:
    """One public or class method exposed by a builtin type."""

    name: str
    return_type: str
    parameters: tuple[tuple[str, str], ...]
    is_static: bool


@dataclass(frozen=True, slots=True)
class BuiltinClassSpec:
    """The generated API surface of one stdlib class."""

    name: str
    fields: tuple[BuiltinFieldSpec, ...]
    methods: tuple[BuiltinMethodSpec, ...]


@dataclass(frozen=True, slots=True)
class BuiltinCatalogSpec:
    """Deterministically ordered builtin collection and static class APIs."""

    collections: tuple[BuiltinClassSpec, ...]
    static_classes: tuple[BuiltinClassSpec, ...]


class BuiltinStdlibScanner:
    """Parse stdlib declarations and select the API visible to LSP features."""

    _ALWAYS_HIDDEN_FIELDS = frozenset({"cap", "occupied"})
    _ALWAYS_HIDDEN_METHODS = frozenset({"resize"})

    def __init__(self, stdlib_directory: Path):
        self._stdlib_directory = stdlib_directory

    def scan(self) -> BuiltinCatalogSpec:
        if not self._stdlib_directory.is_dir():
            raise BuiltinCatalogGenerationError(f"stdlib directory is missing: {self._stdlib_directory}")

        collections: dict[str, BuiltinClassSpec] = {}
        static_classes: dict[str, BuiltinClassSpec] = {}
        for source_path in sorted(self._stdlib_directory.glob("*.btrc")):
            for class_name, declaration in self._parse_file(source_path).items():
                declared_methods = [
                    member
                    for member in declaration.members
                    if isinstance(member, MethodDecl) and member.name != class_name
                ]
                static_methods = [member for member in declared_methods if member.access == "class"]
                instance_methods = [member for member in declared_methods if member.access in {"public", "private"}]
                if declaration.generic_params and instance_methods:
                    fields, methods = self._extract_members(declaration)
                    collections[class_name] = BuiltinClassSpec(
                        name=class_name,
                        fields=fields,
                        methods=tuple(method for method in methods if not method.is_static),
                    )
                elif static_methods and not instance_methods:
                    _fields, methods = self._extract_members(declaration)
                    static_classes[class_name] = BuiltinClassSpec(
                        name=class_name,
                        fields=(),
                        methods=methods,
                    )

        return BuiltinCatalogSpec(
            collections=tuple(collections.values()),
            static_classes=tuple(static_classes.values()),
        )

    def _parse_file(self, source_path: Path) -> dict[str, ClassDecl]:
        try:
            source = source_path.read_text(encoding="utf-8")
            source = "\n".join("" if line.strip().startswith("import ") else line for line in source.splitlines())
            program = Parser(Lexer(source, source_path.name).tokenize()).parse()
        except (OSError, UnicodeError, LexerError, ParseError) as error:
            raise BuiltinCatalogGenerationError(f"cannot scan stdlib source {source_path}: {error}") from error
        return {
            declaration.name: declaration for declaration in program.declarations if isinstance(declaration, ClassDecl)
        }

    def _extract_members(
        self,
        declaration: ClassDecl,
    ) -> tuple[tuple[BuiltinFieldSpec, ...], tuple[BuiltinMethodSpec, ...]]:
        fields: list[BuiltinFieldSpec] = []
        methods: list[BuiltinMethodSpec] = []
        for member in declaration.members:
            if isinstance(member, FieldDecl) and member.access == "public":
                if not self._is_hidden_field(member):
                    fields.append(BuiltinFieldSpec(member.name, self._type_name(member.type)))
                continue
            if isinstance(member, MethodDecl):
                if (
                    member.is_constructor
                    or member.name.startswith("__")
                    or member.access not in {"public", "class"}
                    or member.name in self._ALWAYS_HIDDEN_METHODS
                ):
                    continue
                methods.append(
                    BuiltinMethodSpec(
                        name=member.name,
                        return_type=self._type_name(member.return_type),
                        parameters=tuple(
                            (self._type_name(parameter.type), parameter.name) for parameter in member.params
                        ),
                        is_static=member.access == "class",
                    )
                )
                continue
            if (
                isinstance(member, PropertyDecl)
                and member.access == "public"
                and member.name not in self._ALWAYS_HIDDEN_FIELDS
            ):
                fields.append(BuiltinFieldSpec(member.name, self._type_name(member.type)))
        return tuple(fields), tuple(methods)

    def _is_hidden_field(self, member: FieldDecl) -> bool:
        return member.name in self._ALWAYS_HIDDEN_FIELDS or bool(member.type and member.type.pointer_depth > 0)

    def _type_name(self, type_expression: TypeExpr | None) -> str:
        if type_expression is None:
            return "void"
        result = type_expression.base
        if type_expression.generic_args:
            arguments = ", ".join(self._type_name(argument) for argument in type_expression.generic_args)
            result += f"<{arguments}>"
        if type_expression.pointer_depth > 0:
            result += "*" * type_expression.pointer_depth
        return result


class BuiltinCatalogRenderer:
    """Render a scanned builtin catalog as one immutable Python data module."""

    def render(self, catalog: BuiltinCatalogSpec) -> str:
        lines = [
            '"""Generated immutable builtin declarations for the btrc LSP.',
            "",
            "Auto-generated from stdlib .btrc files by tools/compiler_codegen/builtins.py.",
            "DO NOT EDIT BY HAND — edit the stdlib source or the generator instead.",
            "",
            '"""',
            "",
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass",
            "",
            "",
            "@dataclass(frozen=True)",
            "class BuiltinMemberSpec:",
            '    """Generated schema for one builtin field or method."""',
            "",
            "    name: str",
            "    return_type: str",
            '    kind: str  # "field" or "method"',
            "    params: tuple[tuple[str, str], ...] = ()",
            '    doc: str = ""',
            "",
            "",
            "# " + "-" * 75,
            "# Built-in type member tables",
            "# " + "-" * 75,
            "",
            "# String methods are language intrinsics (not defined in any .btrc file)",
            self._intrinsic_members("STRING_MEMBERS", INTRINSIC_STRING_MEMBERS),
            "",
        ]
        for collection in catalog.collections:
            variable_name = f"{collection.name.upper()}_MEMBERS"
            lines.extend(
                (
                    f"# Generated from src/stdlib/{collection.name.lower()}.btrc",
                    self._collection_members(
                        variable_name,
                        collection,
                        INTRINSIC_COLLECTION_MEMBERS.get(collection.name, ()),
                    ),
                    "",
                )
            )

        lines.extend(
            (
                "MEMBER_TABLES: tuple[tuple[str, tuple[BuiltinMemberSpec, ...]], ...] = (",
                '    ("string", STRING_MEMBERS),',
            )
        )
        lines.extend(
            f'    ("{collection.name}", {collection.name.upper()}_MEMBERS),' for collection in catalog.collections
        )
        lines.extend(
            (
                ")",
                "",
                "",
                "# " + "-" * 75,
                "# Stdlib static method tables",
                "# " + "-" * 75,
                "",
                "# Generated from stdlib .btrc files",
                "STDLIB_STATIC_METHODS: tuple[tuple[str, tuple[BuiltinMemberSpec, ...]], ...] = (",
            )
        )
        lines.extend(self._static_methods(class_spec) for class_spec in catalog.static_classes)
        lines.extend(
            (
                ")",
                "",
                "# Built-in free function signatures: name -> (return_type, params)",
                "BUILTIN_FUNCTION_SIGNATURES: tuple[tuple[str, tuple[str, tuple[tuple[str, str], ...]]], ...] = (",
            )
        )
        lines.extend(
            f'    ("{name}", ("{return_type}", {self._format_parameters(parameters)})),'
            for name, (return_type, parameters) in INTRINSIC_FUNCTIONS.items()
        )
        lines.append(")")
        return "\n".join(lines)

    def _collection_members(
        self,
        variable_name: str,
        collection: BuiltinClassSpec,
        intrinsics: tuple,
    ) -> str:
        lines = [f"{variable_name}: tuple[BuiltinMemberSpec, ...] = ("]
        lines.extend(
            f'    BuiltinMemberSpec("{field.name}", "{field.type_name}", "field", doc="{field.name}"),'
            for field in collection.fields
        )
        lines.extend(self._method_row(method, indent="    ") for method in collection.methods)
        for name, return_type, _kind, parameters, documentation in intrinsics:
            lines.append(
                self._raw_method_row(
                    name,
                    return_type,
                    parameters,
                    documentation,
                    indent="    ",
                )
            )
        lines.append(")")
        return "\n".join(lines)

    def _intrinsic_members(self, variable_name: str, entries: tuple) -> str:
        lines = [f"{variable_name}: tuple[BuiltinMemberSpec, ...] = ("]
        for name, return_type, kind, parameters, documentation in entries:
            escaped = self._escape(documentation)
            lines.append(
                f'    BuiltinMemberSpec("{name}", "{return_type}", "{kind}", '
                f'{self._format_parameters(parameters)}, "{escaped}"),'
            )
        lines.append(")")
        return "\n".join(lines)

    def _static_methods(self, class_spec: BuiltinClassSpec) -> str:
        lines = [f'    ("{class_spec.name}", (']
        lines.extend(self._method_row(method, indent="        ") for method in class_spec.methods)
        lines.append("    )),")
        return "\n".join(lines)

    def _method_row(self, method: BuiltinMethodSpec, *, indent: str) -> str:
        return self._raw_method_row(
            method.name,
            method.return_type,
            method.parameters,
            method.name,
            indent=indent,
        )

    def _raw_method_row(
        self,
        name: str,
        return_type: str,
        parameters: tuple[tuple[str, str], ...],
        documentation: str,
        *,
        indent: str,
    ) -> str:
        escaped = self._escape(documentation)
        return (
            f'{indent}BuiltinMemberSpec("{name}", "{return_type}", "method", '
            f'{self._format_parameters(parameters)}, "{escaped}"),'
        )

    @staticmethod
    def _format_parameters(parameters: tuple[tuple[str, str], ...]) -> str:
        if not parameters:
            return "()"
        items = ", ".join(f'("{type_name}", "{name}")' for type_name, name in parameters)
        return f"({items},)"

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


class BuiltinCatalogGenerator:
    """Generate the LSP builtin catalog artifact from stdlib declarations."""

    _OUTPUT_PATH = PurePosixPath("src/devex/lsp/catalog/generated.py")

    def __init__(self, repository_root: Path):
        self._scanner = BuiltinStdlibScanner(repository_root / "src/stdlib")
        self._renderer = BuiltinCatalogRenderer()

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        catalog = self._scanner.scan()
        content = self._renderer.render(catalog).encode("utf-8")
        return (GeneratedArtifact(self._OUTPUT_PATH, content),)
