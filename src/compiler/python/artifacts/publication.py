"""Durable, no-follow storage and transactional artifact publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager, suppress
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

    def normalize_timestamp(self, path: Path, epoch: int) -> None:
        """Set one artifact timestamp without following a final reparse point."""

        expected = path.lstat()
        if self.metadata_is_reparse_point(expected) or not (
            stat.S_ISREG(expected.st_mode) or stat.S_ISDIR(expected.st_mode)
        ):
            raise ValueError(f"artifact timestamp target must be a real file or directory: {path}")
        if os.name == "nt":
            self._set_windows_timestamp(path, epoch, expected)
        else:
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        self._validate_timestamp_identity(path, expected)

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
                    # Windows DirEntry metadata comes from WIN32_FIND_DATA and
                    # does not carry the stable volume/file identity returned
                    # by lstat(). Capture every entry through the same no-follow
                    # path API used by the pre-descent identity checks.
                    metadata = path.lstat()
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
        return self._open_regular(path, os.O_RDONLY)

    def open_regular_for_sync(self, path: Path) -> int:
        """Open a stable file with the write access required by Windows fsync."""

        access = os.O_WRONLY if os.name == "nt" else os.O_RDONLY
        return self._open_regular(path, access)

    def _open_regular(self, path: Path, access: int) -> int:
        flags = access | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        # Validate the opened identity without blocking if a FIFO was put at a
        # record/candidate path. O_NONBLOCK does not change regular-file I/O.
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
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
            self._fsync_regular_artifact(path)
            return
        entries = self.real_tree_entries(path)
        directories = []
        for child, child_metadata in entries:
            if stat.S_ISDIR(child_metadata.st_mode):
                directories.append(child)
            elif stat.S_ISREG(child_metadata.st_mode):
                self._fsync_regular_artifact(child)
            else:
                raise ValueError(f"publication artifact contains a special file: {child}")
        for child in reversed(directories):
            self.fsync_directory(child)

    def _fsync_regular_artifact(self, path: Path) -> None:
        descriptor = self.open_regular_for_sync(path)
        try:
            try:
                os.fsync(descriptor)
            except OSError as error:
                raise OSError(error.errno, f"cannot flush publication artifact: {path}") from error
        finally:
            os.close(descriptor)

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

    def _set_windows_timestamp(self, path: Path, epoch: int, expected: os.stat_result) -> None:
        """Set access and write times through a no-follow Win32 handle."""

        import ctypes
        from ctypes import wintypes

        file_write_attributes = 0x0100
        file_share_read_write = 0x00000003
        open_existing = 3
        file_flag_open_reparse_point = 0x00200000
        file_flag_backup_semantics = 0x02000000
        epoch_delta_seconds = 11_644_473_600
        ticks_per_second = 10_000_000

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        set_file_time = kernel32.SetFileTime
        set_file_time.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        set_file_time.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        flags = file_flag_open_reparse_point | file_flag_backup_semantics
        handle = create_file(
            str(path),
            file_write_attributes,
            file_share_read_write,
            None,
            open_existing,
            flags,
            None,
        )
        if handle == wintypes.HANDLE(-1).value:
            error = ctypes.WinError(ctypes.get_last_error())
            error.filename = str(path)
            raise error
        ticks = (epoch + epoch_delta_seconds) * ticks_per_second
        timestamp = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
        try:
            # Denying delete sharing keeps this final name bound to the open
            # handle between the identity check and the timestamp mutation.
            self._validate_timestamp_identity(path, expected)
            if not set_file_time(handle, None, ctypes.byref(timestamp), ctypes.byref(timestamp)):
                error = ctypes.WinError(ctypes.get_last_error())
                error.filename = str(path)
                raise error
        finally:
            close_handle(handle)

    def _validate_timestamp_identity(self, path: Path, expected: os.stat_result) -> None:
        current = path.lstat()
        if self.metadata_is_reparse_point(current) or self._identity(current) != self._identity(expected):
            raise ValueError(f"artifact timestamp target changed identity: {path}")

    def _identity(self, metadata: os.stat_result) -> tuple[int, int, int]:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublicationLock:
    """Own a no-follow writer lock; ``name=None`` locks all publications in a directory."""

    def __init__(
        self,
        directory: Path,
        name: str | None,
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
        if self._name is not None and not _NAME_PATTERN.fullmatch(self._name):
            raise ValueError(f"invalid publication name: {self._name!r}")
        self._directory.mkdir(parents=True, exist_ok=True)
        self._storage.require_real_directory(
            self._directory,
            "publication output directory",
        )
        path = self._directory / (
            f".{self._name}.publish.lock" if self._name is not None else ".btrc-publications.lock"
        )
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
class PublicationTarget:
    """Caller-authorized committed state, independent of candidate files."""

    destination: Path
    is_directory: bool = False
    is_absent: bool = False


@dataclass(frozen=True)
class PublishedArtifact:
    # None retires an unchanged regular file from a caller-owned generation.
    staged: Path | None
    destination: Path
    is_directory: bool = False
    expected_digest: str | None = None

    @property
    def target(self) -> PublicationTarget:
        return PublicationTarget(self.destination, self.is_directory, self.staged is None)

    @property
    def is_absent(self) -> bool:
        return self.staged is None


class StagedPublicationPolicy(ABC):
    """Validate one fixed staged generation while its publication lock is held."""

    @abstractmethod
    def validate(self, staged: tuple[Path, ...]) -> None:
        """Validate replacement payloads in write order; retirements have no stage."""


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

    @contextmanager
    def read_directories(self, directories: Sequence[Path]) -> Iterator[None]:
        """Keep caller-selected inputs stable against cooperating publishers.

        Hold the same sorted directory locks as publication through every read,
        including reads in child compilers. A journal only requires rejection;
        readers do not infer recovery authority from its contents. Never recover
        a generation owner while holding these locks (owners lock first).
        """
        parents = sorted({directory.resolve(strict=True) for directory in directories})
        if not parents:
            raise ValueError("publication reader requires input directories")
        for parent in parents:
            self._storage.require_real_directory(parent, "publication input directory")
        with ExitStack() as locks:
            for parent in parents:
                locks.enter_context(PublicationLock(parent, None, threading.Lock(), self._storage))
            for parent in parents:
                # scandir propagates listing errors; unavailable evidence must
                # not be mistaken for a directory with no pending publication.
                with os.scandir(parent) as entries:
                    for entry in entries:
                        if entry.name.startswith(".") and entry.name.endswith(".publish.journal"):
                            raise ValueError(f"publication requires recovery before reading: {parent / entry.name}")
            yield

    def recover(self, name: str, inventory: Sequence[PublicationTarget]) -> None:
        """Recover a caller-authorized attempt without beginning another one.

        Persistent generation owners must finish this before replacing their
        prepared inventory. Otherwise a third requested layout could strand the
        only authority for an earlier interrupted attempt.
        """
        if not _NAME_PATTERN.fullmatch(name):
            raise ValueError(f"invalid publication name: {name!r}")
        targets = tuple(
            PublicationTarget(
                target.destination.parent.resolve() / target.destination.name, target.is_directory, target.is_absent
            )
            for target in inventory
        )
        self._validate_inventory(targets)
        directory = targets[0].destination.parent
        directories = sorted({target.destination.parent for target in targets})
        self._validate_control_paths(directory, name, (), targets)
        for parent in directories:
            self._storage.require_real_directory(parent, "publication output directory")
        with ExitStack() as locks:
            for parent in directories:
                locks.enter_context(PublicationLock(parent, None, threading.Lock(), self._storage))
            locks.enter_context(self.lock(directory, name))
            journals = set(self._journal_paths(directory, name, targets))
            for parent in directories:
                for pending in parent.glob(".*.publish.journal"):
                    if pending not in journals:
                        raise ValueError(f"another publication requires recovery: {pending}")
            self._recover(directory, name, targets)

    def publish(
        self,
        name: str,
        artifacts: Sequence[PublishedArtifact],
        *,
        policy: StagedPublicationPolicy | None = None,
        previous_inventory: Sequence[PublicationTarget] | None = None,
    ) -> None:
        """Durably publish payloads in order, with the final validator last.

        Candidates must be on their destination filesystem. Directory locks
        serialize overlapping writers; participant journals protect recovery
        when payloads span directories. A changed layout supplies the independently
        authorized inventory of the interrupted attempt; journal paths never
        enlarge that authority. Both layouts stay locked through recovery and
        publication. Retirement hashes must come from the caller's owned prior
        generation; changed files cause a conflict rather than silent deletion.
        """

        if not artifacts:
            raise ValueError("publication requires at least one artifact")
        if not _NAME_PATTERN.fullmatch(name):
            raise ValueError(f"invalid publication name: {name!r}")
        for artifact in artifacts:
            if artifact.is_absent:
                if (
                    artifact.is_directory
                    or not isinstance(artifact.expected_digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", artifact.expected_digest)
                ):
                    raise ValueError("retirement requires a regular file and its prior SHA-256 digest")
            elif artifact.expected_digest is not None:
                raise ValueError("replacement artifacts must not specify a retirement digest")
            artifact.destination.parent.mkdir(parents=True, exist_ok=True)
            self._storage.require_real_directory(artifact.destination.parent, "publication output directory")
        artifacts = tuple(
            PublishedArtifact(
                artifact.staged.parent.resolve() / artifact.staged.name if artifact.staged is not None else None,
                artifact.destination.parent.resolve() / artifact.destination.name,
                artifact.is_directory,
                artifact.expected_digest,
            )
            for artifact in artifacts
        )
        targets = tuple(artifact.target for artifact in artifacts)
        prior = (
            targets
            if previous_inventory is None
            else tuple(
                PublicationTarget(
                    target.destination.parent.resolve() / target.destination.name, target.is_directory, target.is_absent
                )
                for target in previous_inventory
            )
        )
        for inventory in (targets, prior):
            self._validate_inventory(inventory)
        if prior[0].destination != targets[0].destination:
            raise ValueError("recovery inventory must retain the publication anchor")
        directory = targets[0].destination.parent
        directories = sorted({target.destination.parent for target in (*targets, *prior)})
        for parent in directories:
            self._storage.require_real_directory(parent, "publication output directory")
        destinations = {target.destination for target in (*targets, *prior)}
        if any(artifact.staged in destinations for artifact in artifacts):
            raise ValueError("staged artifacts must not be public destinations")
        self._validate_control_paths(directory, name, artifacts, prior)
        with ExitStack() as locks:
            # Hold the union: releasing old-layout locks between recovery and
            # publication would admit a competing writer in that gap.
            for parent in directories:
                locks.enter_context(PublicationLock(parent, None, threading.Lock(), self._storage))
            locks.enter_context(self.lock(directory, name))
            journals = self._journal_paths(directory, name, targets)
            owned_journals = set(journals) | set(self._journal_paths(directory, name, prior))
            for parent in directories:
                for pending in parent.glob(".*.publish.journal"):
                    if pending not in owned_journals:
                        raise ValueError(f"another publication requires recovery: {pending}")
            if prior == targets:
                self._recover(directory, name, targets)
            else:
                recovering = self._recovery_inventory(directory, name, prior, targets)
                self._recover(directory, name, recovering)
                self._recover(directory, name, targets if recovering == prior else prior)
            fixed_stages = []
            try:
                for index, artifact in enumerate(artifacts):
                    if artifact.is_absent:
                        fixed_stages.append(None)
                        continue
                    self._storage.validate_artifact(artifact.staged, artifact.is_directory)
                    self._storage.destination_exists(artifact.destination, artifact.is_directory)
                    fixed = self._stage_path(directory, name, index, artifact)
                    os.replace(artifact.staged, fixed)
                    fixed_stages.append(fixed)
                    self._storage.fsync_artifact(fixed, artifact.is_directory)
                for parent in directories:
                    self._storage.fsync_directory(parent)
                if policy is not None:
                    policy.validate(tuple(path for path in fixed_stages if path is not None))
                for artifact in artifacts:
                    if artifact.is_absent:
                        self._validate_retirement(artifact)
                previous = [
                    self._storage.destination_exists(
                        artifact.destination,
                        artifact.is_directory,
                    )
                    for artifact in artifacts
                ]
                journal = self._control_path(directory, name, "journal")
                # Participant markers precede the coordinator journal. No
                # destination is changed until all of them are durable.
                for participant in journals[1:]:
                    self._write_journal(participant, self._journal_record(artifacts, "publishing", previous))
                self._write_journal(
                    journal,
                    self._journal_record(artifacts, "publishing", previous),
                )
                for index in [len(artifacts) - 1, *range(len(artifacts) - 1)]:
                    if previous[index]:
                        os.replace(
                            artifacts[index].destination,
                            self._backup_path(directory, name, index, artifacts[index]),
                        )
                        self._storage.fsync_directory(artifacts[index].destination.parent)
                for index, artifact in enumerate(artifacts):
                    if fixed_stages[index] is not None:
                        os.replace(fixed_stages[index], artifact.destination)
                    self._storage.fsync_directory(artifact.destination.parent)
                self._write_journal(
                    journal,
                    self._journal_record(artifacts, "committed", previous),
                )
            except BaseException:
                if any(self._storage.lstat_or_none(path) is not None for path in journals):
                    self._recover(directory, name, targets)
                else:
                    for fixed in fixed_stages:
                        if fixed is not None:
                            self._storage.remove(fixed)
                    for parent in directories:
                        self._storage.fsync_directory(parent)
                raise
            self._recover(directory, name, targets)

    def _validate_inventory(self, targets: Sequence[PublicationTarget]) -> None:
        if not targets:
            raise ValueError("publication inventory must not be empty")
        if any(type(target.is_directory) is not bool or type(target.is_absent) is not bool for target in targets):
            raise ValueError("publication inventory kinds must be booleans")
        if targets[0].is_absent or targets[-1].is_absent:
            raise ValueError("publication anchor and final validator must be replacements")
        if any(target.is_directory and target.is_absent for target in targets):
            raise ValueError("retirement requires a regular file")
        if len({target.destination for target in targets}) != len(targets):
            raise ValueError("publication destinations must be unique")

    def _recovery_inventory(
        self,
        directory: Path,
        name: str,
        prior: tuple[PublicationTarget, ...],
        current: tuple[PublicationTarget, ...],
    ) -> tuple[PublicationTarget, ...]:
        """Select only among the two caller-authorized layouts, before mutation."""
        prior_journals = set(self._journal_paths(directory, name, prior))
        current_journals = set(self._journal_paths(directory, name, current))
        present = {path for path in prior_journals | current_journals if self._storage.lstat_or_none(path) is not None}
        invalid = None
        for inventory, journals in ((prior, prior_journals), (current, current_journals)):
            if not present <= journals:
                continue
            expected = self._journal_record(inventory, "publishing", [])
            try:
                for path in sorted(present):
                    self._read_journal(path, expected)
            except ValueError as error:
                invalid = error
            else:
                return inventory
        raise ValueError(f"invalid publication recovery journal: conflicting inventories for {name}") from invalid

    def _validate_retirement(self, artifact: PublishedArtifact) -> None:
        if self._storage.lstat_or_none(artifact.destination) is None:
            return
        descriptor = self._storage.open_regular(artifact.destination)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if digest != artifact.expected_digest:
            raise ValueError(f"retired artifact was modified: {artifact.destination}")

    def _control_path(self, directory: Path, name: str, suffix: str) -> Path:
        return directory / f".{name}.publish.{suffix}"

    def _validate_control_paths(
        self, directory: Path, name: str, artifacts: Sequence[PublishedArtifact], prior: Sequence[PublicationTarget]
    ) -> None:
        current = tuple(artifact.target for artifact in artifacts)
        targets = (*current, *prior)
        parents = {target.destination.parent for target in targets}
        controls = {
            *(parent / ".btrc-publications.lock" for parent in parents),
            self._control_path(directory, name, "lock"),
        }
        for inventory in (current, prior):
            journals = self._journal_paths(directory, name, inventory)
            controls.update(journals)
            controls.update(journal.with_name(f"{journal.name}.tmp") for journal in journals)
            for index, target in enumerate(inventory):
                controls.add(self._stage_path(directory, name, index, target))
                controls.add(self._backup_path(directory, name, index, target))
        candidates = tuple(artifact.staged for artifact in artifacts if artifact.staged is not None)
        if any(path in controls for path in (*candidates, *(target.destination for target in targets))):
            raise ValueError("publication artifacts must not use transaction control paths")
        for target in targets:
            if target.is_directory and (
                any(
                    other.destination != target.destination and other.destination.is_relative_to(target.destination)
                    for other in targets
                )
                or any(candidate.is_relative_to(target.destination) for candidate in candidates)
            ):
                raise ValueError("publication artifacts must not contain other destinations or candidates")

    def _participant_name(self, directory: Path, name: str, parent: Path) -> str:
        if parent == directory:
            return name
        coordinator = hashlib.sha256(os.fsencode(os.path.normcase(directory))).hexdigest()
        return f"{name}-{coordinator}"

    def _journal_paths(
        self, directory: Path, name: str, artifacts: Sequence[PublicationTarget | PublishedArtifact]
    ) -> tuple[Path, ...]:
        parents = sorted({artifact.destination.parent for artifact in artifacts} - {directory})
        return (
            self._control_path(directory, name, "journal"),
            *(
                self._control_path(parent, self._participant_name(directory, name, parent), "journal")
                for parent in parents
            ),
        )

    def _stage_path(
        self, directory: Path, name: str, index: int, artifact: PublicationTarget | PublishedArtifact | None = None
    ) -> Path:
        parent = directory if artifact is None else artifact.destination.parent
        return self._control_path(parent, self._participant_name(directory, name, parent), f"new-{index}")

    def _backup_path(
        self, directory: Path, name: str, index: int, artifact: PublicationTarget | PublishedArtifact | None = None
    ) -> Path:
        parent = directory if artifact is None else artifact.destination.parent
        return self._control_path(parent, self._participant_name(directory, name, parent), f"previous-{index}")

    def _journal_record(
        self,
        artifacts: Sequence[PublicationTarget | PublishedArtifact],
        state: str,
        previous: list[bool],
    ) -> dict:
        distributed = len({artifact.destination.parent for artifact in artifacts}) > 1
        retiring = any(artifact.is_absent for artifact in artifacts)
        return {
            "schema": 3 if retiring else 2 if distributed else _JOURNAL_SCHEMA,
            "state": state,
            "previous": previous,
            "artifacts": [
                {
                    "name": str(artifact.destination) if distributed or retiring else artifact.destination.name,
                    "directory": artifact.is_directory,
                    **({"absent": artifact.is_absent} if retiring else {}),
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

    @staticmethod
    def _unique_journal_object(pairs: list[tuple[str, object]]) -> dict:
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError(f"duplicate publication journal field: {key}")
            record[key] = value
        return record

    def _read_journal(self, path: Path, expected: dict) -> dict | None:
        if self._storage.lstat_or_none(path) is None:
            return None
        # Bound untrusted data by the caller's known inventory, not an implicit
        # translation-unit ceiling. Allow the small legacy formatting allowance.
        byte_limit = max(_MAX_JOURNAL_BYTES, 2 * len(json.dumps(expected).encode("utf-8")))
        descriptor = self._storage.open_regular(path)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                encoded = stream.read(byte_limit + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            record = json.loads(encoded.decode("utf-8"), object_pairs_hook=self._unique_journal_object)
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ValueError(f"invalid publication recovery journal: {path}") from error
        if (
            len(encoded) > byte_limit
            or not isinstance(record, dict)
            or set(record) != {"schema", "state", "previous", "artifacts"}
            or type(record.get("schema")) is not int
            or record.get("schema") != expected["schema"]
            or not isinstance(record.get("state"), str)
            or record.get("state") not in {"publishing", "committed"}
            or not isinstance(record.get("artifacts"), list)
            or not all(
                isinstance(artifact, dict)
                and type(artifact.get("directory")) is bool
                and (record["schema"] != 3 or type(artifact.get("absent")) is bool)
                for artifact in record["artifacts"]
            )
            or record.get("artifacts") != expected["artifacts"]
            or not isinstance(record.get("previous"), list)
            or len(record["previous"]) != len(expected["artifacts"])
            or not all(isinstance(value, bool) for value in record["previous"])
        ):
            raise ValueError(f"invalid publication recovery journal: {path}")
        return record

    def _restore_backup(self, backup: Path, artifact: PublicationTarget) -> None:
        if artifact.is_absent and self._storage.lstat_or_none(artifact.destination) is not None:
            raise ValueError(f"retired artifact reappeared during recovery: {artifact.destination}")
        self._storage.fsync_artifact(backup, artifact.is_directory)
        self._storage.remove(artifact.destination)
        os.replace(backup, artifact.destination)
        # The backup now lives at the destination. A flush failure must retain
        # that last good copy; the journal marks recovery incomplete and lets it
        # retry the flush when it finds no remaining backup name.
        self._storage.fsync_artifact(
            artifact.destination,
            artifact.is_directory,
        )
        self._storage.fsync_directory(artifact.destination.parent)

    def _recover(
        self,
        directory: Path,
        name: str,
        artifacts: Sequence[PublicationTarget | PublishedArtifact],
    ) -> None:
        journal = self._control_path(directory, name, "journal")
        journals = self._journal_paths(directory, name, artifacts)
        expected = self._journal_record(artifacts, "publishing", [])
        record = self._read_journal(journal, expected)
        # A participant marker is never interpreted as an independent commit.
        # Validate its complete caller-supplied path inventory before cleanup.
        for participant in journals[1:]:
            self._read_journal(participant, expected)
        if record is None:
            for index, artifact in enumerate(artifacts):
                self._storage.remove(self._stage_path(directory, name, index, artifact))
                self._storage.remove(self._backup_path(directory, name, index, artifact))
            self._finish_recovery(journals, artifacts)
            return
        if record["state"] == "publishing":
            validator_index = len(artifacts) - 1
            validator = artifacts[validator_index]
            validator_backup = self._backup_path(
                directory,
                name,
                validator_index,
                validator,
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
                backup = self._backup_path(directory, name, index, artifact)
                if record["previous"][index]:
                    if self._storage.lstat_or_none(backup) is not None:
                        self._restore_backup(backup, artifact)
                    else:
                        self._storage.fsync_artifact(
                            artifact.destination,
                            artifact.is_directory,
                        )
                elif not artifact.is_absent:
                    self._storage.remove(artifact.destination)
            if self._storage.lstat_or_none(validator_backup) is not None:
                self._restore_backup(validator_backup, validator)
            for index, artifact in enumerate(artifacts):
                self._storage.remove(self._stage_path(directory, name, index, artifact))
                self._storage.remove(self._backup_path(directory, name, index, artifact))
        else:
            for artifact in artifacts:
                if artifact.is_absent:
                    if self._storage.lstat_or_none(artifact.destination) is not None:
                        raise ValueError(f"retired artifact reappeared during recovery: {artifact.destination}")
                else:
                    self._storage.fsync_artifact(artifact.destination, artifact.is_directory)
            for index, artifact in enumerate(artifacts):
                self._storage.remove(self._backup_path(directory, name, index, artifact))
                self._storage.remove(self._stage_path(directory, name, index, artifact))
        self._finish_recovery(journals, artifacts)

    def _finish_recovery(
        self, journals: Sequence[Path], artifacts: Sequence[PublicationTarget | PublishedArtifact]
    ) -> None:
        for parent in sorted({artifact.destination.parent for artifact in artifacts}):
            self._storage.fsync_directory(parent)
        # Retire the coordinator first. After a crash, remaining participant
        # markers block overlapping writers until retry cleans them; an absent
        # coordinator must never cause a completed rollback to run again.
        for journal in journals:
            self._storage.remove(journal)
            self._storage.remove(journal.with_name(f"{journal.name}.tmp"))
            self._storage.fsync_directory(journal.parent)
