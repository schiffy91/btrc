"""Crash-recoverable publication of related build artifacts."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .lock import PublicationLock
from .storage import ArtifactStorage

_JOURNAL_SCHEMA, _MAX_JOURNAL_BYTES = 1, 64 * 1024


@dataclass(frozen=True)
class PublishedArtifact:
    staged: Path
    destination: Path
    is_directory: bool = False


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
        validate_staged: Callable[[Sequence[Path]], None] | None = None,
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
                if validate_staged is not None:
                    validate_staged(tuple(fixed_stages))
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
