"""Real regular-file journal interoperability, process death and recovery."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.compiler.python.artifacts.publication import (
    ArtifactPublisher,
    ArtifactStorage,
    PublicationLock,
    PublicationTarget,
    PublishedArtifact,
)
from src.tests.runner import default_c_compiler

REPO = Path(__file__).resolve().parents[3]
NAME = "compiler-fixture"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX publication and linked syscall fault injection")


@pytest.fixture(scope="module", params=["python", "btrc"])
def publication_driver(request, selfhost_driver, tmp_path_factory):
    source = REPO / "src/tests/btrc/fixtures/PublicationDriver.btrc"
    faults = source.with_name("PublicationFaults.c")
    revision = hashlib.sha256(faults.read_bytes()).hexdigest()[:8]
    flags = [str(faults), "-pedantic", f"-DBTRC_TEST_FAULT_REVISION=0x{revision}"]
    if sys.platform != "darwin":
        flags.append("-ldl")
    if request.param == "python":
        return selfhost_driver(source, compile_flags=flags)
    directory = tmp_path_factory.mktemp("publication-driver")
    generated, executable = directory / "driver.c", directory / "driver"
    compiler = request.getfixturevalue("immutable_btrcc")
    result = subprocess.run(
        [str(compiler), str(source), "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [
            *shlex.split(os.environ.get("BTRC_CC", default_c_compiler())),
            "-std=c11",
            *flags,
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return executable


def _layout(root, *, retiring=False, distributed=True, count=3):
    destinations = []
    for index in range(count):
        parent = root / (f"part-{index % 2}" if distributed else "part")
        parent.mkdir(parents=True, exist_ok=True)
        destination = parent / f"output-{index}"
        destination.write_text(f"old-{index}")
        destinations.append(destination)
    rows = [
        {
            "path": str(path),
            "absent": retiring and index == 1,
            "digest": hashlib.sha256(path.read_bytes()).hexdigest(),
            "content": f"new-{index}",
            "mode": 0o640,
        }
        for index, path in enumerate(destinations)
    ]
    return {"name": NAME, "targets": rows, "prior": [], "inputs": []}


def _targets(configuration):
    return tuple(PublicationTarget(Path(row["path"]), is_absent=row["absent"]) for row in configuration["targets"])


def _publisher():
    return ArtifactPublisher(ArtifactStorage())


def _controls(configuration):
    targets = _targets(configuration)
    publisher = _publisher()
    root = targets[0].destination.parent
    return publisher._journal_paths(root, NAME, targets), [
        publisher._backup_path(root, NAME, i, t) for i, t in enumerate(targets)
    ]


def _run(driver, tmp_path, configuration, operation="publish", fault=None):
    config = tmp_path / "configuration.json"
    config.write_text(json.dumps(configuration))
    environment = dict(os.environ)
    if fault:
        environment.update(fault)
    return subprocess.run(
        [str(driver), operation, str(config)], capture_output=True, text=True, timeout=60, env=environment
    )


def _assert_generation(configuration, committed):
    for index, row in enumerate(configuration["targets"]):
        path = Path(row["path"])
        if committed and row["absent"]:
            assert not path.exists()
        else:
            assert path.read_text() == f"{'new' if committed else 'old'}-{index}"
    for parent in {Path(row["path"]).parent for row in configuration["targets"]}:
        assert not list(parent.glob(".*.publish.journal*"))
        assert not list(parent.glob(".*.publish.new-*"))
        assert not list(parent.glob(".*.publish.previous-*"))


def _reference_crash(configuration, boundary, count):
    publisher = _publisher()
    replace = os.replace
    targets = _targets(configuration)
    artifacts = []
    for index, (row, target) in enumerate(zip(configuration["targets"], targets, strict=True)):
        candidate = None
        if not target.is_absent:
            candidate = target.destination.with_name(f"candidate-{index}")
            candidate.write_text(row["content"])
        artifacts.append(
            PublishedArtifact(
                candidate, target.destination, expected_digest=row["digest"] if target.is_absent else None
            )
        )
    matches = 0

    def interrupted(source, destination):
        nonlocal matches
        replace(source, destination)
        if str(destination) == boundary:
            matches += 1
            if matches == count:
                os._exit(91)

    os.replace = interrupted
    publisher.publish(NAME, artifacts)


def _interrupt_reference(configuration, path, count=1):
    process = multiprocessing.get_context("spawn").Process(
        target=_reference_crash, args=(configuration, str(path), count)
    )
    process.start()
    process.join(30)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("reference publisher did not reach crash boundary")
    assert process.exitcode == 91


@pytest.mark.parametrize("retiring,distributed", [(False, False), (False, True), (True, True)])
def test_native_publication_uses_reference_protocol(publication_driver, tmp_path, retiring, distributed):
    configuration = _layout(tmp_path, retiring=retiring, distributed=distributed)
    result = _run(publication_driver, tmp_path, configuration)
    assert result.returncode == 0, result.stderr
    _publisher().recover(NAME, _targets(configuration))
    _assert_generation(configuration, True)
    for row in configuration["targets"]:
        if not row["absent"]:
            assert Path(row["path"]).stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize(
    "boundary",
    [
        "participant",
        "publishing",
        "validator-backup",
        "payload-backup",
        "payload",
        "validator",
        "commit",
        "cleanup",
        "coordinator-removed",
    ],
)
@pytest.mark.parametrize("recovery", ["python", "native"])
def test_native_process_death_recovers_from_both_implementations(publication_driver, tmp_path, boundary, recovery):
    configuration = _layout(tmp_path, retiring=True)
    journals, backups = _controls(configuration)
    paths = {
        "participant": journals[1],
        "publishing": journals[0],
        "validator-backup": backups[-1],
        "payload-backup": backups[0],
        "payload": Path(configuration["targets"][0]["path"]),
        "validator": Path(configuration["targets"][-1]["path"]),
        "commit": journals[0],
        "cleanup": backups[0],
        "coordinator-removed": journals[0],
    }
    fault = {
        "BTRC_PUBLICATION_FAULT_KIND": "unlink" if boundary in {"cleanup", "coordinator-removed"} else "rename",
        "BTRC_PUBLICATION_FAULT_PATH": str(paths[boundary]),
        "BTRC_PUBLICATION_FAULT_COUNT": "2" if boundary == "commit" else "1",
    }
    result = _run(publication_driver, tmp_path, configuration, fault=fault)
    assert result.returncode == 91, result.stderr
    if recovery == "python":
        _publisher().recover(NAME, _targets(configuration))
    else:
        result = _run(publication_driver, tmp_path, configuration, "recover")
        assert result.returncode == 0, result.stderr
    _assert_generation(configuration, boundary in {"commit", "cleanup", "coordinator-removed"})


@pytest.mark.parametrize("boundary", ["participant", "payload", "validator", "commit"])
def test_native_recovers_reference_process_death(publication_driver, tmp_path, boundary):
    configuration = _layout(tmp_path, retiring=True)
    journals, _ = _controls(configuration)
    path = (
        journals[1]
        if boundary == "participant"
        else journals[0]
        if boundary == "commit"
        else Path(configuration["targets"][0 if boundary == "payload" else -1]["path"])
    )
    _interrupt_reference(configuration, path, 2 if boundary == "commit" else 1)
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, boundary == "commit")


def test_native_preserves_restored_last_good_file_when_directory_flush_fails(publication_driver, tmp_path):
    configuration = _layout(tmp_path)
    primary = Path(configuration["targets"][0]["path"])
    _interrupt_reference(configuration, primary)
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        "recover",
        fault={
            "BTRC_PUBLICATION_FAULT_KIND": "rename",
            "BTRC_PUBLICATION_FAULT_PATH": str(primary),
            "BTRC_PUBLICATION_FAIL_SYNC": "1",
        },
    )
    assert result.returncode == 1, result.stderr
    assert primary.read_text() == "old-0"
    assert _controls(configuration)[0][0].exists()
    _publisher().recover(NAME, _targets(configuration))
    _assert_generation(configuration, False)


@pytest.mark.parametrize(
    "damage",
    [
        "inventory",
        "duplicate-key",
        "unknown-field",
        "bool-schema",
        "string-previous",
        "participant",
        "unrelated",
        "symlink",
    ],
)
def test_invalid_journal_never_authorizes_mutation(publication_driver, tmp_path, damage):
    configuration = _layout(tmp_path)
    primary = Path(configuration["targets"][0]["path"])
    _interrupt_reference(configuration, primary)
    journals, _ = _controls(configuration)
    path = journals[1] if damage == "participant" else journals[0]
    record = json.loads(path.read_text())
    if damage in {"inventory", "participant"}:
        record["artifacts"][0]["name"] = str(tmp_path / "unowned")
    elif damage == "unknown-field":
        record["injected"] = True
    elif damage == "bool-schema":
        record["schema"] = True
    elif damage == "string-previous":
        record["previous"][0] = "true"
    if damage == "duplicate-key":
        path.write_text('{"schema":2,' + json.dumps(record)[1:])
    elif damage == "unrelated":
        (primary.parent / ".unrelated.publish.journal").write_text("unowned")
    elif damage == "symlink":
        owned = path.with_name("unowned-record")
        path.rename(owned)
        path.symlink_to(owned)
    else:
        path.write_text(json.dumps(record))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and not p.name.endswith(".lock")}
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode == 1, result.stderr
    for path, content in before.items():
        assert Path(path).read_bytes() == content


def test_modified_retirement_is_preserved(publication_driver, tmp_path):
    configuration = _layout(tmp_path, retiring=True)
    retired = Path(configuration["targets"][1]["path"])
    retired.write_text("user edit")
    result = _run(publication_driver, tmp_path, configuration)
    assert result.returncode == 1 and "retired artifact changed" in result.stderr
    assert retired.read_text() == "user edit"
    assert Path(configuration["targets"][0]["path"]).read_text() == "old-0"
    assert not list(tmp_path.rglob(".*.publish.new-*"))


def test_changed_layout_recovers_prior_directories_before_publishing(publication_driver, tmp_path):
    previous = _layout(tmp_path / "old")
    _interrupt_reference(previous, previous["targets"][0]["path"])
    configuration = _layout(tmp_path / "new")
    configuration["targets"][0] = previous["targets"][0]
    configuration["prior"] = previous["targets"]
    result = _run(publication_driver, tmp_path, configuration)
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, True)
    for index, row in enumerate(previous["targets"][1:], start=1):
        assert Path(row["path"]).read_text() == f"old-{index}"
    assert not list(tmp_path.rglob(".*.publish.journal"))


def test_large_inventory_journal_has_no_fixed_64k_ceiling(publication_driver, tmp_path):
    configuration = _layout(tmp_path / ("long-" + "x" * 160), count=260)
    _interrupt_reference(configuration, configuration["targets"][0]["path"])
    assert _controls(configuration)[0][0].stat().st_size > 65536
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, False)


@pytest.mark.parametrize("damage", ["bytes", "mode", "retirement"])
def test_prepared_generation_is_revalidated_before_journaling(publication_driver, tmp_path, damage):
    configuration = _layout(tmp_path, retiring=damage == "retirement")
    targets = _targets(configuration)
    publisher = _publisher()
    coordinator = targets[0].destination.parent
    last_stage = publisher._stage_path(coordinator, NAME, len(targets) - 1, targets[-1])
    damaged = (
        targets[1].destination if damage == "retirement" else publisher._stage_path(coordinator, NAME, 0, targets[0])
    )
    fault = {
        "BTRC_PUBLICATION_FAULT_KIND": "rename",
        "BTRC_PUBLICATION_FAULT_PATH": str(last_stage),
        "BTRC_PUBLICATION_DAMAGE_PATH": str(damaged),
    }
    if damage == "mode":
        fault["BTRC_PUBLICATION_DAMAGE_MODE"] = "1"
    result = _run(publication_driver, tmp_path, configuration, fault=fault)
    assert result.returncode == 1, result.stderr
    assert "changed" in result.stderr
    assert targets[0].destination.read_text() == "old-0"
    assert targets[-1].destination.read_text() == "old-2"
    assert targets[1].destination.read_text() == ("bad-0" if damage == "retirement" else "old-1")
    assert not list(tmp_path.rglob(".*.publish.journal"))
    assert not list(tmp_path.rglob(".*.publish.new-*"))


@pytest.mark.parametrize("boundary", ["payload", "validator", "commit"])
def test_reference_recovers_native_private_generation(publication_driver, tmp_path, monkeypatch, boundary):
    from src.compiler.python.artifacts.cache import CompilerGenerationPublisher, CompilerOutput

    configuration = _layout(tmp_path)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    outputs = []
    for index, row in enumerate(configuration["targets"]):
        destination = Path(row["path"])
        candidate = destination.with_name(f"candidate-{index}")
        candidate.write_text(f"old-{index}")
        outputs.append(CompilerOutput(candidate, destination, "primary" if index == 0 else "secondary"))
    owner = CompilerGenerationPublisher(state)
    owner.publish(outputs)
    primary = outputs[0].destination
    key = hashlib.sha256(os.fsencode(primary)).hexdigest()
    entry = state / key
    journal = primary.parent / f".btrc-output-{key}.publish.journal"
    fault_path = {"payload": primary, "validator": entry / "committed.json", "commit": journal}[boundary]
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        "generation",
        fault={
            "BTRC_PUBLICATION_FAULT_KIND": "rename",
            "BTRC_PUBLICATION_FAULT_PATH": str(fault_path),
            "BTRC_PUBLICATION_FAULT_COUNT": "2" if boundary == "commit" else "1",
        },
    )
    assert result.returncode == 91, result.stderr
    assert (entry / "intent.json").is_file()
    recovered = owner.recover(primary)
    _assert_generation(configuration, boundary == "commit")
    assert len(recovered) == len(outputs)
    for identity in recovered:
        assert identity.sha256 == hashlib.sha256(identity.destination.read_bytes()).hexdigest()
    assert not (entry / "intent.json").exists()
    assert not (entry / "candidate.json").exists()


@pytest.mark.parametrize("binding", ["leaf", "parent"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("seeded", [False, True])
def test_generation_rejects_output_rebound_into_state_without_poisoning_recovery(
    publication_driver, tmp_path, monkeypatch, binding, existing, seeded
):
    configuration = _layout(tmp_path, count=2)
    primary, secondary = (Path(row["path"]) for row in configuration["targets"])
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    entry = state / hashlib.sha256(os.fsencode(primary)).hexdigest()
    entry.mkdir(mode=0o700)
    forbidden = state / secondary.name
    if existing:
        forbidden.write_text("private sentinel")
        forbidden.chmod(0o600)
    alias = tmp_path / "alias"
    original = secondary if binding == "leaf" else secondary.parent
    redirected = forbidden if binding == "leaf" else state
    alias.symlink_to(original, target_is_directory=binding == "parent")
    requested = alias if binding == "leaf" else alias / secondary.name
    configuration["targets"][1]["path"] = str(requested)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    if seeded:
        previous = {**configuration, "targets": [dict(row) for row in configuration["targets"]]}
        for index, row in enumerate(previous["targets"]):
            row["content"] = f"old-{index}"
        result = _run(publication_driver, tmp_path, previous, "generation")
        assert result.returncode == 0, result.stderr
    manifest = entry / "committed.json"
    previous_manifest = manifest.read_bytes() if seeded else None
    config = tmp_path / "configuration.json"
    config.write_text(json.dumps(configuration))
    ready = tmp_path / "owner-wait-ready"
    environment = {
        **os.environ,
        "BTRC_PUBLICATION_WAIT_LOCK": str(entry / ".compiler-owner.publish.lock"),
        "BTRC_PUBLICATION_WAIT_READY": str(ready),
    }
    process = None
    try:
        with PublicationLock(entry, "compiler-owner", threading.Lock(), ArtifactStorage()):
            process = subprocess.Popen(
                [str(publication_driver), "generation", str(config)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists(), "native writer did not reach the held owner lock"
            assert process.poll() is None
            alias.unlink()
            alias.symlink_to(redirected, target_is_directory=binding == "parent")
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout
        assert stderr, "rejected generation must explain its failure"
        assert primary.read_text() == "old-0"
        assert secondary.read_text() == "old-1"
        if existing:
            assert forbidden.read_text() == "private sentinel"
        else:
            assert not forbidden.exists()
        assert not (entry / "intent.json").exists(), stderr
        assert not (entry / "candidate.json").exists(), stderr
        assert (manifest.read_bytes() if manifest.exists() else None) == previous_manifest, stderr
        assert not list(tmp_path.rglob(".*.publish.journal*"))
        alias.unlink()
        alias.symlink_to(original, target_is_directory=binding == "parent")
        result = _run(publication_driver, tmp_path, configuration, "generation")
        assert result.returncode == 0, result.stderr
        assert primary.read_text() == "new-0"
        assert secondary.read_text() == "new-1"
        committed = json.loads((entry / "committed.json").read_text())
        assert [row["path"] for row in committed["files"]] == [str(primary), str(secondary)]
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("length", [0, 63, 65536, 65537, 262145])
def test_retirement_hash_uses_bounded_reads(publication_driver, tmp_path, length):
    configuration = _layout(tmp_path, retiring=True)
    retiring = Path(configuration["targets"][1]["path"])
    content = (bytes(range(256)) * ((length + 255) // 256))[:length]
    retiring.write_bytes(content)
    configuration["targets"][1]["digest"] = hashlib.sha256(content).hexdigest()
    result = _run(publication_driver, tmp_path, configuration, fault={"BTRC_PUBLICATION_READ_PATH": str(retiring)})
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, True)


def test_retirement_change_during_hash_preserves_publication(publication_driver, tmp_path):
    configuration = _layout(tmp_path, retiring=True)
    retiring = Path(configuration["targets"][1]["path"])
    content = bytes(range(256)) * 257
    retiring.write_bytes(content)
    configuration["targets"][1]["digest"] = hashlib.sha256(content).hexdigest()
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        fault={"BTRC_PUBLICATION_READ_PATH": str(retiring), "BTRC_PUBLICATION_CHANGE_AFTER_READ": "1"},
    )
    assert result.returncode != 0
    assert "changed" in result.stderr
    assert retiring.read_bytes() == content + b"changed"
    for index in [0, 2]:
        assert Path(configuration["targets"][index]["path"]).read_text() == f"old-{index}"
    assert not list(tmp_path.rglob(".*.publish.journal*"))
    assert not list(tmp_path.rglob(".*.publish.new-*"))


@pytest.mark.parametrize("kind", ["unlock", "close"])
@pytest.mark.parametrize("owner", ["transaction", "coordinator-directory", "participant-directory", "private-owner"])
def test_generation_reports_release_failure(publication_driver, tmp_path, monkeypatch, kind, owner):
    configuration = _layout(tmp_path)
    primary = Path(configuration["targets"][0]["path"])
    participant = Path(configuration["targets"][1]["path"]).parent
    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    digest = hashlib.sha256(os.fsencode(primary)).hexdigest()
    entry = state / digest
    locks = {
        "transaction": primary.parent / f".btrc-output-{digest}.publish.lock",
        "coordinator-directory": primary.parent / ".btrc-publications.lock",
        "participant-directory": participant / ".btrc-publications.lock",
        "private-owner": entry / ".compiler-owner.publish.lock",
    }
    lock = locks[owner]
    configuration["probeLocks"] = [str(path) for path in locks.values()] + [str(entry / ".btrc-publications.lock")]
    trace = tmp_path / "release-fault"
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        "generation",
        fault={
            "BTRC_PUBLICATION_RELEASE_KIND": kind,
            "BTRC_PUBLICATION_RELEASE_PATH": str(lock),
            "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        },
    )
    assert trace.read_text() == kind, result.stderr
    assert result.returncode != 0, "cleanup failure must not report a successful build"
    assert "release" in result.stderr, result.stderr
    _assert_generation(configuration, True)
    assert not (entry / "intent.json").exists()
    result = _run(publication_driver, tmp_path, configuration, "generation")
    assert result.returncode == 0, result.stderr


def test_publication_keeps_primary_and_release_errors(publication_driver, tmp_path):
    configuration = _layout(tmp_path)
    primary = Path(configuration["targets"][0]["path"])
    configuration["inputs"] = [str(primary)]
    configuration["probeLocks"] = [
        str(primary.parent / f".{NAME}.publish.lock"),
        *[str(Path(row["path"]).parent / ".btrc-publications.lock") for row in configuration["targets"]],
    ]
    trace = tmp_path / "release-fault"
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        fault={
            "BTRC_PUBLICATION_RELEASE_KIND": "unlock",
            "BTRC_PUBLICATION_RELEASE_PATH": str(primary.parent / f".{NAME}.publish.lock"),
            "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        },
    )
    assert trace.read_text() == "unlock", result.stderr
    assert result.returncode != 0
    assert "same file as a source input" in result.stderr
    assert "release publication" in result.stderr
    _assert_generation(configuration, False)


@pytest.mark.parametrize("failed_read", [False, True])
def test_retirement_reports_snapshot_close_failure(publication_driver, tmp_path, failed_read):
    configuration = _layout(tmp_path, retiring=True)
    retiring = Path(configuration["targets"][1]["path"])
    trace = tmp_path / "release-fault"
    fault = {
        "BTRC_PUBLICATION_RELEASE_KIND": "close",
        "BTRC_PUBLICATION_RELEASE_PATH": str(retiring),
        "BTRC_PUBLICATION_RELEASE_AFTER_READ": "1",
        "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        "BTRC_PUBLICATION_READ_PATH": str(retiring),
    }
    if failed_read:
        fault["BTRC_PUBLICATION_FAIL_READ"] = "1"
    result = _run(publication_driver, tmp_path, configuration, fault=fault)
    assert trace.read_text() == "close", result.stderr
    assert result.returncode != 0
    assert "cannot close publication" in result.stderr
    if failed_read:
        assert "changed during read" in result.stderr
    _assert_generation(configuration, False)


def test_recovery_refuses_journal_snapshot_close_failure(publication_driver, tmp_path):
    configuration = _layout(tmp_path)
    journals, _ = _controls(configuration)
    _interrupt_reference(configuration, str(configuration["targets"][0]["path"]))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    trace = tmp_path / "release-fault"
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        "recover",
        fault={
            "BTRC_PUBLICATION_RELEASE_KIND": "close",
            "BTRC_PUBLICATION_RELEASE_PATH": str(journals[0]),
            "BTRC_PUBLICATION_RELEASE_AFTER_READ": "1",
            "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        },
    )
    assert trace.read_text() == "close", result.stderr
    assert result.returncode != 0, "untrusted read must not initiate recovery mutations"
    assert "cannot close publication" in result.stderr
    assert {path: path.read_bytes() for path in before} == before
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, False)


@pytest.mark.parametrize("failed_read", [False, True])
def test_staged_validation_reports_snapshot_close_failure(publication_driver, tmp_path, failed_read):
    configuration = _layout(tmp_path)
    targets = _targets(configuration)
    stage = _publisher()._stage_path(targets[0].destination.parent, NAME, 0, targets[0])
    trace = tmp_path / "release-fault"
    fault = {
        "BTRC_PUBLICATION_RELEASE_KIND": "close",
        "BTRC_PUBLICATION_RELEASE_PATH": str(stage),
        "BTRC_PUBLICATION_RELEASE_AFTER_READ": "1",
        "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        "BTRC_PUBLICATION_READ_PATH": str(stage),
    }
    if failed_read:
        fault["BTRC_PUBLICATION_FAIL_READ"] = "1"
    result = _run(publication_driver, tmp_path, configuration, fault=fault)
    assert trace.read_text() == "close", result.stderr
    assert result.returncode != 0
    assert "cannot close publication snapshot" in result.stderr
    if failed_read:
        assert "staged publication payload changed" in result.stderr
    _assert_generation(configuration, False)


def test_recovery_bounds_journal_for_both_authorized_inventories(publication_driver, tmp_path):
    previous = _layout(tmp_path / "previous")
    configuration = _layout(tmp_path / ("expanded-" + "x" * 160), count=260)
    configuration["targets"][0] = previous["targets"][0]
    configuration["prior"] = previous["targets"]
    _interrupt_reference(configuration, configuration["targets"][0]["path"])
    assert _controls(configuration)[0][0].stat().st_size > 65536
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode == 0, result.stderr
    _assert_generation(configuration, False)
    _assert_generation(previous, False)


def test_recovery_rejects_null_journal(publication_driver, tmp_path):
    configuration = _layout(tmp_path)
    journals, _ = _controls(configuration)
    _interrupt_reference(configuration, configuration["targets"][0]["path"])
    journals[0].write_text("null")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = _run(publication_driver, tmp_path, configuration, "recover")
    assert result.returncode != 0
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("mutation", ["rename", "symlink", "edit", "remove"])
def test_generation_rechecks_sources_after_owner_wait(publication_driver, tmp_path, monkeypatch, mutation):
    configuration = _layout(tmp_path, count=2)
    primary = Path(configuration["targets"][0]["path"])
    source = tmp_path / "ReadSource.btrc"
    source.write_text("int main() { return 7; }\n")
    original = source.read_bytes()
    configuration["inputs"] = [str(source)]
    configuration["readInputs"] = [str(source)]
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    entry = state / hashlib.sha256(os.fsencode(primary)).hexdigest()
    entry.mkdir(mode=0o700)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    config = tmp_path / "configuration.json"
    config.write_text(json.dumps(configuration))
    ready = tmp_path / "source-read-owner-wait"
    process = None
    try:
        with PublicationLock(entry, "compiler-owner", threading.Lock(), ArtifactStorage()):
            process = subprocess.Popen(
                [str(publication_driver), "generation", str(config)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    **os.environ,
                    "BTRC_PUBLICATION_WAIT_LOCK": str(entry / ".compiler-owner.publish.lock"),
                    "BTRC_PUBLICATION_WAIT_READY": str(ready),
                },
            )
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists() and process.poll() is None, "writer did not reach owner wait after source read"
            if mutation in {"rename", "symlink"}:
                source.replace(primary)
                if mutation == "rename":
                    source.write_text("int replacement;\n")
                else:
                    replacement = tmp_path / "Replacement.btrc"
                    replacement.write_text("int replacement;\n")
                    source.symlink_to(replacement)
            elif mutation == "edit":
                source.write_text("int changedAfterRead;\n")
            else:
                source.unlink()
            expected = primary.read_bytes()
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode != 0, stdout
        assert "source input changed" in stderr
        assert primary.read_bytes() == expected
        if mutation in {"rename", "symlink"}:
            assert expected == original
        assert Path(configuration["targets"][1]["path"]).read_text() == "old-1"
        assert not (entry / "intent.json").exists()
        assert not (entry / "candidate.json").exists()
        assert not list(tmp_path.rglob(".*.publish.journal*"))
        if mutation == "remove":
            source.write_bytes(original)
        result = _run(publication_driver, tmp_path, configuration, "generation")
        assert result.returncode == 0, result.stderr
        _assert_generation(configuration, True)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_source_reader_rejects_replacement_during_stream_read(publication_driver, tmp_path):
    configuration = _layout(tmp_path)
    source = tmp_path / "ReadSource.btrc"
    source.write_text("int main() { return 7; }\n")
    saved = tmp_path / "saved-source"
    configuration["readInputs"] = [str(source)]
    result = _run(
        publication_driver,
        tmp_path,
        configuration,
        fault={
            "BTRC_SOURCE_READ_PATH": str(source),
            "BTRC_SOURCE_READ_RENAME_TO": str(saved),
        },
    )
    assert result.returncode != 0
    assert "source input changed" in result.stderr
    assert saved.read_text() == "int main() { return 7; }\n"
    assert source.read_text() == "int replacement;\n"
    _assert_generation(configuration, False)


@pytest.mark.parametrize("close_failure", [False, True])
def test_generation_retention_reads_outputs_and_releases_every_handle(
    publication_driver, tmp_path, monkeypatch, close_failure
):
    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    configuration = _layout(tmp_path)
    first = _run(publication_driver, tmp_path, configuration, "generation")
    assert first.returncode == 0, first.stderr
    paths = [*(Path(row["path"]) for row in configuration["targets"]), *state.glob("*/committed.json")]
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths}
    fault = None
    if close_failure:
        trace = tmp_path / "release-fault"
        fault = {
            "BTRC_PUBLICATION_RELEASE_KIND": "close",
            "BTRC_PUBLICATION_RELEASE_PATH": configuration["targets"][0]["path"],
            "BTRC_PUBLICATION_RELEASE_AFTER_READ": "1",
            "BTRC_PUBLICATION_RELEASE_TRACE": str(trace),
        }
    second = _run(publication_driver, tmp_path, configuration, "generation", fault=fault)
    if close_failure:
        assert second.returncode != 0
        assert trace.read_text() == "close"
        assert "cannot close publication snapshot" in second.stderr
    else:
        assert second.returncode == 0, second.stderr
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths} == before


@pytest.mark.parametrize("clear_digests", [False, True])
def test_generation_digests_follow_current_payloads_and_revalidate_files(
    publication_driver, tmp_path, monkeypatch, clear_digests
):
    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    configuration = _layout(tmp_path)
    contents = ["same size", "short", "é漢🙂"]
    for row, content in zip(configuration["targets"], contents, strict=True):
        row["content"] = content
    configuration["digestContents"] = ["different", "x" * 4096, contents[2]]
    configuration["clearDigests"] = clear_digests

    first = _run(publication_driver, tmp_path, configuration, "generation")
    assert first.returncode == 0, first.stderr
    manifest_path = next(state.glob("*/committed.json"))
    manifest = json.loads(manifest_path.read_text())
    expected = {row["path"]: hashlib.sha256(row["content"].encode()).hexdigest() for row in configuration["targets"]}
    assert {row["path"]: row["sha256"] for row in manifest["files"]} == expected
    paths = [*(Path(row["path"]) for row in configuration["targets"]), manifest_path]
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths}
    warm = _run(publication_driver, tmp_path, configuration, "generation")
    assert warm.returncode == 0, warm.stderr
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths} == before

    damaged = paths[0]
    status = damaged.stat()
    damaged.write_text("tampered!")
    os.utime(damaged, ns=(status.st_atime_ns, status.st_mtime_ns))
    repaired = _run(publication_driver, tmp_path, configuration, "generation")
    assert repaired.returncode == 0, repaired.stderr
    for row in configuration["targets"]:
        assert Path(row["path"]).read_text() == row["content"]
    assert manifest_path.read_bytes() == before[manifest_path][2]
