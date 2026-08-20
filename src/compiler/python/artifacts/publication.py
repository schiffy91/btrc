"""Durable, no-follow storage and transactional artifact publication."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

PathMetadata = tuple[Path, os.stat_result]


class ReparsePointError(ValueError):
    """A path would escape the real directory tree being validated."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"filesystem tree must not contain a link or reparse point: {path}")
        self.path = path


class ArtifactStorage:
    """Own stable, no-follow access to artifact files and directories."""

    def metadata_is_reparse_point(self, metadata: os.stat_result) -> bool:
        """Recognize POSIX symlinks and Windows directory/file reparse points."""

        return stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_reparse_tag", 0),
        )

    def require_real_directory(self, path: Path, subject: str) -> os.stat_result:
        """Return metadata only for a concrete, non-reparse directory."""

        metadata = path.lstat()
        if self.metadata_is_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{subject} must be a real directory: {path}")
        return metadata

    def require_real_regular(self, path: Path, subject: str) -> os.stat_result:
        """Return metadata only for a concrete, non-reparse regular file."""

        metadata = path.lstat()
        if self.metadata_is_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{subject} must be a real regular file: {path}")
        return metadata

    def real_tree_entries(
        self,
        root: Path,
        *,
        exclude: Callable[[Path], bool] | None = None,
    ) -> list[PathMetadata]:
        """Enumerate a stable tree without following any link or reparse entry."""

        root_metadata = self.require_real_directory(root, "filesystem tree root")
        discovered: list[PathMetadata] = [(root, root_metadata)]
        pending = [(root, root_metadata)]
        while pending:
            directory, expected = pending.pop()
            self._validate_directory_identity(directory, expected)
            children: list[PathMetadata] = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    if exclude is not None and exclude(path):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if self.metadata_is_reparse_point(metadata):
                        raise ReparsePointError(path)
                    children.append((path, metadata))
            self._validate_directory_identity(directory, expected)
            discovered.extend(children)
            pending.extend((path, metadata) for path, metadata in children if stat.S_ISDIR(metadata.st_mode))
        return sorted(discovered, key=lambda entry: entry[0].as_posix())

    def lstat_or_none(self, path: Path) -> os.stat_result | None:
        try:
            return path.lstat()
        except FileNotFoundError:
            return None

    def remove(self, path: Path) -> None:
        metadata = self.lstat_or_none(path)
        if metadata is None:
            return
        if self.metadata_is_reparse_point(metadata):
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                path.unlink()
            else:
                os.rmdir(path)
        elif stat.S_ISDIR(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    def fsync_directory(self, directory: Path) -> None:
        expected = self.require_real_directory(directory, "publication directory")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            if os.name == "nt":
                return
            raise
        try:
            opened = os.fstat(descriptor)
            current = self.require_real_directory(directory, "publication directory")
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not os.path.samestat(expected, opened)
                or not os.path.samestat(opened, current)
            ):
                raise ValueError(f"publication directory is not stable: {directory}")
            try:
                os.fsync(descriptor)
            except OSError:
                if os.name != "nt":
                    raise
        finally:
            os.close(descriptor)

    def open_regular(self, path: Path) -> int:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or self.metadata_is_reparse_point(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise ValueError(f"publication artifact is not a stable regular file: {path}")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def fsync_artifact(self, path: Path, is_directory: bool) -> None:
        """Validate an artifact recursively and force its bytes to storage."""

        if not is_directory:
            descriptor = self.open_regular(path)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return
        entries = self.real_tree_entries(path)
        directories = []
        for child, child_metadata in entries:
            if stat.S_ISDIR(child_metadata.st_mode):
                directories.append(child)
            elif stat.S_ISREG(child_metadata.st_mode):
                descriptor = self.open_regular(child)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            else:
                raise ValueError(f"publication artifact contains a special file: {child}")
        for child in reversed(directories):
            self.fsync_directory(child)

    def validate_artifact(self, path: Path, is_directory: bool) -> None:
        metadata = self.lstat_or_none(path)
        if metadata is None:
            raise ValueError(f"publication artifact is missing: {path}")
        expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
        if self.metadata_is_reparse_point(metadata) or not expected:
            kind = "directory" if is_directory else "regular file"
            raise ValueError(f"publication artifact must be a real {kind}: {path}")

    def destination_exists(self, path: Path, is_directory: bool) -> bool:
        """Return whether a destination is a stable prior artifact to preserve.

        A file-destination symlink is only a replaceable directory entry. It is
        never followed or treated as a rollback backup.
        """

        metadata = self.lstat_or_none(path)
        if metadata is None:
            return False
        if self.metadata_is_reparse_point(metadata):
            if stat.S_ISLNK(metadata.st_mode) and not is_directory:
                return False
            raise ValueError(f"invalid publication destination: {path}")
        expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
        if not expected:
            raise ValueError(f"invalid publication destination: {path}")
        if not is_directory:
            descriptor = self.open_regular(path)
            os.close(descriptor)
        return True

    def _validate_directory_identity(self, path: Path, expected: os.stat_result) -> None:
        current = self.require_real_directory(path, "filesystem tree directory")
        if self._identity(current) != self._identity(expected):
            raise ValueError(f"filesystem tree directory changed while being traversed: {path}")

    def _identity(self, metadata: os.stat_result) -> tuple[int, int, int]:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublicationLock:
    """Own one no-follow writer lock from acquisition through release."""

    def __init__(
        self,
        directory: Path,
        name: str,
        process_lock: threading.Lock,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._directory = directory
        self._name = name
        self._process_lock = process_lock
        self._storage = storage or ArtifactStorage()
        self._descriptor = -1
        self._locked = False
        self._process_lock_held = False

    def __enter__(self) -> PublicationLock:
        if not _NAME_PATTERN.fullmatch(self._name):
            raise ValueError(f"invalid publication name: {self._name!r}")
        self._directory.mkdir(parents=True, exist_ok=True)
        self._storage.require_real_directory(
            self._directory,
            "publication output directory",
        )
        path = self._directory / f".{self._name}.publish.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        self._process_lock.acquire()
        self._process_lock_held = True
        try:
            self._descriptor = os.open(path, flags, 0o600)
            opened = os.fstat(self._descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or self._storage.metadata_is_reparse_point(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise ValueError(f"publication lock is not a stable regular file: {path}")
            self._lock_descriptor()
            self._locked = True
            return self
        except BaseException:
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1
            self._release_process_lock()
            raise

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._locked:
                self._unlock_descriptor()
                self._locked = False
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1
        finally:
            self._release_process_lock()

    def _lock_descriptor(self) -> None:
        if os.name == "nt":
            import msvcrt

            if os.fstat(self._descriptor).st_size == 0:
                os.write(self._descriptor, b"\0")
            os.lseek(self._descriptor, 0, os.SEEK_SET)
            msvcrt.locking(self._descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._descriptor, fcntl.LOCK_EX)

    def _unlock_descriptor(self) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(self._descriptor, 0, os.SEEK_SET)
            msvcrt.locking(self._descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._descriptor, fcntl.LOCK_UN)

    def _release_process_lock(self) -> None:
        if self._process_lock_held:
            self._process_lock.release()
            self._process_lock_held = False


_JOURNAL_SCHEMA, _MAX_JOURNAL_BYTES = 1, 64 * 1024


@dataclass(frozen=True)
class PublishedArtifact:
    staged: Path
    destination: Path
    is_directory: bool = False


class StagedPublicationPolicy(ABC):
    """Validate one fixed staged generation while its publication lock is held."""

    @abstractmethod
    def validate(self, staged: tuple[Path, ...]) -> None:
        """Reject a staged generation that is unsafe to publish."""


class ArtifactPublisher:
    """Own transactional publication, rollback, and crash recovery."""

    def __init__(self, storage: ArtifactStorage | None = None) -> None:
        self._storage = storage or ArtifactStorage()
        self._process_lock = threading.Lock()

    def lock(self, directory: Path, name: str) -> PublicationLock:
        return PublicationLock(
            directory,
            name,
            self._process_lock,
            self._storage,
        )

    def publication_in_progress(self, directory: Path, name: str) -> bool:
        return self._storage.lstat_or_none(self._control_path(directory, name, "journal")) is not None

    def publish(
        self,
        name: str,
        artifacts: Sequence[PublishedArtifact],
        *,
        policy: StagedPublicationPolicy | None = None,
    ) -> None:
        """Durably publish payloads in order, with the final validator last."""

        if not artifacts:
            raise ValueError("publication requires at least one artifact")
        directory = artifacts[0].destination.parent
        if any(artifact.destination.parent != directory for artifact in artifacts):
            raise ValueError("all publication destinations must share one directory")
        if len({artifact.destination for artifact in artifacts}) != len(artifacts):
            raise ValueError("publication destinations must be unique")
        if any(artifact.staged == artifact.destination for artifact in artifacts):
            raise ValueError("staged artifacts must not be public destinations")
        with self.lock(directory, name):
            self._recover(directory, name, artifacts)
            fixed_stages = []
            try:
                for index, artifact in enumerate(artifacts):
                    self._storage.validate_artifact(artifact.staged, artifact.is_directory)
                    self._storage.destination_exists(artifact.destination, artifact.is_directory)
                    fixed = self._stage_path(directory, name, index)
                    os.replace(artifact.staged, fixed)
                    fixed_stages.append(fixed)
                    self._storage.fsync_artifact(fixed, artifact.is_directory)
                self._storage.fsync_directory(directory)
                if policy is not None:
                    policy.validate(tuple(fixed_stages))
                previous = [
                    self._storage.destination_exists(
                        artifact.destination,
                        artifact.is_directory,
                    )
                    for artifact in artifacts
                ]
                journal = self._control_path(directory, name, "journal")
                self._write_journal(
                    journal,
                    self._journal_record(artifacts, "publishing", previous),
                )
                for index in [len(artifacts) - 1, *range(len(artifacts) - 1)]:
                    if previous[index]:
                        os.replace(
                            artifacts[index].destination,
                            self._backup_path(directory, name, index),
                        )
                        self._storage.fsync_directory(directory)
                for index, artifact in enumerate(artifacts):
                    os.replace(fixed_stages[index], artifact.destination)
                    self._storage.fsync_directory(directory)
                self._write_journal(
                    journal,
                    self._journal_record(artifacts, "committed", previous),
                )
            except BaseException:
                if self.publication_in_progress(directory, name):
                    self._recover(directory, name, artifacts)
                else:
                    for fixed in fixed_stages:
                        self._storage.remove(fixed)
                    self._storage.fsync_directory(directory)
                raise
            self._recover(directory, name, artifacts)

    def _control_path(self, directory: Path, name: str, suffix: str) -> Path:
        return directory / f".{name}.publish.{suffix}"

    def _stage_path(self, directory: Path, name: str, index: int) -> Path:
        return self._control_path(directory, name, f"new-{index}")

    def _backup_path(self, directory: Path, name: str, index: int) -> Path:
        return self._control_path(directory, name, f"previous-{index}")

    def _journal_record(
        self,
        artifacts: Sequence[PublishedArtifact],
        state: str,
        previous: list[bool],
    ) -> dict:
        return {
            "schema": _JOURNAL_SCHEMA,
            "state": state,
            "previous": previous,
            "artifacts": [
                {
                    "name": artifact.destination.name,
                    "directory": artifact.is_directory,
                }
                for artifact in artifacts
            ],
        }

    def _write_journal(self, path: Path, record: dict) -> None:
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temporary = path.with_name(f"{path.name}.tmp")
        self._storage.remove(temporary)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._storage.fsync_directory(path.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                temporary.unlink()

    def _read_journal(self, path: Path, expected: dict) -> dict | None:
        if self._storage.lstat_or_none(path) is None:
            return None
        descriptor = self._storage.open_regular(path)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                encoded = stream.read(_MAX_JOURNAL_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            record = json.loads(encoded.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ValueError(f"invalid publication recovery journal: {path}") from error
        if (
            len(encoded) > _MAX_JOURNAL_BYTES
            or not isinstance(record, dict)
            or set(record) != {"schema", "state", "previous", "artifacts"}
            or record.get("schema") != _JOURNAL_SCHEMA
            or record.get("state") not in {"publishing", "committed"}
            or record.get("artifacts") != expected["artifacts"]
            or not isinstance(record.get("previous"), list)
            or len(record["previous"]) != len(expected["artifacts"])
            or not all(isinstance(value, bool) for value in record["previous"])
        ):
            raise ValueError(f"invalid publication recovery journal: {path}")
        return record

    def _restore_backup(self, backup: Path, artifact: PublishedArtifact) -> None:
        self._storage.fsync_artifact(backup, artifact.is_directory)
        self._storage.remove(artifact.destination)
        os.replace(backup, artifact.destination)
        try:
            self._storage.fsync_artifact(
                artifact.destination,
                artifact.is_directory,
            )
        except BaseException:
            self._storage.remove(artifact.destination)
            self._storage.fsync_directory(artifact.destination.parent)
            raise
        self._storage.fsync_directory(artifact.destination.parent)

    def _recover(
        self,
        directory: Path,
        name: str,
        artifacts: Sequence[PublishedArtifact],
    ) -> None:
        journal = self._control_path(directory, name, "journal")
        expected = self._journal_record(artifacts, "publishing", [])
        record = self._read_journal(journal, expected)
        if record is None:
            for index in range(len(artifacts)):
                self._storage.remove(self._stage_path(directory, name, index))
                self._storage.remove(self._backup_path(directory, name, index))
            self._storage.remove(journal.with_name(f"{journal.name}.tmp"))
            self._storage.fsync_directory(directory)
            return
        if record["state"] == "publishing":
            validator_index = len(artifacts) - 1
            validator = artifacts[validator_index]
            validator_backup = self._backup_path(
                directory,
                name,
                validator_index,
            )
            if record["previous"][validator_index]:
                if self._storage.lstat_or_none(validator_backup) is not None:
                    self._storage.fsync_artifact(
                        validator_backup,
                        validator.is_directory,
                    )
                    self._storage.remove(validator.destination)
                else:
                    self._storage.fsync_artifact(
                        validator.destination,
                        validator.is_directory,
                    )
            else:
                self._storage.remove(validator.destination)
            for index in range(validator_index):
                artifact = artifacts[index]
                backup = self._backup_path(directory, name, index)
                if record["previous"][index]:
                    if self._storage.lstat_or_none(backup) is not None:
                        self._restore_backup(backup, artifact)
                    else:
                        self._storage.fsync_artifact(
                            artifact.destination,
                            artifact.is_directory,
                        )
                else:
                    self._storage.remove(artifact.destination)
            if self._storage.lstat_or_none(validator_backup) is not None:
                self._restore_backup(validator_backup, validator)
            for index in range(len(artifacts)):
                self._storage.remove(self._stage_path(directory, name, index))
                self._storage.remove(self._backup_path(directory, name, index))
        else:
            for artifact in artifacts:
                self._storage.fsync_artifact(
                    artifact.destination,
                    artifact.is_directory,
                )
            for index in range(len(artifacts)):
                self._storage.remove(self._backup_path(directory, name, index))
                self._storage.remove(self._stage_path(directory, name, index))
        self._storage.fsync_directory(directory)
        journal.unlink()
        self._storage.fsync_directory(directory)
