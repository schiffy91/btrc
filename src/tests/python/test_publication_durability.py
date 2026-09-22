"""Crash, concurrency, and reader contracts for artifact publication."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import stat
import threading
from pathlib import Path

import pytest

import src.compiler.python.artifacts.publication as transaction_module
from src.compiler.python.artifacts.cache import CompilerGenerationPublisher, CompilerOutput, ToolchainFingerprint
from src.compiler.python.artifacts.publication import (
    ArtifactPublisher,
    ArtifactStorage,
    PublicationTarget,
    PublishedArtifact,
    StagedPublicationPolicy,
)
from src.compiler.python.artifacts.stdlib import (
    HEADER_NAME,
    IMPL_NAME,
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    ArchiveVersionError,
    StdlibArchivePublisher,
    StdlibArtifactRepository,
)


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


def _publish_bundle(
    publisher: ArtifactPublisher,
    output: Path,
    candidate: tuple[Path, Path, Path],
) -> None:
    publisher.publish(
        "bundle",
        (
            PublishedArtifact(candidate[0], output / "bundle", True),
            PublishedArtifact(candidate[1], output / "bundle.tar.gz"),
            PublishedArtifact(candidate[2], output / "bundle.tar.gz.sha256"),
        ),
    )


def _crash_bundle_publication(output_text: str, candidate_text: str, boundary: str) -> None:
    output = Path(output_text)
    candidate = _bundle_candidates(Path(candidate_text), "interrupted")
    publisher = ArtifactPublisher(ArtifactStorage())
    replace = transaction_module.os.replace

    journal = output / ".bundle.publish.journal"
    remove = publisher._storage.remove

    def exit_at_replacement(source, destination) -> None:
        replace(source, destination)
        source, destination = Path(source), Path(destination)
        if (
            (boundary == "backup" and destination == output / ".bundle.publish.previous-0")
            or (boundary == "payload" and destination == output / "bundle" and source.name == ".bundle.publish.new-0")
            or (
                boundary == "validator"
                and destination == output / "bundle.tar.gz.sha256"
                and source.name == ".bundle.publish.new-2"
            )
            or (
                boundary == "commit"
                and destination == journal
                and json.loads(journal.read_text())["state"] == "committed"
            )
        ):
            os._exit(91)

    def exit_during_cleanup(path) -> None:
        existed = path.exists()
        remove(path)
        if boundary == "cleanup" and existed and path == output / ".bundle.publish.previous-0":
            os._exit(91)

    transaction_module.os.replace = exit_at_replacement
    publisher._storage.remove = exit_during_cleanup
    _publish_bundle(publisher, output, candidate)


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
        "toolchain": ToolchainFingerprint().digest("full"),
        "types": [],
        "functions": [],
        "function_declarations": [],
        "macros": [],
        "helpers": [],
        "global_decl_names": [],
        "shared_helpers": [],
    }


def _publish_stdlib(
    publisher: StdlibArchivePublisher,
    output: Path,
    source: str,
    generation: str,
) -> None:
    header, impl = _stdlib_payload(generation)
    publisher.publish(
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
    publication = ArtifactPublisher(ArtifactStorage())
    _publish_stdlib(
        StdlibArchivePublisher(publication),
        Path(output),
        source,
        generation,
    )


def _file_generation(root: Path, generation: str) -> tuple[PublishedArtifact, ...]:
    artifacts = []
    for folder, name in (("sources", "Main.c"), ("units", "Other.c"), ("plans", "Program.json")):
        directory = root / folder
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / f"candidate-{generation}"
        candidate.write_text(generation)
        artifacts.append(PublishedArtifact(candidate, directory / name))
    return tuple(artifacts)


def _crash_file_generation(root_text: str, boundary: str) -> None:
    root = Path(root_text)
    artifacts = _file_generation(root, "interrupted")
    replace = transaction_module.os.replace
    publisher = ArtifactPublisher()
    remove = publisher._storage.remove
    coordinator = root / "sources/.program.publish.journal"

    def crash_after_primary(source, destination):
        if (
            boundary == "rollback-retired"
            and Path(destination) == artifacts[1].destination
            and ".publish.new-" in Path(source).name
        ):
            raise OSError("force rollback before retirement")
        replace(source, destination)
        destination = Path(destination)
        if (
            (boundary == "participant" and destination.name.endswith(".publish.journal") and destination != coordinator)
            or (
                boundary == "payload"
                and Path(source).name == ".program.publish.new-0"
                and destination == artifacts[0].destination
            )
            or (
                boundary == "committed"
                and destination == coordinator
                and json.loads(coordinator.read_text())["state"] == "committed"
            )
        ):
            os._exit(91)

    def crash_after_retirement(path):
        existed = path.exists()
        remove(path)
        if boundary in {"retired", "rollback-retired"} and path == coordinator and existed:
            os._exit(91)

    transaction_module.os.replace = crash_after_primary
    publisher._storage.remove = crash_after_retirement
    publisher.publish("program", artifacts)


def _concurrent_file_generation(root_text: str, generation: str, start, ready) -> None:
    artifacts = _file_generation(Path(root_text), generation)
    # Different coordinators and lock traversal orders still overlap outputs.
    if generation == "beta":
        artifacts = (artifacts[1], artifacts[0], artifacts[2])
    ready.set()
    if not start.wait(10):
        raise TimeoutError("parent did not start publication")
    ArtifactPublisher().publish(generation, artifacts)


def _retiring_generation(root: Path, generation: str) -> tuple[PublishedArtifact, ...]:
    artifacts = _file_generation(root, generation)
    artifacts[1].staged.unlink()
    return (
        artifacts[0],
        PublishedArtifact(None, artifacts[1].destination, expected_digest=hashlib.sha256(b"old").hexdigest()),
        artifacts[2],
    )


def _crash_retiring_generation(root_text: str, boundary: str) -> None:
    root = Path(root_text)
    artifacts = _retiring_generation(root, "interrupted")
    publisher = ArtifactPublisher()
    replace, remove = transaction_module.os.replace, publisher._storage.remove
    coordinator = root / "sources/.program.publish.journal"

    def crash_on_replace(source, destination):
        replace(source, destination)
        source, destination = Path(source), Path(destination)
        if (
            (boundary == "retirement" and source == artifacts[1].destination)
            or (boundary == "payload" and destination == artifacts[0].destination and ".publish.new-" in source.name)
            or (boundary == "validator" and destination == artifacts[2].destination and ".publish.new-" in source.name)
            or (
                boundary == "committed"
                and destination == coordinator
                and json.loads(coordinator.read_text())["state"] == "committed"
            )
        ):
            os._exit(91)

    def crash_on_cleanup(path):
        existed = path.exists()
        remove(path)
        if boundary == "retired" and path == coordinator and existed:
            os._exit(91)

    transaction_module.os.replace = crash_on_replace
    publisher._storage.remove = crash_on_cleanup
    publisher.publish("program", artifacts)


@pytest.mark.parametrize("boundary", ["retirement", "payload", "validator", "committed", "retired"])
def test_retirement_crash_recovers_before_a_different_inventory(tmp_path, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_retiring_generation, args=(str(tmp_path), boundary)
    )
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    prior = (old[0].target, PublicationTarget(old[1].destination, is_absent=True), old[2].target)
    new = _file_generation(tmp_path, "next")
    new[0].staged.unlink()
    with pytest.raises(ValueError, match="missing"):
        ArtifactPublisher().publish("program", new, previous_inventory=prior)
    committed = boundary in {"committed", "retired"}
    expected = "interrupted" if committed else "old"
    assert old[0].destination.read_text() == old[2].destination.read_text() == expected
    if committed:
        assert not old[1].destination.exists()
    else:
        assert old[1].destination.read_text() == "old"
    ArtifactPublisher().publish("program", _file_generation(tmp_path, "retry"), previous_inventory=prior)
    assert {artifact.destination.read_text() for artifact in old} == {"retry"}
    assert not list(tmp_path.rglob("*.publish.journal"))
    assert not list(tmp_path.rglob("*.publish.previous-*"))


@pytest.mark.parametrize("boundary", ["payload", "committed", "retired"])
def test_retry_of_layout_transition_recognizes_either_authorized_inventory(tmp_path, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_retiring_generation, args=(str(tmp_path), boundary)
    )
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    current = _retiring_generation(tmp_path, "retry")
    current[0].staged.unlink()
    # The transition's caller knows both layouts but cannot know whether a
    # crashed invocation had already recovered the old one and started the new.
    with pytest.raises(ValueError, match="missing"):
        ArtifactPublisher().publish("program", current, previous_inventory=tuple(artifact.target for artifact in old))
    committed = boundary != "payload"
    expected = "interrupted" if committed else "old"
    assert old[0].destination.read_text() == old[2].destination.read_text() == expected
    assert old[1].destination.exists() != committed
    assert not list(tmp_path.rglob("*.publish.journal"))


@pytest.mark.parametrize("count", [0, 1, 4])
@pytest.mark.parametrize("boundary", ["payload", "committed", "retired"])
def test_changed_output_count_and_directory_recovers_previous_layout(tmp_path, count, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_file_generation, args=(str(tmp_path), boundary)
    )
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    current = _file_generation(tmp_path, "next")
    directory = tmp_path / "new units"
    directory.mkdir()
    extras = []
    for index in range(count):
        candidate = directory / f"candidate-{index}"
        candidate.write_text("next")
        extras.append(PublishedArtifact(candidate, directory / f"Part{index}.c"))
    new = (current[0], *extras, current[2])
    ArtifactPublisher().publish("program", new, previous_inventory=tuple(artifact.target for artifact in old))
    assert {artifact.destination.read_text() for artifact in new} == {"next"}
    # Omitting a prior output never authorizes its deletion.
    assert old[1].destination.read_text() == ("old" if boundary == "payload" else "interrupted")
    assert not list(tmp_path.rglob("*.publish.journal"))
    assert not list(tmp_path.rglob("*.publish.previous-*"))


def test_retirement_commits_with_replacements_and_preserves_modified_files(tmp_path):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    old[1].destination.write_text("user edit")
    with pytest.raises(ValueError, match="was modified"):
        ArtifactPublisher().publish("program", _retiring_generation(tmp_path, "rejected"))
    assert old[0].destination.read_text() == old[2].destination.read_text() == "old"
    assert old[1].destination.read_text() == "user edit"
    old[1].destination.write_text("old")
    ArtifactPublisher().publish("program", _retiring_generation(tmp_path, "new"))
    assert old[0].destination.read_text() == old[2].destination.read_text() == "new"
    assert not old[1].destination.exists()
    # Already-absent outputs require no fabricated candidate or hash bypass.
    ArtifactPublisher().publish("program", _retiring_generation(tmp_path, "newer"))
    assert not old[1].destination.exists()


@pytest.mark.parametrize("boundary", ["retirement", "committed"])
def test_recovery_does_not_remove_a_file_recreated_after_retirement(tmp_path, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_retiring_generation, args=(str(tmp_path), boundary)
    )
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    old[1].destination.write_text("new user file")
    with pytest.raises(ValueError, match="reappeared"):
        ArtifactPublisher().publish("program", _retiring_generation(tmp_path, "retry"))
    assert old[1].destination.read_text() == "new user file"
    assert (tmp_path / "sources/.program.publish.journal").is_file()


def _write_old_participant(root_text: str, start, ready, finished) -> None:
    directory = Path(root_text) / "units"
    candidate = directory / "racer-candidate"
    candidate.write_text("racer")
    if not start.wait(10):
        raise TimeoutError("parent did not acquire publication locks")
    ready.set()
    ArtifactPublisher().publish("racer", (PublishedArtifact(candidate, directory / "Other.c"),))
    finished.set()


def test_previous_only_directories_stay_locked_through_new_publication(tmp_path):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    current = _file_generation(tmp_path, "new")
    new = (current[0], current[2])
    context = multiprocessing.get_context("spawn")
    start, ready, finished = context.Event(), context.Event(), context.Event()
    process = context.Process(target=_write_old_participant, args=(str(tmp_path), start, ready, finished))

    class ProbePolicy(StagedPublicationPolicy):
        def validate(self, staged):
            assert [path.read_text() for path in staged] == ["new", "new"]
            start.set()
            assert ready.wait(10)
            assert process.is_alive()
            assert not finished.wait(0.25), "old-layout writer entered while new publication held its locks"

    process.start()
    try:
        ArtifactPublisher().publish(
            "program", new, previous_inventory=tuple(artifact.target for artifact in old), policy=ProbePolicy()
        )
        process.join(15)
        assert process.exitcode == 0 and finished.is_set()
    finally:
        start.set()
        if process.is_alive():
            process.terminate()
        process.join(10)
    assert old[0].destination.read_text() == old[2].destination.read_text() == "new"
    assert old[1].destination.read_text() == "racer"


@pytest.mark.parametrize("corruption", ["path", "directory-kind", "duplicate-state", "state-array"])
def test_changed_inventory_does_not_trust_corrupt_recovery_metadata(tmp_path, corruption):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    sentinel = tmp_path / "unrelated"
    sentinel.write_text("untouched")
    publisher = ArtifactPublisher()
    journal = tmp_path / "sources/.program.publish.journal"
    record = publisher._journal_record(old, "publishing", [True] * len(old))
    if corruption == "path":
        record["artifacts"][1]["name"] = str(sentinel)
    elif corruption == "directory-kind":
        record["artifacts"][1]["directory"] = 0
    elif corruption == "state-array":
        record["state"] = []
    text = json.dumps(record)
    if corruption == "duplicate-state":
        text = text.replace('"state": "publishing"', '"state": "committed", "state": "publishing"')
    journal.write_text(text)
    current = _file_generation(tmp_path, "new")
    with pytest.raises(ValueError, match="invalid publication recovery journal"):
        publisher.publish(
            "program", (current[0], current[2]), previous_inventory=tuple(artifact.target for artifact in old)
        )
    assert sentinel.read_text() == "untouched"
    assert {artifact.destination.read_text() for artifact in old} == {"old"}
    assert current[0].staged.read_text() == "new" and journal.is_file()


@pytest.mark.parametrize("boundary", ["anchor", "validator", "directory", "digest"])
def test_invalid_retirement_requests_preserve_destinations(tmp_path, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    current = list(_retiring_generation(tmp_path, "new"))
    if boundary == "anchor":
        current[0], current[1] = current[1], current[0]
    elif boundary == "validator":
        current[1], current[2] = current[2], current[1]
    elif boundary == "directory":
        current[1] = PublishedArtifact(None, old[1].destination.parent, True, hashlib.sha256(b"old").hexdigest())
    else:
        current[1] = PublishedArtifact(None, old[1].destination, expected_digest="invalid")
    with pytest.raises(ValueError):
        ArtifactPublisher().publish("program", current)
    assert {artifact.destination.read_text() for artifact in old} == {"old"}


def test_retirement_never_follows_a_replaced_output_symlink(tmp_path):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("old")
    old[1].destination.unlink()
    old[1].destination.symlink_to(sentinel)
    with pytest.raises((OSError, ValueError)):
        ArtifactPublisher().publish("program", _retiring_generation(tmp_path, "new"))
    assert old[1].destination.is_symlink() and sentinel.read_text() == "old"
    assert old[0].destination.read_text() == old[2].destination.read_text() == "old"


@pytest.mark.parametrize("edit", [False, True])
def test_retirement_is_validated_after_replacement_policy(tmp_path, edit):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)

    class EditingPolicy(StagedPublicationPolicy):
        def validate(self, staged):
            assert [path.read_text() for path in staged] == ["new", "new"]
            assert old[1].destination.read_text() == "old"
            if edit:
                old[1].destination.write_text("changed during validation")

    current = _retiring_generation(tmp_path, "new")
    if edit:
        with pytest.raises(ValueError, match="was modified"):
            ArtifactPublisher().publish("program", current, policy=EditingPolicy())
        assert old[1].destination.read_text() == "changed during validation"
        assert old[0].destination.read_text() == old[2].destination.read_text() == "old"
    else:
        ArtifactPublisher().publish("program", current, policy=EditingPolicy())
        assert not old[1].destination.exists()


def test_layout_transition_rejects_mixed_participant_inventories(tmp_path):
    old = _file_generation(tmp_path, "old")
    publisher = ArtifactPublisher()
    publisher.publish("program", old)
    current = _file_generation(tmp_path, "new")
    extra = tmp_path / "new units"
    extra.mkdir()
    candidate = extra / "candidate"
    candidate.write_text("new")
    current = (current[0], PublishedArtifact(candidate, extra / "Other.c"), current[2])
    coordinator = old[0].destination.parent
    prior_record = publisher._journal_record(old, "publishing", [True] * len(old))
    new_record = publisher._journal_record(current, "publishing", [True, False, True])
    publisher._write_journal(coordinator / ".program.publish.journal", prior_record)
    participant = next(
        path for path in publisher._journal_paths(coordinator, "program", current) if path.parent == extra
    )
    publisher._write_journal(participant, new_record)
    with pytest.raises(ValueError, match="conflicting inventories"):
        publisher.publish("program", current, previous_inventory=tuple(artifact.target for artifact in old))
    assert {artifact.destination.read_text() for artifact in old} == {"old"}
    assert candidate.read_text() == "new" and participant.is_file()


def test_new_layout_cannot_publish_over_prior_layout_control_files(tmp_path):
    old = _file_generation(tmp_path, "old")
    publisher = ArtifactPublisher()
    publisher.publish("program", old)
    current = _file_generation(tmp_path, "new")
    control = publisher._backup_path(old[0].destination.parent, "program", 1, old[1])
    control.write_text("preserve")
    current = (current[0], PublishedArtifact(current[1].staged, control), current[2])
    with pytest.raises(ValueError, match="control paths"):
        publisher.publish("program", current, previous_inventory=tuple(artifact.target for artifact in old))
    assert control.read_text() == "preserve"
    assert {artifact.destination.read_text() for artifact in old} == {"old"}


def test_publication_spans_directories_and_flushes_each_parent(tmp_path, monkeypatch):
    artifacts = _file_generation(tmp_path, "new")
    storage = ArtifactStorage()
    sync = storage.fsync_directory
    replace = transaction_module.os.replace
    synced = set()

    def observe_sync(path):
        synced.add(path)
        sync(path)

    monkeypatch.setattr(storage, "fsync_directory", observe_sync)

    def same_directory_replace(source, destination):
        assert Path(source).parent == Path(destination).parent
        replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", same_directory_replace)
    ArtifactPublisher(storage).publish("program", artifacts)
    assert {artifact.destination.read_text() for artifact in artifacts} == {"new"}
    assert {artifact.destination.parent for artifact in artifacts} <= synced
    assert not list(tmp_path.rglob("*.publish.journal"))
    assert not list(tmp_path.rglob("*.publish.new-*"))
    assert not list(tmp_path.rglob("*.publish.previous-*"))


def test_cross_directory_publication_failure_rolls_back_all_outputs(tmp_path, monkeypatch):
    publisher = ArtifactPublisher()
    old = _file_generation(tmp_path, "old")
    publisher.publish("program", old)
    artifacts = _file_generation(tmp_path, "new")
    replace = transaction_module.os.replace

    def fail_secondary(source, destination):
        if Path(destination) == artifacts[1].destination and ".publish.new-" in Path(source).name:
            raise OSError("injected secondary publication failure")
        replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", fail_secondary)
    with pytest.raises(OSError, match="injected secondary"):
        publisher.publish("program", artifacts)
    assert {artifact.destination.read_text() for artifact in artifacts} == {"old"}
    assert not list(tmp_path.rglob("*.publish.journal"))


@pytest.mark.parametrize("boundary", ["participant", "payload", "committed", "retired", "rollback-retired"])
def test_cross_directory_crash_blocks_overlapping_writer_until_recovery(tmp_path, boundary):
    old = _file_generation(tmp_path, "old")
    ArtifactPublisher().publish("program", old)
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_crash_file_generation, args=(str(tmp_path), boundary))
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    artifacts = _file_generation(tmp_path, "next")
    before = {
        artifact.destination: artifact.destination.read_bytes() if artifact.destination.exists() else None
        for artifact in artifacts
    }
    with pytest.raises(ValueError, match="requires recovery"):
        # This writer never touches the coordinator's directory: the marker
        # beside its overlapping payload must be enough to prevent mutation.
        ArtifactPublisher().publish("other", artifacts[1:])
    assert {path: path.read_bytes() if path.exists() else None for path in before} == before
    # Trigger recovery independently of new candidate validation.
    for artifact in artifacts:
        artifact.staged.unlink()
    with pytest.raises(ValueError, match="missing"):
        ArtifactPublisher().publish("program", artifacts)
    recovered = "interrupted" if boundary in {"committed", "retired"} else "old"
    assert {artifact.destination.read_text() for artifact in artifacts} == {recovered}
    replacement = _file_generation(tmp_path, "next")
    ArtifactPublisher().publish("other", replacement[1:])
    assert artifacts[0].destination.read_text() == recovered
    assert {artifact.destination.read_text() for artifact in artifacts[1:]} == {"next"}


@pytest.mark.parametrize("reserved", [".btrc-publications.lock", ".program.publish.journal", ".program.publish.new-0"])
def test_publication_rejects_control_path_outputs_before_locking(tmp_path, reserved):
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"new")
    destination = tmp_path / reserved
    destination.write_bytes(b"old")
    with pytest.raises(ValueError, match="control paths"):
        ArtifactPublisher().publish("program", (PublishedArtifact(candidate, destination),))
    assert candidate.read_bytes() == b"new" and destination.read_bytes() == b"old"
    assert set(tmp_path.iterdir()) == {candidate, destination}


def test_publication_rejects_nested_destinations(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    staged = tmp_path / "candidate"
    staged.mkdir()
    secondary = tmp_path / "secondary"
    secondary.write_bytes(b"new")
    with pytest.raises(ValueError, match="must not contain"):
        ArtifactPublisher().publish(
            "program",
            (
                PublishedArtifact(staged, bundle, True),
                PublishedArtifact(secondary, bundle / "inside.c"),
            ),
        )
    assert staged.is_dir() and secondary.read_bytes() == b"new"


def test_large_publication_inventory_has_no_fixed_journal_size_ceiling(tmp_path):
    artifacts = []
    for index in range(260):
        source = tmp_path / f"candidate-{index}"
        source.write_text(str(index))
        destination = tmp_path / (f"unit-{index}-" + "x" * 225)
        artifacts.append(PublishedArtifact(source, destination))
    publisher = ArtifactPublisher()
    assert (
        len(json.dumps(publisher._journal_record(artifacts, "publishing", [False] * len(artifacts))).encode()) > 65536
    )
    publisher.publish("program", artifacts)
    assert [artifact.destination.read_text() for artifact in artifacts] == [str(index) for index in range(260)]
    assert not list(tmp_path.glob("*.publish.journal"))


def test_overlapping_cross_directory_writers_publish_one_generation(tmp_path):
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    ready = [context.Event(), context.Event()]
    writers = [
        context.Process(target=_concurrent_file_generation, args=(str(tmp_path), generation, start, ready[index]))
        for index, generation in enumerate(("alpha", "beta"))
    ]
    try:
        for writer in writers:
            writer.start()
        for event in ready:
            assert event.wait(10)
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
    assert (
        len({(tmp_path / path).read_text() for path in ("sources/Main.c", "units/Other.c", "plans/Program.json")}) == 1
    )
    assert not list(tmp_path.rglob("*.publish.journal"))


@pytest.mark.parametrize("boundary", ["backup", "payload", "validator", "commit", "cleanup"])
def test_interrupted_bundle_transaction_recovers_complete_generation(tmp_path: Path, boundary: str) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    publisher = ArtifactPublisher(ArtifactStorage())
    _publish_bundle(publisher, output, _bundle_candidates(tmp_path / "old", "old"))
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_bundle_publication,
        args=(str(output), str(tmp_path / "interrupted"), boundary),
    )
    process.start()
    try:
        process.join(15)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)
    assert (output / ".bundle.publish.journal").is_file()

    missing = tuple(tmp_path / "missing" / name for name in ("bundle", "archive", "checksum"))
    with pytest.raises(ValueError, match="missing"):
        _publish_bundle(publisher, output, missing)

    generation = "interrupted" if boundary in {"commit", "cleanup"} else "old"
    assert (output / "bundle/marker").read_text(encoding="utf-8") == generation
    assert (output / "bundle.tar.gz").read_bytes() == f"archive-{generation}".encode()
    assert (output / "bundle.tar.gz.sha256").read_bytes() == f"checksum-{generation}".encode()
    assert not (output / ".bundle.publish.journal").exists()
    assert not list(output.glob(".bundle.publish.previous-*"))


@pytest.mark.parametrize("restored_index", [0, 1, 2], ids=["directory", "payload", "validator"])
def test_rollback_flush_failure_preserves_restored_artifact_for_retry(tmp_path, monkeypatch, restored_index):
    output = tmp_path / "dist"
    output.mkdir()
    storage = ArtifactStorage()
    publisher = ArtifactPublisher(storage)
    _publish_bundle(publisher, output, _bundle_candidates(tmp_path / "old", "old"))
    destinations = (output / "bundle", output / "bundle.tar.gz", output / "bundle.tar.gz.sha256")
    restored = destinations[restored_index]
    replace = transaction_module.os.replace
    fsync = storage.fsync_artifact
    failed_publish = False
    failed_flush = False

    def fail_publication(source, destination):
        nonlocal failed_publish
        if Path(destination) == destinations[1] and Path(source).name == ".bundle.publish.new-1":
            failed_publish = True
            raise OSError("injected payload replacement failure")
        replace(source, destination)

    def fail_restored_flush(path, is_directory):
        nonlocal failed_flush
        if failed_publish and not failed_flush and path == restored:
            failed_flush = True
            raise OSError("injected rollback flush failure")
        fsync(path, is_directory)

    monkeypatch.setattr(transaction_module.os, "replace", fail_publication)
    monkeypatch.setattr(storage, "fsync_artifact", fail_restored_flush)
    with pytest.raises(OSError, match="injected rollback flush failure"):
        _publish_bundle(publisher, output, _bundle_candidates(tmp_path / "new", "new"))

    assert failed_publish and failed_flush
    assert (output / ".bundle.publish.journal").is_file()
    preserved = restored / "marker" if restored_index == 0 else restored
    expected = (b"old", b"archive-old", b"checksum-old")[restored_index]
    assert preserved.read_bytes() == expected

    # A fresh owner must complete recovery before validating the next candidate.
    missing = tuple(tmp_path / "missing" / name for name in ("bundle", "archive", "checksum"))
    with pytest.raises(ValueError, match="missing"):
        _publish_bundle(ArtifactPublisher(), output, missing)
    assert (output / "bundle/marker").read_bytes() == b"old"
    assert destinations[1].read_bytes() == b"archive-old"
    assert destinations[2].read_bytes() == b"checksum-old"
    assert not (output / ".bundle.publish.journal").exists()
    assert not list(output.glob(".bundle.publish.previous-*"))
    assert not list(output.glob(".bundle.publish.new-*"))


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
        PublishedArtifact(missing / "bundle", bundle, True),
        PublishedArtifact(missing / "archive", archive),
        PublishedArtifact(missing / "checksum", checksum),
    )
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"must-not-change")
    (output / ".bundle.publish.previous-1").symlink_to(sentinel)
    journal = output / ".bundle.publish.journal"
    publisher = ArtifactPublisher(ArtifactStorage())
    publisher._write_journal(
        journal,
        publisher._journal_record(artifacts, "publishing", [True, True, True]),
    )

    with pytest.raises((OSError, ValueError)):
        _publish_bundle(
            publisher,
            output,
            (missing / "bundle", missing / "archive", missing / "checksum"),
        )

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

    reader_publication = ArtifactPublisher(ArtifactStorage())
    reader = StdlibArchivePublisher(reader_publication)
    StdlibArtifactRepository(reader).load(str(output), source)
    header = (output / HEADER_NAME).read_text(encoding="utf-8")
    impl = (output / IMPL_NAME).read_text(encoding="utf-8")
    assert any(f" {generation} " in header and f" {generation} " in impl for generation in ("alpha", "beta", "gamma"))


def test_stdlib_reader_gets_retryable_mismatch_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "canonical stdlib"
    output = tmp_path / "archive"
    publication = ArtifactPublisher(ArtifactStorage())
    publisher = StdlibArchivePublisher(publication)
    _publish_stdlib(publisher, output, source, "old")
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
            _publish_stdlib(publisher, output, source, "new")
        except BaseException as error:
            errors.append(error)

    writer = threading.Thread(target=publish)
    writer.start()
    try:
        assert payload_published.wait(10)
        with pytest.raises(ArchiveVersionError, match=r"being updated.*retry"):
            StdlibArtifactRepository(publisher).load(str(output), source)
    finally:
        release_writer.set()
        writer.join(10)

    assert errors == []
    StdlibArtifactRepository(publisher).load(str(output), source)
    assert " new " in (output / HEADER_NAME).read_text(encoding="utf-8")
    assert " new " in (output / IMPL_NAME).read_text(encoding="utf-8")


def _compiler_outputs(root: Path, generation: str) -> tuple[CompilerOutput, ...]:
    outputs = []
    for relative, role in (
        ("sources/Main.c", "primary"),
        (f"units-{generation}/Part.c", "secondary"),
        (f"plans/{generation}.json", "link-plan"),
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        candidate = destination.with_name(f"candidate-{generation}-{destination.name}")
        candidate.write_text(f"{generation}:{role}")
        candidate.chmod(0o600)
        outputs.append(CompilerOutput(candidate, destination, role))
    return tuple(outputs)


def _crash_compiler_generation(root_text: str, boundary: str) -> None:
    root = Path(root_text)
    owner = CompilerGenerationPublisher(root / "state")
    replace = transaction_module.os.replace
    remove = owner._storage.remove

    def replace_and_exit(source, destination) -> None:
        replace(source, destination)
        source, destination = Path(source), Path(destination)
        if (
            (boundary == "intent" and destination.name == "intent.json")
            or (boundary == "payload" and destination.name == "Main.c" and ".publish.new-" in source.name)
            or (boundary == "retirement" and destination.name.endswith(".publish.previous-3"))
            or (boundary == "validator" and destination.name == "committed.json" and ".publish.new-" in source.name)
            or (
                boundary == "commit"
                and destination.name.endswith(".publish.journal")
                and json.loads(destination.read_text())["state"] == "committed"
            )
        ):
            os._exit(93)

    def remove_and_exit(path) -> None:
        present = path.exists()
        remove(path)
        if (
            boundary == "coordinator-retired"
            and present
            and path.parent == root / "sources"
            and path.name.endswith(".publish.journal")
        ):
            os._exit(93)

    transaction_module.os.replace = replace_and_exit
    owner._storage.remove = remove_and_exit
    owner.publish(_compiler_outputs(root, "attempted"))


@pytest.mark.parametrize("boundary", ["intent", "retirement", "payload", "validator", "commit", "coordinator-retired"])
def test_compiler_generation_recovers_attempt_before_a_third_layout(tmp_path, boundary):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner = CompilerGenerationPublisher(state)
    owner.publish(_compiler_outputs(tmp_path, "original"))
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_crash_compiler_generation, args=(str(tmp_path), boundary))
    child.start()
    child.join(20)
    assert not child.is_alive()
    assert child.exitcode == 93
    entry = next(path for path in state.iterdir() if path.is_dir())
    assert (entry / "intent.json").is_file()
    intent = json.loads((entry / "intent.json").read_text())
    assert any("units-attempted" in row["path"] for row in intent["targets"])

    recovered = CompilerGenerationPublisher(state).recover(tmp_path / "sources/Main.c")
    expected = "attempted" if boundary in {"commit", "coordinator-retired"} else "original"
    assert [item.destination.read_text() for item in recovered] == [
        f"{expected}:{role}" for role in ("primary", "secondary", "link-plan")
    ]
    assert [item.mode for item in recovered] == [stat.S_IMODE(item.destination.stat().st_mode) for item in recovered]
    assert not (entry / "intent.json").exists()
    assert not tuple(tmp_path.rglob("*.publish.journal"))

    # A fresh owner requests a layout in neither the old nor attempted unit dir.
    CompilerGenerationPublisher(state).publish(_compiler_outputs(tmp_path, "third"))
    final = CompilerGenerationPublisher(state).recover(tmp_path / "sources/Main.c")
    assert [item.destination.read_text() for item in final] == [
        f"third:{role}" for role in ("primary", "secondary", "link-plan")
    ]
    for generation in ("original", "attempted"):
        assert not (tmp_path / f"units-{generation}/Part.c").exists()
        assert not (tmp_path / f"plans/{generation}.json").exists()


def test_compiler_generation_publish_recovers_without_explicit_recovery_call(tmp_path):
    (tmp_path / "state").mkdir(mode=0o700)
    CompilerGenerationPublisher(tmp_path / "state").publish(_compiler_outputs(tmp_path, "original"))
    child = multiprocessing.get_context("spawn").Process(
        target=_crash_compiler_generation, args=(str(tmp_path), "payload")
    )
    child.start()
    child.join(20)
    assert child.exitcode == 93
    CompilerGenerationPublisher(tmp_path / "state").publish(_compiler_outputs(tmp_path, "third"))
    assert (tmp_path / "sources/Main.c").read_text() == "third:primary"
    assert not (tmp_path / "units-original/Part.c").exists()
    assert not (tmp_path / "units-attempted/Part.c").exists()


def test_compiler_generation_retirement_uses_committed_hashes(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner = CompilerGenerationPublisher(state)
    owner.publish(_compiler_outputs(tmp_path, "original"))
    obsolete = tmp_path / "units-original/Part.c"
    obsolete.write_text("user-modified")
    with pytest.raises(ValueError, match="modified"):
        owner.publish(_compiler_outputs(tmp_path, "next"))
    assert obsolete.read_text() == "user-modified"
    assert (tmp_path / "sources/Main.c").read_text() == "original:primary"
    assert not (tmp_path / "units-next/Part.c").exists()
    assert (
        CompilerGenerationPublisher(state).recover(tmp_path / "sources/Main.c")[1].sha256
        == hashlib.sha256(b"original:secondary").hexdigest()
    )


def test_compiler_generation_policy_binds_owned_hashes_after_validation(tmp_path):
    class ChangingPolicy(StagedPublicationPolicy):
        def validate(self, staged):
            staged[0].write_text("changed by candidate validator")

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner = CompilerGenerationPublisher(state)
    owner.publish(_compiler_outputs(tmp_path, "original"))
    with pytest.raises(ValueError, match="changed after preparation"):
        owner.publish(_compiler_outputs(tmp_path, "next"), policy=ChangingPolicy())
    assert (tmp_path / "sources/Main.c").read_text() == "original:primary"
    assert owner.recover(tmp_path / "sources/Main.c")[0].sha256 == hashlib.sha256(b"original:primary").hexdigest()


@pytest.mark.parametrize(
    "damage", ["missing-intent", "duplicate-field", "redirect-anchor", "record-symlink", "numeric-absent"]
)
def test_compiler_generation_rejects_lost_or_invalid_authority(tmp_path, damage):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    CompilerGenerationPublisher(state).publish(_compiler_outputs(tmp_path, "original"))
    child = multiprocessing.get_context("spawn").Process(
        target=_crash_compiler_generation, args=(str(tmp_path), "payload")
    )
    child.start()
    child.join(20)
    assert child.exitcode == 93
    entry = next(path for path in state.iterdir() if path.is_dir())
    intent = entry / "intent.json"
    original = intent.read_text()
    if damage == "missing-intent":
        intent.unlink()
    elif damage == "duplicate-field":
        intent.write_text(original.replace('"schema":1', '"schema":1,"schema":1'))
    elif damage == "record-symlink":
        external = tmp_path / "untrusted.json"
        external.write_text(original)
        intent.unlink()
        intent.symlink_to(external)
    else:
        value = json.loads(original)
        if damage == "redirect-anchor":
            value["targets"][0]["path"] = str(tmp_path / "unrelated.c")
        else:
            value["targets"][0]["absent"] = 0
        intent.write_text(json.dumps(value))
    before = (tmp_path / "sources/Main.c").read_bytes()
    with pytest.raises((ValueError, OSError)):
        CompilerGenerationPublisher(state).publish(_compiler_outputs(tmp_path, "third"))
    assert (tmp_path / "sources/Main.c").read_bytes() == before
    assert tuple(tmp_path.rglob("*.publish.journal"))
    assert not (tmp_path / "units-third/Part.c").exists()


def test_compiler_generation_requires_private_real_state(tmp_path):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    if os.name != "nt":
        with pytest.raises(ValueError, match="private"):
            CompilerGenerationPublisher(public)
    alias = tmp_path / "alias"
    alias.symlink_to(public, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        CompilerGenerationPublisher(alias)


def test_compiler_generation_first_publication_and_optional_roles(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    primary = _compiler_outputs(tmp_path, "first")[0]
    owner = CompilerGenerationPublisher(state)
    assert owner.recover(primary.destination) == ()
    owner.publish((primary,))
    assert len(owner.recover(primary.destination)) == 1
    outputs = _compiler_outputs(tmp_path, "next")
    header = tmp_path / "sources/btrc_rt.h"
    candidate = tmp_path / "sources/header-candidate"
    candidate.write_text("owned runtime header")
    owner.publish((*outputs, CompilerOutput(candidate, header, "freestanding")))
    assert [item.role for item in owner.recover(primary.destination)] == [
        "primary",
        "secondary",
        "link-plan",
        "freestanding",
    ]
    owner.publish((_compiler_outputs(tmp_path, "last")[0],))
    assert not header.exists()
    assert not outputs[1].destination.exists()
    assert not outputs[2].destination.exists()


def test_compiler_generation_intent_barrier_precedes_publisher_entry(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner = CompilerGenerationPublisher(state)
    outputs = _compiler_outputs(tmp_path, "first")
    sync = owner._storage.fsync_directory
    entered = []

    def fail_intent_barrier(directory):
        if (directory / "intent.json").exists():
            raise OSError("intent directory flush failed")
        sync(directory)

    def record_publication(*args, **kwargs):
        entered.append(True)
        raise OSError("publisher entered before intent durability")

    monkeypatch.setattr(owner._files, "sync_parent", lambda path: None)
    monkeypatch.setattr(owner._storage, "fsync_directory", fail_intent_barrier)
    monkeypatch.setattr(owner._publication, "publish", record_publication)
    with pytest.raises(OSError, match="intent directory flush failed"):
        owner.publish(outputs)
    assert not entered
    assert not outputs[0].destination.exists()
    monkeypatch.undo()
    assert CompilerGenerationPublisher(state).recover(outputs[0].destination) == ()
    CompilerGenerationPublisher(state).publish(outputs)
    assert outputs[0].destination.read_text() == "first:primary"


def _concurrent_compiler_writer(root_text, generation, start):
    root = Path(root_text)
    outputs = _compiler_outputs(root, generation)
    if not start.wait(10):
        raise TimeoutError("compiler generation writers did not start")
    CompilerGenerationPublisher(root / "state").publish(outputs)


def test_compiler_generation_serializes_ownership_across_processes(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    CompilerGenerationPublisher(state).publish(_compiler_outputs(tmp_path, "original"))
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    children = [
        context.Process(target=_concurrent_compiler_writer, args=(str(tmp_path), generation, start))
        for generation in ("one", "two")
    ]
    for child in children:
        child.start()
    start.set()
    for child in children:
        child.join(20)
        assert not child.is_alive()
        assert child.exitcode == 0
    final = CompilerGenerationPublisher(state).recover(tmp_path / "sources/Main.c")
    generation = final[0].destination.read_text().split(":")[0]
    assert generation in {"one", "two"}
    assert [item.destination.read_text() for item in final] == [
        f"{generation}:{role}" for role in ("primary", "secondary", "link-plan")
    ]
    for obsolete in {"original", "one", "two"} - {generation}:
        assert not (tmp_path / f"units-{obsolete}/Part.c").exists()
    assert not tuple(state.rglob("intent.json"))
    assert not tuple(tmp_path.rglob("*.publish.journal"))


def test_compiler_generation_rejects_redirected_prior_parent(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    owner = CompilerGenerationPublisher(state)
    owner.publish(_compiler_outputs(tmp_path, "original"))
    unit_dir = tmp_path / "units-original"
    moved = tmp_path / "moved"
    unit_dir.rename(moved)
    unit_dir.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="not canonical"):
        owner.publish(_compiler_outputs(tmp_path, "next"))
    assert (moved / "Part.c").read_text() == "original:secondary"
    assert (tmp_path / "sources/Main.c").read_text() == "original:primary"


def _recover_compiler_with_special_record(root_text):
    root = Path(root_text)
    with pytest.raises(ValueError, match="regular file"):
        CompilerGenerationPublisher(root / "state").recover(root / "sources/Main.c")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO substitution requires POSIX")
def test_compiler_generation_rejects_fifo_record_without_waiting_for_a_writer(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    CompilerGenerationPublisher(state).publish(_compiler_outputs(tmp_path, "original"))
    entry = next(path for path in state.iterdir() if path.is_dir())
    committed = entry / "committed.json"
    committed.unlink()
    os.mkfifo(committed, mode=0o600)
    child = multiprocessing.get_context("spawn").Process(
        target=_recover_compiler_with_special_record, args=(str(tmp_path),)
    )
    child.start()
    child.join(5)
    blocked = child.is_alive()
    if blocked:
        child.terminate()
        child.join(5)
    assert not blocked, "opening a non-regular ownership record must not wait for another process"
    assert child.exitcode == 0
    assert (tmp_path / "sources/Main.c").read_text() == "original:primary"
