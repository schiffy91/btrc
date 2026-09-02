"""Strict frozen-boundary manifest and non-tracked candidate contracts."""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from tools.compiler_codegen.verification import (
    BoundaryCapability,
    BoundaryManifest,
    BoundaryRecord,
    CompilerBoundaryVerifier,
    CompilerVerificationError,
    _BoundaryCaptureSession,
)

REPO = Path(__file__).resolve().parents[3]
ZERO_DIGEST = "0" * 64


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _manifest_text(
    root: str,
    records: list[tuple[str, str, str]],
    *,
    portability: str = "portable",
    channels: tuple[str, ...] = ("artifact", "status", "stderr"),
    capability_id: str = "python.tokens",
    boundary: str = "tokens",
    unknown_root: str = "",
) -> str:
    rendered_records = []
    for record_id, channel, digest in records:
        rendered_records.append(
            f'''[[records]]
id = "{record_id}"
fixture = "surface"
capability = "{capability_id}"
compiler = "python"
boundary = "{boundary}"
channel = "{channel}"
baseline_path = "baseline/{record_id}.bin"
baseline_sha256 = "{digest}"
'''
        )
    quoted_channels = ", ".join(f'"{channel}"' for channel in channels)
    return f'''schema_version = 1
baseline_revision = "fce26b8502feb4019784b18cdee27028ec4e3d15"
source_root = "{root}/sources"
artifact_root = "{root}/artifacts"
candidate_root = "{root}/candidate"
equalities = []
{unknown_root}
[formats]
ast = "selfhost-canonical-v1"
ir = "btrc-ir-v1"
status = "signed-decimal-lf-v1"

[[capabilities]]
id = "{capability_id}"
compiler = "python"
boundary = "{boundary}"
portability = "{portability}"
channels = [{quoted_channels}]

[[fixtures]]
id = "surface"
kind = "source"
entry = "surface.btrc"
files = [{{ path = "surface.btrc", source = "surface.source" }}]
capabilities = ["{capability_id}"]

{"".join(rendered_records)}'''


def _write_manifest(repository: Path, root: str, text: str) -> Path:
    manifest = repository / root / "manifest.toml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(text, encoding="utf-8")
    return manifest


def _write_sources(repository: Path, root: str) -> None:
    source_root = repository / root / "sources"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "surface.source").write_text("int main() { return 0; }\n", encoding="utf-8")


def test_manifest_rejects_unknown_keys_and_missing_capability_channels(tmp_path: Path) -> None:
    root = "build/verification/boundary-schema"
    _write_sources(tmp_path, root)
    unknown = _write_manifest(
        tmp_path,
        root,
        _manifest_text(
            root,
            [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
            channels=("artifact",),
            unknown_root="unknown = true",
        ),
    )
    with pytest.raises(CompilerVerificationError, match="unknown unknown"):
        BoundaryManifest.load(unknown)

    missing = _write_manifest(
        tmp_path,
        root,
        _manifest_text(
            root,
            [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
        ),
    )
    with pytest.raises(CompilerVerificationError, match="record coverage differs"):
        BoundaryManifest.load(missing)


def test_observed_capability_is_skipped_unless_explicitly_required(tmp_path: Path) -> None:
    root = "build/verification/boundary-observed"
    _write_sources(tmp_path, root)
    baseline = {
        "surface.python.behavior-gcc.observation": b'{"toolchain":"baseline"}\n',
        "surface.python.behavior-gcc.status": b"0\n",
    }
    records = [(record_id, record_id.rsplit(".", 1)[1], _digest(content)) for record_id, content in baseline.items()]
    manifest_path = _write_manifest(
        tmp_path,
        root,
        _manifest_text(
            root,
            records,
            portability="observed",
            channels=("observation", "status"),
            capability_id="python.behavior-gcc",
            boundary="behavior-gcc",
        ),
    )
    artifact_root = tmp_path / root / "artifacts/baseline"
    candidate_root = tmp_path / root / "candidate/records"
    artifact_root.mkdir(parents=True)
    candidate_root.mkdir(parents=True)
    for record_id, content in baseline.items():
        (artifact_root / f"{record_id}.bin").write_bytes(content)
        candidate = b'{"toolchain":"other"}\n' if record_id.endswith("observation") else b"9\n"
        (candidate_root / f"{record_id}.bin").write_bytes(candidate)

    manifest = BoundaryManifest.load(manifest_path)
    report = manifest.check_candidate(tmp_path, tmp_path / root / "candidate")

    assert report.checked_records == 0
    assert report.skipped_capabilities == ("python.behavior-gcc@surface",)
    with pytest.raises(CompilerVerificationError, match="incompatible capability observation"):
        manifest.check_candidate(
            tmp_path,
            tmp_path / root / "candidate",
            require_observed=True,
        )


def test_candidate_capture_is_build_only_complete_and_non_mutating() -> None:
    verification_root = REPO / "build/verification"
    verification_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="boundary-focused-", dir=verification_root) as temporary:
        working = Path(temporary)
        root = working.relative_to(REPO).as_posix()
        _write_sources(REPO, root)
        draft_records = [
            ("surface.python.tokens.artifact", "artifact", ZERO_DIGEST),
            ("surface.python.tokens.status", "status", ZERO_DIGEST),
            ("surface.python.tokens.stderr", "stderr", ZERO_DIGEST),
        ]
        manifest_path = _write_manifest(REPO, root, _manifest_text(root, draft_records))
        verifier = CompilerBoundaryVerifier(REPO)
        draft = BoundaryManifest.load(manifest_path)

        captured = verifier.capture_boundary_candidate(draft)

        candidate_records = captured.candidate_root / "records"
        baseline_root = REPO / root / "artifacts/baseline"
        baseline_root.mkdir(parents=True)
        final_records = []
        for record_id, channel, _ in draft_records:
            content = (candidate_records / f"{record_id}.bin").read_bytes()
            (baseline_root / f"{record_id}.bin").write_bytes(content)
            final_records.append((record_id, channel, _digest(content)))
        manifest_path.write_text(_manifest_text(root, final_records), encoding="utf-8")
        manifest = BoundaryManifest.load(manifest_path)
        tracked_before = {
            path: path.read_bytes()
            for path in [manifest_path, REPO / root / "sources/surface.source", *baseline_root.iterdir()]
        }

        verifier.capture_boundary_candidate(manifest)
        report = verifier.check_boundary_candidate(manifest)

        assert report.checked_records == 3
        assert report.skipped_capabilities == ()
        assert captured.record_count == 3
        assert captured.byte_count == sum(path.stat().st_size for path in candidate_records.iterdir())
        assert {path: path.read_bytes() for path in tracked_before} == tracked_before


def test_candidate_checker_rejects_extra_candidate_files(tmp_path: Path) -> None:
    root = "build/verification/boundary-extra"
    _write_sources(tmp_path, root)
    baseline = b"tokens\n"
    record_id = "surface.python.tokens.artifact"
    manifest_path = _write_manifest(
        tmp_path,
        root,
        _manifest_text(root, [(record_id, "artifact", _digest(baseline))], channels=("artifact",)),
    )
    artifact = tmp_path / root / f"artifacts/baseline/{record_id}.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(baseline)
    candidate = tmp_path / root / f"candidate/records/{record_id}.bin"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(baseline)
    (candidate.parent / "orphan.bin").write_bytes(b"orphan")

    with pytest.raises(CompilerVerificationError, match=r"extra: records/orphan\.bin"):
        BoundaryManifest.load(manifest_path).check_candidate(tmp_path, tmp_path / root / "candidate")


def test_manifest_rejects_unused_capabilities_wrong_kinds_and_noncanonical_paths(tmp_path: Path) -> None:
    root = "build/verification/boundary-shape"
    _write_sources(tmp_path, root)
    base = _manifest_text(
        root,
        [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
        channels=("artifact",),
    )
    unused = (
        base
        + """
[[capabilities]]
id = "python.ast"
compiler = "python"
boundary = "ast"
portability = "portable"
channels = ["artifact"]
"""
    )
    with pytest.raises(CompilerVerificationError, match="capabilities have no fixture records"):
        BoundaryManifest.load(_write_manifest(tmp_path, root, unused))

    wrong_kind = base.replace('kind = "source"', 'kind = "runtime"')
    with pytest.raises(CompilerVerificationError, match="kind runtime cannot own capabilities"):
        BoundaryManifest.load(_write_manifest(tmp_path, root, wrong_kind))

    noncanonical = base.replace(f'source_root = "{root}/sources"', f'source_root = "{root}//sources"')
    with pytest.raises(CompilerVerificationError, match="normalized relative path"):
        BoundaryManifest.load(_write_manifest(tmp_path, root, noncanonical))


def test_fixture_source_and_status_encodings_reject_orphans_and_noncanonical_bytes(tmp_path: Path) -> None:
    root = "build/verification/boundary-inputs"
    _write_sources(tmp_path, root)
    status = b"00\n"
    record_id = "surface.python.tokens.status"
    manifest_path = _write_manifest(
        tmp_path,
        root,
        _manifest_text(root, [(record_id, "status", _digest(status))], channels=("status",)),
    )
    artifact = tmp_path / root / f"artifacts/baseline/{record_id}.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(status)
    manifest = BoundaryManifest.load(manifest_path)
    with pytest.raises(CompilerVerificationError, match="signed-decimal-lf-v1"):
        manifest.verify_tracked_inputs(tmp_path)

    artifact.write_bytes(b"0\n")
    (tmp_path / root / "sources/orphan.txt").write_text("orphan\n", encoding="utf-8")
    with pytest.raises(CompilerVerificationError, match=r"extra: orphan\.txt"):
        manifest.verify_fixture_sources(tmp_path)


def test_failed_c_capture_unlinks_stale_artifact_and_materializes_behavior_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "build/verification/boundary-failure"
    _write_sources(tmp_path, root)
    records = [
        ("surface.python.c.artifact", "artifact", ZERO_DIGEST),
        ("surface.python.c.status", "status", ZERO_DIGEST),
    ]
    manifest = BoundaryManifest.load(
        _write_manifest(
            tmp_path,
            root,
            _manifest_text(root, records, channels=("artifact", "status"), capability_id="python.c", boundary="c"),
        )
    )
    session = _BoundaryCaptureSession(manifest, tmp_path, tmp_path)
    stale = tmp_path / root / "workspace/outputs/surface/python.c"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")

    def failed_run(command, *, timeout=300):
        assert not stale.exists()
        return subprocess.CompletedProcess(command, 1, b"", b"internal failure")

    monkeypatch.setattr(session, "_run", failed_run)
    channels = session._python_boundary(manifest.fixtures[0], manifest.capabilities[0])
    assert channels == {"artifact": b"", "status": b"1\n"}

    behavior = BoundaryCapability(
        id="python.behavior-gcc",
        compiler="python",
        boundary="behavior-gcc",
        portability="observed",
        channels=("observation", "source-status", "compile-status", "status", "stdout", "stderr"),
    )
    monkeypatch.setattr(
        session,
        "_behavior_observation",
        lambda capability: ("gcc", ("gcc",), "/usr/bin/gcc", (), b'{"host":"test"}\n'),
    )
    monkeypatch.setattr(session, "_behavior_c_source", lambda fixture, compiler: (None, 7))
    behavior_channels = session._behavior_boundary(manifest.fixtures[0], behavior)
    assert behavior_channels == {
        "observation": b'{"host":"test"}\n',
        "source-status": b"7\n",
        "compile-status": b"-1\n",
        "status": b"-1\n",
        "stdout": b"",
        "stderr": b"",
    }


def test_incompatible_observation_is_preflighted_without_executing_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "build/verification/boundary-preflight"
    _write_sources(tmp_path, root)
    manifest = BoundaryManifest.load(
        _write_manifest(
            tmp_path,
            root,
            _manifest_text(
                root,
                [
                    ("surface.python.behavior-gcc.observation", "observation", ZERO_DIGEST),
                    ("surface.python.behavior-gcc.status", "status", ZERO_DIGEST),
                ],
                portability="observed",
                channels=("observation", "status"),
                capability_id="python.behavior-gcc",
                boundary="behavior-gcc",
            ),
        )
    )
    capability = manifest.capabilities[0]
    session = _BoundaryCaptureSession(
        manifest,
        tmp_path,
        tmp_path,
        {("surface", capability.id): b'{"host":"baseline"}\n'},
    )
    monkeypatch.setattr(session, "_capability_observation", lambda item: b'{"host":"other"}\n')

    def forbidden(*args, **kwargs):
        raise AssertionError("incompatible executable producer ran")

    monkeypatch.setattr(session, "_capture_capability", forbidden)
    assert session._capture_compatible_capability(manifest.fixtures[0], capability) == {
        "observation": b'{"host":"other"}\n',
        "status": b"-1\n",
    }
    forced = _BoundaryCaptureSession(manifest, tmp_path, tmp_path)
    monkeypatch.setattr(
        forced,
        "_capture_capability",
        lambda fixture, item: {"observation": b"forced\n", "status": b"0\n"},
    )
    assert forced._capture_compatible_capability(manifest.fixtures[0], capability)["observation"] == b"forced\n"


def test_toolchain_observation_and_behavior_commands_do_not_leak_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "build/verification/boundary-paths"
    _write_sources(tmp_path, root)
    manifest = BoundaryManifest.load(
        _write_manifest(
            tmp_path,
            root,
            _manifest_text(
                root,
                [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
                channels=("artifact",),
            ),
        )
    )
    session = _BoundaryCaptureSession(manifest, tmp_path, tmp_path)
    executable = tmp_path / "fake-compiler"
    executable.write_bytes(b"compiler")
    monkeypatch.setattr(
        session,
        "_run",
        lambda command, timeout=300: subprocess.CompletedProcess(
            command,
            0,
            f"compiler installed at {tmp_path}\n".encode(),
            b"",
        ),
    )
    observation = session._toolchain_observation(
        (str(executable), str(tmp_path / "absolute-argument")),
        str(executable),
        ("-std=c11",),
    )
    assert str(tmp_path).encode() not in observation
    assert b"fake-compiler" in observation

    class WindowsRepository:
        @staticmethod
        def resolve() -> PureWindowsPath:
            return PureWindowsPath("C:/boundary repo")

    session.execution_repository = WindowsRepository()
    diagnostic = session._canonical_diagnostics(b"  --> C:\\boundary repo\\build\\fixture\\program.btrc:2:3\n")
    assert diagnostic == b"  --> $REPOSITORY/build/fixture/program.btrc:2:3\n"
    session.execution_repository = tmp_path

    class ContainerRepository:
        @staticmethod
        def resolve() -> PurePosixPath:
            return PurePosixPath("/workspace")

    session.execution_repository = ContainerRepository()
    diagnostic = session._canonical_diagnostics(
        b"  --> build/verification/compiler-boundaries/workspace/sources/relative.btrc:2:3\n"
        b"  --> /workspace/build/verification/compiler-boundaries/workspace/sources/absolute.btrc:4:5\n"
    )
    assert diagnostic == (
        b"  --> build/verification/compiler-boundaries/workspace/sources/relative.btrc:2:3\n"
        b"  --> $REPOSITORY/build/verification/compiler-boundaries/workspace/sources/absolute.btrc:4:5\n"
    )
    session.execution_repository = tmp_path

    commands = []
    behavior = BoundaryCapability(
        id="python.behavior-gcc",
        compiler="python",
        boundary="behavior-gcc",
        portability="observed",
        channels=("observation", "source-status", "compile-status", "status", "stdout", "stderr"),
    )
    monkeypatch.setattr(
        session,
        "_behavior_observation",
        lambda capability: ("gcc", ("gcc",), "/usr/bin/gcc", ("-std=c11",), b"observation\n"),
    )
    monkeypatch.setattr(session, "_behavior_c_source", lambda fixture, compiler: (b"int main(void){return 0;}\n", 0))

    def compile_failure(command, *, timeout=300):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, b"", b"")

    monkeypatch.setattr(session, "_run", compile_failure)
    session._behavior_boundary(manifest.fixtures[0], behavior)
    assert commands
    assert not any(Path(argument).is_absolute() for argument in commands[0] if "/" in argument)


def test_bootstrap_producer_is_structurally_modeled_without_large_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "build/verification/boundary-bootstrap-model"
    _write_sources(tmp_path, root)
    manifest = BoundaryManifest.load(
        _write_manifest(
            tmp_path,
            root,
            _manifest_text(
                root,
                [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
                channels=("artifact",),
            ),
        )
    )
    session = _BoundaryCaptureSession(manifest, tmp_path, tmp_path)
    monkeypatch.setenv("BTRC_CC", shlex.quote(sys.executable))
    stage = b"fixed point C bytes\n"

    def fake_run(command, *, timeout=300):
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, b"test compiler\n", b"")
        if "src.compiler.python.main" in command:
            output = tmp_path.joinpath(*PurePosixPath(command[command.index("-o") + 1]).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"stage one")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[0].endswith("btrcc1") or command[0].endswith("btrcc2"):
            return subprocess.CompletedProcess(command, 0, stage, b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(session, "_run", fake_run)
    capability = BoundaryCapability(
        id="bootstrap.fixed-point",
        compiler="bootstrap",
        boundary="bootstrap-fixed-point",
        portability="observed",
        channels=(
            "observation",
            "stage1-status",
            "stage1-compile-status",
            "stage2-status",
            "stage2-compile-status",
            "stage3-status",
            "fixed-point-status",
            "stage2-sha256",
            "stage3-sha256",
        ),
    )
    channels = session._bootstrap_boundary(capability)
    assert channels["fixed-point-status"] == b"0\n"
    assert channels["stage2-sha256"] == channels["stage3-sha256"]
    assert not any(channel.endswith("artifact") for channel in channels)


def test_runtime_snapshot_reader_preserves_pinned_v1_rows(tmp_path: Path) -> None:
    root = "build/verification/boundary-runtime-v1"
    _write_sources(tmp_path, root)
    manifest = BoundaryManifest.load(
        _write_manifest(
            tmp_path,
            root,
            _manifest_text(
                root,
                [("surface.python.tokens.artifact", "artifact", ZERO_DIGEST)],
                channels=("artifact",),
            ),
        )
    )
    runtime_root = tmp_path / "src/runtime/c"
    runtime_root.mkdir(parents=True)
    (runtime_root / "btrc_rt.h").write_text("/* header */\n", encoding="utf-8")
    (runtime_root / "core.c").write_text(
        "/* btrc-runtime-helper:begin __btrc_test */\n"
        "static void __btrc_test(void) {}\n"
        "/* btrc-runtime-helper:end __btrc_test */\n",
        encoding="utf-8",
    )
    for asset in (
        "collections.c",
        "cycles.c",
        "mutex.c",
        "process.c",
        "strings.c",
        "threads.c",
        "trycatch.c",
        "gpu.c",
    ):
        (runtime_root / asset).write_text("/* empty */\n", encoding="utf-8")
    (runtime_root / "manifest.toml").write_text(
        """schema_version = 1
marker_version = 1
freestanding_header = "btrc_rt.h"
runtime_call_features = []
header_features = []

[freestanding]
calls = []
objects = []
types = []
literals = []

[[helpers]]
name = "__btrc_test"
category = "core"
asset = "core.c"
dependencies = []
headers = []
source_visible = false
realtime_effect = "safe"
order = { python = 0, btrc = 0 }
""",
        encoding="utf-8",
    )
    session = _BoundaryCaptureSession(manifest, tmp_path, tmp_path)
    metadata, rows, orders = session._runtime_snapshot()
    assert metadata["schema_version"] == 1
    assert rows["__btrc_test"]["provided_types"] == []
    assert rows["__btrc_test"]["provided_objects"] == []
    assert rows["__btrc_test"]["realtime_effect"] == "safe"
    assert rows["__btrc_test"]["source_size"] > 0
    assert orders == {"python": ("__btrc_test",), "btrc": ("__btrc_test",)}


def test_tracked_manifest_has_exact_capability_fixture_and_runtime_universes() -> None:
    manifest = BoundaryManifest.load(REPO / "src/tests/fixtures/compiler_boundaries/manifest.toml")
    assert {fixture.id for fixture in manifest.fixtures} == {
        "surface",
        "managed",
        "lexical-error",
        "parse-error",
        "semantic-error",
        "strict-import-error",
        "runtime-catalog",
    }
    assert {capability.id for capability in manifest.capabilities} == {
        "python.tokens",
        "python.ast",
        "python.raw-ir",
        "python.optimized-ir",
        "python.c",
        "python.diagnostics",
        "python.behavior-gcc",
        "python.behavior-clang",
        "btrc.tokens",
        "btrc.ast",
        "btrc.c",
        "btrc.diagnostics",
        "btrc.behavior-gcc",
        "btrc.behavior-clang",
        "shared.runtime-source",
        "shared.runtime-metadata",
        "shared.runtime-order",
    }
    assert len(manifest.records) == 305
    assert not BoundaryManifest._supports_capability("btrc", "raw-ir")
    assert not BoundaryManifest._supports_capability("btrc", "optimized-ir")
    manifest._validate_runtime_channel_universe(REPO)

    victim = "helper.__btrc_safe_realloc"
    capabilities = tuple(
        replace(capability, channels=tuple(channel for channel in capability.channels if channel != victim))
        if capability.id == "shared.runtime-metadata"
        else capability
        for capability in manifest.capabilities
    )
    records = tuple(
        record
        for record in manifest.records
        if not (record.capability == "shared.runtime-metadata" and record.channel == victim)
    )
    incomplete = replace(manifest, capabilities=capabilities, records=records)
    with pytest.raises(CompilerVerificationError, match="baseline runtime helper rows differ"):
        incomplete._validate_runtime_channel_universe(REPO)


def test_runtime_metadata_difference_reports_exact_fields() -> None:
    record = BoundaryRecord(
        id="runtime.helper",
        fixture="runtime-catalog",
        capability="shared.runtime-metadata",
        compiler="shared",
        boundary="runtime-helper-metadata",
        channel="helper.example",
        baseline_path=PurePosixPath("baseline/runtime.helper.bin"),
        baseline_sha256=ZERO_DIGEST,
    )
    message = BoundaryManifest._difference_message(
        record,
        b'{"dependencies":["a"],"source_sha256":"one"}\n',
        b'{"dependencies":["b"],"source_sha256":"two"}\n',
    )
    assert message.endswith("metadata fields differ: dependencies, source_sha256")
