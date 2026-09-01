"""Transactional and concurrent publication contracts for btrcc bundles."""

from __future__ import annotations

import gzip
import json
import multiprocessing
import os
import stat
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import pytest

import src.compiler.python.artifacts.archive as archive_source_module
import src.compiler.python.artifacts.publication as transaction_module
from src.compiler.python.artifacts.archive import ArchiveCodec, TargetBinaryValidator
from src.compiler.python.artifacts.publication import (
    ArtifactPublisher,
    ArtifactStorage,
    PublishedArtifact,
)
from src.compiler.python.artifacts.selfhost import (
    SelfhostBundleBuilder,
    SelfhostBundlePublisher,
    SelfhostBundleValidator,
)

ARCHIVE_CODEC = ArchiveCodec()
write_checksum = ARCHIVE_CODEC.write_checksum
from src.tests.python.test_btrcc_bundle import _fixture, _manifest


def _hold_publication_lock(
    output_dir: str,
    bundle_name: str,
    entered,
    release,
) -> None:
    publication = ArtifactPublisher(ArtifactStorage())
    with SelfhostBundlePublisher(publication, SelfhostBundleValidator()).lock(
        Path(output_dir),
        bundle_name,
    ):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("parent did not release bundle publication lock")


def _wait_for_publication_lock(
    output_dir: str,
    bundle_name: str,
    attempted,
    entered,
) -> None:
    attempted.set()
    publication = ArtifactPublisher(ArtifactStorage())
    with SelfhostBundlePublisher(publication, SelfhostBundleValidator()).lock(
        Path(output_dir),
        bundle_name,
    ):
        entered.set()


def test_publication_failure_restores_every_previous_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    archive = tmp_path / "bundle.tar.gz"
    checksum = tmp_path / "bundle.tar.gz.sha256"
    bundle.mkdir()
    (bundle / "marker").write_text("old bundle", encoding="utf-8")
    archive.write_bytes(b"old archive")
    checksum.write_bytes(b"old checksum")

    staging = tmp_path / "staging"
    staging.mkdir()
    staged_bundle = staging / "bundle"
    staged_bundle.mkdir()
    (staged_bundle / "marker").write_text("new bundle", encoding="utf-8")
    staged_archive = staging / "bundle.tar.gz"
    staged_archive.write_bytes(b"new archive")
    staged_checksum = staging / "bundle.tar.gz.sha256"
    staged_checksum.write_bytes(b"new checksum")
    replace = os.replace

    def fail_archive_publish(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(destination) == archive and Path(source).name == ".bundle.publish.new-1":
            raise OSError("injected archive publication failure")
        replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", fail_archive_publish)
    publisher = ArtifactPublisher(ArtifactStorage())
    with pytest.raises(OSError, match="injected archive"):
        publisher.publish(
            "bundle",
            (
                PublishedArtifact(staged_bundle, bundle, True),
                PublishedArtifact(staged_archive, archive),
                PublishedArtifact(staged_checksum, checksum),
            ),
        )

    assert (bundle / "marker").read_text(encoding="utf-8") == "old bundle"
    assert archive.read_bytes() == b"old archive"
    assert checksum.read_bytes() == b"old checksum"


def test_publication_replaces_file_symlinks_without_preserving_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "bundle"
    bundle = tmp_path / name
    archive = tmp_path / "bundle.tar.gz"
    checksum = tmp_path / "bundle.tar.gz.sha256"
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    bundle.mkdir()
    (bundle / "marker").write_bytes(b"old bundle")
    try:
        archive.symlink_to(sentinel)
        checksum.symlink_to(sentinel)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    staging = tmp_path / "staging"
    staging.mkdir()
    staged_bundle = staging / name
    staged_bundle.mkdir()
    (staged_bundle / "marker").write_bytes(b"new bundle")
    staged_archive = staging / archive.name
    staged_archive.write_bytes(b"new archive")
    staged_checksum = staging / checksum.name
    staged_checksum.write_bytes(b"new checksum")
    records = []
    replacements = []
    publisher = ArtifactPublisher(ArtifactStorage())
    write_journal = publisher._write_journal
    replace = transaction_module.os.replace

    def observe_journal(path: Path, record: dict) -> None:
        records.append(record)
        write_journal(path, record)

    def observe_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(destination)))
        replace(source, destination)

    monkeypatch.setattr(publisher, "_write_journal", observe_journal)
    monkeypatch.setattr(transaction_module.os, "replace", observe_replace)

    publisher.publish(
        name,
        (
            PublishedArtifact(staged_bundle, bundle, True),
            PublishedArtifact(staged_archive, archive),
            PublishedArtifact(staged_checksum, checksum),
        ),
    )

    assert (bundle / "marker").read_bytes() == b"new bundle"
    assert archive.read_bytes() == b"new archive"
    assert checksum.read_bytes() == b"new checksum"
    assert not archive.is_symlink()
    assert not checksum.is_symlink()
    assert sentinel.read_bytes() == b"must-not-change"
    assert records[0]["state"] == "publishing"
    assert records[0]["previous"] == [True, False, False]
    assert (bundle, publisher._backup_path(tmp_path, name, 0)) in replacements
    assert (archive, publisher._backup_path(tmp_path, name, 1)) not in replacements
    assert (checksum, publisher._backup_path(tmp_path, name, 2)) not in replacements
    assert not (tmp_path / f".{name}.publish.journal").exists()
    assert not any((tmp_path / f".{name}.publish.previous-{index}").exists() for index in range(3))


