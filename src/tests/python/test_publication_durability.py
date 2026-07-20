"""Crash, concurrency, and reader contracts for artifact publication."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
import threading
from pathlib import Path

import pytest

import src.compiler.python.artifact_publication as transaction_module
from src.compiler.python.cache_keys import toolchain_hash
from src.compiler.python.stdlib_archive import (
    HEADER_NAME,
    IMPL_NAME,
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    ArchiveVersionError,
    load_manifest,
)
from src.compiler.python.stdlib_archive_publish import publish_stdlib_archive


def _bundle_candidates(root: Path, generation: str) -> tuple[Path, Path, Path]:
    root.mkdir()
    bundle = root / "bundle"
    bundle.mkdir()
    (bundle / "marker").write_text(generation, encoding="utf-8")
    archive = root / "bundle.tar.gz"
    archive.write_bytes(f"archive-{generation}".encode())
    checksum = root / "bundle.tar.gz.sha256"
    checksum.write_bytes(f"checksum-{generation}".encode())
    return bundle, archive, checksum


def _publish_bundle(output: Path, candidate: tuple[Path, Path, Path]) -> None:
    transaction_module.publish_artifacts(
        "bundle",
        (
            transaction_module.PublishedArtifact(candidate[0], output / "bundle", True),
            transaction_module.PublishedArtifact(candidate[1], output / "bundle.tar.gz"),
            transaction_module.PublishedArtifact(candidate[2], output / "bundle.tar.gz.sha256"),
        ),
    )


def _crash_bundle_publication(output_text: str, candidate_text: str) -> None:
    output = Path(output_text)
    candidate = _bundle_candidates(Path(candidate_text), "interrupted")
    replace = transaction_module.os.replace

    def exit_after_first_payload(source, destination) -> None:
        replace(source, destination)
        if Path(destination) == output / "bundle" and Path(source).name == ".bundle.publish.new-0":
            os._exit(91)

    transaction_module.os.replace = exit_after_first_payload
    _publish_bundle(output, candidate)


def _stdlib_payload(generation: str) -> tuple[str, str]:
    return f"/* header {generation} */\n", f"/* implementation {generation} */\n"


def _stdlib_manifest(source: str, header: str, impl: str) -> dict:
    return {
        "artifacts": {
            HEADER_NAME: hashlib.sha256(header.encode()).hexdigest(),
            IMPL_NAME: hashlib.sha256(impl.encode()).hexdigest(),
        },
        "schema": MANIFEST_SCHEMA,
        "stdlib_source": hashlib.sha256(source.encode()).hexdigest(),
        "toolchain": toolchain_hash("full"),
        "types": [],
        "functions": [],
        "function_declarations": [],
        "macros": [],
        "helpers": [],
        "global_decl_names": [],
        "shared_helpers": [],
    }


def _publish_stdlib(output: Path, source: str, generation: str) -> None:
    header, impl = _stdlib_payload(generation)
    publish_stdlib_archive(
        str(output),
        HEADER_NAME,
        header,
        IMPL_NAME,
        impl,
        MANIFEST_NAME,
        _stdlib_manifest(source, header, impl),
    )


def _concurrent_stdlib_writer(output: str, source: str, generation: str, start) -> None:
    if not start.wait(10):
        raise TimeoutError("parent did not start concurrent archive writers")
    _publish_stdlib(Path(output), source, generation)


def test_interrupted_bundle_transaction_restores_prior_generation(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    _publish_bundle(output, _bundle_candidates(tmp_path / "old", "old"))
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_bundle_publication,
        args=(str(output), str(tmp_path / "interrupted")),
    )
    process.start()
    process.join(15)
    assert process.exitcode == 91
    assert (output / ".bundle.publish.journal").is_file()

    missing = tuple(tmp_path / "missing" / name for name in ("bundle", "archive", "checksum"))
    with pytest.raises(ValueError, match="missing"):
        _publish_bundle(output, missing)

    assert (output / "bundle/marker").read_text(encoding="utf-8") == "old"
    assert (output / "bundle.tar.gz").read_bytes() == b"archive-old"
    assert (output / "bundle.tar.gz.sha256").read_bytes() == b"checksum-old"
    assert not (output / ".bundle.publish.journal").exists()
    assert not list(output.glob(".bundle.publish.previous-*"))


def test_recovery_rejects_symlinked_backup_from_forged_journal(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    bundle = output / "bundle"
    bundle.mkdir()
    (bundle / "marker").write_text("old", encoding="utf-8")
    archive = output / "bundle.tar.gz"
    archive.write_bytes(b"archive-old")
    checksum = output / "bundle.tar.gz.sha256"
    checksum.write_bytes(b"checksum-old")
    missing = tmp_path / "missing"
    artifacts = (
        transaction_module.PublishedArtifact(missing / "bundle", bundle, True),
        transaction_module.PublishedArtifact(missing / "archive", archive),
        transaction_module.PublishedArtifact(missing / "checksum", checksum),
    )
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    (output / ".bundle.publish.previous-1").symlink_to(sentinel)
    journal = output / ".bundle.publish.journal"
    transaction_module._write_journal(
        journal,
        transaction_module._journal_record(artifacts, "publishing", [True, True, True]),
    )

    with pytest.raises((OSError, ValueError)):
        _publish_bundle(output, (missing / "bundle", missing / "archive", missing / "checksum"))

    assert sentinel.read_bytes() == b"must-not-change"
    assert archive.read_bytes() == b"archive-old"
    assert journal.is_file()


def test_concurrent_stdlib_writers_leave_one_valid_generation(tmp_path: Path) -> None:
    source = "canonical stdlib"
    output = tmp_path / "archive"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    writers = [
        context.Process(
            target=_concurrent_stdlib_writer,
            args=(str(output), source, generation, start),
        )
        for generation in ("alpha", "beta", "gamma")
    ]
    try:
        for writer in writers:
            writer.start()
        start.set()
        for writer in writers:
            writer.join(20)
            assert writer.exitcode == 0
    finally:
        start.set()
        for writer in writers:
            if writer.is_alive():
                writer.terminate()
            writer.join(10)

    load_manifest(str(output), source)
    header = (output / HEADER_NAME).read_text(encoding="utf-8")
    impl = (output / IMPL_NAME).read_text(encoding="utf-8")
    assert any(f" {generation} " in header and f" {generation} " in impl for generation in ("alpha", "beta", "gamma"))


def test_stdlib_reader_gets_retryable_mismatch_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "canonical stdlib"
    output = tmp_path / "archive"
    _publish_stdlib(output, source, "old")
    replace = os.replace
    payload_published = threading.Event()
    release_writer = threading.Event()

    def pause_after_header(source_path, destination) -> None:
        replace(source_path, destination)
        if Path(destination) == output / HEADER_NAME and Path(source_path).name.endswith("new-0"):
            payload_published.set()
            if not release_writer.wait(10):
                raise TimeoutError("reader did not release archive writer")

    monkeypatch.setattr(transaction_module.os, "replace", pause_after_header)
    errors: list[BaseException] = []

    def publish() -> None:
        try:
            _publish_stdlib(output, source, "new")
        except BaseException as error:
            errors.append(error)

    writer = threading.Thread(target=publish)
    writer.start()
    try:
        assert payload_published.wait(10)
        with pytest.raises(ArchiveVersionError, match=r"being updated.*retry"):
            load_manifest(str(output), source)
    finally:
        release_writer.set()
        writer.join(10)

    assert errors == []
    load_manifest(str(output), source)
    assert " new " in (output / HEADER_NAME).read_text(encoding="utf-8")
    assert " new " in (output / IMPL_NAME).read_text(encoding="utf-8")
