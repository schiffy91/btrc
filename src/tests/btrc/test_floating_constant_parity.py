"""Floating constants, their binary32 edges and untyped globals, in both compilers.

C11 6.4.4.2 spells a floating constant without a digit on one side of its
point (``.5f``, ``5.f``, ``1.e5f``); both lexers read those, while a dot after
an operand still selects its member or tuple field (``t.0.1``, ``f().0``). An
``f`` literal rounds once, from its exact decimal value, to binary32: the
overflow and underflow refusals compare that value with the binary32
midpoints, never with a double first rounded onto one. A static initializer
may not cast a floating constant out of its integer type's range (C11
6.3.1.4p1), and an untyped global ``var`` has its inferred C type in both
compilers and every unit layout. Each refusal carries one diagnostic --
message, line and column -- in both compilers; each accepted program builds
under strict C11 and prints the same output from both.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import random
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from src.compiler.python.lexer.lexer import Lexer, LiteralDecoder
from src.compiler.python.syntax.tokens import TokenKind
from src.tests.btrc.diagnostic_harness import diagnostic_identity
from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.c_toolchains import configured_c_compiler

REPO = Path(__file__).resolve().parents[3]
CC = configured_c_compiler()

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

# The decimal expansions of the binary32 midpoints: 2^128 - 2^103, the first
# magnitude that rounds to infinity, and 2^-150, the last that rounds to zero.
OVERFLOW_MIDPOINT = "340282356779733661637539395458142568448"
UNDERFLOW_MIDPOINT = (
    "7.00649232162408535461864791644958065640130970938257885878534141944895541342930300743319094181060791015625e-46"
)
FLOAT_RANGE = "is outside the finite float range"
FLOAT_UNDERFLOW = "underflows to zero as float"


def _tokens(source: str) -> list[tuple[TokenKind, str]]:
    return [(token.type, token.value) for token in Lexer(source).tokenize()[:-1]]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (".5f", [(TokenKind.FLOAT_LIT, ".5f")]),
        ("5.f", [(TokenKind.FLOAT_LIT, "5.f")]),
        ("1.e5f", [(TokenKind.FLOAT_LIT, "1.e5f")]),
        ("5.", [(TokenKind.FLOAT_LIT, "5.")]),
        (".5e-1", [(TokenKind.FLOAT_LIT, ".5e-1")]),
        ("09.", [(TokenKind.FLOAT_LIT, "09.")]),
        (
            "x = .5;",
            [(TokenKind.IDENT, "x"), (TokenKind.EQ, "="), (TokenKind.FLOAT_LIT, ".5"), (TokenKind.SEMICOLON, ";")],
        ),
        (
            "(int).5",
            [(TokenKind.LPAREN, "("), (TokenKind.INT, "int"), (TokenKind.RPAREN, ")"), (TokenKind.FLOAT_LIT, ".5")],
        ),
        # A dot after an operand selects; a field index is digits alone.
        ("t.0", [(TokenKind.IDENT, "t"), (TokenKind.DOT, "."), (TokenKind.INT_LIT, "0")]),
        (
            "t.0.1",
            [
                (TokenKind.IDENT, "t"),
                (TokenKind.DOT, "."),
                (TokenKind.INT_LIT, "0"),
                (TokenKind.DOT, "."),
                (TokenKind.INT_LIT, "1"),
            ],
        ),
        (
            "t.0.size",
            [
                (TokenKind.IDENT, "t"),
                (TokenKind.DOT, "."),
                (TokenKind.INT_LIT, "0"),
                (TokenKind.DOT, "."),
                (TokenKind.IDENT, "size"),
            ],
        ),
        (
            "a[0].1",
            [
                (TokenKind.IDENT, "a"),
                (TokenKind.LBRACKET, "["),
                (TokenKind.INT_LIT, "0"),
                (TokenKind.RBRACKET, "]"),
                (TokenKind.DOT, "."),
                (TokenKind.INT_LIT, "1"),
            ],
        ),
        (
            "f().0",
            [(TokenKind.IDENT, "f"), (TokenKind.LPAREN, "("), (TokenKind.RPAREN, ")"), (TokenKind.FLOAT_LIT, ".0")],
        ),
        # Dots after digits stay dots, as in a GNU range.
        (
            "1...5",
            [
                (TokenKind.INT_LIT, "1"),
                (TokenKind.DOT, "."),
                (TokenKind.DOT, "."),
                (TokenKind.DOT, "."),
                (TokenKind.INT_LIT, "5"),
            ],
        ),
    ],
)
def test_reference_lexer_reads_dotted_floating_constants(source: str, expected: list[tuple[TokenKind, str]]) -> None:
    assert _tokens(source) == expected


ACCEPTED = """\
#include <assert.h>
#include <stdio.h>

