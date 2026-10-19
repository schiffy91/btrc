"""Both compilers keep the same generic callables without dead-code elimination.

The reference lowers a generic class instance's ordinary methods and property
accessors only when the program demands them (``GenericSpecializer``'s
selected callables). btrcc lowers every one, and a typed operator the type
argument does not support -- ``<`` on a class reference in
``Vector<T>.sort`` -- becomes a deferred diagnostic in that body, which DCE
dropped with the unreachable method. With ``--no-dce`` nothing dropped it, so
btrcc refused every program that specialized ``Vector`` over a class, down to
one importing nothing but ``Library.Callback``, while the reference compiled
it. Stage five now keeps such a callable only while other code names it and
refuses a deferred diagnostic that remains, as the reference's lowering does,
in the reference's words.

Every compile stops at C, so the Android rows run on any host.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.tests.process_limits import TRANSPILE_TIMEOUT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

REPO = Path(__file__).resolve().parents[3]
# The modules btrcc refused alone under --no-dce; each specializes a stdlib
# generic over a class whose unused methods compare or hash it.
MODULES = ("BackgroundJobs", "Callback", "Daemon", "FileSystem", "Graph", "HTTP", "JSON", "Process", "TOML")
TARGETS = ("host", "android-aarch64", "android-x86_64")
# A generic specialization's definition: `btrc_<Base>_..._<callable>(...) {`.
SPECIALIZED_DEFINITION = re.compile(r"^[A-Za-z_][^\n;=(){}]*?\b(btrc_\w+)\([^;{}\n]*\)\s*\{", re.MULTILINE)
REFUSED_COMPARISON = "error: operator '<' is not defined for reference operands; only == and != are portable\n"

ITEM = """
class Item {
    public int value;
    public Item(int value) { self.value = value; }
}
"""
BOX = (
    ITEM
    + """
class Box<T> {
    public T first;
    public T second;
    public Box(T first, T second) { self.first = first; self.second = second; }
    public bool ordered() { return self.first < self.second; }
    public bool orderedTwice() { return self.ordered() && self.ordered(); }
    public T head() { return self.first; }
}
"""
)


@dataclass(frozen=True)
class Case:
    """A program, and the diagnostic both compilers refuse it with (None: both compile it)."""

    source: str
    refusal: str | None = None
    # Callables neither compiler may define when the program compiles.
    undemanded: tuple[str, ...] = ()


CASES = {
    # Vector<Item>.sort compares Item references, but nothing sorts.
    "unsorted-vector": Case(
        "import Library.Vector;\n"
        + ITEM
        + "int main() {\n    Vector<Item> items = [];\n    items.push(Item(1));\n    return items.len - 1;\n}\n",
        undemanded=("_sort", "_sorted", "_min", "_max"),
    ),
    # Only head is demanded; ordered is named only by orderedTwice.
    "undemanded-chain": Case(
        BOX + "int main() {\n    Box<Item> box = Box(Item(1), Item(2));\n    return box.head().value - 1;\n}\n",
        undemanded=("_ordered", "_orderedTwice"),
    ),
    # A function nothing calls still demands what it names, transitively.
    "demanded-chain": Case(
        BOX
        + "bool unused(Box<Item> box) { return box.orderedTwice(); }\n"
        + "int main() {\n    Box<Item> box = Box(Item(1), Item(2));\n    return box.head().value - 1;\n}\n",
        REFUSED_COMPARISON,
    ),
    "demanded-sort": Case(
        "import Library.Vector;\n"
        + ITEM
        + "void unused() {\n    Vector<Item> items = [];\n    items.sort();\n}\n"
        + "int main() { return 0; }\n",
        REFUSED_COMPARISON,
    ),
    # Every specialization's constructor is lowered, used or not.
    "constructor": Case(
        ITEM
        + "class Pair<T> {\n    public bool ordered;\n    public Pair(T first, T second) { self.ordered = first < second; }\n}\n"
        + "int main() {\n    Pair<Item>? pair = null;\n    return pair == null ? 0 : 1;\n}\n",
        REFUSED_COMPARISON,
    ),
}
MODULE_UNIT_CASES = ("unsorted-vector", "undemanded-chain", "demanded-chain")


@dataclass(frozen=True)
class Outcome:
    """One compiler's run and the C file it was asked to write."""

    result: subprocess.CompletedProcess[str]
    output: Path

    def definitions(self) -> set[str]:
        return set(SPECIALIZED_DEFINITION.findall(self.output.read_text()))


