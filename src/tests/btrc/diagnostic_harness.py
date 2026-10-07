"""Parse both compilers' error diagnostics into comparable identities."""

from __future__ import annotations

import re
from dataclasses import dataclass

REFERENCE_DIAGNOSTIC = re.compile(r"^error: (.*)\n\s*--> .*?:(\d+):(\d+)", re.MULTILINE)

# btrcc renders a positioned error as the reference does, at its own file's
# position; only a position no source line maps keeps "<message> at L:C",
# which diagnostic_identity also reads.
SELFHOST_DIAGNOSTIC = REFERENCE_DIAGNOSTIC


@dataclass(frozen=True)
class GpuDiagnostic:
    """The first diagnostic both compilers must report for an invalid probe."""

    message: str
    line: int
    col: int


def diagnostic_identity(stderr: str) -> tuple[str, int, int]:
    selfhost = re.fullmatch(r"error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)\n?", stderr)
    if selfhost is not None:
        return selfhost.group("message"), int(selfhost.group("line")), int(selfhost.group("col"))
    reference = re.match(
        r"error: (?P<message>[^\n]+)\n\s*--> .*:(?P<line>\d+):(?P<col>\d+)\n",
        stderr,
    )
    assert reference is not None, stderr
    return reference.group("message"), int(reference.group("line")), int(reference.group("col"))


def rendered_at_file(path: object, source: str, diagnostic: str) -> str:
    """A compiler's rendering of ``"<message> at <line>:<col>"`` in ``source``.

    Both compilers render a positioned error at its own file: the message,
    the file as named, its line and column, the source line and a caret.
    """

    match = re.fullmatch(r"(?P<message>.*) at (?P<line>\d+):(?P<col>\d+)", diagnostic, re.DOTALL)
    assert match is not None, diagnostic
    line, col = int(match.group("line")), int(match.group("col"))
    # Lines end as a text-mode read ends them, at \r\n, \r or \n.
    text = re.split(r"\r\n|\r|\n", source)[line - 1]
    pad = " " * len(str(line))
    caret = " " * max(col - 1, 0) + "^"
    return f"error: {match.group('message')}\n {pad}--> {path}:{line}:{col}\n {pad} |\n {line} | {text}\n {pad} | {caret}\n"
