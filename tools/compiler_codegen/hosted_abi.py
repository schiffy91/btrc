"""Validated hosted-C ABI manifest and compiler catalog generation."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import GeneratedArtifact
from .runtime import RuntimeManifest


class HostedAbiManifestError(ValueError):
    """The shared hosted-ABI specification is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class HostedAbiTypeSpec:
    """One exact C type shape used at a hosted function boundary."""

    base: str
    pointer_depth: int
    is_const: bool
    generic_args: tuple[HostedAbiTypeSpec, ...] = ()

    def canonical(self) -> dict[str, object]:
        result: dict[str, object] = {
            "base": self.base,
            "pointer_depth": self.pointer_depth,
            "is_const": self.is_const,
        }
        if self.generic_args:
            result["generic_args"] = [argument.canonical() for argument in self.generic_args]
        return result


@dataclass(frozen=True, slots=True)
class HostedAbiParameterSpec:
    """One exact hosted parameter and its ownership effect."""

    type_shape: HostedAbiTypeSpec
    effect: str
    callback_lifetime: str | None = None

    def canonical(self) -> dict[str, object]:
        result = {**self.type_shape.canonical(), "effect": self.effect}
        if self.callback_lifetime is not None:
            result["callback_lifetime"] = self.callback_lifetime
        return result


@dataclass(frozen=True, slots=True)
class HostedAbiFunctionSpec:
    """One exact hosted function signature and lifetime contract."""

    name: str
    origin: str
    result: HostedAbiTypeSpec
    parameters_known: bool
    parameters: tuple[HostedAbiParameterSpec, ...]
    variadic: bool
    semantic_result: HostedAbiTypeSpec | None
    return_effect: str
    return_alias_parameter: int | None
    return_alias_null_effect: str | None
    raw_lifetime: bool
    return_deallocator: str | None
    return_alias_shape: str | None
    consume_deallocator: str | None
    return_alias_null_deallocator: str | None

    def canonical(self) -> dict[str, object]:
        return {
            "name": self.name,
            "origin": self.origin,
            "result": self.result.canonical(),
            "parameters_known": self.parameters_known,
            "parameters": [parameter.canonical() for parameter in self.parameters],
            "variadic": self.variadic,
            "semantic_result": (
                self.semantic_result.canonical() if self.semantic_result is not None else None
            ),
            "return_effect": self.return_effect,
            "return_alias_parameter": self.return_alias_parameter,
            "return_alias_null_effect": self.return_alias_null_effect,
            "raw_lifetime": self.raw_lifetime,
            "return_deallocator": self.return_deallocator,
            "return_alias_shape": self.return_alias_shape,
            "consume_deallocator": self.consume_deallocator,
            "return_alias_null_deallocator": self.return_alias_null_deallocator,
        }


@dataclass(frozen=True, slots=True)
class HostedAbiNameSets:
    """Complete compiler-owned hosted namespaces and native audit sets."""

    functions: tuple[str, ...]
    macros: tuple[str, ...]
    objects: tuple[str, ...]
    types: tuple[str, ...]
    typedefs: tuple[str, ...]
    owned: tuple[str, ...]
    native: tuple[str, ...]
    native_internal: tuple[str, ...]
    runtime_adopting_helpers: tuple[str, ...]

    def canonical(self) -> dict[str, object]:
        return {
            "functions": list(self.functions),
            "macros": list(self.macros),
            "objects": list(self.objects),
            "types": list(self.types),
            "typedefs": list(self.typedefs),
            "owned": list(self.owned),
            "native": list(self.native),
            "native_internal": list(self.native_internal),
            "runtime_adopting_helpers": list(self.runtime_adopting_helpers),
        }


@dataclass(frozen=True, slots=True)
class HostedAbiPlatformSets:
    """Names contributed by supported hosted platform headers."""

    functions: tuple[str, ...]
    macros: tuple[str, ...]
    objects: tuple[str, ...]
    types: tuple[str, ...]
    typedefs: tuple[str, ...]

    def canonical(self) -> dict[str, object]:
        return {
            "functions": list(self.functions),
            "macros": list(self.macros),
            "objects": list(self.objects),
            "types": list(self.types),
            "typedefs": list(self.typedefs),
        }


@dataclass(frozen=True, slots=True)
class HostedAbiProvenanceSpec:
    """Compiler-authenticated source markers used by trust decisions."""

    stdlib_source_marker: str
    user_source_marker: str

    def canonical(self) -> dict[str, object]:
        return {
            "stdlib_source_marker": self.stdlib_source_marker,
            "user_source_marker": self.user_source_marker,
        }


