"""Compiler output cache storage and whole-toolchain fingerprints."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import threading
from contextlib import suppress


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


class CompilerCache:
    """Own framing, validation, and persistence of compiled C results."""

    MAX_ENTRY_BYTES = 256 * 1024 * 1024

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

    def load_text(
        self,
        resolved_source: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> str | None:
        """Load one bounded regular cache entry, treating corruption as a miss."""

        try:
            key = self.key_for(resolved_source, source_identity)
            path = os.path.join(self._directory.resolve(input_path), f"{key}.c")
            cache_file = self._files.open_regular_binary(path)
            if cache_file is None:
                return None
            with cache_file:
                if os.fstat(cache_file.fileno()).st_size > self._max_entry_bytes:
                    return None
                encoded = cache_file.read(self._max_entry_bytes + 1)
            if len(encoded) > self._max_entry_bytes:
                return None
            return encoded.decode("utf-8")
        except (OSError, UnicodeError):
            return None

    def store_text(
        self,
        resolved_source: str,
        c_output: str,
        input_path: str | None = None,
        *,
        source_identity: str = "",
    ) -> None:
        """Atomically store one compiled C cache entry."""

        key = self.key_for(resolved_source, source_identity)
        path = os.path.join(self._directory.resolve(input_path), f"{key}.c")
        self._files.write_text(path, c_output)
