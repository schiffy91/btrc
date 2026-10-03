"""ARC behavior is proven per declarator (C row 3, PLAN.md Stage 16's exit).

A declaration with several declarators splices into one declaration per
declarator (docs/design/c-compatibility.md (b), D20), so each declarator must
own, retain and release exactly what its own declaration would.
``fixtures/DeclaratorArcWitnessRuntime.btrc`` covers fresh and aliasing
managed declarators, ``*`` bound per declarator beside managed strings, a
function-pointer declarator in the list, class fields declared together, an
initializer that throws partway through the list, and a loop that continues.

The witness: before the C compiler sees the generated program, every ARC
retain, release and edge-store helper, and the string retain and release
helpers, gain one call to ``arc_witness_note``
(``fixtures/arc_declarator_witness.c``). The program reads the counts back
around each scenario and prints them, so the exact numbers, not just a
balanced end state, are pinned -- identically for both compilers, under
every strict C11 compiler, with the allocation tracker proving the measured
pass leaves nothing allocated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import FIXTURES, tracked_strict_matrix
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair
from src.tests.c_toolchains import HOST_C_COMPILERS

PROGRAM = FIXTURES / "DeclaratorArcWitnessRuntime.btrc"
WITNESS = FIXTURES / "arc_declarator_witness.c"

# Helper -> (witness kind, the parameter naming the counted object). Kinds:
# 0 retain, 1 release, 2 edge store (the stored replacement), 3 string
# retain, 4 string release.
WITNESSED_HELPERS = {
    "__btrc_arc_retain": (0, "object"),
    "__btrc_arc_retain_edge": (0, "object"),
    "__btrc_arc_release": (1, "object"),
    "__btrc_arc_release_edge": (1, "object"),
    "__btrc_arc_release_acyclic": (1, "object"),
    "__btrc_arc_replace_edge": (2, "replacement"),
    "__btrc_string_retain": (3, "value"),
    "__btrc_string_release": (4, "value"),
}

# Each scenario's counts. Two fresh declarators are adopted, not retained; a
# copying declarator retains once; a field pair stores two edges, which the
# holder's destruction removes; a throwing third initializer leaves only the
# first declarator to unwind (and the caught string to release); a loop pays
# one retain and two releases per iteration, the continued one included.
EXPECTED = "".join(
    f"{line}\n"
    for line in (
        "fresh: created=2 destroyed=2 retains=0 releases=2 edges=0 string-retains=0 string-releases=0",
        "alias: created=2 destroyed=2 retains=1 releases=3 edges=0 string-retains=0 string-releases=0",
        "pointer: created=0 destroyed=0 retains=0 releases=0 edges=0 string-retains=1 string-releases=2",
        "function-pointer: created=1 destroyed=1 retains=1 releases=2 edges=0 string-retains=0 string-releases=0",
        "fields: created=2 destroyed=2 retains=0 releases=1 edges=2 string-retains=0 string-releases=0",
        "throwing: created=1 destroyed=1 retains=0 releases=1 edges=0 string-retains=0 string-releases=1",
        "loop: created=3 destroyed=3 retains=3 releases=6 edges=0 string-retains=0 string-releases=0",
    )
)

pytestmark = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires a strict C11 compiler")


def _witness(generated: Path) -> set[str]:
    """Instrument the helpers *generated* defines; return their names."""
    text = generated.read_text()
    found = set()
    for name, (kind, operand) in WITNESSED_HELPERS.items():
        definition = re.search(rf"^static inline [^\n(]*\b{name}\(", text, re.MULTILINE)
        if definition is None:
            continue
        body = text.index(") {\n", definition.end()) + len(") {\n")
        text = f"{text[:body]}    arc_witness_note({kind}, (const void*){operand});\n{text[body:]}"
        found.add(name)
    generated.write_text(f"void arc_witness_note(int kind, const void* object);\n{text}")
    return found


def test_each_declarator_owns_exactly_its_own_references(semantic_btrcc: Path, tmp_path: Path) -> None:
    for frontend, generated in compile_snippet_pair(semantic_btrcc, tmp_path, PROGRAM.read_text(), PROGRAM.stem):
        witnessed = _witness(generated)
        # The program exercises every counted family, so a renamed helper
        # cannot silently drop out of the witness.
        assert {"__btrc_arc_retain", "__btrc_arc_release", "__btrc_arc_replace_edge"} <= witnessed, frontend
        assert {"__btrc_string_retain", "__btrc_string_release"} <= witnessed, frontend
        tracked_strict_matrix(
            (frontend, generated),
            tmp_path,
            expected_stdout=EXPECTED,
            extra_sources=(WITNESS,),
        )
