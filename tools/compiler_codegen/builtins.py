"""Compiler-owned generation of the data-only LSP builtin catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from types import MappingProxyType

from src.compiler.python.analyzer.types import STRING_METHODS
from src.compiler.python.frontend.packages import PackageManifestReader, PackageManifestValidator
from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import ClassDecl, FieldDecl, MethodDecl, PropertyDecl, TypeExpr

from . import GeneratedArtifact

# Parameter names and documentation for the string intrinsics. Names, return
# types and parameter types come from the analyzer's STRING_METHODS table; the
# generator fails when the two disagree on which members exist or on arity.
STRING_MEMBER_DOCUMENTATION = MappingProxyType(
    {
        "len": ("field", (), "Length of the string (bytes)"),
        "byteLen": ("method", (), "Byte length"),
        "length": ("method", (), "Length of the string (bytes)"),
        "charLen": ("method", (), "UTF-8 character count"),
        "equals": ("method", ("other",), "Compare strings"),
        "contains": ("method", ("sub",), "Check if contains substring"),
        "startsWith": ("method", ("prefix",), "Check prefix"),
        "endsWith": ("method", ("suffix",), "Check suffix"),
        "indexOf": ("method", ("sub",), "Index of first occurrence"),
        "lastIndexOf": ("method", ("sub",), "Index of last occurrence"),
        "find": ("method", ("sub", "start"), "Find from start index"),
        "count": ("method", ("sub",), "Count non-overlapping occurrences"),
        "charAt": ("method", ("index",), "Character at index"),
        "isEmpty": ("method", (), "True if string is empty"),
        "isBlank": ("method", (), "Empty or all whitespace"),
        "isUpper": ("method", (), "All chars are uppercase"),
        "isLower": ("method", (), "All chars are lowercase"),
        "isAlnum": ("method", (), "All chars are alphanumeric"),
        "isDigit": ("method", (), "All chars are digits"),
        "isAlpha": ("method", (), "All chars are alphabetic"),
        "trim": ("method", (), "Remove leading/trailing whitespace"),
        "lstrip": ("method", (), "Remove leading whitespace"),
        "rstrip": ("method", (), "Remove trailing whitespace"),
        "toUpper": ("method", (), "Convert to uppercase"),
        "toLower": ("method", (), "Convert to lowercase"),
        "substring": ("method", ("start", "end"), "Extract substring"),
        "replace": ("method", ("old", "replacement"), "Replace occurrences"),
        "repeat": ("method", ("count",), "Repeat N times"),
        "reverse": ("method", (), "Reverse the string"),
        "capitalize": ("method", (), "Uppercase first char"),
        "title": ("method", (), "Capitalize each word"),
        "swapCase": ("method", (), "Swap upper/lower case"),
        "padLeft": ("method", ("width", "fill"), "Left-pad"),
        "padRight": ("method", ("width", "fill"), "Right-pad"),
        "center": ("method", ("width", "fill"), "Center with padding"),
        "zfill": ("method", ("width",), "Left-pad with zeros (preserves sign)"),
        "removePrefix": ("method", ("prefix",), "Remove prefix if present"),
        "removeSuffix": ("method", ("suffix",), "Remove suffix if present"),
        "split": ("method", ("delim",), "Split into a string array"),
        "toInt": ("method", (), "Parse as integer"),
        "toFloat": ("method", (), "Parse as float"),
        "toDouble": ("method", (), "Parse as double"),
        "toLong": ("method", (), "Parse as long"),
        "toBool": ("method", (), 'Parse as bool (false for empty, "false", "0")'),
    }
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


INTRINSIC_TYPE_MEMBERS = MappingProxyType(
    {
        "Atomic": (
            ("init", "void", "method", (("T", "value"),), "Initialize stable atomic storage"),
            ("load", "T", "method", (("MemoryOrder", "order"),), "Load with explicit C11 ordering"),
            (
                "store",
                "void",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Store with explicit C11 ordering",
            ),
            (
                "exchange",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Exchange with explicit C11 ordering",
            ),
            (
                "fetchAdd",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Atomically add and return the previous value",
            ),
            (
                "fetchSub",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Atomically subtract and return the previous value",
            ),
            (
                "fetchAnd",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Atomically AND and return the previous value",
            ),
            (
                "fetchOr",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Atomically OR and return the previous value",
            ),
            (
                "fetchXor",
                "T",
                "method",
                (("T", "value"), ("MemoryOrder", "order")),
                "Atomically XOR and return the previous value",
            ),
            (
                "compareExchangeStrong",
                "bool",
                "method",
                (
                    ("T*", "expected"),
                    ("T", "desired"),
                    ("MemoryOrder", "successOrder"),
                    ("MemoryOrder", "failureOrder"),
                ),
                "Strong compare-exchange with exact C11 ordering",
            ),
        ),
        "Span": (
            ("length", "size_t", "method", (), "Borrowed element count"),
            ("isEmpty", "bool", "method", (), "Whether the borrowed extent is empty"),
            ("isValid", "bool", "method", (), "Whether pointer and extent form a valid view"),
            (
                "tryGet",
                "bool",
                "method",
                (("size_t", "index"), ("T*", "output")),
                "Copy an in-range element without changing output on failure",
            ),
            (
                "trySet",
                "bool",
                "method",
                (("size_t", "index"), ("T", "value")),
                "Replace an in-range element",
            ),
        ),
    }
)


# The free functions every program may call without an import: the analyzer's
# print/len/range intrinsics and the hosted-ABI exit.
INTRINSIC_FUNCTIONS = MappingProxyType(
    {
        "print": ("void", (("string", "message"),)),
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
        for source_path in sorted(self._exported_modules(), key=self._source_order_key):
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

    def _exported_modules(self) -> list[Path]:
        """The catalog is the stdlib's public API: every module its manifests export.

        The root manifest exports the prelude and names each group folder as a
        path dependency (src/stdlib/README.md); group manifests export their own
        public modules and keep private providers beside them, so the manifest
        graph, not the directory listing, decides visibility.
        """
        root_manifest = self._stdlib_directory / "btrc.toml"
        if not root_manifest.is_file():
            return sorted(self._stdlib_directory.rglob("*.btrc"))
        reader = PackageManifestReader()
        validator = PackageManifestValidator()
        exported: list[Path] = []
        pending = [root_manifest]
        seen: set[Path] = set()
        while pending:
            manifest_path = pending.pop(0)
            if manifest_path in seen:
                continue
            seen.add(manifest_path)
            try:
                manifest = reader.read(str(manifest_path))
                modules = validator.exported_modules(manifest, str(manifest_path))
                dependencies = validator.dependencies(manifest, str(manifest_path))
            except (OSError, ValueError) as error:
                raise BuiltinCatalogGenerationError(f"cannot read stdlib manifest {manifest_path}: {error}") from error
            if modules is None:
                exported.extend(sorted(manifest_path.parent.rglob("*.btrc")))
            else:
                exported.extend(Path(path) for path in modules)
            for specification in dependencies.values():
                if "path" in specification:
                    pending.append((manifest_path.parent / specification["path"] / "btrc.toml").resolve())
        return exported

    @staticmethod
    def _source_order_key(source_path: PurePath) -> str:
        """Use one case-sensitive, flavor-independent order: path parts joined by '/'."""
        return "/".join(PurePath(source_path).parts)

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
            self._intrinsic_members("STRING_MEMBERS", self._string_members()),
            "",
        ]
        for type_name, members in INTRINSIC_TYPE_MEMBERS.items():
            lines.extend(
                (
                    f"# {type_name} is a compiler intrinsic (not defined in stdlib source)",
                    self._intrinsic_members(f"{type_name.upper()}_MEMBERS", members),
                    "",
                )
            )
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
        lines.extend(f'    ("{type_name}", {type_name.upper()}_MEMBERS),' for type_name in INTRINSIC_TYPE_MEMBERS)
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

    @staticmethod
    def _string_members() -> tuple:
        """The analyzer's string intrinsics, documented; a mismatch is a generation error."""

        methods = STRING_METHODS
        undocumented = sorted(set(methods) - set(STRING_MEMBER_DOCUMENTATION))
        stale = sorted(set(STRING_MEMBER_DOCUMENTATION) - set(methods))
        if undocumented or stale:
            raise BuiltinCatalogGenerationError(
                f"string member documentation differs from the analyzer (undocumented: {undocumented}; stale: {stale})"
            )
        entries = []
        for name, method in methods.items():
            kind, parameter_names, documentation = STRING_MEMBER_DOCUMENTATION[name]
            if len(parameter_names) != len(method.argument_types):
                raise BuiltinCatalogGenerationError(f"string member {name} documents the wrong parameter count")
            parameters = tuple(zip(method.argument_types, parameter_names, strict=True))
            entries.append((name, method.return_type, kind, parameters, documentation))
        return tuple(entries)

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
