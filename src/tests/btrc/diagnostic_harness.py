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
