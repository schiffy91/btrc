"""C4 preprocessor conditionals (c-preprocessor-conditionals.md, PLAN.md Stage 16).

This is the reference compiler's half. Every table here is shared: the
self-hosted port (CL-C-06) runs the same expression battery through
``ConditionalExpressionDriver.btrc`` and the same diagnostic rows through
btrcc, and must match each message and file-local ``line:col`` exactly. Every
battery is ASCII, because Python counts columns in code points and btrc in
bytes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python import Compiler
from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.application.results import CompilerOptions, CompilerOutput
from src.compiler.python.frontend.packages import PackageTarget
from src.compiler.python.frontend.sources import (
    ConditionalEnvironment,
    PreprocessorConditionalError,
    SourceConditionals,
)
from src.compiler.python.ir.lowering.types import CodegenError
from src.compiler.python.syntax.ast.generated import PreprocessorDirective
from tools.compiler_codegen.hosted_abi import TargetManifest

REPO = Path(__file__).resolve().parents[3]
TESTS = REPO / "src" / "tests"
BATTERY = Path(__file__).resolve().parent / "fixtures" / "conditional_expressions.tsv"
LINUX = ConditionalEnvironment(PackageTarget("linux", "x86_64"))
TIMEOUT = 120


# -- The shared expression battery ------------------------------------------


@dataclass(frozen=True)
class ExpressionCase:
    defines: tuple[str, ...]
    payload: str
    expected: str

    @property
    def source(self) -> str:
        return "\n".join((*self.defines, f"#if {self.payload}", "taken", "#endif", ""))

    @classmethod
    def load(cls) -> list[ExpressionCase]:
        cases = []
        for line in BATTERY.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            defines, payload, expected = line.split("\t")
            cases.append(cls(() if defines == "-" else tuple(defines.split(";")), payload, expected))
        return cases


EXPRESSION_CASES = ExpressionCase.load()


def reference_outcome(case: ExpressionCase) -> str:
    try:
        conditioned = SourceConditionals(LINUX).condition(case.source, "/battery/Case.btrc")
    except PreprocessorConditionalError as error:
        return f"error {error.line}:{error.col} {error.message}"
    return "1" if "taken" in conditioned.text else "0"


def test_battery_is_ascii_and_large_enough() -> None:
    assert BATTERY.read_text(encoding="utf-8").isascii()
    assert len(EXPRESSION_CASES) >= 60


@pytest.mark.parametrize("case", EXPRESSION_CASES, ids=lambda case: case.payload)
def test_expression_battery(case: ExpressionCase) -> None:
    assert reference_outcome(case) == case.expected


# -- Directive structure, shapes and blanking -------------------------------


def condition(source: str, environment: ConditionalEnvironment = LINUX) -> str:
    return SourceConditionals(environment).condition(source, "/t/Main.btrc").text


def conditioning_error(source: str) -> tuple[str, int, int]:
    with pytest.raises(PreprocessorConditionalError) as raised:
        condition(source)
    return raised.value.message, raised.value.line, raised.value.col


def test_blanking_keeps_every_line_and_live_bytes() -> None:
    source = "int a;\n#if 0\nint b;\n#else\n  int c; // live\n#endif\nint d;"
    conditioned = condition(source)
    assert conditioned.split("\n") == ["int a;", "", "", "", "  int c; // live", "", "int d;"]


def test_nested_dead_groups_are_never_evaluated() -> None:
    source = "#if 0\n#if garbage (\n#elif 1/0\nx\n#endif\n#elif 1\ny\n#endif\n"
    assert condition(source) == "\n\n\n\n\n\ny\n\n"


def test_elif_after_a_taken_group_is_not_lexed() -> None:
    assert condition("#if 1\na\n#elif 1/0 garbage (\nb\n#endif\n") == "\na\n\n\n\n"


def test_a_comment_hides_directive_lines_as_c_phase_3_does() -> None:
    source = "/*\n#if FOO\n*/\nint a;\n#if 1\nint b;\n#endif\n"
    assert condition(source) == "/*\n#if FOO\n*/\nint a;\n\nint b;\n\n"


DIRECTIVE_ERRORS = [
    ("#endif", ("'#endif' without '#if'", 1, 1)),
    ("#else", ("'#else' without '#if'", 1, 1)),
    ("#elif 1", ("'#elif' without '#if'", 1, 1)),
    ("#if 1\n#else\n#elif 1\n#endif", ("'#elif' after '#else'", 3, 1)),
    ("#if 1\n#else\n#else\n#endif", ("'#else' after '#else'", 3, 1)),
    ("#if 1\n", ("'#if' without '#endif'", 1, 1)),
    ("#if 1\n#ifndef A\n#endif", ("'#if' without '#endif'", 1, 1)),
    ("#ifdef X\n", ("'#ifdef' without '#endif'", 1, 1)),
    ("#ifdef\n#endif", ("'#ifdef' needs a macro name", 1, 1)),
    ("#ifndef 3\n#endif", ("'#ifndef' needs a macro name, got '3'", 1, 9)),
    ("#ifdef true\n#endif", ("'#ifdef' needs a macro name, got 'true'", 1, 8)),
    ("#ifdef X Y\n#endif", ("'#ifdef' takes one macro name; unexpected 'Y'", 1, 10)),
    ("#ifdef X #\n#endif", ("'#ifdef' takes one macro name; unexpected '#'", 1, 10)),
    ("#if 1\n#else if X\n#endif", ("'#else' takes no operands; unexpected 'if'", 2, 7)),
    ("#if 1\n#endif X", ("'#endif' takes no operands; unexpected 'X'", 2, 8)),
    ("#if\n#endif", ("'#if' needs an expression", 1, 1)),
    ("#if 0\n#elif /* empty */\n#endif", ("'#elif' needs an expression", 2, 1)),
    ("#elifdef X", ("'#elifdef' is C23; write '#elif defined(NAME)'", 1, 1)),
    ("#if 0\n#if 1\n#elifndef X\n#endif\n#endif", ("'#elifndef' is C23; write '#elif !defined(NAME)'", 3, 1)),
    ("#error stop /* why */ here", ("#error stop   here", 1, 1)),
    ("#error", ("#error", 1, 1)),
    ("#if 1\n#error inside\n#endif", ("#error inside", 2, 1)),
    ("#if 1 \\\n+ 1\n#endif", ("multi-line preprocessor directives are unsupported", 1, 7)),
    ("int a; // note \\\n#if 1\n#endif", ("multi-line preprocessor directives are unsupported", 1, 16)),
    ("#\\\nif 1\n#endif", ("multi-line preprocessor directives are unsupported", 1, 2)),
    ("#if 0\n#define X \\\n1\n#endif", ("multi-line preprocessor directives are unsupported", 2, 11)),
    ("#if 1 ??= 2\n#endif", ("C11 trigraphs in preprocessor directives are unsupported", 1, 7)),
    ("%:if 1\n#endif", ("'%:' is not supported as a spelling of '#'; write '#'", 1, 1)),
    ("  ??=if 1", ("'??=' is not supported as a spelling of '#'; write '#'", 1, 3)),
    ("#if 1 /* open\nclose */\n#endif", ("a comment in a preprocessor directive must close on the same line", 1, 7)),
    (
        "#if 0\n#define X 1 /* open\n*/\n#endif",
        ("a comment in a preprocessor directive must close on the same line", 2, 13),
    ),
    ("#/**/if 1\n#endif", ("a comment between '#' and the directive name is unsupported", 1, 2)),
    ("#if\f1\n#endif", ("only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)", 1, 4)),
    ("#if 1\n#endif\v", ("only spaces and tabs may separate tokens in a preprocessor directive (C11 6.10p5)", 2, 7)),
    ("// note \\\n#define M 1\n#ifdef M\n#endif", ("multi-line preprocessor directives are unsupported", 1, 9)),
    (
        "#define M 1\n// note \\\n#undef M\n#ifdef M\n#endif",
        ("multi-line preprocessor directives are unsupported", 2, 9),
    ),
    ('#if 1\nstring s = "open;\n#endif', ("Unterminated string literal", 2, 12)),
    ("#if 0\nint x = 08;\n#endif", ("Invalid digit '8' in octal literal", 2, 9)),
    (
        "#define N 1\n#if N\n#endif\n#define N 2",
        ("Macro 'N' is redefined with a different replacement; #undef it first (C11 6.10.3p2)", 4, 1),
    ),
    ("#undef defined\n#if 1\n#endif", ("'defined' cannot be #define'd or #undef'd (C11 6.10.8p2)", 1, 1)),
    (
        "#define NDEBUG 1\n#if 1\n#endif",
        ("'NDEBUG' is set by C headers or compiler flags; btrc sources cannot #define or #undef it", 1, 1),
    ),
    ("#define int long\n#if 1\n#endif", ("'int' is a reserved word and cannot be used as a name", 1, 1)),
    ("#define BTRC_X 1\n#if 1\n#endif", ("Macro name 'BTRC_X' uses the compiler-reserved 'BTRC_' prefix", 1, 1)),
    ("#undef BTRC_X\n#if 1\n#endif", ("Source #undef of compiler-owned C symbol 'BTRC_X' is not allowed", 1, 1)),
]


@pytest.mark.parametrize(("source", "expected"), DIRECTIVE_ERRORS, ids=[row[1][0] for row in DIRECTIVE_ERRORS])
def test_directive_diagnostics(source: str, expected: tuple[str, int, int]) -> None:
    assert conditioning_error(source) == expected


def test_identical_redefinition_and_environment_undef_are_accepted() -> None:
    source = "#define L 10\n#define L  10 /* same */\n#define T 1\n#undef T\n#ifdef T\nx\n#else\ny\n#endif\n"
    assert condition(source).split("\n")[5:8] == ["", "", "y"]


def test_no_target_fails_only_at_the_first_evaluated_conditional() -> None:
    environment = ConditionalEnvironment(None)
    assert condition("int a;\n", environment) == "int a;\n"
    assert condition("#define X 1\nint a;\n", environment) == "#define X 1\nint a;\n"
    with pytest.raises(PreprocessorConditionalError) as raised:
        condition("int a;\n  #ifdef X\n#endif\n", environment)
    assert (raised.value.message, raised.value.line, raised.value.col) == (
        "preprocessor conditionals need a target; this host is not a btrc target, so pass --target OS-ARCH",
        2,
        3,
    )


def test_test_records_cover_evaluated_absent_and_local_names_only() -> None:
    source = (
        "#define A 1\n#ifdef A\n#endif\n#if 0 && defined(B)\n#endif\n#ifndef C\n#endif\n#if A && __linux__\n#endif\n"
    )
    tests = SourceConditionals(LINUX).condition(source, "/t/Main.btrc").tests
    assert [(test.name, test.line, test.col, test.local) for test in tests] == [
        ("A", 2, 8, True),
        ("C", 6, 9, False),
        ("A", 8, 5, True),
    ]


# -- The fast path ----------------------------------------------------------

FAST_PATH_SHAPES = [
    "#\\\nif 1\n#endif",
    "#/**/if 1\n#endif",
    "%:if 1\n%:endif",
    "int a; // c \\\n#if 1\n#else\n#endif",
    "#define X 1 /* open\n*/",
    "#if 1\n#endif",
]


def test_fast_path_candidate_regex() -> None:
    for source in FAST_PATH_SHAPES[:-2]:
        assert SourceConditionals.candidate(source), source
    for source in ("#define X 1\n", "#include <stdio.h>\n", "int ifx;\n", "x #if\n", "#pragma pack(push)\n"):
        assert not SourceConditionals.candidate(source), source
    assert SourceConditionals.candidate("  #  endif")
    assert SourceConditionals.candidate("#\tif 1")


def test_slow_path_returns_every_non_candidate_corpus_file_unchanged() -> None:
    """The fast path is unobservable: a forced slow path changes no file without a candidate line."""

    from src.compiler.python.frontend.sources import _ConditionalWalk

    checked = 0
    for path in sorted(TESTS.rglob("*.btrc")):
        text = path.read_text(encoding="utf-8")
        if SourceConditionals.candidate(text) or "\r" in text:
            continue
        try:
            conditioned = _ConditionalWalk(LINUX, str(path), text).run()
        except PreprocessorConditionalError:
            # A raw-lex or name-rule failure the main lexer or analyzer reports too.
            continue
        assert conditioned.text == text, path
        checked += 1
    assert checked > 1000


# -- The C oracle -----------------------------------------------------------

C_ORACLE = [
    "1",
    "0",
    "1 + 2 * 3 == 7",
    "7 / -2 == -3",
    "7 % -2 == 1",
    "-7 / 2 == -3",
    "-7 % 2 == -1",
    "0xffffffffffffffff == 18446744073709551615u",
    "0xffffffffffffffff > 0",
    "-1 < 0",
    "~0 == -1",
    "~0u == 0xffffffffffffffff",
    "-8 >> 1 == -4",
    "1 << 62 == 4611686018427387904",
    "0u - 1 == 18446744073709551615u",
    "!0 && !!5",
    "1 ? 2 : 3",
    "0 ? 1 : 0",
    "3 & 5 ^ 1 | 8",
    "'A' == 65",
    "'\\n' == 10",
    "'\\x41' == 65",
    "017 == 15",
    "0 && (1 / 0)",
    "1 || (1 / 0)",
    "0 ? 1 / 0 : 2",
    "(1 ? 0 : 1)",
    "defined(__linux__)",
    "defined __x86_64__",
    "defined(__APPLE__)",
    "defined(_WIN32)",
    "__CHAR_BIT__ == 8",
    "__SIZEOF_INT__ == 4",
    "__SIZEOF_LONG_LONG__ == 8",
    "__SIZEOF_POINTER__ == 8",
    "__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__",
    "__STDC_VERSION__ >= 201112L",
    "__STDC__",
    "9223372036854775807 > 0",
    "(2 + 3) * (4 - 1) == 15",
    "10 / 3 * 3 + 10 % 3 == 10",
]
C_ORACLE_COMPILERS = [compiler for compiler in ("gcc", "clang") if shutil.which(compiler)]
HOST_IS_LINUX_X86_64 = sys.platform.startswith("linux") and os.uname().machine in {"x86_64", "amd64"}


def c_selection(
    compiler: str, source: str, tmp_path: Path, *, pedantic: bool = True
) -> subprocess.CompletedProcess[str]:
    program = tmp_path / "oracle.c"
    program.write_text(source)
    return subprocess.run(
        [compiler, "-std=c11", *(("-pedantic-errors",) if pedantic else ()), "-E", "-P", str(program)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


@pytest.mark.skipif(not C_ORACLE_COMPILERS, reason="requires gcc or clang")
@pytest.mark.skipif(not HOST_IS_LINUX_X86_64, reason="the oracle compares against the host's own C preprocessor")
@pytest.mark.parametrize("expression", C_ORACLE)
def test_c_oracle_selects_identically(expression: str, tmp_path: Path) -> None:
    source = f"#if {expression}\nint s = 1;\n#else\nint s = 0;\n#endif\n"
    ours = "int s = 1;" in condition(source)
    for compiler in C_ORACLE_COMPILERS:
        result = c_selection(compiler, source, tmp_path)
        assert result.returncode == 0, (compiler, result.stderr)
        assert ("int s = 1;" in result.stdout) == ours, (compiler, expression)


C_SHAPES = [
    # A comment between '#' and the name (gccprobe/comment.c): C reads a directive.
    "#/**/if 0\nint s = 1;\n#else\nint s = 0;\n#endif\n",
    # A '//' comment continued by a splice (gccprobe/linecomment.c): C swallows the #else.
    "#if 1\nint s = 1; // note \\\n#else\nint s = 0;\n#endif\n",
    # A digraph directive (gccprobe/digraph.c).
    "%:if 0\nint s = 1;\n%:else\nint s = 0;\n%:endif\n",
    # A form feed inside a directive (gccprobe/formfeed.c).
    "#if\f0\nint s = 1;\n#else\nint s = 0;\n#endif\n",
]


@pytest.mark.parametrize("source", C_SHAPES)
def test_c_shape_cases_are_refused(source: str, tmp_path: Path) -> None:
    with pytest.raises(PreprocessorConditionalError):
        condition(source)
    for compiler in C_ORACLE_COMPILERS:
        # C reads each shape in translation phases 1-3 first; btrc's directive
        # token does not, so the two would disagree on what is selected.
        assert c_selection(compiler, source, tmp_path, pedantic=False).returncode == 0, compiler


def test_pinned_deviations_from_c11() -> None:
    # true/false have their C23 values; C11 without <stdbool.h> reads 0.
    assert "x" in condition("#if true\nx\n#endif\n")
    # 0b and 0o constants are a documented btrc extension.
    assert "x" in condition("#if 0b11 == 3 && 0o7 == 7\nx\n#endif\n")
    # A negative left shift and a silent negative-to-unsigned conversion are errors.
    assert conditioning_error("#if -1 << 1\n#endif")[0] == "Left shift of negative value in #if expression"
    assert conditioning_error("#if -1 < 0u\n#endif")[0] == (
        "#if expression converts negative value -1 to unsigned for '<'"
    )


# -- Per-target selection and dead imports through the compiler -------------

SELECTION = """\
#if defined(__linux__)
#include <stdio.h>
int platform() { return 1; }
#elif defined(__APPLE__)
#include <stdlib.h>
int platform() { return 2; }
#else
#include <string.h>
int platform() { return 3; }
#endif
#if defined(__aarch64__)
int bits() { return 64; }
#else
int bits() { return 46; }
#endif
int main() { return platform() + bits(); }
"""


def compile_files(
    tmp_path: Path,
    files: dict[str, str],
    *,
    target: str | None = "linux-x86_64",
    output: CompilerOutput = CompilerOutput.C,
    use_cache: bool = False,
):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    root = tmp_path / "Main.btrc"
    options = CompilerOptions(output=output, include_stdlib=False, use_cache=use_cache, target=target)
    return Compiler().compile(root.read_text(), str(root), options)


@pytest.mark.parametrize("target", [f"{row.operating_system}-{row.architecture}" for row in TARGET_ROWS])
def test_per_target_selection(target: str, tmp_path: Path) -> None:
    result = compile_files(tmp_path, {"Main.btrc": SELECTION}, target=target)
    assert result.successful, result.failure
    system, architecture = target.split("-")
    header, value = {"linux": ("stdio.h", "1"), "macos": ("stdlib.h", "2"), "windows": ("string.h", "3")}[system]
    resolved = result.source_bundle.user_source
    assert [line for line in resolved.splitlines() if line.startswith("#include")] == [f"#include <{header}>"]
    assert resolved.count("int platform()") == 1
    assert resolved.count("int bits()") == 1
    assert f"#include <{header}>" in result.c_source
    assert f"return {value};" in result.c_source
    assert ("return 64;" in result.c_source) == (architecture == "aarch64")


def test_dead_import_adds_no_edge_or_source(tmp_path: Path) -> None:
    files = {
        "Main.btrc": "#if 0\nimport ./Missing.btrc;\nimport ./Conflict.btrc;\n#endif\nint value() { return 2; }\n"
        "int main() { return value(); }\n",
        "Conflict.btrc": "int value() { return 1; }\n",
    }
    result = compile_files(tmp_path, files)
    assert result.successful, result.failure
    assert result.source_bundle.graph.cache_records() == ()
    assert "Conflict" not in "".join(path for path, _line in result.source_bundle.source_positions)


def test_dead_c_import_is_not_spliced(tmp_path: Path) -> None:
    files = {
        "Main.btrc": "#ifdef __APPLE__\nimport ./helpers.c;\n#endif\nint main() { return 0; }\n",
        "helpers.c": "int helper(void) { return 1; }\n",
    }
    result = compile_files(tmp_path, files)
    assert result.successful, result.failure
    assert "helpers.c" not in result.c_source


# -- Diagnostics through the compiler, file-local ---------------------------


@dataclass(frozen=True)
class DiagnosticCase:
    name: str
    files: dict[str, str]
    message: str
    file: str
    line: int
    col: int


MANIFEST = 'manifest-version = 1\n[package]\nname = "example"\n'

DIAGNOSTIC_CASES = [
    DiagnosticCase(
        "I1",
        {"Main.btrc": "#if NOT_DEFINED_ANYWHERE\nint value() { return 1; }\n#endif\nint main() { return 0; }\n"},
        "Identifier 'NOT_DEFINED_ANYWHERE' in #if is not a macro defined earlier in this file or a target macro; "
        "test it with defined(NOT_DEFINED_ANYWHERE)",
        "Main.btrc",
        1,
        5,
    ),
    DiagnosticCase(
        "imported-file-position",
        {
            "Main.btrc": "import ./Other.btrc;\nint main() { return 0; }\n",
            "Other.btrc": "int other() { return 1; }\n\n#if 1\n#else\n#else\n#endif\n",
        },
        "'#else' after '#else'",
        "Other.btrc",
        5,
        1,
    ),
    DiagnosticCase(
        "resolution-order",
        {
            "Main.btrc": "import ./B.btrc;\nimport ./A.btrc;\n#endif\nint main() { return 0; }\n",
            "A.btrc": "#if FROM_A\n#endif\n",
            "B.btrc": "#if FROM_B\n#endif\n",
        },
        "'#endif' without '#if'",
        "Main.btrc",
        3,
        1,
    ),
    DiagnosticCase(
        "resolution-order-depth-first",
        {
            "Main.btrc": "import ./B.btrc;\nimport ./A.btrc;\nint main() { return 0; }\n",
            "A.btrc": "#if FROM_A\n#endif\n",
            "B.btrc": "#if FROM_B\n#endif\n",
        },
        "Identifier 'FROM_B' in #if is not a macro defined earlier in this file or a target macro; "
        "test it with defined(FROM_B)",
        "B.btrc",
        1,
        5,
    ),
    DiagnosticCase(
        "I3-package-define",
        {
            "btrc.toml": MANIFEST + '[[native.defines]]\nname = "EXAMPLE_ABI"\nvalue = "1"\n',
            "Main.btrc": "#ifdef EXAMPLE_ABI\n#endif\nint main() { return 0; }\n",
        },
        "'EXAMPLE_ABI' is a C compiler define of package 'example'; "
        "#if is evaluated before C compilation and cannot test it",
        "Main.btrc",
        1,
        8,
    ),
    DiagnosticCase(
        "P1",
        {
            "Main.btrc": "import ./Config.btrc;\n#ifdef USE_FAST\nint fast() { return 1; }\n#endif\n"
            "int main() { return 0; }\n",
            "Config.btrc": "#define USE_FAST 1\n",
        },
        "'USE_FAST' is defined in Config.btrc, but #if in Main.btrc cannot see it; "
        "#if sees only target macros and #defines earlier in the same file",
        "Main.btrc",
        2,
        8,
    ),
    DiagnosticCase(
        "P4",
        {
            "Main.btrc": "#define M 1\nimport ./Other.btrc;\n#if M\n#endif\nint main() { return 0; }\n",
            "Other.btrc": "#undef M\n",
        },
        "'M' is #undef'd in Other.btrc, but #if in Main.btrc cannot see that; "
        "#if sees only #defines and #undefs earlier in the same file",
        "Main.btrc",
        3,
        5,
    ),
    DiagnosticCase(
        "P3-quoted-include",
        {
            "Main.btrc": '#include "config.h"\n#ifndef HAVE_X\n#endif\nint main() { return 0; }\n',
            "config.h": "#define HAVE_X 1\n",
        },
        "'HAVE_X' may come from C that btrc does not read (\"config.h\" in Main.btrc); "
        "#if is evaluated before C compilation and cannot test it",
        "Main.btrc",
        2,
        9,
    ),
    DiagnosticCase(
        "P3-c-import",
        {
            "Main.btrc": "import ./helpers.c;\n#if defined(HAVE_HELPERS)\n#endif\nint main() { return 0; }\n",
            "helpers.c": "int helper(void) { return 1; }\n",
        },
        "'HAVE_HELPERS' may come from C that btrc does not read (helpers.c imported by Main.btrc); "
        "#if is evaluated before C compilation and cannot test it",
        "Main.btrc",
        2,
        13,
    ),
    DiagnosticCase(
        "M1-across-files",
        {
            "Main.btrc": "#define N 1\nimport ./Other.btrc;\nint main() { return N; }\n",
            "Other.btrc": "#define N 2\n",
        },
        "Macro 'N' is redefined with a different replacement; #undef it first (C11 6.10.3p2)",
        "Other.btrc",
        1,
        1,
    ),
    DiagnosticCase(
        "M2",
        {"Main.btrc": "#undef max\nint main() { return 0; }\n"},
        "#undef of 'max' is not allowed; btrc undefines only macros that its own sources #define",
        "Main.btrc",
        1,
        1,
    ),
    DiagnosticCase(
        "M3",
        {"Main.btrc": "#define defined 1\nint main() { return 0; }\n"},
        "'defined' cannot be #define'd or #undef'd (C11 6.10.8p2)",
        "Main.btrc",
        1,
        1,
    ),
    DiagnosticCase(
        "M4",
        {"Main.btrc": "#undef TARGET_OS_MAC\nint main() { return 0; }\n"},
        "'TARGET_OS_MAC' is set by C headers or compiler flags; btrc sources cannot #define or #undef it",
        "Main.btrc",
        1,
        1,
    ),
    DiagnosticCase(
        "U1",
        {"Main.btrc": "#define WRAP 1\n#undef WRAP\nint main() { return WRAP; }\n"},
        "Source macro 'WRAP' cannot be used in code because it is #undef'd; "
        "btrc emits every #define and #undef before the program",
        "Main.btrc",
        3,
        21,
    ),
    DiagnosticCase(
        "U1-call",
        {"Main.btrc": "#define WRAP(v) (v)\n#undef WRAP\nint main() { return WRAP(0); }\n"},
        "Source macro 'WRAP' cannot be used in code because it is #undef'd; "
        "btrc emits every #define and #undef before the program",
        "Main.btrc",
        3,
        21,
    ),
    DiagnosticCase(
        "U1-default",
        {"Main.btrc": "#define WRAP 1\n#undef WRAP\nint f(int v = WRAP) { return v; }\nint main() { return f(); }\n"},
        "Source macro 'WRAP' cannot be used in code because it is #undef'd; "
        "btrc emits every #define and #undef before the program",
        "Main.btrc",
        3,
        15,
    ),
    DiagnosticCase(
        "U1-constant",
        {"Main.btrc": "#define N 3\n#undef N\nenum E { A = N };\nint main() { return A; }\n"},
        "Source macro 'N' cannot be used in code because it is #undef'd; "
        "btrc emits every #define and #undef before the program",
        "Main.btrc",
        3,
        14,
    ),
    DiagnosticCase(
        "U2",
        {"Main.btrc": "#define WRAP 1\n#define A WRAP\n#undef WRAP\nint main() { return A; }\n"},
        "Source macro 'A' cannot be used in code because it expands to #undef'd macro 'WRAP'; "
        "btrc emits every #define and #undef before the program",
        "Main.btrc",
        4,
        21,
    ),
    DiagnosticCase(
        "B1-function",
        {"Main.btrc": "int main() {\n  #define X 1\n  return 0;\n}\n"},
        "Preprocessor directive '#define' must be at file scope",
        "Main.btrc",
        2,
        3,
    ),
    DiagnosticCase(
        "B1-class",
        {"Main.btrc": "class C {\n#include <stdio.h>\n  public int a;\n}\nint main() { return 0; }\n"},
        "Preprocessor directive '#include' must be at file scope",
        "Main.btrc",
        2,
        1,
    ),
    DiagnosticCase(
        "B1-operand",
        {"Main.btrc": "int main() {\n  int x = 1 +\n#undef X\n  2;\n  return x;\n}\n"},
        "Preprocessor directive '#undef' must be at file scope",
        "Main.btrc",
        3,
        1,
    ),
]

_RENDERED = re.compile(r"^error: (?P<message>.*)\n\s*--> (?P<path>.*):(?P<line>\d+):(?P<col>\d+)", re.MULTILINE)


def reference_diagnostic(tmp_path: Path, files: dict[str, str]) -> tuple[str, str, int, int]:
    """Compile through the reference CLI and read its first rendered error."""

    for name, text in files.items():
        (tmp_path / name).write_text(text)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(tmp_path / "Main.btrc"),
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x86_64",
            "-o",
            str(tmp_path / "Main.c"),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode != 0, result.stderr
    match = _RENDERED.search(result.stderr)
    assert match is not None, result.stderr
    return match["message"], os.path.basename(match["path"]), int(match["line"]), int(match["col"])


@pytest.mark.parametrize("case", DIAGNOSTIC_CASES, ids=lambda case: case.name)
def test_reference_diagnostics(case: DiagnosticCase, tmp_path: Path) -> None:
    assert reference_diagnostic(tmp_path, case.files) == (case.message, case.file, case.line, case.col)


def test_program_checks_run_in_every_parsing_mode(tmp_path: Path) -> None:
    files = {
        "Main.btrc": "import ./Config.btrc;\n#ifdef USE_FAST\n#endif\nint main() { return 0; }\n",
        "Config.btrc": "#define USE_FAST 1\n",
    }
    for output in (CompilerOutput.AST, CompilerOutput.IR, CompilerOutput.OPTIMIZED_IR, CompilerOutput.C):
        result = compile_files(tmp_path, files, output=output)
        assert result.failure is not None and result.failure.message.startswith("'USE_FAST' is defined"), output
    assert compile_files(tmp_path, files, output=CompilerOutput.TOKENS).successful


def test_whole_program_cache_keeps_the_program_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two variants compose identically; a warm compile of the one with C evidence still gives P3."""

    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    plain = {"Main.btrc": '#include "config.h"\n\n\nint main() { return 0; }\n', "config.h": "\n"}
    first = compile_files(tmp_path / "plain", plain, use_cache=True)
    assert first.successful, first.failure
    tested = {"Main.btrc": '#include "config.h"\n#ifdef HAVE_X\n#endif\nint main() { return 0; }\n', "config.h": "\n"}
    for _ in range(2):
        result = compile_files(tmp_path / "plain", tested, use_cache=True)
        assert result.failure is not None and "may come from C" in result.failure.message
        assert not result.cache_hit


