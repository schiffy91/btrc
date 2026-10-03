"""Source models, bounded repositories, provenance, and dependency resolution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol

import src.compiler.python.syntax.ast.generated as ast

from ..abi.generated import (
    TARGET_FOREIGN_MACRO_NAMES,
    TARGET_PREDEFINED_MACRO_ROWS,
    TARGET_ROWS,
    TARGET_UNDEFINED_MACRO_NAMES,
)
from ..abi.hosted import HOSTED_ABI
from ..lexer.lexer import Lexer, LexerError, LiteralDecoder
from ..parser.parser import Parser
from ..syntax.ast.codec import AstJsonCodec
from ..syntax.tokens import SourceSymbolDirective, Token, TokenKind, TokenVocabulary
from .native_imports import NativeDeclarationImporter, NativeGeneratedSource, NativeHeaderSource
from .packages import IncludeResolutionError, NativeLinkPlan, PackageTarget, PackageUniverse, ResolvedPackages
from .symbol_index import StdlibSymbolIndex


class CompilerStdlibSource(str):
    """A displayable path authenticated by frontend source composition."""

    def __new__(cls, path: str = "<stdlib>"):
        return super().__new__(cls, path)

    @classmethod
    def authenticated(cls, value: object) -> bool:
        return isinstance(value, cls)

    @classmethod
    def stamp_nested(cls, declaration) -> None:
        for attribute in ("members", "methods", "variants"):
            for nested in getattr(declaration, attribute, ()) or ():
                nested.source_file = declaration.source_file


@dataclass(frozen=True)
class StdlibSource:
    source: str
    source_positions: tuple[tuple[str, int], ...]
    input_identities: tuple[SourceReadIdentity, ...] = ()


class SourceDependencyKind(Enum):
    """The source-composition relationship represented by a graph edge."""

    IMPORT = "import"
    INCLUDE = "include"


@dataclass(frozen=True)
class SourceDependency:
    """One typed outgoing dependency from a source file."""

    target: str
    kind: SourceDependencyKind


@dataclass(frozen=True)
class CompilationGroups:
    """Strongly connected source groups, each compiled into its own unit.

    A group is named by its first canonical member path. Declarations with no
    source path, everything the native importer declares, and declarations
    from a file outside every group belong to the program unit, which also
    owns process-unique runtime state.
    """

    PROGRAM = ""

    groups: tuple[tuple[str, ...], ...]
    _membership: dict[str, str] = field(default_factory=dict, compare=False, repr=False)
    # Stamped path → group: canonicalizing resolves symlinks on disk, and a
    # module-unit session asks once per declaration.
    _resolved: dict[str, str] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        for members in self.groups:
            for member in members:
                self._membership[member] = members[0]

    def names(self) -> tuple[str, ...]:
        """Group names in dependency order."""

        return tuple(members[0] for members in self.groups)

    def members(self, name: str) -> tuple[str, ...]:
        return next((members for members in self.groups if members[0] == name), ())

    def group_of(self, source_file: object) -> str:
        """The owning group of a declaration's stamped source file.

        What the native importer declares belongs to the program unit whatever
        module's binding imported it: the Objective-C and C++ adapters form one
        generated unit per language, which only the program unit carries, and
        the classes the importer writes have no line in any group's source.
        """

        # Before the memo: a native stamp compares and hashes equal to its
        # binding module's path, which the memo maps to that module's group.
        if isinstance(source_file, (NativeHeaderSource, NativeGeneratedSource)):
            return self.PROGRAM
        if not isinstance(source_file, str) or not source_file or source_file.startswith("<"):
            return self.PROGRAM
        group = self._resolved.get(source_file)
        if group is None:
            group = self._membership.get(SourceDependencyGraph.canonical_file(source_file), self.PROGRAM)
            self._resolved[source_file] = group
        return group


@dataclass
class SourceDependencyGraph:
    """Typed source graph with the language's visibility semantics.

    ``import`` is directed. Legacy ``#include`` composes both files into one
    compilation unit, so visibility traversal treats include edges as
    reciprocal while retaining their distinct edge kind.
    """

    _outgoing: dict[str, set[SourceDependency]] = field(default_factory=dict)
    _reads: dict[str, SourceReadIdentity] = field(default_factory=dict)
    _tests: list[ConditionalTest] = field(default_factory=list)

    def record_read(self, identity: SourceReadIdentity) -> None:
        previous = self._reads.get(identity.path)
        if previous is not None and previous != identity:
            raise SourceReadError(f"source input changed between reads: {identity.path}")
        self._reads[identity.path] = identity

    def read_identities(self) -> tuple[SourceReadIdentity, ...]:
        return tuple(self._reads.values())

    def record_tests(self, tests: tuple[ConditionalTest, ...]) -> None:
        """Keep one conditioned file's ``#if`` test records, in resolution order."""

        self._tests.extend(tests)

    def conditional_tests(self) -> tuple[ConditionalTest, ...]:
        return tuple(self._tests)

    @staticmethod
    def canonical_file(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    def ensure_source(self, source: str) -> None:
        self._outgoing.setdefault(os.path.abspath(source), set())

    def add(self, source: str, target: str, kind: SourceDependencyKind) -> None:
        source = os.path.abspath(source)
        target = os.path.abspath(target)
        self.ensure_source(source)
        self.ensure_source(target)
        self._outgoing[source].add(SourceDependency(target, kind))

    def add_import(self, source: str, target: str) -> None:
        self.add(source, target, SourceDependencyKind.IMPORT)

    def add_include(self, source: str, target: str) -> None:
        self.add(source, target, SourceDependencyKind.INCLUDE)

    def dependencies_from(self, source: str) -> frozenset[SourceDependency]:
        return frozenset(self._outgoing.get(os.path.abspath(source), ()))

    def iter_edges(self) -> Iterator[tuple[str, SourceDependency]]:
        for source, dependencies in self._outgoing.items():
            for dependency in dependencies:
                yield source, dependency

    def has_target(self, target: str) -> bool:
        canonical_target = self.canonical_file(target)
        return any(self.canonical_file(dependency.target) == canonical_target for _, dependency in self.iter_edges())

    def source_paths(self) -> tuple[str, ...]:
        """Return every loaded source path for package-plan projection."""

        return tuple(self._outgoing)

    def cache_records(self) -> tuple[tuple[str, str, str], ...]:
        """Canonical, deterministic edge records for artifact identities."""

        return tuple(
            sorted(
                (
                    self.canonical_file(source),
                    dependency.kind.value,
                    self.canonical_file(dependency.target),
                )
                for source, dependency in self.iter_edges()
            )
        )

    def compilation_groups(self, root: str) -> CompilationGroups:
        """Partition loaded files into strongly connected compilation groups.

        Imports are directed and textual includes are reciprocal, exactly as
        for visibility. Groups are ordered so every group follows the groups
        it depends on; members and ties are ordered by canonical path.
        """

        adjacency: dict[str, set[str]] = {self.canonical_file(root): set()}
        for path in self._outgoing:
            adjacency.setdefault(self.canonical_file(path), set())
        for source, dependency in self.iter_edges():
            canonical_source = self.canonical_file(source)
            canonical_target = self.canonical_file(dependency.target)
            adjacency.setdefault(canonical_source, set()).add(canonical_target)
            adjacency.setdefault(canonical_target, set())
            if dependency.kind is SourceDependencyKind.INCLUDE:
                adjacency[canonical_target].add(canonical_source)
        # Tarjan's algorithm emits each component after every component it
        # reaches, which is already dependency order.
        index: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        groups: list[tuple[str, ...]] = []
        for start in sorted(adjacency):
            if start in index:
                continue
            index[start] = lowlink[start] = len(index)
            stack.append(start)
            on_stack.add(start)
            work = [(start, iter(sorted(adjacency[start])))]
            while work:
                node, successors = work[-1]
                for successor in successors:
                    if successor not in index:
                        index[successor] = lowlink[successor] = len(index)
                        stack.append(successor)
                        on_stack.add(successor)
                        work.append((successor, iter(sorted(adjacency[successor]))))
                        break
                    if successor in on_stack:
                        lowlink[node] = min(lowlink[node], index[successor])
                else:
                    work.pop()
                    if work:
                        parent = work[-1][0]
                        lowlink[parent] = min(lowlink[parent], lowlink[node])
                    if lowlink[node] == index[node]:
                        members = []
                        while True:
                            member = stack.pop()
                            on_stack.discard(member)
                            members.append(member)
                            if member == node:
                                break
                        groups.append(tuple(sorted(members)))
        return CompilationGroups(tuple(groups))

    def visibility_reachable(self, start: str) -> set[str]:
        """Return files visible from ``start`` under import/include rules."""

        adjacency: dict[str, set[str]] = {}
        for source, dependency in self.iter_edges():
            canonical_source = self.canonical_file(source)
            canonical_target = self.canonical_file(dependency.target)
            adjacency.setdefault(canonical_source, set()).add(canonical_target)
            adjacency.setdefault(canonical_target, set())
            if dependency.kind is SourceDependencyKind.INCLUDE:
                adjacency[canonical_target].add(canonical_source)

        canonical_start = self.canonical_file(start)
        seen = {canonical_start}
        pending = list(adjacency.get(canonical_start, ()))
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            pending.extend(adjacency.get(path, ()) - seen)
        return seen


@dataclass(frozen=True, slots=True)
class SourceMap:
    """Immutable mapping from compiler line spaces to native source lines."""

    positions: tuple[tuple[str, int], ...]
    user_line_count: int
    stdlib_line_count: int
    split_spaces: bool

    @property
    def user_position_offset(self) -> int:
        # Synthetic compilation inputs (notably stdlib archive construction)
        # intentionally have no native-position table.  In that case mapping
        # is unavailable rather than a negative slice into an empty tuple.
        return max(0, len(self.positions) - self.user_line_count)

    def map_line(self, line: int, space: str = "combined") -> tuple[str, int] | None:
        """Translate a 1-based parse-space line to a native source location."""
        offset = self.user_position_offset
        if space == "combined":
            if line > self.stdlib_line_count:
                space, line = "user", line - self.stdlib_line_count
            else:
                space = "stdlib"
        if space == "stdlib":
            index, lower, upper = line - 1, 0, offset
        else:
            index, lower, upper = offset + line - 1, offset, len(self.positions)
        if line >= 1 and lower <= index < upper:
            return self.positions[index]
        return None

    @staticmethod
    def _normalized(
        mapped: tuple[str, int] | None,
    ) -> tuple[str, int] | None:
        if mapped is None:
            return None
        source_file, native_line = mapped
        if os.path.exists(source_file):
            source_file = os.path.abspath(source_file)
        return source_file, native_line

    def combined(self, line: int) -> tuple[str, int] | None:
        """Map a combined parse-space line for debug markers."""
        return self._normalized(self.map_line(line, "combined"))

    def declaration(self, source_file: str | None, source_line: int) -> tuple[str, int] | None:
        """Map a declaration line from combined or split parse coordinates."""
        if not self.split_spaces:
            return self.combined(source_line)
        if not source_file:
            return None
        expected = os.path.normcase(os.path.realpath(source_file))
        for space in ("user", "stdlib"):
            mapped = self.map_line(source_line, space)
            if mapped is not None and os.path.normcase(os.path.realpath(mapped[0])) == expected:
                return self._normalized(mapped)
        return None

    def diagnostic(
        self,
        line: int,
        diagnostic_file: str | None = None,
    ) -> tuple[str, int] | None:
        """Map one diagnostic from its configured parse coordinate space."""
        if not self.split_spaces:
            return self.combined(line)
        offset = self.user_position_offset
        space = (
            "stdlib"
            if diagnostic_file is not None and any(path == diagnostic_file for path, _native in self.positions[:offset])
            else "user"
        )
        return self._normalized(self.map_line(line, space))


@dataclass(frozen=True)
class ResolvedSource:
    """One immutable source bundle ready for lexing and parsing."""

    user_source: str
    source: str
    stdlib_source: str = ""
    provenance: tuple[str, ...] = ()
    source_positions: tuple[tuple[str, int], ...] = ()
    graph: SourceDependencyGraph = field(default_factory=SourceDependencyGraph)
    strict_imports: bool = True
    root_source_path: str = ""
    native_plan: NativeLinkPlan = field(default_factory=NativeLinkPlan.empty)
    native_declarations: tuple = ()
    native_cache_identity: str | None = None
    input_identities: tuple[SourceReadIdentity, ...] = ()
    conditional_tests: tuple[ConditionalTest, ...] = ()

    def source_map(self, *, split_spaces: bool) -> SourceMap:
        """Return the immutable source map used by IR lowering."""
        return SourceMap(
            positions=self.source_positions,
            user_line_count=self.user_source.count("\n") + 1,
            stdlib_line_count=(self.stdlib_source.count("\n") + 1 if self.stdlib_source else 0),
            split_spaces=split_spaces,
        )

    def map_line(self, line: int, space: str = "combined") -> tuple[str, int] | None:
        """Translate a 1-based parse-space line to a native source location."""
        return self.source_map(split_spaces=False).map_line(line, space)

    def map_diag_line(
        self,
        line: int,
        *,
        diag_file: str | None = None,
        split_spaces: bool = False,
    ) -> tuple[str, int] | None:
        """Resolve a diagnostic position to a native source location."""

        return self.source_map(split_spaces=split_spaces).diagnostic(line, diag_file)

    def map_declaration_line(
        self,
        line: int,
        source_file: str | None,
        *,
        split_spaces: bool,
    ) -> tuple[str, int] | None:
        """Map a declaration line from combined or split parse coordinates."""

        return self.source_map(split_spaces=split_spaces).declaration(source_file, line)

    def cache_identity(self) -> str:
        """Hash source paths and native lines that can shape generated C."""

        digest = hashlib.sha256()

        def add_text(value: str) -> None:
            encoded = value.encode("utf-8", errors="surrogatepass")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)

        add_text("btrc-source-provenance-v3")
        add_text(self.root_source_path)
        add_text(self.native_plan.canonical_json())
        add_text(self.native_cache_identity or "")
        for source_file, native_line in self.source_positions:
            normalized = os.path.abspath(source_file) if os.path.exists(source_file) else source_file
            add_text(normalized)
            digest.update(int(native_line).to_bytes(8, "big", signed=True))
        for source, kind, target in self.graph.cache_records():
            add_text(source)
            add_text(kind)
            add_text(target)
        # Blanked lines drop out of the composed text, so the program checks'
        # records are part of the identity (c-preprocessor-conditionals.md).
        for test in self.conditional_tests:
            add_text(test.cache_record())
        return digest.hexdigest()


class SourceReadError(OSError):
    """A source file could not be read under the compiler's input contract."""


@dataclass(frozen=True, slots=True)
class SourceReadIdentity:
    """Copied identity of an opened source, independent of later path lookup."""

    path: str
    canonical: str
    version: tuple[int, int, int, int, int, int]

    @staticmethod
    def immutable_store_file(canonical: str) -> bool:
        """Whether a canonical path lies inside the read-only Nix store."""

        store = os.environ.get("NIX_STORE_DIR") or "/nix/store"
        return canonical.startswith(store.rstrip("/") + "/")

    def same_version(self, version: tuple[int, int, int, int, int, int]) -> bool:
        """Whether another stat version names the bytes this identity read.

        A store file never changes once written, but Nix's auto-optimise-store
        replaces it with a hard link to an identical file: its device, inode,
        link count and change time move while its mode, size and modification
        time do not. Only those last three are compared there.
        """

        if self.immutable_store_file(self.canonical):
            return version[2:5] == self.version[2:5]
        return version == self.version

    @staticmethod
    def file_version(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )

    def validate(self) -> None:
        try:
            if sys.platform == "win32":
                # Windows path stat and fstat can give st_ctime different
                # meanings (birth vs change time). Compare handles there.
                with open(self.path, "rb") as source_file:
                    version = self.file_version(os.fstat(source_file.fileno()))
            else:
                # Reopening a POSIX FIFO could block after its writer exits.
                version = self.file_version(os.stat(self.path))
            unchanged = os.path.normcase(os.path.realpath(self.path)) == self.canonical and self.same_version(version)
        except OSError as error:
            raise SourceReadError(f"source input changed after read: {self.path}: {error}") from error
        if not unchanged:
            raise SourceReadError(f"source input changed after read: {self.path}")


@dataclass(frozen=True, slots=True)
class SourceText:
    text: str
    identity: SourceReadIdentity


class SourceFileReader:
    """Own deterministic UTF-8 source reads for one compiler application.

    The compiler imposes no size ceiling of its own: a source file is read
    until the operating system reports end of file, and only genuine
    filesystem or allocation failures become diagnostics.
    """

    def read(self, path: str) -> str:
        return self.read_source(path).text

    def read_source(self, path: str) -> SourceText:
        """Correlate decoded bytes with the opened file and its requested name."""

        requested = os.path.join(os.getcwd(), path)
        try:
            canonical = os.path.normcase(os.path.realpath(requested))
            with open(requested, "rb") as source_file:
                identity = SourceReadIdentity(
                    requested, canonical, SourceReadIdentity.file_version(os.fstat(source_file.fileno()))
                )
                encoded = source_file.read()
                if not identity.same_version(SourceReadIdentity.file_version(os.fstat(source_file.fileno()))):
                    raise SourceReadError(f"source input changed during read: {requested}")
            identity.validate()
        except FileNotFoundError as error:
            raise SourceReadError(f"source file {path!r} not found") from error
        except OSError as error:
            raise SourceReadError(f"cannot read source file {path!r}: {error}") from error
        except MemoryError as error:
            raise SourceReadError(f"cannot allocate memory for source file {path!r}") from error
        try:
            text = encoded.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise SourceReadError(f"source file {path!r} is not valid UTF-8 at byte {error.start}") from error
        except MemoryError as error:
            raise SourceReadError(f"cannot allocate memory for source file {path!r}") from error
        nul = text.find("\0")
        if nul >= 0:
            raise SourceReadError(f"source file {path!r} contains a NUL byte at character {nul}")
        return SourceText(self.normalize_newlines(text), identity)

    @staticmethod
    def normalize_newlines(text: str) -> str:
        """CRLF and lone CR become LF, as every source reader and editor buffer sees them."""

        return text if "\r" not in text else text.replace("\r\n", "\n").replace("\r", "\n")


