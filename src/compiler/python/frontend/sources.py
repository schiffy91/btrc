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
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

import src.compiler.python.syntax.ast.generated as ast

from ..lexer.lexer import Lexer
from ..parser.parser import Parser
from ..syntax.ast.codec import AstJsonCodec
from ..syntax.tokens import SourceSymbolDirective, Token, TokenKind
from .packages import IncludeResolutionError, NativeLinkPlan, PackageUniverse


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


class SourceDependencyKind(Enum):
    """The source-composition relationship represented by a graph edge."""

    IMPORT = "import"
    INCLUDE = "include"


@dataclass(frozen=True)
class SourceDependency:
    """One typed outgoing dependency from a source file."""

    target: str
    kind: SourceDependencyKind


@dataclass
class SourceDependencyGraph:
    """Typed source graph with the language's visibility semantics.

    ``import`` is directed. Legacy ``#include`` composes both files into one
    compilation unit, so visibility traversal treats include edges as
    reciprocal while retaining their distinct edge kind.
    """

    _outgoing: dict[str, set[SourceDependency]] = field(default_factory=dict)

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

        add_text("btrc-source-provenance-v2")
        add_text(self.root_source_path)
        add_text(self.native_plan.canonical_json())
        for source_file, native_line in self.source_positions:
            normalized = os.path.abspath(source_file) if os.path.exists(source_file) else source_file
            add_text(normalized)
            digest.update(int(native_line).to_bytes(8, "big", signed=True))
        for source, kind, target in self.graph.cache_records():
            add_text(source)
            add_text(kind)
            add_text(target)
        return digest.hexdigest()


class SourceReadError(OSError):
    """A source file could not be read under the compiler's input contract."""


class SourceFileReader:
    """Own deterministic UTF-8 source reads for one compiler application.

    The compiler imposes no size ceiling of its own: a source file is read
    until the operating system reports end of file, and only genuine
    filesystem or allocation failures become diagnostics.
    """

    def read(self, path: str) -> str:
        """Read one source file and normalize universal newlines."""

        try:
            with open(path, "rb") as source_file:
                encoded = source_file.read()
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
        if "\r" not in text:
            return text
        return text.replace("\r\n", "\n").replace("\r", "\n")


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


class SourceDirectiveScanner:
    """Own comment-aware import/include discovery through the real lexer."""

    _BTRC_INCLUDE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')

    def scan(self, source: str) -> list[SourceDirective]:
        """Return directives that own their complete source line range."""

        try:
            tokens = Lexer(source).tokenize()
        except Exception:
            return []  # malformed source: the main lexer/parser owns the error

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
    "vector.btrc",
    "list.btrc",
    "strings.btrc",
    "platform.btrc",
    "process.btrc",
    "fs.btrc",
    "daemon.btrc",
    "ui.btrc",
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
        return set(_CLASS_NAME.findall(source)) | set(_INTERFACE_NAME.findall(source))

    def source(self, user_source: str = "") -> str:
        return self.source_mapped(user_source).source

    def source_mapped(self, user_source: str = "") -> StdlibSource:
        """Compose relaxed-mode stdlib text with native source positions."""
        user_names = self.defined_names(user_source)
        lines: list[str] = []
        source_positions: list[tuple[str, int]] = []
        for filename in self.discover_files():
            path = os.path.join(self._directory, filename)
            if not os.path.isfile(path):
                continue
            try:
                content = self._source_reader.read(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
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
        derived from the stdlib itself rather than a second hardcoded table.
        """

        if self._symbol_files is not None:
            return self._symbol_files

        owners: dict[str, set[str]] = {}
        root = self.directory()
        for filename in self.discover_files():
            path = os.path.join(root, filename)
            if not os.path.isfile(path):
                continue
            try:
                source = self._source_reader.read(path)
            except SourceReadError as error:
                raise IncludeResolutionError(str(error)) from error
            program = Parser(Lexer(source, path).tokenize()).parse()
            canonical = SourceDependencyGraph.canonical_file(path)
            for declaration in program.declarations:
                for name in self._declaration_names(declaration):
                    owners.setdefault(name, set()).add(canonical)
        self._symbol_files = {name: frozenset(paths) for name, paths in owners.items()}
        return self._symbol_files


class _SourceImportResolver(Protocol):
    stdlib: StdlibRepository

    def resolve_mapped(self, source, source_path, packages, included=None, *, exit_on_error=True): ...

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
        target: str | None = None,
        profile: dict[str, float] | None = None,
    ) -> ResolvedSource:
        """Resolve one root file into text, provenance, and dependency graph."""

        packages = self.package_universe.resolve_for(
            source_path,
            refresh=refresh_packages,
            target=target,
        )
        start = time.perf_counter()
        user_source, provenance, source_positions, graph = self.imports.resolve_mapped(
            source,
            source_path,
            packages,
            exit_on_error=False,
        )
        self._timed(profile, "resolve_includes", start)

        stdlib_source = ""
        stdlib_positions: tuple[tuple[str, int], ...] = ()
        if include_stdlib and not strict_imports:
            start = time.perf_counter()
            if map_stdlib_positions:
                stdlib = self.stdlib.source_mapped(user_source)
                stdlib_source = stdlib.source
                stdlib_positions = stdlib.source_positions
            else:
                stdlib_source = self.stdlib.source(user_source)
            self._timed(profile, "stdlib_include", start)

        full_source = f"{stdlib_source}\n{user_source}" if stdlib_source else user_source
        return ResolvedSource(
            user_source=user_source,
            source=full_source,
            stdlib_source=stdlib_source,
            provenance=tuple(provenance),
            source_positions=stdlib_positions + tuple(source_positions),
            graph=graph,
            strict_imports=strict_imports,
            root_source_path=os.path.realpath(source_path),
            native_plan=packages.native_plan,
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
    "FrontendCacheDirectory",
    "FrontendFingerprint",
    "ResolvedSource",
    "SourceDependency",
    "SourceDependencyGraph",
    "SourceDependencyKind",
    "SourceDirective",
    "SourceDirectiveScanner",
    "SourceDirectoryScanner",
    "SourceFileReader",
    "SourceMap",
    "SourceReadError",
    "SourceResolver",
    "StdlibAstCache",
    "StdlibRepository",
    "StdlibSource",
)