def test_recovery_restores_regular_backup_and_unlinks_file_symlinks(
    tmp_path: Path,
) -> None:
    name = "bundle"
    bundle = tmp_path / name
    archive = tmp_path / "bundle.tar.gz"
    checksum = tmp_path / "bundle.tar.gz.sha256"
    bundle.mkdir()
    (bundle / "marker").write_bytes(b"new bundle")
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    try:
        archive.symlink_to(sentinel)
        checksum.symlink_to(sentinel)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")
    publisher = ArtifactPublisher(ArtifactStorage())
    artifacts = (
        PublishedArtifact(tmp_path / "staged-bundle", bundle, True),
        PublishedArtifact(tmp_path / "staged-archive", archive),
        PublishedArtifact(tmp_path / "staged-checksum", checksum),
    )

    backup_bundle = publisher._backup_path(tmp_path, name, 0)
    backup_bundle.mkdir()
    (backup_bundle / "marker").write_bytes(b"old bundle")

    stages = []
    for index in range(len(artifacts)):
        stage = publisher._stage_path(tmp_path, name, index)
        stage.write_bytes(b"partially published")
        stages.append(stage)
    journal = publisher._control_path(tmp_path, name, "journal")
    publisher._write_journal(
        journal,
        publisher._journal_record(artifacts, "publishing", [True, False, False]),
    )

    publisher._recover(tmp_path, name, artifacts)

    assert (bundle / "marker").read_bytes() == b"old bundle"
    assert not archive.exists() and not archive.is_symlink()
    assert not checksum.exists() and not checksum.is_symlink()
    assert sentinel.read_bytes() == b"must-not-change"
    assert not journal.exists()
    assert not any(stage.exists() for stage in stages)
    assert not backup_bundle.exists()


