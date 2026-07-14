"""Compatibility and override validation for precompiled stdlib archives."""

from __future__ import annotations

import hashlib
import os

from .cache_io import load_json, open_regular_binary
from .cache_keys import toolchain_hash

MANIFEST_SCHEMA = 5
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_ARTIFACT_BYTES = 512 * 1024 * 1024
ARCHIVE_ARTIFACT_NAMES = ("btrc_stdlib.h", "btrc_stdlib.c")
MANIFEST_LIST_FIELDS = (
    "function_declarations",
    "functions",
    "global_decl_names",
    "helpers",
    "shared_helpers",
    "types",
)
_MACRO_FIELDS = {"name", "params", "replacement"}
_MANIFEST_FIELDS = {
    "artifacts",
    "schema",
    "stdlib_source",
    "toolchain",
    "macros",
    *MANIFEST_LIST_FIELDS,
}


class ArchiveVersionError(Exception):
    """The archive is incompatible with the compiler, stdlib, or program."""


def stdlib_source_hash(stdlib_source: str) -> str:
    return hashlib.sha256(stdlib_source.encode("utf-8")).hexdigest()


def valid_manifest(manifest) -> bool:
    return (
        isinstance(manifest, dict)
        and set(manifest) == _MANIFEST_FIELDS
        and manifest.get("schema") == MANIFEST_SCHEMA
        and isinstance(manifest.get("stdlib_source"), str)
        and isinstance(manifest.get("toolchain"), str)
        and isinstance(manifest.get("artifacts"), dict)
        and set(manifest["artifacts"]) == set(ARCHIVE_ARTIFACT_NAMES)
        and all(_valid_sha256(value) for value in manifest["artifacts"].values())
        and isinstance(manifest.get("macros"), list)
        and all(_valid_macro(macro) for macro in manifest["macros"])
        and all(
            isinstance(manifest.get(field), list) and all(isinstance(value, str) for value in manifest[field])
            for field in MANIFEST_LIST_FIELDS
        )
    )


def _valid_sha256(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_macro(macro) -> bool:
    if not (
        isinstance(macro, dict)
        and set(macro) == _MACRO_FIELDS
        and isinstance(macro["name"], str)
        and (
            macro["params"] is None
            or (isinstance(macro["params"], list) and all(isinstance(param, str) for param in macro["params"]))
        )
        and isinstance(macro["replacement"], str)
    ):
        return False

    from .ir.nodes import IRMacroDef

    try:
        IRMacroDef(**macro)
    except (TypeError, ValueError):
        return False
    return True


def load_manifest(
    stdlib_dir: str,
    stdlib_source: str,
    manifest_name: str,
) -> dict:
    """Load an archive manifest and verify compiler and canonical stdlib bytes."""
    manifest = load_json(
        os.path.join(stdlib_dir, manifest_name),
        max_bytes=MAX_MANIFEST_BYTES,
        follow_symlinks=True,
    )
    if not valid_manifest(manifest):
        raise ArchiveVersionError(
            f"stdlib archive in '{stdlib_dir}' has an invalid or unsupported "
            "manifest; regenerate it with --build-stdlib"
        )
    current = toolchain_hash("full")
    stamped = manifest["toolchain"]
    if stamped != current:
        raise ArchiveVersionError(
            f"stdlib archive in '{stdlib_dir}' was built by a different "
            f"compiler version (archive: {stamped or 'unstamped'}, current: "
            f"{current}); regenerate it with --build-stdlib"
        )
    if manifest["stdlib_source"] != stdlib_source_hash(stdlib_source):
        raise ArchiveVersionError(
            f"stdlib archive in '{stdlib_dir}' was built from a different "
            "standard library source; regenerate it with --build-stdlib or "
            "compile without --stdlib"
        )
    for artifact_name, expected_hash in manifest["artifacts"].items():
        artifact_path = os.path.join(stdlib_dir, artifact_name)
        try:
            actual_hash = _artifact_hash(artifact_path)
        except OSError as error:
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' is incomplete: missing "
                f"{artifact_name}; regenerate it with --build-stdlib"
            ) from error
        if actual_hash is None:
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' has an invalid {artifact_name}; regenerate it with --build-stdlib"
            )
        if actual_hash != expected_hash:
            raise ArchiveVersionError(
                f"stdlib archive in '{stdlib_dir}' has a modified {artifact_name}; regenerate it with --build-stdlib"
            )
    return manifest


def _artifact_hash(path: str) -> str | None:
    """Hash one bounded regular archive artifact, or reject it."""
    digest = hashlib.sha256()
    artifact_file = open_regular_binary(path, follow_symlinks=True)
    if artifact_file is None:
        return None
    with artifact_file:
        metadata = os.fstat(artifact_file.fileno())
        if metadata.st_size <= 0 or metadata.st_size > MAX_ARCHIVE_ARTIFACT_BYTES:
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


def reject_user_overrides(program, manifest: dict) -> None:
    """Reject user declarations that an archive partition would drop by name.

    Declarations originating in ``src/stdlib`` are ordinary resolved imports of
    the canonical sources and are safe. A same-named declaration from any other
    file is a real override and cannot be linked against the prebuilt archive.
    """
    provided = set(manifest["types"]) | set(manifest["functions"]) | set(manifest["global_decl_names"])
    stdlib_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "stdlib"))
    conflicts = set()
    for declaration in program.declarations:
        name = getattr(declaration, "name", None)
        if not name or name not in provided:
            continue
        source_file = getattr(declaration, "source_file", None)
        if source_file and _is_within(source_file, stdlib_root):
            continue
        conflicts.add(name)
    if conflicts:
        names = ", ".join(sorted(conflicts))
        raise ArchiveVersionError(
            f"program overrides archive-provided stdlib declarations ({names}); compile without --stdlib"
        )


def _is_within(path: str, directory: str) -> bool:
    try:
        return os.path.commonpath((os.path.realpath(path), directory)) == directory
    except (OSError, ValueError):
        return False
