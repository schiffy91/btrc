"""Validated compiler-intrinsic effect and lowering specification."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class IntrinsicEffectManifestError(ValueError):
    """The shared compiler-intrinsic effect specification is malformed."""


@dataclass(frozen=True, slots=True)
class IntrinsicEffectSpec:
    """One exact typed method effect and optional emitted C callee."""

    receiver: str
    method: str
    realtime_effect: str
    c_callee: str | None

    @property
    def provenance(self) -> str:
        return f"{self.receiver}.{self.method}"


@dataclass(frozen=True, slots=True)
class IntrinsicEffectManifest:
    """Canonical intrinsic effects consumed by both compiler implementations."""

    schema_version: int
    methods: tuple[IntrinsicEffectSpec, ...]

    _ROOT_KEYS = frozenset({"schema_version", "methods"})
    _METHOD_KEYS = frozenset({"receiver", "method", "realtime_effect", "c_callee"})
    _METHOD_REQUIRED_KEYS = frozenset({"receiver", "method", "realtime_effect"})
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
    def load(cls, path: Path) -> IntrinsicEffectManifest:
        try:
            data = path.read_bytes()
            if b"\x00" in data or b"\r" in data:
                raise IntrinsicEffectManifestError(
                    f"intrinsic effect manifest must be NUL-free UTF-8 with LF endings: {path}"
                )
            document = tomllib.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise IntrinsicEffectManifestError(f"cannot read intrinsic effect manifest {path}: {error}") from error
        cls._require_keys(document, cls._ROOT_KEYS, "intrinsic effect manifest")
        schema_version = document.get("schema_version")
        if type(schema_version) is not int or schema_version != 1:
            raise IntrinsicEffectManifestError(f"unsupported intrinsic effect schema version: {schema_version!r}")
        raw_methods = document.get("methods")
        if not isinstance(raw_methods, list) or not raw_methods:
            raise IntrinsicEffectManifestError("methods must be a non-empty array of tables")
        methods = tuple(cls._method(value, index) for index, value in enumerate(raw_methods))
        provenances = tuple(method.provenance for method in methods)
        if provenances != tuple(sorted(provenances)):
            raise IntrinsicEffectManifestError("methods must be sorted by receiver and method")
        if len(provenances) != len(set(provenances)):
            raise IntrinsicEffectManifestError("methods must not contain duplicate receiver/method pairs")
        return cls(schema_version=schema_version, methods=methods)

    @classmethod
    def _method(cls, value: Any, index: int) -> IntrinsicEffectSpec:
        context = f"methods[{index}]"
        if not isinstance(value, dict):
            raise IntrinsicEffectManifestError(f"{context} must be a table")
        cls._require_keys(value, cls._METHOD_KEYS, context, required=cls._METHOD_REQUIRED_KEYS)
        receiver = cls._identifier(value, "receiver", context)
        method = cls._identifier(value, "method", context)
        realtime_effect = value.get("realtime_effect")
        if not isinstance(realtime_effect, str) or realtime_effect not in cls._REALTIME_EFFECTS:
            raise IntrinsicEffectManifestError(f"{context}.realtime_effect is invalid")
        c_callee = cls._identifier(value, "c_callee", context) if "c_callee" in value else None
        return IntrinsicEffectSpec(receiver, method, realtime_effect, c_callee)

    @classmethod
    def _identifier(cls, table: dict[str, Any], key: str, context: str) -> str:
        value = table.get(key)
        if not isinstance(value, str) or not cls._IDENTIFIER.fullmatch(value):
            raise IntrinsicEffectManifestError(f"{context}.{key} must be a C identifier")
        return value

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
            raise IntrinsicEffectManifestError(f"unknown {context} keys: {', '.join(sorted(unknown))}")
        missing = (required or allowed) - set(table)
        if missing:
            raise IntrinsicEffectManifestError(f"missing {context} keys: {', '.join(sorted(missing))}")
