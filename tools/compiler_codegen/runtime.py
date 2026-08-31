"""Shared C-runtime manifest, source marker, and catalog generation."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import GeneratedArtifact


class RuntimeManifestError(ValueError):
    """The shared runtime manifest or one of its source assets is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeSourceSection:
    """One byte-preserved helper body extracted from a cohesive C asset."""

    name: str
    source: str


class RuntimeSourceMarker:
    """Parse the version-one runtime-helper section format."""

    _BEGIN = "/* btrc-runtime-helper:begin "
    _END = "/* btrc-runtime-helper:end "
    _COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*(?:\n|$)", re.DOTALL)
    _IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

    def parse(self, asset: Path) -> tuple[RuntimeSourceSection, ...]:
        data = asset.read_bytes()
        if b"\x00" in data or b"\r" in data:
            raise RuntimeManifestError(f"runtime asset must be NUL-free UTF-8 with LF endings: {asset}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeManifestError(f"runtime asset is not UTF-8: {asset}") from error

        sections: list[RuntimeSourceSection] = []
        cursor = 0
        while True:
            begin = text.find(self._BEGIN, cursor)
            if begin < 0:
                self._validate_outside(text[cursor:], asset)
                break
            self._validate_outside(text[cursor:begin], asset)
            begin_line_end = text.find("\n", begin)
            if begin_line_end < 0:
                raise RuntimeManifestError(f"unterminated begin marker in {asset}")
            begin_line = text[begin:begin_line_end]
            if not begin_line.endswith(" */"):
                raise RuntimeManifestError(f"malformed begin marker in {asset}: {begin_line!r}")
            name = begin_line[len(self._BEGIN) : -3]
            if not self._IDENTIFIER.fullmatch(name):
                raise RuntimeManifestError(f"invalid helper marker name in {asset}: {name!r}")

            payload_start = begin_line_end + 1
            end_marker = f"{self._END}{name} */"
            end = text.find(end_marker, payload_start)
            if end < 0:
                raise RuntimeManifestError(f"missing end marker for {name} in {asset}")
            nested = text.find(self._BEGIN, payload_start, end)
            if nested >= 0:
                raise RuntimeManifestError(f"nested helper marker before {name} ends in {asset}")
            delimited_payload = text[payload_start:end]
            if not delimited_payload.endswith("\n"):
                raise RuntimeManifestError(f"helper {name} lacks its separator LF in {asset}")
            sections.append(RuntimeSourceSection(name=name, source=delimited_payload[:-1]))

            marker_end = end + len(end_marker)
            if marker_end < len(text) and text[marker_end] != "\n":
                raise RuntimeManifestError(f"end marker for {name} is not line-delimited in {asset}")
            cursor = marker_end + (1 if marker_end < len(text) else 0)

        names = [section.name for section in sections]
        if len(names) != len(set(names)):
            raise RuntimeManifestError(f"duplicate helper marker in {asset}")
        return tuple(sections)

    def _validate_outside(self, text: str, asset: Path) -> None:
        if self._COMMENT.sub("", text).strip():
            raise RuntimeManifestError(f"C behavior outside helper sections in {asset}")


@dataclass(frozen=True, slots=True)
class RuntimeCallFeatureSpec:
    prefix: str
    macro: str


@dataclass(frozen=True, slots=True)
class RuntimeHeaderFeatureSpec:
    header: str
    macro: str


@dataclass(frozen=True, slots=True)
class FreestandingRuntimeSpec:
    header: str
    header_source: str
    calls: tuple[str, ...]
    objects: tuple[str, ...]
    types: tuple[str, ...]
    literals: tuple[str, ...]
    call_features: tuple[RuntimeCallFeatureSpec, ...]
    header_features: tuple[RuntimeHeaderFeatureSpec, ...]


@dataclass(frozen=True, slots=True)
class RuntimeHelperSpec:
    name: str
    category: str
    asset: str
    source: str
    dependencies: tuple[str, ...]
    headers: tuple[str, ...]
    provided_types: tuple[str, ...]
    provided_objects: tuple[str, ...]
    source_visible: bool
    python_order: int | None
    btrc_order: int | None
    realtime_effect: str

    def order_for(self, catalog: str) -> int | None:
        if catalog == "python":
            return self.python_order
        if catalog == "btrc":
            return self.btrc_order
        raise RuntimeManifestError(f"unknown runtime catalog: {catalog}")


@dataclass(frozen=True, slots=True)
class RuntimeManifest:
    """Validated authoritative runtime specification and extracted payloads."""

    schema_version: int
    marker_version: int
    freestanding: FreestandingRuntimeSpec
    helpers: tuple[RuntimeHelperSpec, ...]

    _ROOT_KEYS = frozenset(
        {
            "schema_version",
            "marker_version",
            "freestanding_header",
            "freestanding",
            "runtime_call_features",
            "header_features",
            "helpers",
        }
    )
    _FREESTANDING_KEYS = frozenset({"calls", "objects", "types", "literals"})
    _CALL_FEATURE_KEYS = frozenset({"prefix", "macro"})
    _HEADER_FEATURE_KEYS = frozenset({"header", "macro"})
    _HELPER_KEYS = frozenset(
        {
            "name",
            "category",
            "asset",
            "dependencies",
            "headers",
            "provided_types",
            "provided_objects",
            "source_visible",
            "realtime_effect",
            "order",
        }
    )
    _OPTIONAL_HELPER_KEYS = frozenset({"provided_types", "provided_objects", "realtime_effect"})
    _REALTIME_EFFECTS = frozenset(
        {
            "safe",
            "allocation",
            "arc",
            "exceptions",
            "strings",
            "collections",
            "locks",
            "logging",
            "blocking",
            "io",
            "runtime",
            "unknown",
        }
    )
    _CATALOGS = ("python", "btrc")
    _ASSETS = (
        "core.c",
        "collections.c",
        "cycles.c",
        "mutex.c",
        "process.c",
        "strings.c",
        "threads.c",
        "trycatch.c",
        "gpu.c",
    )
    _IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

    @classmethod
    def load(cls, manifest_path: Path) -> RuntimeManifest:
        try:
            manifest_data = manifest_path.read_bytes()
            if b"\x00" in manifest_data or b"\r" in manifest_data:
                raise RuntimeManifestError(f"runtime manifest must be NUL-free UTF-8 with LF endings: {manifest_path}")
            document = tomllib.loads(manifest_data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise RuntimeManifestError(f"cannot read runtime manifest {manifest_path}: {error}") from error
        cls._require_keys(document, cls._ROOT_KEYS, "runtime manifest")
        schema_version = cls._integer(document, "schema_version", "runtime manifest")
        marker_version = cls._integer(document, "marker_version", "runtime manifest")
        if schema_version != 3 or marker_version != 1:
            raise RuntimeManifestError(
                f"unsupported runtime manifest versions: schema={schema_version}, marker={marker_version}"
            )

        asset_root = manifest_path.parent
        freestanding_table = cls._table(document, "freestanding", "runtime manifest")
        cls._require_keys(freestanding_table, cls._FREESTANDING_KEYS, "freestanding")
        header = cls._string(document, "freestanding_header", "runtime manifest")
        if Path(header).name != header or not header.endswith(".h"):
            raise RuntimeManifestError(f"invalid freestanding header path: {header!r}")
        header_path = asset_root / header
        try:
            header_data = header_path.read_bytes()
            if b"\x00" in header_data or b"\r" in header_data:
                raise RuntimeManifestError(f"freestanding header must be NUL-free UTF-8 with LF endings: {header_path}")
            header_source = header_data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise RuntimeManifestError(f"cannot read freestanding header {header_path}: {error}") from error

        call_features = cls._call_features(document.get("runtime_call_features", []))
        header_features = cls._header_features(document.get("header_features", []))
        freestanding = FreestandingRuntimeSpec(
            header=header,
            header_source=header_source,
            calls=cls._string_tuple(freestanding_table, "calls", "freestanding"),
            objects=cls._string_tuple(freestanding_table, "objects", "freestanding"),
            types=cls._string_tuple(freestanding_table, "types", "freestanding"),
            literals=cls._string_tuple(freestanding_table, "literals", "freestanding"),
            call_features=call_features,
            header_features=header_features,
        )

        helper_tables = document.get("helpers")
        if not isinstance(helper_tables, list) or not helper_tables:
            raise RuntimeManifestError("runtime manifest helpers must be a non-empty array of tables")
        marker = RuntimeSourceMarker()
        sections_by_asset: dict[str, tuple[RuntimeSourceSection, ...]] = {}
        sources: dict[str, tuple[str, str]] = {}
        for asset_name in cls._ASSETS:
            asset_path = asset_root / asset_name
            if not asset_path.is_file():
                raise RuntimeManifestError(f"missing runtime asset: {asset_path}")
            sections = marker.parse(asset_path)
            sections_by_asset[asset_name] = sections
            for section in sections:
                if section.name in sources:
                    previous_asset = sources[section.name][0]
                    raise RuntimeManifestError(
                        f"helper {section.name} appears in both {previous_asset} and {asset_name}"
                    )
                sources[section.name] = (asset_name, section.source)

        helpers: list[RuntimeHelperSpec] = []
        expected_asset_order: dict[str, list[str]] = {asset: [] for asset in cls._ASSETS}
        for index, raw_helper in enumerate(helper_tables):
            context = f"helpers[{index}]"
            if not isinstance(raw_helper, dict):
                raise RuntimeManifestError(f"{context} must be a table")
            cls._require_keys(
                raw_helper,
                cls._HELPER_KEYS,
                context,
                optional=cls._OPTIONAL_HELPER_KEYS,
            )
            name = cls._string(raw_helper, "name", context)
            category = cls._string(raw_helper, "category", context)
            asset = cls._string(raw_helper, "asset", context)
            if not cls._IDENTIFIER.fullmatch(name):
                raise RuntimeManifestError(f"{context}.name is not a C identifier: {name!r}")
            if not cls._IDENTIFIER.fullmatch(category):
                raise RuntimeManifestError(f"{context}.category is not an identifier: {category!r}")
            if asset not in cls._ASSETS:
                raise RuntimeManifestError(f"{context}.asset is not a supported runtime asset: {asset!r}")
            source_entry = sources.get(name)
            if source_entry is None:
                raise RuntimeManifestError(f"missing source marker for helper {name}")
            if source_entry[0] != asset:
                raise RuntimeManifestError(
                    f"helper {name} declares asset {asset}, but its marker is in {source_entry[0]}"
                )
            order = cls._table(raw_helper, "order", context)
            cls._require_keys(order, frozenset(cls._CATALOGS), f"{context}.order", allow_missing=True)
            if not order:
                raise RuntimeManifestError(f"{context}.order must name at least one compiler catalog")
            python_order = cls._optional_order(order, "python", context)
            btrc_order = cls._optional_order(order, "btrc", context)
            source_visible = raw_helper.get("source_visible")
            if type(source_visible) is not bool:
                raise RuntimeManifestError(f"{context}.source_visible must be a boolean")
            realtime_effect = raw_helper.get("realtime_effect", "unknown")
            if not isinstance(realtime_effect, str) or realtime_effect not in cls._REALTIME_EFFECTS:
                raise RuntimeManifestError(f"{context}.realtime_effect is invalid")
            dependencies = cls._string_tuple(raw_helper, "dependencies", context)
            headers = cls._string_tuple(raw_helper, "headers", context)
            provided_types = cls._provided_identifiers(
                raw_helper,
                "provided_types",
                source_entry[1],
                context,
            )
            provided_objects = cls._provided_identifiers(
                raw_helper,
                "provided_objects",
                source_entry[1],
                context,
            )
            helpers.append(
                RuntimeHelperSpec(
                    name=name,
                    category=category,
                    asset=asset,
                    source=source_entry[1],
                    dependencies=dependencies,
                    headers=headers,
                    provided_types=provided_types,
                    provided_objects=provided_objects,
                    source_visible=source_visible,
                    python_order=python_order,
                    btrc_order=btrc_order,
                    realtime_effect=realtime_effect,
                )
            )
            expected_asset_order[asset].append(name)

        manifest = cls(
            schema_version=schema_version,
            marker_version=marker_version,
            freestanding=freestanding,
            helpers=tuple(helpers),
        )
        manifest._validate(sections_by_asset, expected_asset_order)
        return manifest

    def helpers_for(self, catalog: str) -> tuple[RuntimeHelperSpec, ...]:
        if catalog not in self._CATALOGS:
            raise RuntimeManifestError(f"unknown runtime catalog: {catalog}")
        members = [helper for helper in self.helpers if helper.order_for(catalog) is not None]
        return tuple(sorted(members, key=lambda helper: helper.order_for(catalog)))

    def _validate(
        self,
        sections_by_asset: dict[str, tuple[RuntimeSourceSection, ...]],
        expected_asset_order: dict[str, list[str]],
    ) -> None:
        names = [helper.name for helper in self.helpers]
        if len(names) != len(set(names)):
            raise RuntimeManifestError("runtime helper names must be unique")
        type_providers = {
            provided_type: helper.name for helper in self.helpers for provided_type in helper.provided_types
        }
        provided_type_count = sum(len(helper.provided_types) for helper in self.helpers)
        if len(type_providers) != provided_type_count:
            raise RuntimeManifestError("runtime provided types must have exactly one provider")
        object_providers = {
            provided_object: helper.name for helper in self.helpers for provided_object in helper.provided_objects
        }
        provided_object_count = sum(len(helper.provided_objects) for helper in self.helpers)
        if len(object_providers) != provided_object_count:
            raise RuntimeManifestError("runtime provided objects must have exactly one provider")
        known = set(names)
        for helper in self.helpers:
            self._unique(helper.dependencies, f"helper {helper.name} dependencies")
            self._unique(helper.headers, f"helper {helper.name} headers")
            unknown = set(helper.dependencies) - known
            if unknown:
                raise RuntimeManifestError(
                    f"helper {helper.name} has unknown dependencies: {', '.join(sorted(unknown))}"
                )
        for asset, sections in sections_by_asset.items():
            actual = [section.name for section in sections]
            expected = expected_asset_order[asset]
            if actual != expected:
                raise RuntimeManifestError(
                    f"helper marker order for {asset} differs from manifest: expected {expected!r}, got {actual!r}"
                )
        for catalog in self._CATALOGS:
            helpers = self.helpers_for(catalog)
            orders = [helper.order_for(catalog) for helper in helpers]
            if orders != list(range(len(helpers))):
                raise RuntimeManifestError(f"{catalog} helper order must be unique and dense from zero")
            members = {helper.name for helper in helpers}
            for helper in helpers:
                unavailable = set(helper.dependencies) - members
                if unavailable:
                    raise RuntimeManifestError(
                        f"{catalog} helper {helper.name} depends on unavailable helpers: "
                        f"{', '.join(sorted(unavailable))}"
                    )
            self._validate_acyclic(catalog, helpers)
        self._unique(self.freestanding.calls, "freestanding calls")
        self._unique(self.freestanding.objects, "freestanding objects")
        self._unique(self.freestanding.types, "freestanding types")
        self._unique(self.freestanding.literals, "freestanding literals")
        self._unique(tuple(feature.prefix for feature in self.freestanding.call_features), "runtime call prefixes")
        self._unique(tuple(feature.header for feature in self.freestanding.header_features), "runtime feature headers")

    @classmethod
    def _validate_acyclic(cls, catalog: str, helpers: tuple[RuntimeHelperSpec, ...]) -> None:
        index = {helper.name: helper for helper in helpers}
        state: dict[str, int] = {}

        def visit(name: str, path: tuple[str, ...]) -> None:
            current = state.get(name, 0)
            if current == 2:
                return
            if current == 1:
                raise RuntimeManifestError(f"{catalog} runtime dependency cycle: {' -> '.join((*path, name))}")
            state[name] = 1
            for dependency in index[name].dependencies:
                visit(dependency, (*path, name))
            state[name] = 2

        for helper in helpers:
            visit(helper.name, ())

    @classmethod
    def _call_features(cls, value: Any) -> tuple[RuntimeCallFeatureSpec, ...]:
        if not isinstance(value, list):
            raise RuntimeManifestError("runtime_call_features must be an array of tables")
        features: list[RuntimeCallFeatureSpec] = []
        for index, item in enumerate(value):
            context = f"runtime_call_features[{index}]"
            if not isinstance(item, dict):
                raise RuntimeManifestError(f"{context} must be a table")
            cls._require_keys(item, cls._CALL_FEATURE_KEYS, context)
            features.append(
                RuntimeCallFeatureSpec(
                    prefix=cls._string(item, "prefix", context),
                    macro=cls._string(item, "macro", context),
                )
            )
        return tuple(features)

    @classmethod
    def _header_features(cls, value: Any) -> tuple[RuntimeHeaderFeatureSpec, ...]:
        if not isinstance(value, list):
            raise RuntimeManifestError("header_features must be an array of tables")
        features: list[RuntimeHeaderFeatureSpec] = []
        for index, item in enumerate(value):
            context = f"header_features[{index}]"
            if not isinstance(item, dict):
                raise RuntimeManifestError(f"{context} must be a table")
            cls._require_keys(item, cls._HEADER_FEATURE_KEYS, context)
            features.append(
                RuntimeHeaderFeatureSpec(
                    header=cls._string(item, "header", context),
                    macro=cls._string(item, "macro", context),
                )
            )
        return tuple(features)

    @staticmethod
    def _require_keys(
        table: dict[str, Any],
        allowed: frozenset[str],
        context: str,
        *,
        allow_missing: bool = False,
        optional: frozenset[str] = frozenset(),
    ) -> None:
        unknown = set(table) - allowed
        if unknown:
            raise RuntimeManifestError(f"unknown {context} keys: {', '.join(sorted(unknown))}")
        if not allow_missing:
            missing = allowed - optional - set(table)
            if missing:
                raise RuntimeManifestError(f"missing {context} keys: {', '.join(sorted(missing))}")

    @staticmethod
    def _table(table: dict[str, Any], key: str, context: str) -> dict[str, Any]:
        value = table.get(key)
        if not isinstance(value, dict):
            raise RuntimeManifestError(f"{context}.{key} must be a table")
        return value

    @staticmethod
    def _string(table: dict[str, Any], key: str, context: str) -> str:
        value = table.get(key)
        if not isinstance(value, str) or not value:
            raise RuntimeManifestError(f"{context}.{key} must be a non-empty string")
        return value

    @staticmethod
    def _integer(table: dict[str, Any], key: str, context: str) -> int:
        value = table.get(key)
        if type(value) is not int:
            raise RuntimeManifestError(f"{context}.{key} must be an integer")
        return value

    @classmethod
    def _optional_order(cls, order: dict[str, Any], catalog: str, context: str) -> int | None:
        if catalog not in order:
            return None
        value = order[catalog]
        if type(value) is not int or value < 0:
            raise RuntimeManifestError(f"{context}.order.{catalog} must be a non-negative integer")
        return value

    @classmethod
    def _string_tuple(cls, table: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
        value = table.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise RuntimeManifestError(f"{context}.{key} must be an array of non-empty strings")
        result = tuple(value)
        cls._unique(result, f"{context}.{key}")
        return result

    @classmethod
    def _optional_string_tuple(cls, table: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
        if key not in table:
            return ()
        return cls._string_tuple(table, key, context)

    @classmethod
    def _provided_identifiers(
        cls,
        table: dict[str, Any],
        key: str,
        source: str,
        context: str,
    ) -> tuple[str, ...]:
        identifiers = cls._optional_string_tuple(table, key, context)
        invalid = [identifier for identifier in identifiers if not cls._IDENTIFIER.fullmatch(identifier)]
        if invalid:
            raise RuntimeManifestError(f"{context}.{key} contains non-C identifiers: {', '.join(invalid)}")
        absent = [identifier for identifier in identifiers if not re.search(rf"\b{re.escape(identifier)}\b", source)]
        if absent:
            raise RuntimeManifestError(f"{context}.{key} are absent from helper source: {', '.join(absent)}")
        return identifiers

    @staticmethod
    def _unique(values: tuple[str, ...], context: str) -> None:
        if len(values) != len(set(values)):
            raise RuntimeManifestError(f"{context} must not contain duplicates")


class RuntimeCatalogGenerator:
    """Render compiler-specific immutable runtime catalog data."""

    _PYTHON_PATH = PurePosixPath("src/compiler/python/runtime/generated.py")
    _BTRC_PATH = PurePosixPath("src/compiler/btrc/generated/runtime/catalog.btrc")
    _PYTHON_STRING_CHUNK = 72
    _BTRC_STRING_CHUNK_BYTES = 1024

    def __init__(self, manifest: RuntimeManifest):
        self._manifest = manifest

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        return (
            GeneratedArtifact(self._PYTHON_PATH, self._render_python().encode("utf-8")),
            GeneratedArtifact(self._BTRC_PATH, self._render_btrc().encode("utf-8")),
        )

    def _render_python(self) -> str:
        lines = [
            '"""Generated shared runtime data. Do not edit by hand."""',
            "",
            "from typing import NamedTuple",
            "",
            "",
            "class GeneratedRuntimeHelperRow(NamedTuple):",
            "    category: str",
            "    name: str",
            "    c_source: str",
            "    depends_on: tuple[str, ...]",
            "    required_headers: tuple[str, ...]",
            "    provided_types: tuple[str, ...]",
            "    provided_objects: tuple[str, ...]",
            "    source_visible: bool",
            "    realtime_effect: str",
            "",
            "",
            "RUNTIME_HELPER_ROWS: tuple[GeneratedRuntimeHelperRow, ...] = (",
        ]
        for helper in self._manifest.helpers_for("python"):
            lines.extend(
                [
                    "    GeneratedRuntimeHelperRow(",
                    f"        category={helper.category!r},",
                    f"        name={helper.name!r},",
                    "        c_source=(",
                ]
            )
            lines.extend(self._python_string_lines(helper.source, 12))
            lines.extend(
                [
                    "        ),",
                    f"        depends_on={helper.dependencies!r},",
                    f"        required_headers={helper.headers!r},",
                    f"        provided_types={helper.provided_types!r},",
                    f"        provided_objects={helper.provided_objects!r},",
                    f"        source_visible={helper.source_visible!r},",
                    f"        realtime_effect={helper.realtime_effect!r},",
                    "    ),",
                ]
            )
        lines.extend([")", ""])
        self._append_python_tuple(lines, "C_RUNTIME_CALLS", self._manifest.freestanding.calls)
        self._append_python_tuple(lines, "C_RUNTIME_OBJECTS", self._manifest.freestanding.objects)
        self._append_python_tuple(lines, "C_RUNTIME_TYPES", self._manifest.freestanding.types)
        self._append_python_tuple(lines, "C_RUNTIME_LITERALS", self._manifest.freestanding.literals)
        self._append_python_pairs(
            lines,
            "RUNTIME_CALL_FEATURES",
            tuple((feature.prefix, feature.macro) for feature in self._manifest.freestanding.call_features),
        )
        self._append_python_pairs(
            lines,
            "HEADER_FEATURES",
            tuple((feature.header, feature.macro) for feature in self._manifest.freestanding.header_features),
        )
        lines.extend(
            [
                "RUNTIME_HEADER = (",
                *self._python_string_lines(self._manifest.freestanding.header_source, 4),
                ")",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_btrc(self) -> str:
        lines = [
            "/* Generated shared runtime data. Do not edit by hand. */",
            "",
            "import std.vector;",
            "",
            "class GeneratedRuntimeHelperRow {",
            "    public string category;",
            "    public string name;",
            "    public Vector<string> source_chunks;",
            "    public Vector<string> dependencies;",
            "    public Vector<string> headers;",
            "    public Vector<string> provided_types;",
            "    public Vector<string> provided_objects;",
            "    public bool source_visible;",
            "    public string realtime_effect;",
            "",
            "    public GeneratedRuntimeHelperRow(",
            "            string category,",
            "            string name,",
            "            Vector<string> source_chunks,",
            "            Vector<string> dependencies,",
            "            Vector<string> headers,",
            "            Vector<string> provided_types,",
            "            Vector<string> provided_objects,",
            "            bool source_visible,",
            "            string realtime_effect) {",
            "        self.category = category;",
            "        self.name = name;",
            "        self.source_chunks = source_chunks;",
            "        self.dependencies = dependencies;",
            "        self.headers = headers;",
            "        self.provided_types = provided_types;",
            "        self.provided_objects = provided_objects;",
            "        self.source_visible = source_visible;",
            "        self.realtime_effect = realtime_effect;",
            "    }",
            "}",
            "",
            "class GeneratedRuntimeCatalogData {",
            "    public Vector<GeneratedRuntimeHelperRow> rows;",
            "",
            "    private Vector<string> emptyStrings() {",
            "        Vector<string> values = [];",
            "        return values;",
            "    }",
            "",
            "    public GeneratedRuntimeCatalogData() {",
            "        self.rows = [];",
        ]
        # One constructor holding every row compiled into a single C function of
        # tens of thousands of lines, and a C optimizer's cost grows superlinearly
        # with function size. The rows and their order are unchanged; they are just
        # spread across methods small enough to stay in the linear regime.
        blocks: list[list[str]] = []
        for helper in self._manifest.helpers_for("btrc"):
            block = [
                "        self.rows.push(GeneratedRuntimeHelperRow(",
                f"            {self._btrc_string(helper.category)},",
                f"            {self._btrc_string(helper.name)},",
                "            [",
            ]
            for chunk in self._btrc_chunks(helper.source):
                block.append(f"                {self._btrc_string(chunk)},")
            block.extend(
                [
                    "            ],",
                    f"            {self._btrc_vector(helper.dependencies)},",
                    f"            {self._btrc_vector(helper.headers)},",
                    f"            {self._btrc_vector(helper.provided_types)},",
                    f"            {self._btrc_vector(helper.provided_objects)},",
                    f"            {'true' if helper.source_visible else 'false'},",
                    f"            {self._btrc_string(helper.realtime_effect)}));",
                ]
            )
            blocks.append(block)
        methods: list[str] = []
        for start in range(0, len(blocks), self.BTRC_ROWS_PER_METHOD):
            name = f"pushRows{start // self.BTRC_ROWS_PER_METHOD}"
            lines.append(f"        self.{name}();")
            methods.append(f"    private void {name}() {{")
            for block in blocks[start : start + self.BTRC_ROWS_PER_METHOD]:
                methods.extend(block)
            methods.extend(["    }", ""])
        lines.extend(["    }", ""])
        lines.extend(methods)
        lines.extend(["}", ""])
        return "\n".join(lines)

    BTRC_ROWS_PER_METHOD = 8

    def _python_string_lines(self, value: str, indent: int) -> list[str]:
        prefix = " " * indent
        if not value:
            return [f'{prefix}""']
        return [
            f"{prefix}{value[index : index + self._PYTHON_STRING_CHUNK]!r}"
            for index in range(0, len(value), self._PYTHON_STRING_CHUNK)
        ]

    @staticmethod
    def _append_python_tuple(lines: list[str], name: str, values: tuple[str, ...]) -> None:
        lines.append(f"{name}: tuple[str, ...] = (")
        lines.extend(f"    {value!r}," for value in values)
        lines.extend([")", ""])

    @staticmethod
    def _append_python_pairs(lines: list[str], name: str, values: tuple[tuple[str, str], ...]) -> None:
        lines.append(f"{name}: tuple[tuple[str, str], ...] = (")
        lines.extend(f"    ({left!r}, {right!r})," for left, right in values)
        lines.extend([")", ""])

    def _btrc_chunks(self, value: str) -> tuple[str, ...]:
        chunks: list[str] = []
        current: list[str] = []
        current_bytes = 0
        for character in value:
            width = len(character.encode("utf-8"))
            if current and current_bytes + width > self._BTRC_STRING_CHUNK_BYTES:
                chunks.append("".join(current))
                current = []
                current_bytes = 0
            current.append(character)
            current_bytes += width
        if current or not chunks:
            chunks.append("".join(current))
        return tuple(chunks)

    @staticmethod
    def _btrc_string(value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\b", "\\b")
            .replace("\f", "\\f")
        )
        return f'"{escaped}"'

    @classmethod
    def _btrc_vector(cls, values: tuple[str, ...]) -> str:
        if not values:
            return "self.emptyStrings()"
        return "[" + ", ".join(cls._btrc_string(value) for value in values) + "]"
