"""Standard-library discovery, composition, and parsed-AST caching."""

from __future__ import annotations

import os
import re

from .cache_keys import toolchain_hash
from .frontend_limits import ResolutionBudget
from .import_scan import scan_directives
from .pipeline.models import StdlibSource
from .pkg import IncludeResolutionError
from .source_io import SourceReadError, read_source

_STDLIB_AST_VERSION = toolchain_hash("frontend")

# Regex to extract class/interface names from btrc source (for skip-if-redefined)
_CLASS_NAME_RE = re.compile(
    r"^\s*(?:abstract\s+)?class\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?"
    r"(?:implements\s+\w+(?:\s*,\s*\w+)*\s*)?\{",
    re.MULTILINE,
)
_INTERFACE_NAME_RE = re.compile(
    r"^\s*interface\s+(\w+)(?:\s*<[^>\n]+>)?\s*"
    r"(?:extends\s+\w+(?:\s*<[^>\n]+>)?\s*)?\{",
    re.MULTILINE,
)


def _defined_stdlib_names(source: str) -> set[str]:
    return set(_CLASS_NAME_RE.findall(source)) | set(_INTERFACE_NAME_RE.findall(source))


def _get_stdlib_dir() -> str:
    """Get the absolute path to the stdlib directory."""
    # src/compiler/python/frontend.py -> src/stdlib/
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(module_dir, "..", "..", "stdlib")


def _discover_stdlib_files() -> list[str]:
    """Scan src/stdlib/ and return .btrc filenames in include order.

    vector.btrc comes first (Map/Set/List/Array may depend on Vector), then
    list.btrc (depends on ListNode + Vector), then strings.btrc because
    higher-level stdlib modules use Strings.copy(). Process/fs come before
    app-level modules that construct shell and filesystem helpers.
    """
    stdlib_dir = _get_stdlib_dir()
    if not os.path.isdir(stdlib_dir):
        return []
    files = sorted(f for f in os.listdir(stdlib_dir) if f.endswith(".btrc"))
    priority = [
        "vector.btrc",
        "list.btrc",
        "strings.btrc",
        "platform.btrc",
        "process.btrc",
        "fs.btrc",
        "daemon.btrc",
        "ui.btrc",
    ]
    ordered = [f for f in priority if f in files]
    ordered += [f for f in files if f not in priority]
    return ordered


def get_stdlib_source(user_source: str = "") -> str:
    """Read stdlib sources, skipping classes/interfaces already defined by user."""
    return get_stdlib_source_mapped(user_source).source


def _stdlib_file_source(content: str, path: str) -> tuple[list[str], list[tuple[str, int]]]:
    """Drop the file's own import directives; the stdlib is composed wholesale."""
    covered = {ln for d in scan_directives(content) if d.kind == "import" for ln in range(d.start, d.end + 1)}
    lines = []
    source_positions = []
    for line_number, line in enumerate(content.split("\n"), start=1):
        if line_number in covered:
            continue
        lines.append(line)
        source_positions.append((path, line_number))
    return lines, source_positions


def get_stdlib_source_mapped(user_source: str = "") -> StdlibSource:
    """Read stdlib sources, skipping classes/interfaces already defined by user."""
    stdlib_dir = _get_stdlib_dir()
    user_names = _defined_stdlib_names(user_source)

    lines = []
    source_positions = []
    budget = ResolutionBudget()
    for fname in _discover_stdlib_files():
        fpath = os.path.join(stdlib_dir, fname)
        if not os.path.exists(fpath):
            continue
        try:
            content = read_source(fpath)
        except SourceReadError as error:
            raise IncludeResolutionError(str(error)) from error
        budget.enter(content, fpath, 0)
        file_names = _defined_stdlib_names(content)
        if file_names & user_names:
            continue
        file_lines, file_positions = _stdlib_file_source(content, fpath)
        lines.extend(file_lines)
        source_positions.extend(file_positions)
    return StdlibSource(source="\n".join(lines), source_positions=tuple(source_positions))


def _find_stdlib_file(include_path: str) -> str | None:
    """Find a stdlib file by root-relative path or basename in subdirectories."""
    stdlib_dir = _get_stdlib_dir()
    stdlib_path = os.path.join(stdlib_dir, include_path)
    if os.path.exists(stdlib_path):
        return stdlib_path

    fname = os.path.basename(include_path)
    for entry in os.listdir(stdlib_dir):
        sub = os.path.join(stdlib_dir, entry)
        if os.path.isdir(sub):
            candidate = os.path.join(sub, fname)
            if os.path.exists(candidate):
                return candidate
    return None
