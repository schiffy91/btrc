"""Object-like SDK macros selected as binding symbols import as typed constants.

The header reader evaluates an object-like macro's replacement tokens through
Clang's Sema, so a macro constant carries the exact C type and value the SDK
gives it, and btrc code names it directly instead of through a handwritten
re-spelling in a wrapper header (FreeType's FT_LOAD_* flags, for example).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.native_imports import NativeHeaderCodec
from src.tests.process_limits import RUN_TIMEOUT, TOOL_TIMEOUT, TRANSPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]
MACROS = """#include <stdint.h>
enum Color { RED = 3 };
#define FLAG_A 0x00000020
#define SHIFTED ( 1L << 2 )
#define WIDE UINT32_MAX
#define CAST ((uint16_t)0xFFFF)
#define NEG (-5)
#define FOURCC 'dev#'
#define FROM_ENUM (RED + 1)
#define CHOSEN (1 ? 7u : 8u)
#define STRING "uid"
#define FUNCTION_LIKE(x) ((x) + 1)
#define USES_FUNCTION FUNCTION_LIKE(2)
#define U32C(x) x##U
#define WIDE_VIA U32C(4294967295)
#define BARE_FUNCTION FUNCTION_LIKE
#define UNTERMINATED FUNCTION_LIKE(1
"""
PROGRAM = """#include <assert.h>
int main() {
\tassert(FLAG_A == 32);
\tassert(SHIFTED == 4L);
\tassert(WIDE == 4294967295U);
\tassert(CAST == 65535);
\tassert(NEG == -5);
\tassert(FROM_ENUM == 4);
\tassert(FT_LOAD_DEFAULT == 0);
\tassert(FT_LOAD_RENDER == 4);
\tFT_Library library = null;
\tassert(FT_Init_FreeType(&library) == 0);
\tassert(FT_Done_FreeType(library) == 0);
\tprintf("PASS: native macro constants\\n");
\treturn 0;
}
"""
MANIFEST = """manifest-version = 1
[package]
name = "macroConstants"

[[native.bindings]]
module = "Main"
header = "Macros.h"
language = "c"
standard = "c11"
symbols = ["FLAG_A", "SHIFTED", "WIDE", "CAST", "NEG", "FROM_ENUM"]

[[native.bindings]]
module = "Main"
header = "FreeType.h"
language = "c"
standard = "c11"
symbols = ["FT_Library", "FT_Init_FreeType", "FT_Done_FreeType", "FT_LOAD_DEFAULT", "FT_LOAD_RENDER"]

[[native.pkg-config]]
name = "freetype2"
modules = ["Main"]

[[native.include-directories]]
path = "."
"""


@pytest.fixture(scope="module")
def reader() -> str:
    executable = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not executable:
        pytest.skip("requires the explicitly built native header reader")
    return executable


def _read(reader: str, tmp_path: Path, symbol: str) -> subprocess.CompletedProcess[str]:
    header = tmp_path / "Macros.h"
    header.write_text(MACROS, encoding="utf-8")
    return subprocess.run(
        [reader, f"--symbol={symbol}", str(header), "--", "-x", "c", "-std=c11"],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )


def _type_name(value: dict) -> str:
    return value["name"]


@pytest.mark.parametrize(
    ("symbol", "type_name", "value"),
    [
        ("FLAG_A", "int", "32"),
        ("SHIFTED", "long", "4"),
        ("WIDE", "unsigned int", "4294967295"),
        ("CAST", "uint16_t", "65535"),
        ("NEG", "int", "-5"),
        ("FOURCC", "int", "1684370979"),
        ("FROM_ENUM", "int", "4"),
        ("CHOSEN", "unsigned int", "7"),
        ("WIDE_VIA", "unsigned int", "4294967295"),
        ("USES_FUNCTION", "int", "3"),
    ],
)
def test_integer_macro_imports_with_its_c_type(reader, tmp_path, symbol, type_name, value) -> None:
    result = _read(reader, tmp_path, symbol)

    assert result.returncode == 0, result.stderr
    NativeHeaderCodec().decode(result.stdout)
    declaration = json.loads(result.stdout)["declarations"][0]
    assert declaration["name"] == symbol
    assert declaration["kind"] == "enum_constant"
    assert declaration["value"] == value
    assert _type_name(declaration["type"]) == type_name
    assert declaration["source"].endswith("Macros.h")


@pytest.mark.parametrize(
    ("symbol", "reason"),
    [
        ("STRING", "uses unsupported token string_literal"),
        ("FUNCTION_LIKE", "is a function-like macro"),
        ("BARE_FUNCTION", "names FUNCTION_LIKE, which is not an enumerator"),
        ("UNTERMINATED", "expands to no tokens"),
    ],
)
def test_non_integer_macros_refuse(reader, tmp_path, symbol, reason) -> None:
    result = _read(reader, tmp_path, symbol)

    assert result.returncode != 0
    assert f"Native macro {symbol} {reason}" in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="the FreeType proof builds against the Linux SDK")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_freetype_macro_constants_build_and_run(reader, tmp_path, request, frontend) -> None:
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "freetype2"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional FreeType SDK through pkg-config")
    shutil.copyfile(REPO / "src/stdlib/GUI/FreeType/FreeType.h", tmp_path / "FreeType.h")
    (tmp_path / "Macros.h").write_text(MACROS, encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    source = tmp_path / "Main.btrc"
    source.write_text(PROGRAM, encoding="utf-8")
    generated = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    flags = ["--no-cache", "--target", "linux-x64", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", *flags, "-o", str(generated)]
        if frontend == "python"
        else [request.getfixturevalue("btrcc_bin"), *flags]
    )
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout, encoding="utf-8")
    assert "BTRC_FT_" not in generated.read_text(encoding="utf-8")
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: native macro constants\n"
