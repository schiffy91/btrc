"""Transactional and concurrent publication contracts for btrcc bundles."""

from __future__ import annotations

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

import src.compiler.python.artifact_publication as transaction_module
import src.compiler.python.btrcc_bundle_publish as bundle_publish_module
import src.compiler.python.btrcc_bundle_validation as bundle_validation_module
import src.compiler.python.bundle_archive_source as archive_source_module
from src.compiler.python.btrcc_bundle import build_bundle
from src.compiler.python.btrcc_bundle_archive import write_checksum
from src.compiler.python.btrcc_bundle_publish import (
    bundle_publication_lock,
)
from src.tests.python.test_btrcc_bundle import _fixture, _manifest


def _hold_publication_lock(
    output_dir: str,
    bundle_name: str,
    entered,
    release,
) -> None:
    with bundle_publication_lock(Path(output_dir), bundle_name):
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
    with bundle_publication_lock(Path(output_dir), bundle_name):
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
    with pytest.raises(OSError, match="injected archive"):
        transaction_module.publish_artifacts(
            "bundle",
            (
                transaction_module.PublishedArtifact(staged_bundle, bundle, True),
                transaction_module.PublishedArtifact(staged_archive, archive),
                transaction_module.PublishedArtifact(staged_checksum, checksum),
            ),
        )

    assert (bundle / "marker").read_text(encoding="utf-8") == "old bundle"
    assert archive.read_bytes() == b"old archive"
    assert checksum.read_bytes() == b"old checksum"


def test_concurrent_same_target_builds_serialize_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    write_journal = transaction_module._write_journal
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_write_journal(*args, **kwargs) -> None:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.05)
            write_journal(*args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(transaction_module, "_write_journal", observed_write_journal)
    errors: list[BaseException] = []

    def build() -> None:
        try:
            build_bundle(
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
        build_bundle(
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
    validate = bundle_publish_module.btrcc_bundle_validation.validate_bundle_generation

    def mutate_then_validate(bundle: Path, *args) -> None:
        (bundle / "README.md").write_text("changed after archiving\n", encoding="utf-8")
        validate(bundle, *args)

    monkeypatch.setattr(
        bundle_publish_module.btrcc_bundle_validation,
        "validate_bundle_generation",
        mutate_then_validate,
    )
    with pytest.raises(ValueError, match=r"changed size|does not match its manifest"):
        build_bundle(
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
    source_root, binary = _fixture(tmp_path / "source")
    result = build_bundle(
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
        bundle_validation_module.validate_bundle_generation(
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
    source_root, binary = _fixture(tmp_path / "source")
    result = build_bundle(
        binary=binary,
        target=target,
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    result.archive.write_bytes(b"not an archive")
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="valid tar or ZIP"):
        bundle_validation_module.validate_bundle_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )


def test_generation_validator_rejects_backslash_manifest_path(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = build_bundle(
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
        bundle_validation_module.validate_bundle_generation(
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
    result = build_bundle(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    unexpected = result.bundle / "unexpected-large"
    with unexpected.open("wb") as stream:
        stream.truncate(1024 * 1024 * 1024 + 1)
    discovered = []
    discover = archive_source_module._discover_regular

    def observe_discovery(path: Path, metadata, expected_size=None):
        discovered.append(path)
        return discover(path, metadata, expected_size)

    monkeypatch.setattr(archive_source_module, "_discover_regular", observe_discovery)
    with pytest.raises(ValueError, match="unexpected entries"):
        bundle_validation_module.validate_bundle_generation(
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
    capture = bundle_validation_module._capture_bundle
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

    monkeypatch.setattr(bundle_validation_module, "_capture_bundle", replace_after_capture)
    with pytest.raises(ValueError, match="bundle changed"):
        build_bundle(
            binary=binary,
            target="linux-x64",
            output_dir=output,
            source_root=source_root,
        )


def test_generation_validator_rejects_noncanonical_bundle_mode(tmp_path: Path) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    result = build_bundle(
        binary=binary,
        target="linux-x64",
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )
    (result.bundle / "README.md").chmod(0o600)
    with pytest.raises(ValueError, match="noncanonical mode"):
        bundle_validation_module.validate_bundle_generation(
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
    source_root, binary = _fixture(tmp_path / "source")
    result = build_bundle(
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
            tarfile.open(
                replacement,
                "w:gz",
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
        bundle_validation_module.validate_bundle_generation(
            result.bundle,
            result.archive,
            result.checksum,
            result.bundle.name,
            result.archive.name,
        )