class FrontendFingerprint:
    """Own the source identity governing cached frontend representations."""

    def __init__(self, compiler_directory: str | None = None, source_directory: str | None = None) -> None:
        self.compiler_directory = os.path.abspath(
            compiler_directory or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.source_directory = os.path.abspath(
            source_directory or os.path.dirname(os.path.dirname(self.compiler_directory))
        )
        self._digest: str | None = None
        self._lock = threading.Lock()

    def digest(self) -> str:
        cached = self._digest
        if cached is not None:
            return cached
        with self._lock:
            if self._digest is None:
                self._digest = self._hash(self.files())
            return self._digest

    def files(self) -> tuple[str, ...]:
        paths = [
            os.path.join(self.source_directory, "language", "grammar.ebnf"),
            os.path.join(self.source_directory, "language", "ast.asdl"),
        ]
        for relative in ("syntax", "lexer", "parser", "frontend"):
            root = os.path.join(self.compiler_directory, relative)
            for current, _directories, filenames in os.walk(root):
                paths.extend(os.path.join(current, name) for name in filenames if name.endswith(".py"))
        return tuple(sorted(set(paths)))

    def _hash(self, paths: tuple[str, ...]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            relative_path = os.path.relpath(path, self.source_directory).replace(os.sep, "/")
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


class FrontendCacheDirectory:
    """Own placement of frontend-only cached representations."""

    def resolve(self, input_path: str | None = None) -> str:
        configured = os.environ.get("BTRC_CACHE_DIR")
        if configured:
            directory = configured
        else:
            start = os.path.dirname(os.path.abspath(input_path)) if input_path else os.getcwd()
            manifest = PackageUniverse.find_manifest(start)
            if manifest is not None:
                directory = os.path.join(os.path.dirname(manifest), ".btrc-cache")
            else:
                directory = os.path.join(self._user_root(), "btrc")
        os.makedirs(directory, exist_ok=True)
        return directory

    @staticmethod
    def _user_root() -> str:
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches")
        if sys.platform == "win32":  # pragma: no cover - unsupported dev platform
            return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
        return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


class StdlibAstCache:
    """Own the frontend's validated, content-addressed stdlib AST cache."""

    SCHEMA = 1
    PREFIX = "stdlib-"
    SUFFIX = ".ast.json"
    LEGACY_SUFFIX = ".ast"
    MAX_AGE_SECONDS = 30 * 24 * 3600

    def __init__(
        self,
        *,
        schema_version: int = SCHEMA,
        max_age_seconds: int = MAX_AGE_SECONDS,
        codec: AstJsonCodec | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.max_age_seconds = max_age_seconds
        self.codec = codec or AstJsonCodec()
        self._pruned_dirs: set[str] = set()

    def path(self, cache_dir: str, frontend_version: str, source: str) -> str:
        digest = hashlib.sha256()
        for part in (str(self.schema_version), frontend_version, source):
            encoded = part.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return os.path.join(cache_dir, f"{self.PREFIX}{digest.hexdigest()}{self.SUFFIX}")

    def load(self, path: str, content_hash: str) -> list | None:
        payload = self._read_json(path)
        if not self._valid_payload(payload, content_hash):
            return None
        try:
            declarations = [self.codec.decode(value) for value in payload["declarations"]]
        except (ValueError, TypeError, RecursionError):
            return None
        return declarations if all(hasattr(declaration, "source_file") for declaration in declarations) else None

    def store(self, path: str, content_hash: str, declarations: list) -> None:
        self._write_json(
            path,
            {
                "content_hash": content_hash,
                "declarations": [self.codec.encode(declaration) for declaration in declarations],
                "schema": self.schema_version,
            },
        )

    def prune(self, cache_dir: str) -> None:
        if cache_dir in self._pruned_dirs:
            return
        cutoff = time.time() - self.max_age_seconds
        try:
            with os.scandir(cache_dir) as entries:
                self._pruned_dirs.add(cache_dir)
                for entry in entries:
                    name = entry.name
                    if not name.startswith(self.PREFIX):
                        continue
                    try:
                        expired_json = name.endswith(self.SUFFIX) and entry.stat().st_mtime < cutoff
                        if name.endswith(self.LEGACY_SUFFIX) or expired_json:
                            os.remove(entry.path)
                    except OSError:
                        pass
        except OSError:
            return

    @staticmethod
    def source_hash(source: str) -> str:
        return hashlib.sha256(source.encode()).hexdigest()

    def _read_json(self, path: str):
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return None
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            encoded = b"".join(chunks)
            return json.loads(encoded.decode("utf-8"), parse_constant=self._reject_json_constant)
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError, MemoryError):
            return None
        finally:
            with suppress(OSError):
                os.close(descriptor)

    def _write_json(self, path: str, payload) -> None:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".btrc-stdlib-ast-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as cache_file:
                descriptor = -1
                cache_file.write(encoded)
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary_path, path)
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                os.remove(temporary_path)

    @staticmethod
    def _reject_json_constant(value: str):
        raise ValueError(f"invalid JSON constant: {value}")

    def _valid_payload(self, payload, content_hash: str) -> bool:
        return (
            isinstance(payload, dict)
            and set(payload) == {"content_hash", "declarations", "schema"}
            and payload["schema"] == self.schema_version
            and payload["content_hash"] == content_hash
            and isinstance(payload["declarations"], list)
        )


@dataclass(frozen=True)
class SourceDirective:
    """One import or deprecated btrc-include with its owned line range."""

    kind: str
    payload: object
    start: int
    end: int


class SourceDirectiveCachePort(Protocol):
    """Value-only persistence for directive spans keyed by complete source bytes."""

    def load_directives(self, source: str, input_path: str) -> tuple[tuple[int, int], ...] | None: ...

    def store_directives(self, source: str, ranges: tuple[tuple[int, int], ...], input_path: str) -> None: ...


class SourceDirectiveScanner:
    """Own comment-aware import/include discovery through the real lexer."""

    _BTRC_INCLUDE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')

    def __init__(self, cache: SourceDirectiveCachePort | None = None) -> None:
        self._cache = cache

    def scan(self, source: str, *, cache_input: str | None = None) -> list[SourceDirective]:
        """Return directives that own their complete source line range."""

        if self._cache is not None and cache_input is not None:
            ranges = self._cache.load_directives(source, cache_input)
            if ranges is not None:
                restored = self._restore(source, ranges)
                if restored is not None:
                    return restored
        directives = self._scan(source)
        if directives is None:
            return []  # malformed source: the main lexer/parser owns the error
        if self._cache is not None and cache_input is not None:
            self._cache.store_directives(source, tuple((item.start, item.end) for item in directives), cache_input)
        return directives

    def _restore(self, source: str, ranges: tuple[tuple[int, int], ...]) -> list[SourceDirective] | None:
        lines = source.split("\n")
        previous = 0
        directives = []
        for start, end in ranges:
            if not previous < start <= end <= len(lines):
                return None
            # Use the same lexer/parser for the actual fragment. If it requires
            # surrounding multiline-comment context, rescan the complete file.
            fragment = self._scan("\n".join(lines[start - 1 : end]))
            if fragment is None or len(fragment) != 1:
                return None
            [item] = fragment
            if item.start != 1 or item.end != end - start + 1:
                return None
            directives.append(SourceDirective(item.kind, item.payload, start, end))
            previous = end
        return directives

    def _scan(self, source: str) -> list[SourceDirective] | None:

        try:
            tokens = Lexer(source).tokenize()
        except Exception:
            return None

        first_on_line: dict[int, Token] = {}
        last_on_line: dict[int, Token] = {}
        for token in tokens:
            if token.type == TokenKind.EOF:
                continue
            first_on_line.setdefault(token.line, token)
            last_on_line[token.line] = token

        directives: list[SourceDirective] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == TokenKind.IMPORT and first_on_line.get(token.line) is token:
                spec, next_index = self._parse_spec_tokens(tokens, index + 1)
                if spec is None:
                    index += 1
                    continue
                end_token = tokens[next_index - 1]
                if last_on_line.get(end_token.line) is end_token:
                    directives.append(
                        SourceDirective(
                            "import",
                            spec,
                            token.line,
                            end_token.line,
                        )
                    )
                index = next_index
                continue
            if token.type == TokenKind.PREPROCESSOR and first_on_line.get(token.line) is token:
                include_path = self.btrc_include_path(token.value)
                if include_path is not None and last_on_line.get(token.line) is token:
                    directives.append(
                        SourceDirective(
                            "btrc_include",
                            include_path,
                            token.line,
                            token.line,
                        )
                    )
            index += 1
        return directives

    def btrc_include_path(self, preprocessor_text: str) -> str | None:
        """Return a quoted ``.btrc`` include path, or ``None`` for C includes."""

        match = self._BTRC_INCLUDE.match(preprocessor_text)
        return match.group(1) if match else None

    @staticmethod
    def _parse_spec_tokens(
        tokens: list[Token],
        start: int,
    ) -> tuple[object | None, int]:
        from ..parser.parser import Parser

        remaining = list(tokens[start:])
        remaining.append(Token(TokenKind.EOF, "", 0, 0))
        parser = Parser(remaining)
        try:
            spec = parser._parse_import_spec()
        except Exception:
            return None, start
        parser._match(TokenKind.SEMICOLON)
        return spec, start + parser.pos


class PreprocessorConditionalError(Exception):
    """A file-local preprocessor-conditional or program-check failure.

    The application reports it as a positioned ``SYNTAX`` failure in ``file``,
    whose line and column are that file's own, also for an imported file.
    """

    def __init__(self, message: str, file: str, line: int, col: int) -> None:
        self.message = message
        self.file = file
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


@dataclass(frozen=True, slots=True)
class ConditionalTest:
    """One evaluated test of a this-file or absent name in a ``#if`` family directive."""

    path: str
    name: str
    line: int
    col: int
    local: bool

    def cache_record(self) -> str:
        return f"{self.path}\0{self.name}\0{self.line}\0{self.col}\0{1 if self.local else 0}"


@dataclass(frozen=True, slots=True)
class ConditionedSource:
    """A file's text with its dead groups and conditional directives blanked."""

    text: str
    tests: tuple[ConditionalTest, ...] = ()


_COMPILER_RESERVED_PREFIXES = ("__btrc_", "__BTRC_", "__gpu_", "btrc_")
# A macro name may not take BTRC_ either: the emitted C defines BTRC_INCLUDE_*,
# BTRC_RT_* and BTRC_FREESTANDING. Other declarations may (stdlib enum values do).
_MACRO_RESERVED_PREFIXES = (*_COMPILER_RESERVED_PREFIXES, "BTRC_")
# The runtime's embedder hooks: btrc_rt.h defines each only under #ifndef, so a
# program may #define it first (test_runtime_dependencies.py pins the GPU one).
_RUNTIME_OVERRIDE_MACROS = frozenset({"BTRC_RT_ARENA_BYTES", "BTRC_RT_GPU_HEADER"})


class SourceMacroRules:
    """Own the per-directive ``#define``/``#undef`` name rules and macro identity.

    Conditioning applies them to its own file's live directives and the
    analyzer to the whole program, so both refuse a name with one message.
    """

    RUNTIME_OVERRIDES = _RUNTIME_OVERRIDE_MACROS

    @staticmethod
    def compiler_reserved_prefix(name: str) -> str | None:
        """The compiler-reserved prefix of a declaration name, if any."""

        return next((prefix for prefix in _COMPILER_RESERVED_PREFIXES if name.startswith(prefix)), None)

    @staticmethod
    def macro_reserved_prefix(name: str) -> str | None:
        """The compiler-reserved prefix of a macro name, ``BTRC_`` included."""

        return next((prefix for prefix in _MACRO_RESERVED_PREFIXES if name.startswith(prefix)), None)

    @classmethod
    def violation(cls, name: str, *, define: bool) -> str | None:
        """The message refusing ``#define``/``#undef`` of ``name``, if any."""

        if name == "defined":
            return "'defined' cannot be #define'd or #undef'd (C11 6.10.8p2)"
        if name in TokenVocabulary.canonical().keywords:
            return f"'{name}' is a reserved word and cannot be used as a name"
        prefix = cls.macro_reserved_prefix(name)
        if prefix is not None and not (define and name in _RUNTIME_OVERRIDE_MACROS):
            return (
                f"Macro name '{name}' uses the compiler-reserved '{prefix}' prefix"
                if define
                else f"Source #undef of compiler-owned C symbol '{name}' is not allowed"
            )
        if name.startswith("_"):
            subject = "Macro name" if define else "Source #undef name"
            return f"{subject} '{name}' is reserved by C11 at file scope"
        if HOSTED_ABI.owned_name(name):
            action = "Macro name" if define else "Source #undef of"
            return f"{action} compiler-owned hosted C symbol '{name}' is not allowed"
        if name in TARGET_FOREIGN_MACRO_NAMES:
            return f"'{name}' is set by C headers or compiler flags; btrc sources cannot #define or #undef it"
        return None

    @staticmethod
    def redefinition_message(name: str) -> str:
        return f"Macro '{name}' is redefined with a different replacement; #undef it first (C11 6.10.3p2)"

    @classmethod
    def same_definition(cls, first: SourceSymbolDirective, second: SourceSymbolDirective) -> bool:
        """C11 6.10.3p2: the same kind, parameters and normalized replacement."""

        return (
            first.function_like == second.function_like
            and first.parameter_order == second.parameter_order
            and first.variadic == second.variadic
            and first.invalid_parameters == second.invalid_parameters
            and cls.normalized_replacement(first.replacement) == cls.normalized_replacement(second.replacement)
        )

    @staticmethod
    def without_comments(text: str) -> str:
        """Replace every comment outside literals with one space."""

        pieces: list[str] = []
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                end = SourceSymbolDirective._skip_quoted(text, index, value)
                pieces.append(text[index:end])
                index = end
            elif text.startswith("//", index):
                pieces.append(" ")
                break
            elif text.startswith("/*", index):
                close = text.find("*/", index + 2)
                pieces.append(" ")
                index = len(text) if close < 0 else close + 2
            else:
                pieces.append(value)
                index += 1
        return "".join(pieces)

    @classmethod
    def normalized_replacement(cls, text: str) -> str:
        """Comments become one space, whitespace runs outside literals one space, ends trimmed."""

        text = cls.without_comments(text)
        pieces: list[str] = []
        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                end = SourceSymbolDirective._skip_quoted(text, index, value)
                pieces.append(text[index:end])
                index = end
            elif value in " \t\f\v\r\n":
                while index < len(text) and text[index] in " \t\f\v\r\n":
                    index += 1
                pieces.append(" ")
            else:
                pieces.append(value)
                index += 1
        return "".join(pieces).strip()


class ConditionalEnvironment:
    """Own the selected target's predefined macros and ``#if`` name classification.

    The environment is the target only: a file's own ``#define`` lines are
    tracked by the walk. Without a target (an unsupported host in the LSP) it
    still classifies names, and the first evaluated conditional fails (D13).
    """

    TARGET = "target"
    RESERVED = "reserved"
    FOREIGN = "foreign"
    ABSENT = "absent"

    _target_names: frozenset[str] | None = None
    _hosted_names: frozenset[str] | None = None

    def __init__(self, target: PackageTarget | None, package_defines: Mapping[str, str] | None = None) -> None:
        self._target = target
        self._package_defines = dict(sorted((package_defines or {}).items()))
        self._values: dict[str, int] | None = None
        self._identity: str | None = None

    @classmethod
    def for_packages(cls, packages: ResolvedPackages) -> ConditionalEnvironment:
        """The resolved target, with every package ``-D`` name of the graph as foreign."""

        plan = packages.native_plan
        defines: dict[str, str] = {}
        for item in plan.declarations:
            if item.kind == "define":
                defines.setdefault(item.value, item.package)
        for package in sorted(plan.packages, key=lambda node: node.name):
            for item in package.native:
                if item.kind == "define":
                    defines.setdefault(item.value, item.package)
        return cls(plan.target, defines)

    @classmethod
    def for_host(cls) -> ConditionalEnvironment:
        """The host target, or none on a host btrc does not target."""

        try:
            return cls(PackageTarget.parse(None))
        except ValueError:
            return cls(None)

    @classmethod
    def every_target(cls) -> tuple[ConditionalEnvironment, ...]:
        return tuple(cls(PackageTarget(row.operating_system, row.architecture)) for row in TARGET_ROWS)

    @property
    def target(self) -> PackageTarget | None:
        return self._target

    @property
    def label(self) -> str:
        target = self._target
        return f"{target.operating_system}-{target.architecture}" if target is not None else ""

    def require(self, path: str, line: int, col: int) -> None:
        """Fail an evaluated conditional when there is no target (D13)."""

        if self._target is None:
            raise PreprocessorConditionalError(
                "preprocessor conditionals need a target; this host is not a btrc target, so pass --target OS-ARCH",
                path,
                line,
                col,
            )

    def _selected(self) -> dict[str, int]:
        if self._values is None:
            target = self._target
            values: dict[str, int] = {}
            if target is not None:
                for row in TARGET_PREDEFINED_MACRO_ROWS:
                    if (not row.operating_systems or target.operating_system in row.operating_systems) and (
                        not row.architectures or target.architecture in row.architectures
                    ):
                        values[row.name] = row.value
            self._values = values
        return self._values

    def target_value(self, name: str) -> int:
        return self._selected().get(name, 0)

    def selects(self, name: str) -> bool:
        """Whether the selected target defines a target macro."""

        return name in self._selected()

    @classmethod
    def _target_macro_names(cls) -> frozenset[str]:
        if cls._target_names is None:
            cls._target_names = frozenset(row.name for row in TARGET_PREDEFINED_MACRO_ROWS) | frozenset(
                TARGET_UNDEFINED_MACRO_NAMES
            )
        return cls._target_names

    @classmethod
    def hosted_names(cls) -> frozenset[str]:
        """Every hosted-ABI name of ``[names]`` and ``[platform]``."""

        if cls._hosted_names is None:
            abi = HOSTED_ABI
            cls._hosted_names = (
                abi.owned_names
                | abi.function_names
                | abi.macros
                | abi.objects
                | abi.types
                | abi.typedefs
                | abi.platform_function_names
                | abi.platform_macro_names
                | abi.platform_object_names
                | abi.platform_type_names
                | abi.platform_typedef_names
            )
        return cls._hosted_names

    def classify(self, name: str) -> str:
        """The class of a name that is not one of the file's own macros."""

        if name in self._target_macro_names():
            return self.TARGET
        if name.startswith("_"):
            return self.RESERVED
        if (
            name in self.hosted_names()
            or name in TARGET_FOREIGN_MACRO_NAMES
            or name.startswith(("btrc_", "BTRC_"))
            or name in self._package_defines
        ):
            return self.FOREIGN
        return self.ABSENT

    @staticmethod
    def reserved_message(name: str) -> str:
        return f"'{name}' is reserved for the C implementation and is not a btrc target macro; #if cannot test it"

    def foreign_message(self, name: str) -> str:
        package = self._package_defines.get(name)
        if package is not None and not (
            name in self.hosted_names() or name in TARGET_FOREIGN_MACRO_NAMES or name.startswith(("btrc_", "BTRC_"))
        ):
            return (
                f"'{name}' is a C compiler define of package '{package}'; "
                "#if is evaluated before C compilation and cannot test it"
            )
        return (
            f"'{name}' is defined by C headers or C compiler flags, not by btrc; "
            "#if is evaluated before C compilation and cannot test it"
        )

    def cache_identity(self) -> str:
        """Digest of the target label, its selected rows, the undefined names and the foreign set."""

        if self._identity is None:
            digest = hashlib.sha256()

            def add_text(value: str) -> None:
                encoded = value.encode("utf-8")
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)

            add_text("btrc-conditional-environment-v1")
            add_text(self.label)
            for name, value in sorted(self._selected().items()):
                add_text(f"{name}={value}")
            for name in TARGET_UNDEFINED_MACRO_NAMES:
                add_text(name)
            for name in sorted(self.hosted_names() | frozenset(TARGET_FOREIGN_MACRO_NAMES)):
                add_text(name)
            for name, package in self._package_defines.items():
                add_text(f"{package}:{name}")
            self._identity = digest.hexdigest()
        return self._identity


