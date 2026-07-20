"""Crash-recoverable publication of related build artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .artifact_lock import publication_lock
from .artifact_storage import (
    destination_exists as _destination_exists,
)
from .artifact_storage import (
    fsync_artifact as _fsync_artifact,
)
from .artifact_storage import (
    fsync_directory as _fsync_directory,
)
from .artifact_storage import (
    lstat_or_none as _lstat,
)
from .artifact_storage import (
    open_regular as _open_regular,
)
from .artifact_storage import (
    remove_path as _remove,
)
from .artifact_storage import (
    validate_artifact as _validate_artifact,
)

_JOURNAL_SCHEMA, _MAX_JOURNAL_BYTES = 1, 64 * 1024


@dataclass(frozen=True)
class PublishedArtifact:
    staged: Path
    destination: Path
    is_directory: bool = False


def _control_path(directory: Path, name: str, suffix: str) -> Path:
    return directory / f".{name}.publish.{suffix}"


def _stage_path(directory: Path, name: str, index: int) -> Path:
    return _control_path(directory, name, f"new-{index}")


def _backup_path(directory: Path, name: str, index: int) -> Path:
    return _control_path(directory, name, f"previous-{index}")


def _journal_record(artifacts: Sequence[PublishedArtifact], state: str, previous: list[bool]) -> dict:
    return {
        "schema": _JOURNAL_SCHEMA,
        "state": state,
        "previous": previous,
        "artifacts": [
            {"name": artifact.destination.name, "directory": artifact.is_directory} for artifact in artifacts
        ],
    }


def _write_journal(path: Path, record: dict) -> None:
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(f"{path.name}.tmp")
    _remove(temporary)
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
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()


def _read_journal(path: Path, expected: dict) -> dict | None:
    if _lstat(path) is None:
        return None
    descriptor = _open_regular(path)
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


def publication_in_progress(directory: Path, name: str) -> bool:
    return _lstat(_control_path(directory, name, "journal")) is not None


def _restore_backup(backup: Path, artifact: PublishedArtifact) -> None:
    _fsync_artifact(backup, artifact.is_directory)
    _remove(artifact.destination)
    os.replace(backup, artifact.destination)
    try:
        _fsync_artifact(artifact.destination, artifact.is_directory)
    except BaseException:
        _remove(artifact.destination)
        _fsync_directory(artifact.destination.parent)
        raise
    _fsync_directory(artifact.destination.parent)


def _recover(directory: Path, name: str, artifacts: Sequence[PublishedArtifact]) -> None:
    journal = _control_path(directory, name, "journal")
    expected = _journal_record(artifacts, "publishing", [])
    record = _read_journal(journal, expected)
    if record is None:
        for index in range(len(artifacts)):
            _remove(_stage_path(directory, name, index))
            _remove(_backup_path(directory, name, index))
        _remove(journal.with_name(f"{journal.name}.tmp"))
        _fsync_directory(directory)
        return
    if record["state"] == "publishing":
        validator_index = len(artifacts) - 1
        validator = artifacts[validator_index]
        validator_backup = _backup_path(directory, name, validator_index)
        if record["previous"][validator_index]:
            if _lstat(validator_backup) is not None:
                _fsync_artifact(validator_backup, validator.is_directory)
                _remove(validator.destination)
            else:
                _fsync_artifact(validator.destination, validator.is_directory)
        else:
            _remove(validator.destination)
        for index in range(validator_index):
            artifact = artifacts[index]
            backup = _backup_path(directory, name, index)
            if record["previous"][index]:
                if _lstat(backup) is not None:
                    _restore_backup(backup, artifact)
                else:
                    _fsync_artifact(artifact.destination, artifact.is_directory)
            else:
                _remove(artifact.destination)
        if _lstat(validator_backup) is not None:
            _restore_backup(validator_backup, validator)
        for index in range(len(artifacts)):
            _remove(_stage_path(directory, name, index))
            _remove(_backup_path(directory, name, index))
    else:
        for artifact in artifacts:
            _fsync_artifact(artifact.destination, artifact.is_directory)
        for index in range(len(artifacts)):
            _remove(_backup_path(directory, name, index))
            _remove(_stage_path(directory, name, index))
    _fsync_directory(directory)
    journal.unlink()
    _fsync_directory(directory)


def publish_artifacts(
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
    with publication_lock(directory, name):
        _recover(directory, name, artifacts)
        fixed_stages = []
        try:
            for index, artifact in enumerate(artifacts):
                _validate_artifact(artifact.staged, artifact.is_directory)
                _destination_exists(artifact.destination, artifact.is_directory)
                fixed = _stage_path(directory, name, index)
                os.replace(artifact.staged, fixed)
                fixed_stages.append(fixed)
                _fsync_artifact(fixed, artifact.is_directory)
            _fsync_directory(directory)
            if validate_staged is not None:
                validate_staged(tuple(fixed_stages))
            previous = [_destination_exists(artifact.destination, artifact.is_directory) for artifact in artifacts]
            journal = _control_path(directory, name, "journal")
            _write_journal(journal, _journal_record(artifacts, "publishing", previous))
            for index in [len(artifacts) - 1, *range(len(artifacts) - 1)]:
                if previous[index]:
                    os.replace(artifacts[index].destination, _backup_path(directory, name, index))
                    _fsync_directory(directory)
            for index, artifact in enumerate(artifacts):
                os.replace(fixed_stages[index], artifact.destination)
                _fsync_directory(directory)
            _write_journal(journal, _journal_record(artifacts, "committed", previous))
        except BaseException:
            if publication_in_progress(directory, name):
                _recover(directory, name, artifacts)
            else:
                for fixed in fixed_stages:
                    _remove(fixed)
                _fsync_directory(directory)
            raise
        _recover(directory, name, artifacts)