@dataclass(frozen=True, slots=True)
class HostedAbiManifest:
    """Validated authoritative hosted ABI shared by both compilers."""

    schema_version: int
    provenance: HostedAbiProvenanceSpec
    names: HostedAbiNameSets
    platform: HostedAbiPlatformSets
    functions: tuple[HostedAbiFunctionSpec, ...]

    _ROOT_KEYS = frozenset({"schema_version", "provenance", "names", "platform", "functions"})
    _PROVENANCE_KEYS = frozenset({"stdlib_source_marker", "user_source_marker"})
    _NAME_KEYS = frozenset(
        {
            "functions",
            "macros",
            "objects",
            "types",
            "typedefs",
            "owned",
            "native",
            "native_internal",
            "runtime_adopting_helpers",
        }
    )
    _PLATFORM_KEYS = frozenset({"functions", "macros", "objects", "types", "typedefs"})
    _FUNCTION_REQUIRED_KEYS = frozenset(
        {
            "name",
            "origin",
            "result",
            "parameters_known",
            "parameters",
            "variadic",
            "return_effect",
            "raw_lifetime",
        }
    )
    _FUNCTION_OPTIONAL_KEYS = frozenset(
        {
            "semantic_result",
            "return_alias_parameter",
            "return_alias_null_effect",
            "return_deallocator",
            "return_alias_shape",
            "consume_deallocator",
            "return_alias_null_deallocator",
        }
    )
    _TYPE_REQUIRED_KEYS = frozenset({"base", "pointer_depth", "is_const"})
    _TYPE_KEYS = _TYPE_REQUIRED_KEYS | frozenset({"generic_args"})
    _PARAMETER_KEYS = _TYPE_KEYS | frozenset({"effect", "callback_lifetime"})
    _PARAMETER_REQUIRED_KEYS = _TYPE_REQUIRED_KEYS | frozenset({"effect"})
    _EFFECTS = frozenset({"value", "read", "mutate", "consume", "unknown"})
    _CALLBACK_LIFETIMES = frozenset({"during_call", "stored_until_unregister"})
    _RETURN_EFFECTS = frozenset({"value", "fresh", "alias", "independent", "opaque"})
    _ALIAS_SHAPES = frozenset({"exact", "interior", "dependent"})
    _NULL_ALIAS_EFFECTS = frozenset({"fresh", "independent", "opaque"})
    _IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

    @classmethod
    def load(cls, manifest_path: Path, runtime: RuntimeManifest) -> HostedAbiManifest:
        try:
            raw = manifest_path.read_bytes()
            if b"\x00" in raw or b"\r" in raw:
                raise HostedAbiManifestError(
                    f"hosted ABI manifest must be NUL-free UTF-8 with LF endings: {manifest_path}"
                )
            document = tomllib.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise HostedAbiManifestError(
                f"cannot read hosted ABI manifest {manifest_path}: {error}"
            ) from error

        cls._require_keys(document, cls._ROOT_KEYS, "hosted ABI manifest")
        schema_version = cls._integer(document, "schema_version", "hosted ABI manifest")
        if schema_version != 2:
            raise HostedAbiManifestError(
                f"unsupported hosted ABI schema version: {schema_version}"
            )

        provenance_table = cls._table(document, "provenance", "hosted ABI manifest")
        cls._require_keys(provenance_table, cls._PROVENANCE_KEYS, "provenance")
        provenance = HostedAbiProvenanceSpec(
            stdlib_source_marker=cls._string(
                provenance_table, "stdlib_source_marker", "provenance"
            ),
            user_source_marker=cls._string(
                provenance_table, "user_source_marker", "provenance"
            ),
        )

        names_table = cls._table(document, "names", "hosted ABI manifest")
        cls._require_keys(names_table, cls._NAME_KEYS, "names")
        names = HostedAbiNameSets(
            functions=cls._name_tuple(names_table, "functions", "names"),
            macros=cls._name_tuple(names_table, "macros", "names"),
            objects=cls._name_tuple(names_table, "objects", "names"),
            types=cls._name_tuple(names_table, "types", "names"),
            typedefs=cls._name_tuple(names_table, "typedefs", "names"),
            owned=cls._name_tuple(names_table, "owned", "names"),
            native=cls._name_tuple(names_table, "native", "names"),
            native_internal=cls._name_tuple(names_table, "native_internal", "names"),
            runtime_adopting_helpers=cls._name_tuple(
                names_table, "runtime_adopting_helpers", "names"
            ),
        )

        platform_table = cls._table(document, "platform", "hosted ABI manifest")
        cls._require_keys(platform_table, cls._PLATFORM_KEYS, "platform")
        platform = HostedAbiPlatformSets(
            functions=cls._name_tuple(platform_table, "functions", "platform"),
            macros=cls._name_tuple(platform_table, "macros", "platform"),
            objects=cls._name_tuple(platform_table, "objects", "platform"),
            types=cls._name_tuple(platform_table, "types", "platform"),
            typedefs=cls._name_tuple(platform_table, "typedefs", "platform"),
        )

        raw_functions = document.get("functions")
        if not isinstance(raw_functions, list) or not raw_functions:
            raise HostedAbiManifestError("functions must be a non-empty array of tables")
        functions = tuple(
            cls._function(raw_function, index)
            for index, raw_function in enumerate(raw_functions)
        )
        manifest = cls(
            schema_version=schema_version,
            provenance=provenance,
            names=names,
            platform=platform,
            functions=functions,
        )
        manifest._validate(runtime)
        return manifest

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "provenance": self.provenance.canonical(),
            "names": self.names.canonical(),
            "platform": self.platform.canonical(),
            "functions": [function.canonical() for function in self.functions],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _function(cls, value: Any, index: int) -> HostedAbiFunctionSpec:
        context = f"functions[{index}]"
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._require_keys(
            value,
            cls._FUNCTION_REQUIRED_KEYS | cls._FUNCTION_OPTIONAL_KEYS,
            context,
            required=cls._FUNCTION_REQUIRED_KEYS,
        )
        raw_parameters = value.get("parameters")
        if not isinstance(raw_parameters, list):
            raise HostedAbiManifestError(f"{context}.parameters must be an array of tables")
        parameters = tuple(
            cls._parameter(parameter, parameter_index, context)
            for parameter_index, parameter in enumerate(raw_parameters)
        )
        return HostedAbiFunctionSpec(
            name=cls._identifier(value, "name", context),
            origin=cls._identifier(value, "origin", context),
            result=cls._type_shape(value.get("result"), f"{context}.result"),
            parameters_known=cls._boolean(value, "parameters_known", context),
            parameters=parameters,
            variadic=cls._boolean(value, "variadic", context),
            semantic_result=(
                cls._type_shape(value["semantic_result"], f"{context}.semantic_result")
                if "semantic_result" in value
                else None
            ),
            return_effect=cls._string(value, "return_effect", context),
            return_alias_parameter=cls._optional_integer(value, "return_alias_parameter", context),
            return_alias_null_effect=cls._optional_string(
                value, "return_alias_null_effect", context
            ),
            raw_lifetime=cls._boolean(value, "raw_lifetime", context),
            return_deallocator=cls._optional_string(value, "return_deallocator", context),
            return_alias_shape=cls._optional_string(value, "return_alias_shape", context),
            consume_deallocator=cls._optional_string(value, "consume_deallocator", context),
            return_alias_null_deallocator=cls._optional_string(
                value, "return_alias_null_deallocator", context
            ),
        )

    @classmethod
    def _parameter(
        cls, value: Any, index: int, function_context: str
    ) -> HostedAbiParameterSpec:
        context = f"{function_context}.parameters[{index}]"
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._require_keys(
            value,
            cls._PARAMETER_KEYS,
            context,
            required=cls._PARAMETER_REQUIRED_KEYS,
        )
        shape = cls._type_shape(
            {key: value[key] for key in cls._TYPE_KEYS if key in value}, context
        )
        return HostedAbiParameterSpec(
            type_shape=shape,
            effect=cls._string(value, "effect", context),
            callback_lifetime=cls._optional_string(value, "callback_lifetime", context),
        )

    @classmethod
    def _type_shape(cls, value: Any, context: str) -> HostedAbiTypeSpec:
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._require_keys(value, cls._TYPE_KEYS, context, required=cls._TYPE_REQUIRED_KEYS)
        base = cls._string(value, "base", context)
        pointer_depth = cls._integer(value, "pointer_depth", context)
        if pointer_depth < 0:
            raise HostedAbiManifestError(f"{context}.pointer_depth must be non-negative")
        raw_generic_args = value.get("generic_args", [])
        if not isinstance(raw_generic_args, list):
            raise HostedAbiManifestError(f"{context}.generic_args must be an array of tables")
        generic_args = tuple(
            cls._type_shape(argument, f"{context}.generic_args[{index}]")
            for index, argument in enumerate(raw_generic_args)
        )
        return HostedAbiTypeSpec(
            base=base,
            pointer_depth=pointer_depth,
            is_const=cls._boolean(value, "is_const", context),
            generic_args=generic_args,
        )

    def _validate(self, runtime: RuntimeManifest) -> None:
        if self.provenance.stdlib_source_marker == self.provenance.user_source_marker:
            raise HostedAbiManifestError("hosted ABI provenance markers must be distinct")
        for marker in (
            self.provenance.stdlib_source_marker,
            self.provenance.user_source_marker,
        ):
            if not marker.startswith("compiler:"):
                raise HostedAbiManifestError(
                    f"hosted ABI provenance marker is not compiler-authenticated: {marker!r}"
                )

        function_names = tuple(function.name for function in self.functions)
        if function_names != tuple(sorted(function_names)):
            raise HostedAbiManifestError("exact hosted functions must be sorted by name")
        self._unique(function_names, "exact hosted function names")
        exact = set(function_names)
        declared_functions = set(self.names.functions)
        if not exact <= declared_functions:
            missing = sorted(exact - declared_functions)
            raise HostedAbiManifestError(
                f"exact hosted functions missing from owned function names: {missing!r}"
            )
        expected_owned = (
            declared_functions
            | set(self.names.macros)
            | set(self.names.objects)
            | set(self.names.types)
        )
        if set(self.names.owned) != expected_owned:
            raise HostedAbiManifestError("names.owned differs from the hosted namespace union")
        if not set(self.names.typedefs) <= set(self.names.types):
            raise HostedAbiManifestError("hosted typedef names must be included in type names")
        if not set(self.names.native) <= exact:
            raise HostedAbiManifestError("hosted native names must have exact function specs")

        final_sets = {
            "functions": set(self.names.functions),
            "macros": set(self.names.macros),
            "objects": set(self.names.objects),
            "types": set(self.names.types),
            "typedefs": set(self.names.typedefs),
        }
        for field in final_sets:
            platform_values = set(getattr(self.platform, field))
            if not platform_values <= final_sets[field]:
                raise HostedAbiManifestError(
                    f"platform.{field} contains names outside names.{field}"
                )

        index = {function.name: function for function in self.functions}
        for function in self.functions:
            self._validate_function(function)

        source_visible = {
            helper.name for helper in runtime.helpers if helper.source_visible
        }
        runtime_specs = {
            function.name for function in self.functions if function.origin == "runtime"
        }
        if runtime_specs != source_visible:
            missing = sorted(source_visible - runtime_specs)
            extra = sorted(runtime_specs - source_visible)
            raise HostedAbiManifestError(
                "runtime hosted functions differ from source-visible runtime helpers: "
                f"missing={missing!r}, extra={extra!r}"
            )
        adopting = set(self.names.runtime_adopting_helpers)
        if not adopting <= source_visible:
            raise HostedAbiManifestError(
                "runtime-adopting helpers must be source-visible runtime helpers"
            )
        for name in adopting:
            function = index[name]
            semantic = function.semantic_result or function.result
            if (
                not function.parameters_known
                or not function.parameters
                or function.parameters[0].effect != "consume"
                or semantic.base != "string"
                or semantic.pointer_depth != 0
                or function.raw_lifetime
            ):
                raise HostedAbiManifestError(
                    f"runtime-adopting helper {name!r} lacks the required string-adoption contract"
                )

    @classmethod
    def _validate_function(cls, function: HostedAbiFunctionSpec) -> None:
        context = f"hosted function {function.name!r}"
        if not function.parameters_known:
            if function.parameters:
                raise HostedAbiManifestError(f"{context} has parameters despite an opaque signature")
            if function.variadic:
                raise HostedAbiManifestError(f"{context} is variadic without a fixed prefix")
        if any(parameter.effect not in cls._EFFECTS for parameter in function.parameters):
            raise HostedAbiManifestError(f"{context} contains an unknown parameter effect")
        for parameter in function.parameters:
            cls._validate_type_shape(parameter.type_shape, context)
            if (
                parameter.type_shape.base == "CFunction"
                and parameter.callback_lifetime is None
            ):
                raise HostedAbiManifestError(
                    f"{context} callback parameter lacks explicit lifetime metadata"
                )
            if parameter.callback_lifetime is not None:
                if parameter.callback_lifetime not in cls._CALLBACK_LIFETIMES:
                    raise HostedAbiManifestError(f"{context} contains an unknown callback lifetime")
                if parameter.type_shape.base != "CFunction":
                    raise HostedAbiManifestError(
                        f"{context} attaches callback lifetime metadata to a non-callback parameter"
                    )
        cls._validate_type_shape(function.result, context)
        if function.semantic_result is not None:
            cls._validate_type_shape(function.semantic_result, context)
        if function.return_effect not in cls._RETURN_EFFECTS:
            raise HostedAbiManifestError(f"{context} contains an unknown return effect")
        if function.return_effect != "value" and function.result.pointer_depth == 0:
            raise HostedAbiManifestError(f"{context} has a pointer-lifetime scalar result")
        aliasing = function.return_effect == "alias"
        if aliasing != (function.return_alias_parameter is not None):
            raise HostedAbiManifestError(f"{context} has inconsistent alias metadata")
        if aliasing != (function.return_alias_shape is not None):
            raise HostedAbiManifestError(f"{context} lacks an explicit alias shape")
        if function.return_alias_shape not in cls._ALIAS_SHAPES | {None}:
            raise HostedAbiManifestError(f"{context} contains an invalid alias shape")
        if function.return_alias_parameter is not None:
            parameter_index = function.return_alias_parameter
            if not 0 <= parameter_index < len(function.parameters):
                raise HostedAbiManifestError(f"{context} alias parameter is out of range")
            parameter = function.parameters[parameter_index]
            if parameter.effect not in {"read", "mutate"} or parameter.type_shape.pointer_depth == 0:
                raise HostedAbiManifestError(f"{context} alias parameter is not a pointer borrow")
        if function.return_alias_null_effect is not None:
            if not aliasing or function.return_alias_null_effect not in cls._NULL_ALIAS_EFFECTS:
                raise HostedAbiManifestError(f"{context} contains invalid null-alias metadata")
        if function.return_alias_null_deallocator is not None:
            if function.return_alias_null_effect is None:
                raise HostedAbiManifestError(f"{context} null deallocator lacks a null effect")
        if function.return_deallocator is not None:
            if function.result.pointer_depth == 0 or aliasing:
                raise HostedAbiManifestError(f"{context} has an invalid return deallocator")
        consumed = [
            parameter for parameter in function.parameters if parameter.effect == "consume"
        ]
        if function.raw_lifetime:
            if (
                not function.parameters
                or function.parameters[0].effect != "consume"
                or len(consumed) != 1
                or consumed[0].type_shape.pointer_depth == 0
                or function.consume_deallocator is None
            ):
                raise HostedAbiManifestError(f"{context} has an invalid raw-lifetime contract")
        elif function.consume_deallocator is not None:
            raise HostedAbiManifestError(f"{context} has a deallocator without raw-lifetime consumption")

    @classmethod
    def _validate_type_shape(cls, shape: HostedAbiTypeSpec, context: str) -> None:
        if shape.generic_args and shape.base != "CFunction":
            raise HostedAbiManifestError(
                f"{context} contains generic hosted type {shape.base!r}; only CFunction is supported"
            )
        if shape.base == "CFunction":
            if shape.pointer_depth != 0 or shape.is_const or not shape.generic_args:
                raise HostedAbiManifestError(
                    f"{context} contains an invalid CFunction shape"
                )
        for argument in shape.generic_args:
            cls._validate_type_shape(argument, context)

    @staticmethod
    def _require_keys(
        table: dict[str, Any],
        allowed: frozenset[str],
        context: str,
        *,
        required: frozenset[str] | None = None,
    ) -> None:
        unknown = set(table) - allowed
        if unknown:
            raise HostedAbiManifestError(f"unknown {context} keys: {', '.join(sorted(unknown))}")
        required_keys = allowed if required is None else required
        missing = required_keys - set(table)
        if missing:
            raise HostedAbiManifestError(f"missing {context} keys: {', '.join(sorted(missing))}")

    @staticmethod
    def _table(table: dict[str, Any], key: str, context: str) -> dict[str, Any]:
        value = table.get(key)
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context}.{key} must be a table")
        return value

    @staticmethod
    def _string(table: dict[str, Any], key: str, context: str) -> str:
        value = table.get(key)
        if not isinstance(value, str) or not value:
            raise HostedAbiManifestError(f"{context}.{key} must be a non-empty string")
        return value

    @classmethod
    def _identifier(cls, table: dict[str, Any], key: str, context: str) -> str:
        value = cls._string(table, key, context)
        if not cls._IDENTIFIER.fullmatch(value):
            raise HostedAbiManifestError(f"{context}.{key} is not an identifier: {value!r}")
        return value

    @staticmethod
    def _integer(table: dict[str, Any], key: str, context: str) -> int:
        value = table.get(key)
        if type(value) is not int:
            raise HostedAbiManifestError(f"{context}.{key} must be an integer")
        return value

    @classmethod
    def _optional_integer(
        cls, table: dict[str, Any], key: str, context: str
    ) -> int | None:
        return cls._integer(table, key, context) if key in table else None

    @staticmethod
    def _boolean(table: dict[str, Any], key: str, context: str) -> bool:
        value = table.get(key)
        if type(value) is not bool:
            raise HostedAbiManifestError(f"{context}.{key} must be a boolean")
        return value

    @classmethod
    def _optional_string(
        cls, table: dict[str, Any], key: str, context: str
    ) -> str | None:
        return cls._string(table, key, context) if key in table else None

    @classmethod
    def _name_tuple(cls, table: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
        value = table.get(key)
        if not isinstance(value, list):
            raise HostedAbiManifestError(f"{context}.{key} must be an array")
        names = tuple(value)
        if any(not isinstance(name, str) or not cls._IDENTIFIER.fullmatch(name) for name in names):
            raise HostedAbiManifestError(f"{context}.{key} contains an invalid identifier")
        if names != tuple(sorted(names)):
            raise HostedAbiManifestError(f"{context}.{key} must be sorted")
        cls._unique(names, f"{context}.{key}")
        return names

    @staticmethod
    def _unique(values: tuple[str, ...], context: str) -> None:
        if len(values) != len(set(values)):
            raise HostedAbiManifestError(f"{context} must not contain duplicates")


class HostedAbiCatalogGenerator:
    """Render data-only Python and btrc hosted-ABI catalogs."""

    _PYTHON_PATH = PurePosixPath("src/compiler/python/abi/generated.py")
    _BTRC_PATH = PurePosixPath("src/compiler/btrc/generated/hosted_abi/tables.btrc")

    def __init__(self, manifest: HostedAbiManifest):
        self._manifest = manifest

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        return (
            GeneratedArtifact(self._PYTHON_PATH, self._render_python().encode("utf-8")),
            GeneratedArtifact(self._BTRC_PATH, self._render_btrc().encode("utf-8")),
        )

    def _render_python(self) -> str:
        lines = [
            '"""Generated hosted-ABI data. Do not edit by hand."""',
            "",
            "from typing import NamedTuple",
            "",
            "",
            "class GeneratedAbiTypeRow(NamedTuple):",
            "    base: str",
            "    pointer_depth: int",
            "    is_const: bool",
            "    generic_args: tuple['GeneratedAbiTypeRow', ...]",
            "",
            "",
            "class GeneratedHostedParameterRow(NamedTuple):",
            "    type_shape: GeneratedAbiTypeRow",
            "    effect: str",
            "    callback_lifetime: str | None",
            "",
            "",
            "class GeneratedHostedFunctionRow(NamedTuple):",
            "    name: str",
            "    origin: str",
            "    result: GeneratedAbiTypeRow",
            "    parameters: tuple[GeneratedHostedParameterRow, ...] | None",
            "    variadic: bool",
            "    semantic_result: GeneratedAbiTypeRow | None",
            "    return_effect: str",
            "    return_alias_parameter: int | None",
            "    return_alias_null_effect: str | None",
            "    raw_lifetime: bool",
            "    return_deallocator: str | None",
            "    return_alias_shape: str | None",
            "    consume_deallocator: str | None",
            "    return_alias_null_deallocator: str | None",
            "",
            "",
            "HOSTED_FUNCTION_ROWS: tuple[GeneratedHostedFunctionRow, ...] = (",
        ]
        for function in self._manifest.functions:
            lines.extend(self._python_function(function))
        lines.extend([")", ""])
        self._append_python_tuple(lines, "HOSTED_FUNCTION_NAMES", self._manifest.names.functions)
        self._append_python_tuple(lines, "HOSTED_MACRO_NAMES", self._manifest.names.macros)
        self._append_python_tuple(lines, "HOSTED_OBJECT_NAMES", self._manifest.names.objects)
        self._append_python_tuple(lines, "HOSTED_TYPE_NAMES", self._manifest.names.types)
        self._append_python_tuple(lines, "HOSTED_TYPEDEF_NAMES", self._manifest.names.typedefs)
        self._append_python_tuple(lines, "HOSTED_OWNED_NAMES", self._manifest.names.owned)
        self._append_python_tuple(lines, "HOSTED_NATIVE_NAMES", self._manifest.names.native)
        self._append_python_tuple(
            lines, "HOSTED_NATIVE_INTERNAL_NAMES", self._manifest.names.native_internal
        )
        self._append_python_tuple(
            lines,
            "HOSTED_RUNTIME_ADOPTING_HELPERS",
            self._manifest.names.runtime_adopting_helpers,
        )
        self._append_python_tuple(
            lines, "HOSTED_PLATFORM_FUNCTION_NAMES", self._manifest.platform.functions
        )
        self._append_python_tuple(
            lines, "HOSTED_PLATFORM_MACRO_NAMES", self._manifest.platform.macros
        )
        self._append_python_tuple(
            lines, "HOSTED_PLATFORM_OBJECT_NAMES", self._manifest.platform.objects
        )
        self._append_python_tuple(
            lines, "HOSTED_PLATFORM_TYPE_NAMES", self._manifest.platform.types
        )
        self._append_python_tuple(
            lines, "HOSTED_PLATFORM_TYPEDEF_NAMES", self._manifest.platform.typedefs
        )
        lines.extend(
            [
                f"HOSTED_STDLIB_SOURCE_MARKER = {self._manifest.provenance.stdlib_source_marker!r}",
                f"HOSTED_USER_SOURCE_MARKER = {self._manifest.provenance.user_source_marker!r}",
                f"HOSTED_ABI_FINGERPRINT = {self._manifest.fingerprint!r}",
                "",
            ]
        )
        return "\n".join(lines)

    def _python_function(self, function: HostedAbiFunctionSpec) -> list[str]:
        semantic = (
            self._python_type(function.semantic_result)
            if function.semantic_result is not None
            else "None"
        )
        parameters = "None"
        if function.parameters_known:
            if not function.parameters:
                parameters = "()"
            else:
                parameter_rows = ", ".join(
                    "GeneratedHostedParameterRow("
                    f"{self._python_type(parameter.type_shape)}, {parameter.effect!r}, "
                    f"{parameter.callback_lifetime!r})"
                    for parameter in function.parameters
                )
                parameters = f"({parameter_rows},)"
        return [
            "    GeneratedHostedFunctionRow(",
            f"        name={function.name!r},",
            f"        origin={function.origin!r},",
            f"        result={self._python_type(function.result)},",
            f"        parameters={parameters},",
            f"        variadic={function.variadic!r},",
            f"        semantic_result={semantic},",
            f"        return_effect={function.return_effect!r},",
            f"        return_alias_parameter={function.return_alias_parameter!r},",
            f"        return_alias_null_effect={function.return_alias_null_effect!r},",
            f"        raw_lifetime={function.raw_lifetime!r},",
            f"        return_deallocator={function.return_deallocator!r},",
            f"        return_alias_shape={function.return_alias_shape!r},",
            f"        consume_deallocator={function.consume_deallocator!r},",
            "        return_alias_null_deallocator="
            f"{function.return_alias_null_deallocator!r},",
            "    ),",
        ]

    @classmethod
    def _python_type(cls, shape: HostedAbiTypeSpec) -> str:
        arguments = ", ".join(cls._python_type(argument) for argument in shape.generic_args)
        generic_args = f"({arguments},)" if arguments else "()"
        return (
            f"GeneratedAbiTypeRow({shape.base!r}, {shape.pointer_depth}, "
            f"{shape.is_const!r}, {generic_args})"
        )

    @staticmethod
    def _append_python_tuple(lines: list[str], name: str, values: tuple[str, ...]) -> None:
        lines.append(f"{name}: tuple[str, ...] = (")
        lines.extend(f"    {value!r}," for value in values)
        lines.extend([")", ""])

    def _render_btrc(self) -> str:
        lines = [
            "/* Generated hosted-ABI data. Do not edit by hand. */",
            "",
            "import std.vector;",
            "",
            "class GeneratedAbiTypeRow {",
            "    public string base;",
            "    public int pointer_depth;",
            "    public bool is_const;",
            "    public Vector<GeneratedAbiTypeRow> generic_args;",
            "",
            "    public GeneratedAbiTypeRow(string base, int pointer_depth, bool is_const,",
            "            Vector<GeneratedAbiTypeRow> generic_args) {",
            "        self.base = base;",
            "        self.pointer_depth = pointer_depth;",
            "        self.is_const = is_const;",
            "        self.generic_args = generic_args;",
            "    }",
            "}",
            "",
            "class GeneratedHostedParameterRow {",
            "    public GeneratedAbiTypeRow type_shape;",
            "    public string effect;",
            "    public string callback_lifetime;",
            "",
            "    public GeneratedHostedParameterRow(GeneratedAbiTypeRow type_shape, string effect,",
            "            string callback_lifetime) {",
            "        self.type_shape = type_shape;",
            "        self.effect = effect;",
            "        self.callback_lifetime = callback_lifetime;",
            "    }",
            "}",
            "",
            "class GeneratedHostedFunctionRow {",
            "    public string name;",
            "    public string origin;",
            "    public GeneratedAbiTypeRow result;",
            "    public bool parameters_known;",
            "    public Vector<GeneratedHostedParameterRow> parameters;",
            "    public bool variadic;",
            "    public bool has_semantic_result;",
            "    public GeneratedAbiTypeRow semantic_result;",
            "    public string return_effect;",
            "    public int return_alias_parameter;",
            "    public string return_alias_null_effect;",
            "    public bool raw_lifetime;",
            "    public string return_deallocator;",
            "    public string return_alias_shape;",
            "    public string consume_deallocator;",
            "    public string return_alias_null_deallocator;",
            "",
            "    public GeneratedHostedFunctionRow(",
            "            string name, string origin, GeneratedAbiTypeRow result,",
            "            bool parameters_known, Vector<GeneratedHostedParameterRow> parameters,",
            "            bool variadic, bool has_semantic_result,",
            "            GeneratedAbiTypeRow semantic_result, string return_effect,",
            "            int return_alias_parameter, string return_alias_null_effect,",
            "            bool raw_lifetime, string return_deallocator,",
            "            string return_alias_shape, string consume_deallocator,",
            "            string return_alias_null_deallocator) {",
            "        self.name = name;",
            "        self.origin = origin;",
            "        self.result = result;",
            "        self.parameters_known = parameters_known;",
            "        self.parameters = parameters;",
            "        self.variadic = variadic;",
            "        self.has_semantic_result = has_semantic_result;",
            "        self.semantic_result = semantic_result;",
            "        self.return_effect = return_effect;",
            "        self.return_alias_parameter = return_alias_parameter;",
            "        self.return_alias_null_effect = return_alias_null_effect;",
            "        self.raw_lifetime = raw_lifetime;",
            "        self.return_deallocator = return_deallocator;",
            "        self.return_alias_shape = return_alias_shape;",
            "        self.consume_deallocator = consume_deallocator;",
            "        self.return_alias_null_deallocator = return_alias_null_deallocator;",
            "    }",
            "}",
            "",
            "class GeneratedHostedAbiData {",
            "    public Vector<GeneratedHostedFunctionRow> functions;",
            "    public Vector<string> function_names;",
            "    public Vector<string> macro_names;",
            "    public Vector<string> object_names;",
            "    public Vector<string> type_names;",
            "    public Vector<string> typedef_names;",
            "    public Vector<string> owned_names;",
            "    public Vector<string> native_names;",
            "    public Vector<string> native_internal_names;",
            "    public Vector<string> runtime_adopting_helpers;",
            "    public Vector<string> platform_function_names;",
            "    public Vector<string> platform_macro_names;",
            "    public Vector<string> platform_object_names;",
            "    public Vector<string> platform_type_names;",
            "    public Vector<string> platform_typedef_names;",
            "    public string stdlib_source_marker;",
            "    public string user_source_marker;",
            "    public string fingerprint;",
            "",
            "    private Vector<GeneratedHostedParameterRow> emptyParameters() {",
            "        Vector<GeneratedHostedParameterRow> values = [];",
            "        return values;",
            "    }",
            "",
            "    private Vector<GeneratedAbiTypeRow> emptyTypes() {",
            "        Vector<GeneratedAbiTypeRow> values = [];",
            "        return values;",
            "    }",
            "",
            "    public GeneratedHostedAbiData() {",
        ]
        # Populating these tables from the constructor alone produced a single C
        # function of 114,000 lines, and a C optimizer's cost grows superlinearly
        # with function size: that one function accounted for roughly 90% of the
        # time to compile the whole self-hosted compiler. Spreading the same rows,
        # in the same order, over many small methods keeps the data identical
        # while staying in the optimizer's linear regime.
        calls: list[str] = ["        self.functions = [];"]
        methods: list[str] = []
        self._btrc_chunk(
            calls,
            methods,
            "pushFunctions",
            [self._btrc_function(function) for function in self._manifest.functions],
            self.BTRC_ROWS_PER_METHOD,
        )
        for field, values in self._btrc_name_fields():
            calls.append(f"        self.{field} = [];")
            self._btrc_chunk(
                calls,
                methods,
                f"push_{field}",
                [[f"        self.{field}.push({self._btrc_string(value)});"] for value in values],
                self.BTRC_NAMES_PER_METHOD,
            )
        calls.extend(
            [
                "        self.stdlib_source_marker = "
                f"{self._btrc_string(self._manifest.provenance.stdlib_source_marker)};",
                "        self.user_source_marker = "
                f"{self._btrc_string(self._manifest.provenance.user_source_marker)};",
                f"        self.fingerprint = {self._btrc_string(self._manifest.fingerprint)};",
            ]
        )
        lines.extend(calls)
        lines.extend(["    }", ""])
        lines.extend(methods)
        lines.extend(["}", ""])
        return "\n".join(lines)

    @staticmethod
    def _btrc_chunk(
        calls: list[str],
        methods: list[str],
        prefix: str,
        blocks: list[list[str]],
        per_method: int,
    ) -> None:
        """Spread row population across methods a C optimizer can still chew."""

        for start in range(0, len(blocks), per_method):
            name = f"{prefix}{start // per_method}"
            calls.append(f"        self.{name}();")
            methods.append(f"    private void {name}() {{")
            for block in blocks[start : start + per_method]:
                methods.extend(block)
            methods.extend(["    }", ""])

    BTRC_ROWS_PER_METHOD = 40
    BTRC_NAMES_PER_METHOD = 250

    def _btrc_function(self, function: HostedAbiFunctionSpec) -> list[str]:
        semantic = function.semantic_result or function.result
        lines = [
            "        self.functions.push(GeneratedHostedFunctionRow(",
            f"            {self._btrc_string(function.name)},",
            f"            {self._btrc_string(function.origin)},",
            f"            {self._btrc_type(function.result)},",
            f"            {'true' if function.parameters_known else 'false'},",
        ]
        if function.parameters:
            lines.append("            [")
            lines.extend(
                "                GeneratedHostedParameterRow("
                f"{self._btrc_type(parameter.type_shape)}, "
                f"{self._btrc_string(parameter.effect)}, "
                f"{self._btrc_optional(parameter.callback_lifetime)}),"
                for parameter in function.parameters
            )
            lines.append("            ],")
        else:
            lines.append("            self.emptyParameters(),")
        lines.extend(
            [
                f"            {'true' if function.variadic else 'false'},",
                f"            {'true' if function.semantic_result is not None else 'false'},",
                f"            {self._btrc_type(semantic)},",
                f"            {self._btrc_string(function.return_effect)},",
                f"            {function.return_alias_parameter if function.return_alias_parameter is not None else -1},",
                f"            {self._btrc_optional(function.return_alias_null_effect)},",
                f"            {'true' if function.raw_lifetime else 'false'},",
                f"            {self._btrc_optional(function.return_deallocator)},",
                f"            {self._btrc_optional(function.return_alias_shape)},",
                f"            {self._btrc_optional(function.consume_deallocator)},",
                f"            {self._btrc_optional(function.return_alias_null_deallocator)}));",
            ]
        )
        return lines

    def _btrc_name_fields(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return (
            ("function_names", self._manifest.names.functions),
            ("macro_names", self._manifest.names.macros),
            ("object_names", self._manifest.names.objects),
            ("type_names", self._manifest.names.types),
            ("typedef_names", self._manifest.names.typedefs),
            ("owned_names", self._manifest.names.owned),
            ("native_names", self._manifest.names.native),
            ("native_internal_names", self._manifest.names.native_internal),
            ("runtime_adopting_helpers", self._manifest.names.runtime_adopting_helpers),
            ("platform_function_names", self._manifest.platform.functions),
            ("platform_macro_names", self._manifest.platform.macros),
            ("platform_object_names", self._manifest.platform.objects),
            ("platform_type_names", self._manifest.platform.types),
            ("platform_typedef_names", self._manifest.platform.typedefs),
        )

    def _btrc_type(self, shape: HostedAbiTypeSpec) -> str:
        arguments = ", ".join(self._btrc_type(argument) for argument in shape.generic_args)
        generic_args = f"[{arguments}]" if arguments else "self.emptyTypes()"
        return (
            "GeneratedAbiTypeRow("
            f"{self._btrc_string(shape.base)}, {shape.pointer_depth}, "
            f"{'true' if shape.is_const else 'false'}, {generic_args})"
        )

    def _btrc_optional(self, value: str | None) -> str:
        return self._btrc_string(value or "")

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
