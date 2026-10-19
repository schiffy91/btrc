"""Disagreements between the compilers, found writing Library.Terminal and glob (PR #96).

Each program goes through the reference compiler's CLI and ``btrcc``. An
accepted program must be accepted by both, its C must build under strict C11
and print what it should; a refused one must be refused by both with the same
rendered diagnostic, and a warning must read the same in both.

- Indexing opaque C storage. A pointer or array member of a record a C
  header declares (``glob_t``'s ``gl_pathv``, ``struct termios``'s ``c_cc``)
  has no btrc type. The reference compiler let C index it; btrcc refused with
  "Cannot determine whether expression is indexable". Both index it.
- Storing through opaque C storage. ``raw.c_cc[VMIN] = 1`` crashed the
  reference compiler ("receiver-backed storage requires a typed lowered
  receiver"), ``values[raw.c_cc[i]] = 1`` crashed it too and made btrcc emit
  ``void`` temporaries (and, once btrcc indexed such storage, drop the
  declaration of a typed key's temporary), and ``raw.c_lflag |= 1`` was
  refused only by the reference compiler. Both store through such storage as
  written. A C macro that must be ordered against such storage
  (``(int)raw.c_cc[VMIN]``) stays refused, now with the reference compiler's
  diagnostic in btrcc too, where it read "managed ownership boundary ...
  requires a concrete type".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
STRICT_C11 = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror")
DIAGNOSTIC = re.compile(r"^(?:error|warning): ", re.MULTILINE)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the programs include POSIX headers")


@dataclass(frozen=True)
class Outcome:
    """One compiler's result: its exit status, rendered diagnostics and C."""

    returncode: int
    diagnostics: tuple[str, ...]
    c_path: Path


class ParityHarness:
    """Compile one program through both compilers, then build and run its C."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile(self, name: str, source: str) -> tuple[Outcome, Outcome]:
        path = self._workspace / f"{name}.btrc"
        path.write_text(source, encoding="utf-8")
        reference_c = self._workspace / f"{name}.reference.c"
        selfhost_c = self._workspace / f"{name}.selfhost.c"
        reference = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(path), "--no-cache", "-o", str(reference_c)],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "BTRC_CACHE_DIR": str(self._workspace / "reference-cache")},
            timeout=TRANSPILE_TIMEOUT,
        )
        selfhost = subprocess.run(
            [str(self._btrcc), str(path), "--no-cache", "-o", str(selfhost_c)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        return (
            Outcome(reference.returncode, self._blocks(reference.stderr), reference_c),
            Outcome(selfhost.returncode, self._blocks(selfhost.stderr), selfhost_c),
        )

    def run(self, outcome: Outcome) -> str:
        """Build one compiler's C under strict C11 and return what it prints."""
        executable = outcome.c_path.with_suffix(".exe")
        built = subprocess.run(
            [*configured_c_compiler(), *STRICT_C11, str(outcome.c_path), "-o", str(executable), "-lm", "-lpthread"],
            capture_output=True,
            text=True,
            timeout=C_COMPILE_TIMEOUT,
        )
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert ran.returncode == 0, (ran.stdout, ran.stderr)
        return ran.stdout

    def accepted(self, name: str, source: str) -> tuple[str, str]:
        """Both compilers accept with no diagnostic; return each program's output."""
        reference, selfhost = self.compile(name, source)
        assert reference.returncode == 0 and not reference.diagnostics, reference.diagnostics
        assert selfhost.returncode == 0 and not selfhost.diagnostics, selfhost.diagnostics
        return self.run(reference), self.run(selfhost)

    def refused(self, name: str, source: str) -> str:
        """Both compilers refuse with one identical diagnostic; return it."""
        reference, selfhost = self.compile(name, source)
        assert reference.returncode != 0 and selfhost.returncode != 0, (reference, selfhost)
        assert len(reference.diagnostics) == 1, reference.diagnostics
        assert reference.diagnostics == selfhost.diagnostics
        return reference.diagnostics[0]

    @staticmethod
    def _blocks(stderr: str) -> tuple[str, ...]:
        """Each rendered diagnostic: its message, location and source excerpt."""
        starts = [match.start() for match in DIAGNOSTIC.finditer(stderr)]
        ends = [*starts[1:], len(stderr)] if starts else []
        return tuple(stderr[start:end].rstrip("\n") for start, end in zip(starts, ends, strict=True))