def compile_both(btrcc: Path, root: Path, source: str, target: str, *flags: str) -> dict[str, Outcome]:
    """Compile Main.btrc through each compiler, with --no-dce, in its own directory."""

    outcomes = {}
    for frontend in ("reference", "selfhost"):
        directory = root / frontend
        directory.mkdir(parents=True)
        program = directory / "Main.btrc"
        program.write_text(source)
        arguments = ["--no-dce", "--no-cache", *flags, "-o", str(directory / "Main.c")]
        if target != "host":
            arguments.extend(("--target", target))
        if "--module-units" in flags:
            arguments.extend(("--emit-units", str(directory / "units")))
        command = (
            [sys.executable, "-m", "src.compiler.python.main", str(program), *arguments]
            if frontend == "reference"
            else [str(btrcc), *arguments, str(program)]
        )
        result = subprocess.run(
            command,
            cwd=REPO,
            env={**os.environ, "BTRC_HOME": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        outcomes[frontend] = Outcome(result, directory / "Main.c")
    return outcomes


def assert_compiled(outcomes: dict[str, Outcome]) -> None:
    for frontend, outcome in outcomes.items():
        assert outcome.result.returncode == 0, (frontend, outcome.result.stderr)
        assert outcome.output.is_file(), frontend


def assert_same_refusal(outcomes: dict[str, Outcome], expected: str) -> None:
    for frontend, outcome in outcomes.items():
        assert (outcome.result.returncode, outcome.result.stderr) == (1, expected), frontend
        assert not outcome.output.exists(), frontend


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("module", MODULES)
def test_a_stdlib_module_alone_compiles_without_dce(
    immutable_btrcc: Path, tmp_path: Path, module: str, target: str
) -> None:
    source = f"import Library.{module};\n\nint main() {{ return 0; }}\n"
    outcomes = compile_both(immutable_btrcc, tmp_path, source, target)
    assert_compiled(outcomes)
    reference = outcomes["reference"].definitions()
    selfhost = outcomes["selfhost"].definitions()
    assert reference
    assert sorted(selfhost ^ reference) == [], "the compilers define different generic specializations"


@pytest.mark.parametrize("name", sorted(CASES))
def test_generic_demand_matches_the_reference_without_dce(immutable_btrcc: Path, tmp_path: Path, name: str) -> None:
    case = CASES[name]
    outcomes = compile_both(immutable_btrcc, tmp_path, case.source, "host")
    if case.refusal is not None:
        assert_same_refusal(outcomes, case.refusal)
        return
    assert_compiled(outcomes)
    for frontend, outcome in outcomes.items():
        assert [symbol for symbol in sorted(outcome.definitions()) if symbol.endswith(case.undemanded)] == [], frontend
    assert outcomes["selfhost"].definitions() == outcomes["reference"].definitions()


@pytest.mark.parametrize("name", MODULE_UNIT_CASES)
def test_module_units_keep_the_reference_demand_without_dce(immutable_btrcc: Path, tmp_path: Path, name: str) -> None:
    case = CASES[name]
    outcomes = compile_both(immutable_btrcc, tmp_path, case.source, "host", "--module-units")
    if case.refusal is not None:
        assert_same_refusal(outcomes, case.refusal)
    else:
        assert_compiled(outcomes)
