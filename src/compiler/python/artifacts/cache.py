"""Compiler output storage, generation ownership and toolchain fingerprints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .publication import (
    ArtifactPublisher,
    ArtifactStorage,
    PublicationLock,
    PublicationTarget,
    PublishedArtifact,
    StagedPublicationPolicy,
)


class AtomicFileStore:
    """Own secure regular-file reads and durable atomic publication."""

    def __init__(self, *, default_max_json_bytes: int = 64 * 1024 * 1024) -> None:
        if default_max_json_bytes <= 0:
            raise ValueError("JSON byte limit must be positive")
        self.default_max_json_bytes = default_max_json_bytes

    def read_json(
        self,
        path: str,
        max_bytes: int | None = None,
        *,
        follow_symlinks: bool = False,
    ):
        """Read bounded strict JSON, returning ``None`` for invalid data."""
        limit = self.default_max_json_bytes if max_bytes is None else max_bytes
        if limit <= 0:
            raise ValueError("JSON byte limit must be positive")
        try:
            cache_file = self.open_regular_binary(
                path,
                follow_symlinks=follow_symlinks,
            )
            if cache_file is None:
                return None
            with cache_file:
                if os.fstat(cache_file.fileno()).st_size > limit:
                    return None
                encoded = cache_file.read(limit + 1)
            if len(encoded) > limit:
                return None
            return json.loads(
                encoded.decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return None

    def open_regular_binary(self, path: str, *, follow_symlinks: bool = False):
        """Open a regular file without blocking on a substituted device."""
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if not follow_symlinks:
            flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                descriptor = -1
                return None
            binary_file = os.fdopen(descriptor, "rb")
            descriptor = -1
            return binary_file
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)

    def write_json(self, path: str, payload, *, file_mode: int | None = None) -> None:
        """Serialize deterministic JSON and atomically replace ``path``."""
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.write_text(path, encoded, file_mode=file_mode)

    def write_text(
        self,
        path: str,
        content: str,
        *,
        file_mode: int | None = None,
    ) -> None:
        """Write text durably before an atomic same-directory replacement."""
        cache_dir = os.path.dirname(path) or "."
        os.makedirs(cache_dir, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".btrc-cache-",
            dir=cache_dir,
        )
        try:
            if file_mode is not None:
                fchmod = getattr(os, "fchmod", None)
                if fchmod is not None:
                    fchmod(descriptor, file_mode)
                else:
                    os.chmod(temporary_path, file_mode)
            cache_file = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            )
            descriptor = -1
            with cache_file:
                cache_file.write(content)
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary_path, path)
            self.sync_parent(path)
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                os.remove(temporary_path)

    def sync_parent(self, path: str) -> None:
        """Apply a best-effort durability barrier to a directory entry."""
        directory = os.path.dirname(os.path.abspath(path))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            return
        try:
            with suppress(OSError):
                os.fsync(descriptor)
        finally:
            with suppress(OSError):
                os.close(descriptor)

    @staticmethod
    def _reject_json_constant(value: str):
        raise ValueError(f"invalid JSON constant: {value}")


@dataclass(frozen=True)
class CompilerOutput:
    """One caller-authorized, already staged compiler output."""

    staged: Path
    destination: Path
    role: str


@dataclass(frozen=True)
class CompilerOutputContent:
    destination: Path
    content: str
    role: str


@dataclass(frozen=True)
class CompilerOutputIdentity:
    destination: Path
    role: str
    sha256: str
    mode: int


class CompilerGenerationPolicy(StagedPublicationPolicy):
    """Bind the committed ownership record to the actual fixed-stage bytes."""

    def __init__(
        self,
        identities: tuple[CompilerOutputIdentity, ...],
        manifest: str,
        storage: ArtifactStorage,
        policy: StagedPublicationPolicy | None,
        validate_destinations: Callable[[Sequence[Path]], None] | None = None,
        destinations: tuple[Path, ...] = (),
    ) -> None:
        self._identities = identities
        self._manifest = manifest
        self._storage = storage
        self._policy = policy
        self._validate_destinations = validate_destinations
        self._destinations = destinations

    @classmethod
    def identity(cls, path: Path, destination: Path, role: str, storage: ArtifactStorage) -> CompilerOutputIdentity:
        descriptor = storage.open_regular(path)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return CompilerOutputIdentity(destination, role, digest, stat.S_IMODE(metadata.st_mode))

    def validate(self, staged: tuple[Path, ...]) -> None:
        if len(staged) != len(self._identities) + 1:
            raise ValueError("compiler generation has an invalid staged inventory")
        if self._policy is not None:
            self._policy.validate(staged[:-1])
        if self._validate_destinations is not None:
            self._validate_destinations(self._destinations)
        for path, expected in zip(staged, self._identities, strict=False):
            if self.identity(path, expected.destination, expected.role, self._storage) != expected:
                raise ValueError(f"compiler output changed after preparation: {expected.destination}")
        descriptor = self._storage.open_regular(staged[-1])
        with os.fdopen(descriptor, "rb") as stream:
            expected = self._manifest.encode("utf-8")
            if stream.read(len(expected) + 1) != expected:
                raise ValueError("compiler generation ownership record changed after preparation")


class CompilerGenerationPublisher:
    """Persist output ownership and interrupted inventories around one publisher.

    The caller provisions a private, durable state directory outside untrusted
    source trees. It is recovery state, not an evictable compilation cache. POSIX
    ownership/modes are checked here; Windows callers must provision its ACL.
    Current destinations are explicit caller authority. Old destinations are
    authorized only by records in that private directory, never output journals.
    """

    _ROLES = frozenset({"primary", "secondary", "link-plan", "freestanding"})

    def __init__(
        self,
        directory: Path,
        *,
        publication: ArtifactPublisher | None = None,
        storage: ArtifactStorage | None = None,
        max_record_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if max_record_bytes <= 0:
            raise ValueError("generation record byte limit must be positive")
        self._storage = storage or ArtifactStorage()
        self._require_private_directory(directory)
        self._directory = directory.resolve()
        self._publication = publication or ArtifactPublisher(self._storage)
        self._files = AtomicFileStore()
        self._max_record_bytes = max_record_bytes

    def _require_private_directory(self, path: Path) -> None:
        metadata = self._storage.require_real_directory(path, "compiler generation state")
        if os.name != "nt" and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077):
            raise ValueError(f"compiler generation state must be private to the current user: {path}")

    def _path(self, value: object) -> Path:
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("invalid compiler generation path")
        path = Path(value)
        if not path.is_absolute() or path != path.parent.resolve() / path.name:
            raise ValueError(f"compiler generation path is not canonical: {path}")
        return path

    def _output_path(self, value: object) -> Path:
        path = self._path(value)
        if path.is_relative_to(self._directory):
            raise ValueError("compiler outputs must not replace generation state")
        return path

    def _entry(self, anchor: Path) -> tuple[Path, str]:
        self._require_private_directory(self._directory)
        key = hashlib.sha256(os.fsencode(os.path.normcase(anchor))).hexdigest()
        entry = self._directory / key
        entry.mkdir(mode=0o700, exist_ok=True)
        self._require_private_directory(entry)
        self._storage.fsync_directory(self._directory)
        return entry, f"btrc-output-{key}"

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate compiler generation field: {key}")
            result[key] = value
        return result

    def _read(self, path: Path) -> dict | None:
        if self._storage.lstat_or_none(path) is None:
            return None
        descriptor = self._storage.open_regular(path)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if metadata.st_nlink != 1 or (
                os.name != "nt" and (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077)
            ):
                raise ValueError(f"compiler generation record must be private and unaliased: {path}")
            encoded = stream.read(self._max_record_bytes + 1)
        try:
            if len(encoded) > self._max_record_bytes:
                raise ValueError("compiler generation record exceeds byte limit")
            record = json.loads(encoded, object_pairs_hook=self._unique_object)
            if not isinstance(record, dict) or type(record.get("schema")) is not int or record["schema"] != 1:
                raise ValueError("unsupported compiler generation schema")
            return record
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ValueError(f"invalid compiler generation record: {path}") from error

    def _encode(self, record: dict) -> str:
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self._max_record_bytes:
            raise ValueError("compiler generation record exceeds byte limit")
        return encoded

    def _committed(self, entry: Path, anchor: Path) -> tuple[CompilerOutputIdentity, ...]:
        record = self._read(entry / "committed.json")
        if record is None:
            return ()
        if (
            set(record) != {"schema", "anchor", "files"}
            or record["anchor"] != str(anchor)
            or not isinstance(record["files"], list)
        ):
            raise ValueError("invalid committed compiler generation")
        identities = []
        for row in record["files"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "role", "sha256", "mode"}
                or not isinstance(row["role"], str)
                or row["role"] not in self._ROLES
                or not isinstance(row["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                or type(row["mode"]) is not int
                or not 0 <= row["mode"] <= 0o7777
            ):
                raise ValueError("invalid committed compiler output identity")
            identities.append(
                CompilerOutputIdentity(self._output_path(row["path"]), row["role"], row["sha256"], row["mode"])
            )
        self._validate_roles(identities, anchor)
        return tuple(identities)

    def _validate_roles(
        self, outputs: Sequence[CompilerOutput | CompilerOutputContent | CompilerOutputIdentity], anchor: Path
    ) -> None:
        if not outputs or outputs[0].destination != anchor or outputs[0].role != "primary":
            raise ValueError("compiler generation must begin with its primary output")
        if len({output.destination for output in outputs}) != len(outputs):
            raise ValueError("compiler generation destinations must be unique")
        for role in self._ROLES - {"secondary"}:
            if sum(output.role == role for output in outputs) > 1:
                raise ValueError(f"duplicate compiler output role: {role}")
        if any(output.role not in self._ROLES for output in outputs):
            raise ValueError("unknown compiler output role")

    def _recover(
        self,
        entry: Path,
        anchor: Path,
        name: str,
        validate_destinations: Callable[[Sequence[Path]], None] | None = None,
    ) -> None:
        record = self._read(entry / "intent.json")
        if record is None:
            if self._publication.publication_in_progress(anchor.parent, name):
                raise ValueError("compiler publication has no owned recovery inventory")
            return
        if (
            set(record) != {"schema", "anchor", "targets"}
            or record["anchor"] != str(anchor)
            or not isinstance(record["targets"], list)
        ):
            raise ValueError("invalid prepared compiler generation")
        targets = []
        for row in record["targets"]:
            if not isinstance(row, dict) or set(row) != {"path", "absent"} or type(row["absent"]) is not bool:
                raise ValueError("invalid prepared compiler output")
            targets.append(PublicationTarget(self._path(row["path"]), is_absent=row["absent"]))
        if (
            len(targets) < 2
            or targets[0] != PublicationTarget(anchor)
            or targets[-1] != PublicationTarget(entry / "committed.json")
        ):
            raise ValueError("invalid compiler generation recovery boundaries")
        for target in targets[:-1]:
            self._output_path(str(target.destination))
        if validate_destinations is not None:
            validate_destinations(tuple(target.destination for target in targets[:-1]))
        self._publication.recover(name, targets)
        # committed.json is the transaction's final validator: rollback restores
        # the old ownership set; a durable commit retains the new one.
        self._committed(entry, anchor)
        (entry / "candidate.json").unlink(missing_ok=True)
        (entry / "intent.json").unlink()
        self._storage.fsync_directory(entry)

    def recover(self, anchor: Path) -> tuple[CompilerOutputIdentity, ...]:
        """Recover the recorded attempt and return the resulting ownership set."""
        anchor = self._output_path(str(anchor))
        entry, name = self._entry(anchor)
        with PublicationLock(entry, "compiler-owner", threading.Lock(), self._storage):
            self._recover(entry, anchor, name)
            return self._committed(entry, anchor)

    @staticmethod
    def _revision(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def _retained_output(self, output: CompilerOutputContent, owned: CompilerOutputIdentity) -> os.stat_result | None:
        metadata = self._storage.lstat_or_none(output.destination)
        if metadata is None or not stat.S_ISREG(metadata.st_mode) or self._storage.metadata_is_reparse_point(metadata):
            return None
        if stat.S_IMODE(metadata.st_mode) != owned.mode:
            return None
        descriptor = self._storage.open_regular(output.destination)
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb") as stream:
            if self._revision(os.fstat(stream.fileno())) != self._revision(metadata):
                raise ValueError(f"compiler output changed during retention: {output.destination}")
            for offset in range(0, len(output.content), 65536):
                encoded = output.content[offset : offset + 65536].encode("utf-8")
                if stream.read(len(encoded)) != encoded:
                    return None
                digest.update(encoded)
            if stream.read(1) or digest.hexdigest() != owned.sha256:
                return None
            if self._revision(os.fstat(stream.fileno())) != self._revision(metadata):
                raise ValueError(f"compiler output changed during retention: {output.destination}")
        if self._revision(output.destination.lstat()) != self._revision(metadata):
            raise ValueError(f"compiler output changed during retention: {output.destination}")
        return metadata

    def retain_unchanged(
        self,
        outputs: Sequence[CompilerOutputContent],
        *,
        validate_destinations: Callable[[Sequence[Path]], None],
    ) -> bool:
        """Verify an owned generation under its normal locks before skipping staging.

        A miss grants no authority: the caller still uses ordinary publication.
        Fresh source/path guards run after lock acquisition and after every read.
        """
        outputs = tuple(outputs)
        if not outputs:
            return False
        anchor = self._output_path(str(outputs[0].destination))
        self._validate_roles(outputs, anchor)
        for output in outputs:
            self._output_path(str(output.destination))
        entry, name = self._entry(anchor)
        with PublicationLock(entry, "compiler-owner", threading.Lock(), self._storage):
            self._recover(entry, anchor, name, validate_destinations)
            previous = self._committed(entry, anchor)
            if [(value.destination, value.role) for value in previous] != [
                (value.destination, value.role) for value in outputs
            ]:
                return False
            targets = (
                *[PublicationTarget(value.destination) for value in previous],
                PublicationTarget(entry / "committed.json"),
            )
            self._publication.recover(name, targets)
            with self._publication.read_directories(tuple(target.destination.parent for target in targets)):
                destinations = tuple(value.destination for value in outputs)
                validate_destinations(destinations)
                self._require_private_directory(self._directory)
                self._require_private_directory(entry)
                revisions = []
                for output, owned in zip(outputs, previous, strict=True):
                    revision = self._retained_output(output, owned)
                    if revision is None:
                        return False
                    revisions.append(revision)
                validate_destinations(destinations)
                for output, revision in zip(outputs, revisions, strict=True):
                    if self._revision(output.destination.lstat()) != self._revision(revision):
                        raise ValueError(f"compiler output changed during retention: {output.destination}")
                if self._committed(entry, anchor) != previous:
                    raise ValueError("compiler generation ownership changed during retention")
                return True

    def publish(
        self,
        outputs: Sequence[CompilerOutput],
        *,
        policy: StagedPublicationPolicy | None = None,
        validate_destinations: Callable[[Sequence[Path]], None] | None = None,
    ) -> None:
        """Publish regular files, retiring only unchanged owned predecessors.

        Destinations must already be canonical and authorized by source/output
        validation. Symlink/device and create-if-absent seam policy belongs to
        the compiler caller; this owner never silently takes ownership of them.
        """
        outputs = tuple(outputs)
        if not outputs:
            raise ValueError("compiler generation requires outputs")
        anchor = self._output_path(str(outputs[0].destination))
        self._validate_roles(outputs, anchor)
        for output in outputs:
            self._output_path(str(output.destination))
            if output.staged.parent.resolve().is_relative_to(self._directory):
                raise ValueError("compiler candidates must not alias generation state")
            metadata = self._storage.lstat_or_none(output.destination)
            if metadata is not None and self._storage.metadata_is_reparse_point(metadata):
                raise ValueError("compiler output destinations must not be symlinks")
        entry, name = self._entry(anchor)
        with PublicationLock(entry, "compiler-owner", threading.Lock(), self._storage):
            self._recover(entry, anchor, name, validate_destinations)
            previous = self._committed(entry, anchor)
            identities = tuple(
                CompilerGenerationPolicy.identity(output.staged, output.destination, output.role, self._storage)
                for output in outputs
            )
            manifest = self._encode(
                {
                    "schema": 1,
                    "anchor": str(anchor),
                    "files": [
                        {"path": str(value.destination), "role": value.role, "sha256": value.sha256, "mode": value.mode}
                        for value in identities
                    ],
                }
            )
            destinations = {output.destination for output in outputs}
            artifacts = tuple(PublishedArtifact(output.staged, output.destination) for output in outputs)
            artifacts += tuple(
                PublishedArtifact(None, prior.destination, expected_digest=prior.sha256)
                for prior in previous
                if prior.destination not in destinations
            )
            public_destinations = tuple(artifact.destination for artifact in artifacts)
            if validate_destinations is not None:
                validate_destinations(public_destinations)
            candidate = entry / "candidate.json"
            artifacts += (PublishedArtifact(candidate, entry / "committed.json"),)
            # Validate the exact authorized layout before persisting it. No
            # prior intent survives this point; this recovery only clears owned
            # controls left before a transaction journal was installed.
            self._publication.recover(name, tuple(artifact.target for artifact in artifacts))
            intent = self._encode(
                {
                    "schema": 1,
                    "anchor": str(anchor),
                    "targets": [
                        {"path": str(artifact.destination), "absent": artifact.is_absent} for artifact in artifacts
                    ],
                }
            )
            self._files.write_text(str(candidate), manifest, file_mode=0o600)
            self._files.write_text(str(entry / "intent.json"), intent, file_mode=0o600)
            # Cache writes deliberately use best-effort directory durability.
            # Recovery authority cannot: do not enter publication until its
            # complete prepared inventory has crossed a strict barrier.
            self._storage.fsync_directory(entry)
            try:
                self._publication.publish(
                    name,
                    artifacts,
                    policy=CompilerGenerationPolicy(
                        identities,
                        manifest,
                        self._storage,
                        policy,
                        validate_destinations,
                        public_destinations,
                    ),
                )
            finally:
                # Failure can leave a recovery journal; preserve intent until
                # the next call reconciles it. The candidate is never authority.
                candidate.unlink(missing_ok=True)
            self._recover(entry, anchor, name, validate_destinations)


class CompilerOutputPublication:
    """Compose persistent generation storage for the process CLI, on demand."""

    def state_directory(self) -> Path:
        configured = os.environ.get("BTRC_STATE_DIR")
        if configured:
            directory = Path(configured)
        elif sys.platform == "darwin":
            directory = Path.home() / "Library/Application Support/btrc/generations"
        elif os.name == "nt":
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise ValueError("LOCALAPPDATA is required for compiler generation state")
            directory = Path(local) / "btrc/generations"
        else:
            root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
            directory = root / "btrc/generations"
        if not directory.is_absolute():
            raise ValueError("compiler generation state directory must be absolute")
        # Python >=3.13 also applies a user/administrators-only ACL for 0700
        # directory creation on Windows. Existing POSIX modes are checked by
        # the generation owner, never silently broadened or repaired here.
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return directory

    def retain_unchanged(
        self,
        outputs: Sequence[tuple[str, str, str]],
        *,
        validate: Callable[[Sequence[str]], None],
    ) -> bool:
        generation = CompilerGenerationPublisher(self.state_directory())
        return generation.retain_unchanged(
            tuple(CompilerOutputContent(Path(destination), content, role) for destination, content, role in outputs),
            validate_destinations=lambda paths: validate(tuple(str(path) for path in paths)),
        )

    def publish_staged(
        self,
        outputs: Sequence[tuple[str, str, str]],
        *,
        validate: Callable[[Sequence[str]], None],
    ) -> None:
        generation = CompilerGenerationPublisher(self.state_directory())
        generation.publish(
            tuple(CompilerOutput(Path(staged), Path(destination), role) for staged, destination, role in outputs),
            validate_destinations=lambda paths: validate(tuple(str(path) for path in paths)),
        )


class ToolchainSourceInventory:
    """Own the deterministic source inventory for toolchain fingerprints."""

    _FRONTEND_FILES = (
        "syntax/grammar.py",
        "syntax/tokens.py",
        "lexer/lexer.py",
        "syntax/ast/generated.py",
        "syntax/ast/codec.py",
        "artifacts/cache.py",
        "application/results.py",
        "application/pipeline.py",
        "frontend/packages.py",
        "frontend/sources.py",
        "frontend/imports.py",
        "frontend/stage.py",
    )

    def __init__(self, compiler_directory: str, source_directory: str) -> None:
        self.compiler_directory = os.path.abspath(compiler_directory)
        self.source_directory = os.path.abspath(source_directory)

    @classmethod
    def canonical(cls) -> ToolchainSourceInventory:
        compiler_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        source_directory = os.path.dirname(os.path.dirname(compiler_directory))
        return cls(compiler_directory, source_directory)

    def files(self, scope: str) -> tuple[str, ...]:
        if scope not in ("frontend", "full"):
            raise ValueError(f"unknown toolchain hash scope: {scope!r}")

        paths = [
            os.path.join(self.source_directory, "language", "grammar.ebnf"),
            os.path.join(self.source_directory, "language", "ast.asdl"),
            *(os.path.join(self.compiler_directory, path) for path in self._FRONTEND_FILES),
        ]
        paths.extend(self._python_files_under("application", "frontend", "parser"))
        if scope == "full":
            # Generated C can be shaped by orchestration, publication, cache,
            # analyzer, or IR code. Cover every production Python source so a
            # new lowering-adjacent module cannot silently reuse stale output.
            paths.extend(self._python_files_under(""))
            # Cover runtime source inputs as well as their generated catalogs;
            # source-tree toolchain changes must invalidate emitted generations.
            runtime = Path(self.source_directory) / "runtime" / "c"
            paths.extend(str(path) for path in runtime.rglob("*") if path.is_file())
        return tuple(sorted(set(paths)))

    def _python_files_under(self, *relative_directories: str) -> list[str]:
        found: list[str] = []
        for relative in relative_directories:
            root = os.path.join(self.compiler_directory, relative)
            for current, _directories, files in os.walk(root):
                found.extend(os.path.join(current, name) for name in files if name.endswith(".py"))
        return found


class ToolchainFingerprint:
    """Own memoized fingerprints for one explicit source inventory."""

    def __init__(self, inventory: ToolchainSourceInventory | None = None) -> None:
        self.inventory = inventory or ToolchainSourceInventory.canonical()
        self._digests: dict[str, str] = {}
        self._lock = threading.Lock()

    def digest(self, scope: str = "full") -> str:
        if scope not in ("frontend", "full"):
            raise ValueError(f"unknown toolchain hash scope: {scope!r}")
        cached = self._digests.get(scope)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._digests.get(scope)
            if cached is None:
                cached = self._hash(self.inventory.files(scope))
                self._digests[scope] = cached
        return cached

    def _hash(self, paths: tuple[str, ...]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            relative_path = os.path.relpath(
                path,
                self.inventory.source_directory,
            ).replace(os.sep, "/")
            encoded_path = relative_path.encode()
            digest.update(len(encoded_path).to_bytes(8, "big"))
            digest.update(encoded_path)
            try:
                with open(path, "rb") as source_file:
                    content = source_file.read()
            except OSError:
                content = b"<missing>"
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()[:16]


class CacheDirectory:
    """Own deterministic compiler-cache directory resolution."""

    def resolve(self, input_path: str | None = None) -> str:
        """Resolve and create the cache directory for ``input_path``.

        Resolution order is ``$BTRC_CACHE_DIR``, the nearest package root, then
        the platform's per-user cache directory. The invoking directory itself
        is never used as a cache root.
        """

        configured = os.environ.get("BTRC_CACHE_DIR")
        if configured:
            directory = configured
        else:
            start = os.path.dirname(os.path.abspath(input_path)) if input_path else os.getcwd()
            manifest = self._find_manifest(start)
            if manifest is not None:
                directory = os.path.join(os.path.dirname(manifest), ".btrc-cache")
            else:
                directory = os.path.join(self._user_root(), "btrc")
        os.makedirs(directory, exist_ok=True)
        return directory

    @staticmethod
    def _find_manifest(start_directory: str) -> str | None:
        """Find the nearest package marker needed by cache placement policy."""

        directory = os.path.abspath(start_directory)
        while True:
            candidate = os.path.join(directory, "btrc.toml")
            if os.path.exists(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                return None
            directory = parent

    @staticmethod
    def _user_root() -> str:
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches")
        if sys.platform == "win32":  # pragma: no cover - unsupported dev platform
            return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
        return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


@dataclass(frozen=True)
class CompiledArtifacts:
    """One complete emitted result; source maps and adapters live in its payloads."""

    c_source: str
    c_units: tuple[str, ...]
    link_plan: str
    # message, line, column, severity, source file; no executable compiler objects.
    diagnostics: tuple[tuple[str, int, int, str, str | None], ...] = ()
    split_source_spaces: bool = False


class CompilerCache:
    """Own framing, validation, and persistence of complete emitted generations."""

    # Split debug output repeats declarations: the measured BTRSmith generation
    # is 327 MB. Bound aggregate reads while admitting that real product build.
    MAX_ENTRY_BYTES = 512 * 1024 * 1024
    ARTIFACT_SCHEMA = 2

    def __init__(
        self,
        fingerprint: ToolchainFingerprint | None = None,
        directory: CacheDirectory | None = None,
        *,
        max_entry_bytes: int = MAX_ENTRY_BYTES,
        file_store: AtomicFileStore | None = None,
    ) -> None:
        if max_entry_bytes <= 0:
            raise ValueError("compiled cache entry limit must be positive")
        self._fingerprint = fingerprint or ToolchainFingerprint()
        self._directory = directory or CacheDirectory()
        self._max_entry_bytes = max_entry_bytes
        self._files = file_store or AtomicFileStore()
        self._storage = ArtifactStorage()
        self._publisher = ArtifactPublisher(self._storage)

    def load_artifacts(
        self,
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> CompiledArtifacts | None:
        """Read a checksum-verified generation under the publication lock."""
        try:
            key = self.key_for(resolved_source, source_identity)
            directory = Path(self._directory.resolve(input_path))
            name = f"{key}.artifacts"
            generation = directory / name
            if not generation.exists():
                return None
            with self._publisher.lock(directory, name):
                if self._publisher.publication_in_progress(directory, name):
                    return None
                self._storage.require_real_directory(generation, "compiled generation")
                self._storage.require_real_regular(generation / "manifest.json", "compiled manifest")
                manifest = self._files.read_json(str(generation / "manifest.json"), max_bytes=8 * 1024 * 1024)
                if (
                    not isinstance(manifest, dict)
                    or set(manifest) != {"schema", "key", "files"}
                    or type(manifest["schema"]) is not int
                    or manifest["schema"] != self.ARTIFACT_SCHEMA
                    or manifest["key"] != key
                    or not isinstance(manifest["files"], list)
                    or len(manifest["files"]) < 3
                ):
                    return None
                records = manifest["files"]
                names = [
                    "primary.c",
                    *[f"unit-{index}.c" for index in range(1, len(records) - 2)],
                    "link-plan.json",
                    "diagnostics.json",
                ]
                with os.scandir(generation) as entries:
                    if {entry.name for entry in entries} != {*names, "manifest.json"}:
                        return None
                payloads = []
                remaining = self._max_entry_bytes
                for name, record in zip(names, records, strict=True):
                    if (
                        not isinstance(record, dict)
                        or set(record) != {"name", "bytes", "sha256"}
                        or record["name"] != name
                        or type(record["bytes"]) is not int
                        or not 0 <= record["bytes"] <= remaining
                    ):
                        return None
                    path = generation / name
                    self._storage.require_real_regular(path, "compiled artifact")
                    stream = self._files.open_regular_binary(str(path))
                    if stream is None:
                        return None
                    with stream:
                        if os.fstat(stream.fileno()).st_size != record["bytes"]:
                            return None
                        encoded = stream.read(record["bytes"] + 1)
                    if len(encoded) != record["bytes"] or hashlib.sha256(encoded).hexdigest() != record["sha256"]:
                        return None
                    remaining -= len(encoded)
                    payloads.append(encoded.decode("utf-8"))
                metadata = json.loads(payloads[-1])
                if (
                    not isinstance(metadata, dict)
                    or set(metadata) != {"diagnostics", "split-source-spaces"}
                    or type(metadata["split-source-spaces"]) is not bool
                    or not isinstance(metadata["diagnostics"], list)
                ):
                    return None
                diagnostics = []
                for record in metadata["diagnostics"]:
                    if (
                        not isinstance(record, list)
                        or len(record) != 5
                        or not isinstance(record[0], str)
                        or type(record[1]) is not int
                        or record[1] < 0
                        or type(record[2]) is not int
                        or record[2] < 0
                        or record[3] not in ("warning", "note", "info")
                        or not (record[4] is None or isinstance(record[4], str))
                    ):
                        return None
                    diagnostics.append(tuple(record))
                return CompiledArtifacts(
                    payloads[0],
                    tuple(payloads[1:-2]),
                    payloads[-2],
                    tuple(diagnostics),
                    metadata["split-source-spaces"],
                )
        except (OSError, UnicodeError, ValueError, RecursionError):
            return None

    def store_artifacts(
        self,
        resolved_source: str,
        c_source: str,
        input_path: str | None = None,
        *,
        c_units: tuple[str, ...] = (),
        link_plan: str,
        diagnostics: tuple[tuple[str, int, int, str, str | None], ...] = (),
        split_source_spaces: bool = False,
        source_identity: str = "",
    ) -> None:
        """Stage all payloads before transactionally replacing one generation."""
        key = self.key_for(resolved_source, source_identity)
        directory = Path(self._directory.resolve(input_path))
        name = f"{key}.artifacts"
        with tempfile.TemporaryDirectory(prefix=".btrc-generation-", dir=directory) as temporary:
            staged = Path(temporary) / "artifacts"
            staged.mkdir()
            records = []
            remaining = self._max_entry_bytes
            payloads = (
                ("primary.c", c_source),
                *((f"unit-{index}.c", unit) for index, unit in enumerate(c_units, start=1)),
                ("link-plan.json", link_plan),
                (
                    "diagnostics.json",
                    json.dumps(
                        {"diagnostics": diagnostics, "split-source-spaces": split_source_spaces},
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
            for filename, content in payloads:
                encoded = content.encode("utf-8")
                remaining -= len(encoded)
                if remaining < 0:
                    return  # A valid large compile can simply forgo caching.
                (staged / filename).write_bytes(encoded)
                records.append({"name": filename, "bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()})
            self._files.write_json(
                str(staged / "manifest.json"),
                {"schema": self.ARTIFACT_SCHEMA, "key": key, "files": records},
            )
            self._publisher.publish(name, [PublishedArtifact(staged, directory / name, is_directory=True)])

    def key_for(self, resolved_source: str, source_identity: str = "") -> str:
        """Frame toolchain, provenance, and source into one collision-safe key."""

        digest = hashlib.sha256()
        for component in (
            f"v{self._fingerprint.digest('full')}",
            source_identity,
            resolved_source,
        ):
            encoded = component.encode("utf-8", errors="surrogatepass")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def load_directives(self, source: str, input_path: str) -> tuple[tuple[int, int], ...] | None:
        """Read content/toolchain-keyed directive spans, never resolved paths."""
        try:
            key = self.key_for(source, "source-directives-v1")
            path = Path(self._directory.resolve(input_path)) / f"{key}.directives.json"
            payload = self._files.read_json(str(path), max_bytes=min(self._max_entry_bytes, 8 * 1024 * 1024))
            if (
                not isinstance(payload, dict)
                or set(payload) != {"key", "ranges", "sha256"}
                or payload["key"] != key
                or not isinstance(payload["ranges"], list)
            ):
                return None
            ranges = payload["ranges"]
            for row in ranges:
                if not isinstance(row, list) or len(row) != 2 or any(type(value) is not int for value in row):
                    return None
            encoded = json.dumps(ranges, separators=(",", ":")).encode()
            if hashlib.sha256(encoded).hexdigest() != payload["sha256"]:
                return None
            return tuple(tuple(row) for row in ranges)
        except (OSError, UnicodeError, ValueError, RecursionError):
            return None

    def store_directives(self, source: str, ranges: tuple[tuple[int, int], ...], input_path: str) -> None:
        """Atomically store scanner spans; optional storage cannot break a scan."""
        try:
            key = self.key_for(source, "source-directives-v1")
            encoded = json.dumps(ranges, separators=(",", ":")).encode()
            payload = {"key": key, "ranges": ranges, "sha256": hashlib.sha256(encoded).hexdigest()}
            if len(json.dumps(payload).encode()) > min(self._max_entry_bytes, 8 * 1024 * 1024):
                return
            path = Path(self._directory.resolve(input_path)) / f"{key}.directives.json"
            self._files.write_json(str(path), payload)
        except (OSError, UnicodeError, ValueError, RecursionError):
            return