@pytest.fixture
def harness(immutable_btrcc: Path, tmp_path: Path) -> ParityHarness:
    return ParityHarness(immutable_btrcc, tmp_path)


# Indexing: glob's matches through `found->gl_pathv[i]`, with a null errfunc.
# The root directory is the one path every POSIX host has.
GLOB = """#include <glob.h>
#include <stdio.h>

int main() {
\tglob_t found;
\tglob_t* view = &found;
\tif (glob("/", 0, null, view) != 0) { return 1; }
\tfor (int i = 0; i < (int)view->gl_pathc; i++) { printf("%s\\n", view->gl_pathv[i]); }
\tchar* first = found.gl_pathv[0];
\tprintf("%d %d\\n", (int)found.gl_pathc, (int)first[1]);
\tglobfree(view);
\treturn 0;
}
"""


def test_a_pointer_member_of_a_c_header_record_is_indexable(harness: ParityHarness) -> None:
    reference, selfhost = harness.accepted("OpaqueIndex", GLOB)
    assert reference == selfhost == "/\n1 0\n"


# Storing: stores, compound updates and increments through opaque C storage,
# an opaque key on a typed array, and a member through a pointer.
TERMIOS = """#include <stdio.h>
#include <string.h>
#include <termios.h>

int main() {
\tstruct termios raw;
\tmemset(&raw, 0, sizeof(raw));
\traw.c_cc[VMIN] = 1;
\traw.c_cc[VTIME] = 0;
\tint minimum = VMIN;
\tint slot = VTIME;
\traw.c_cc[slot] += 3;
\traw.c_cc[slot]++;
\traw.c_lflag |= 8;
\tint values[4] = {0, 0, 0, 0};
\tvalues[raw.c_cc[minimum]] = 5;
\tvalues[raw.c_cc[minimum]] += 1;
\tstruct termios* view = &raw;
\tview->c_cc[minimum] = (cc_t)2;
\tprintf("%d %d %d %d\\n", (int)raw.c_cc[minimum], (int)raw.c_cc[slot], (int)raw.c_lflag, values[1]);
\treturn 0;
}
"""


def test_stores_through_c_header_record_members_compile_in_both(harness: ParityHarness) -> None:
    reference, selfhost = harness.accepted("OpaqueStores", TERMIOS)
    assert reference == selfhost == "2 4 8 6\n"


# Storing, refused: a C macro's expansion is unknown, so neither compiler
# assumes it free of effects, and a read or a store that must order it against
# an operand with no type is refused with the same diagnostic. `int slot =
# VMIN;` first gives the key a type, as the program above does.
@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        (
            "OpaqueRead",
            "\tint minimum = (int)raw.c_cc[VMIN];\n\treturn minimum;\n",
            "error: opaque C operand at 7:21 precedes an ordered sibling in expression; cast it explicitly",
        ),
        (
            "OpaqueKey",
            "\tint values[32];\n\tvalues[VMIN] = 1;\n\treturn 0;\n",
            "error: opaque C operand at 8:9 precedes an ordered sibling in assignment target; cast it explicitly",
        ),
    ],
)
def test_an_unordered_c_macro_beside_opaque_storage_is_refused_alike(
    harness: ParityHarness, name: str, body: str, message: str
) -> None:
    source = (
        "#include <string.h>\n#include <termios.h>\n\nint main() {\n"
        "\tstruct termios raw;\n\tmemset(&raw, 0, sizeof(raw));\n" + body + "}\n"
    )
    assert harness.refused(name, source) == message
