"""Portable C-header directive generation for frontend imports."""

from .pkg import IncludeResolutionError

_C_TRIGRAPH_SUFFIXES = frozenset("=/'()!<>-")


def c_include_directive(path: str) -> str:
    """Return a safe quoted C include directive for an existing path.

    C header names have no portable escape for a literal quote or control
    character. Trigraph replacement also happens before directive parsing in
    C11, so a path containing a trigraph can silently name a different file.
    Reject those rare filesystem names instead of emitting malformed or
    attacker-controlled generated C.
    """
    for char in path:
        if char == '"' or ord(char) < 0x20 or ord(char) == 0x7F:
            raise IncludeResolutionError(
                f"cannot import C file with a quote or control character in its path: {path!r}"
            )
    for index in range(len(path) - 2):
        if path[index : index + 2] == "??" and path[index + 2] in _C_TRIGRAPH_SUFFIXES:
            raise IncludeResolutionError(f"cannot import C file whose path contains a C trigraph: {path!r}")
    return f'#include "{path}"'