# -- Macros, #undef emission and module units -------------------------------


def test_undef_is_emitted_in_hoisted_order(tmp_path: Path) -> None:
    source = "#define X 1\n#undef X\n#define X 2\nint main() { return 0; }\n"
    result = compile_files(tmp_path, {"Main.btrc": source})
    assert result.successful, result.failure
    directives = [line for line in result.c_source.splitlines() if line.startswith(("#define X", "#undef X"))]
    assert directives == ["#define X 1", "#undef X", "#define X 2"]


def test_module_units_carry_the_whole_directive_list_with_undefs(tmp_path: Path) -> None:
    files = {
        "Main.btrc": "import ./B.btrc;\n#define X 1\n#undef X\n#define X 2\nint main() { return b(); }\n",
        "B.btrc": "#undef X\nint b() { return 1; }\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    root = tmp_path / "Main.btrc"
    options = CompilerOptions(
        include_stdlib=False,
        use_cache=False,
        target="linux-x86_64",
        units_prefix=str(tmp_path / "out"),
        module_units=True,
    )
    result = Compiler().compile(root.read_text(), str(root), options)
    assert result.successful, result.failure
    whole = [line for line in result.c_source.splitlines() if line.startswith(("#define X", "#undef X"))]
    assert whole == ["#undef X", "#define X 1", "#undef X", "#define X 2"]
    for unit in result.c_units:
        assert [line for line in unit.splitlines() if line.startswith(("#define X", "#undef X"))] == whole


def test_testing_a_macro_after_undef_is_allowed(tmp_path: Path) -> None:
    source = (
        "#define F 1\n#undef F\n#ifdef F\nint f() { return 1; }\n#else\nint f() { return 0; }\n#endif\n"
        "int main() { return f(); }\n"
    )
    result = compile_files(tmp_path, {"Main.btrc": source})
    assert result.successful, result.failure
    assert "#undef F" in result.c_source


# -- The lowering invariant --------------------------------------------------


def _lower_directive(text: str) -> None:
    from src.compiler.python.ir.lowering.translation_unit import TranslationUnitLowerer

    lowerer = TranslationUnitLowerer.__new__(TranslationUnitLowerer)
    lowerer.lower_preprocessor(PreprocessorDirective(text=text, line=1, col=1))


@pytest.mark.parametrize("name", ["if", "ifdef", "ifndef", "elif", "else", "endif", "elifdef", "elifndef"])
def test_lowering_keeps_refusing_conditional_directives(name: str) -> None:
    with pytest.raises(CodegenError, match=re.escape(f"unsupported preprocessor directive '#{name}'")):
        _lower_directive(f"#{name} 1")


def test_lowering_refuses_live_directive_shapes() -> None:
    with pytest.raises(CodegenError, match=re.escape("only spaces and tabs may separate tokens")):
        _lower_directive("#define X\f1")
    with pytest.raises(CodegenError, match=re.escape("a comment in a preprocessor directive must close")):
        _lower_directive("#define X 1 /* open")
    with pytest.raises(CodegenError, match=re.escape("malformed #undef directive: #undef X Y")):
        _lower_directive("#undef X Y")


def test_runtime_override_hooks_are_the_runtime_header_ifndef_defaults() -> None:
    """A btrc source may #define these BTRC_ names, and only these: btrc_rt.h defaults each under #ifndef."""

    from src.compiler.python.frontend.sources import SourceMacroRules

    header = (REPO / "src" / "runtime" / "c" / "btrc_rt.h").read_text()
    hooks = set(re.findall(r"^#ifndef (BTRC_\w+)\n#define \1 \S", header, re.MULTILINE))
    assert hooks == set(SourceMacroRules.RUNTIME_OVERRIDES)
    for name in hooks:
        assert SourceMacroRules.violation(name, define=True) is None
        assert SourceMacroRules.violation(name, define=False) is not None


def test_the_verifier_skips_exactly_the_conditioning_candidates() -> None:
    """LexMain stays raw while --emit-tokens conditions, so the lexer-parity selection skips every candidate."""

    from tools.compiler_codegen.verification import CompilerBoundaryVerifier

    pattern = CompilerBoundaryVerifier._SOURCE_DEPENDENCY
    for source in (*FAST_PATH_SHAPES[:-2], "#ifdef X\n#endif\n", "  %:if 1\n"):
        assert pattern.search(source) is not None, source
    for path in sorted(TESTS.rglob("*.btrc")):
        text = path.read_text(encoding="utf-8")
        if SourceConditionals.candidate(text):
            assert pattern.search(text) is not None, path


# -- The self-hosted half (CL-C-06) ------------------------------------------
#
# btrcc must give every battery, directive and diagnostic row above exactly the
# reference's outcome, message and file-local line:col.

GRAMMAR = REPO / "src" / "language" / "grammar.ebnf"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
NATIVE_HEADER_READER = os.environ.get("BTRC_NATIVE_HEADER_READER")


@pytest.fixture(scope="module")
def conditional_driver(selfhost_driver) -> Path:
    """btrc's FeSourceConditionals, built once per btrcc fingerprint."""

    return selfhost_driver(FIXTURES / "ConditionalExpressionDriver.btrc", compile_flags=("-pedantic-errors",))


@pytest.fixture(scope="module")
def frontend_driver(selfhost_driver) -> Path:
    return selfhost_driver(REPO / "src" / "compiler" / "btrc" / "tools" / "FrontendMain.btrc")


def selfhost_condition(driver: Path, tmp_path: Path, source: str, *, no_target: bool = False) -> str:
    """btrc's conditioned text for linux-x86_64, or ``error LINE:COL MESSAGE``."""

    program = tmp_path / "Input.btrc"
    program.write_bytes(source.encode())
    result = subprocess.run(
        [str(driver), str(GRAMMAR), *(["--no-target"] if no_target else []), "--file", str(program)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.removesuffix("\n")


def reference_condition(source: str) -> str:
    try:
        return condition(source)
    except PreprocessorConditionalError as error:
        return f"error {error.line}:{error.col} {error.message}"


def test_selfhost_expression_battery(conditional_driver: Path) -> None:
    result = subprocess.run(
        [str(conditional_driver), str(GRAMMAR), str(BATTERY)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    outcomes = result.stdout.splitlines()
    assert len(outcomes) == len(EXPRESSION_CASES)
    for case, outcome in zip(EXPRESSION_CASES, outcomes, strict=True):
        assert outcome == case.expected, case.payload


SELFHOST_FILES = [
    *(source for source, _expected in DIRECTIVE_ERRORS),
    "int a;\n#if 0\nint b;\n#else\n  int c; // live\n#endif\nint d;",
    "#if 0\n#if garbage (\n#elif 1/0\nx\n#endif\n#elif 1\ny\n#endif\n",
    "#if 1\na\n#elif 1/0 garbage (\nb\n#endif\n",
    "/*\n#if FOO\n*/\nint a;\n#if 1\nint b;\n#endif\n",
    "#define L 10\n#define L  10 /* same */\n#define T 1\n#undef T\n#ifdef T\nx\n#else\ny\n#endif\n",
    *FAST_PATH_SHAPES,
    *C_SHAPES,
    SELECTION,
]


@pytest.mark.parametrize("source", SELFHOST_FILES)
def test_selfhost_conditions_each_file_as_the_reference(conditional_driver: Path, tmp_path: Path, source: str) -> None:
    assert selfhost_condition(conditional_driver, tmp_path, source) == reference_condition(source)


def test_selfhost_conditions_the_corpus_program_as_the_reference(conditional_driver: Path, tmp_path: Path) -> None:
    source = (TESTS / "c_compat" / "PreprocessorConditionals.btrc").read_text()
    assert selfhost_condition(conditional_driver, tmp_path, source) == reference_condition(source)


def test_selfhost_no_target_fails_only_at_the_first_evaluated_conditional(
    conditional_driver: Path, tmp_path: Path
) -> None:
    """D13 through the unit seam: btrcc on a host that is not a btrc target."""

    assert selfhost_condition(conditional_driver, tmp_path, "int a;\n", no_target=True) == "int a;\n"
    assert selfhost_condition(conditional_driver, tmp_path, "#define X 1\nint a;\n", no_target=True) == (
        "#define X 1\nint a;\n"
    )
    assert selfhost_condition(conditional_driver, tmp_path, "int a;\n  #ifdef X\n#endif\n", no_target=True) == (
        "error 2:3 preprocessor conditionals need a target; this host is not a btrc target, so pass --target OS-ARCH"
    )


def btrcc_run(btrcc: Path, arguments: list[str], cwd: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(btrcc), *arguments],
        cwd=cwd,
        env={**os.environ, "BTRC_HOME": str(REPO / "src"), **environment},
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("target", [f"{row.operating_system}-{row.architecture}" for row in TARGET_ROWS])
def test_selfhost_per_target_selection(
    target: str, frontend_driver: Path, immutable_btrcc: Path, tmp_path: Path
) -> None:
    root = tmp_path / "Main.btrc"
    root.write_text(SELECTION)
    reference = compile_files(tmp_path, {"Main.btrc": SELECTION}, target=target)
    assert reference.successful, reference.failure
    resolved = subprocess.run(
        [str(frontend_driver), "--no-stdlib", "--target", target, str(root)],
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == reference.source_bundle.source
    compiled = btrcc_run(immutable_btrcc, ["--no-stdlib", "--no-cache", "--target", target, str(root)], tmp_path)
    assert compiled.returncode == 0, compiled.stderr
    system, architecture = target.split("-")
    header, value = {"linux": ("stdio.h", "1"), "macos": ("stdlib.h", "2"), "windows": ("string.h", "3")}[system]
    for c_source in (compiled.stdout, reference.c_source):
        includes = {
            line
            for line in c_source.splitlines()
            if line in {f"#include <{name}>" for name in ("stdio.h", "stdlib.h", "string.h")}
        }
        assert f"#include <{header}>" in includes
        assert f"return {value};" in c_source
        assert all(f"return {other};" not in c_source for other in {"1", "2", "3"} - {value})
        assert ("return 64;" in c_source) == (architecture == "aarch64")
        assert ("return 46;" in c_source) == (architecture != "aarch64")
    reference_includes = {line for line in reference.c_source.splitlines() if line.startswith("#include")}
    selfhost_includes = {line for line in compiled.stdout.splitlines() if line.startswith("#include")}
    assert selfhost_includes == reference_includes


def test_selfhost_dead_import_adds_no_edge_source_or_plan_entry(immutable_btrcc: Path, tmp_path: Path) -> None:
    files = {
        "Main.btrc": "#if 0\nimport ./Missing.btrc;\nimport ./Conflict.btrc;\nimport ./helpers.c;\n#endif\n"
        "int value() { return 2; }\nint main() { return value(); }\n",
        "Conflict.btrc": "int value() { return 1; }\n",
        "helpers.c": "int helper(void) { return 1; }\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    root = tmp_path / "Main.btrc"
    selfhost = btrcc_run(
        immutable_btrcc,
        [
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x86_64",
            str(root),
            "-o",
            str(tmp_path / "selfhost.c"),
            "--emit-link-plan",
            str(tmp_path / "selfhost.json"),
        ],
        tmp_path,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    reference = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(root),
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x86_64",
            "-o",
            str(tmp_path / "reference.c"),
            "--emit-link-plan",
            str(tmp_path / "reference.json"),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert reference.returncode == 0, reference.stderr
    import json

    plans = [json.loads((tmp_path / f"{name}.json").read_text()) for name in ("selfhost", "reference")]
    # The link plan's native units and headers: no dead .c import is a unit.
    assert plans[0]["units"] == plans[1]["units"]
    assert plans[0]["headers"] == plans[1]["headers"]
    assert all("helpers.c" not in json.dumps(plan) for plan in plans)
    for name in ("selfhost", "reference"):
        c_source = (tmp_path / f"{name}.c").read_text()
        assert "helpers.c" not in c_source and "return 1;" not in c_source


_PLAIN = re.compile(r"^error: (?P<message>.*) at (?P<line>\d+):(?P<col>\d+)$", re.MULTILINE)


def selfhost_diagnostic(btrcc: Path, tmp_path: Path, files: dict[str, str]) -> tuple[str, str, int, int]:
    """btrcc's first error: rendered with its file, or a root-file parse error."""

    for name, text in files.items():
        (tmp_path / name).write_text(text)
    result = btrcc_run(
        btrcc,
        [
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x86_64",
            str(tmp_path / "Main.btrc"),
            "-o",
            str(tmp_path / "Main.c"),
        ],
        tmp_path,
    )
    assert result.returncode != 0, result.stderr
    match = _RENDERED.search(result.stderr)
    if match is not None:
        return match["message"], os.path.basename(match["path"]), int(match["line"]), int(match["col"])
    plain = _PLAIN.search(result.stderr)
    assert plain is not None, result.stderr
    # btrcc's parser reports root-file positions without a file name.
    return plain["message"], "Main.btrc", int(plain["line"]), int(plain["col"])


@pytest.mark.parametrize("case", DIAGNOSTIC_CASES, ids=lambda case: case.name)
def test_selfhost_diagnostics(case: DiagnosticCase, immutable_btrcc: Path, tmp_path: Path) -> None:
    assert selfhost_diagnostic(immutable_btrcc, tmp_path, case.files) == (case.message, case.file, case.line, case.col)


def test_selfhost_program_checks_run_in_every_emitting_mode(immutable_btrcc: Path, tmp_path: Path) -> None:
    files = {
        "Main.btrc": "import ./Config.btrc;\n#ifdef USE_FAST\n#endif\nint main() { return 0; }\n",
        "Config.btrc": "#define USE_FAST 1\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    for mode in ([], ["--emit-ir"], ["--emit-optimized-ir"]):
        result = btrcc_run(immutable_btrcc, ["--no-stdlib", "--no-cache", *mode, str(tmp_path / "Main.btrc")], tmp_path)
        assert result.returncode != 0 and "'USE_FAST' is defined in Config.btrc" in result.stderr, mode


def test_selfhost_undef_is_emitted_in_hoisted_order(immutable_btrcc: Path, tmp_path: Path) -> None:
    source = tmp_path / "Main.btrc"
    source.write_text("#define X 1\n#undef X\n#define X 2\nint main() { return 0; }\n")
    result = btrcc_run(immutable_btrcc, ["--no-stdlib", "--no-cache", str(source)], tmp_path)
    assert result.returncode == 0, result.stderr
    directives = [line for line in result.stdout.splitlines() if line.startswith(("#define X", "#undef X"))]
    assert directives == ["#define X 1", "#undef X", "#define X 2"]


def test_selfhost_module_units_carry_the_whole_directive_list_with_undefs(
    immutable_btrcc: Path, tmp_path: Path
) -> None:
    (tmp_path / "Main.btrc").write_text(
        "import ./B.btrc;\n#define X 1\n#undef X\n#define X 2\nint main() { return b(); }\n"
    )
    (tmp_path / "B.btrc").write_text("#undef X\nint b() { return 1; }\n")
    result = btrcc_run(
        immutable_btrcc,
        [
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x86_64",
            "Main.btrc",
            "-o",
            "out.c",
            "--emit-units",
            "out",
            "--module-units",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    whole = [
        line for line in (tmp_path / "out.c").read_text().splitlines() if line.startswith(("#define X", "#undef X"))
    ]
    assert whole == ["#undef X", "#define X 1", "#undef X", "#define X 2"]
    units = sorted(tmp_path.glob("out.unit-*.c"))
    assert units
    for unit in units:
        assert [line for line in unit.read_text().splitlines() if line.startswith(("#define X", "#undef X"))] == whole


@pytest.fixture(scope="module")
def lowering_driver(selfhost_driver) -> Path:
    return selfhost_driver(FIXTURES / "LoweringInvariantDriver.btrc")


def selfhost_lowering(driver: Path, tmp_path: Path, directive: str) -> subprocess.CompletedProcess[str]:
    program = tmp_path / "Main.btrc"
    program.write_text("int main() { return 0; }\n")
    return subprocess.run(
        [str(driver), str(GRAMMAR), str(REPO / "src" / "stdlib"), str(program), directive],
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


@pytest.mark.parametrize("name", ["if", "ifdef", "ifndef", "elif", "else", "endif", "elifdef", "elifndef"])
def test_selfhost_lowering_keeps_refusing_conditional_directives(
    lowering_driver: Path, tmp_path: Path, name: str
) -> None:
    result = selfhost_lowering(lowering_driver, tmp_path, f"#{name} 1")
    assert result.returncode != 0
    assert f"unsupported preprocessor directive '#{name}'" in result.stderr


def test_selfhost_lowering_refuses_live_directive_shapes(lowering_driver: Path, tmp_path: Path) -> None:
    for directive, message in (
        ("#define X\f1", "only spaces and tabs may separate tokens"),
        ("#define X 1 /* open", "a comment in a preprocessor directive must close"),
        ("#define X 1\n#undef X Y", "malformed #undef directive: #undef X Y"),
    ):
        result = selfhost_lowering(lowering_driver, tmp_path, directive)
        assert result.returncode != 0 and message in result.stderr, directive
    assert selfhost_lowering(lowering_driver, tmp_path, "#define X 1\n#undef X").stdout == "lowered\n"


# -- Caches in both compilers --------------------------------------------------

CACHE_FILES = {
    "Main.btrc": "import ./A.btrc;\nimport ./B.btrc;\nint main() { return a() + b(); }\n",
    "A.btrc": "#define TAG 2\n#if defined(__linux__)\nint a() { return 1; }\n#else\nint a() { return 5; }\n#endif\n",
    "B.btrc": "int b() { return 3; }\n",
}


class CacheWorkspace:
    """One program compiled with module units through both compilers' caches."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources = self.root / "src"
        self.sources.mkdir(parents=True)
        for name, text in CACHE_FILES.items():
            (self.sources / name).write_text(text)
        self.builds = 0

    def edit(self, name: str, old: str, new: str) -> None:
        path = self.sources / name
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, new))

    def reference(self, monkeypatch: pytest.MonkeyPatch, target: str, cache: str = "cache"):
        from src.compiler.python.artifacts.cache import CompilerCache

        monkeypatch.setenv("BTRC_CACHE_DIR", str(self.root / f"reference-{cache}"))
        # One output prefix for every build: the whole-program key covers it.
        output = self.root / "reference-out"
        output.mkdir(exist_ok=True)
        root = self.sources / "Main.btrc"
        result = Compiler(cache=CompilerCache()).compile(
            root.read_text(),
            str(root),
            CompilerOptions(
                include_stdlib=False,
                target=target,
                units_prefix=str(output / "program"),
                module_units=True,
                generated_c_path=str(output / "program.c"),
            ),
        )
        assert result.failure is None, result.failure
        lowered = {os.path.basename(path) for path in result.module_units_lowered}
        return result, lowered, (result.c_source, tuple(result.c_units))

    def selfhost(self, btrcc: Path, target: str, cache: str = "cache") -> tuple[dict[str, int], str, dict[str, int]]:
        self.builds += 1
        output = self.root / f"selfhost-{self.builds}"
        output.mkdir()
        result = btrcc_run(
            btrcc,
            [
                "--no-stdlib",
                "--target",
                target,
                "Main.btrc",
                "-o",
                str(output / "program.c"),
                "--emit-units",
                str(output / "program"),
                "--module-units",
            ],
            self.sources,
            BTRC_TIMING="1",
            BTRC_CACHE_DIR=str(self.root / f"selfhost-{cache}"),
        )
        assert result.returncode == 0, result.stderr
        counters = {
            name: int(value)
            for name, value in (
                item.split(":") for item in result.stderr.split("module-units=", 1)[1].split()[0].split(",")
            )
        }
        texts = [(output / "program.c").read_text()]
        texts.extend(path.read_text() for path in sorted(output.glob("program.unit-*.c")))
        records = re.search(r"a-records-stored\(replayed=(\d+),journaled=(\d+)\)", result.stderr)
        replay = {"replayed": int(records.group(1)), "journaled": int(records.group(2))} if records else {}
        return counters, "\n".join(texts), replay


ALL_GROUPS = {"Main.btrc", "A.btrc", "B.btrc"}


def test_reference_caches_follow_conditioned_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = CacheWorkspace(tmp_path)
    _cold, lowered, linux = workspace.reference(monkeypatch, "linux-x86_64")
    assert lowered == ALL_GROUPS
    # A target switch misses the whole-program cache; warm equals cold.
    switched, _lowered, windows = workspace.reference(monkeypatch, "windows-x86_64")
    assert not switched.cache_hit
    _fresh, _lowered, windows_cold = workspace.reference(monkeypatch, "windows-x86_64", cache="fresh")
    assert windows == windows_cold
    assert workspace.reference(monkeypatch, "linux-x86_64")[2] == linux
    # A live line inside a conditional group re-lowers exactly that group.
    workspace.edit("A.btrc", "return 1;", "return 7;")
    assert workspace.reference(monkeypatch, "linux-x86_64")[1] == {"A.btrc"}
    # A live directive is part of the program interface: every group re-lowers.
    workspace.edit("A.btrc", "#define TAG 2", "#define TAG 3")
    assert workspace.reference(monkeypatch, "linux-x86_64")[1] == ALL_GROUPS
    # An edit confined to a dead group is a whole-program hit.
    _warm, _lowered, before = workspace.reference(monkeypatch, "linux-x86_64")
    workspace.edit("A.btrc", "return 5;", "return 9;")
    dead, lowered, after = workspace.reference(monkeypatch, "linux-x86_64")
    assert dead.cache_hit and not lowered and after == before
    # With a live edit in another group, exactly that group re-lowers.
    workspace.edit("A.btrc", "return 9;", "return 11;")
    workspace.edit("B.btrc", "return 3;", "return 4;")
    assert workspace.reference(monkeypatch, "linux-x86_64")[1] == {"B.btrc"}


@pytest.mark.skipif(
    not NATIVE_HEADER_READER, reason="self-hosted artifact reuse needs the native header reader identity"
)
def test_selfhost_caches_follow_conditioned_text(immutable_btrcc: Path, tmp_path: Path) -> None:
    workspace = CacheWorkspace(tmp_path)
    counters, linux, _replay = workspace.selfhost(immutable_btrcc, "linux-x86_64")
    assert counters == {"lowered": 3, "reused": 0}
    # Warm across a target switch equals cold.
    _counters, windows, _replay = workspace.selfhost(immutable_btrcc, "windows-x86_64")
    _counters, windows_cold, _replay = workspace.selfhost(immutable_btrcc, "windows-x86_64", cache="fresh")
    assert windows == windows_cold
    assert workspace.selfhost(immutable_btrcc, "linux-x86_64")[1] == linux
    # A live line inside a conditional group re-lowers exactly that group.
    workspace.edit("A.btrc", "return 1;", "return 7;")
    assert workspace.selfhost(immutable_btrcc, "linux-x86_64")[0] == {"lowered": 1, "reused": 2}
    # A live directive edit re-lowers every group.
    workspace.edit("A.btrc", "#define TAG 2", "#define TAG 3")
    assert workspace.selfhost(immutable_btrcc, "linux-x86_64")[0] == {"lowered": 3, "reused": 0}
    # A dead-group edit misses the artifact (raw content) but reuses every
    # unit and replays every validation record; the C is byte-identical.
    _counters, before, _replay = workspace.selfhost(immutable_btrcc, "linux-x86_64")
    workspace.edit("A.btrc", "return 5;", "return 9;")
    counters, after, replay = workspace.selfhost(immutable_btrcc, "linux-x86_64")
    assert counters == {"lowered": 0, "reused": 3}
    assert after == before
    assert replay.get("journaled") == 0 and replay.get("replayed", 0) > 0
    # With a live edit in another group, exactly that group re-lowers.
    workspace.edit("A.btrc", "return 9;", "return 11;")
    workspace.edit("B.btrc", "return 3;", "return 4;")
    assert workspace.selfhost(immutable_btrcc, "linux-x86_64")[0] == {"lowered": 1, "reused": 2}


def test_selfhost_warm_compile_keeps_the_program_checks(immutable_btrcc: Path, tmp_path: Path) -> None:
    """Two variants compose identically; a warm compile of the one with C evidence still gives P3."""

    cache = str(tmp_path / "cache")
    (tmp_path / "config.h").write_text("\n")
    root = tmp_path / "Main.btrc"
    arguments = ["--no-stdlib", "--target", "linux-x86_64", str(root), "-o", str(tmp_path / "Main.c")]
    root.write_text('#include "config.h"\n\n\nint main() { return 0; }\n')
    first = btrcc_run(immutable_btrcc, arguments, tmp_path, BTRC_CACHE_DIR=cache)
    assert first.returncode == 0, first.stderr
    root.write_text('#include "config.h"\n#ifdef HAVE_X\n#endif\nint main() { return 0; }\n')
    for _ in range(2):
        result = btrcc_run(immutable_btrcc, arguments, tmp_path, BTRC_CACHE_DIR=cache)
        assert result.returncode != 0 and "may come from C that btrc does not read" in result.stderr


# -- The stdlib conditions for every target ------------------------------------


def test_the_generated_source_check_conditions_every_stdlib_module(tmp_path: Path) -> None:
    """The generated-source check requires every stdlib module to condition for
    every target, hold no #undef and record no test of an absent name."""

    from tools.compiler_codegen.stdlib_symbols import StdlibSymbolIndexGenerator

    StdlibSymbolIndexGenerator(REPO).verify_conditions()
    stdlib = tmp_path / "src" / "stdlib"
    stdlib.mkdir(parents=True)
    for text, message in (
        ("#define X 1\n#undef X\n", "may not #undef"),
        ("#if 1\n", "'#if' without '#endif'"),
        ("#ifdef HAVE_X\n#endif\n", "tests absent name 'HAVE_X'"),
    ):
        (stdlib / "Module.btrc").write_text(text)
        with pytest.raises(ValueError, match=re.escape(message)):
            StdlibSymbolIndexGenerator(tmp_path, TargetManifest.load_repository(REPO)).verify_conditions()


# -- P2 and P3's binding evidence: the native reader ---------------------------

NATIVE_BINDING = (
    'manifest-version = 1\n\n[package]\nname = "bindings"\n'
    '\n[[native.bindings]]\nmodule = "Api"\nheader = "Native.h"\n'
    'language = "c"\nstandard = "c11"\nsymbols = ["measure"]\n'
)


def native_case(tmp_path: Path, main: str, api: str) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "btrc.toml").write_text(NATIVE_BINDING)
    (tmp_path / "Native.h").write_text("long measure(const char *text);\n")
    (tmp_path / "src" / "Api.btrc").write_text(api)
    root = tmp_path / "src" / "Main.btrc"
    root.write_text(main)
    return root


NATIVE_CASES = [
    pytest.param(
        "import ./Api.btrc;\n#ifdef measure\n#endif\nint main() { return 0; }\n",
        "// Native wrapper module.\n",
        (
            "'measure' comes from a native header; #if is evaluated before C compilation and cannot test it",
            "Main.btrc",
            2,
            8,
        ),
        id="P2",
    ),
    pytest.param(
        "import ./Api.btrc;\nint main() { return 0; }\n",
        "// Native wrapper module.\n#ifndef HAVE_MEASURE\n#endif\n",
        (
            "'HAVE_MEASURE' may come from C that btrc does not read (native header Native.h for Api.btrc); "
            "#if is evaluated before C compilation and cannot test it",
            "Api.btrc",
            2,
            9,
        ),
        id="P3-binding",
    ),
]


@pytest.mark.skipif(not NATIVE_HEADER_READER, reason="native bindings need the native header reader")
@pytest.mark.parametrize(("main", "api", "expected"), NATIVE_CASES)
def test_native_program_checks_in_both_compilers(
    main: str, api: str, expected: tuple[str, str, int, int], immutable_btrcc: Path, tmp_path: Path
) -> None:
    root = native_case(tmp_path, main, api)
    arguments = ["--no-stdlib", "--no-cache", "--target", "linux-x86_64", str(root), "-o", str(tmp_path / "Main.c")]
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", *arguments],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    selfhost = btrcc_run(immutable_btrcc, arguments, tmp_path)
    for result in (reference, selfhost):
        assert result.returncode != 0
        match = _RENDERED.search(result.stderr)
        assert match is not None, result.stderr
        found = (match["message"], os.path.basename(match["path"]), int(match["line"]), int(match["col"]))
        assert found == expected
