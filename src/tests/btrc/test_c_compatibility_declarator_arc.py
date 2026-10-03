"""ARC behavior is proven per declarator (C row 3, PLAN.md Stage 16's exit).

A declaration with several declarators splices into one declaration per
declarator (docs/design/c-compatibility.md (b), D20), so each declarator must
own, retain and release exactly what its own declaration would.
``fixtures/DeclaratorArcWitnessRuntime.btrc`` covers fresh and aliasing
managed declarators, ``*`` bound per declarator beside managed strings, a
function-pointer declarator in the list, class fields declared together, an
initializer that throws partway through the list, and a loop that continues.

The witness: before the C compiler sees the generated program, each ARC
retain, release, edge-store and edge-removal helper and each string
adoption, retain and release helper the program reaches gains a call to
``arc_witness_note`` (``fixtures/arc_declarator_witness.c``); an edge helper
that reads its slot counts the object the slot held. The program reads the counts back
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

# Each witnessed helper: (name, kind, the operand counted, and the line of
# its body after which the note goes, or None for the top of the body). An
# edge helper that reads its slot is noted after the read, so the counted
# object is the one the slot held. Kinds: 0 retain, 1 release, 2 edge store,
# 3 string retain, 4 string release, 5 edge removal, 6 string adoption.
SLOT_READ = "    void* object = access(slot_storage, NULL, NULL, 0);\n"
WITNESSED_HELPERS = (
    ("__btrc_arc_retain", 0, "object", None),
    ("__btrc_arc_retain_edge", 0, "object", None),
    ("__btrc_arc_release", 1, "object", None),
    ("__btrc_arc_release_edge", 1, "object", None),
    ("__btrc_arc_release_acyclic", 1, "object", None),
    ("__btrc_arc_replace_edge", 2, "replacement", None),
    ("__btrc_arc_replace_edge", 5, "object", SLOT_READ),
    ("__btrc_arc_adopt_edge", 2, "object", None),
    ("__btrc_arc_unlink_edge", 5, "object", None),
    ("__btrc_arc_destroy_edge", 5, "object", SLOT_READ),
    ("__btrc_arc_destroy_slot", 5, "object", SLOT_READ),
    ("__btrc_string_retain", 3, "value", None),
    ("__btrc_string_release", 4, "value", None),
    ("__btrc_string_adopt", 6, "value", None),
)

# Each scenario's counts. Two fresh declarators are adopted, not retained; a
# copying declarator retains once; the managed string beside the pointer
# declarators is adopted once and retained once by its copy; a field pair
# stores two edges, which the holder's destruction removes; a throwing third
# initializer leaves only the first declarator to unwind (plus the thrown
# string, adopted and released); a loop pays one retain and two releases per
# iteration, the continued one included.
EXPECTED = "".join(
    f"{label}: created={created} destroyed={destroyed} retains={retains} releases={releases} edges={edges} "
    f"edge-removals={removals} string-adopts={adopts} string-retains={string_retains} "
    f"string-releases={string_releases}\n"
    for label, created, destroyed, retains, releases, edges, removals, adopts, string_retains, string_releases in (
        ("fresh", 2, 2, 0, 2, 0, 0, 0, 0, 0),
        ("alias", 2, 2, 1, 3, 0, 0, 0, 0, 0),
        ("pointer", 0, 0, 0, 0, 0, 0, 1, 1, 2),
        ("function-pointer", 1, 1, 1, 2, 0, 0, 0, 0, 0),
        ("fields", 2, 2, 0, 1, 2, 2, 0, 0, 0),
        ("throwing", 1, 1, 0, 1, 0, 0, 1, 0, 1),
        ("loop", 3, 3, 3, 6, 0, 0, 0, 0, 0),
    )
)

pytestmark = pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires a strict C11 compiler")


def _witness(generated: Path) -> set[str]:
    """Instrument the helpers *generated* defines; return their names."""
    text = generated.read_text()
    found = set()
    for name, kind, operand, after in WITNESSED_HELPERS:
        definition = re.search(rf"^static inline [^\n(]*\b{name}\(", text, re.MULTILINE)
        if definition is None:
            continue
        body = text.index(") {\n", definition.end()) + len(") {\n")
        if after is not None:
            # The line must sit in this helper's own body, before the next one.
            end = text.index("\n}\n", body)
            body = text.index(after, body, end) + len(after)
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