@dataclass(slots=True)
class _ConditionalAtom:
    """One classified ``#if`` operand or operator, positioned in the file."""

    kind: str  # "op", "number", "absent"
    text: str
    line: int
    col: int
    value: int = 0
    unsigned: bool = False
    tests: tuple[ConditionalTest, ...] = ()


@dataclass(slots=True)
class _ConditionalNode:
    """One parsed ``#if`` subexpression."""

    kind: str  # "leaf", "unary", "binary", "conditional"
    atom: _ConditionalAtom
    operands: tuple[_ConditionalNode, ...] = ()


_INTMAX_MIN = -(1 << 63)
_INTMAX_MAX = (1 << 63) - 1
_UINTMAX_MAX = (1 << 64) - 1
_EXPANSION_LIMIT = 4096
_CONDITIONAL_BINARY_PRECEDENCE = MappingProxyType(
    {
        "||": 1,
        "&&": 2,
        "|": 3,
        "^": 4,
        "&": 5,
        "==": 6,
        "!=": 6,
        "<": 7,
        ">": 7,
        "<=": 7,
        ">=": 7,
        "<<": 8,
        ">>": 8,
        "+": 9,
        "-": 9,
        "*": 10,
        "/": 10,
        "%": 10,
    }
)
_CONDITIONAL_UNARY = frozenset({"+", "-", "~", "!"})
_CONDITIONAL_PUNCTUATION = frozenset(_CONDITIONAL_BINARY_PRECEDENCE) | _CONDITIONAL_UNARY | {"?", ":", "(", ")"}
_WIDE_CHARACTER_PREFIXES = frozenset({"L", "u", "U"})


