"""Build relocatable, reproducible self-hosted compiler distributions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ...btrcc_bundle_archive import write_checksum, write_tar_gz, write_zip
from ...btrcc_target_binary import TargetSpec, target_spec, validate_target_binary
from ..publication.publisher import ArtifactPublisher
from ..publication.storage import ArtifactStorage
from .copier import BundleCopier
from .publisher import SelfhostBundlePublisher
from .validator import BundleValidator

FORMAT_VERSION = 1
MAX_ARCHIVE_EPOCH = 0xFFFFFFFF
RUNTIME_SUFFIXES = frozenset({".btrc", ".c", ".h", ".m", ".md"})
EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "build", ".cache"})
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class BundleResult:
    bundle: Path
    archive: Path
    checksum: Path


class BundleBuilder:
    """Own one reusable self-hosted bundle build and publication service."""

    def __init__(
        self,
        storage: ArtifactStorage | None = None,
        publication: ArtifactPublisher | None = None,
        validator: BundleValidator | None = None,
    ) -> None:
        self._storage = storage or ArtifactStorage()
        self._copier = BundleCopier(self._storage)
        bundle_validator = validator or BundleValidator(self._storage)
        self._publisher = SelfhostBundlePublisher(
            publication or ArtifactPublisher(self._storage),
            bundle_validator,
        )

    def build(
        self,
        *,
        binary: Path,
        target: str,
        output_dir: Path,
        source_root: Path,
        version: str | None = None,
        epoch: int = 0,
    ) -> BundleResult:
        """Create a bundle directory, deterministic archive, and checksum."""

        if not TARGET_PATTERN.fullmatch(target) or ".." in target:
            raise ValueError(f"invalid target name: {target!r}")
        spec = target_spec(target)
        if epoch < 0 or epoch > MAX_ARCHIVE_EPOCH:
            raise ValueError(f"archive epoch must be between 0 and {MAX_ARCHIVE_EPOCH}")
        try:
            self._storage.require_real_regular(binary, "compiler binary")
        except (FileNotFoundError, ValueError):
            raise ValueError(f"compiler binary is not a regular file: {binary}") from None
        self._storage.require_real_directory(source_root, "bundle source root")
        grammar = source_root / "src" / "language" / "grammar.ebnf"
        stdlib = source_root / "src" / "stdlib"
        license_file = source_root / "LICENSE"
        try:
            self._storage.require_real_regular(grammar, "required grammar")
        except (FileNotFoundError, ValueError):
            raise ValueError(
                f"required grammar is missing or not a regular file: {grammar}",
            ) from None
        try:
            self._storage.require_real_directory(stdlib, "required stdlib directory")
        except (FileNotFoundError, ValueError):
            raise ValueError(
                f"required stdlib directory is missing or invalid: {stdlib}",
            ) from None
        try:
            self._storage.require_real_regular(license_file, "required license")
        except (FileNotFoundError, ValueError):
            raise ValueError(
                f"required license is missing or not a regular file: {license_file}",
            ) from None
        runtime_sources = self._source_files(stdlib)
        bundle_name = f"btrcc-{target}"
        output_dir.mkdir(parents=True, exist_ok=True)
        self._storage.require_real_directory(output_dir, "bundle output directory")
        with tempfile.TemporaryDirectory(
            prefix=f".{bundle_name}.",
            dir=output_dir,
        ) as temporary:
            staged = Path(temporary) / bundle_name
            executable_name = Path(spec.executable).name
            self._copier.copy(binary, staged / "bin" / executable_name, 0o755, epoch)
            validate_target_binary(staged / spec.executable, target)
            self._copier.copy(license_file, staged / "LICENSE", 0o644, epoch)
            self._copier.copy(
                grammar,
                staged / "share" / "btrc" / "language" / grammar.name,
                0o644,
                epoch,
            )
            for source in runtime_sources:
                self._copier.copy(
                    source,
                    staged / "share" / "btrc" / "stdlib" / source.relative_to(stdlib),
                    0o644,
                    epoch,
                )
            bundle_version = version or self._project_version(source_root)
            self._write_readme(staged, target, spec, bundle_version, epoch)
            self._write_manifest(staged, target, spec, bundle_version, epoch)
            self._normalize_tree(staged, epoch)
            bundle = output_dir / bundle_name
            archive_name = f"{bundle_name}{spec.archive_suffix}"
            staged_archive = Path(temporary) / archive_name
            if spec.archive_suffix == ".zip":
                write_zip(staged, staged_archive, epoch)
            else:
                write_tar_gz(staged, staged_archive, epoch)
            staged_checksum = write_checksum(staged_archive)
            archive = output_dir / archive_name
            checksum = archive.with_name(f"{archive.name}.sha256")
            self._publisher.publish(
                staged_bundle=staged,
                staged_archive=staged_archive,
                staged_checksum=staged_checksum,
                bundle=bundle,
                archive=archive,
                checksum=checksum,
            )
        return BundleResult(bundle, archive, checksum)

    def _project_version(self, source_root: Path) -> str:
        pyproject = source_root / "pyproject.toml"
        descriptor = -1
        try:
            descriptor = self._storage.open_regular(pyproject)
            stream = os.fdopen(descriptor, "r", encoding="utf-8")
            descriptor = -1
            with stream:
                project = tomllib.loads(stream.read())["project"]
            version = project["version"]
        except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"cannot read project version from {pyproject}: {error}") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not isinstance(version, str) or not version:
            raise ValueError(f"project.version in {pyproject} must be a non-empty string")
        return version

    def _source_files(self, stdlib: Path) -> list[Path]:
        files: list[Path] = []

        def excluded(path: Path) -> bool:
            relative = path.relative_to(stdlib)
            return any(part in EXCLUDED_DIRECTORIES for part in relative.parts)

        for path, metadata in self._storage.real_tree_entries(stdlib, exclude=excluded):
            if path == stdlib or stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"runtime source must be a regular file: {path}")
            if path.suffix not in RUNTIME_SUFFIXES:
                raise ValueError(f"unknown stdlib runtime source type: {path}")
            files.append(path)
        for required in ("vector.btrc", "strings.btrc"):
            if (stdlib / required) not in files:
                raise ValueError(
                    f"required stdlib runtime source is missing: {stdlib / required}",
                )
        return files

    def _hash_entry(self, path: Path, bundle: Path) -> dict[str, object]:
        descriptor = self._storage.open_regular(path)
        try:
            stream = os.fdopen(descriptor, "rb")
            descriptor = -1
            with stream:
                payload = stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return {
            "path": path.relative_to(bundle).as_posix(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def _write_manifest(
        self,
        bundle: Path,
        target: str,
        spec: TargetSpec,
        version: str,
        epoch: int,
    ) -> None:
        payload_files = [
            path
            for path, metadata in self._storage.real_tree_entries(bundle)
            if stat.S_ISREG(metadata.st_mode) and path.name != "manifest.json"
        ]
        manifest = {
            "format_version": FORMAT_VERSION,
            "version": version,
            "target": target,
            "executable": spec.executable,
            "data_root": "share/btrc",
            "files": [self._hash_entry(path, bundle) for path in payload_files],
        }
        destination = bundle / "share" / "btrc" / "manifest.json"
        destination.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        destination.chmod(0o644)
        os.utime(destination, (epoch, epoch), follow_symlinks=False)

    def _write_readme(
        self,
        bundle: Path,
        target: str,
        spec: TargetSpec,
        version: str,
        epoch: int,
    ) -> None:
        executable = spec.executable.replace("/", "\\") if spec.archive_suffix == ".zip" else spec.executable
        text = f"""btrcc {version} ({target})

