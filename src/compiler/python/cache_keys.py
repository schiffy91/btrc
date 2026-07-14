"""Shared cache-key and cache-location helpers for every btrc on-disk cache.

Cache versioning is *derived*, never hand-bumped: each cache keys itself with a
content hash of the compiler sources that shape its entries, so any compiler
change automatically orphans stale entries.

Two hash scopes exist:

* ``"frontend"`` — grammar, ASDL/AST, imports, lexer, tokens, parser. Invalidates
  caches of frontend parse artifacts.
* ``"full"`` — frontend scope plus analyzer/ and ir/ (type checking, lowering,
  optimization, emission all shape the generated C). Invalidates caches of
  *compiled output* (.c disk cache, stdlib archives).

Cache directory resolution (``resolve_cache_dir``) is deterministic:

1. ``$BTRC_CACHE_DIR`` if set (used as-is).
2. ``<project root>/.btrc-cache`` where the project root is the nearest
   directory containing ``btrc.toml``, walking up from the input file's
   directory (or the cwd when no input path is given).
3. The per-user OS cache directory: ``~/Library/Caches/btrc`` on macOS,
   ``%LOCALAPPDATA%\\btrc`` on Windows, ``$XDG_CACHE_HOME/btrc`` or
   ``~/.cache/btrc`` elsewhere.

The invoking cwd itself is never used, so running the compiler does not
litter whatever directory it happens to be invoked from.
"""

from __future__ import annotations

import hashlib
import os
import sys

from . import pkg

_COMPILER_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(os.path.dirname(_COMPILER_DIR))  # .../src

# scope -> computed hash; computed once per process (hashing is ~1ms).
_HASH_CACHE: dict[str, str] = {}


def _python_files_under(*rel_dirs: str) -> list[str]:
    """All .py files under src/compiler/python/<rel_dir>, sorted for determinism."""
    found: list[str] = []
    for rel in rel_dirs:
        root = os.path.join(_COMPILER_DIR, rel)
        for current, _dirs, files in os.walk(root):
            found.extend(os.path.join(current, name) for name in files if name.endswith(".py"))
    return sorted(found)


def _toolchain_files(scope: str) -> list[str]:
    """The compiler sources whose content shapes a cache entry for ``scope``."""
    paths = [
        os.path.join(_SRC_DIR, "language", "grammar.ebnf"),
        os.path.join(_SRC_DIR, "language", "ast.asdl"),
        os.path.join(_COMPILER_DIR, "ebnf.py"),
        os.path.join(_COMPILER_DIR, "lexer.py"),
        os.path.join(_COMPILER_DIR, "lexer_literals.py"),
        os.path.join(_COMPILER_DIR, "numeric_literals.py"),
        os.path.join(_COMPILER_DIR, "tokens.py"),
        os.path.join(_COMPILER_DIR, "ast_nodes.py"),
        os.path.join(_COMPILER_DIR, "ast_codec.py"),
        os.path.join(_COMPILER_DIR, "cache_io.py"),
        os.path.join(_COMPILER_DIR, "frontend.py"),
        os.path.join(_COMPILER_DIR, "frontend_imports.py"),
        os.path.join(_COMPILER_DIR, "frontend_models.py"),
        os.path.join(_COMPILER_DIR, "frontend_stdlib.py"),
        os.path.join(_COMPILER_DIR, "import_scan.py"),
        os.path.join(_COMPILER_DIR, "import_visibility.py"),
        os.path.join(_COMPILER_DIR, "pkg.py"),
        os.path.join(_COMPILER_DIR, "source_io.py"),
        os.path.join(_COMPILER_DIR, "stdlib_ast_cache.py"),
    ]
    paths.extend(_python_files_under("parser"))
    if scope == "full":
        # Generated C can be shaped by orchestration, archive, freestanding,
        # cache, and CLI modules as well as analyzer/IR code. Cover every
        # production Python source so a new lowering-adjacent module cannot be
        # forgotten and silently reuse stale output.
        paths.extend(_python_files_under(""))
    return sorted(set(paths))


def _hash_paths(paths: list[str]) -> str:
    """Short content hash over stable relative paths and length-framed bytes."""
    digest = hashlib.sha256()
    for path in paths:
        relative_path = os.path.relpath(path, _SRC_DIR).replace(os.sep, "/").encode()
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        try:
            with open(path, "rb") as f:
                content = f.read()
        except OSError:
            content = b"<missing>"
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()[:16]


def toolchain_hash(scope: str = "full") -> str:
    """Content hash of the toolchain sources for ``scope`` (see module doc)."""
    if scope not in ("frontend", "full"):
        raise ValueError(f"unknown toolchain hash scope: {scope!r}")
    cached = _HASH_CACHE.get(scope)
    if cached is None:
        cached = _HASH_CACHE[scope] = _hash_paths(_toolchain_files(scope))
    return cached


def _user_cache_root() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches")
    if sys.platform == "win32":  # pragma: no cover - not a supported dev platform
        return os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


def resolve_cache_dir(input_path: str | None = None) -> str:
    """Resolve (and create) the btrc cache directory; see the module docstring
    for the resolution order. ``input_path`` anchors the btrc.toml walk at the
    file being compiled; without it the walk starts at the cwd."""
    env = os.environ.get("BTRC_CACHE_DIR")
    if env:
        cache = env
    else:
        start = os.path.dirname(os.path.abspath(input_path)) if input_path else os.getcwd()
        manifest = pkg.find_manifest(start)
        if manifest is not None:
            cache = os.path.join(os.path.dirname(manifest), ".btrc-cache")
        else:
            cache = os.path.join(_user_cache_root(), "btrc")
    os.makedirs(cache, exist_ok=True)
    return cache