class ConditionalExpression:
    """Evaluate one ``#if``/``#elif`` payload by C11 6.10.1 in 64-bit integers.

    The steps run in C11 6.10.1p4's order, each reporting its first error in
    token order: resolve ``defined``, expand this file's object-like macros,
    classify the remaining tokens, parse, then evaluate with short-circuiting.
    Steps 1-4 apply to every operand; identifier and arithmetic errors only
    to evaluated ones.
    """

    def __init__(
        self,
        environment: ConditionalEnvironment,
        path: str,
        macros: Mapping[str, SourceSymbolDirective],
    ) -> None:
        self._environment = environment
        self._path = path
        self._macros = macros

    def _error(self, message: str, line: int, col: int) -> PreprocessorConditionalError:
        return PreprocessorConditionalError(message, self._path, line, col)

    # -- Lexing -----------------------------------------------------------

    @staticmethod
    def pre_scan(text: str) -> tuple[int, str] | None:
        """The offset and spelling of the first ``#``, ``##`` or ``%:`` outside literals and comments."""

        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = SourceSymbolDirective._skip_quoted(text, index, value)
                continue
            if text.startswith("//", index):
                return None
            if text.startswith("/*", index):
                close = text.find("*/", index + 2)
                if close < 0:
                    return None
                index = close + 2
                continue
            if value == "#":
                return index, "##" if text.startswith("##", index) else "#"
            if text.startswith("%:", index):
                return index, "%:"
            index += 1
        return None

    def lex(self, text: str, line: int, col: int) -> list[Token]:
        """Lex a payload or replacement in place; a lexer failure is E0 at its position."""

        try:
            tokens = Lexer(text, self._path, line=line, col=col).tokenize()
        except LexerError as error:
            message = str(error).removesuffix(f" at {error.line}:{error.col}")
            raise self._error(message, error.line, error.col) from error
        return [token for token in tokens if token.type != TokenKind.EOF]

    def payload_tokens(self, text: str, line: int, col: int) -> list[Token]:
        """Pre-scan, then lex, a ``#if``/``#elif`` payload (E7, E0)."""

        found = self.pre_scan(text)
        if found is not None:
            offset, spelling = found
            raise self._error(f"'{spelling}' is not allowed in a #if expression", line, col + offset)
        return self.lex(text, line, col)

    # -- Steps 1-3: defined, expansion, classification --------------------

    @staticmethod
    def name_token(token: Token) -> bool:
        """An identifier, or a keyword, which ``#if`` reads as the identifier it spells."""

        return token.type == TokenKind.IDENT or token.value in TokenVocabulary.canonical().keywords

    def _test(self, name: str, line: int, col: int, *, local: bool) -> ConditionalTest:
        return ConditionalTest(self._path, name, line, col, local)

    def defined_value(self, name: str, line: int, col: int) -> _ConditionalAtom:
        """``defined NAME`` classified as ``#ifdef NAME`` is (I2, I3)."""

        category = self._environment.classify(name)
        if category == ConditionalEnvironment.TARGET:
            selected = int(self._environment.selects(name))
            return _ConditionalAtom("number", "defined", line, col, selected)
        if category == ConditionalEnvironment.RESERVED:
            raise self._error(ConditionalEnvironment.reserved_message(name), line, col)
        if name in self._macros:
            return _ConditionalAtom("number", "defined", line, col, 1, tests=(self._test(name, line, col, local=True),))
        if category == ConditionalEnvironment.FOREIGN:
            raise self._error(self._environment.foreign_message(name), line, col)
        return _ConditionalAtom("number", "defined", line, col, 0, tests=(self._test(name, line, col, local=False),))

    def _resolve_defined(self, tokens: list[Token]) -> list[Token | _ConditionalAtom]:
        resolved: list[Token | _ConditionalAtom] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if not (token.type == TokenKind.IDENT and token.value == "defined"):
                resolved.append(token)
                index += 1
                continue
            index += 1
            parenthesized = index < len(tokens) and tokens[index].type == TokenKind.LPAREN
            if parenthesized:
                index += 1
            if index >= len(tokens):
                raise self._error("'defined' needs a macro name", token.line, token.col)
            operand = tokens[index]
            if not self.name_token(operand) or operand.type in {TokenKind.TRUE, TokenKind.FALSE}:
                raise self._error(
                    f"'defined' needs a macro name, got '{operand.value}'",
                    operand.line,
                    operand.col,
                )
            index += 1
            if parenthesized:
                if index >= len(tokens) or tokens[index].type != TokenKind.RPAREN:
                    raise self._error("'defined(' needs a closing ')'", token.line, token.col)
                index += 1
            atom = self.defined_value(operand.value, operand.line, operand.col)
            resolved.append(atom)
        return resolved

    def _expand(self, items: list[Token | _ConditionalAtom]) -> list[tuple[Token | _ConditionalAtom, tuple]]:
        """Expand this file's object-like macros (I4-I8, E16); returns items with their origins.

        An expanded token sits at the outermost macro name in the directive
        and carries the record of every macro expanded to produce it.
        """

        expanded: list[tuple[Token | _ConditionalAtom, tuple]] = []
        for item in items:
            if isinstance(item, Token) and self._local_macro(item.value) and item.type == TokenKind.IDENT:
                anchor = item
                produced = self._expansion(item.value, anchor, frozenset())
                if len(expanded) + len(produced) > _EXPANSION_LIMIT:
                    raise self._error(
                        f"#if expression expands to more than {_EXPANSION_LIMIT} tokens", anchor.line, anchor.col
                    )
                expanded.extend(produced)
            else:
                expanded.append((item, ()))
                if len(expanded) > _EXPANSION_LIMIT:
                    raise self._error(
                        f"#if expression expands to more than {_EXPANSION_LIMIT} tokens", item.line, item.col
                    )
        return expanded

    def _local_macro(self, name: str) -> bool:
        return name in self._macros

    def _expansion(self, name: str, anchor: Token, active: frozenset[str]) -> list[tuple[Token, tuple]]:
        directive = self._macros[name]
        record = (self._test(name, anchor.line, anchor.col, local=True),)
        if directive.function_like:
            raise self._error(
                f"Function-like macro '{name}' cannot be used in #if; btrc expands only object-like macros there",
                anchor.line,
                anchor.col,
            )
        if directive.uses_token_paste():
            raise self._error(f"Macro '{name}' uses '##', which #if does not evaluate", anchor.line, anchor.col)
        replacement = directive.replacement
        found = self.pre_scan(replacement)
        if found is not None:
            raise self._error(f"'{found[1]}' is not allowed in a #if expression", anchor.line, anchor.col)
        try:
            tokens = [token for token in Lexer(replacement, self._path).tokenize() if token.type != TokenKind.EOF]
        except LexerError as error:
            message = str(error).removesuffix(f" at {error.line}:{error.col}")
            raise self._error(message, anchor.line, anchor.col) from error
        if not tokens:
            raise self._error(
                f"Macro '{name}' expands to nothing in #if; test it with defined({name})", anchor.line, anchor.col
            )
        produced: list[tuple[Token, tuple]] = []
        inner_active = active | {name}
        for token in tokens:
            if token.type == TokenKind.IDENT and token.value == "defined":
                raise self._error(
                    f"Macro '{name}' expands to 'defined'; C11 leaves that undefined", anchor.line, anchor.col
                )
            if token.type == TokenKind.IDENT and self._local_macro(token.value):
                if token.value in inner_active:
                    raise self._error(f"Macro '{token.value}' expands to itself in #if", anchor.line, anchor.col)
                for inner, origin in self._expansion(token.value, anchor, inner_active):
                    produced.append((inner, record + origin))
                    if len(produced) > _EXPANSION_LIMIT:
                        raise self._error(
                            f"#if expression expands to more than {_EXPANSION_LIMIT} tokens", anchor.line, anchor.col
                        )
                continue
            positioned = Token(token.type, token.value, anchor.line, anchor.col)
            produced.append((positioned, record))
            if len(produced) > _EXPANSION_LIMIT:
                raise self._error(
                    f"#if expression expands to more than {_EXPANSION_LIMIT} tokens", anchor.line, anchor.col
                )
        return produced

    def _classify(self, expanded: list[tuple[Token | _ConditionalAtom, tuple]]) -> list[_ConditionalAtom]:
        atoms: list[_ConditionalAtom] = []
        for index, (item, origin) in enumerate(expanded):
            if isinstance(item, _ConditionalAtom):
                atoms.append(item)
                continue
            token = item
            kind = token.type
            if kind == TokenKind.INT_LIT:
                try:
                    value = LiteralDecoder.parse_integer_value(token.value)
                except ValueError:
                    raise self._error(f"Invalid integer literal '{token.value}'", token.line, token.col) from None
                unsigned = "u" in LiteralDecoder.integer_parts(token.value)[1] or value > _INTMAX_MAX
                atoms.append(_ConditionalAtom("number", token.value, token.line, token.col, value, unsigned, origin))
            elif kind == TokenKind.CHAR_LIT:
                value = LiteralDecoder.decode_character(token.value)
                if value is None or value > 127:
                    raise self._error(
                        f"Character constant {token.value} in #if has a target-dependent value; write its integer value",
                        token.line,
                        token.col,
                    )
                atoms.append(_ConditionalAtom("number", token.value, token.line, token.col, value, False, origin))
            elif kind in {TokenKind.STRING_LIT, TokenKind.FSTRING_LIT}:
                raise self._error("A string literal cannot appear in a #if expression", token.line, token.col)
            elif kind == TokenKind.FLOAT_LIT:
                raise self._error(
                    f"Floating constant '{token.value}' in #if expression; #if needs integer constants",
                    token.line,
                    token.col,
                )
            elif kind == TokenKind.SIZEOF:
                raise self._error(
                    "sizeof cannot be evaluated in #if; test a target macro such as __SIZEOF_INT__",
                    token.line,
                    token.col,
                )
            elif kind in {TokenKind.TRUE, TokenKind.FALSE}:
                atoms.append(
                    _ConditionalAtom(
                        "number", token.value, token.line, token.col, int(kind == TokenKind.TRUE), False, origin
                    )
                )
            elif self.name_token(token):
                following = expanded[index + 1][0] if index + 1 < len(expanded) else None
                if (
                    token.value in _WIDE_CHARACTER_PREFIXES
                    and isinstance(following, Token)
                    and following.type == TokenKind.CHAR_LIT
                    and following.line == token.line
                    and following.col == token.col + len(token.value)
                ):
                    raise self._error(
                        f"Wide character constant {token.value}{following.value} in #if; write its integer value",
                        token.line,
                        token.col,
                    )
                category = self._environment.classify(token.value)
                if category == ConditionalEnvironment.TARGET:
                    atoms.append(
                        _ConditionalAtom(
                            "number",
                            token.value,
                            token.line,
                            token.col,
                            self._environment.target_value(token.value),
                            False,
                            origin,
                        )
                    )
                elif category == ConditionalEnvironment.RESERVED:
                    raise self._error(ConditionalEnvironment.reserved_message(token.value), token.line, token.col)
                elif category == ConditionalEnvironment.FOREIGN:
                    raise self._error(self._environment.foreign_message(token.value), token.line, token.col)
                else:
                    atoms.append(_ConditionalAtom("absent", token.value, token.line, token.col, tests=origin))
            elif token.value in _CONDITIONAL_PUNCTUATION:
                atoms.append(_ConditionalAtom("op", token.value, token.line, token.col, tests=origin))
            else:
                raise self._error(f"'{token.value}' is not allowed in a #if expression", token.line, token.col)
        return atoms

    # -- Step 4: parse ------------------------------------------------------

    def parse(self, atoms: list[_ConditionalAtom]) -> _ConditionalNode:
        parser = _ConditionalParser(self, atoms)
        node = parser.expression()
        if parser.index < len(atoms):
            atom = atoms[parser.index]
            if atom.kind == "op" and atom.text == ")":
                raise self._error("Unmatched ')' in #if expression", atom.line, atom.col)
            if atom.kind == "op" and atom.text == ":":
                raise self._error("':' is not allowed in a #if expression", atom.line, atom.col)
            raise self._error(f"Missing operator before '{atom.text}' in #if expression", atom.line, atom.col)
        return node

    # -- Step 5: evaluate -------------------------------------------------

    def evaluate(self, tokens: list[Token], tests: list[ConditionalTest]) -> bool:
        """Steps 1-5 over a lexed payload; appends evaluated records to ``tests``."""

        atoms = self._classify(self._expand(self._resolve_defined(tokens)))
        node = self.parse(atoms)
        value, _unsigned = self._value(node, True, tests)
        return value != 0

    def _static_unsigned(self, node: _ConditionalNode) -> bool:
        if node.kind == "leaf":
            return node.atom.unsigned
        operator = node.atom.text
        if node.kind == "unary":
            return False if operator == "!" else self._static_unsigned(node.operands[0])
        if node.kind == "conditional":
            return self._static_unsigned(node.operands[1]) or self._static_unsigned(node.operands[2])
        if operator in {"&&", "||", "<", ">", "<=", ">=", "==", "!="}:
            return False
        if operator in {"<<", ">>"}:
            return self._static_unsigned(node.operands[0])
        return self._static_unsigned(node.operands[0]) or self._static_unsigned(node.operands[1])

    @staticmethod
    def _record(atom: _ConditionalAtom, tests: list[ConditionalTest]) -> None:
        for test in atom.tests:
            if not any(existing is test for existing in tests):
                tests.append(test)

    def _convert(self, value: int, unsigned: bool, operator: _ConditionalAtom) -> int:
        """Convert one evaluated operand to unsigned (A5 for a negative signed value)."""

        if not unsigned and value < 0:
            raise self._error(
                f"#if expression converts negative value {value} to unsigned for '{operator.text}'",
                operator.line,
                operator.col,
            )
        return value

    def _signed_result(self, value: int, operator: _ConditionalAtom) -> int:
        if not _INTMAX_MIN <= value <= _INTMAX_MAX:
            raise self._error("Integer overflow in #if expression", operator.line, operator.col)
        return value

    def _value(self, node: _ConditionalNode, evaluated: bool, tests: list[ConditionalTest]) -> tuple[int, bool]:
        atom = node.atom
        if node.kind == "leaf":
            if evaluated:
                self._record(atom, tests)
                if atom.kind == "absent":
                    raise self._error(
                        f"Identifier '{atom.text}' in #if is not a macro defined earlier in this file "
                        f"or a target macro; test it with defined({atom.text})",
                        atom.line,
                        atom.col,
                    )
            return atom.value, atom.unsigned
        operator = atom.text
        if node.kind == "unary":
            value, unsigned = self._value(node.operands[0], evaluated, tests)
            if not evaluated:
                return 0, False if operator == "!" else unsigned
            self._record(atom, tests)
            if operator == "!":
                return int(value == 0), False
            if operator == "+":
                return value, unsigned
            if operator == "~":
                return ((~value) & _UINTMAX_MAX, True) if unsigned else (~value, False)
            if unsigned:
                return (-value) & _UINTMAX_MAX, True
            return self._signed_result(-value, atom), False
        if node.kind == "conditional":
            condition, _ = self._value(node.operands[0], evaluated, tests)
            unsigned = self._static_unsigned(node)
            if evaluated:
                self._record(atom, tests)
            take_first = condition != 0
            first, _ = self._value(node.operands[1], evaluated and take_first, tests)
            second, _ = self._value(node.operands[2], evaluated and not take_first, tests)
            if not evaluated:
                return 0, unsigned
            chosen_node = node.operands[1] if take_first else node.operands[2]
            chosen = first if take_first else second
            if unsigned:
                chosen = self._convert(chosen, self._static_unsigned(chosen_node), atom)
            return chosen, unsigned
        left_node, right_node = node.operands
        if operator in {"&&", "||"}:
            left, _ = self._value(left_node, evaluated, tests)
            if evaluated:
                self._record(atom, tests)
            short = (left == 0) if operator == "&&" else (left != 0)
            right, _ = self._value(right_node, evaluated and not short, tests)
            if not evaluated:
                return 0, False
            if short:
                return (0 if operator == "&&" else 1), False
            return int(right != 0), False
        left, left_unsigned = self._value(left_node, evaluated, tests)
        right, right_unsigned = self._value(right_node, evaluated, tests)
        if operator in {"<<", ">>"}:
            unsigned = left_unsigned
        else:
            unsigned = left_unsigned or right_unsigned
        result_unsigned = False if operator in {"<", ">", "<=", ">=", "==", "!="} else unsigned
        if not evaluated:
            return 0, result_unsigned
        self._record(atom, tests)
        if operator in {"<<", ">>"}:
            if (right_unsigned and right >= 64) or (not right_unsigned and not 0 <= right < 64):
                raise self._error(f"Shift count {right} is out of range in #if expression", atom.line, atom.col)
            if operator == ">>":
                return left >> right, left_unsigned
            if left_unsigned:
                return (left << right) & _UINTMAX_MAX, True
            if left < 0:
                raise self._error("Left shift of negative value in #if expression", atom.line, atom.col)
            return self._signed_result(left << right, atom), False
        if unsigned:
            left = self._convert(left, left_unsigned, atom)
            right = self._convert(right, right_unsigned, atom)
        if operator in {"/", "%"}:
            if right == 0:
                noun = "Division" if operator == "/" else "Remainder"
                raise self._error(f"{noun} by zero in #if expression", atom.line, atom.col)
            if not unsigned and left == _INTMAX_MIN and right == -1:
                raise self._error("Integer overflow in #if expression", atom.line, atom.col)
            quotient = abs(left) // abs(right)
            if (left < 0) != (right < 0):
                quotient = -quotient
            return (quotient if operator == "/" else left - quotient * right), unsigned
        comparisons = {
            "<": left < right,
            ">": left > right,
            "<=": left <= right,
            ">=": left >= right,
            "==": left == right,
            "!=": left != right,
        }
        if operator in comparisons:
            return int(comparisons[operator]), False
        if operator == "&":
            result = left & right
        elif operator == "^":
            result = left ^ right
        elif operator == "|":
            result = left | right
        elif operator == "+":
            result = left + right
        elif operator == "-":
            result = left - right
        else:
            result = left * right
        if unsigned:
            return result & _UINTMAX_MAX, True
        return self._signed_result(result, atom), False