def test_concurrent_same_target_builds_serialize_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    write_journal = ArtifactPublisher._write_journal
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_write_journal(self, *args, **kwargs) -> None:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.05)
            write_journal(self, *args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(ArtifactPublisher, "_write_journal", observed_write_journal)
    errors: list[BaseException] = []
    builder = SelfhostBundleBuilder()

    def build() -> None:
        try:
            builder.build(
                binary=binary,
                target="linux-x64",
                output_dir=output,
                source_root=source_root,
            )
        except BaseException as error:
            errors.append(error)

    workers = [threading.Thread(target=build) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert errors == []
    assert maximum_active == 1
    assert _manifest(output / "btrcc-linux-x64")["target"] == "linux-x64"


def test_same_target_publication_lock_serializes_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    output = tmp_path / "dist"
    output.mkdir()
    holder_entered = context.Event()
    release_holder = context.Event()
    waiter_attempted = context.Event()
    waiter_entered = context.Event()
    holder = context.Process(
        target=_hold_publication_lock,
        args=(str(output), "btrcc-linux-x64", holder_entered, release_holder),
    )
    waiter = context.Process(
        target=_wait_for_publication_lock,
        args=(str(output), "btrcc-linux-x64", waiter_attempted, waiter_entered),
    )

    try:
        holder.start()
        assert holder_entered.wait(10)
        waiter.start()
        assert waiter_attempted.wait(10)
        assert not waiter_entered.wait(0.2)
        release_holder.set()
        assert waiter_entered.wait(10)
        holder.join(10)
        waiter.join(10)
        assert holder.exitcode == 0
        assert waiter.exitcode == 0
    finally:
        release_holder.set()
        for process in (holder, waiter):
            if process.is_alive():
                process.terminate()
            process.join(10)


def test_publication_lock_does_not_follow_a_symlink(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    output.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    (output / ".btrcc-linux-x64.publish.lock").symlink_to(sentinel)

    with pytest.raises((OSError, ValueError)):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=output,
            source_root=source_root,
        )
    assert sentinel.read_bytes() == b"must-not-change"


def test_final_staged_validation_rejects_post_archive_bundle_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    validator = SelfhostBundleValidator()
    validate = validator.validate_generation

    def mutate_then_validate(bundle: Path, *args) -> None:
        (bundle / "README.md").write_text("changed after archiving\n", encoding="utf-8")
        validate(bundle, *args)

    monkeypatch.setattr(validator, "validate_generation", mutate_then_validate)
    with pytest.raises(ValueError, match=r"changed size|does not match its manifest"):
        SelfhostBundleBuilder(validator=validator).build(
            binary=binary,
            target="linux-x64",
            output_dir=output,
            source_root=source_root,
        )

    assert not (output / "btrcc-linux-x64").exists()
    assert not (output / "btrcc-linux-x64.tar.gz").exists()
    assert not (output / ".btrcc-linux-x64.publish.journal").exists()


def test_generation_validator_rejects_coherently_rechecksummed_archive_payload(
    tmp_path: Path,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", "windows-x64")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="windows-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    replacement = tmp_path / "replacement.zip"
    with (
        zipfile.ZipFile(result.archive) as source,
        zipfile.ZipFile(
            replacement,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as destination,
    ):
        for entry in source.infolist():
            payload = source.read(entry)
            if entry.filename.endswith("/README.md"):
                payload = b"attacker-controlled replacement\n"
            destination.writestr(entry, payload)
    os.replace(replacement, result.archive)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="does not match the manifest"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


@pytest.mark.parametrize("target", ["linux-x64", "windows-x64"])
def test_generation_validator_normalizes_malformed_archive_error(
    tmp_path: Path,
    target: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", target)
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target=target,
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    result.archive.write_bytes(b"not an archive")
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="valid tar or ZIP"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


def test_generation_validator_rejects_backslash_manifest_path(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    manifest_path = result.bundle / "share" / "btrc" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "unsafe\\payload"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid file record"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


def test_generation_validator_bounds_unexpected_sparse_file_before_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    unexpected = result.bundle / "unexpected-large"
    with unexpected.open("wb") as stream:
        stream.truncate(1024 * 1024 * 1024 + 1)
    discovered = []
    discover = archive_source_module.ArchiveSource._discover_regular

    def observe_discovery(self, path: Path, metadata, expected_size=None):
        discovered.append(path)
        return discover(self, path, metadata, expected_size)

    monkeypatch.setattr(
        archive_source_module.ArchiveSource,
        "_discover_regular",
        observe_discovery,
    )
    with pytest.raises(ValueError, match="unexpected entries"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )
    assert discovered == []


def test_final_validation_rejects_identical_content_inode_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    validator = SelfhostBundleValidator()
    capture = validator._capture_bundle
    captures = 0

    def replace_after_capture(bundle: Path, *args):
        nonlocal captures
        snapshot = capture(bundle, *args)
        if captures == 0:
            readme = bundle / "README.md"
            replacement = bundle / ".README.replacement"
            replacement.write_bytes(readme.read_bytes())
            replacement.chmod(0o644)
            os.replace(replacement, readme)
        captures += 1
        return snapshot

    monkeypatch.setattr(validator, "_capture_bundle", replace_after_capture)
    with pytest.raises(ValueError, match="bundle changed"):
        SelfhostBundleBuilder(validator=validator).build(
            binary=binary,
            target="linux-x64",
            output_dir=output,
            source_root=source_root,
        )


def test_generation_validator_rejects_noncanonical_bundle_mode(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    (result.bundle / "README.md").chmod(0o600)
    with pytest.raises(ValueError, match="noncanonical mode"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


@pytest.mark.parametrize(
    ("host_os_name", "is_directory", "is_executable", "expected"),
    [
        ("posix", True, False, 0o755),
        ("posix", False, True, 0o755),
        ("posix", False, False, 0o644),
        ("nt", True, False, 0o777),
        ("nt", False, True, 0o777),
        ("nt", False, False, 0o666),
    ],
)
def test_generation_validator_uses_host_staging_mode_contract(
    host_os_name: str,
    is_directory: bool,
    is_executable: bool,
    expected: int,
) -> None:
    assert (
        SelfhostBundleValidator()._expected_staged_mode(
            is_directory=is_directory,
            is_executable=is_executable,
            host_os_name=host_os_name,
        )
        == expected
    )


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows stat modes")
def test_generation_validator_matches_native_windows_staging_modes(tmp_path: Path) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    executable = directory / "btrcc.exe"
    executable.write_bytes(b"binary")
    regular = tmp_path / "README.md"
    regular.write_bytes(b"readme")
    directory.chmod(0o755)
    executable.chmod(0o755)
    regular.chmod(0o644)
    validator = SelfhostBundleValidator()

    assert stat.S_IMODE(directory.lstat().st_mode) == validator._expected_staged_mode(
        is_directory=True,
        is_executable=False,
        host_os_name=os.name,
    )
    assert stat.S_IMODE(executable.lstat().st_mode) == validator._expected_staged_mode(
        is_directory=False,
        is_executable=True,
        host_os_name=os.name,
    )
    assert stat.S_IMODE(regular.lstat().st_mode) == validator._expected_staged_mode(
        is_directory=False,
        is_executable=False,
        host_os_name=os.name,
    )


@pytest.mark.skipif(os.name == "nt", reason="Windows prevents replacing an open executable")
def test_generation_validator_binds_target_check_to_captured_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    executable = result.bundle / "bin/btrcc"
    replacement = tmp_path / "btrcc-replacement"
    replacement.write_bytes(executable.read_bytes())
    replacement.chmod(0o755)
    binary_validator = TargetBinaryValidator()
    original_validate = binary_validator.validate_stream

    def swap_after_target_check(stream, target: str) -> None:
        original_validate(stream, target)
        replacement.replace(executable)

    monkeypatch.setattr(
        binary_validator,
        "validate_stream",
        swap_after_target_check,
    )

    with pytest.raises(ValueError, match="archive source changed while packaging"):
        SelfhostBundleValidator(binary_validator=binary_validator).validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


@pytest.mark.parametrize("target", ["linux-x64", "windows-x64"])
def test_generation_validator_rejects_noncanonical_archive_mode(
    tmp_path: Path,
    target: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", target)
    result = SelfhostBundleBuilder().build(
        binary=binary,
        target=target,
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    replacement = tmp_path / "replacement"
    if target.startswith("windows-"):
        with (
            zipfile.ZipFile(result.archive) as source,
            zipfile.ZipFile(
                replacement,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as destination,
        ):
            for entry in source.infolist():
                payload = source.read(entry)
                if entry.filename.endswith("/README.md"):
                    entry.external_attr = ((stat.S_IFREG | 0o600) << 16) | (entry.external_attr & 0xFFFF)
                destination.writestr(entry, payload)
    else:
        with (
            tarfile.open(result.archive, "r:gz") as source,
            replacement.open("wb") as raw,
            gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                mtime=0,
            ) as compressed,
            tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as destination,
        ):
            for member in source.getmembers():
                payload = source.extractfile(member) if member.isfile() else None
                if member.name.endswith("/README.md"):
                    member.mode = 0o600
                destination.addfile(member, payload)
    os.replace(replacement, result.archive)
    write_checksum(result.archive)
    with pytest.raises(ValueError, match="noncanonical mode"):
        SelfhostBundleValidator().validate_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )
