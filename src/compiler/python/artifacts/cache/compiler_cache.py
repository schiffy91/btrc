"""Owned compiler fingerprints, cache locations, and compiled-C entries."""

from __future__ import annotations

import hashlib
import os
import sys
import threading

from ...cache_io import atomic_write_text, open_regular_binary
from ...frontend.dependencies import ResolvedSource
from ...pkg import PackageResolver


class ToolchainSourceInventory:
    """Own the deterministic source inventory for toolchain fingerprints."""

    _FRONTEND_FILES = (
        "ebnf.py",
        "lexer.py",
        "lexer_literals.py",
        "numeric_literals.py",
        "tokens.py",
        "ast_nodes.py",
        "ast_codec.py",
        "cache_io.py",
        "pkg.py",
        "frontend/source_io.py",
        "stdlib_ast_cache.py",
        "artifacts/cache/compiler_cache.py",
    )

    def __init__(self, compiler_directory: str, source_directory: str) -> None:
        self.compiler_directory = os.path.abspath(compiler_directory)
        self.source_directory = os.path.abspath(source_directory)

    @classmethod
    def canonical(cls) -> ToolchainSourceInventory:
        compiler_directory = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        paths.extend(self._python_files_under("frontend", "pipeline", "parser"))
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

    def __init__(self, package_resolver: PackageResolver | None = None) -> None:
        self._packages = package_resolver or PackageResolver()

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
            manifest = self._packages.find_manifest(start)
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


class CompilationCache:
    """Own framing, validation, and persistence of compiled C results."""

    MAX_ENTRY_BYTES = 256 * 1024 * 1024

    def __init__(
        self,
        fingerprint: ToolchainFingerprint | None = None,
        directory: CacheDirectory | None = None,
        *,
        max_entry_bytes: int = MAX_ENTRY_BYTES,
    ) -> None:
        if max_entry_bytes <= 0:
            raise ValueError("compiled cache entry limit must be positive")
        self._fingerprint = fingerprint or ToolchainFingerprint()
        self._directory = directory or CacheDirectory()
        self._max_entry_bytes = max_entry_bytes

    @staticmethod
    def cache_source(source: ResolvedSource) -> str:
        import_mode = "strict" if source.strict_imports else "relaxed"
        return f"import-mode={import_mode}\0{source.source}"

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
            cache_file = open_regular_binary(path)
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
        atomic_write_text(path, c_output)

    def load(self, source: ResolvedSource, input_path: str) -> str | None:
        return self.load_text(
            self.cache_source(source),
            input_path=input_path,
            source_identity=source.cache_identity(),
        )

    def store(self, source: ResolvedSource, input_path: str, c_source: str) -> None:
        self.store_text(
            self.cache_source(source),
            c_source,
            input_path=input_path,
            source_identity=source.cache_identity(),
        )