class _ConditionalParser:
    """Recursive descent over classified ``#if`` atoms (E1-E7)."""

    def __init__(self, owner: ConditionalExpression, atoms: list[_ConditionalAtom]) -> None:
        self._owner = owner
        self._atoms = atoms
        self.index = 0

    def _peek(self) -> _ConditionalAtom | None:
        return self._atoms[self.index] if self.index < len(self._atoms) else None

    def _is_op(self, atom: _ConditionalAtom | None, *spellings: str) -> bool:
        return atom is not None and atom.kind == "op" and atom.text in spellings

    def expression(self) -> _ConditionalNode:
        condition = self._binary(1)
        question = self._peek()
        if not self._is_op(question, "?"):
            return condition
        self.index += 1
        first = self.expression()
        colon = self._peek()
        if not self._is_op(colon, ":"):
            raise self._owner._error("'?' in #if expression needs ':'", question.line, question.col)
        self.index += 1
        second = self.expression()
        return _ConditionalNode("conditional", question, (condition, first, second))

    def _binary(self, minimum: int) -> _ConditionalNode:
        left = self._unary()
        while True:
            operator = self._peek()
            if operator is None or operator.kind != "op":
                return left
            precedence = _CONDITIONAL_BINARY_PRECEDENCE.get(operator.text)
            if precedence is None or precedence < minimum:
                return left
            self.index += 1
            right = self._binary(precedence + 1)
            left = _ConditionalNode("binary", operator, (left, right))

    def _unary(self) -> _ConditionalNode:
        atom = self._peek()
        if self._is_op(atom, *_CONDITIONAL_UNARY):
            self.index += 1
            self._require_operand(atom)
            return _ConditionalNode("unary", atom, (self._unary(),))
        return self._primary()

    def _require_operand(self, after: _ConditionalAtom) -> None:
        if self._peek() is None:
            raise self._owner._error(
                f"#if expression ends after '{after.text}'; expected an operand", after.line, after.col
            )

    def _primary(self) -> _ConditionalNode:
        atom = self._peek()
        if atom is None:
            previous = self._atoms[self.index - 1]
            raise self._owner._error(
                f"#if expression ends after '{previous.text}'; expected an operand", previous.line, previous.col
            )
        if atom.kind != "op":
            self.index += 1
            return _ConditionalNode("leaf", atom)
        if atom.text == "(":
            self.index += 1
            if self._peek() is None:
                raise self._owner._error("Unmatched '(' in #if expression", atom.line, atom.col)
            inner = self.expression()
            close = self._peek()
            if not self._is_op(close, ")"):
                if close is None:
                    raise self._owner._error("Unmatched '(' in #if expression", atom.line, atom.col)
                if close.kind == "op" and close.text == ":":
                    raise self._owner._error("':' is not allowed in a #if expression", close.line, close.col)
                raise self._owner._error(
                    f"Missing operator before '{close.text}' in #if expression", close.line, close.col
                )
            self.index += 1
            return inner
        if atom.text == ":":
            raise self._owner._error("':' is not allowed in a #if expression", atom.line, atom.col)
        raise self._owner._error(f"Expected an operand in #if expression, got '{atom.text}'", atom.line, atom.col)


@dataclass(slots=True)
class _ConditionalEntry:
    """One open if-section on the walk's stack."""

    token: Token
    name: str
    state: str  # "taking", "seeking" or "done"
    else_seen: bool = False


_CONDITIONAL_CANDIDATE = re.compile(r"^[ \t\f\v]*(?:#[ \t\f\v]*(?:if|el|en|er|\\|\?\?/|/\*)|%:|\?\?=)", re.MULTILINE)
_CONDITIONAL_NAMES = frozenset({"if", "ifdef", "ifndef", "elif", "else", "endif", "elifdef", "elifndef"})
_DIRECTIVE_SPACE = " \t\f\v"
_C11_TRIGRAPH = re.compile(r"\?\?[=/'()!<>-]")


class SourceConditionals:
    """Condition one file's text for one target (C11 6.10.1, D20).

    The result has exactly the raw file's lines: every conditional-directive
    line and every line of a dead group becomes empty, and live lines are
    byte-identical. A file with no candidate line is returned untouched.
    """

    def __init__(self, environment: ConditionalEnvironment) -> None:
        self._environment = environment

    @property
    def environment(self) -> ConditionalEnvironment:
        return self._environment

    @staticmethod
    def candidate(text: str) -> bool:
        """Whether some line could spell a conditional directive (the slow path)."""

        return _CONDITIONAL_CANDIDATE.search(text) is not None

    @staticmethod
    def unclosed_comment(text: str) -> int | None:
        """The offset of a ``/*`` that does not close on the directive's line (D15)."""

        index = 0
        while index < len(text):
            value = text[index]
            if value in {'"', "'"}:
                index = SourceSymbolDirective._skip_quoted(text, index, value)
                continue
            if text.startswith("//", index):
                return None
            if text.startswith("/*", index):
                close = text.find("*/", index + 2)
                if close < 0:
                    return index
                index = close + 2
                continue
            index += 1
        return None

    @staticmethod
    def directive_whitespace(text: str) -> int | None:
        """The offset of a ``\\f`` or ``\\v`` after a directive's ``#`` (D17)."""

        return next((offset for offset in range(1, len(text)) if text[offset] in "\f\v"), None)

    def condition(self, text: str, path: str) -> ConditionedSource:
        if not self.candidate(text):
            return ConditionedSource(text)
        return _ConditionalWalk(self._environment, path, text).run()


