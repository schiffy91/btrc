"""Build, validate, and atomically publish self-hosted compiler bundles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .archive import (
    ArchiveCodec,
    ArchiveSource,
    ArchiveValidator,
    ContentSnapshot,
    TargetBinaryValidator,
    TargetCatalog,
    TargetSpec,
)
from .publication import (
    ArtifactPublisher,
    ArtifactStorage,
    PublicationLock,
    PublishedArtifact,
    StagedPublicationPolicy,
)

_CHUNK_SIZE = 1024 * 1024


class SelfhostBundleCopier:
    """Copy one stable source while proving its content and identity."""

    def __init__(self, storage: ArtifactStorage | None = None) -> None:
        self._storage = storage or ArtifactStorage()

    def copy(self, source: Path, destination: Path, mode: int, epoch: int) -> None:
        """Copy one stable source, tolerating content-neutral metadata churn."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        created = False
        try:
            identity = self._validate_identity(source, descriptor)
            with os.fdopen(descriptor, "rb") as source_stream:
                descriptor = -1
                before = self._hash_stream(source_stream)
                source_stream.seek(0)
                copied_digest = hashlib.sha256()
                copied_size = 0
                with destination.open("xb") as destination_stream:
                    created = True
                    while chunk := source_stream.read(_CHUNK_SIZE):
                        destination_stream.write(chunk)
                        copied_digest.update(chunk)
                        copied_size += len(chunk)
                destination_hash = self._hash_regular_path(destination)
                source_stream.seek(0)
                after = self._hash_stream(source_stream)
                self._validate_identity(source, source_stream.fileno(), identity)
            copied = copied_digest.digest(), copied_size
            if before != copied or copied != after or after != destination_hash:
                raise ValueError(f"bundle source changed while being copied: {source}")
            destination.chmod(mode)
            os.utime(destination, (epoch, epoch), follow_symlinks=False)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _validate_identity(
        self,
        path: Path,
        descriptor: int,
        expected: tuple[int, int, int] | None = None,
    ) -> tuple[int, int, int]:
        opened = os.fstat(descriptor)
        current = path.lstat()
        opened_identity = self._identity(opened)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or self._storage.metadata_is_reparse_point(current)
            or opened_identity != self._identity(current)
            or (expected is not None and opened_identity != expected)
        ):
            raise ValueError(f"bundle source changed identity while being copied: {path}")
        return opened_identity

    def _hash_regular_path(self, path: Path) -> tuple[bytes, int]:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            identity = self._validate_identity(path, descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                digest = self._hash_stream(stream)
                self._validate_identity(path, stream.fileno(), identity)
                return digest
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _hash_stream(self, stream: BinaryIO) -> tuple[bytes, int]:
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
        return digest.digest(), size

    def _identity(self, metadata: os.stat_result) -> tuple[int, int, int]:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


_MANIFEST_PATH = "share/btrc/manifest.json"
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_PAYLOAD_BYTES = 1024 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class _BundleSnapshot:
    manifest: bytes
    files: dict[str, ContentSnapshot]
    directories: frozenset[str]
    executable: str
    modified_time: int
    entries: tuple[tuple[str, int, int, int, int, bool], ...]


class SelfhostBundleValidator:
    """Own exact staged-bundle, archive, and checksum validation."""

    def __init__(
        self,
        storage: ArtifactStorage | None = None,
        target_catalog: TargetCatalog | None = None,
        binary_validator: TargetBinaryValidator | None = None,
        archive_codec: ArchiveCodec | None = None,
    ) -> None:
        self._storage = storage if storage is not None else ArtifactStorage()
        self._archive_codec = archive_codec or ArchiveCodec(self._storage)
        self._target_catalog = target_catalog if target_catalog is not None else TargetCatalog()
        self._binary_validator = (
            binary_validator
            if binary_validator is not None
            else TargetBinaryValidator(
                self._target_catalog,
                self._storage,
            )
        )

    def validate_generation(
        self,
        bundle: Path,
        archive: Path,
        checksum: Path,
        bundle_name: str,
        archive_name: str,
    ) -> None:
        """Validate the exact staged generation immediately before publication."""

        snapshot = self._capture_bundle(bundle, bundle_name, archive_name)
        expected_files, expected_dirs, expected_modes = self._expected_archive(
            snapshot,
            bundle_name,
        )
        checksum_before = self._checksum_text(checksum)
        digest_before = self._hash_artifact(archive)
        if checksum_before != f"{digest_before}  {archive_name}\n":
            raise ValueError(
                "bundle archive checksum does not match the staged archive",
            )
        archive_validator = ArchiveValidator(
            archive_name,
            expected_files,
            expected_dirs,
            expected_modes,
            snapshot.modified_time,
            self._archive_codec,
        )
        with self._stable_file(archive, _MAX_ARCHIVE_BYTES) as stream:
            archive_validator.validate(stream)
        if self._hash_artifact(archive) != digest_before or self._checksum_text(checksum) != checksum_before:
            raise ValueError("bundle archive changed while being validated")
        try:
            final_snapshot = self._capture_bundle(
                bundle,
                bundle_name,
                archive_name,
            )
        except ValueError as error:
            raise ValueError(
                "bundle changed while its archive was being validated",
            ) from error
        if final_snapshot != snapshot:
            raise ValueError("bundle changed while its archive was being validated")

    @contextmanager
    def _stable_file(self, path: Path, max_bytes: int) -> BinaryIO:
        descriptor = self._storage.open_regular(path)
        try:
            opened = os.fstat(descriptor)
            if opened.st_size <= 0 or opened.st_size > max_bytes:
                raise ValueError(f"bundle artifact has an invalid size: {path}")
            expected = self._identity(opened)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                yield stream
                if self._identity(os.fstat(stream.fileno())) != expected or self._identity(path.lstat()) != expected:
                    raise ValueError(
                        f"bundle artifact changed while being validated: {path}",
                    )
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _manifest_records(
        self,
        encoded: bytes,
        bundle_name: str,
        archive_name: str,
    ) -> tuple[dict[str, ContentSnapshot], str, str]:
        try:
            manifest = json.loads(
                encoded.decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (UnicodeError, ValueError, TypeError, RecursionError) as error:
            raise ValueError("bundle manifest is not valid strict JSON") from error
        fields = {
            "format_version",
            "version",
            "target",
            "executable",
            "data_root",
            "files",
        }
        if (
            not isinstance(manifest, dict)
            or set(manifest) != fields
            or manifest.get("format_version") != 1
            or not all(isinstance(manifest.get(field), str) for field in fields - {"format_version", "files"})
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("bundle manifest has an invalid schema")
        target = manifest["target"]
        try:
            spec = self._target_catalog.spec(target)
        except ValueError as error:
            raise ValueError(
                "bundle manifest does not match its target artifacts",
            ) from error
        expected_archive = f"{bundle_name}{spec.archive_suffix}"
        executable = spec.executable
        if (
            not manifest["version"]
            or bundle_name != f"btrcc-{target}"
            or archive_name != expected_archive
            or manifest["executable"] != executable
            or manifest["data_root"] != "share/btrc"
        ):
            raise ValueError("bundle manifest does not match its target artifacts")
        records = {}
        total_size = 0
        for record in manifest["files"]:
            if not isinstance(record, dict) or set(record) != {
                "path",
                "sha256",
                "size",
            }:
                raise ValueError("bundle manifest has an invalid file record")
            path, digest, size = record["path"], record["sha256"], record["size"]
            if (
                not isinstance(path, str)
                or not self._safe_relative(path)
                or path in records
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or type(size) is not int
                or size < 0
            ):
                raise ValueError("bundle manifest has an invalid file record")
            total_size += size
            if total_size > _MAX_PAYLOAD_BYTES:
                raise ValueError(
                    "bundle manifest payload exceeds the validation limit",
                )
            records[path] = bytes.fromhex(digest), size
        if list(records) != sorted(records) or executable not in records:
            raise ValueError("bundle manifest file records are not canonical")
        return records, executable, target

    def _capture_bundle(
        self,
        bundle: Path,
        bundle_name: str,
        archive_name: str,
    ) -> _BundleSnapshot:
        encoded = self._read_manifest(bundle)
        records, executable, target = self._manifest_records(
            encoded,
            bundle_name,
            archive_name,
        )
        expected_files = set(records) | {_MANIFEST_PATH}
        directories = self._expected_directories(expected_files)
        sizes = {path: content[1] for path, content in records.items()}
        sizes[_MANIFEST_PATH] = len(encoded)
        archive_source = ArchiveSource(bundle, self._storage)
        entries = archive_source.discover_bounded(sizes, directories)
        actual_files = {entry.path.relative_to(bundle).as_posix(): entry for entry in entries if not entry.is_directory}
        expected_content = dict(records)
        expected_content[_MANIFEST_PATH] = (
            hashlib.sha256(encoded).digest(),
            len(encoded),
        )
        for path, expected in expected_content.items():
            actual = actual_files.get(path)
            if actual is None or actual.content != expected:
                raise ValueError(f"bundle file does not match its manifest: {path}")
        with archive_source.open_regular(actual_files[executable]) as stream:
            self._binary_validator.validate_stream(stream, target)
        state = []
        modified_time = self._archive_codec.canonical_epoch(entry.modified_time_ns for entry in entries)
        for entry in entries:
            relative = entry.path.relative_to(bundle).as_posix()
            expected_mode = self._expected_staged_mode(
                is_directory=entry.is_directory,
                is_executable=relative == executable,
                host_os_name=os.name,
            )
            if stat.S_IMODE(entry.mode) != expected_mode:
                raise ValueError(
                    f"bundle artifact has a noncanonical mode: {relative}",
                )
            state.append(
                (
                    relative,
                    entry.device,
                    entry.inode,
                    entry.mode,
                    entry.modified_time_ns,
                    entry.is_directory,
                ),
            )
        archive_source.validate_snapshot(
            entries,
            files=sizes,
            directories=directories,
        )
        return _BundleSnapshot(
            encoded,
            records,
            directories,
            executable,
            modified_time,
            tuple(state),
        )

    def _expected_archive(
        self,
        snapshot: _BundleSnapshot,
        bundle_name: str,
    ) -> tuple[dict[str, ContentSnapshot], set[str], dict[str, int]]:
        files = {f"{bundle_name}/{path}": content for path, content in snapshot.files.items()}
        files[f"{bundle_name}/{_MANIFEST_PATH}"] = (
            hashlib.sha256(snapshot.manifest).digest(),
            len(snapshot.manifest),
        )
        directories = {
            f"{bundle_name}/",
            *(f"{bundle_name}/{path}/" for path in snapshot.directories),
        }
        modes = {directory: 0o755 for directory in directories}
        for member in files:
            relative = member.removeprefix(f"{bundle_name}/")
            modes[member] = 0o755 if relative == snapshot.executable else 0o644
        return files, directories, modes

    def _hash_artifact(self, path: Path) -> str:
        with self._stable_file(path, _MAX_ARCHIVE_BYTES) as stream:
            size = os.fstat(stream.fileno()).st_size
            digest = hashlib.sha256()
            remaining = size
            while remaining:
                chunk = stream.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError(
                        "bundle artifact changed size while being validated",
                    )
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1) or os.fstat(stream.fileno()).st_size != size:
                raise ValueError(
                    "bundle artifact changed size while being validated",
                )
        return digest.hexdigest()

    def _checksum_text(self, path: Path) -> str:
        with self._stable_file(path, 4096) as stream:
            try:
                return stream.read(4097).decode("ascii")
            except UnicodeError as error:
                raise ValueError("bundle checksum is not ASCII") from error

    def _read_manifest(self, bundle: Path) -> bytes:
        with self._stable_file(
            bundle / _MANIFEST_PATH,
            _MAX_MANIFEST_BYTES,
        ) as stream:
            return self._read_exact(stream, os.fstat(stream.fileno()).st_size)

    def _read_exact(self, stream: BinaryIO, size: int) -> bytes:
        payload = stream.read(size + 1)
        if len(payload) != size or stream.read(1):
            raise ValueError("bundle artifact changed size while being validated")
        return payload

    def _expected_directories(self, files: set[str]) -> frozenset[str]:
        directories = set()
        for path in files:
            parent = PurePosixPath(path).parent
            while parent.as_posix() != ".":
                directories.add(parent.as_posix())
                parent = parent.parent
        return frozenset(directories)

    def _expected_staged_mode(
        self,
        *,
        is_directory: bool,
        is_executable: bool,
        host_os_name: str,
    ) -> int:
        """Return the mode exposed by the host for a canonical staged entry."""

        if host_os_name == "nt":
            return 0o777 if is_directory else 0o666
        return 0o755 if is_directory or is_executable else 0o644

    def _safe_relative(self, path: str) -> bool:
        parsed = PurePosixPath(path)
        return (
            bool(path)
            and "\\" not in path
            and not parsed.is_absolute()
            and path == parsed.as_posix()
            and all(part not in {"", ".", ".."} for part in parsed.parts)
        )

    def _reject_json_constant(self, value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    def _identity(self, metadata: os.stat_result) -> tuple[int, int, int]:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


@dataclass(frozen=True)
class SelfhostBundlePublicationPolicy(StagedPublicationPolicy):
    """Validate one named self-host generation under its publication lock."""

    validator: SelfhostBundleValidator
    bundle_name: str
    archive_name: str

    def validate(self, staged: tuple[Path, ...]) -> None:
        self.validator.validate_generation(
            staged[0],
            staged[1],
            staged[2],
            self.bundle_name,
            self.archive_name,
        )


class SelfhostBundlePublisher:
    """Own validation and transactional publication of a bundle generation."""

    def __init__(
        self,
        publication: ArtifactPublisher,
        validator: SelfhostBundleValidator,
    ) -> None:
        self._publication = publication
        self._validator = validator

    def lock(self, output_dir: Path, bundle_name: str) -> PublicationLock:
        """Return the bundle writer lock for diagnostics and lock tests."""

        return self._publication.lock(output_dir, bundle_name)

    def publish(
        self,
        *,
        staged_bundle: Path,
        staged_archive: Path,
        staged_checksum: Path,
        bundle: Path,
        archive: Path,
        checksum: Path,
    ) -> None:
        """Publish the directory and archive before their checksum validator."""

        self._publication.publish(
            bundle.name,
            (
                PublishedArtifact(staged_bundle, bundle, is_directory=True),
                PublishedArtifact(staged_archive, archive),
                PublishedArtifact(staged_checksum, checksum),
            ),
            policy=SelfhostBundlePublicationPolicy(
                self._validator,
                bundle.name,
                archive.name,
            ),
        )


FORMAT_VERSION = 1
MAX_ARCHIVE_EPOCH = 0xFFFFFFFF
RUNTIME_SUFFIXES = frozenset({".btrc", ".c", ".h", ".m", ".md"})
EXCLUDED_DIRECTORIES = frozenset({"__pycache__", "build", ".cache"})
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class SelfhostBundleResult:
    bundle: Path
    archive: Path
    checksum: Path


class SelfhostBundleBuilder:
    """Own one reusable self-hosted bundle build and publication service."""

    def __init__(
        self,
        storage: ArtifactStorage | None = None,
        publication: ArtifactPublisher | None = None,
        validator: SelfhostBundleValidator | None = None,
        target_catalog: TargetCatalog | None = None,
        binary_validator: TargetBinaryValidator | None = None,
        archive_codec: ArchiveCodec | None = None,
    ) -> None:
        self._storage = storage if storage is not None else ArtifactStorage()
        self._archive_codec = archive_codec or ArchiveCodec(self._storage)
        self._target_catalog = target_catalog if target_catalog is not None else TargetCatalog()
        self._binary_validator = (
            binary_validator
            if binary_validator is not None
            else TargetBinaryValidator(
                self._target_catalog,
                self._storage,
            )
        )
        self._copier = SelfhostBundleCopier(self._storage)
        bundle_validator = (
            validator
            if validator is not None
            else SelfhostBundleValidator(
                self._storage,
                self._target_catalog,
                self._binary_validator,
                self._archive_codec,
            )
        )
        self._publisher = SelfhostBundlePublisher(
            publication if publication is not None else ArtifactPublisher(self._storage),
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
    ) -> SelfhostBundleResult:
        """Create a bundle directory, deterministic archive, and checksum."""

        if not TARGET_PATTERN.fullmatch(target) or ".." in target:
            raise ValueError(f"invalid target name: {target!r}")
        spec = self._target_catalog.spec(target)
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
            self._binary_validator.validate_path(
                staged / spec.executable,
                target,
            )
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
                self._archive_codec.write_zip(staged, staged_archive, epoch)
            else:
                self._archive_codec.write_tar_gz(staged, staged_archive, epoch)
            staged_checksum = self._archive_codec.write_checksum(staged_archive)
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
        return SelfhostBundleResult(bundle, archive, checksum)

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
