"""Safe persistent cache for parsed standard-library AST declarations."""

from __future__ import annotations

import hashlib
import os
import time

from .ast_codec import AstJsonCodec
from .cache_io import AtomicFileStore

SCHEMA_VERSION = 1
_PREFIX = "stdlib-"
_SUFFIX = ".ast.json"
_LEGACY_SUFFIX = ".ast"
_MAX_AGE = 30 * 24 * 3600


class StdlibAstCache:
    """Own content addressing, validation, and pruning for parsed stdlib ASTs."""

    def __init__(
        self,
        *,
        schema_version: int = SCHEMA_VERSION,
        max_age_seconds: int = _MAX_AGE,
        file_store: AtomicFileStore | None = None,
        codec: AstJsonCodec | None = None,
    ) -> None:
        self.schema_version = schema_version
        self.max_age_seconds = max_age_seconds
        self.file_store = file_store or AtomicFileStore()
        self.codec = codec if codec is not None else AstJsonCodec()
        self._pruned_dirs: set[str] = set()

    def path(self, cache_dir: str, frontend_version: str, source: str) -> str:
        """Return a content-addressed path covering schema, frontend, and source."""
        digest = hashlib.sha256()
        for part in (str(self.schema_version), frontend_version, source):
            encoded = part.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return os.path.join(
            cache_dir,
            f"{_PREFIX}{digest.hexdigest()}{_SUFFIX}",
        )

    def load(self, path: str, content_hash: str) -> list | None:
        """Load validated declarations, or return ``None`` to request a reparse."""
        payload = self.file_store.read_json(path)
        if not self._valid_payload(payload, content_hash):
            return None
        try:
            declarations = [self.codec.decode(value) for value in payload["declarations"]]
        except (ValueError, TypeError, RecursionError):
            return None
        if not all(hasattr(declaration, "source_file") for declaration in declarations):
            return None
        return declarations

    def store(
        self,
        path: str,
        content_hash: str,
        declarations: list,
    ) -> None:
        """Atomically store declarations in the deterministic JSON schema."""
        self.file_store.write_json(
            path,
            {
                "content_hash": content_hash,
                "declarations": [self.codec.encode(declaration) for declaration in declarations],
                "schema": self.schema_version,
            },
        )

    def prune(self, cache_dir: str) -> None:
        """Remove unsafe legacy pickles immediately and expired JSON entries."""
        if cache_dir in self._pruned_dirs:
            return
        cutoff = time.time() - self.max_age_seconds
        try:
            names = os.listdir(cache_dir)
        except OSError:
            return
        self._pruned_dirs.add(cache_dir)
        for name in names:
            if not name.startswith(_PREFIX):
                continue
            path = os.path.join(cache_dir, name)
            try:
                expired_json = name.endswith(_SUFFIX) and os.path.getmtime(path) < cutoff
                if name.endswith(_LEGACY_SUFFIX) or expired_json:
                    os.remove(path)
            except OSError:
                pass

    @staticmethod
    def source_hash(source: str) -> str:
        return hashlib.sha256(source.encode()).hexdigest()

    def _valid_payload(self, payload, content_hash: str) -> bool:
        return (
            isinstance(payload, dict)
            and set(payload) == {"content_hash", "declarations", "schema"}
            and payload["schema"] == self.schema_version
            and payload["content_hash"] == content_hash
            and isinstance(payload["declarations"], list)
        )


__all__ = ["SCHEMA_VERSION", "StdlibAstCache"]
