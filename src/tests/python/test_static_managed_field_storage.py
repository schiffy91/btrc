"""Strict-C ownership contracts for class-designated static storage."""

from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

STATIC_STRONG_SLOT_SOURCE = r"""
#include <assert.h>

int alive = 0;
int produced = 0;

class Item {
    public int value;
    public Item(int value) { self.value = value; alive++; }
    public void __del__() { alive--; }
}

class Globals {
    class Item shared = null;
}

Item makeItem(int value) {
    produced++;
    return new Item(value);
}

int main() {
    Item first = new Item(1);
    Globals.shared = first;
    assert(alive == 1 && Globals.shared == first);

    Globals.shared = Globals.shared;
    assert(alive == 1 && Globals.shared == first);

    Globals.shared = makeItem(2);
    assert(produced == 1);
    assert(alive == 2 && Globals.shared.value == 2);

    assert((Globals.shared = makeItem(3)).value == 3);
    assert(produced == 2);
    assert(alive == 2 && Globals.shared.value == 3);

    Globals.shared = null;
    assert(alive == 1 && Globals.shared == null);
    delete first;
    assert(alive == 0);
    return 0;
}
"""

GENERIC_STATIC_FIELD_SOURCE = r"""
#include <assert.h>
int alive = 0;
class Item {
    public int value;
    public Item(int value) { self.value = value; alive++; }
    public void __del__() { alive--; }
}
class Globals {
    class int calls = 0;
    class Item shared = null;
}
class Installer<T> {
    public Installer() {}
    public int install(Item value) {
        Globals.calls = Globals.calls + 1;
        Globals.shared = value;
        return Globals.calls;
    }
    public void clear() { Globals.shared = null; }
}
int main() {
    Installer<int> installer = Installer();
    assert(installer.install(new Item(1)) == 1);
    assert(alive == 1 && Globals.shared.value == 1);
    assert(installer.install(new Item(2)) == 2);
    assert(alive == 1 && Globals.shared.value == 2);
    installer.clear();
    assert(alive == 0 && Globals.shared == null);
    return 0;
}
"""


@functools.cache
def _generated(source: str) -> str:
    return emit_c(source)


def _main_statement(generated: str, needle: str) -> str:
    main = generated.split("int main(void) {", 1)[1]
    return next(line for line in main.splitlines() if needle in line)


def test_static_managed_field_uses_a_strong_slot_without_an_arc_edge_owner() -> None:
    generated = _generated(STATIC_STRONG_SLOT_SOURCE)

    borrowed = _main_statement(generated, " = first)")
    self_assignment = _main_statement(generated, " = Globals_shared)")
    fresh = _main_statement(generated, "makeItem(2)")

    assert "__btrc_arc_retain(" in borrowed
    assert "__btrc_arc_retain(" in self_assignment
    assert "__btrc_arc_retain(" not in fresh
    assert generated.count("makeItem(2)") == 1
    assert generated.count("makeItem(3)") == 1
    assert "__btrc_arc_replace_edge" not in generated
    assert "Globals->shared" not in generated


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "name, source",
    (
        ("strong-slot", STATIC_STRONG_SLOT_SOURCE),
        ("generic-static-field", GENERIC_STATIC_FIELD_SOURCE),
    ),
)
def test_static_managed_field_sources_are_strict_c11_and_runtime_correct(
    tmp_path: Path,
    c_compiler: str,
    name: str,
    source: str,
) -> None:
    c_path = tmp_path / f"{name}.c"
    executable = tmp_path / name
    c_path.write_text(_generated(source))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr
