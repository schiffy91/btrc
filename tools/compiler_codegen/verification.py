"""Generated-source publication and compiler-boundary verification owners."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar

from src.compiler.python.syntax.ast.codec import AstCanonicalRenderer

from . import GeneratedArtifact, GeneratedSourceError


@dataclass(frozen=True, slots=True)
class GeneratedSourceSet:
    """A complete, collision-free collection of generated artifacts."""

    artifacts: tuple[GeneratedArtifact, ...]

    def __post_init__(self) -> None:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise GeneratedSourceError("generated artifact paths must be unique")

    def stale_paths(self, repository_root: Path) -> tuple[Path, ...]:
        stale: list[Path] = []
        for artifact in self.artifacts:
            target = repository_root.joinpath(*artifact.path.parts)
            if not target.is_file() or target.read_bytes() != artifact.content:
                stale.append(target)
        return tuple(stale)

    def check(self, repository_root: Path) -> None:
        stale = self.stale_paths(repository_root)
        if stale:
            rendered = "\n".join(f"  {path}" for path in stale)
            raise GeneratedSourceError(f"generated sources are stale:\n{rendered}")

    def publish(self, repository_root: Path) -> None:
        """Atomically replace every artifact after all output has rendered."""

        for artifact in self.artifacts:
            target = repository_root.joinpath(*artifact.path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, artifact.mode)
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()


class CompilerVerificationError(RuntimeError):
    """A compiler-boundary verifier could not be configured or executed."""


@dataclass(frozen=True, slots=True)
class BoundaryFormats:
    """Versioned canonical encodings used by frozen boundary records."""

    ast: str
    ir: str
    status: str


@dataclass(frozen=True, slots=True)
class BoundaryCapability:
    """One explicitly supported compiler/boundary observation."""

    id: str
    compiler: str
    boundary: str
    portability: str
    channels: tuple[str, ...]

    @property
    def observed(self) -> bool:
        return self.portability == "observed"


@dataclass(frozen=True, slots=True)
class BoundarySourceFile:
    """One tracked fixture source staged under a stable ephemeral path."""

    path: PurePosixPath
    source: PurePosixPath


@dataclass(frozen=True, slots=True)
class BoundaryFixture:
    """One source, runtime, or bootstrap boundary fixture."""

    id: str
    kind: str
    entry: PurePosixPath | None
    files: tuple[BoundarySourceFile, ...]
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryRecord:
    """One exact byte channel with an optional reviewed correctness delta."""

    id: str
    fixture: str
    capability: str
    compiler: str
    boundary: str
    channel: str
    baseline_path: PurePosixPath
    baseline_sha256: str
    accepted_path: PurePosixPath | None = None
    accepted_sha256: str | None = None
    reason: str | None = None
    regressions: tuple[str, ...] = ()

    @property
    def candidate_path(self) -> PurePosixPath:
        return PurePosixPath("records", self.id + ".bin")

    @property
    def expected_path(self) -> PurePosixPath:
        return self.accepted_path or self.baseline_path

    @property
    def expected_sha256(self) -> str:
        return self.accepted_sha256 or self.baseline_sha256


@dataclass(frozen=True, slots=True)
class BoundaryEquality:
    """One exact current-tree parity relation between captured records."""

    id: str
    left: str
    right: str


@dataclass(frozen=True, slots=True)
class BoundaryCheckReport:
    """Portable records checked and incompatible observed gates skipped."""

    checked_records: int
    skipped_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoundaryCandidateArtifact:
    """One derived candidate byte channel."""

    path: PurePosixPath
    content: bytes


@dataclass(frozen=True, slots=True)
class BoundaryCaptureReport:
    """Summary of one non-tracked candidate publication."""

    candidate_root: Path
    record_count: int
    byte_count: int
    revision: str


@dataclass(frozen=True, slots=True)
class BoundaryCandidateSet:
    """A complete candidate collection published only beneath build/."""

    artifacts: tuple[BoundaryCandidateArtifact, ...]

    def __post_init__(self) -> None:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise CompilerVerificationError("boundary candidate paths must be unique")
        if any(path.is_absolute() or ".." in path.parts for path in paths):
            raise CompilerVerificationError("boundary candidate paths must be normalized and relative")

    @property
    def byte_count(self) -> int:
        return sum(len(artifact.content) for artifact in self.artifacts)

    def publish(self, candidate_root: Path) -> None:
        """Atomically replace declared candidate files, rejecting stale extras."""

        expected = {artifact.path for artifact in self.artifacts}
        actual = (
            {
                PurePosixPath(path.relative_to(candidate_root).as_posix())
                for path in candidate_root.rglob("*")
                if path.is_file()
            }
            if candidate_root.exists()
            else set()
        )
        extras = actual - expected
        if extras:
            rendered = ", ".join(str(path) for path in sorted(extras))
            raise CompilerVerificationError(f"boundary candidate root contains stale files: {rendered}")
        for artifact in self.artifacts:
            target = candidate_root.joinpath(*artifact.path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(artifact.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()


@dataclass(frozen=True, slots=True)
class BoundaryManifest:
    """Strict frozen-boundary manifest with no executable configuration."""

    schema_version: int
    baseline_revision: str
    source_root: PurePosixPath
    artifact_root: PurePosixPath
    candidate_root: PurePosixPath
    formats: BoundaryFormats
    capabilities: tuple[BoundaryCapability, ...]
    fixtures: tuple[BoundaryFixture, ...]
    records: tuple[BoundaryRecord, ...]
    equalities: tuple[BoundaryEquality, ...]

    _ROOT_KEYS = frozenset(
        {
            "schema_version",
            "baseline_revision",
            "source_root",
            "artifact_root",
            "candidate_root",
            "formats",
            "capabilities",
            "fixtures",
            "records",
            "equalities",
        }
    )
    _FORMAT_KEYS = frozenset({"ast", "ir", "status"})
    _CAPABILITY_KEYS = frozenset({"id", "compiler", "boundary", "portability", "channels"})
    _FIXTURE_KEYS = frozenset({"id", "kind", "entry", "files", "capabilities"})
    _SOURCE_FILE_KEYS = frozenset({"path", "source"})
    _RECORD_REQUIRED_KEYS = frozenset(
        {
            "id",
            "fixture",
            "capability",
            "compiler",
            "boundary",
            "channel",
            "baseline_path",
            "baseline_sha256",
        }
    )
    _RECORD_ACCEPTED_KEYS = frozenset({"accepted_path", "accepted_sha256", "reason", "regressions"})
    _EQUALITY_KEYS = frozenset({"id", "left", "right"})
    _COMPILERS = frozenset({"python", "btrc", "shared", "bootstrap"})
    _BOUNDARIES = frozenset(
        {
            "tokens",
            "ast",
            "raw-ir",
            "optimized-ir",
            "c",
            "diagnostics",
            "runtime-helper-source",
            "runtime-helper-metadata",
            "runtime-helper-order",
            "behavior-gcc",
            "behavior-clang",
            "bootstrap-fixed-point",
        }
    )
    _KINDS = frozenset({"source", "runtime", "bootstrap"})
    _PORTABILITY = frozenset({"portable", "observed"})
    _IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
    _CHANNEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
    _REVISION = re.compile(r"[0-9a-f]{40}\Z")
    _SHA256 = re.compile(r"[0-9a-f]{64}\Z")

    @classmethod
    def load(cls, manifest_path: Path) -> BoundaryManifest:
        """Load one manifest, rejecting every unknown or incomplete field."""

        try:
            raw = manifest_path.read_bytes()
            if b"\x00" in raw or b"\r" in raw:
                raise CompilerVerificationError("boundary manifest must be NUL-free UTF-8 with LF endings")
            document = tomllib.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise CompilerVerificationError(f"cannot read boundary manifest {manifest_path}: {error}") from error
        cls._require_keys(document, cls._ROOT_KEYS, "boundary manifest")
        schema_version = cls._integer(document, "schema_version", "boundary manifest")
        if schema_version != 1:
            raise CompilerVerificationError(f"unsupported boundary manifest schema version: {schema_version}")
        revision = cls._string(document, "baseline_revision", "boundary manifest")
        if not cls._REVISION.fullmatch(revision):
            raise CompilerVerificationError("boundary manifest baseline_revision must be a full lowercase commit id")
        source_root = cls._path(document, "source_root", "boundary manifest")
        artifact_root = cls._path(document, "artifact_root", "boundary manifest")
        candidate_root = cls._path(document, "candidate_root", "boundary manifest")
        if candidate_root.parts[0] != "build":
            raise CompilerVerificationError("boundary candidate_root must be beneath build/")
        formats_table = cls._table(document, "formats", "boundary manifest")
        cls._require_keys(formats_table, cls._FORMAT_KEYS, "boundary manifest.formats")
        formats = BoundaryFormats(
            ast=cls._string(formats_table, "ast", "boundary manifest.formats"),
            ir=cls._string(formats_table, "ir", "boundary manifest.formats"),
            status=cls._string(formats_table, "status", "boundary manifest.formats"),
        )
        if formats.ast != "selfhost-canonical-v1" or formats.ir != "btrc-ir-v1":
            raise CompilerVerificationError(f"unsupported boundary formats: ast={formats.ast}, ir={formats.ir}")
        if formats.status != "signed-decimal-lf-v1":
            raise CompilerVerificationError(f"unsupported boundary status format: {formats.status}")
        capabilities = cls._capabilities(document.get("capabilities"))
        fixtures = cls._fixtures(document.get("fixtures"), capabilities)
        records = cls._records(document.get("records"), capabilities, fixtures)
        equalities = cls._equalities(document.get("equalities"), records)
        manifest = cls(
            schema_version=schema_version,
            baseline_revision=revision,
            source_root=source_root,
            artifact_root=artifact_root,
            candidate_root=candidate_root,
            formats=formats,
            capabilities=capabilities,
            fixtures=fixtures,
            records=records,
            equalities=equalities,
        )
        manifest._validate_coverage()
        return manifest

    @classmethod
    def _capabilities(cls, values: object) -> tuple[BoundaryCapability, ...]:
        tables = cls._table_array(values, "boundary manifest.capabilities")
        capabilities = []
        for index, table in enumerate(tables):
            context = f"boundary manifest.capabilities[{index}]"
            cls._require_keys(table, cls._CAPABILITY_KEYS, context)
            compiler = cls._string(table, "compiler", context)
            boundary = cls._string(table, "boundary", context)
            portability = cls._string(table, "portability", context)
            channels = cls._strings(table, "channels", context)
            if compiler not in cls._COMPILERS:
                raise CompilerVerificationError(f"unsupported boundary compiler at {context}: {compiler}")
            if boundary not in cls._BOUNDARIES:
                raise CompilerVerificationError(f"unsupported boundary at {context}: {boundary}")
            if not cls._supports_capability(compiler, boundary):
                raise CompilerVerificationError(f"unsupported compiler/boundary capability at {context}")
            if portability not in cls._PORTABILITY:
                raise CompilerVerificationError(f"unsupported portability at {context}: {portability}")
            if not channels or len(channels) != len(set(channels)):
                raise CompilerVerificationError(f"{context}.channels must be non-empty and unique")
            if any(not cls._CHANNEL.fullmatch(channel) for channel in channels):
                raise CompilerVerificationError(f"{context}.channels contains an invalid channel")
            has_observation = "observation" in channels
            if has_observation != (portability == "observed"):
                raise CompilerVerificationError(f"{context} observed capabilities alone require an observation channel")
            requires_observation = boundary in {"behavior-gcc", "behavior-clang", "bootstrap-fixed-point"}
            if requires_observation != (portability == "observed"):
                raise CompilerVerificationError(f"{context} executable capabilities must be observed")
            capabilities.append(
                BoundaryCapability(
                    id=cls._manifest_id(table, "id", context),
                    compiler=compiler,
                    boundary=boundary,
                    portability=portability,
                    channels=channels,
                )
            )
        cls._require_unique((capability.id for capability in capabilities), "boundary capability ids")
        return tuple(capabilities)

    @staticmethod
    def _supports_capability(compiler: str, boundary: str) -> bool:
        if compiler == "python":
            return boundary in {
                "tokens",
                "ast",
                "raw-ir",
                "optimized-ir",
                "c",
                "diagnostics",
                "behavior-gcc",
                "behavior-clang",
            }
        if compiler == "btrc":
            return boundary in {
                "tokens",
                "ast",
                "c",
                "diagnostics",
                "behavior-gcc",
                "behavior-clang",
            }
        if compiler == "shared":
            return boundary in {
                "runtime-helper-source",
                "runtime-helper-metadata",
                "runtime-helper-order",
            }
        return compiler == "bootstrap" and boundary == "bootstrap-fixed-point"

    @classmethod
    def _fixtures(
        cls,
        values: object,
        capabilities: tuple[BoundaryCapability, ...],
    ) -> tuple[BoundaryFixture, ...]:
        tables = cls._table_array(values, "boundary manifest.fixtures")
        capability_by_id = {capability.id: capability for capability in capabilities}
        capability_ids = set(capability_by_id)
        fixtures = []
        for index, table in enumerate(tables):
            context = f"boundary manifest.fixtures[{index}]"
            cls._require_keys(table, cls._FIXTURE_KEYS, context)
            kind = cls._string(table, "kind", context)
            if kind not in cls._KINDS:
                raise CompilerVerificationError(f"unsupported fixture kind at {context}: {kind}")
            entry_text = cls._string(table, "entry", context)
            entry = cls._relative_path(entry_text, f"{context}.entry") if entry_text else None
            files = cls._source_files(table.get("files"), context)
            fixture_capabilities = cls._strings(table, "capabilities", context)
            if not fixture_capabilities or len(fixture_capabilities) != len(set(fixture_capabilities)):
                raise CompilerVerificationError(f"{context}.capabilities must be non-empty and unique")
            unknown = set(fixture_capabilities) - capability_ids
            if unknown:
                raise CompilerVerificationError(f"{context} names unknown capabilities: {', '.join(sorted(unknown))}")
            mismatched = [
                capability_id
                for capability_id in fixture_capabilities
                if cls._capability_kind(capability_by_id[capability_id]) != kind
            ]
            if mismatched:
                raise CompilerVerificationError(
                    f"{context} kind {kind} cannot own capabilities: {', '.join(sorted(mismatched))}"
                )
            if kind == "source":
                if entry is None or not files or entry not in {source.path for source in files}:
                    raise CompilerVerificationError(f"{context} source fixture entry must name one staged file")
            elif entry is not None or files:
                raise CompilerVerificationError(f"{context} non-source fixture cannot declare entry/files")
            fixtures.append(
                BoundaryFixture(
                    id=cls._manifest_id(table, "id", context),
                    kind=kind,
                    entry=entry,
                    files=files,
                    capabilities=fixture_capabilities,
                )
            )
        cls._require_unique((fixture.id for fixture in fixtures), "boundary fixture ids")
        return tuple(fixtures)

    @staticmethod
    def _capability_kind(capability: BoundaryCapability) -> str:
        if capability.compiler == "shared":
            return "runtime"
        if capability.compiler == "bootstrap":
            return "bootstrap"
        return "source"

    @classmethod
    def _source_files(cls, values: object, context: str) -> tuple[BoundarySourceFile, ...]:
        tables = cls._table_array(values, f"{context}.files", allow_empty=True)
        files = []
        for index, table in enumerate(tables):
            file_context = f"{context}.files[{index}]"
            cls._require_keys(table, cls._SOURCE_FILE_KEYS, file_context)
            path = cls._path(table, "path", file_context)
            source = cls._path(table, "source", file_context)
            if path.suffix != ".btrc" or source.suffix != ".source":
                raise CompilerVerificationError(f"{file_context} must stage .source as .btrc")
            files.append(BoundarySourceFile(path=path, source=source))
        cls._require_unique((source.path for source in files), f"{context} staged paths")
        cls._require_unique((source.source for source in files), f"{context} source paths")
        return tuple(files)

    @classmethod
    def _records(
        cls,
        values: object,
        capabilities: tuple[BoundaryCapability, ...],
        fixtures: tuple[BoundaryFixture, ...],
    ) -> tuple[BoundaryRecord, ...]:
        tables = cls._table_array(values, "boundary manifest.records")
        capability_by_id = {capability.id: capability for capability in capabilities}
        fixture_by_id = {fixture.id: fixture for fixture in fixtures}
        records = []
        for index, table in enumerate(tables):
            context = f"boundary manifest.records[{index}]"
            keys = set(table)
            allowed = cls._RECORD_REQUIRED_KEYS | cls._RECORD_ACCEPTED_KEYS
            missing = cls._RECORD_REQUIRED_KEYS - keys
            unknown = keys - allowed
            if missing or unknown:
                cls._raise_key_error(context, missing, unknown)
            fixture_id = cls._string(table, "fixture", context)
            fixture = fixture_by_id.get(fixture_id)
            if fixture is None:
                raise CompilerVerificationError(f"{context} names unknown fixture: {fixture_id}")
            capability_id = cls._string(table, "capability", context)
            capability = capability_by_id.get(capability_id)
            if capability is None or capability.id not in fixture.capabilities:
                raise CompilerVerificationError(f"{context} is not declared by fixture capabilities")
            compiler = cls._string(table, "compiler", context)
            boundary = cls._string(table, "boundary", context)
            if (compiler, boundary) != (capability.compiler, capability.boundary):
                raise CompilerVerificationError(f"{context} compiler/boundary differ from {capability.id}")
            channel = cls._string(table, "channel", context)
            if channel not in capability.channels:
                raise CompilerVerificationError(f"{context}.channel is not declared by {capability.id}: {channel}")
            baseline_path = cls._path(table, "baseline_path", context)
            if not baseline_path.parts or baseline_path.parts[0] != "baseline":
                raise CompilerVerificationError(f"{context}.baseline_path must be beneath baseline/")
            baseline_sha256 = cls._digest(table, "baseline_sha256", context)
            accepted_present = keys & cls._RECORD_ACCEPTED_KEYS
            accepted_path = None
            accepted_sha256 = None
            reason = None
            regressions: tuple[str, ...] = ()
            if accepted_present:
                if accepted_present != cls._RECORD_ACCEPTED_KEYS:
                    missing_accepted = cls._RECORD_ACCEPTED_KEYS - accepted_present
                    raise CompilerVerificationError(
                        f"{context} accepted delta is incomplete: {', '.join(sorted(missing_accepted))}"
                    )
                accepted_path = cls._path(table, "accepted_path", context)
                if not accepted_path.parts or accepted_path.parts[0] != "accepted":
                    raise CompilerVerificationError(f"{context}.accepted_path must be beneath accepted/")
                accepted_sha256 = cls._digest(table, "accepted_sha256", context)
                reason = cls._string(table, "reason", context).strip()
                regressions = cls._strings(table, "regressions", context)
                if not reason or not regressions:
                    raise CompilerVerificationError(f"{context} accepted delta requires reason and regressions")
            records.append(
                BoundaryRecord(
                    id=cls._manifest_id(table, "id", context),
                    fixture=fixture_id,
                    capability=capability_id,
                    compiler=compiler,
                    boundary=boundary,
                    channel=channel,
                    baseline_path=baseline_path,
                    baseline_sha256=baseline_sha256,
                    accepted_path=accepted_path,
                    accepted_sha256=accepted_sha256,
                    reason=reason,
                    regressions=regressions,
                )
            )
        cls._require_unique((record.id for record in records), "boundary record ids")
        cls._require_unique(
            ((record.fixture, record.capability, record.channel) for record in records),
            "boundary record coordinates",
        )
        cls._require_unique((record.baseline_path for record in records), "baseline artifact paths")
        cls._require_unique(
            (record.accepted_path for record in records if record.accepted_path is not None),
            "accepted artifact paths",
        )
        return tuple(records)

    @classmethod
    def _equalities(
        cls,
        values: object,
        records: tuple[BoundaryRecord, ...],
    ) -> tuple[BoundaryEquality, ...]:
        tables = cls._table_array(values, "boundary manifest.equalities", allow_empty=True)
        record_ids = {record.id for record in records}
        equalities = []
        for index, table in enumerate(tables):
            context = f"boundary manifest.equalities[{index}]"
            cls._require_keys(table, cls._EQUALITY_KEYS, context)
            left = cls._string(table, "left", context)
            right = cls._string(table, "right", context)
            if left == right or left not in record_ids or right not in record_ids:
                raise CompilerVerificationError(f"{context} must reference two distinct boundary records")
            equalities.append(BoundaryEquality(id=cls._manifest_id(table, "id", context), left=left, right=right))
        cls._require_unique((equality.id for equality in equalities), "boundary equality ids")
        cls._require_unique(
            ((equality.left, equality.right) for equality in equalities),
            "boundary equality pairs",
        )
        return tuple(equalities)

    def _validate_coverage(self) -> None:
        capabilities = {capability.id: capability for capability in self.capabilities}
        declared_capabilities = {capability_id for fixture in self.fixtures for capability_id in fixture.capabilities}
        unused_capabilities = set(capabilities) - declared_capabilities
        if unused_capabilities:
            raise CompilerVerificationError(
                "boundary capabilities have no fixture records: " + ", ".join(sorted(unused_capabilities))
            )
        records_by_capability: dict[tuple[str, str], set[str]] = {}
        for record in self.records:
            records_by_capability.setdefault((record.fixture, record.capability), set()).add(record.channel)
        for fixture in self.fixtures:
            for capability_id in fixture.capabilities:
                capability = capabilities[capability_id]
                actual = records_by_capability.get((fixture.id, capability_id), set())
                expected = set(capability.channels)
                if actual != expected:
                    missing = ", ".join(sorted(expected - actual)) or "none"
                    extra = ", ".join(sorted(actual - expected)) or "none"
                    raise CompilerVerificationError(
                        f"fixture {fixture.id} capability {capability_id} record coverage differs "
                        f"(missing: {missing}; extra: {extra})"
                    )

    def verify_tracked_inputs(self, repository_root: Path) -> None:
        """Validate fixture sources, artifact hashes, deltas, regressions, and orphans."""

        self.verify_fixture_sources(repository_root)
        referenced_artifacts = {record.baseline_path for record in self.records}
        referenced_artifacts.update(record.accepted_path for record in self.records if record.accepted_path is not None)
        artifact_root = self._repository_path(repository_root, self.artifact_root)
        for record in self.records:
            self._verify_artifact(
                artifact_root,
                record.baseline_path,
                record.baseline_sha256,
                record.id,
                record.channel,
            )
            if record.accepted_path is not None and record.accepted_sha256 is not None:
                self._verify_artifact(
                    artifact_root,
                    record.accepted_path,
                    record.accepted_sha256,
                    record.id,
                    record.channel,
                )
                if record.accepted_sha256 == record.baseline_sha256:
                    raise CompilerVerificationError(f"boundary record {record.id} has a redundant accepted delta")
                for regression in record.regressions:
                    test_path = regression.split("::", 1)[0]
                    if not test_path.startswith("src/tests/") or not (repository_root / test_path).is_file():
                        raise CompilerVerificationError(
                            f"boundary record {record.id} names missing regression: {regression}"
                        )
        if artifact_root.exists():
            actual_artifacts = {
                PurePosixPath(path.relative_to(artifact_root).as_posix())
                for path in artifact_root.rglob("*")
                if path.is_file()
            }
            if actual_artifacts != referenced_artifacts:
                raise CompilerVerificationError(
                    self._orphan_message("boundary artifacts", referenced_artifacts, actual_artifacts)
                )
        self._validate_runtime_channel_universe(repository_root)

    def verify_fixture_sources(self, repository_root: Path) -> None:
        """Validate the complete tracked .source fixture set without requiring snapshots."""

        source_paths = {source.source for fixture in self.fixtures for source in fixture.files}
        source_root = self._repository_path(repository_root, self.source_root)
        for source_path in source_paths:
            target = source_root.joinpath(*source_path.parts)
            if not target.is_file():
                raise CompilerVerificationError(f"missing boundary fixture source: {target}")
        if source_root.exists():
            actual_sources = {
                PurePosixPath(path.relative_to(source_root).as_posix())
                for path in source_root.rglob("*")
                if path.is_file()
            }
            if actual_sources != source_paths:
                raise CompilerVerificationError(
                    self._orphan_message("boundary fixture sources", source_paths, actual_sources)
                )

    def _validate_runtime_channel_universe(self, repository_root: Path) -> None:
        runtime_capabilities = {
            capability.boundary: capability for capability in self.capabilities if capability.compiler == "shared"
        }
        if not runtime_capabilities:
            return
        manifest_path = repository_root / "src/runtime/c/manifest.toml"
        try:
            current = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise CompilerVerificationError(f"cannot validate runtime boundary channel universe: {error}") from error
        current_names = {
            helper["name"]
            for helper in current.get("helpers", ())
            if isinstance(helper, dict) and isinstance(helper.get("name"), str)
        }
        baseline_names = set()
        order_channels = set()
        artifact_root = self._repository_path(repository_root, self.artifact_root)
        for record in self.records:
            if record.boundary == "runtime-helper-order":
                order_channels.add(record.channel)
                try:
                    order = artifact_root.joinpath(*record.baseline_path.parts).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as error:
                    raise CompilerVerificationError(
                        f"cannot read baseline runtime order {record.id}: {error}"
                    ) from error
                names = order.splitlines()
                if not names or len(names) != len(set(names)) or any(not name for name in names):
                    raise CompilerVerificationError(
                        f"baseline runtime order is not a unique non-empty sequence: {record.id}"
                    )
                baseline_names.update(names)
        if order_channels != {"python", "btrc"}:
            raise CompilerVerificationError("baseline runtime helper order must declare Python and btrc sequences")
        baseline_row_names = set()
        for record in self.records:
            if record.boundary != "runtime-helper-metadata" or not record.channel.startswith("helper."):
                continue
            try:
                row = json.loads(artifact_root.joinpath(*record.baseline_path.parts).read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise CompilerVerificationError(f"cannot read baseline runtime row {record.id}: {error}") from error
            name = record.channel.removeprefix("helper.")
            if row is not None:
                if not isinstance(row, dict) or row.get("name") != name:
                    raise CompilerVerificationError(f"baseline runtime row has wrong helper identity: {record.id}")
                baseline_row_names.add(name)
        if baseline_row_names != baseline_names:
            raise CompilerVerificationError(
                self._orphan_message("baseline runtime helper rows", baseline_names, baseline_row_names)
            )
        helper_names = current_names | baseline_names
        assets = {
            "asset.btrc_rt_h",
            "asset.collections_c",
            "asset.core_c",
            "asset.cycles_c",
            "asset.gpu_c",
            "asset.mutex_c",
            "asset.process_c",
            "asset.strings_c",
            "asset.threads_c",
            "asset.trycatch_c",
        }
        expected = {
            "runtime-helper-source": assets,
            "runtime-helper-metadata": {"manifest", *(f"helper.{name}" for name in helper_names)},
            "runtime-helper-order": {"python", "btrc"},
        }
        for boundary, capability in runtime_capabilities.items():
            actual = set(capability.channels)
            required = expected[boundary]
            if actual != required:
                raise CompilerVerificationError(
                    self._orphan_message(f"runtime channels for {capability.id}", required, actual)
                )

    def check_candidate(
        self,
        repository_root: Path,
        candidate_root: Path | None = None,
        *,
        require_observed: bool = False,
    ) -> BoundaryCheckReport:
        """Compare one candidate without changing tracked or candidate bytes."""

        self.verify_tracked_inputs(repository_root)
        root = candidate_root or self._repository_path(repository_root, self.candidate_root)
        expected_candidates = {record.candidate_path for record in self.records}
        actual_candidates = (
            {PurePosixPath(path.relative_to(root).as_posix()) for path in root.rglob("*") if path.is_file()}
            if root.exists()
            else set()
        )
        if actual_candidates != expected_candidates:
            raise CompilerVerificationError(
                self._orphan_message("boundary candidate records", expected_candidates, actual_candidates)
            )
        records_by_id = {record.id: record for record in self.records}
        skipped: set[tuple[str, str]] = set()
        failures: list[str] = []
        for fixture in self.fixtures:
            for capability_id in fixture.capabilities:
                capability = next(item for item in self.capabilities if item.id == capability_id)
                if not capability.observed:
                    continue
                observation = next(
                    record
                    for record in self.records
                    if record.fixture == fixture.id
                    and record.capability == capability.id
                    and record.channel == "observation"
                )
                actual = self._candidate_bytes(root, observation)
                expected = self._artifact_bytes(repository_root, observation)
                if actual != expected:
                    key = (fixture.id, capability.id)
                    skipped.add(key)
                    if require_observed:
                        failures.append(f"{observation.id}: incompatible capability observation")
        checked = 0
        for record in self.records:
            key = (record.fixture, record.capability)
            if key in skipped:
                continue
            actual = self._candidate_bytes(root, record)
            self._validate_status(record, actual, "candidate")
            expected = self._artifact_bytes(repository_root, record)
            if actual != expected:
                failures.append(self._difference_message(record, expected, actual))
            checked += 1
        for equality in self.equalities:
            left = records_by_id[equality.left]
            right = records_by_id[equality.right]
            left_key = (left.fixture, left.capability)
            right_key = (right.fixture, right.capability)
            if left_key in skipped or right_key in skipped:
                continue
            if self._candidate_bytes(root, left) != self._candidate_bytes(root, right):
                failures.append(f"{equality.id}: {equality.left} != {equality.right}")
        if failures:
            raise CompilerVerificationError("boundary candidate differs:\n  " + "\n  ".join(failures))
        skipped_ids = tuple(sorted(capability + "@" + fixture for fixture, capability in skipped))
        return BoundaryCheckReport(checked_records=checked, skipped_capabilities=skipped_ids)

    @classmethod
    def _difference_message(cls, record: BoundaryRecord, expected: bytes, actual: bytes) -> str:
        if record.boundary == "runtime-helper-metadata":
            try:
                expected_value = json.loads(expected)
                actual_value = json.loads(actual)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            else:
                fields = cls._difference_fields(expected_value, actual_value)
                if fields:
                    return f"{record.id}: metadata fields differ: {', '.join(fields)}"
        return f"{record.id}: expected {record.expected_sha256}, got {hashlib.sha256(actual).hexdigest()}"

    @classmethod
    def _difference_fields(cls, expected: object, actual: object, prefix: str = "") -> tuple[str, ...]:
        if isinstance(expected, dict) and isinstance(actual, dict):
            differences = []
            for key in sorted(set(expected) | set(actual)):
                path = f"{prefix}.{key}" if prefix else key
                if key not in expected or key not in actual:
                    differences.append(path)
                    continue
                differences.extend(cls._difference_fields(expected[key], actual[key], path))
            return tuple(differences)
        return () if expected == actual else (prefix or "$",)

    def _artifact_bytes(self, repository_root: Path, record: BoundaryRecord) -> bytes:
        root = self._repository_path(repository_root, self.artifact_root)
        return root.joinpath(*record.expected_path.parts).read_bytes()

    @staticmethod
    def _candidate_bytes(candidate_root: Path, record: BoundaryRecord) -> bytes:
        return candidate_root.joinpath(*record.candidate_path.parts).read_bytes()

    @classmethod
    def _verify_artifact(
        cls,
        root: Path,
        path: PurePosixPath,
        expected: str,
        record_id: str,
        channel: str,
    ) -> None:
        target = root.joinpath(*path.parts)
        if not target.is_file():
            raise CompilerVerificationError(f"missing boundary artifact for {record_id}: {target}")
        content = target.read_bytes()
        cls._validate_status_id(record_id, channel, content, "tracked")
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise CompilerVerificationError(
                f"boundary artifact hash differs for {record_id}: expected {expected}, got {actual}"
            )

    @classmethod
    def _table_array(cls, value: object, context: str, *, allow_empty: bool = False) -> list[dict]:
        if (
            not isinstance(value, list)
            or (not value and not allow_empty)
            or any(not isinstance(item, dict) for item in value)
        ):
            qualifier = "an array of tables" if allow_empty else "a non-empty array of tables"
            raise CompilerVerificationError(f"{context} must be {qualifier}")
        return value

    @classmethod
    def _require_keys(cls, table: dict, expected: frozenset[str], context: str) -> None:
        keys = set(table)
        missing = expected - keys
        unknown = keys - expected
        if missing or unknown:
            cls._raise_key_error(context, missing, unknown)

    @staticmethod
    def _raise_key_error(context: str, missing: set[str], unknown: set[str]) -> None:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise CompilerVerificationError(f"{context} keys differ: {'; '.join(details)}")

    @staticmethod
    def _table(table: dict, key: str, context: str) -> dict:
        value = table.get(key)
        if not isinstance(value, dict):
            raise CompilerVerificationError(f"{context}.{key} must be a table")
        return value

    @staticmethod
    def _string(table: dict, key: str, context: str) -> str:
        value = table.get(key)
        if not isinstance(value, str):
            raise CompilerVerificationError(f"{context}.{key} must be a string")
        return value

    @classmethod
    def _manifest_id(cls, table: dict, key: str, context: str) -> str:
        value = cls._string(table, key, context)
        if not cls._IDENTIFIER.fullmatch(value):
            raise CompilerVerificationError(f"{context}.{key} is not a canonical id: {value!r}")
        return value

    @staticmethod
    def _integer(table: dict, key: str, context: str) -> int:
        value = table.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise CompilerVerificationError(f"{context}.{key} must be an integer")
        return value

    @classmethod
    def _path(cls, table: dict, key: str, context: str) -> PurePosixPath:
        return cls._relative_path(cls._string(table, key, context), f"{context}.{key}")

    @staticmethod
    def _relative_path(value: str, context: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "." in path.parts or path.as_posix() != value:
            raise CompilerVerificationError(f"{context} must be a normalized relative path")
        return path

    @classmethod
    def _digest(cls, table: dict, key: str, context: str) -> str:
        value = cls._string(table, key, context)
        if not cls._SHA256.fullmatch(value):
            raise CompilerVerificationError(f"{context}.{key} must be a lowercase SHA-256")
        return value

    @staticmethod
    def _strings(table: dict, key: str, context: str) -> tuple[str, ...]:
        value = table.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise CompilerVerificationError(f"{context}.{key} must be an array of strings")
        return tuple(value)

    @staticmethod
    def _require_unique(values, context: str) -> None:
        entries = list(values)
        if len(entries) != len(set(entries)):
            raise CompilerVerificationError(f"{context} must be unique")

    @staticmethod
    def _repository_path(repository_root: Path, path: PurePosixPath) -> Path:
        return repository_root.joinpath(*path.parts)

    @staticmethod
    def _orphan_message(context: str, expected: set, actual: set) -> str:
        missing = ", ".join(str(value) for value in sorted(expected - actual)) or "none"
        extra = ", ".join(str(value) for value in sorted(actual - expected)) or "none"
        return f"{context} differ (missing: {missing}; extra: {extra})"

    @classmethod
    def _validate_status(cls, record: BoundaryRecord, content: bytes, source: str) -> None:
        if record.channel == "status" or record.channel.endswith("-status"):
            cls._validate_status_id(record.id, record.channel, content, source)

    @staticmethod
    def _validate_status_id(record_id: str, channel: str, content: bytes, source: str) -> None:
        if (channel == "status" or channel.endswith("-status")) and not re.fullmatch(
            rb"(?:0|-?[1-9][0-9]*)\n", content
        ):
            raise CompilerVerificationError(f"boundary {source} status is not signed-decimal-lf-v1: {record_id}")


@dataclass(frozen=True, slots=True)
class _SelfhostToolBuild:
    """A usable self-host boundary tool or its exact failed build process."""

    binary: Path | None
    failure: subprocess.CompletedProcess[bytes] | None


class _BoundaryCaptureSession:
    """Materialize declared candidate channels from one repository snapshot."""

    _PYTHON_FLAGS: ClassVar[dict[str, str]] = {
        "tokens": "--emit-tokens",
        "ast": "--emit-ast",
        "raw-ir": "--emit-ir",
        "optimized-ir": "--emit-optimized-ir",
    }
    _SELFHOST_TOOLS: ClassVar[dict[str, str]] = {
        "tokens": "src/compiler/btrc/tools/lex_main.btrc",
        "ast": "src/compiler/btrc/tools/parse_main.btrc",
        "c": "src/compiler/btrc/btrcc_main.btrc",
        "diagnostics": "src/compiler/btrc/btrcc_main.btrc",
    }

    def __init__(
        self,
        manifest: BoundaryManifest,
        fixture_repository: Path,
        execution_repository: Path,
        observation_expectations: dict[tuple[str, str], bytes] | None = None,
    ) -> None:
        self.manifest = manifest
        self.fixture_repository = fixture_repository
        self.execution_repository = execution_repository
        self.workspace_relative = manifest.candidate_root.parent / "workspace"
        self.workspace = execution_repository.joinpath(*self.workspace_relative.parts)
        self.environment = dict(os.environ)
        self.environment.update(
            {
                "BTRC_CACHE_DIR": str(self.workspace / "cache"),
                "BTRC_HOME": str(execution_repository / "src"),
                "LANG": "C",
                "LC_ALL": "C",
                "PYTHONHASHSEED": "0",
                "PYTHONPATH": str(execution_repository),
                "TZ": "UTC",
            }
        )
        self._tools: dict[str, _SelfhostToolBuild] = {}
        self._generated_c: dict[tuple[str, str], bytes] = {}
        self._observation_expectations = observation_expectations

    def capture(self) -> BoundaryCandidateSet:
        records_by_coordinate = {
            (record.fixture, record.capability, record.channel): record for record in self.manifest.records
        }
        content_by_record: dict[str, bytes] = {}
        capabilities = {capability.id: capability for capability in self.manifest.capabilities}
        for fixture in self.manifest.fixtures:
            for capability_id in fixture.capabilities:
                capability = capabilities[capability_id]
                channels = self._capture_compatible_capability(fixture, capability)
                if set(channels) != set(capability.channels):
                    missing = ", ".join(sorted(set(capability.channels) - set(channels))) or "none"
                    extra = ", ".join(sorted(set(channels) - set(capability.channels))) or "none"
                    raise CompilerVerificationError(
                        f"candidate producer {capability.id} channels differ (missing: {missing}; extra: {extra})"
                    )
                for channel, content in channels.items():
                    record = records_by_coordinate[(fixture.id, capability.id, channel)]
                    content_by_record[record.id] = content
        if set(content_by_record) != {record.id for record in self.manifest.records}:
            raise CompilerVerificationError("candidate capture did not materialize every manifest record")
        return BoundaryCandidateSet(
            tuple(
                BoundaryCandidateArtifact(record.candidate_path, content_by_record[record.id])
                for record in self.manifest.records
            )
        )

    def _capture_compatible_capability(
        self,
        fixture: BoundaryFixture,
        capability: BoundaryCapability,
    ) -> dict[str, bytes]:
        if not capability.observed or self._observation_expectations is None:
            return self._capture_capability(fixture, capability)
        observation = self._capability_observation(capability)
        expected = self._observation_expectations[(fixture.id, capability.id)]
        if observation == expected:
            return self._capture_capability(fixture, capability)
        channels = {channel: b"" for channel in capability.channels}
        channels["observation"] = observation
        for channel in capability.channels:
            if channel == "status" or channel.endswith("-status"):
                channels[channel] = self._status_bytes(-1)
        return channels

    def _capture_capability(
        self,
        fixture: BoundaryFixture,
        capability: BoundaryCapability,
    ) -> dict[str, bytes]:
        if capability.compiler == "python" and capability.boundary in {
            *self._PYTHON_FLAGS,
            "c",
            "diagnostics",
        }:
            return self._python_boundary(fixture, capability)
        if capability.compiler == "btrc" and capability.boundary in self._SELFHOST_TOOLS:
            return self._selfhost_boundary(fixture, capability)
        if capability.compiler == "shared" and capability.boundary.startswith("runtime-helper-"):
            return self._runtime_boundary(capability)
        if capability.compiler in {"python", "btrc"} and capability.boundary in {
            "behavior-gcc",
            "behavior-clang",
        }:
            return self._behavior_boundary(fixture, capability)
        if capability.compiler == "bootstrap" and capability.boundary == "bootstrap-fixed-point":
            return self._bootstrap_boundary(capability)
        raise CompilerVerificationError(
            f"candidate capture does not implement declared capability {capability.id} "
            f"({capability.compiler}/{capability.boundary})"
        )

    def _python_boundary(
        self,
        fixture: BoundaryFixture,
        capability: BoundaryCapability,
    ) -> dict[str, bytes]:
        entry = self._stage_fixture(fixture)
        command = (
            [sys.executable, "-m", "tools.compiler_codegen.main", "verify-ast", entry]
            if capability.boundary == "ast"
            else [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                entry,
                "--no-stdlib",
                "--no-cache",
            ]
        )
        output_path = self.workspace_relative / "outputs" / fixture.id / "python.c"
        output_target = self.execution_repository.joinpath(*output_path.parts)
        if capability.boundary in self._PYTHON_FLAGS and capability.boundary != "ast":
            command.append(self._PYTHON_FLAGS[capability.boundary])
        elif capability.boundary in {"c", "diagnostics"}:
            output_target.parent.mkdir(parents=True, exist_ok=True)
            output_target.unlink(missing_ok=True)
            command.extend(("-o", output_path.as_posix()))
        result = self._run(command)
        artifact = result.stdout
        if capability.boundary == "c":
            if result.returncode == 0 and not output_target.is_file():
                raise CompilerVerificationError(f"Python C boundary omitted output for fixture {fixture.id}")
            artifact = output_target.read_bytes() if output_target.is_file() else b""
            if result.returncode == 0:
                self._generated_c[(fixture.id, "python")] = artifact
        if capability.boundary == "diagnostics":
            stderr = self._canonical_diagnostics(result.stderr)
            if b"Traceback (most recent call last):" in stderr:
                stderr = b""
            result = subprocess.CompletedProcess(result.args, result.returncode, result.stdout, stderr)
        return self._select_process_channels(capability, result, artifact)

    def _selfhost_boundary(
        self,
        fixture: BoundaryFixture,
        capability: BoundaryCapability,
    ) -> dict[str, bytes]:
        entry = self._stage_fixture(fixture)
        source = self._SELFHOST_TOOLS[capability.boundary]
        tool = self._selfhost_tool(source)
        if tool.failure is not None:
            failure = tool.failure
            if capability.boundary == "diagnostics":
                failure = subprocess.CompletedProcess(failure.args, failure.returncode, failure.stdout, b"")
            return self._select_process_channels(capability, failure, b"")
        if tool.binary is None:
            raise AssertionError("successful self-host boundary tool omitted its binary")
        binary = tool.binary
        command = [str(binary)]
        if capability.boundary in {"c", "diagnostics"}:
            command.append("--no-stdlib")
        command.append(entry)
        result = self._run(command)
        if capability.boundary == "diagnostics":
            result = subprocess.CompletedProcess(
                result.args,
                result.returncode,
                result.stdout,
                self._canonical_diagnostics(result.stderr),
            )
        artifact = result.stdout
        if capability.boundary == "c" and result.returncode == 0:
            self._generated_c[(fixture.id, "btrc")] = artifact
        return self._select_process_channels(capability, result, artifact)

    def _canonical_diagnostics(self, stderr: bytes) -> bytes:
        repository = str(self.execution_repository.resolve())
        prefixes = {repository, repository.replace("\\", "/")}
        canonical = stderr
        for prefix in prefixes:
            encoded = prefix.rstrip("/\\").encode("utf-8")
            canonical = canonical.replace(encoded + b"/", b"$REPOSITORY/")
            canonical = canonical.replace(encoded + b"\\", b"$REPOSITORY/")
        return re.sub(
            rb"\$REPOSITORY/[^\r\n]*?(?=:[0-9]+:[0-9]+(?:\r?\n|$))",
            lambda match: match.group().replace(b"\\", b"/"),
            canonical,
        )

    def _runtime_boundary(self, capability: BoundaryCapability) -> dict[str, bytes]:
        assets = {
            "asset.btrc_rt_h": "btrc_rt.h",
            "asset.collections_c": "collections.c",
            "asset.core_c": "core.c",
            "asset.cycles_c": "cycles.c",
            "asset.gpu_c": "gpu.c",
            "asset.mutex_c": "mutex.c",
            "asset.process_c": "process.c",
            "asset.strings_c": "strings.c",
            "asset.threads_c": "threads.c",
            "asset.trycatch_c": "trycatch.c",
        }
        manifest_metadata, helpers, orders = self._runtime_snapshot()
        channels: dict[str, bytes] = {}
        for channel in capability.channels:
            if capability.boundary == "runtime-helper-source" and channel in assets:
                channels[channel] = (self.execution_repository / "src/runtime/c" / assets[channel]).read_bytes()
                continue
            if capability.boundary == "runtime-helper-metadata" and channel == "manifest":
                channels[channel] = self._canonical_json_line(manifest_metadata)
                continue
            if channel in {"python", "btrc"} and capability.boundary == "runtime-helper-order":
                channels[channel] = ("\n".join(orders[channel]) + "\n").encode("utf-8")
                continue
            parts = channel.split(".")
            if len(parts) != 2 or parts[0] != "helper" or capability.boundary != "runtime-helper-metadata":
                raise CompilerVerificationError(f"unknown runtime boundary channel: {channel}")
            channels[channel] = self._canonical_json_line(helpers.get(parts[1]))
        return channels

    def _runtime_snapshot(
        self,
    ) -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, tuple[str, ...]]]:
        """Read the frozen v1/v3 runtime schema without weakening the production loader."""

        from tools.compiler_codegen.runtime import RuntimeSourceMarker

        root = self.execution_repository / "src/runtime/c"
        manifest_path = root / "manifest.toml"
        try:
            data = manifest_path.read_bytes()
            if b"\x00" in data or b"\r" in data:
                raise CompilerVerificationError("runtime boundary manifest must be NUL-free UTF-8 with LF endings")
            document = tomllib.loads(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise CompilerVerificationError(f"cannot read runtime boundary manifest: {error}") from error
        expected_root = {
            "schema_version",
            "marker_version",
            "freestanding_header",
            "freestanding",
            "runtime_call_features",
            "header_features",
            "helpers",
        }
        if set(document) != expected_root:
            raise CompilerVerificationError(
                BoundaryManifest._orphan_message("runtime boundary manifest keys", expected_root, set(document))
            )
        schema = document["schema_version"]
        marker_version = document["marker_version"]
        if type(schema) is not int or schema not in {1, 3} or marker_version != 1:
            raise CompilerVerificationError(
                f"unsupported frozen runtime manifest versions: schema={schema}, marker={marker_version}"
            )
        freestanding = document["freestanding"]
        if not isinstance(freestanding, dict) or set(freestanding) != {"calls", "objects", "types", "literals"}:
            raise CompilerVerificationError("runtime boundary freestanding table has an unsupported shape")
        call_features = document["runtime_call_features"]
        header_features = document["header_features"]
        if not isinstance(call_features, list) or not isinstance(header_features, list):
            raise CompilerVerificationError("runtime boundary feature tables must be arrays")
        manifest_metadata: dict[str, object] = {
            "call_features": call_features,
            "calls": freestanding["calls"],
            "header": document["freestanding_header"],
            "header_features": header_features,
            "literals": freestanding["literals"],
            "marker_version": marker_version,
            "objects": freestanding["objects"],
            "schema_version": schema,
            "types": freestanding["types"],
        }
        asset_names = (
            "core.c",
            "collections.c",
            "cycles.c",
            "mutex.c",
            "process.c",
            "strings.c",
            "threads.c",
            "trycatch.c",
            "gpu.c",
        )
        source_by_name = {}
        source_asset_by_name = {}
        source_marker = RuntimeSourceMarker()
        for asset in asset_names:
            for section in source_marker.parse(root / asset):
                if section.name in source_by_name:
                    raise CompilerVerificationError(f"duplicate runtime helper source marker: {section.name}")
                source_by_name[section.name] = section.source
                source_asset_by_name[section.name] = asset
        helper_tables = document["helpers"]
        if not isinstance(helper_tables, list) or not helper_tables:
            raise CompilerVerificationError("runtime boundary helpers must be a non-empty array")
        rows: dict[str, dict[str, object]] = {}
        ordered: dict[str, list[tuple[int, str]]] = {"python": [], "btrc": []}
        base_keys = {"name", "category", "asset", "dependencies", "headers", "source_visible", "order"}
        provider_keys = {"provided_types", "provided_objects"}
        for index, helper in enumerate(helper_tables):
            if not isinstance(helper, dict):
                raise CompilerVerificationError(f"runtime boundary helper {index} must be a table")
            required = base_keys
            allowed = base_keys | provider_keys
            if not required <= set(helper) or not set(helper) <= allowed:
                raise CompilerVerificationError(f"runtime boundary helper {index} has an unsupported shape")
            name = helper["name"]
            asset = helper["asset"]
            if not isinstance(name, str) or name in rows or source_asset_by_name.get(name) != asset:
                raise CompilerVerificationError(f"runtime boundary helper {index} has invalid source ownership")
            order = helper["order"]
            if not isinstance(order, dict) or not order or set(order) - {"python", "btrc"}:
                raise CompilerVerificationError(f"runtime boundary helper {name} has invalid order metadata")
            for compiler, position in order.items():
                if type(position) is not int or position < 0:
                    raise CompilerVerificationError(f"runtime boundary helper {name} has invalid {compiler} order")
                ordered[compiler].append((position, name))
            source = source_by_name[name].encode("utf-8")
            rows[name] = {
                "asset": asset,
                "btrc_order": order.get("btrc"),
                "category": helper["category"],
                "dependencies": helper["dependencies"],
                "headers": helper["headers"],
                "name": name,
                "provided_objects": helper.get("provided_objects", []),
                "provided_types": helper.get("provided_types", []),
                "python_order": order.get("python"),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "source_size": len(source),
                "source_visible": helper["source_visible"],
            }
        if set(rows) != set(source_by_name):
            raise CompilerVerificationError("runtime boundary helper rows and source markers differ")
        orders = {}
        for compiler, entries in ordered.items():
            entries.sort()
            if [position for position, _ in entries] != list(range(len(entries))):
                raise CompilerVerificationError(f"runtime boundary {compiler} order is not dense")
            orders[compiler] = tuple(name for _, name in entries)
        return manifest_metadata, rows, orders

    def _behavior_boundary(
        self,
        fixture: BoundaryFixture,
        capability: BoundaryCapability,
    ) -> dict[str, bytes]:
        c_compiler, compiler_command, resolved, flags, observation = self._behavior_observation(capability)
        if resolved is None:
            unavailable = {channel: b"" for channel in capability.channels}
            unavailable["observation"] = observation
            for channel in {"source-status", "compile-status", "status"} & set(capability.channels):
                unavailable[channel] = self._status_bytes(-1)
            return unavailable
        c_source, source_status = self._behavior_c_source(fixture, capability.compiler)
        if c_source is None:
            unavailable = {channel: b"" for channel in capability.channels}
            unavailable.update(
                {
                    "observation": observation,
                    "source-status": self._status_bytes(source_status),
                    "compile-status": self._status_bytes(-1),
                    "status": self._status_bytes(-1),
                }
            )
            return self._select_channels(capability, unavailable)
        source_relative = self.workspace_relative / "behavior" / fixture.id / f"{capability.compiler}.c"
        binary_relative = self.workspace_relative / "behavior" / fixture.id / f"{capability.compiler}-{c_compiler}"
        source_path = self.execution_repository.joinpath(*source_relative.parts)
        binary_path = self.execution_repository.joinpath(*binary_relative.parts)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(c_source)
        compile_result = self._run(
            [
                *compiler_command,
                *flags,
                source_relative.as_posix(),
                "-o",
                binary_relative.as_posix(),
                "-lm",
                "-lpthread",
            ]
        )
        if compile_result.returncode == 0:
            runtime_result = self._run([binary_relative.as_posix()])
        else:
            runtime_result = subprocess.CompletedProcess([str(binary_path)], -1, b"", b"")
        available = {
            "compile-status": self._status_bytes(compile_result.returncode),
            "compile-stderr": compile_result.stderr,
            "compile-stdout": compile_result.stdout,
            "observation": observation,
            "source-status": self._status_bytes(source_status),
            "status": self._status_bytes(runtime_result.returncode),
            "stderr": runtime_result.stderr,
            "stdout": runtime_result.stdout,
        }
        return self._select_channels(capability, available)

    def _behavior_observation(
        self,
        capability: BoundaryCapability,
    ) -> tuple[str, tuple[str, ...], str | None, tuple[str, ...], bytes]:
        c_compiler = "gcc" if capability.boundary == "behavior-gcc" else "clang"
        compiler_command = self._environment_command("BTRC_" + c_compiler.upper(), c_compiler)
        resolved = shutil.which(compiler_command[0]) if compiler_command else None
        flags = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O0")
        return (
            c_compiler,
            compiler_command,
            resolved,
            flags,
            self._toolchain_observation(
                compiler_command,
                resolved,
                flags,
            ),
        )

    def _capability_observation(self, capability: BoundaryCapability) -> bytes:
        if capability.boundary in {"behavior-gcc", "behavior-clang"}:
            return self._behavior_observation(capability)[4]
        if capability.boundary == "bootstrap-fixed-point":
            compiler_command = self._environment_command("BTRC_CC", os.environ.get("CC", "cc"))
            resolved = shutil.which(compiler_command[0]) if compiler_command else None
            flags = tuple(
                shlex.split(
                    os.environ.get(
                        "BTRC_BOOTSTRAP_CFLAGS",
                        "-std=c11 -Wall -Wextra -Werror -pedantic -O2",
                    )
                )
            )
            return self._toolchain_observation(compiler_command, resolved, flags)
        raise CompilerVerificationError(f"capability has no executable observation: {capability.id}")

    def _behavior_c_source(self, fixture: BoundaryFixture, compiler: str) -> tuple[bytes | None, int]:
        key = (fixture.id, compiler)
        if key in self._generated_c:
            return self._generated_c[key], 0
        synthetic = BoundaryCapability(
            id=f"{compiler}.c.synthetic",
            compiler=compiler,
            boundary="c",
            portability="portable",
            channels=("artifact", "status"),
        )
        if compiler == "python":
            channels = self._python_boundary(fixture, synthetic)
        else:
            channels = self._selfhost_boundary(fixture, synthetic)
        status = int(channels["status"].decode("ascii").strip())
        return (channels["artifact"] if status == 0 else None), status

    def _bootstrap_boundary(self, capability: BoundaryCapability) -> dict[str, bytes]:
        """Capture every stage of a three-generation self-host fixed point."""

        compiler_command = self._environment_command("BTRC_CC", os.environ.get("CC", "cc"))
        resolved = shutil.which(compiler_command[0]) if compiler_command else None
        flags = tuple(
            shlex.split(
                os.environ.get(
                    "BTRC_BOOTSTRAP_CFLAGS",
                    "-std=c11 -Wall -Wextra -Werror -pedantic -O2",
                )
            )
        )
        observation = self._toolchain_observation(compiler_command, resolved, flags)
        statuses = {
            "stage1-status": -1,
            "stage1-compile-status": -1,
            "stage2-status": -1,
            "stage2-compile-status": -1,
            "stage3-status": -1,
            "fixed-point-status": -1,
        }
        stage2 = b""
        stage3 = b""
        if resolved is not None:
            root = self.workspace_relative / "bootstrap"
            target_root = self.execution_repository.joinpath(*root.parts)
            target_root.mkdir(parents=True, exist_ok=True)
            compiler_source = "src/compiler/btrc/btrcc_main.btrc"
            c1 = root / "btrcc1.c"
            b1 = root / "btrcc1"
            c2 = root / "btrcc2.c"
            b2 = root / "btrcc2"
            stage1 = self._run(
                [
                    sys.executable,
                    "-m",
                    "src.compiler.python.main",
                    compiler_source,
                    "--strict-imports",
                    "--no-cache",
                    "-o",
                    c1.as_posix(),
                ],
                timeout=1200,
            )
            statuses["stage1-status"] = stage1.returncode
            if stage1.returncode == 0 and self.execution_repository.joinpath(*c1.parts).is_file():
                compiled1 = self._run(
                    [*compiler_command, *flags, c1.as_posix(), "-o", b1.as_posix(), "-lm", "-lpthread"],
                    timeout=1200,
                )
                statuses["stage1-compile-status"] = compiled1.returncode
                if compiled1.returncode == 0:
                    generated2 = self._run(
                        [b1.as_posix(), "--strict-imports", compiler_source],
                        timeout=1200,
                    )
                    statuses["stage2-status"] = generated2.returncode
                    if generated2.returncode == 0:
                        stage2 = generated2.stdout
                        self.execution_repository.joinpath(*c2.parts).write_bytes(stage2)
                        compiled2 = self._run(
                            [
                                *compiler_command,
                                *flags,
                                c2.as_posix(),
                                "-o",
                                b2.as_posix(),
                                "-lm",
                                "-lpthread",
                            ],
                            timeout=1200,
                        )
                        statuses["stage2-compile-status"] = compiled2.returncode
                        if compiled2.returncode == 0:
                            generated3 = self._run(
                                [b2.as_posix(), "--strict-imports", compiler_source],
                                timeout=1200,
                            )
                            statuses["stage3-status"] = generated3.returncode
                            if generated3.returncode == 0:
                                stage3 = generated3.stdout
                                statuses["fixed-point-status"] = int(stage2 != stage3)
        available = {
            "observation": observation,
            "stage2-sha256": (hashlib.sha256(stage2).hexdigest() + "\n").encode("ascii") if stage2 else b"",
            "stage3-sha256": (hashlib.sha256(stage3).hexdigest() + "\n").encode("ascii") if stage3 else b"",
        }
        available.update({channel: self._status_bytes(status) for channel, status in statuses.items()})
        return self._select_channels(capability, available)

    def _stage_fixture(self, fixture: BoundaryFixture) -> str:
        if fixture.kind != "source" or fixture.entry is None:
            raise CompilerVerificationError(f"capability requires a source fixture: {fixture.id}")
        fixture_relative = self.workspace_relative / "sources" / fixture.id
        fixture_target = self.execution_repository.joinpath(*fixture_relative.parts)
        expected = {source.path for source in fixture.files}
        actual = (
            {
                PurePosixPath(path.relative_to(fixture_target).as_posix())
                for path in fixture_target.rglob("*")
                if path.is_file()
            }
            if fixture_target.exists()
            else set()
        )
        extras = actual - expected
        if extras:
            rendered = ", ".join(str(path) for path in sorted(extras))
            raise CompilerVerificationError(f"fixture workspace {fixture.id} contains stale files: {rendered}")
        source_root = self.fixture_repository.joinpath(*self.manifest.source_root.parts)
        for source in fixture.files:
            source_path = source_root.joinpath(*source.source.parts)
            target = fixture_target.joinpath(*source.path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source_path.read_bytes())
        return (fixture_relative / fixture.entry).as_posix()

    def _selfhost_tool(self, source: str) -> _SelfhostToolBuild:
        cached = self._tools.get(source)
        if cached is not None:
            return cached
        name = Path(source).stem
        generated_relative = self.workspace_relative / "tools" / f"{name}.c"
        binary_relative = self.workspace_relative / "tools" / name
        generated = self.execution_repository.joinpath(*generated_relative.parts)
        binary = self.execution_repository.joinpath(*binary_relative.parts)
        generated.parent.mkdir(parents=True, exist_ok=True)
        transpile = self._run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                source,
                "--no-cache",
                "-o",
                generated_relative.as_posix(),
            ],
            timeout=900,
        )
        if transpile.returncode != 0 or not generated.is_file():
            failure = _SelfhostToolBuild(binary=None, failure=transpile)
            self._tools[source] = failure
            return failure
        c_compiler = self._environment_command("BTRC_CC", os.environ.get("CC", "cc"))
        compile_result = self._run(
            [
                *c_compiler,
                "-std=c11",
                "-pedantic-errors",
                generated_relative.as_posix(),
                "-o",
                binary_relative.as_posix(),
                "-lm",
                "-lpthread",
            ],
            timeout=900,
        )
        if compile_result.returncode != 0 or not binary.is_file():
            failure = _SelfhostToolBuild(binary=None, failure=compile_result)
            self._tools[source] = failure
            return failure
        success = _SelfhostToolBuild(binary=binary, failure=None)
        self._tools[source] = success
        return success

    def _toolchain_observation(
        self,
        command: tuple[str, ...],
        resolved: str | None,
        flags: tuple[str, ...],
    ) -> bytes:
        version = self._run([*command, "--version"]) if resolved is not None else None
        executable_digest = None
        if resolved is not None:
            try:
                executable_digest = hashlib.sha256(Path(resolved).resolve().read_bytes()).hexdigest()
            except OSError as error:
                raise CompilerVerificationError(
                    f"cannot fingerprint toolchain executable {command[0]!r}: {error}"
                ) from error
        version_stdout = version.stdout if version is not None else b""
        version_stderr = version.stderr if version is not None else b""
        command_arguments = json.dumps(command[1:], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        value = {
            "command_arguments_sha256": hashlib.sha256(command_arguments).hexdigest(),
            "command_name": Path(command[0]).name,
            "environment": {key: self.environment[key] for key in ("LANG", "LC_ALL", "PYTHONHASHSEED", "TZ")},
            "executable_sha256": executable_digest,
            "flags": list(flags),
            "platform": {
                "machine": platform.machine(),
                "python": platform.python_version(),
                "release": platform.release(),
                "system": platform.system(),
            },
            "schema": 1,
            "version_status": version.returncode if version is not None else None,
            "version_stderr_sha256": hashlib.sha256(version_stderr).hexdigest(),
            "version_stdout_sha256": hashlib.sha256(version_stdout).hexdigest(),
        }
        return self._canonical_json_line(value)

    def _select_process_channels(
        self,
        capability: BoundaryCapability,
        result: subprocess.CompletedProcess[bytes],
        artifact: bytes,
    ) -> dict[str, bytes]:
        return self._select_channels(
            capability,
            {
                "artifact": artifact,
                "status": self._status_bytes(result.returncode),
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )

    @staticmethod
    def _select_channels(
        capability: BoundaryCapability,
        available: dict[str, bytes],
    ) -> dict[str, bytes]:
        missing = set(capability.channels) - set(available)
        if missing:
            raise CompilerVerificationError(
                f"candidate producer {capability.id} cannot capture channels: {', '.join(sorted(missing))}"
            )
        return {channel: available[channel] for channel in capability.channels}

    @staticmethod
    def _status_bytes(status: int) -> bytes:
        return f"{status}\n".encode("ascii")

    @staticmethod
    def _canonical_json_line(value: object) -> bytes:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    @staticmethod
    def _environment_command(name: str, default: str) -> tuple[str, ...]:
        try:
            command = tuple(shlex.split(os.environ.get(name, default)))
        except ValueError as error:
            raise CompilerVerificationError(f"invalid {name} command: {error}") from error
        if not command:
            raise CompilerVerificationError(f"{name} command must not be empty")
        return command

    def _run(
        self,
        command: Sequence[str],
        *,
        timeout: int = 300,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                cwd=self.execution_repository,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CompilerVerificationError(f"could not execute {command[0]!r}: {error}") from error


class CompilerBoundaryVerifier:
    """Own canonical AST dumps and Python/self-hosted lexer comparisons."""

    _SOURCE_DEPENDENCY = re.compile(
        r"^[ \t]*(?:import|#include[ \t]*(?:\"[^\"]*\.btrc\"|<[^>]*\.btrc>))",
        re.MULTILINE,
    )

    def __init__(self, repository_root: Path):
        self._repository_root = repository_root
        self._ast_renderer = AstCanonicalRenderer()

    def canonical_ast(self, source_path: Path) -> bytes:
        """Parse one source file and return its canonical AST bytes."""

        from src.compiler.python.lexer.lexer import Lexer
        from src.compiler.python.parser.parser import Parser

        source = source_path.read_text(encoding="utf-8")
        program = Parser(Lexer(source, source_path.name).tokenize()).parse()
        return (self._ast_renderer.render(program) + "\n").encode("utf-8")

    def boundary_manifest(self, manifest_path: Path | None = None) -> BoundaryManifest:
        """Load the default or explicitly named frozen-boundary manifest."""

        path = manifest_path or Path("src/tests/fixtures/compiler_boundaries/manifest.toml")
        if not path.is_absolute():
            path = self._repository_root / path
        return BoundaryManifest.load(path)

    def capture_boundary_candidate(
        self,
        manifest: BoundaryManifest,
        candidate_root: Path | None = None,
        *,
        revision: str | None = None,
        force_observed: bool = True,
    ) -> BoundaryCaptureReport:
        """Capture build-only bytes, optionally skipping host-incompatible executable records.

        Explicit ``boundary-capture`` calls leave ``force_observed`` enabled and
        intentionally execute every declared producer. Ordinary ``boundary-check``
        disables it so an incompatible observation never launches that producer.
        """

        if not force_observed:
            if revision is not None:
                raise CompilerVerificationError("compatible observed capture is only available for the current tree")
            manifest.verify_tracked_inputs(self._repository_root)
        else:
            manifest.verify_fixture_sources(self._repository_root)
        output_root = candidate_root or self._repository_root.joinpath(*manifest.candidate_root.parts)
        self._require_build_output(output_root)
        if revision is None:
            observations = None
            if not force_observed:
                observations = {
                    (record.fixture, record.capability): manifest._artifact_bytes(self._repository_root, record)
                    for record in manifest.records
                    if record.channel == "observation"
                }
            candidate = _BoundaryCaptureSession(
                manifest,
                self._repository_root,
                self._repository_root,
                observations,
            ).capture()
            revision_label = self._worktree_revision()
        else:
            if revision != manifest.baseline_revision:
                raise CompilerVerificationError(
                    "boundary revision capture is restricted to the manifest's pinned baseline_revision"
                )
            with tempfile.TemporaryDirectory(prefix="btrc-boundary-revision-") as temporary:
                execution_root = Path(temporary) / "repository"
                self._extract_revision(revision, execution_root)
                candidate = _BoundaryCaptureSession(manifest, self._repository_root, execution_root).capture()
            revision_label = revision
        candidate.publish(output_root)
        return BoundaryCaptureReport(
            candidate_root=output_root,
            record_count=len(candidate.artifacts),
            byte_count=candidate.byte_count,
            revision=revision_label,
        )

    def check_boundary_candidate(
        self,
        manifest: BoundaryManifest,
        candidate_root: Path | None = None,
        *,
        require_observed: bool = False,
    ) -> BoundaryCheckReport:
        """Validate one existing candidate without modifying it."""

        root = candidate_root or self._repository_root.joinpath(*manifest.candidate_root.parts)
        self._require_build_output(root)
        return manifest.check_candidate(
            self._repository_root,
            root,
            require_observed=require_observed,
        )

    def _require_build_output(self, output_root: Path) -> None:
        build_root = (self._repository_root / "build").resolve()
        try:
            output_root.resolve().relative_to(build_root)
        except ValueError as error:
            raise CompilerVerificationError(f"boundary candidate output must remain beneath {build_root}") from error

    def _worktree_revision(self) -> str:
        result = self._run(("git", "rev-parse", "HEAD"))
        if result.returncode != 0:
            return "worktree"
        revision = result.stdout.decode("ascii", errors="replace").strip()
        dirty = self._run(("git", "status", "--porcelain", "--untracked-files=no"))
        return revision + ("+dirty" if dirty.stdout else "")

    def _extract_revision(self, revision: str, destination: Path) -> None:
        resolved = self._run(("git", "rev-parse", "--verify", revision + "^{commit}"))
        if resolved.returncode != 0 or resolved.stdout.decode("ascii", errors="replace").strip() != revision:
            raise CompilerVerificationError(f"cannot resolve pinned boundary revision: {revision}")
        destination.mkdir(parents=True)
        archive_path = destination.parent / "repository.tar"
        try:
            with archive_path.open("wb") as stream:
                archived = subprocess.run(
                    ("git", "archive", "--format=tar", revision),
                    cwd=self._repository_root,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            if archived.returncode != 0:
                raise CompilerVerificationError(
                    "cannot archive pinned boundary revision:\n"
                    + archived.stderr.decode("utf-8", errors="replace")[:4000]
                )
            with tarfile.open(archive_path, "r") as archive:
                for member in archive.getmembers():
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                        raise CompilerVerificationError(f"unsafe path in pinned boundary archive: {member.name}")
                    target = destination.joinpath(*path.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        source = archive.extractfile(member)
                        if source is None:
                            raise CompilerVerificationError(
                                f"cannot read pinned boundary archive member: {member.name}"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(source.read())
                        if member.mode & 0o111:
                            target.chmod(0o755)
                    else:
                        raise CompilerVerificationError(f"unsupported pinned boundary archive member: {member.name}")
        finally:
            if archive_path.exists():
                archive_path.unlink()

    def verify_lexer(
        self,
        btrcpy_command: Sequence[str] | None = None,
        c_compiler_command: Sequence[str] | None = None,
    ) -> int:
        """Compare raw token bytes for every self-contained corpus source."""

        btrcpy = tuple(btrcpy_command or self._environment_command("BTRCPY", "python3 -m src.compiler.python.main"))
        c_compiler = tuple(c_compiler_command or self._environment_command("CC", "cc"))
        if not btrcpy or not c_compiler:
            raise CompilerVerificationError("BTRCPY and CC must name non-empty commands")

        with tempfile.TemporaryDirectory(prefix="btrc-lexer-verification-") as temporary:
            workspace = Path(temporary)
            lexer_source = workspace / "lexer.c"
            lexer_binary = workspace / "btrclex"
            self._build_selfhosted_lexer(btrcpy, c_compiler, lexer_source, lexer_binary)
            return self._compare_lexers(btrcpy, lexer_binary)

    def _environment_command(self, name: str, default: str) -> tuple[str, ...]:
        try:
            return tuple(shlex.split(os.environ.get(name, default)))
        except ValueError as error:
            raise CompilerVerificationError(f"invalid {name} command: {error}") from error

    def _build_selfhosted_lexer(
        self,
        btrcpy: Sequence[str],
        c_compiler: Sequence[str],
        lexer_source: Path,
        lexer_binary: Path,
    ) -> None:
        print("Building self-hosted lexer...")
        source = self._repository_root / "src/compiler/btrc/tools/lex_main.btrc"
        compile_result = self._run((*btrcpy, str(source), "--no-cache", "-o", str(lexer_source)))
        if compile_result.returncode != 0:
            raise CompilerVerificationError(
                "self-hosted lexer transpilation failed:\n" + compile_result.stderr.decode("utf-8", errors="replace")
            )
        c_result = self._run((*c_compiler, "-std=c11", str(lexer_source), "-o", str(lexer_binary), "-lm", "-lpthread"))
        if c_result.returncode != 0:
            raise CompilerVerificationError(
                "self-hosted lexer C compilation failed:\n" + c_result.stderr.decode("utf-8", errors="replace")
            )

    def _compare_lexers(self, btrcpy: Sequence[str], lexer_binary: Path) -> int:
        total = 0
        matched = 0
        failures = 0
        test_root = self._repository_root / "src/tests"
        for source_path in sorted(test_root.rglob("*.btrc")):
            source = source_path.read_text(encoding="utf-8")
            if self._SOURCE_DEPENDENCY.search(source):
                continue
            total += 1
            selfhost = self._run((str(lexer_binary), str(source_path)))
            if selfhost.returncode != 0:
                failures += 1
                self._report_failure("SELFHOST LEXER FAILED", source_path, selfhost.stderr)
                continue
            reference = self._run((*btrcpy, str(source_path), "--emit-tokens", "--no-stdlib"))
            if reference.returncode != 0:
                failures += 1
                self._report_failure("PYTHON LEXER FAILED", source_path, reference.stderr)
                continue
            if selfhost.stdout == reference.stdout:
                matched += 1
            else:
                failures += 1
                print(f"MISMATCH: {source_path}")
        print(f"lexer parity: {matched} / {total} byte-identical")
        return 0 if failures == 0 else 1

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                cwd=self._repository_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise CompilerVerificationError(f"could not execute {command[0]!r}: {error}") from error

    def _report_failure(self, label: str, source_path: Path, stderr: bytes) -> None:
        print(f"{label}: {source_path}")
        message = stderr.decode("utf-8", errors="replace")
        for line in message.splitlines():
            print(f"  {line}")