class _ConditionalWalk:
    """One slow-path conditioning of one file: raw lex, shape checks, walk, blanking."""

    def __init__(self, environment: ConditionalEnvironment, path: str, text: str) -> None:
        self._environment = environment
        self._path = path
        self._text = text
        self._lines = text.split("\n")
        self._macros: dict[str, SourceSymbolDirective] = {}
        self._tests: list[ConditionalTest] = []
        self._expression = ConditionalExpression(environment, path, self._macros)

    def _error(self, message: str, line: int, col: int) -> PreprocessorConditionalError:
        return PreprocessorConditionalError(message, self._path, line, col)

    # -- Directive anatomy --------------------------------------------------

    @staticmethod
    def name_span(text: str) -> tuple[int, int]:
        """The start and end of a directive's name: the longest identifier after ``#`` and spaces."""

        start = 1
        while start < len(text) and text[start] in _DIRECTIVE_SPACE:
            start += 1
        end = start
        if end < len(text) and (text[end] == "_" or (text[end].isascii() and text[end].isalpha())):
            end += 1
            while end < len(text) and (text[end] == "_" or (text[end].isascii() and text[end].isalnum())):
                end += 1
        return start, end

    @classmethod
    def directive_name(cls, text: str) -> str:
        start, end = cls.name_span(text)
        return text[start:end]

    @staticmethod
    def splice_offset(text: str) -> int | None:
        """The offset of the first ``\\`` or ``??/`` that splices a directive's line."""

        newline = text.find("\n")
        if newline < 0:
            return None
        if text[:newline].endswith("??/"):
            return newline - 3
        return newline - 1

    # -- Shape checks (C11 translation phases 1-3) --------------------------

    def _position(self, token: Token, offset: int) -> tuple[int, int]:
        """The file position of ``offset`` inside a directive token's text."""

        line, col = token.line, token.col
        for character in token.value[:offset]:
            if character == "\n":
                line, col = line + 1, 1
            else:
                col += 1
        return line, col

    def _shape_error(self, message: str, token: Token, offset: int) -> PreprocessorConditionalError:
        line, col = self._position(token, offset)
        return self._error(message, line, col)

    def _check_conditional_shape(self, token: Token) -> None:
        text = token.value
        previous = self._lines[token.line - 2] if token.line >= 2 else ""
        if previous.endswith("??/"):
            raise self._error("multi-line preprocessor directives are unsupported", token.line - 1, len(previous) - 2)
        if previous.endswith("\\"):
            raise self._error("multi-line preprocessor directives are unsupported", token.line - 1, len(previous))
        trigraph = _C11_TRIGRAPH.search(text)
        if trigraph is not None:
            raise self._shape_error("C11 trigraphs in preprocessor directives are unsupported", token, trigraph.start())
        splice = self.splice_offset(text)
        if splice is not None:
            raise self._shape_error("multi-line preprocessor directives are unsupported", token, splice)
        whitespace = SourceConditionals.directive_whitespace(text)
        if whitespace is not None:
            raise self._shape_error(
                "only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)",
                token,
                whitespace,
            )
        unclosed = SourceConditionals.unclosed_comment(text)
        if unclosed is not None:
            raise self._shape_error(
                "a comment in a preprocessor directive must close on the same line", token, unclosed
            )

    def _check_dead_directive_shape(self, token: Token) -> None:
        splice = self.splice_offset(token.value)
        if splice is not None:
            raise self._shape_error("multi-line preprocessor directives are unsupported", token, splice)
        unclosed = SourceConditionals.unclosed_comment(token.value)
        if unclosed is not None:
            raise self._shape_error(
                "a comment in a preprocessor directive must close on the same line", token, unclosed
            )

    def _check_shapes(self, tokens: list[Token]) -> None:
        first_on_line: dict[int, Token] = {}
        for token in tokens:
            first_on_line.setdefault(token.line, token)
        for line_number in sorted(first_on_line):
            token = first_on_line[line_number]
            line = self._lines[line_number - 1]
            indent = len(line) - len(line.lstrip(_DIRECTIVE_SPACE))
            if token.col != indent + 1:
                continue
            for spelling in ("%:", "??="):
                if line.startswith(spelling, indent):
                    raise self._error(
                        f"'{spelling}' is not supported as a spelling of '#'; write '#'", line_number, indent + 1
                    )
            if token.type != TokenKind.PREPROCESSOR:
                continue
            text = token.value
            start, end = self.name_span(text)
            if start == end:
                if text.startswith("\\", start) or text.startswith("??/", start):
                    raise self._shape_error("multi-line preprocessor directives are unsupported", token, start)
                if text.startswith("/*", start):
                    raise self._shape_error("a comment between '#' and the directive name is unsupported", token, start)
                continue
            if text[start:end] in _CONDITIONAL_NAMES:
                self._check_conditional_shape(token)

    # -- The walk ----------------------------------------------------------

    @staticmethod
    def _live(stack: list[_ConditionalEntry]) -> bool:
        return all(entry.state == "taking" for entry in stack)

    def _payload(self, token: Token) -> tuple[str, int]:
        _start, end = self.name_span(token.value)
        return token.value[end:], token.col + end

    def _structural_tokens(self, token: Token) -> list[tuple[str, int, int]]:
        """``(spelling, line, col)`` of a payload's tokens, a pre-scanned ``#`` ending the list."""

        payload, col = self._payload(token)
        found = ConditionalExpression.pre_scan(payload)
        prefix = payload if found is None else payload[: found[0]]
        tokens = [(item.value, item.line, item.col) for item in self._expression.lex(prefix, token.line, col)]
        if found is not None:
            tokens.append((found[1], token.line, col + found[0]))
        return tokens

    def _ifdef(self, token: Token, name: str) -> bool:
        payload, col = self._payload(token)
        found = ConditionalExpression.pre_scan(payload)
        prefix = payload if found is None else payload[: found[0]]
        lexed = self._expression.lex(prefix, token.line, col)
        if found is not None:
            lexed.append(Token(TokenKind.PREPROCESSOR, found[1], token.line, col + found[0]))
        if not lexed:
            raise self._error(f"'#{name}' needs a macro name", token.line, token.col)
        operand = lexed[0]
        if (
            operand.type == TokenKind.PREPROCESSOR
            or not ConditionalExpression.name_token(operand)
            or operand.type in {TokenKind.TRUE, TokenKind.FALSE}
        ):
            raise self._error(f"'#{name}' needs a macro name, got '{operand.value}'", operand.line, operand.col)
        if len(lexed) > 1:
            extra = lexed[1]
            raise self._error(f"'#{name}' takes one macro name; unexpected '{extra.value}'", extra.line, extra.col)
        atom = self._expression.defined_value(operand.value, operand.line, operand.col)
        self._tests.extend(atom.tests)
        return (atom.value != 0) == (name == "ifdef")

    def _evaluate(self, token: Token, name: str) -> bool:
        payload, col = self._payload(token)
        tokens = self._expression.payload_tokens(payload, token.line, col)
        if not tokens:
            raise self._error(f"'#{name}' needs an expression", token.line, token.col)
        return self._expression.evaluate(tokens, self._tests)

    def _no_operands(self, token: Token, name: str) -> None:
        tokens = self._structural_tokens(token)
        if tokens:
            spelling, line, col = tokens[0]
            raise self._error(f"'#{name}' takes no operands; unexpected '{spelling}'", line, col)

    def _define(self, token: Token) -> None:
        directive = SourceSymbolDirective.parse(token.value)
        if directive is None:
            return
        name = directive.name
        message = SourceMacroRules.violation(name, define=directive.operation == "define")
        if message is not None:
            raise self._error(message, token.line, token.col)
        if directive.operation == "undef":
            self._macros.pop(name, None)
            return
        previous = self._macros.get(name)
        if previous is not None and not SourceMacroRules.same_definition(previous, directive):
            raise self._error(SourceMacroRules.redefinition_message(name), token.line, token.col)
        self._macros[name] = directive

    def run(self) -> ConditionedSource:
        try:
            tokens = Lexer(self._text, self._path).tokenize()
        except LexerError as error:
            message = str(error).removesuffix(f" at {error.line}:{error.col}")
            raise self._error(message, error.line, error.col) from error
        self._check_shapes(tokens)
        stack: list[_ConditionalEntry] = []
        blank: set[int] = set()
        dead_from: int | None = None
        for token in tokens:
            if token.type != TokenKind.PREPROCESSOR:
                continue
            name = self.directive_name(token.value)
            enclosing_live = self._live(stack)
            if name not in _CONDITIONAL_NAMES:
                if not enclosing_live:
                    self._check_dead_directive_shape(token)
                elif name == "error":
                    payload, _col = self._payload(token)
                    detail = SourceMacroRules.without_comments(payload).strip()
                    raise self._error(f"#error {detail}" if detail else "#error", token.line, token.col)
                elif name in {"define", "undef"}:
                    self._define(token)
                continue
            if name in {"elifdef", "elifndef"}:
                replacement = "#elif defined(NAME)" if name == "elifdef" else "#elif !defined(NAME)"
                raise self._error(f"'#{name}' is C23; write '{replacement}'", token.line, token.col)
            if name in {"if", "ifdef", "ifndef"}:
                if enclosing_live:
                    self._environment.require(self._path, token.line, token.col)
                    taken = self._evaluate(token, name) if name == "if" else self._ifdef(token, name)
                    stack.append(_ConditionalEntry(token, name, "taking" if taken else "seeking"))
                else:
                    stack.append(_ConditionalEntry(token, name, "done"))
            else:
                if not stack:
                    raise self._error(f"'#{name}' without '#if'", token.line, token.col)
                entry = stack[-1]
                level_live = self._live(stack[:-1])
                if name == "elif":
                    if entry.else_seen:
                        raise self._error("'#elif' after '#else'", token.line, token.col)
                    if level_live and entry.state == "seeking":
                        self._environment.require(self._path, token.line, token.col)
                        if self._evaluate(token, name):
                            entry.state = "taking"
                    elif entry.state == "taking":
                        entry.state = "done"
                elif name == "else":
                    if entry.else_seen:
                        raise self._error("'#else' after '#else'", token.line, token.col)
                    if level_live:
                        self._no_operands(token, name)
                    entry.else_seen = True
                    entry.state = "taking" if entry.state == "seeking" else "done"
                else:
                    if level_live:
                        self._no_operands(token, name)
                    stack.pop()
            blank.add(token.line)
            live_now = self._live(stack)
            if not live_now and dead_from is None:
                dead_from = token.line + 1
            elif live_now and dead_from is not None:
                blank.update(range(dead_from, token.line))
                dead_from = None
            elif not live_now and dead_from is not None:
                blank.update(range(dead_from, token.line))
                dead_from = token.line + 1
        if stack:
            opened = stack[-1]
            raise self._error(f"'#{opened.name}' without '#endif'", opened.token.line, opened.token.col)
        if not blank:
            return ConditionedSource(self._text, tuple(self._tests))
        lines = ["" if number in blank else line for number, line in enumerate(self._lines, start=1)]
        return ConditionedSource("\n".join(lines), tuple(self._tests))


class SourceDirectoryScanner:
    """Own iterative, deterministic filesystem traversal for directory imports.

    Traversal streams directory entries and keeps an explicit pending stack, so
    neither nesting depth nor directory size is capped by the compiler. Only
    real filesystem failures become diagnostics.
    """

    _SOURCE_SUFFIXES = (".btrc", ".c")

    def scan(self, root: str, *, recursive: bool) -> list[str]:
        """Return sorted sources without materializing whole directory listings."""

        matches: list[str] = []
        pending = [root]
        try:
            while pending:
                current = pending.pop()
                child_directories: list[str] = []
                with os.scandir(current) as entries:
                    for entry in entries:
                        if recursive and entry.is_dir(follow_symlinks=False):
                            child_directories.append(entry.path)
                        elif entry.is_file() and entry.name.endswith(self._SOURCE_SUFFIXES):
                            matches.append(entry.path)
                if recursive:
                    pending.extend(sorted(child_directories, reverse=True))
        except OSError as error:
            raise IncludeResolutionError(f"cannot scan import directory {root!r}: {error}") from error
        except MemoryError as error:
            raise IncludeResolutionError(f"cannot allocate memory scanning import directory {root!r}") from error
        return sorted(matches)


_DEFAULT_STDLIB_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "stdlib"))
_PRIORITY_FILES = (
    "Vector.btrc",
    "List.btrc",
    "Strings.btrc",
    "Platform.btrc",
    "Process.btrc",
)
_CLASS_NAME = re.compile(
    r"^\s*(?:abstract\s+)?class\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?"
    r"(?:implements\s+\w+(?:\s*,\s*\w+)*\s*)?\{",
    re.MULTILINE,
)
_INTERFACE_NAME = re.compile(
    r"^\s*interface\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?\{",
    re.MULTILINE,
)


