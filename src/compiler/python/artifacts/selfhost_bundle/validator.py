"""Final semantic validation for staged self-hosted bundle generations."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from ...btrcc_archive_metadata import canonical_epoch
from ...btrcc_bundle_validation_archive import BundleArchiveValidator
from ...btrcc_target_binary import TargetBinaryValidator, TargetCatalog
from ...bundle_archive_source import BundleArchiveSource, ContentSnapshot
from ..publication.storage import ArtifactStorage

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


class BundleValidator:
    """Own exact staged-bundle, archive, and checksum validation."""

    def __init__(
        self,
        storage: ArtifactStorage | None = None,
        target_catalog: TargetCatalog | None = None,
        binary_validator: TargetBinaryValidator | None = None,
    ) -> None:
        self._storage = storage if storage is not None else ArtifactStorage()
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
        archive_validator = BundleArchiveValidator(
            archive_name,
            expected_files,
            expected_dirs,
            expected_modes,
            snapshot.modified_time,
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
        archive_source = BundleArchiveSource(bundle, self._storage)
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
        modified_time = canonical_epoch(entry.modified_time_ns for entry in entries)
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
