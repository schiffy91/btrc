"""The target predefined-macro table (src/language/targets.toml) against C compilers.

``#if`` evaluates a target macro from the table before C compilation, so the
table must say exactly what the C compiler of that target will define
(docs/design/c-preprocessor-conditionals.md, test 3). For each spec target,
clang's ``-dM`` dump must define exactly the table names and undefined names
the table selects, with the table's values; the host's gcc must agree on its
own target. The names left out on purpose must stay out of the table.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import (
    TARGET_PREDEFINED_MACRO_ROWS,
    TARGET_ROWS,
    TARGET_UNDEFINED_MACRO_NAMES,
)
from src.compiler.python.frontend.packages import PackageTarget
from src.tests.c_toolchains import HOST_CLANG, HOST_GCC
from src.tests.process_limits import C_COMPILE_TIMEOUT

# clang's spelling of each target. They live here until PLAN.md Stage 24 moves
# triples into targets.toml; Windows is the MinGW environment, because
# x86_64-pc-windows-msvc does not define __STDC__.
TRIPLES = {
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
    "macos-x86_64": "x86_64-apple-macosx14.0.0",
    "macos-aarch64": "arm64-apple-macosx14.0.0",
    "windows-x86_64": "x86_64-w64-windows-gnu",
    "windows-aarch64": "aarch64-w64-windows-gnu",
}

# Left out on purpose (c-preprocessor-conditionals.md, "Left out on purpose"):
# toolchain or invocation identity, the data model, and a size MinGW and MSVC
# disagree on. #if refuses each one as reserved until a later stage adds it.
LEFT_OUT = (
    "__GNUC__",
    "__MINGW32__",
    "__MINGW64__",
    "__OPTIMIZE__",
    "__SIZEOF_LONG_DOUBLE__",
    "__SIZEOF_LONG__",
    "__SIZEOF_WCHAR_T__",
    "__STDC_HOSTED__",
    "__clang__",
    "__gnu_linux__",
    "_LP64",
    "__LP64__",
)

_DEFINE = re.compile(r"#define ([A-Za-z_][A-Za-z0-9_]*) (.*)\Z")
_INTEGER = re.compile(r"([0-9]+)[uUlL]*\Z")


def _label(row) -> str:
    return f"{row.operating_system}-{row.architecture}"


def _unwrapped_clang() -> str | None:
    """The clang binary itself, not nix's cc-wrapper.

    The wrapper adds host flags and warns on every foreign --target; its
    nix-support/orig-cc names the store path of the clang it wraps.
    """

    if HOST_CLANG is None:
        return None
    original = Path(HOST_CLANG).resolve().parent.parent / "nix-support" / "orig-cc"
    if original.is_file():
        candidate = Path(original.read_text().strip()) / "bin" / "clang"
        if candidate.is_file():
            return str(candidate)
    return HOST_CLANG


def _predefines(command: list[str]) -> dict[str, int | None]:
    """Every macro the compiler predefines, with its integer value (None when not an integer).

    An object-like alias (``__BYTE_ORDER__`` is ``__ORDER_LITTLE_ENDIAN__``)
    resolves through the dump, and integer suffixes are stripped.
    """

    completed = subprocess.run(
        [*command, "-std=c11", "-dM", "-E", "-x", "c", "-"],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
    replacements = {}
    for line in completed.stdout.splitlines():
        match = _DEFINE.match(line)
        if match is not None:
            replacements[match.group(1)] = match.group(2).strip()

    def resolve(name: str, depth: int = 0) -> int | None:
        replacement = replacements[name]
        integer = _INTEGER.match(replacement)
        if integer is not None:
            return int(integer.group(1))
        if depth < 8 and replacement in replacements:
            return resolve(replacement, depth + 1)
        return None

    return {name: resolve(name) for name in replacements}


def _selected(label: str) -> dict[str, int]:
    operating_system, architecture = label.split("-", 1)
    return {
        row.name: row.value
        for row in TARGET_PREDEFINED_MACRO_ROWS
        if (not row.operating_systems or operating_system in row.operating_systems)
        and (not row.architectures or architecture in row.architectures)
    }


def _checked_names() -> set[str]:
    return {row.name for row in TARGET_PREDEFINED_MACRO_ROWS} | set(TARGET_UNDEFINED_MACRO_NAMES)


def _assert_agrees(label: str, predefined: dict[str, int | None]) -> None:
    expected = _selected(label)
    defined = {name: predefined[name] for name in _checked_names() if name in predefined}
    assert defined == expected, f"{label}: compiler {defined!r} != table {expected!r}"


def test_every_spec_target_has_a_clang_triple() -> None:
    assert set(TRIPLES) == {_label(row) for row in TARGET_ROWS}
    assert len(TRIPLES) == 6


def test_left_out_names_stay_out_of_the_table() -> None:
    assert not set(LEFT_OUT) & _checked_names()


@pytest.mark.parametrize("label", tuple(TRIPLES))
def test_clang_defines_exactly_the_selected_table_rows(label: str) -> None:
    clang = _unwrapped_clang()
    if clang is None:
        pytest.skip("requires clang to dump each target's predefined macros")
    _assert_agrees(label, _predefines([clang, f"--target={TRIPLES[label]}"]))


def test_host_gcc_agrees_on_its_own_target() -> None:
    if HOST_GCC is None:
        pytest.skip("requires the host gcc to dump its predefined macros")
    host = PackageTarget.parse(None)
    _assert_agrees(f"{host.operating_system}-{host.architecture}", _predefines([HOST_GCC]))
