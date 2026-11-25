"""Persist, authenticate, and publish precompiled user-package archive payloads."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from ..abi.generated import TARGET_SPEC_FINGERPRINT
from .cache import AtomicFileStore, ToolchainFingerprint
from .publication import ArtifactPublisher, ArtifactStorage, PublishedArtifact


class PackageArchiveError(ValueError):
    """A precompiled package archive is missing, invalid, or incompatible."""


class PackageArchivePublisher:
    """Own staging and atomic publication of one precompiled package archive generation."""

    def __init__(self, publication: ArtifactPublisher) -> None:
        self._publication = publication

    @staticmethod
    def publication_name(package_name: str) -> str:
        return f"btrc-pkg-{package_name}"

    def publish(
        self,
        output_dir: str,
        package_name: str,
        header_name: str,
        header: str,
        impl_name: str,
        impl: str,
        link_plan_name: str,
        link_plan_json: str,
        manifest_name: str,
        manifest: dict,
    ) -> None:
        """Publish payload files first and their authenticated manifest last."""

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        encoded_manifest = json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        pub_name = self.publication_name(package_name)
        with tempfile.TemporaryDirectory(
            prefix=f".{pub_name}.candidate-",
            dir=directory,
        ) as temporary:
            candidate = Path(temporary)
            staged_header = candidate / header_name
            staged_impl = candidate / impl_name
            staged_plan = candidate / link_plan_name
            staged_manifest = candidate / manifest_name
            for path, content in (
                (staged_header, header),
                (staged_impl, impl),
                (staged_plan, link_plan_json),
                (staged_manifest, encoded_manifest),
            ):
                path.write_text(content, encoding="utf-8", newline="\n")
                path.chmod(0o644)
            self._publication.publish(
                pub_name,
                (
                    PublishedArtifact(staged_header, directory / header_name),
                    PublishedArtifact(staged_impl, directory / impl_name),
                    PublishedArtifact(staged_plan, directory / link_plan_name),
                    PublishedArtifact(staged_manifest, directory / manifest_name),
                ),
            )

    def publication_in_progress(self, output_dir: str, package_name: str) -> bool:
        return self._publication.publication_in_progress(
            Path(output_dir),
            self.publication_name(package_name),
        )


class PackageArchiveManifest:
    """Own precompiled package archive manifest schema, loading, and integrity checks."""

    SCHEMA = 1
    MAX_BYTES = 16 * 1024 * 1024
    MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
    LIST_FIELDS = (
        "exports",
        "function_declarations",
        "functions",
        "generated_units",
        "global_decl_names",
        "gpu_kernels",
        "helpers",
        "native_units",
        "shared_helpers",
        "source_files",
        "types",
    )
    _MACRO_FIELDS = frozenset({"name", "params", "replacement"})
    _FIELDS = frozenset(
        {
            "artifacts",
            "header_name",
            "impl_name",
            "link_plan_name",
            "macros",
            "package",
            "package_root",
            "package_source",
            "schema",
            "target",
            "target_spec",
            "toolchain",
            *LIST_FIELDS,
        }
    )

    def __init__(
        self,
        publisher: PackageArchivePublisher,
        fingerprint: ToolchainFingerprint | None = None,
        *,
        file_store: AtomicFileStore | None = None,
    ) -> None:
        self.publisher = publisher
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.file_store = file_store or AtomicFileStore()

    @staticmethod
    def artifact_names(package_name: str) -> tuple[str, str, str, str]:
        return (
            f"{package_name}.h",
            f"{package_name}.c",
            f"{package_name}.link.json",
            f"{package_name}.manifest",
        )

    @staticmethod
    def source_hash(source_entries: dict[str, str]) -> str:
        digest = hashlib.sha256()
        for key in sorted(source_entries):
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            digest.update(source_entries[key].encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def discover_manifest_path(self, archive_dir: str) -> Path:
        directory = Path(archive_dir)
        if not directory.is_dir():
            raise PackageArchiveError(f"package archive directory '{archive_dir}' does not exist")
        manifests = sorted(
            p
            for p in directory.iterdir()
            if p.is_file() and p.name.endswith(".manifest") and not p.name.startswith(".")
        )
        if not manifests:
            raise PackageArchiveError(
                f"package archive directory '{archive_dir}' has no .manifest file; generate one with --build-package"
            )
        if len(manifests) > 1:
            names = ", ".join(p.name for p in manifests)
            raise PackageArchiveError(f"package archive directory '{archive_dir}' contains multiple manifests: {names}")
        return manifests[0]

    def valid(self, manifest) -> bool:
        if not (
            isinstance(manifest, dict)
            and set(manifest) == self._FIELDS
            and manifest.get("schema") == self.SCHEMA
            and self._valid_c_identifier(manifest.get("package"))
            and isinstance(manifest.get("package_root"), str)
            and bool(manifest["package_root"])
            and self._valid_sha256(manifest.get("package_source"))
            and isinstance(manifest.get("target"), str)
            and bool(manifest["target"])
            and self._valid_sha256(manifest.get("target_spec"))
            and isinstance(manifest.get("toolchain"), str)
            and isinstance(manifest.get("header_name"), str)
            and isinstance(manifest.get("impl_name"), str)
            and isinstance(manifest.get("link_plan_name"), str)
            and isinstance(manifest.get("artifacts"), dict)
            and isinstance(manifest.get("macros"), list)
            and all(self._valid_macro(macro) for macro in manifest["macros"])
            and all(
                isinstance(manifest.get(field), list) and all(isinstance(value, str) for value in manifest[field])
                for field in self.LIST_FIELDS
            )
        ):
            return False
        expected_artifacts = {manifest["header_name"], manifest["impl_name"], manifest["link_plan_name"]}
        return set(manifest["artifacts"]) == expected_artifacts and all(
            self._valid_sha256(value) for value in manifest["artifacts"].values()
        )

    def load(self, archive_dir: str, target: str) -> dict:
        """Load and authenticate one precompiled package archive against toolchain, target, and artifact digests."""

        manifest_path = self.discover_manifest_path(archive_dir)
        manifest = self.file_store.read_json(
            str(manifest_path),
            max_bytes=self.MAX_BYTES,
            follow_symlinks=True,
        )
        if not self.valid(manifest):
            raise PackageArchiveError(
                f"package archive in '{archive_dir}' has an invalid or unsupported manifest; "
                "regenerate it with --build-package"
            )
        package_name = manifest["package"]
        if self.publisher.publication_in_progress(archive_dir, package_name):
            raise PackageArchiveError(
                f"package archive '{package_name}' in '{archive_dir}' is being updated; "
                "retry after publication completes"
            )
        current = self.fingerprint.digest("full")
        stamped = manifest["toolchain"]
        if stamped != current:
            raise PackageArchiveError(
                f"package archive '{package_name}' in '{archive_dir}' was built by a different compiler version "
                f"(archive: {stamped or 'unstamped'}, current: {current}); regenerate it with --build-package"
            )
        if manifest["target"] != target:
            raise PackageArchiveError(
                f"prebuilt package archive '{package_name}' was built for {manifest['target']}; "
                f"regenerate it for {target}"
            )
        if manifest["target_spec"] != TARGET_SPEC_FINGERPRINT:
            raise PackageArchiveError(
                f"prebuilt package archive '{package_name}' was built for {target} under another targets.toml; "
                f"regenerate it for {target}"
            )
        for artifact_name, expected_hash in manifest["artifacts"].items():
            artifact_path = os.path.join(archive_dir, artifact_name)
            try:
                actual_hash = self._artifact_hash(artifact_path)
            except OSError as error:
                raise PackageArchiveError(
                    f"package archive '{package_name}' in '{archive_dir}' is incomplete: missing {artifact_name}; "
                    "regenerate it with --build-package"
                ) from error
            if actual_hash is None:
                raise PackageArchiveError(
                    f"package archive '{package_name}' in '{archive_dir}' has an invalid {artifact_name}; "
                    "regenerate it with --build-package"
                )
            if actual_hash != expected_hash:
                raise PackageArchiveError(
                    f"package archive '{package_name}' in '{archive_dir}' has a modified {artifact_name}; "
                    "regenerate it with --build-package"
                )
        source_entries: dict[str, str] = {}
        for source_path in manifest["source_files"]:
            try:
                source_hash = self._artifact_hash(source_path, allow_empty=True)
            except OSError as error:
                raise PackageArchiveError(
                    f"package archive '{package_name}' in '{archive_dir}' is stale: missing source {source_path}; "
                    "regenerate it with --build-package"
                ) from error
            if source_hash is None:
                raise PackageArchiveError(
                    f"package archive '{package_name}' in '{archive_dir}' is stale: unreadable source {source_path}; "
                    "regenerate it with --build-package"
                )
            source_entries[source_path] = source_hash
        if self.source_hash(source_entries) != manifest["package_source"]:
            raise PackageArchiveError(
                f"package archive '{package_name}' in '{archive_dir}' is stale (package sources changed); "
                "regenerate it with --build-package"
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
            and self._valid_c_identifier(macro["name"])
            and (
                macro["params"] is None
                or (
                    isinstance(macro["params"], list)
                    and len(macro["params"]) == len(set(macro["params"]))
                    and all(self._valid_c_identifier(param) for param in macro["params"])
                )
            )
            and isinstance(macro["replacement"], str)
        ):
            return False
        return "\n" not in macro["replacement"] and "\r" not in macro["replacement"]

    @staticmethod
    def _valid_c_identifier(value) -> bool:
        return bool(
            isinstance(value, str)
            and value
            and value.isascii()
            and (value[0] == "_" or value[0].isalpha())
            and all(character == "_" or character.isalnum() for character in value[1:])
        )

    def _artifact_hash(self, path: str, *, allow_empty: bool = False) -> str | None:
        digest = hashlib.sha256()
        artifact_file = self.file_store.open_regular_binary(path, follow_symlinks=True)
        if artifact_file is None:
            return None
        with artifact_file:
            metadata = os.fstat(artifact_file.fileno())
            if (
                (not allow_empty and metadata.st_size <= 0)
                or metadata.st_size < 0
                or metadata.st_size > self.MAX_ARTIFACT_BYTES
            ):
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


class PackageArtifactRepository:
    """Own precompiled user-package archive serialization and publication."""

    available = True

    def __init__(
        self,
        publisher: PackageArchivePublisher | None = None,
        fingerprint: ToolchainFingerprint | None = None,
    ) -> None:
        self.publisher = publisher or PackageArchivePublisher(ArtifactPublisher(ArtifactStorage()))
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.manifest = PackageArchiveManifest(self.publisher, self.fingerprint)

    def publish(
        self,
        out_dir: str,
        package_name: str,
        package_root: str,
        source_entries: dict[str, str],
        header: str,
        implementation: str,
        link_plan_json: str,
        metadata: dict,
        target: str,
    ) -> dict:
        header_name, impl_name, plan_name, manifest_name = PackageArchiveManifest.artifact_names(package_name)
        manifest = {
            **metadata,
            "artifacts": {
                header_name: hashlib.sha256(header.encode("utf-8")).hexdigest(),
                impl_name: hashlib.sha256(implementation.encode("utf-8")).hexdigest(),
                plan_name: hashlib.sha256(link_plan_json.encode("utf-8")).hexdigest(),
            },
            "header_name": header_name,
            "impl_name": impl_name,
            "link_plan_name": plan_name,
            "package": package_name,
            "package_root": os.path.realpath(package_root),
            "package_source": PackageArchiveManifest.source_hash(source_entries),
            "schema": PackageArchiveManifest.SCHEMA,
            "source_files": sorted(source_entries),
            "target": target,
            "target_spec": TARGET_SPEC_FINGERPRINT,
            "toolchain": self.fingerprint.digest("full"),
        }
        if not self.manifest.valid(manifest):
            raise ValueError(f"application supplied invalid package archive metadata for '{package_name}'")
        self.publisher.publish(
            out_dir,
            package_name,
            header_name,
            header,
            impl_name,
            implementation,
            plan_name,
            link_plan_json,
            manifest_name,
            manifest,
        )
        return manifest

    def load(self, archive_dir: str, target: str) -> dict:
        return self.manifest.load(archive_dir, target)