enum Scaled { HALF = (int).5f, FIVE = (int)5.f, LARGE = (int)1.e5f };

float largest = 340282356779733661637539395458142568447.0f;
float smallest =
	7.006492321624085354618647916449580656401309709382578858785341419448955413429303007433190941810607910156251e-46f;
static double reciprocal = 1.0 / 1e-50;
static int truncated = (int)-2147483648.9;
static unsigned int zero = (unsigned int)-0.5;

int main() {
	long long quarter = (long long).25;
	var pair = (1, (2, .5));
	assert(pair.1.1 == .5 && (pair.1).0 == 2);
	assert(largest == 340282346638528859811704183484516925440.0f);
	assert(smallest > 0.0f && reciprocal > 1e49 && quarter == 0);
	printf("%d %d %d %d %u %.1f %.1f\\n", HALF, FIVE, LARGE, truncated, zero, .5 + 5., 1.e1);
	return 0;
}
"""


def _build_and_run(compiler: list[str], program: Path, directory: Path, layout: list[str] | None) -> str:
    """Transpile ``program`` in one unit layout, link every unit strictly, run it."""
    directory.mkdir()
    primary = directory / "program.c"
    plan = directory / "program.json"
    command = [*compiler, "--no-cache", str(program), "-o", str(primary)]
    if layout is not None:
        command += ["--emit-units", str(directory / "program"), *layout]
    command += ["--emit-link-plan", str(plan)]
    transpiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=300)
    assert transpiled.returncode == 0, transpiled.stderr
    units = json.loads(plan.read_text()).get("emitted-units", [])
    binary = directory / "program"
    built = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(primary),
            *units,
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], cwd=directory, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


def _compilers(semantic_btrcc: Path) -> dict[str, list[str]]:
    return {
        "reference": [sys.executable, "-m", "src.compiler.python.main"],
        "selfhost": [str(semantic_btrcc)],
    }


def test_dotted_constants_and_float_edges_run_identically(semantic_btrcc: Path, tmp_path: Path) -> None:
    program = tmp_path / "Accepted.btrc"
    program.write_text(ACCEPTED)
    for name, compiler in _compilers(semantic_btrcc).items():
        stdout = _build_and_run(compiler, program, tmp_path / name, None)
        assert stdout == "0 5 100000 -2147483648 0 5.5 10.0\n", name


SHARED_GLOBALS = """\
class Point {
	public int x;

	public Point(int x) { self.x = x; }
}

var sharedGreeting = "hi";
var sharedRatio = 2.5;
var sharedNarrow = .5f;
var sharedWide = 3000000000;
var sharedSuffixed = 3000000000LL;
var sharedHex = 0xFFFFFFFF;
var sharedFlag = true;
var sharedPoint = (Point?)null;
"""

GLOBALS_MAIN = """\
#include <stdio.h>
import ./Shared.btrc;

