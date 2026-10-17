"""An interface value's release follows its implementers' cyclicity in both compilers.

An interface value is one of its implementers at run time. When none of them
can join a cycle, releasing the interface value needs no cycle collection, and
neither compiler may pull the cycle collector into the program; when one of
them can, both must select the cycle-aware release. The self-hosted compiler
once treated every interface as cyclic, so a native callback receiver held by
an interface brought the whole cycle collector into otherwise acyclic programs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import compile_reference_source
from src.tests.btrc.selfhost_snippet_harness import compile_source
from src.tests.c_toolchains import HOST_C_COMPILERS
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT

ACYCLIC = """interface IVisitor { int visit(); }
class Counter implements IVisitor {
	public int count = 0;
	public int visit() { self.count++; return self.count; }
}
int use(IVisitor visitor) { return visitor.visit(); }
int main() {
	IVisitor visitor = Counter();
	int first = use(visitor);
	int second = use(visitor);
	visitor = null;
	return first == 1 && second == 2 ? 0 : 1;
}
"""

CYCLIC = ACYCLIC.replace(
    "int use(IVisitor visitor)",
    "class Link implements IVisitor {\n\tpublic Link? next = null;\n\tpublic int visit() { return 0; }\n}\nint use(IVisitor visitor)",
)

# A generic implementer stands for every specialization of it, so both
# compilers conservatively treat the interface as one that may cycle.
GENERIC = ACYCLIC.replace(
    "int use(IVisitor visitor)",
    "class Box<T> implements IVisitor {\n\tpublic int visit() { return 0; }\n}\nint use(IVisitor visitor)",
)

CYCLE_MACHINERY = ("__btrc_suspect_locked", "__btrc_flush_cycles")


@pytest.mark.parametrize(
    ("source", "cyclic"),
    [(ACYCLIC, False), (CYCLIC, True), (GENERIC, True)],
    ids=["acyclic", "cyclic", "generic-implementer"],
)
def test_interface_release_follows_implementer_cyclicity(semantic_btrcc: Path, tmp_path: Path, source, cyclic):
    selfhost, selfhost_c = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = compile_reference_source(tmp_path, source, "interface-release-cyclicity")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for frontend, generated in (("selfhost", selfhost_c), ("reference", reference_c)):
        text = Path(generated).read_text(encoding="utf-8")
        present = [name for name in CYCLE_MACHINERY if name in text]
        if cyclic:
            assert "__btrc_arc_release(" in text, frontend
        else:
            assert present == [], (frontend, present)
        if HOST_C_COMPILERS:
            executable = tmp_path / f"{frontend}-interface-release"
            built = subprocess.run(
                [
                    HOST_C_COMPILERS[0],
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(generated),
                    "-o",
                    str(executable),
                    "-lm",
                    "-lpthread",
                ],
                capture_output=True,
                text=True,
                timeout=C_COMPILE_TIMEOUT,
                check=False,
            )
            assert built.returncode == 0, built.stderr
            ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
            assert ran.returncode == 0, (frontend, ran.stdout, ran.stderr)