This is a relocatable self-hosted btrc compiler bundle. Keep bin/ and
share/btrc/ together. The compiler discovers share/btrc from its real
executable path, so it can be launched through an absolute PATH entry or a
symlink and from any working directory.

Run `{executable} --stdlib-dir` to inspect the active standard-library path.
Set BTRC_HOME to an alternate data root containing language/grammar.ebnf and
stdlib/. An invalid BTRC_HOME is an error and never falls back silently.

Generated C that imports a native module must be compiled with the bundle's
headers. Add the printed stdlib directory and the imported module directory to
the C include path, for example `-I <stdlib-dir> -I <stdlib-dir>/gui`. Link the
matching runtime source/library and any platform dependencies documented by
that module (gpu/, gui/, or tray/).

This bundle is distributed under the MIT License; see LICENSE.

The adjacent archive .sha256 file verifies the downloaded archive. The
share/btrc/manifest.json file records the bundle format, version, target, and
SHA-256 digest of every bundled payload file.
"""
        destination = bundle / "README.md"
        destination.write_text(text, encoding="utf-8", newline="\n")
        destination.chmod(0o644)
        os.utime(destination, (epoch, epoch), follow_symlinks=False)

    def _normalize_tree(self, bundle: Path, epoch: int) -> None:
        for directory in sorted(
            (
                path
                for path, metadata in self._storage.real_tree_entries(bundle)
                if path != bundle and stat.S_ISDIR(metadata.st_mode)
            ),
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            directory.chmod(0o755)
            os.utime(directory, (epoch, epoch), follow_symlinks=False)
        bundle.chmod(0o755)
        os.utime(bundle, (epoch, epoch), follow_symlinks=False)