int main() {
	sharedWide = sharedWide + 1;
	sharedPoint = Point(4);
	int x = sharedPoint?.x ?? 0;
	sharedPoint = null;
	printf("%s %.2f %.2f %lld %lld %u %d %d\\n", sharedGreeting, sharedRatio, (double)sharedNarrow,
		(long long)sharedWide, sharedSuffixed, sharedHex, sharedFlag ? 1 : 0, x);
	return 0;
}
"""


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(None, id="single-unit"),
        pytest.param([], id="split"),
        pytest.param(["--module-units"], id="module-units"),
    ],
)
def test_untyped_globals_take_their_inferred_type_in_every_unit(
    semantic_btrcc: Path,
    tmp_path: Path,
    layout: list[str] | None,
) -> None:
    (tmp_path / "Shared.btrc").write_text(SHARED_GLOBALS)
    program = tmp_path / "Main.btrc"
    program.write_text(GLOBALS_MAIN)
    for name, compiler in _compilers(semantic_btrcc).items():
        stdout = _build_and_run(compiler, program, tmp_path / name, layout)
        assert stdout == "hi 2.50 0.50 3000000001 3000000000 4294967295 1 4\n", name


def _out_of_range(spelling: str, target: str) -> str:
    return f"Floating constant '{spelling}' is out of range for '{target}' in a static initializer"


REFUSALS = [
    pytest.param(
        "int main() { int x = 5 .f; return x; }",
        ("Numeric literal '5' has no field 'f'", 1, 22),
        id="spaced-integer-literal-field",
    ),
    pytest.param(
        "int main() { int x = (5).x; return x; }",
        ("Numeric literal '5' has no field 'x'", 1, 23),
        id="parenthesized-integer-literal-field",
    ),
    pytest.param(
        "int main() { double x = 2.5 .y; return 0; }",
        ("Numeric literal '2.5' has no field 'y'", 1, 25),
        id="floating-literal-field",
    ),
    pytest.param(
        "int main() { long long y = (long long).x; return 0; }",
        ("Expected expression after a cast, got DOT '.'", 1, 39),
        id="member-of-type-name",
    ),
    pytest.param(
        "int main() { int x = 5.x; return x; }", ("Invalid numeric literal '5.x'", 1, 22), id="trailing-dot-tail"
    ),
    pytest.param(
        "int main() { float x = .5x; return 0; }", ("Invalid numeric literal '.5x'", 1, 24), id="leading-dot-tail"
    ),
    pytest.param(
        "int main() { double x = 5.e; return 0; }",
        ("Invalid float literal: no digits in exponent", 1, 25),
        id="trailing-dot-empty-exponent",
    ),
    pytest.param(
        f"int main() {{ float x = {OVERFLOW_MIDPOINT}.0f; return 0; }}",
        (f"Floating literal '{OVERFLOW_MIDPOINT}.0f' {FLOAT_RANGE}", 1, 24),
        id="float-overflow-midpoint",
    ),
    pytest.param(
        f"int main() {{ float x = {UNDERFLOW_MIDPOINT}f; return 0; }}",
        (f"Floating literal '{UNDERFLOW_MIDPOINT}f' {FLOAT_UNDERFLOW}", 1, 24),
        id="float-underflow-midpoint",
    ),
    pytest.param(
        "static int big = (int)1e30;\nint main() { return big; }",
        (_out_of_range("1e30", "int"), 1, 18),
        id="static-global",
    ),
    pytest.param(
        "int g = (int)-1e20;\nint main() { return g; }",
        (_out_of_range("-1e20", "int"), 1, 9),
        id="negated-global",
    ),
    pytest.param(
        "unsigned char c = (unsigned char)300.0;\nint main() { return c; }",
        (_out_of_range("300.0", "unsigned char"), 1, 19),
        id="unsigned-char-global",
    ),
    pytest.param(
        "unsigned int u = (unsigned int)-1.0;\nint main() { return 0; }",
        (_out_of_range("-1.0", "unsigned int"), 1, 18),
        id="negative-unsigned-global",
    ),
    pytest.param(
        "var v = (int)1e30;\nint main() { return v; }",
        (_out_of_range("1e30", "int"), 1, 9),
        id="untyped-global",
    ),
    pytest.param(
        "int values[2] = {1, (int)2147483648.0};\nint main() { return values[0]; }",
        (_out_of_range("2147483648.0", "int"), 1, 21),
        id="aggregate-element",
    ),
    pytest.param(
        "long long g = (long long)1e19 + 1;\nint main() { return 0; }",
        (_out_of_range("1e19", "long long"), 1, 15),
        id="arithmetic-operand",
    ),
    pytest.param(
        "int main() { static int s = (int)3e9f; return s; }",
        (_out_of_range("3e9f", "int"), 1, 29),
        id="static-local",
    ),
    pytest.param(
        "class Limits { class int big = (short)40000.0; }\nint main() { return 0; }",
        (_out_of_range("40000.0", "short"), 1, 32),
        id="static-class-field",
    ),
]


@pytest.mark.parametrize(("source", "expected"), REFUSALS)
def test_refusal_is_identical_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    expected: tuple[str, int, int],
) -> None:
    selfhost, reference = compile_diagnostic_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0 and reference.returncode != 0
    assert diagnostic_identity(reference.stderr) == expected
    assert diagnostic_identity(selfhost.stderr) == expected


def _libc_strtof():
    library = ctypes.util.find_library("c")
    if library is None:
        return None
    strtof = ctypes.CDLL(library).strtof
    strtof.restype = ctypes.c_float
    strtof.argtypes = (ctypes.c_char_p, ctypes.c_void_p)
    return strtof


def _edge_spellings(seed: int, count: int) -> list[str]:
    """Decimal spellings just inside, on and just outside both midpoints."""
    generator = random.Random(seed)
    spellings: list[str] = []
    with localcontext() as context:
        context.prec = 200
        for midpoint in (Decimal(OVERFLOW_MIDPOINT), Decimal(UNDERFLOW_MIDPOINT)):
            for _ in range(count):
                # A relative nudge from 1e-60 up to 1e-6 in either direction, or none.
                exponent = generator.randint(6, 60)
                nudge = Decimal(generator.choice((-1, 0, 1)) * generator.randint(1, 9)).scaleb(-exponent)
                value = midpoint * (1 + nudge)
                spellings.append(format(value, "f") if midpoint > 1 else format(value, "e"))
    # The midpoints themselves in the forms the lexer reads.
    spellings += [
        f"{OVERFLOW_MIDPOINT}.",
        f"{OVERFLOW_MIDPOINT}.0",
        f"{OVERFLOW_MIDPOINT[0]}.{OVERFLOW_MIDPOINT[1:]}e38",
    ]
    spellings += [UNDERFLOW_MIDPOINT, "." + UNDERFLOW_MIDPOINT.replace(".", "").split("e")[0] + "e-45"]
    return spellings


def _strtof_problem(strtof, body: str) -> str | None:
    value = strtof(body.encode(), None)
    if value == float("inf"):
        return FLOAT_RANGE
    if value == 0.0:
        return FLOAT_UNDERFLOW
    return None


def test_reference_float_edges_match_strtof() -> None:
    strtof = _libc_strtof()
    if strtof is None:
        pytest.skip("needs the C library's strtof")
    spellings = _edge_spellings(seed=12, count=400)
    mismatches = []
    for body in spellings:
        raw = f"{body}f"
        problem = LiteralDecoder.float_problem(raw, float(body))
        expected = _strtof_problem(strtof, body)
        actual = None if problem is None else (FLOAT_RANGE if FLOAT_RANGE in problem else FLOAT_UNDERFLOW)
        if actual != expected:
            mismatches.append((raw, actual, expected))
    assert {_strtof_problem(strtof, body) for body in spellings} == {None, FLOAT_RANGE, FLOAT_UNDERFLOW}
    assert mismatches == []


def test_selfhost_float_edges_match_strtof(semantic_btrcc: Path, tmp_path: Path) -> None:
    strtof = _libc_strtof()
    if strtof is None:
        pytest.skip("needs the C library's strtof")
    program = tmp_path / "edge.btrc"
    mismatches = []
    for body in _edge_spellings(seed=34, count=12):
        program.write_text(f"int main() {{ float value = {body}f; return value > 0.0f ? 0 : 1; }}\n")
        result = subprocess.run(
            [str(semantic_btrcc), "--no-stdlib", str(program)], cwd=REPO, capture_output=True, text=True, timeout=60
        )
        actual = None
        if result.returncode != 0:
            actual = FLOAT_RANGE if FLOAT_RANGE in result.stderr else FLOAT_UNDERFLOW
            assert FLOAT_RANGE in result.stderr or FLOAT_UNDERFLOW in result.stderr, result.stderr
        expected = _strtof_problem(strtof, body)
        if actual != expected:
            mismatches.append((body, actual, expected))
    assert mismatches == []
