"""Validated hosted-C ABI manifest and compiler catalog generation."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from . import GeneratedArtifact, GeneratedSourceStyle
from .manifest_fields import ManifestFields
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
    realtime_effect: str

    def canonical(self) -> dict[str, object]:
        return {
            "name": self.name,
            "origin": self.origin,
            "result": self.result.canonical(),
            "parameters_known": self.parameters_known,
            "parameters": [parameter.canonical() for parameter in self.parameters],
            "variadic": self.variadic,
            "semantic_result": (self.semantic_result.canonical() if self.semantic_result is not None else None),
            "return_effect": self.return_effect,
            "return_alias_parameter": self.return_alias_parameter,
            "return_alias_null_effect": self.return_alias_null_effect,
            "raw_lifetime": self.raw_lifetime,
            "return_deallocator": self.return_deallocator,
            "return_alias_shape": self.return_alias_shape,
            "consume_deallocator": self.consume_deallocator,
            "return_alias_null_deallocator": self.return_alias_null_deallocator,
            "realtime_effect": self.realtime_effect,
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
    noreturn: tuple[str, ...]

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
            "noreturn": list(self.noreturn),
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
class HostedAbiPlatformTargetSpec:
    """The ``[platform]`` names one target row's C compile does not declare, kind by kind.

    Schema 3's ``[[platform_targets]]`` (platform-target-contract.md §2.2):
    each list is a sorted subset of the matching ``[platform]`` list, and
    ``source`` says where the row was extracted.
    """

    target: str
    functions: tuple[str, ...]
    macros: tuple[str, ...]
    objects: tuple[str, ...]
    types: tuple[str, ...]
    typedefs: tuple[str, ...]
    source: str

    KINDS = ("functions", "macros", "objects", "types", "typedefs")

    def canonical(self) -> dict[str, object]:
        return {
            "target": self.target,
            **{f"unavailable_{kind}": list(getattr(self, kind)) for kind in self.KINDS},
            "source": self.source,
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

    _FIELDS = ManifestFields(HostedAbiManifestError)

    schema_version: int
    provenance: HostedAbiProvenanceSpec
    names: HostedAbiNameSets
    platform: HostedAbiPlatformSets
    functions: tuple[HostedAbiFunctionSpec, ...]
    platform_targets: tuple[HostedAbiPlatformTargetSpec, ...]

    SCHEMA_VERSION = 3
    # btrc's own namespace: the runtime is ported to every row, never filtered.
    RUNTIME_PREFIXES = ("btrc_", "Btrc", "BTRC_", "__btrc_")
    _ROOT_KEYS = frozenset({"schema_version", "provenance", "names", "platform", "functions", "platform_targets"})
    _PLATFORM_TARGET_KEYS = frozenset(
        {"target", "source", *(f"unavailable_{kind}" for kind in HostedAbiPlatformTargetSpec.KINDS)}
    )
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
            "noreturn",
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
            "realtime_effect",
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
            raise HostedAbiManifestError(f"cannot read hosted ABI manifest {manifest_path}: {error}") from error

        cls._FIELDS.require_keys(document, cls._ROOT_KEYS, "hosted ABI manifest")
        schema_version = cls._FIELDS.integer(document, "schema_version", "hosted ABI manifest")
        if schema_version != cls.SCHEMA_VERSION:
            raise HostedAbiManifestError(f"unsupported hosted ABI schema version: {schema_version}")

        provenance_table = cls._FIELDS.table(document, "provenance", "hosted ABI manifest")
        cls._FIELDS.require_keys(provenance_table, cls._PROVENANCE_KEYS, "provenance")
        provenance = HostedAbiProvenanceSpec(
            stdlib_source_marker=cls._FIELDS.string(provenance_table, "stdlib_source_marker", "provenance"),
            user_source_marker=cls._FIELDS.string(provenance_table, "user_source_marker", "provenance"),
        )

        names_table = cls._FIELDS.table(document, "names", "hosted ABI manifest")
        cls._FIELDS.require_keys(names_table, cls._NAME_KEYS, "names")
        names = HostedAbiNameSets(
            functions=cls._name_tuple(names_table, "functions", "names"),
            macros=cls._name_tuple(names_table, "macros", "names"),
            objects=cls._name_tuple(names_table, "objects", "names"),
            types=cls._name_tuple(names_table, "types", "names"),
            typedefs=cls._name_tuple(names_table, "typedefs", "names"),
            owned=cls._name_tuple(names_table, "owned", "names"),
            native=cls._name_tuple(names_table, "native", "names"),
            native_internal=cls._name_tuple(names_table, "native_internal", "names"),
            runtime_adopting_helpers=cls._name_tuple(names_table, "runtime_adopting_helpers", "names"),
            noreturn=cls._name_tuple(names_table, "noreturn", "names"),
        )

        platform_table = cls._FIELDS.table(document, "platform", "hosted ABI manifest")
        cls._FIELDS.require_keys(platform_table, cls._PLATFORM_KEYS, "platform")
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
        functions = tuple(cls._function(raw_function, index) for index, raw_function in enumerate(raw_functions))
        raw_platform_targets = document.get("platform_targets")
        if not isinstance(raw_platform_targets, list) or not raw_platform_targets:
            raise HostedAbiManifestError("platform_targets must be a non-empty array of tables")
        platform_targets = tuple(
            cls._platform_target(raw_target, index) for index, raw_target in enumerate(raw_platform_targets)
        )
        manifest = cls(
            schema_version=schema_version,
            provenance=provenance,
            names=names,
            platform=platform,
            functions=functions,
            platform_targets=platform_targets,
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
            "platform_targets": [target.canonical() for target in self.platform_targets],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _platform_target(cls, value: Any, index: int) -> HostedAbiPlatformTargetSpec:
        context = f"platform_targets[{index}]"
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._FIELDS.require_keys(value, cls._PLATFORM_TARGET_KEYS, context)
        return HostedAbiPlatformTargetSpec(
            target=cls._FIELDS.string(value, "target", context),
            source=cls._FIELDS.string(value, "source", context),
            **{
                kind: cls._name_tuple(value, f"unavailable_{kind}", context)
                for kind in HostedAbiPlatformTargetSpec.KINDS
            },
        )

    @classmethod
    def _function(cls, value: Any, index: int) -> HostedAbiFunctionSpec:
        context = f"functions[{index}]"
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._FIELDS.require_keys(
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
            parameters_known=cls._FIELDS.boolean(value, "parameters_known", context),
            parameters=parameters,
            variadic=cls._FIELDS.boolean(value, "variadic", context),
            semantic_result=(
                cls._type_shape(value["semantic_result"], f"{context}.semantic_result")
                if "semantic_result" in value
                else None
            ),
            return_effect=cls._FIELDS.string(value, "return_effect", context),
            return_alias_parameter=cls._optional_integer(value, "return_alias_parameter", context),
            return_alias_null_effect=cls._optional_string(value, "return_alias_null_effect", context),
            raw_lifetime=cls._FIELDS.boolean(value, "raw_lifetime", context),
            return_deallocator=cls._optional_string(value, "return_deallocator", context),
            return_alias_shape=cls._optional_string(value, "return_alias_shape", context),
            consume_deallocator=cls._optional_string(value, "consume_deallocator", context),
            return_alias_null_deallocator=cls._optional_string(value, "return_alias_null_deallocator", context),
            realtime_effect=(cls._optional_string(value, "realtime_effect", context) or "unknown"),
        )

    @classmethod
    def _parameter(cls, value: Any, index: int, function_context: str) -> HostedAbiParameterSpec:
        context = f"{function_context}.parameters[{index}]"
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._FIELDS.require_keys(
            value,
            cls._PARAMETER_KEYS,
            context,
            required=cls._PARAMETER_REQUIRED_KEYS,
        )
        shape = cls._type_shape({key: value[key] for key in cls._TYPE_KEYS if key in value}, context)
        return HostedAbiParameterSpec(
            type_shape=shape,
            effect=cls._FIELDS.string(value, "effect", context),
            callback_lifetime=cls._optional_string(value, "callback_lifetime", context),
        )

    @classmethod
    def _type_shape(cls, value: Any, context: str) -> HostedAbiTypeSpec:
        if not isinstance(value, dict):
            raise HostedAbiManifestError(f"{context} must be a table")
        cls._FIELDS.require_keys(value, cls._TYPE_KEYS, context, required=cls._TYPE_REQUIRED_KEYS)
        base = cls._FIELDS.string(value, "base", context)
        pointer_depth = cls._FIELDS.integer(value, "pointer_depth", context)
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
            is_const=cls._FIELDS.boolean(value, "is_const", context),
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
                raise HostedAbiManifestError(f"hosted ABI provenance marker is not compiler-authenticated: {marker!r}")

        function_names = tuple(function.name for function in self.functions)
        if function_names != tuple(sorted(function_names)):
            raise HostedAbiManifestError("exact hosted functions must be sorted by name")
        self._unique(function_names, "exact hosted function names")
        exact = set(function_names)
        declared_functions = set(self.names.functions)
        if not exact <= declared_functions:
            missing = sorted(exact - declared_functions)
            raise HostedAbiManifestError(f"exact hosted functions missing from owned function names: {missing!r}")
        expected_owned = declared_functions | set(self.names.macros) | set(self.names.objects) | set(self.names.types)
        if set(self.names.owned) != expected_owned:
            raise HostedAbiManifestError("names.owned differs from the hosted namespace union")
        if not set(self.names.typedefs) <= set(self.names.types):
            raise HostedAbiManifestError("hosted typedef names must be included in type names")
        if not set(self.names.native) <= exact:
            raise HostedAbiManifestError("hosted native names must have exact function specs")
        if not set(self.names.noreturn) <= declared_functions:
            raise HostedAbiManifestError("hosted noreturn names must be hosted function names")

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
                raise HostedAbiManifestError(f"platform.{field} contains names outside names.{field}")

        index = {function.name: function for function in self.functions}
        for function in self.functions:
            self._validate_function(function)

        source_visible = {helper.name for helper in runtime.helpers if helper.source_visible}
        runtime_specs = {function.name for function in self.functions if function.origin == "runtime"}
        if runtime_specs != source_visible:
            missing = sorted(source_visible - runtime_specs)
            extra = sorted(runtime_specs - source_visible)
            raise HostedAbiManifestError(
                "runtime hosted functions differ from source-visible runtime helpers: "
                f"missing={missing!r}, extra={extra!r}"
            )
        self._validate_platform_targets(runtime_specs)
        adopting = set(self.names.runtime_adopting_helpers)
        if not adopting <= source_visible:
            raise HostedAbiManifestError("runtime-adopting helpers must be source-visible runtime helpers")
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

    def _validate_platform_targets(self, runtime_names: set[str]) -> None:
        """Each row lists only ``[platform]`` names, never ISO C or btrc's own runtime.

        A name in ``[names]`` but not in ``[platform]`` (ISO C, runtime and
        native names) is available everywhere, so the subset rule refuses it.
        ``TargetManifest`` checks that the rows are exactly its labels.
        """

        labels = [target.target for target in self.platform_targets]
        if len(labels) != len(set(labels)):
            duplicate = next(label for label in labels if labels.count(label) > 1)
            raise HostedAbiManifestError(f"platform_targets lists target {duplicate!r} more than once")
        if labels != sorted(labels):
            raise HostedAbiManifestError("platform_targets must be listed in target order")
        for target in self.platform_targets:
            context = f"platform_targets[{target.target!r}]"
            for kind in HostedAbiPlatformTargetSpec.KINDS:
                listed = getattr(target, kind)
                outside = sorted(set(listed) - set(getattr(self.platform, kind)))
                if outside:
                    raise HostedAbiManifestError(
                        f"{context}.unavailable_{kind} lists names outside platform.{kind}: {outside[:5]!r}"
                    )
                runtime = sorted(name for name in listed if name in runtime_names or name.startswith(self.RUNTIME_PREFIXES))
                if runtime:
                    raise HostedAbiManifestError(
                        f"{context}.unavailable_{kind} lists btrc runtime names, which are ported, not filtered: "
                        f"{runtime[:5]!r}"
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
            if parameter.type_shape.base == "CFunction" and parameter.callback_lifetime is None:
                raise HostedAbiManifestError(f"{context} callback parameter lacks explicit lifetime metadata")
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
        if function.realtime_effect not in cls._REALTIME_EFFECTS:
            raise HostedAbiManifestError(f"{context} contains an unknown realtime effect")
        if function.realtime_effect == "safe" and any(
            parameter.type_shape.base == "CFunction" for parameter in function.parameters
        ):
            raise HostedAbiManifestError(
                f"{context} cannot be realtime-safe while callback call-graph proof is unavailable"
            )
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
        consumed = [parameter for parameter in function.parameters if parameter.effect == "consume"]
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
        if shape.generic_args and shape.base not in {"CFunction", "Span"}:
            raise HostedAbiManifestError(f"{context} contains unsupported generic hosted type {shape.base!r}")
        if shape.base == "CFunction":
            if shape.pointer_depth != 0 or shape.is_const or not shape.generic_args:
                raise HostedAbiManifestError(f"{context} contains an invalid CFunction shape")
        if shape.base == "Span":
            if shape.pointer_depth != 0 or shape.is_const or len(shape.generic_args) != 1:
                raise HostedAbiManifestError(f"{context} contains an invalid Span shape")
        for argument in shape.generic_args:
            cls._validate_type_shape(argument, context)

    @classmethod
    def _identifier(cls, table: dict[str, Any], key: str, context: str) -> str:
        value = cls._FIELDS.string(table, key, context)
        if not cls._IDENTIFIER.fullmatch(value):
            raise HostedAbiManifestError(f"{context}.{key} is not an identifier: {value!r}")
        return value

    @classmethod
    def _optional_integer(cls, table: dict[str, Any], key: str, context: str) -> int | None:
        return cls._FIELDS.integer(table, key, context) if key in table else None

    @classmethod
    def _optional_string(cls, table: dict[str, Any], key: str, context: str) -> str | None:
        return cls._FIELDS.string(table, key, context) if key in table else None

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


@dataclass(frozen=True, slots=True)
class TargetRowSpec:
    """One compilation target row: the unit every consumer selects, keys and reports.

    It joins operating system, architecture, environment, deployment minimum,
    clang triple, data model and sysroot rule
    (docs/design/platform-target-contract.md §1.1). Fields are the spec's
    columns, in its order.
    """

    label: str
    operating_system: str
    architecture: str
    environment: str
    minimum_version: str
    triple: str
    triple_aliases: tuple[str, ...]
    zig_target: str
    target_arguments: tuple[str, ...]
    sizeof_pointer: int
    sizeof_long: int
    sizeof_wchar_t: int
    sizeof_long_double: int
    char_signed: bool
    wchar_signed: bool
    sysroot_kind: str
    sysroot_name: str
    compiler_host: bool
    objective_c: bool
    frameworks: bool

    def canonical(self) -> dict[str, object]:
        return {
            field.name: list(value) if isinstance(value, tuple) else value
            for field in fields(self)
            for value in (getattr(self, field.name),)
        }


@dataclass(frozen=True, slots=True)
class PredefinedMacroSpec:
    """One target predefined macro and the targets whose C compilers define it.

    An empty selector selects every value of its axis; ``""`` in
    ``environments`` names the empty environment.
    """

    name: str
    value: int
    operating_systems: tuple[str, ...]
    architectures: tuple[str, ...]
    environments: tuple[str, ...]

    def selects(self, target: TargetRowSpec) -> bool:
        return (
            (not self.operating_systems or target.operating_system in self.operating_systems)
            and (not self.architectures or target.architecture in self.architectures)
            and (not self.environments or target.environment in self.environments)
        )

    def selects_every_value(self) -> bool:
        return not (self.operating_systems or self.architectures or self.environments)

    def canonical(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "operating_systems": list(self.operating_systems),
            "architectures": list(self.architectures),
            "environments": list(self.environments),
        }


@dataclass(frozen=True, slots=True)
class TargetManifest:
    """Validated compilation-target spec (``src/language/targets.toml``, PLAN.md D21).

    It holds the target rows, the architecture aliases and default
    environments that labels use, the predefined-macro table that ``#if``
    reads (the hand-written rows and the rows derived from the row columns),
    and the reserved and foreign macro name lists
    (docs/design/c-preprocessor-conditionals.md,
    docs/design/platform-target-contract.md §1.1-§1.3). It is rendered into
    the hosted-ABI catalogs; parsing, selection and classification belong to
    each compiler's target and conditional-environment owners, never to
    generated data.
    """

    _FIELDS = ManifestFields(HostedAbiManifestError)
    _ROW_FIELDS = ManifestFields(HostedAbiManifestError, empty_strings=True)

    schema_version: int
    architecture_aliases: tuple[tuple[str, str], ...]
    default_environments: tuple[tuple[str, str], ...]
    targets: tuple[TargetRowSpec, ...]
    predefined_macros: tuple[PredefinedMacroSpec, ...]
    derived_macros: tuple[PredefinedMacroSpec, ...]
    undefined_macro_names: tuple[str, ...]
    foreign_macro_names: tuple[str, ...]

    SCHEMA_VERSION = 2
    OPERATING_SYSTEMS = ("android", "ios", "linux", "macos", "windows")
    ARCHITECTURES = ("aarch64", "x86_64")
    ENVIRONMENTS = ("", "gnu", "msvc", "simulator")
    SYSROOT_KINDS = ("ndk", "none", "windows-sdk", "xcrun", "zig-mingw")
    # The environments each operating system takes.
    _OS_ENVIRONMENTS = MappingProxyType(
        {
            "android": ("",),
            "ios": ("", "simulator"),
            "linux": ("gnu",),
            "macos": ("",),
            "windows": ("gnu", "msvc"),
        }
    )
    # The sysroot kind and xcrun SDK name each (operating system, environment) takes.
    _SYSROOTS = MappingProxyType(
        {
            ("android", ""): ("ndk", ""),
            ("ios", ""): ("xcrun", "iphoneos"),
            ("ios", "simulator"): ("xcrun", "iphonesimulator"),
            ("linux", "gnu"): ("none", ""),
            ("macos", ""): ("xcrun", "macosx"),
            ("windows", "gnu"): ("zig-mingw", ""),
            ("windows", "msvc"): ("windows-sdk", ""),
        }
    )
    _DESKTOP_OPERATING_SYSTEMS = ("linux", "macos", "windows")
    _APPLE_OPERATING_SYSTEMS = ("ios", "macos")
    # cc1's spelling of each architecture on Apple triples.
    _APPLE_ARCHITECTURES = MappingProxyType({"aarch64": "arm64", "x86_64": "x86_64"})
    # The MSVC compatibility version an msvc triple pins (Visual Studio 2022
    # 17.10), so cc1's triple and _MSC_VER do not vary with the host.
    MSVC_COMPATIBILITY_VERSION = "19.40.0"
    # char, short, int and long long have one width on every row.
    _PINNED_SIZES = (("__CHAR_BIT__", 8), ("__SIZEOF_SHORT__", 2), ("__SIZEOF_INT__", 4), ("__SIZEOF_LONG_LONG__", 8))
    # Generated from the row columns; a hand-written row may not name one.
    DERIVED_MACRO_NAMES = (
        "_LP64",
        "__ANDROID_API__",
        "__ANDROID_MIN_SDK_VERSION__",
        "__CHAR_UNSIGNED__",
        "__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__",
        "__ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__",
        "__ENVIRONMENT_OS_VERSION_MIN_REQUIRED__",
        "__LP64__",
        "__SIZEOF_LONG_DOUBLE__",
        "__SIZEOF_LONG__",
        "__SIZEOF_WCHAR_T__",
        "__WCHAR_UNSIGNED__",
    )

    _ROOT_KEYS = frozenset({"schema_version", "aliases", "targets", "predefined_macros", "conditionals"})
    _ALIAS_KEYS = frozenset({"architectures", "default_environments"})
    _TARGET_KEYS = frozenset(field.name for field in fields(TargetRowSpec))
    _MACRO_REQUIRED_KEYS = frozenset({"name", "value"})
    _MACRO_KEYS = _MACRO_REQUIRED_KEYS | frozenset({"operating_systems", "architectures", "environments"})
    _CONDITIONAL_KEYS = frozenset({"undefined_macro_names", "foreign_macro_names"})
    _IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
    _APPLE_MINIMUM = re.compile(r"[1-9][0-9]?\.[0-9]{1,2}\Z")
    _ANDROID_MINIMUM = re.compile(r"[1-9][0-9]*\Z")
    _MAXIMUM_VALUE = 2**63 - 1

    @classmethod
    def load(cls, manifest_path: Path, hosted_abi: HostedAbiManifest) -> TargetManifest:
        try:
            raw = manifest_path.read_bytes()
            if b"\x00" in raw or b"\r" in raw:
                raise HostedAbiManifestError(f"target spec must be NUL-free UTF-8 with LF endings: {manifest_path}")
            document = tomllib.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise HostedAbiManifestError(f"cannot read target spec {manifest_path}: {error}") from error
        return cls.from_document(document, hosted_abi)

    @classmethod
    def load_repository(cls, repository_root: Path) -> TargetManifest:
        """The repository's target spec, validated against its hosted ABI."""

        runtime = RuntimeManifest.load(repository_root / "src/runtime/c/manifest.toml")
        hosted_abi = HostedAbiManifest.load(repository_root / "src/language/hosted_abi.toml", runtime)
        return cls.load(repository_root / "src/language/targets.toml", hosted_abi)

    @classmethod
    def from_document(cls, document: dict[str, Any], hosted_abi: HostedAbiManifest) -> TargetManifest:
        cls._FIELDS.require_keys(document, cls._ROOT_KEYS, "target spec")
        schema_version = cls._FIELDS.integer(document, "schema_version", "target spec")
        if schema_version != cls.SCHEMA_VERSION:
            raise HostedAbiManifestError(f"unsupported target spec schema version: {schema_version}")
        aliases = cls._FIELDS.table(document, "aliases", "target spec")
        cls._FIELDS.require_keys(aliases, cls._ALIAS_KEYS, "aliases")
        targets = tuple(
            cls._target(value, index) for index, value in enumerate(cls._tables(document, "targets", "target spec"))
        )
        macros = tuple(
            cls._macro(value, index)
            for index, value in enumerate(cls._tables(document, "predefined_macros", "target spec"))
        )
        conditionals = cls._FIELDS.table(document, "conditionals", "target spec")
        cls._FIELDS.require_keys(conditionals, cls._CONDITIONAL_KEYS, "conditionals")
        manifest = cls(
            schema_version=schema_version,
            architecture_aliases=cls._string_table(aliases, "architectures", "aliases"),
            default_environments=cls._string_table(aliases, "default_environments", "aliases"),
            targets=targets,
            predefined_macros=macros,
            derived_macros=cls._derived_macros(targets),
            undefined_macro_names=cls._names(conditionals, "undefined_macro_names", "conditionals"),
            foreign_macro_names=cls._names(conditionals, "foreign_macro_names", "conditionals"),
        )
        manifest._validate(hosted_abi)
        return manifest

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(target.label for target in self.targets)

    @property
    def macro_rows(self) -> tuple[PredefinedMacroSpec, ...]:
        """The hand-written rows, then the derived rows sorted by name and label."""

        return self.predefined_macros + self.derived_macros

    @property
    def predefined_macro_names(self) -> tuple[str, ...]:
        """Every predefined and derived name, on any row, sorted: the names M3 refuses."""

        return tuple(sorted({macro.name for macro in self.macro_rows}))

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "architecture_aliases": dict(self.architecture_aliases),
            "default_environments": dict(self.default_environments),
            "targets": [target.canonical() for target in self.targets],
            "predefined_macros": [macro.canonical() for macro in self.predefined_macros],
            "undefined_macro_names": list(self.undefined_macro_names),
            "foreign_macro_names": list(self.foreign_macro_names),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def reserved(cls, name: str) -> bool:
        """C11 7.1.3: a name starting with ``__``, or with ``_`` and an uppercase letter."""

        return name.startswith("__") or (len(name) > 1 and name[0] == "_" and name[1].isupper())

    @classmethod
    def _tables(cls, document: dict[str, Any], key: str, context: str) -> list[dict[str, Any]]:
        value = document.get(key)
        if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
            raise HostedAbiManifestError(f"{context}.{key} must be a non-empty array of tables")
        return value

    @classmethod
    def _string_table(cls, table: dict[str, Any], key: str, context: str) -> tuple[tuple[str, str], ...]:
        """A table of identifier keys and string values, in key order."""

        value = cls._FIELDS.table(table, key, context)
        for name, item in value.items():
            if not cls._IDENTIFIER.fullmatch(name) or not isinstance(item, str) or not item:
                raise HostedAbiManifestError(f"{context}.{key} must map identifiers to non-empty strings")
        return tuple(sorted(value.items()))

    @classmethod
    def _target(cls, value: dict[str, Any], index: int) -> TargetRowSpec:
        context = f"targets[{index}]"
        cls._FIELDS.require_keys(value, cls._TARGET_KEYS, context)
        strings = {
            field.name: cls._ROW_FIELDS.string(value, field.name, context)
            for field in fields(TargetRowSpec)
            if field.type == "str"
        }
        integers = {
            field.name: cls._FIELDS.integer(value, field.name, context)
            for field in fields(TargetRowSpec)
            if field.type == "int"
        }
        booleans = {
            field.name: cls._FIELDS.boolean(value, field.name, context)
            for field in fields(TargetRowSpec)
            if field.type == "bool"
        }
        return TargetRowSpec(
            **strings,
            **integers,
            **booleans,
            triple_aliases=cls._strings(value, "triple_aliases", context),
            target_arguments=cls._strings(value, "target_arguments", context),
        )

    @classmethod
    def _strings(cls, table: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
        value = table.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise HostedAbiManifestError(f"{context}.{key} must be an array of non-empty strings")
        return tuple(value)

    @classmethod
    def _macro(cls, value: dict[str, Any], index: int) -> PredefinedMacroSpec:
        context = f"predefined_macros[{index}]"
        cls._FIELDS.require_keys(value, cls._MACRO_KEYS, context, required=cls._MACRO_REQUIRED_KEYS)
        return PredefinedMacroSpec(
            name=cls._identifier(value, "name", context),
            value=cls._FIELDS.integer(value, "value", context),
            operating_systems=cls._selector(value, "operating_systems", context),
            architectures=cls._selector(value, "architectures", context),
            environments=cls._selector(value, "environments", context),
        )

    @classmethod
    def _identifier(cls, table: dict[str, Any], key: str, context: str) -> str:
        value = cls._FIELDS.string(table, key, context)
        if not cls._IDENTIFIER.fullmatch(value):
            raise HostedAbiManifestError(f"{context}.{key} is not an identifier: {value!r}")
        return value

    @classmethod
    def _selector(cls, table: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
        """An omitted selector selects every value; an explicit one names at least one.

        Only ``environments`` may name ``""``, the empty environment.
        """

        if key not in table:
            return ()
        values = cls._names(table, key, context, empty_name=key == "environments")
        if not values:
            raise HostedAbiManifestError(f"{context}.{key} must name a value; omit it to select every value")
        return values

    @classmethod
    def _names(cls, table: dict[str, Any], key: str, context: str, *, empty_name: bool = False) -> tuple[str, ...]:
        value = table.get(key)
        if not isinstance(value, list):
            raise HostedAbiManifestError(f"{context}.{key} must be an array")
        names = tuple(value)
        if any(
            not isinstance(name, str) or not (cls._IDENTIFIER.fullmatch(name) or (empty_name and name == ""))
            for name in names
        ):
            raise HostedAbiManifestError(f"{context}.{key} contains an invalid identifier")
        if names != tuple(sorted(set(names))):
            raise HostedAbiManifestError(f"{context}.{key} must be sorted and unique")
        return names

    @classmethod
    def _derived_macros(cls, targets: tuple[TargetRowSpec, ...]) -> tuple[PredefinedMacroSpec, ...]:
        """One row per derived macro a target defines, selecting exactly that target, by name then label."""

        rows = [
            (
                name,
                target.label,
                PredefinedMacroSpec(
                    name, value, (target.operating_system,), (target.architecture,), (target.environment,)
                ),
            )
            for target in targets
            for name, value in cls._derived_values(target)
        ]
        return tuple(row for _, _, row in sorted(rows, key=lambda item: (item[0], item[1])))

    @classmethod
    def _derived_values(cls, target: TargetRowSpec) -> tuple[tuple[str, int], ...]:
        """The data-model and deployment macros clang derives from a row (§1.3)."""

        values = [
            ("__SIZEOF_LONG__", target.sizeof_long),
            ("__SIZEOF_WCHAR_T__", target.sizeof_wchar_t),
            ("__SIZEOF_LONG_DOUBLE__", target.sizeof_long_double),
        ]
        if target.sizeof_long == 8 and target.sizeof_pointer == 8:
            values.extend([("__LP64__", 1), ("_LP64", 1)])
        if not target.char_signed:
            values.append(("__CHAR_UNSIGNED__", 1))
        if not target.wchar_signed:
            values.append(("__WCHAR_UNSIGNED__", 1))
        if target.operating_system == "android" and cls._ANDROID_MINIMUM.fullmatch(target.minimum_version):
            level = int(target.minimum_version)
            values.extend([("__ANDROID_API__", level), ("__ANDROID_MIN_SDK_VERSION__", level)])
        if target.operating_system in cls._APPLE_OPERATING_SYSTEMS and cls._APPLE_MINIMUM.fullmatch(
            target.minimum_version
        ):
            major, minor = (int(part) for part in target.minimum_version.split("."))
            version = major * 10000 + minor * 100
            values.append(("__ENVIRONMENT_OS_VERSION_MIN_REQUIRED__", version))
            platform = "MAC_OS_X" if target.operating_system == "macos" else "IPHONE_OS"
            values.append((f"__ENVIRONMENT_{platform}_VERSION_MIN_REQUIRED__", version))
        return tuple(values)

    def _validate(self, hosted_abi: HostedAbiManifest) -> None:
        self._validate_aliases()
        self._validate_targets()
        self._validate_macros(hosted_abi)
        self._validate_platform_targets(hosted_abi)

    def _validate_platform_targets(self, hosted_abi: HostedAbiManifest) -> None:
        """Every row has exactly one hosted availability table, so no row ships without one."""

        listed = {target.target for target in hosted_abi.platform_targets}
        unknown = sorted(listed - set(self.labels))
        if unknown:
            raise HostedAbiManifestError(f"hosted platform_targets name unknown targets {unknown!r}")
        missing = sorted(set(self.labels) - listed)
        if missing:
            raise HostedAbiManifestError(f"hosted platform_targets lack a table for targets {missing!r}")

    def _validate_aliases(self) -> None:
        for alias, architecture in self.architecture_aliases:
            if alias in self.ARCHITECTURES:
                raise HostedAbiManifestError(f"architecture alias {alias!r} is a canonical architecture")
            if architecture not in self.ARCHITECTURES:
                raise HostedAbiManifestError(
                    f"architecture alias {alias!r} names {architecture!r}, which is not a canonical architecture"
                )
        rows = {target.operating_system for target in self.targets}
        for operating_system, environment in self.default_environments:
            if operating_system not in rows:
                raise HostedAbiManifestError(
                    f"default environment of {operating_system!r} names an operating system with no row"
                )
            if environment not in self._OS_ENVIRONMENTS.get(operating_system, ()):
                raise HostedAbiManifestError(
                    f"default environment {environment!r} does not fit operating system {operating_system!r}"
                )
            for architecture in sorted(
                {t.architecture for t in self.targets if t.operating_system == operating_system}
            ):
                count = sum(
                    1
                    for target in self.targets
                    if (target.operating_system, target.architecture, target.environment)
                    == (operating_system, architecture, environment)
                )
                if count != 1:
                    raise HostedAbiManifestError(
                        f"{operating_system}-{architecture} must have exactly one row in its default "
                        f"environment {environment!r}"
                    )

    def _validate_targets(self) -> None:
        labels = [target.label for target in self.targets]
        if len(labels) != len(set(labels)):
            duplicate = next(label for label in labels if labels.count(label) > 1)
            raise HostedAbiManifestError(f"target {duplicate!r} appears more than once")
        if labels != sorted(labels):
            raise HostedAbiManifestError("targets must be listed in label order")
        defaults = dict(self.default_environments)
        aliases: dict[str, str] = {}
        triples = {target.triple: target.label for target in self.targets}
        for target in self.targets:
            context = f"target {target.label!r}"
            if target.operating_system not in self.OPERATING_SYSTEMS:
                raise HostedAbiManifestError(f"{context} has unknown operating system {target.operating_system!r}")
            if target.architecture not in self.ARCHITECTURES:
                raise HostedAbiManifestError(f"{context} has unknown architecture {target.architecture!r}")
            if target.environment not in self._OS_ENVIRONMENTS[target.operating_system]:
                raise HostedAbiManifestError(
                    f"{context} has environment {target.environment!r}, which {target.operating_system} does not take"
                )
            default = defaults.get(target.operating_system, "")
            suffix = f"-{target.environment}" if target.environment and target.environment != default else ""
            label = f"{target.operating_system}-{target.architecture}{suffix}"
            if target.label != label:
                raise HostedAbiManifestError(f"{context} must be labelled {label!r}")
            self._validate_minimum(target, context)
            triple = self._cc1_triple(target)
            if target.triple != triple:
                raise HostedAbiManifestError(f"{context} triple {target.triple!r} is not clang's cc1 form {triple!r}")
            if list(target.triple_aliases) != sorted(set(target.triple_aliases)):
                raise HostedAbiManifestError(f"{context} triple_aliases must be sorted and unique")
            for alias in target.triple_aliases:
                if alias in triples:
                    raise HostedAbiManifestError(
                        f"{context} triple alias {alias!r} is the triple of {triples[alias]!r}"
                    )
                if alias in aliases:
                    raise HostedAbiManifestError(
                        f"{context} triple alias {alias!r} is also an alias of {aliases[alias]!r}"
                    )
                aliases[alias] = target.label
            zig = (
                f"{target.architecture}-{target.operating_system}-{target.environment}"
                if target.operating_system in ("linux", "windows")
                else ""
            )
            if target.zig_target != zig:
                raise HostedAbiManifestError(f"{context} zig_target must be {zig!r}")
            if target.target_arguments != (f"--target={target.triple}",):
                raise HostedAbiManifestError(f"{context} target_arguments must be exactly ['--target={target.triple}']")
            self._validate_data_model(target, context)
            if target.sysroot_kind not in self.SYSROOT_KINDS:
                raise HostedAbiManifestError(f"{context} has unknown sysroot_kind {target.sysroot_kind!r}")
            if bool(target.sysroot_name) != (target.sysroot_kind == "xcrun"):
                raise HostedAbiManifestError(f"{context} must name a sysroot_name exactly when sysroot_kind is xcrun")
            sysroot = self._SYSROOTS[(target.operating_system, target.environment)]
            if (target.sysroot_kind, target.sysroot_name) != sysroot:
                raise HostedAbiManifestError(
                    f"{context} must have sysroot_kind {sysroot[0]!r} and sysroot_name {sysroot[1]!r}"
                )
            host = target.operating_system in self._DESKTOP_OPERATING_SYSTEMS and target.environment == default
            if target.compiler_host != host:
                raise HostedAbiManifestError(
                    f"{context} compiler_host must be {str(host).lower()}: compiler hosts are exactly the desktop "
                    "rows in their default environment"
                )
            apple = target.operating_system in self._APPLE_OPERATING_SYSTEMS
            if target.objective_c != apple or target.frameworks != apple:
                raise HostedAbiManifestError(f"{context} objective_c and frameworks must be {str(apple).lower()}")

    def _validate_minimum(self, target: TargetRowSpec, context: str) -> None:
        if target.operating_system in self._APPLE_OPERATING_SYSTEMS:
            pattern, form = self._APPLE_MINIMUM, "MAJOR.MINOR"
        elif target.operating_system == "android":
            pattern, form = self._ANDROID_MINIMUM, "an API level"
        else:
            if target.minimum_version:
                raise HostedAbiManifestError(f"{context} minimum_version must be empty: its triple carries none")
            return
        if not pattern.fullmatch(target.minimum_version):
            raise HostedAbiManifestError(f"{context} minimum_version must be {form}")

    @classmethod
    def _cc1_triple(cls, target: TargetRowSpec) -> str:
        """The triple clang's cc1 uses for a row (``-###``)."""

        architecture = target.architecture
        if target.operating_system in cls._APPLE_OPERATING_SYSTEMS:
            system = "macosx" if target.operating_system == "macos" else "ios"
            suffix = "-simulator" if target.environment == "simulator" else ""
            return f"{cls._APPLE_ARCHITECTURES[architecture]}-apple-{system}{target.minimum_version}.0{suffix}"
        if target.operating_system == "linux":
            return f"{architecture}-unknown-linux-gnu"
        if target.operating_system == "android":
            return f"{architecture}-unknown-linux-android{target.minimum_version}"
        if target.environment == "msvc":
            return f"{architecture}-pc-windows-msvc{cls.MSVC_COMPATIBILITY_VERSION}"
        return f"{architecture}-w64-windows-gnu"

    def _validate_data_model(self, target: TargetRowSpec, context: str) -> None:
        windows = target.operating_system == "windows"
        if target.sizeof_pointer != 8:
            raise HostedAbiManifestError(f"{context} sizeof_pointer must be 8: there is no 32-bit row")
        if target.sizeof_long != (4 if windows else 8):
            raise HostedAbiManifestError(f"{context} sizeof_long must be {4 if windows else 8}")
        if target.sizeof_wchar_t != (2 if windows else 4):
            raise HostedAbiManifestError(f"{context} sizeof_wchar_t must be {2 if windows else 4}")
        if target.sizeof_long_double not in (8, 16):
            raise HostedAbiManifestError(f"{context} sizeof_long_double must be 8 or 16")

    def _validate_macros(self, hosted_abi: HostedAbiManifest) -> None:
        operating_systems = {target.operating_system for target in self.targets}
        architectures = {target.architecture for target in self.targets}
        environments = {target.environment for target in self.targets}
        for macro in self.predefined_macros:
            context = f"predefined macro {macro.name!r}"
            unknown = sorted(set(macro.operating_systems) - operating_systems)
            if unknown:
                raise HostedAbiManifestError(f"{context} selects unknown operating systems {unknown!r}")
            unknown = sorted(set(macro.architectures) - architectures)
            if unknown:
                raise HostedAbiManifestError(f"{context} selects unknown architectures {unknown!r}")
            unknown = sorted(set(macro.environments) - environments)
            if unknown:
                raise HostedAbiManifestError(f"{context} selects unknown environments {unknown!r}")
            if macro.name in self.DERIVED_MACRO_NAMES:
                raise HostedAbiManifestError(f"{context} is derived from the target columns and cannot be a row")
            apple_only = bool(macro.operating_systems) and set(macro.operating_systems) <= set(
                self._APPLE_OPERATING_SYSTEMS
            )
            if not self.reserved(macro.name) and not (macro.name.startswith("TARGET_") and apple_only):
                raise HostedAbiManifestError(
                    f"{context} is not a reserved name (a TARGET_ name may select only macos and ios)"
                )
            if not any(macro.selects(target) for target in self.targets):
                raise HostedAbiManifestError(f"{context} has a row that selects no target")
            if not 0 <= macro.value <= self._MAXIMUM_VALUE:
                raise HostedAbiManifestError(f"{context} has value {macro.value} outside [0, 2**63 - 1]")
        for name, value in self._PINNED_SIZES:
            rows = [macro for macro in self.predefined_macros if macro.name == name]
            if len(rows) != 1 or rows[0].value != value or not rows[0].selects_every_value():
                raise HostedAbiManifestError(
                    f"predefined macro {name!r} must be one row of value {value} on every target: "
                    "char, short, int and long long are pinned across rows"
                )
        selections: dict[str, list[PredefinedMacroSpec]] = {}
        for macro in self.macro_rows:
            for other in selections.get(macro.name, ()):
                shared = [target.label for target in self.targets if macro.selects(target) and other.selects(target)]
                if shared:
                    raise HostedAbiManifestError(
                        f"predefined macro {macro.name!r} has rows that both select {shared[0]!r}"
                    )
            selections.setdefault(macro.name, []).append(macro)
        for name in self.undefined_macro_names:
            if not self.reserved(name):
                raise HostedAbiManifestError(f"undefined macro name {name!r} is not a reserved name")
            if name in selections:
                raise HostedAbiManifestError(f"undefined macro name {name!r} is also a predefined macro")
        hosted = set(hosted_abi.names.owned) | set(hosted_abi.names.typedefs)
        for name in self.foreign_macro_names:
            if self.reserved(name):
                raise HostedAbiManifestError(f"foreign macro name {name!r} is a reserved name")
            if name in hosted:
                raise HostedAbiManifestError(f"foreign macro name {name!r} is already a hosted-ABI name")
            # A predefined name is refused by M3, and #if reads its row; listing
            # it as foreign too would let the two classifications drift.
            if name in selections:
                raise HostedAbiManifestError(f"foreign macro name {name!r} is also a predefined macro")


class TargetUnion:
    """Merge a generator's per-target results into one target-independent result.

    ``btrc.symbols`` and the LSP builtin catalog do not depend on the target:
    an owner is the union, over every spec target, of a file's live
    declarations (c-preprocessor-conditionals.md, "Stdlib symbol index"). A
    name that two targets declare differently in one file has no union, so
    the generator fails, naming the file and the two targets.

    The union is keyed by the identities the compilers' conditional
    environments distinguish: since PLAN.md Stage 24 commit 1c they select by
    environment too (platform-target-contract.md §1.3), so every row label is
    its own key.
    """

    def __init__(self, targets: TargetManifest) -> None:
        self._labels = tuple(target.label for target in targets.targets)

    @property
    def labels(self) -> tuple[str, ...]:
        return self._labels

    def owners(self, per_target: dict[str, dict[str, set[str]]]) -> dict[str, set[str]]:
        """Union every target's ``symbol -> owning files`` map."""

        self._require_every_target(per_target)
        merged: dict[str, set[str]] = {}
        for label in self._labels:
            for name, files in per_target[label].items():
                merged.setdefault(name, set()).update(files)
        return merged

    def merge[V](self, path: str, per_target: dict[str, dict[str, V]]) -> dict[str, V]:
        """Union one file's per-target declarations, which must agree wherever two targets share a name."""

        self._require_every_target(per_target)
        merged: dict[str, V] = {}
        first_label: dict[str, str] = {}
        for label in self._labels:
            for name, value in per_target[label].items():
                if name not in merged:
                    merged[name] = value
                    first_label[name] = label
                elif merged[name] != value:
                    raise HostedAbiManifestError(
                        f"{path}: {name!r} differs between targets {first_label[name]!r} and {label!r}"
                    )
        return merged

    def _require_every_target(self, per_target: dict[str, object]) -> None:
        if set(per_target) != set(self._labels):
            raise HostedAbiManifestError(f"per-target results must cover exactly the spec targets {self._labels!r}")


class HostedAbiCatalogGenerator:
    """Render data-only Python and btrc hosted-ABI catalogs."""

    _PYTHON_PATH = PurePosixPath("src/compiler/python/abi/generated.py")
    _BTRC_PATH = PurePosixPath("src/compiler/btrc/generated/hosted_abi/Tables.btrc")

    def __init__(self, manifest: HostedAbiManifest, targets: TargetManifest):
        self._manifest = manifest
        self._targets = targets

    def artifacts(self) -> tuple[GeneratedArtifact, ...]:
        return (
            GeneratedArtifact(self._PYTHON_PATH, self._render_python().encode("utf-8")),
            GeneratedArtifact(self._BTRC_PATH, GeneratedSourceStyle.format_btrc(self._render_btrc(), self._BTRC_PATH)),
        )

    def _render_python(self) -> str:
        lines = [
            '"""Generated hosted-ABI data. Do not edit by hand."""',
            "",
            "from types import MappingProxyType",
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
            "    realtime_effect: str",
            "",
            "",
            "class GeneratedTargetRow(NamedTuple):",
            *(f"    {field.name}: {field.type}" for field in fields(TargetRowSpec)),
            "",
            "",
            "class GeneratedPlatformTargetRow(NamedTuple):",
            "    target: str",
            *(f"    {kind}: frozenset[str]" for kind in HostedAbiPlatformTargetSpec.KINDS),
            "    source: str",
            "",
            "",
            "class GeneratedPredefinedMacroRow(NamedTuple):",
            "    name: str",
            "    value: int",
            "    operating_systems: tuple[str, ...]",
            "    architectures: tuple[str, ...]",
            "    environments: tuple[str, ...]",
            "",
            "",
            "HOSTED_FUNCTION_ROWS: tuple[GeneratedHostedFunctionRow, ...] = (",
        ]
        for function in self._manifest.functions:
            lines.extend(self._python_function(function))
        lines.extend([")", ""])
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_FUNCTION_NAMES", self._manifest.names.functions)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_MACRO_NAMES", self._manifest.names.macros)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_OBJECT_NAMES", self._manifest.names.objects)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_TYPE_NAMES", self._manifest.names.types)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_TYPEDEF_NAMES", self._manifest.names.typedefs)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_OWNED_NAMES", self._manifest.names.owned)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_NATIVE_NAMES", self._manifest.names.native)
        GeneratedSourceStyle.append_python_tuple(
            lines, "HOSTED_NATIVE_INTERNAL_NAMES", self._manifest.names.native_internal
        )
        GeneratedSourceStyle.append_python_tuple(
            lines,
            "HOSTED_RUNTIME_ADOPTING_HELPERS",
            self._manifest.names.runtime_adopting_helpers,
        )
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_NORETURN_FUNCTIONS", self._manifest.names.noreturn)
        GeneratedSourceStyle.append_python_tuple(
            lines, "HOSTED_PLATFORM_FUNCTION_NAMES", self._manifest.platform.functions
        )
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_PLATFORM_MACRO_NAMES", self._manifest.platform.macros)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_PLATFORM_OBJECT_NAMES", self._manifest.platform.objects)
        GeneratedSourceStyle.append_python_tuple(lines, "HOSTED_PLATFORM_TYPE_NAMES", self._manifest.platform.types)
        GeneratedSourceStyle.append_python_tuple(
            lines, "HOSTED_PLATFORM_TYPEDEF_NAMES", self._manifest.platform.typedefs
        )
        lines.extend(self._python_platform_targets())
        lines.extend(
            [
                f"HOSTED_STDLIB_SOURCE_MARKER = {self._manifest.provenance.stdlib_source_marker!r}",
                f"HOSTED_USER_SOURCE_MARKER = {self._manifest.provenance.user_source_marker!r}",
                f"HOSTED_ABI_FINGERPRINT = {self._manifest.fingerprint!r}",
                "",
            ]
        )
        lines.extend(self._python_targets())
        return "\n".join(lines)

    def _python_targets(self) -> list[str]:
        lines = ["TARGET_ROWS: tuple[GeneratedTargetRow, ...] = ("]
        for target in self._targets.targets:
            lines.append("    GeneratedTargetRow(")
            for field in fields(TargetRowSpec):
                value = getattr(target, field.name)
                rendered = self._python_names(value) if isinstance(value, tuple) else repr(value)
                lines.append(f"        {field.name}={rendered},")
            lines.append("    ),")
        lines.extend([")", ""])
        for name, table in (
            ("TARGET_ARCHITECTURE_ALIASES", self._targets.architecture_aliases),
            ("TARGET_DEFAULT_ENVIRONMENTS", self._targets.default_environments),
        ):
            lines.append(f"{name}: MappingProxyType[str, str] = MappingProxyType(")
            lines.append("    {")
            lines.extend(f"        {key!r}: {value!r}," for key, value in table)
            lines.extend(["    }", ")", ""])
        GeneratedSourceStyle.append_python_tuple(lines, "TARGET_ENVIRONMENTS", self._targets.ENVIRONMENTS)
        lines.append("TARGET_PREDEFINED_MACRO_ROWS: tuple[GeneratedPredefinedMacroRow, ...] = (")
        for macro in self._targets.macro_rows:
            lines.extend(
                [
                    "    GeneratedPredefinedMacroRow(",
                    f"        name={macro.name!r},",
                    f"        value={macro.value},",
                    f"        operating_systems={self._python_names(macro.operating_systems)},",
                    f"        architectures={self._python_names(macro.architectures)},",
                    f"        environments={self._python_names(macro.environments)},",
                    "    ),",
                ]
            )
        lines.extend([")", ""])
        GeneratedSourceStyle.append_python_tuple(
            lines, "TARGET_UNDEFINED_MACRO_NAMES", self._targets.undefined_macro_names
        )
        GeneratedSourceStyle.append_python_tuple(lines, "TARGET_FOREIGN_MACRO_NAMES", self._targets.foreign_macro_names)
        GeneratedSourceStyle.append_python_tuple(
            lines, "TARGET_PREDEFINED_MACRO_NAMES", self._targets.predefined_macro_names
        )
        lines.extend([f"TARGET_SPEC_FINGERPRINT = {self._targets.fingerprint!r}", ""])
        return lines

    def _python_platform_targets(self) -> list[str]:
        """``HOSTED_PLATFORM_UNAVAILABLE``: each row's unavailable ``[platform]`` names, keyed by label."""

        lines = [
            "HOSTED_PLATFORM_UNAVAILABLE: MappingProxyType[str, GeneratedPlatformTargetRow] = MappingProxyType(",
            "    {",
        ]
        for target in self._manifest.platform_targets:
            lines.extend([f"        {target.target!r}: GeneratedPlatformTargetRow(", f"            target={target.target!r},"])
            for kind in HostedAbiPlatformTargetSpec.KINDS:
                values = getattr(target, kind)
                if not values:
                    lines.append(f"            {kind}=frozenset(),")
                    continue
                lines.append(f"            {kind}=frozenset(")
                lines.append("                {")
                lines.extend(f"                    {value!r}," for value in values)
                lines.extend(["                }", "            ),"])
            lines.extend([f"            source={target.source!r},", "        ),"])
        lines.extend(["    }", ")", ""])
        return lines

    @staticmethod
    def _python_names(values: tuple[str, ...]) -> str:
        trailing = "," if len(values) == 1 else ""
        return f"({', '.join(repr(value) for value in values)}{trailing})"

    def _python_function(self, function: HostedAbiFunctionSpec) -> list[str]:
        semantic = self._python_type(function.semantic_result) if function.semantic_result is not None else "None"
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
            f"        return_alias_null_deallocator={function.return_alias_null_deallocator!r},",
            f"        realtime_effect={function.realtime_effect!r},",
            "    ),",
        ]

    @classmethod
    def _python_type(cls, shape: HostedAbiTypeSpec) -> str:
        arguments = ", ".join(cls._python_type(argument) for argument in shape.generic_args)
        generic_args = f"({arguments},)" if arguments else "()"
        return f"GeneratedAbiTypeRow({shape.base!r}, {shape.pointer_depth}, {shape.is_const!r}, {generic_args})"

    def _render_btrc(self) -> str:
        lines = [
            "/* Generated hosted-ABI data. Do not edit by hand. */",
            "",
            "import Library.Map;",
            "import Library.Vector;",
            "",
            "class GeneratedAbiTypeRow {",
            "    public string base;",
            "    public int pointerDepth;",
            "    public bool isConst;",
            "    public Vector<GeneratedAbiTypeRow> genericArgs;",
            "",
            "    public GeneratedAbiTypeRow(string base, int pointerDepth, bool isConst,",
            "            Vector<GeneratedAbiTypeRow> genericArgs) {",
            "        self.base = base;",
            "        self.pointerDepth = pointerDepth;",
            "        self.isConst = isConst;",
            "        self.genericArgs = genericArgs;",
            "    }",
            "}",
            "",
            "class GeneratedHostedParameterRow {",
            "    public GeneratedAbiTypeRow typeShape;",
            "    public string effect;",
            "    public string callbackLifetime;",
            "",
            "    public GeneratedHostedParameterRow(GeneratedAbiTypeRow typeShape, string effect,",
            "            string callbackLifetime) {",
            "        self.typeShape = typeShape;",
            "        self.effect = effect;",
            "        self.callbackLifetime = callbackLifetime;",
            "    }",
            "}",
            "",
            "class GeneratedHostedFunctionRow {",
            "    public string name;",
            "    public string origin;",
            "    public GeneratedAbiTypeRow result;",
            "    public bool parametersKnown;",
            "    public Vector<GeneratedHostedParameterRow> parameters;",
            "    public bool variadic;",
            "    public bool hasSemanticResult;",
            "    public GeneratedAbiTypeRow semanticResult;",
            "    public string returnEffect;",
            "    public int returnAliasParameter;",
            "    public string returnAliasNullEffect;",
            "    public bool rawLifetime;",
            "    public string returnDeallocator;",
            "    public string returnAliasShape;",
            "    public string consumeDeallocator;",
            "    public string returnAliasNullDeallocator;",
            "    public string realtimeEffect;",
            "",
            "    public GeneratedHostedFunctionRow(",
            "            string name, string origin, GeneratedAbiTypeRow result,",
            "            bool parametersKnown, Vector<GeneratedHostedParameterRow> parameters,",
            "            bool variadic, bool hasSemanticResult,",
            "            GeneratedAbiTypeRow semanticResult, string returnEffect,",
            "            int returnAliasParameter, string returnAliasNullEffect,",
            "            bool rawLifetime, string returnDeallocator,",
            "            string returnAliasShape, string consumeDeallocator,",
            "            string returnAliasNullDeallocator,",
            "            string realtimeEffect) {",
            "        self.name = name;",
            "        self.origin = origin;",
            "        self.result = result;",
            "        self.parametersKnown = parametersKnown;",
            "        self.parameters = parameters;",
            "        self.variadic = variadic;",
            "        self.hasSemanticResult = hasSemanticResult;",
            "        self.semanticResult = semanticResult;",
            "        self.returnEffect = returnEffect;",
            "        self.returnAliasParameter = returnAliasParameter;",
            "        self.returnAliasNullEffect = returnAliasNullEffect;",
            "        self.rawLifetime = rawLifetime;",
            "        self.returnDeallocator = returnDeallocator;",
            "        self.returnAliasShape = returnAliasShape;",
            "        self.consumeDeallocator = consumeDeallocator;",
            "        self.returnAliasNullDeallocator = returnAliasNullDeallocator;",
            "        self.realtimeEffect = realtimeEffect;",
            "    }",
            "}",
            "",
            *self._btrc_target_row_class(),
            "class GeneratedPredefinedMacroRow {",
            "    public string name;",
            "    public long long value;",
            "    public Vector<string> operatingSystems;",
            "    public Vector<string> architectures;",
            "    public Vector<string> environments;",
            "",
            "    public GeneratedPredefinedMacroRow(string name, long long value,",
            "            Vector<string> operatingSystems, Vector<string> architectures,",
            "            Vector<string> environments) {",
            "        self.name = name;",
            "        self.value = value;",
            "        self.operatingSystems = operatingSystems;",
            "        self.architectures = architectures;",
            "        self.environments = environments;",
            "    }",
            "}",
            "",
            "/* The [platform] names one target row's C compile does not declare,",
            " * one membership table per kind (hosted_abi.toml [[platform_targets]]). */",
            "class GeneratedPlatformTargetRow {",
            "    public string target;",
            "    public string source;",
            *(f"    public Map<string, bool> {kind};" for kind in HostedAbiPlatformTargetSpec.KINDS),
            "",
            "    public GeneratedPlatformTargetRow(string target, string source) {",
            "        self.target = target;",
            "        self.source = source;",
            *(
                line
                for index, kind in enumerate(HostedAbiPlatformTargetSpec.KINDS)
                for line in (f"        Map<string, bool> names{index} = {{}};", f"        self.{kind} = names{index};")
            ),
            "    }",
            "}",
            "",
            "class GeneratedHostedAbiData {",
            "    public string stdlibSourceMarker;",
            "    public string userSourceMarker;",
            "    public string fingerprint;",
            "    public string targetSpecFingerprint;",
            "    private Vector<GeneratedTargetRow>? targetRowsMemo = null;",
            "    private Map<string, string>? architectureAliasesMemo = null;",
            "    private Map<string, string>? defaultEnvironmentsMemo = null;",
            "    private Vector<GeneratedPredefinedMacroRow>? predefinedMacroRowsMemo = null;",
            "    private Vector<GeneratedHostedFunctionRow>? functionRows = null;",
            "    private Map<string, int>? functionSlots = null;",
            "    private Map<string, GeneratedHostedFunctionRow>? functionMemo = null;",
            "    private Map<string, GeneratedPlatformTargetRow>? platformTargetMemo = null;",
        ]
        name_fields = (
            *self._btrc_name_fields(),
            ("undefinedMacroNames", self._targets.undefined_macro_names),
            ("foreignMacroNames", self._targets.foreign_macro_names),
            ("predefinedMacroNames", self._targets.predefined_macro_names),
        )
        lines.extend(f"    private Vector<string>? {field}Memo = null;" for field, _ in name_fields)
        lines.extend(
            [
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
                "    private Vector<string> emptyNames() {",
                "        Vector<string> values = [];",
                "        return values;",
                "    }",
                "",
                "    public GeneratedHostedAbiData() {",
                "        self.stdlibSourceMarker = "
                f"{GeneratedSourceStyle.btrc_string(self._manifest.provenance.stdlib_source_marker)};",
                f"        self.userSourceMarker = {GeneratedSourceStyle.btrc_string(self._manifest.provenance.user_source_marker)};",
                f"        self.fingerprint = {GeneratedSourceStyle.btrc_string(self._manifest.fingerprint)};",
                f"        self.targetSpecFingerprint = {GeneratedSourceStyle.btrc_string(self._targets.fingerprint)};",
                "    }",
                "",
                "    /* Every table builds on first use. A compile that never asks for a",
                "     * name set or a function row never pays for it; building all of them",
                "     * eagerly cost twelve thousand string pushes and map inserts on every",
                "     * start of the compiler. Rows keep their manifest order. */",
                "    public Vector<GeneratedHostedFunctionRow> functions() {",
                "        Vector<GeneratedHostedFunctionRow>? rows = self.functionRows;",
                "        if (rows != null) { return rows; }",
                "        Vector<GeneratedHostedFunctionRow> built = [];",
                "        int index = 0;",
                f"        while (index < {len(self._manifest.functions)}) {{",
                "            built.push(self.functionAt(index));",
                "            index = index + 1;",
                "        }",
                "        self.functionRows = built;",
                "        return built;",
                "    }",
                "",
                "    private Map<string, GeneratedHostedFunctionRow> memoTable() {",
                "        Map<string, GeneratedHostedFunctionRow>? existing = self.functionMemo;",
                "        if (existing != null) { return existing; }",
                "        Map<string, GeneratedHostedFunctionRow> fresh = {};",
                "        self.functionMemo = fresh;",
                "        return fresh;",
                "    }",
                "",
                "    private Map<string, int> slotTable() {",
                "        Map<string, int>? existing = self.functionSlots;",
                "        if (existing != null) { return existing; }",
                "        Map<string, int> indexed = {};",
                "        self.indexFunctions(indexed);",
                "        self.functionSlots = indexed;",
                "        return indexed;",
                "    }",
                "",
                "    public GeneratedHostedFunctionRow? functionNamed(string name) {",
                "        Map<string, GeneratedHostedFunctionRow> memo = self.memoTable();",
                "        if (memo.has(name)) { return memo.get(name); }",
                "        Map<string, int> slots = self.slotTable();",
                "        if (!slots.has(name)) { return null; }",
                "        GeneratedHostedFunctionRow row = self.functionAt(slots.get(name));",
                "        memo.put(name, row);",
                "        return row;",
                "    }",
                "",
            ]
        )
        # Populating every table from one method produced a single C function of
        # 114,000 lines, and a C optimizer's cost grows superlinearly with
        # function size: that one function accounted for roughly 90% of the time
        # to compile the whole self-hosted compiler. Rows and names therefore
        # spread over many small methods, in manifest order.
        functions = list(self._manifest.functions)
        chunks = range(0, len(functions), self.BTRC_ROWS_PER_METHOD)
        lines.append("    private GeneratedHostedFunctionRow functionAt(int index) {")
        for chunk, start_index in enumerate(chunks):
            bound = start_index + self.BTRC_ROWS_PER_METHOD
            lines.append(f"        if (index < {bound}) {{ return self.functionRow{chunk}(index); }}")
        lines.extend(['        throw "hosted ABI function row index out of range";', "    }", ""])
        for chunk, start_index in enumerate(chunks):
            lines.append(f"    private GeneratedHostedFunctionRow functionRow{chunk}(int index) {{")
            for offset, function in enumerate(functions[start_index : start_index + self.BTRC_ROWS_PER_METHOD]):
                lines.append(f"        if (index == {start_index + offset}) {{")
                lines.extend(self._btrc_function(function))
                lines.append("        }")
            lines.extend(['        throw "hosted ABI function row index out of range";', "    }", ""])
        lines.append("    private void indexFunctions(Map<string, int> slots) {")
        index_chunks = range(0, len(functions), self.BTRC_NAMES_PER_METHOD)
        lines.extend(f"        self.indexFunctions{chunk}(slots);" for chunk, _ in enumerate(index_chunks))
        lines.extend(["    }", ""])
        for chunk, start_index in enumerate(index_chunks):
            lines.append(f"    private void indexFunctions{chunk}(Map<string, int> slots) {{")
            for offset, function in enumerate(functions[start_index : start_index + self.BTRC_NAMES_PER_METHOD]):
                lines.append(
                    f"        slots.put({GeneratedSourceStyle.btrc_string(function.name)}, {start_index + offset});"
                )
            lines.extend(["    }", ""])
        for field, values in name_fields:
            method = f"push{field[:1].upper()}{field[1:]}"
            value_chunks = range(0, len(values), self.BTRC_NAMES_PER_METHOD)
            lines.extend(
                [
                    f"    public Vector<string> {field}() {{",
                    f"        Vector<string>? memo = self.{field}Memo;",
                    "        if (memo != null) { return memo; }",
                    "        Vector<string> built = [];",
                ]
            )
            lines.extend(f"        self.{method}{chunk}(built);" for chunk, _ in enumerate(value_chunks))
            lines.extend([f"        self.{field}Memo = built;", "        return built;", "    }", ""])
            for chunk, start_index in enumerate(value_chunks):
                lines.append(f"    private void {method}{chunk}(Vector<string> values) {{")
                lines.extend(
                    f"        values.push({GeneratedSourceStyle.btrc_string(value)});"
                    for value in values[start_index : start_index + self.BTRC_NAMES_PER_METHOD]
                )
                lines.extend(["    }", ""])
        lines.extend(self._btrc_platform_targets())
        lines.extend(self._btrc_targets())
        lines.extend(["}", ""])
        return "\n".join(lines)

    def _btrc_platform_targets(self) -> list[str]:
        """``platformUnavailable(label)``: one row's tables, built on first use for that label only.

        Each kind's names spread over small methods, like the hosted tables.
        """

        lines = [
            "    private Map<string, GeneratedPlatformTargetRow> platformTargetTable() {",
            "        Map<string, GeneratedPlatformTargetRow>? existing = self.platformTargetMemo;",
            "        if (existing != null) { return existing; }",
            "        Map<string, GeneratedPlatformTargetRow> fresh = {};",
            "        self.platformTargetMemo = fresh;",
            "        return fresh;",
            "    }",
            "",
            "    public GeneratedPlatformTargetRow? platformUnavailable(string label) {",
            "        Map<string, GeneratedPlatformTargetRow> memo = self.platformTargetTable();",
            "        if (memo.has(label)) { return memo.get(label); }",
            "        GeneratedPlatformTargetRow? built = self.platformTargetNamed(label);",
            "        if (built != null) { memo.put(label, built); }",
            "        return built;",
            "    }",
            "",
            "    private GeneratedPlatformTargetRow? platformTargetNamed(string label) {",
        ]
        targets = self._manifest.platform_targets
        lines.extend(
            f"        if (label == {GeneratedSourceStyle.btrc_string(target.target)}) "
            f"{{ return self.platformTarget{index}(); }}"
            for index, target in enumerate(targets)
        )
        lines.extend(["        return null;", "    }", ""])
        for index, target in enumerate(targets):
            body = [
                f"    private GeneratedPlatformTargetRow platformTarget{index}() {{",
                "        GeneratedPlatformTargetRow row = GeneratedPlatformTargetRow("
                f"{GeneratedSourceStyle.btrc_string(target.target)}, {GeneratedSourceStyle.btrc_string(target.source)});",
            ]
            methods: list[str] = []
            for kind in HostedAbiPlatformTargetSpec.KINDS:
                values = getattr(target, kind)
                for chunk, start_index in enumerate(range(0, len(values), self.BTRC_NAMES_PER_METHOD)):
                    method = f"putPlatformTarget{index}{kind[:1].upper()}{kind[1:]}{chunk}"
                    body.append(f"        self.{method}(row.{kind});")
                    methods.append(f"    private void {method}(Map<string, bool> names) {{")
                    methods.extend(
                        f"        names.put({GeneratedSourceStyle.btrc_string(value)}, true);"
                        for value in values[start_index : start_index + self.BTRC_NAMES_PER_METHOD]
                    )
                    methods.extend(["    }", ""])
            lines.extend([*body, "        return row;", "    }", "", *methods])
        return lines

    def _btrc_targets(self) -> list[str]:
        """The target spec's rows and tables, built on first use like the hosted tables."""

        lines = [
            "    public Vector<GeneratedTargetRow> targetRows() {",
            "        Vector<GeneratedTargetRow>? memo = self.targetRowsMemo;",
            "        if (memo != null) { return memo; }",
            "        Vector<GeneratedTargetRow> built = [];",
        ]
        for target in self._targets.targets:
            arguments = ", ".join(self._btrc_value(getattr(target, field.name)) for field in fields(TargetRowSpec))
            lines.append(f"        built.push(GeneratedTargetRow({arguments}));")
        lines.extend(["        self.targetRowsMemo = built;", "        return built;", "    }", ""])
        for method, table in (
            ("architectureAliases", self._targets.architecture_aliases),
            ("defaultEnvironments", self._targets.default_environments),
        ):
            lines.extend(
                [
                    f"    public Map<string, string> {method}() {{",
                    f"        Map<string, string>? memo = self.{method}Memo;",
                    "        if (memo != null) { return memo; }",
                    "        Map<string, string> built = {};",
                ]
            )
            lines.extend(
                f"        built.put({GeneratedSourceStyle.btrc_string(key)}, {GeneratedSourceStyle.btrc_string(value)});"
                for key, value in table
            )
            lines.extend([f"        self.{method}Memo = built;", "        return built;", "    }", ""])
        # The hand-written rows, then the derived ones, spread over small
        # methods like the hosted tables.
        macros = list(self._targets.macro_rows)
        chunks = range(0, len(macros), self.BTRC_ROWS_PER_METHOD)
        lines.extend(
            [
                "    public Vector<GeneratedPredefinedMacroRow> predefinedMacroRows() {",
                "        Vector<GeneratedPredefinedMacroRow>? memo = self.predefinedMacroRowsMemo;",
                "        if (memo != null) { return memo; }",
                "        Vector<GeneratedPredefinedMacroRow> built = [];",
            ]
        )
        lines.extend(f"        self.pushPredefinedMacroRows{chunk}(built);" for chunk, _ in enumerate(chunks))
        lines.extend(["        self.predefinedMacroRowsMemo = built;", "        return built;", "    }", ""])
        for chunk, start_index in enumerate(chunks):
            lines.append(
                f"    private void pushPredefinedMacroRows{chunk}(Vector<GeneratedPredefinedMacroRow> built) {{"
            )
            lines.extend(
                "        built.push(GeneratedPredefinedMacroRow("
                f"{GeneratedSourceStyle.btrc_string(macro.name)}, {macro.value}LL, "
                f"{self._btrc_names(macro.operating_systems)}, {self._btrc_names(macro.architectures)}, "
                f"{self._btrc_names(macro.environments)}));"
                for macro in macros[start_index : start_index + self.BTRC_ROWS_PER_METHOD]
            )
            lines.extend(["    }", ""])
        return lines

    @classmethod
    def _btrc_target_row_class(cls) -> list[str]:
        """``GeneratedTargetRow`` with the spec's columns respelled in camelCase, in spec order."""

        columns = [(cls._btrc_field(field.name), cls._BTRC_COLUMN_TYPES[field.type]) for field in fields(TargetRowSpec)]
        parameters = ", ".join(f"{kind} {name}" for name, kind in columns)
        return [
            "class GeneratedTargetRow {",
            *(f"    public {kind} {name};" for name, kind in columns),
            "",
            f"    public GeneratedTargetRow({parameters}) {{",
            *(f"        self.{name} = {name};" for name, _ in columns),
            "    }",
            "}",
            "",
        ]

    _BTRC_COLUMN_TYPES = MappingProxyType(
        {"str": "string", "int": "int", "bool": "bool", "tuple[str, ...]": "Vector<string>"}
    )

    @staticmethod
    def _btrc_field(name: str) -> str:
        """Respell one snake_case spec field the way btrc source spells names."""

        head, *rest = name.split("_")
        return head + "".join(part[:1].upper() + part[1:] for part in rest)

    def _btrc_value(self, value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, tuple):
            return self._btrc_names(value)
        return GeneratedSourceStyle.btrc_string(str(value))

    @staticmethod
    def _btrc_names(values: tuple[str, ...]) -> str:
        if not values:
            return "self.emptyNames()"
        return f"[{', '.join(GeneratedSourceStyle.btrc_string(value) for value in values)}]"

    BTRC_ROWS_PER_METHOD = 40
    BTRC_NAMES_PER_METHOD = 250

    def _btrc_function(self, function: HostedAbiFunctionSpec) -> list[str]:
        semantic = function.semantic_result or function.result
        lines = [
            "            return GeneratedHostedFunctionRow(",
            f"            {GeneratedSourceStyle.btrc_string(function.name)},",
            f"            {GeneratedSourceStyle.btrc_string(function.origin)},",
            f"            {self._btrc_type(function.result)},",
            f"            {'true' if function.parameters_known else 'false'},",
        ]
        if function.parameters:
            lines.append("            [")
            lines.extend(
                "                GeneratedHostedParameterRow("
                f"{self._btrc_type(parameter.type_shape)}, "
                f"{GeneratedSourceStyle.btrc_string(parameter.effect)}, "
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
                f"            {GeneratedSourceStyle.btrc_string(function.return_effect)},",
                f"            {function.return_alias_parameter if function.return_alias_parameter is not None else -1},",
                f"            {self._btrc_optional(function.return_alias_null_effect)},",
                f"            {'true' if function.raw_lifetime else 'false'},",
                f"            {self._btrc_optional(function.return_deallocator)},",
                f"            {self._btrc_optional(function.return_alias_shape)},",
                f"            {self._btrc_optional(function.consume_deallocator)},",
                f"            {self._btrc_optional(function.return_alias_null_deallocator)},",
                f"            {GeneratedSourceStyle.btrc_string(function.realtime_effect)});",
            ]
        )
        return lines

    def _btrc_name_fields(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The name sets the self-hosted analyzer consults (HostedAbiRepository).

        The reference tables carry every set; the self-host only ever asks
        whether a name is a hosted function, macro, typedef, owned name,
        adopting helper or non-returning function, and its structure contract rejects accessors nothing
        calls, so the other sets are not emitted for it.
        """

        return (
            ("functionNames", self._manifest.names.functions),
            ("macroNames", self._manifest.names.macros),
            ("typedefNames", self._manifest.names.typedefs),
            ("ownedNames", self._manifest.names.owned),
            ("runtimeAdoptingHelpers", self._manifest.names.runtime_adopting_helpers),
            ("noreturnFunctions", self._manifest.names.noreturn),
        )

    def _btrc_type(self, shape: HostedAbiTypeSpec) -> str:
        arguments = ", ".join(self._btrc_type(argument) for argument in shape.generic_args)
        generic_args = f"[{arguments}]" if arguments else "self.emptyTypes()"
        return (
            "GeneratedAbiTypeRow("
            f"{GeneratedSourceStyle.btrc_string(shape.base)}, {shape.pointer_depth}, "
            f"{'true' if shape.is_const else 'false'}, {generic_args})"
        )

    def _btrc_optional(self, value: str | None) -> str:
        return GeneratedSourceStyle.btrc_string(value or "")
