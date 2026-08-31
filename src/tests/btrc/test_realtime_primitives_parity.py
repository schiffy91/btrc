"""Reference/self-host parity for the bounded realtime primitive foundation."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _diagnostic_identity(stderr: str) -> tuple[str, int, int]:
    selfhost = re.fullmatch(r"error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)\n?", stderr)
    if selfhost is not None:
        return selfhost.group("message"), int(selfhost.group("line")), int(selfhost.group("col"))
    reference = re.match(
        r"error: (?P<message>[^\n]+)\n\s*--> .*:(?P<line>\d+):(?P<col>\d+)\n",
        stderr,
    )
    assert reference is not None, stderr
    return reference.group("message"), int(reference.group("line")), int(reference.group("col"))


def _compile_pair(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> tuple[subprocess.CompletedProcess[str], Path, subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "program.btrc"
    reference_c = tmp_path / "reference.c"
    selfhost_c = tmp_path / "selfhost.c"
    program.write_text(source)
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")}
    reference = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            str(program),
            "-o",
            str(reference_c),
        ],
        cwd=REPO,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    selfhost = subprocess.run(
        [str(semantic_btrcc), "--no-stdlib", str(program)],
        cwd=REPO,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if selfhost.returncode == 0:
        selfhost_c.write_text(selfhost.stdout)
    return reference, reference_c, selfhost, selfhost_c


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "Span<int> escaped; int main() { return 0; }",
            "Global 'escaped' cannot store nonescaping Span<T>",
        ),
        (
            "void inspect(Atomic<string>* value) {} int main() { return 0; }",
            "Atomic<T> payload must be bool, int, uint, or a raw pointer",
        ),
        (
            "int main() { Atomic<int> value = Atomic(0); value.load(MemoryOrder.RELEASE); return 0; }",
            "Atomic.load does not accept MemoryOrder.RELEASE",
        ),
        (
            "int main() { Atomic<int> value = Atomic(0); int expected = 0; "
            "value.compareExchangeStrong(&expected, 1, MemoryOrder.RELEASE, "
            "MemoryOrder.ACQUIRE); return 0; }",
            "Atomic.compareExchangeStrong failure order MemoryOrder.ACQUIRE "
            "is not allowed with success order MemoryOrder.RELEASE",
        ),
        (
            "int main() { int* values = null; Span<int> view = Span(values); return 0; }",
            "Span(pointer) requires an explicit element count",
        ),
        (
            "int main() { Span<int> view = Span(1, 1); return 0; }",
            "Span() backing must be a fixed array or raw pointer",
        ),
        (
            'int main() { int values[1] = {1}; Span<int> view = Span(values, "one"); return 0; }',
            "Span() element count must be integral",
        ),
        (
            "int main() { int count = 4; int values[count]; Span<int> view = Span(values); return 0; }",
            "Span(array) requires a fixed constant extent",
        ),
        (
            "int main() { Atomic<int> first = Atomic(0); Atomic<int> second = first; return 0; }",
            "cannot copy an Atomic<T> owner; initialize with Atomic(value)",
        ),
        (
            "class Box<T> { public T value; public Box(T value) { self.value = value; } } "
            "int main() { int values[1] = {1}; Span<int> view = Span(values); "
            "Box<Span<int>> box = new Box<Span<int>>(view); return 0; }",
            "Variable 'box' cannot contain nonescaping Span<T> in aggregate or managed storage",
        ),
        (
            "struct Holder { Atomic<int> value; }; int main() { Holder first; Holder second = first; return 0; }",
            "Struct field 'Holder.value' cannot embed an Atomic<T> owner in shallow copyable storage; "
            "keep Atomic<T> as a direct class field or local owner",
        ),
    ),
    ids=(
        "span-escape",
        "atomic-pointer-payload",
        "load-order",
        "cas-order",
        "span-count",
        "span-invalid-backing",
        "span-invalid-extent",
        "span-vla",
        "atomic-copy",
        "generic-span-escape",
        "aggregate-atomic-copy",
    ),
)
def test_invalid_contract_diagnostics_are_exactly_equal(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    reference, _reference_c, selfhost, _selfhost_c = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
    )

    assert reference.returncode == 1
    assert selfhost.returncode == 1
    reference_identity = _diagnostic_identity(reference.stderr)
    selfhost_identity = _diagnostic_identity(selfhost.stderr)
    assert diagnostic in reference_identity[0]
    assert selfhost_identity == reference_identity


@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda compiler: Path(compiler).name)
def test_valid_primitives_have_strict_c11_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    reference, reference_c, selfhost, selfhost_c = _compile_pair(
        semantic_btrcc,
        tmp_path,
        """
        uint readAtomic(Atomic<uint>* value) {
            return value->load(MemoryOrder.ACQUIRE);
        }
        bool advanceAtomic(Atomic<uint>* value) {
            uint expected = 1u;
            return value->compareExchangeStrong(
                &expected, 2u, MemoryOrder.ACQ_REL, MemoryOrder.ACQUIRE);
        }
        int main() {
            int values[3] = {11, 13, 17};
            Span<int> view = Span(values);
            int output = -1;
            if (!view.tryGet(1, &output) || output != 13) { return 1; }
            if (view.tryGet(4, &output) || output != 13) { return 2; }
            if (view.trySet(4, 99) || values[2] != 17) { return 3; }
            int sum = 0;
            for value in view { sum += value; }
            if (sum != 41) { return 4; }
            Atomic<uint> state = Atomic(1u);
            if (readAtomic(&state) != 1u || !advanceAtomic(&state)) { return 5; }
            return state.load(MemoryOrder.ACQUIRE) == 2u ? 0 : 6;
        }
        """,
    )
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr

    for frontend, generated in (("reference", reference_c), ("selfhost", selfhost_c)):
        executable = tmp_path / f"{frontend}-{Path(c_compiler).name}"
        built = subprocess.run(
            [
                c_compiler,
                "-std=c11",
                "-pedantic-errors",
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
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert built.returncode == 0, built.stderr
        executed = subprocess.run(
            [str(executable)],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert executed.returncode == 0, executed.stderr
