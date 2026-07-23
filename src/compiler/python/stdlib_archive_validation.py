"""Owned compatibility and override policy for precompiled stdlib archives."""

from __future__ import annotations

import hashlib
import os

from .artifacts.cache.compiler_cache import ToolchainFingerprint
from .artifacts.stdlib.publisher import StdlibArchivePublisher
from .cache_io import load_json, open_regular_binary
from .ir.nodes import IRMacroDef


class ArchiveVersionError(Exception):
    """The archive is incompatible with the compiler, stdlib, or program."""


class StdlibArchiveManifest:
    """Own archive manifest schema, loading, integrity, and override checks."""

    SCHEMA = 5
    MAX_BYTES = 16 * 1024 * 1024
    MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
    ARTIFACT_NAMES = ("btrc_stdlib.h", "btrc_stdlib.c")
    LIST_FIELDS = (
        "function_declarations",
        "functions",
        "global_decl_names",
        "helpers",
        "shared_helpers",
        "types",
    )
    _MACRO_FIELDS = frozenset({"name", "params", "replacement"})
    _FIELDS = frozenset(
        {
            "artifacts",
            "schema",
            "stdlib_source",
            "toolchain",
            "macros",
            *LIST_FIELDS,
        }
    )

    def __init__(
        self,
        publisher: StdlibArchivePublisher,
        fingerprint: ToolchainFingerprint | None = None,
        *,
        manifest_name: str = "btrc_stdlib.manifest",
        stdlib_root: str | None = None,
    ) -> None:
        self.publisher = publisher
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.manifest_name = manifest_name
        self.stdlib_root = os.path.realpath(
            stdlib_root or os.path.join(os.path.dirname(__file__), "..", "..", "stdlib")
        )

    def source_hash(self, stdlib_source: str) -> str:
        return hashlib.sha256(stdlib_source.encode("utf-8")).hexdigest()

    def valid(self, manifest) -> bool:
        return (
            isinstance(manifest, dict)
            and set(manifest) == self._FIELDS
            and manifest.get("schema") == self.SCHEMA
            and isinstance(manifest.get("stdlib_source"), str)
            and isinstance(manifest.get("toolchain"), str)
            and isinstance(manifest.get("artifacts"), dict)
            and set(manifest["artifacts"]) == set(self.ARTIFACT_NAMES)
            and all(self._valid_sha256(value) for value in manifest["artifacts"].values())
            and isinstance(manifest.get("macros"), list)
            and all(self._valid_macro(macro) for macro in manifest["macros"])
            and all(
                isinstance(manifest.get(field), list) and all(isinstance(value, str) for value in manifest[field])
                for field in self.LIST_FIELDS
            )
        )

    def load(self, stdlib_dir: str, stdlib_source: str) -> dict:
        """Load and authenticate one archive against compiler and stdlib."""

        if self.publisher.publication_in_progress(stdlib_dir):
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' is being updated; retry after the publication completes"
            )
        manifest = load_json(
            os.path.join(stdlib_dir, self.manifest_name),
            max_bytes=self.MAX_BYTES,
            follow_symlinks=True,
        )
        if not self.valid(manifest):
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' has an invalid or unsupported "
                "manifest; regenerate it with --build-stdlib"
            )
        current = self.fingerprint.digest("full")
        stamped = manifest["toolchain"]
        if stamped != current:
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' was built by a different "
                f"compiler version (archive: {stamped or 'unstamped'}, current: "
                f"{current}); regenerate it with --build-stdlib"
            )
        if manifest["stdlib_source"] != self.source_hash(stdlib_source):
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' was built from a different "
                "standard library source; regenerate it with --build-stdlib or "
                "compile without --stdlib"
            )
        for artifact_name, expected_hash in manifest["artifacts"].items():
            artifact_path = os.path.join(stdlib_dir, artifact_name)
            try:
                actual_hash = self._artifact_hash(artifact_path)
            except OSError as error:
                raise ArchiveVersionError(
                    f"stdlib archive in '{stdlib_dir}' is incomplete: missing "
                    f"{artifact_name}; regenerate it with --build-stdlib"
                ) from error
            if actual_hash is None:
                raise ArchiveVersionError(
                    f"stdlib archive in '{stdlib_dir}' has an invalid "
                    f"{artifact_name}; regenerate it with --build-stdlib"
                )
            if actual_hash != expected_hash:
                raise ArchiveVersionError(
                    f"stdlib archive in '{stdlib_dir}' has a modified "
                    f"{artifact_name}; regenerate it with --build-stdlib"
                )
        return manifest

    def reject_user_overrides(self, program, manifest: dict) -> None:
        """Reject declarations that archive partitioning would drop by name."""

        provided = set(manifest["types"]) | set(manifest["functions"]) | set(manifest["global_decl_names"])
        conflicts = set()
        for declaration in program.declarations:
            name = getattr(declaration, "name", None)
            if not name or name not in provided:
                continue
            source_file = getattr(declaration, "source_file", None)
            if source_file and self._is_within(source_file, self.stdlib_root):
                continue
            conflicts.add(name)
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise ArchiveVersionError(
                f"program overrides archive-provided stdlib declarations ({names}); compile without --stdlib"
            )

    def _valid_sha256(self, value) -> bool:
        return (
            isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
        )

    def _valid_macro(self, macro) -> bool:
        if not (
            isinstance(macro, dict)
            and set(macro) == self._MACRO_FIELDS
            and isinstance(macro["name"], str)
            and (
                macro["params"] is None
                or (isinstance(macro["params"], list) and all(isinstance(param, str) for param in macro["params"]))
            )
            and isinstance(macro["replacement"], str)
        ):
            return False
        try:
            IRMacroDef(**macro)
        except (TypeError, ValueError):
            return False
        return True

    def _artifact_hash(self, path: str) -> str | None:
        """Hash one bounded regular archive artifact, or reject it."""

        digest = hashlib.sha256()
        artifact_file = open_regular_binary(path, follow_symlinks=True)
        if artifact_file is None:
            return None
        with artifact_file:
            metadata = os.fstat(artifact_file.fileno())
            if metadata.st_size <= 0 or metadata.st_size > self.MAX_ARTIFACT_BYTES:
                return None
            remaining = metadata.st_size
            while remaining:
                chunk = artifact_file.read(min(1024 * 1024, remaining))
                if not chunk:
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
            if artifact_file.read(1):
                return None
        return digest.hexdigest()

    def _is_within(self, path: str, directory: str) -> bool:
        try:
            return os.path.commonpath((os.path.realpath(path), directory)) == directory
        except (OSError, ValueError):
            return False


__all__ = ["ArchiveVersionError", "StdlibArchiveManifest"]