class StdlibRepository:
    """Own access to the compiler's canonical standard-library sources."""

    def __init__(
        self,
        ast_cache: StdlibAstCache | None = None,
        cache_directory: FrontendCacheDirectory | None = None,
        fingerprint: FrontendFingerprint | None = None,
        source_reader: SourceFileReader | None = None,
        directive_scanner: SourceDirectiveScanner | None = None,
        *,
        directory: str | None = None,
    ) -> None:
        self.ast_cache = ast_cache or StdlibAstCache()
        self._cache_directory = cache_directory or FrontendCacheDirectory()
        self._ast_version = (fingerprint or FrontendFingerprint()).digest()
        self._source_reader = source_reader or SourceFileReader()
        self._directives = directive_scanner or SourceDirectiveScanner()
        self._directory = os.path.abspath(directory or _DEFAULT_STDLIB_DIRECTORY)
        self._symbol_files: dict[str, frozenset[str]] | None = None

    @property
    def ast_version(self) -> str:
        return self._ast_version

    def directory(self) -> str:
        return self._directory

    def discover_files(self) -> list[str]:
        """Return root stdlib modules in their deterministic composition order."""
        files: list[str] = []
        try:
            with os.scandir(self._directory) as entries:
                files.extend(entry.name for entry in entries if entry.name.endswith(".btrc"))
        except OSError:
            return []
        files.sort()
        prioritized = [name for name in _PRIORITY_FILES if name in files]
        prioritized.extend(name for name in files if name not in _PRIORITY_FILES)
        return prioritized

    def find_file(self, include_path: str) -> str | None:
        """Find a stdlib file by root-relative path or nested basename.

        The nested fallback streams the root directory and keeps only the
        lexicographically first match, so the answer stays deterministic
        without materializing the listing.
        """

        direct = os.path.join(self._directory, include_path)
        if os.path.isfile(direct):
            return direct
        filename = os.path.basename(include_path)
        best_name: str | None = None
        best_path: str | None = None
        try:
            with os.scandir(self._directory) as entries:
                for entry in entries:
                    if best_name is not None and entry.name >= best_name:
                        continue
                    candidate = os.path.join(entry.path, filename)
                    if os.path.isfile(candidate):
                        best_name = entry.name
                        best_path = candidate
        except OSError:
            return None
        return best_path

    def defined_names(self, source: str) -> set[str]:
        """Class and interface names a conditioned source defines."""

        return set(_CLASS_NAME.findall(source)) | set(_INTERFACE_NAME.findall(source))

    def source(self, user_source: str = "", environment: ConditionalEnvironment | None = None) -> str:
        return self.source_mapped(user_source, environment).source

    def source_mapped(self, user_source: str = "", environment: ConditionalEnvironment | None = None) -> StdlibSource:
        """Compose relaxed-mode stdlib text, each file conditioned, with native source positions.

        ``user_source`` is already conditioned; the stdlib files are conditioned
        for ``environment``, the host target when none is given.
        """
        conditionals = SourceConditionals(environment or ConditionalEnvironment.for_host())
        user_names = self.defined_names(user_source)
        lines: list[str] = []
        source_positions: list[tuple[str, int]] = []
        identities: list[SourceReadIdentity] = []
        for filename in self.discover_files():
            path = os.path.join(self._directory, filename)
            if not os.path.isfile(path):
                continue
            try:
                loaded = self._source_reader.read_source(path)
                identities.append(loaded.identity)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            content = conditionals.condition(loaded.text, path).text
            if self.defined_names(content) & user_names:
                continue
            file_lines, file_positions = self._source_without_imports(
                content,
                path,
            )
            lines.extend(file_lines)
            source_positions.extend(file_positions)
        return StdlibSource(
            source="\n".join(lines),
            source_positions=tuple(source_positions),
            input_identities=tuple(identities),
        )

    def cached_declarations(self, stdlib_source: str) -> list:
        """Return independently decoded declarations from the persistent cache."""
        try:
            cache_dir = self._cache_directory.resolve()
        except OSError:
            return self._parse_declarations(stdlib_source)
        self.ast_cache.prune(cache_dir)
        content_hash = self.ast_cache.source_hash(stdlib_source)
        path = self.ast_cache.path(
            cache_dir,
            self.ast_version,
            stdlib_source,
        )
        cached = self.ast_cache.load(path, content_hash)
        if cached is not None:
            return cached
        declarations = self._parse_declarations(stdlib_source)
        with suppress(OSError, TypeError, ValueError):
            self.ast_cache.store(path, content_hash, declarations)
        return declarations

    def _parse_declarations(self, stdlib_source: str) -> list:
        tokens = Lexer(stdlib_source, "<stdlib>").tokenize()
        return Parser(tokens).parse().declarations

    def _source_without_imports(
        self,
        content: str,
        path: str,
    ) -> tuple[list[str], list[tuple[str, int]]]:
        covered = {
            line
            for directive in self._directives.scan(content)
            if directive.kind == "import"
            for line in range(directive.start, directive.end + 1)
        }
        lines: list[str] = []
        positions: list[tuple[str, int]] = []
        for line_number, line in enumerate(content.split("\n"), start=1):
            if line_number in covered:
                continue
            lines.append(line)
            positions.append((path, line_number))
        return lines, positions

    @staticmethod
    def _declaration_names(declaration) -> tuple[str, ...]:
        if isinstance(declaration, ast.PreprocessorDirective):
            directive = SourceSymbolDirective.parse(declaration.text)
            return (directive.name,) if directive is not None and directive.operation == "define" else ()
        if isinstance(declaration, ast.TypedefDecl):
            return (declaration.alias,) if declaration.alias else ()
        if isinstance(
            declaration,
            (
                ast.ClassDecl,
                ast.InterfaceDecl,
                ast.FunctionDecl,
                ast.StructDecl,
                ast.EnumDecl,
                ast.RichEnumDecl,
                ast.VarDeclStmt,
            ),
        ):
            names = [declaration.name] if declaration.name else []
            if isinstance(declaration, ast.EnumDecl):
                names.extend(value.name for value in declaration.values if value.name)
            elif isinstance(declaration, ast.RichEnumDecl):
                names.extend(variant.name for variant in declaration.variants if variant.name)
            return tuple(names)
        return ()

    def symbol_files(self) -> dict[str, frozenset[str]]:
        """Map every canonical stdlib symbol to the file that owns it.

        Strict visibility must know about compiler-recognized stdlib types even
        when their source was not imported into the current AST. The map is
        derived from the stdlib itself rather than a second hardcoded table:
        from the generated ``btrc.symbols`` index when its digest matches the
        root modules on disk, otherwise by parsing them.
        """

        if self._symbol_files is not None:
            return self._symbol_files

        root = self.directory()
        files = self._root_module_files()
        owners = StdlibSymbolIndex.load(root, self.symbol_index_digest(files))
        if owners is None:
            owners = self.parsed_symbol_owners(files)
        self._symbol_files = {
            name: frozenset(
                SourceDependencyGraph.canonical_file(os.path.join(root, relative)) for relative in relatives
            )
            for name, relatives in owners.items()
        }
        return self._symbol_files

    def _root_module_files(self) -> list[str]:
        root = self.directory()
        return [filename for filename in self.discover_files() if os.path.isfile(os.path.join(root, filename))]

    def symbol_index_digest(self, files: list[str] | None = None) -> str:
        """Digest of the root modules exactly as ``btrc.symbols`` records it."""

        root = self.directory()
        entries: list[tuple[str, bytes]] = []
        for filename in self._root_module_files() if files is None else files:
            try:
                with open(os.path.join(root, filename), "rb") as source_file:
                    entries.append((filename, source_file.read()))
            except OSError as error:
                raise IncludeResolutionError(f"cannot read stdlib module {filename!r}: {error}") from error
        return StdlibSymbolIndex.snapshot_digest(entries)

    def parsed_symbol_owners(
        self,
        files: list[str] | None = None,
        environment: ConditionalEnvironment | None = None,
    ) -> dict[str, set[str]]:
        """Derive symbol -> owning root module names by parsing every conditioned root module.

        With no environment an owner is the union over every spec target, as
        ``btrc.symbols`` records it.
        """

        environments = (environment,) if environment is not None else ConditionalEnvironment.every_target()
        owners: dict[str, set[str]] = {}
        root = self.directory()
        for filename in self._root_module_files() if files is None else files:
            path = os.path.join(root, filename)
            try:
                source = self._source_reader.read(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            conditioned = {SourceConditionals(each).condition(source, path).text for each in environments}
            for text in sorted(conditioned):
                program = Parser(Lexer(text, path).tokenize()).parse()
                for declaration in program.declarations:
                    for name in self._declaration_names(declaration):
                        owners.setdefault(name, set()).add(filename)
        return owners

    def render_symbol_index(self) -> str:
        """Render the current ``btrc.symbols`` content for this stdlib."""

        files = self._root_module_files()
        return StdlibSymbolIndex.render(self.symbol_index_digest(files), self.parsed_symbol_owners(files))


class _SourceImportResolver(Protocol):
    stdlib: StdlibRepository

    def resolve_mapped(self, source, source_path, packages, included=None, *, exit_on_error=True, environment=None): ...

    def resolve(self, source, source_path, packages, included=None, *, exit_on_error=True): ...

    def resolve_with_graph(self, source, source_path, packages, *, exit_on_error=True): ...


class SourceResolver:
    """Own package setup, import/include resolution, and stdlib composition."""

    def __init__(
        self,
        stdlib: StdlibRepository | None = None,
        *,
        imports: _SourceImportResolver,
        package_universe: PackageUniverse | None = None,
    ) -> None:
        if imports is not None and stdlib is not None and imports.stdlib is not stdlib:
            raise ValueError("SourceResolver imports and stdlib must share one repository")
        self.stdlib = imports.stdlib
        self.imports = imports
        self.package_universe = package_universe or PackageUniverse()

    @staticmethod
    def _timed(profile: dict[str, float] | None, label: str, start: float) -> None:
        if profile is not None:
            profile[label] = time.perf_counter() - start

    def resolve(
        self,
        source: str,
        source_path: str,
        *,
        include_stdlib: bool = True,
        strict_imports: bool = True,
        map_stdlib_positions: bool = False,
        refresh_packages: bool = False,
        use_cache: bool = True,
        target: str | None = None,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        """Resolve one root file into text, provenance, and dependency graph."""

        packages = self.package_universe.resolve_for(
            source_path,
            refresh=refresh_packages,
            target=target,
        )
        environment = ConditionalEnvironment.for_packages(packages)
        start = time.perf_counter()
        user_source, provenance, source_positions, graph = self.imports.resolve_mapped(
            source,
            source_path,
            packages,
            exit_on_error=False,
            use_cache=use_cache,
            environment=environment,
        )
        self._timed(profile, "resolve_includes", start)

        stdlib_source = ""
        stdlib_positions: tuple[tuple[str, int], ...] = ()
        stdlib_identities: tuple[SourceReadIdentity, ...] = ()
        if include_stdlib and not strict_imports:
            start = time.perf_counter()
            stdlib = self.stdlib.source_mapped(user_source, environment)
            stdlib_source = stdlib.source
            stdlib_identities = stdlib.input_identities
            if map_stdlib_positions:
                stdlib_positions = stdlib.source_positions
            self._timed(profile, "stdlib_include", start)

        full_source = f"{stdlib_source}\n{user_source}" if stdlib_source else user_source
        sources = graph.source_paths()
        native_plan = packages.native_plan.for_sources(sources).with_stdlib(self.stdlib.directory(), sources)
        native = NativeDeclarationImporter().resolve(native_plan, use_cache=use_cache)
        return ResolvedSource(
            user_source=user_source,
            source=full_source,
            stdlib_source=stdlib_source,
            provenance=tuple(provenance),
            source_positions=stdlib_positions + tuple(source_positions),
            graph=graph,
            strict_imports=strict_imports,
            root_source_path=os.path.realpath(source_path),
            native_plan=native_plan,
            native_declarations=native.declarations,
            native_cache_identity=native.cache_identity,
            input_identities=graph.read_identities() + stdlib_identities,
            conditional_tests=graph.conditional_tests(),
        )

    def resolve_includes(
        self,
        source: str,
        source_path: str,
        included: set[str] | None = None,
        *,
        exit_on_error: bool = True,
    ) -> str:
        packages = self.package_universe.resolve_for(source_path)
        return self.imports.resolve(
            source,
            source_path,
            packages,
            included,
            exit_on_error=exit_on_error,
        )

    def resolve_includes_traced(
        self,
        source: str,
        source_path: str,
        *,
        exit_on_error: bool = True,
    ):
        packages = self.package_universe.resolve_for(source_path)
        return self.imports.resolve_with_graph(
            source,
            source_path,
            packages,
            exit_on_error=exit_on_error,
        )


__all__ = (
    "CompilerStdlibSource",
    "ConditionalEnvironment",
    "ConditionalExpression",
    "ConditionalTest",
    "ConditionedSource",
    "FrontendCacheDirectory",
    "FrontendFingerprint",
    "PreprocessorConditionalError",
    "ResolvedSource",
    "SourceConditionals",
    "SourceDependency",
    "SourceDependencyGraph",
    "SourceDependencyKind",
    "SourceDirective",
    "SourceDirectiveScanner",
    "SourceDirectoryScanner",
    "SourceFileReader",
    "SourceMacroRules",
    "SourceMap",
    "SourceReadError",
    "SourceResolver",
    "StdlibAstCache",
    "StdlibRepository",
    "StdlibSource",
)
