"""Persist, authenticate, and publish standard-library archive payloads."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .cache import AtomicFileStore, ToolchainFingerprint
from .publication import ArtifactPublisher, ArtifactStorage, PublishedArtifact


class StdlibArchivePublisher:
    """Own staging and atomic publication of one stdlib archive generation."""

    PUBLICATION_NAME = "btrc-stdlib"

    def __init__(self, publication: ArtifactPublisher) -> None:
        self._publication = publication

    def publish(
        self,
        output_dir: str,
        header_name: str,
        header: str,
        impl_name: str,
        impl: str,
        manifest_name: str,
        manifest: dict,
    ) -> None:
        """Publish payload files first and their hash manifest last."""

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        encoded_manifest = json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with tempfile.TemporaryDirectory(
            prefix=".btrc-stdlib.candidate-",
            dir=directory,
        ) as temporary:
            candidate = Path(temporary)
            staged_header = candidate / header_name
            staged_impl = candidate / impl_name
            staged_manifest = candidate / manifest_name
            for path, content in (
                (staged_header, header),
                (staged_impl, impl),
                (staged_manifest, encoded_manifest),
            ):
                path.write_text(content, encoding="utf-8", newline="\n")
                path.chmod(0o644)
            self._publication.publish(
                self.PUBLICATION_NAME,
                (
                    PublishedArtifact(staged_header, directory / header_name),
                    PublishedArtifact(staged_impl, directory / impl_name),
                    PublishedArtifact(staged_manifest, directory / manifest_name),
                ),
            )

    def publication_in_progress(self, output_dir: str) -> bool:
        return self._publication.publication_in_progress(
            Path(output_dir),
            self.PUBLICATION_NAME,
        )

class ArchiveVersionError(ValueError):
    """The archive is incompatible with the compiler, stdlib, or program."""


class StdlibArchiveManifest:
    """Own archive manifest schema, loading, and integrity checks."""

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
        file_store: AtomicFileStore | None = None,
    ) -> None:
        self.publisher = publisher
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.manifest_name = manifest_name
        self.file_store = file_store or AtomicFileStore()

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
        manifest = self.file_store.read_json(
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
        return bool(macro["name"]) and "\n" not in macro["name"]

    def _artifact_hash(self, path: str) -> str | None:
        """Hash one bounded regular archive artifact, or reject it."""

        digest = hashlib.sha256()
        artifact_file = self.file_store.open_regular_binary(
            path,
            follow_symlinks=True,
        )
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

HEADER_NAME, IMPL_NAME = StdlibArchiveManifest.ARTIFACT_NAMES
MANIFEST_NAME = "btrc_stdlib.manifest"
MANIFEST_SCHEMA = StdlibArchiveManifest.SCHEMA

class StdlibArtifactRepository:
    """Own standard-library archive serialization and publication."""

    available = True
    header_name = HEADER_NAME

    def __init__(
        self,
        publisher: StdlibArchivePublisher | None = None,
        fingerprint: ToolchainFingerprint | None = None,
    ) -> None:
        self.publisher = publisher or StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.manifest = StdlibArchiveManifest(
            self.publisher,
            self.fingerprint,
            manifest_name=MANIFEST_NAME,
        )

    def publish(
        self,
        out_dir: str,
        stdlib_source: str,
        header: str,
        implementation: str,
        metadata: dict,
    ) -> dict:
        """Stamp and atomically publish one application-prepared payload."""

        manifest = {
            **metadata,
            "artifacts": {
                HEADER_NAME: hashlib.sha256(header.encode("utf-8")).hexdigest(),
                IMPL_NAME: hashlib.sha256(implementation.encode("utf-8")).hexdigest(),
            },
            "schema": MANIFEST_SCHEMA,
            "stdlib_source": self.manifest.source_hash(stdlib_source),
            "toolchain": self.fingerprint.digest("full"),
        }
        if not self.manifest.valid(manifest):
            raise ValueError("application supplied invalid stdlib archive metadata")
        self.publisher.publish(
            out_dir,
            HEADER_NAME,
            header,
            IMPL_NAME,
            implementation,
            MANIFEST_NAME,
            manifest,
        )
        return manifest

    def load(self, stdlib_dir: str, stdlib_source: str) -> dict:
        """Load and validate an archive against the canonical whole stdlib."""

        return self.manifest.load(stdlib_dir, stdlib_source)
