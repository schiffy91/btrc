"""Object-like SDK macros selected as binding symbols import as typed constants.

The header reader evaluates an object-like macro's replacement tokens through
Clang's Sema, so a macro constant carries the exact C type and value the SDK
gives it, and btrc code names it directly instead of through a handwritten
re-spelling in a wrapper header (FreeType's FT_LOAD_* flags, WebGPU's
WGPU_DEPTH_SLICE_UNDEFINED and CoreAudio's string keys, for example). Integer
macros import as `enum_constant` records, ordinary string-literal macros as
`string_constant` records typed `const char*`, and numeric pointer sentinels as
`pointer_constant` records with their target type and width. Pointer uses retain
the SDK macro name; they never acquire addressable storage.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.native_generated import NativePointerConstant
from src.compiler.python.artifacts.archive import TargetCatalog
from src.compiler.python.frontend.native_imports import NativeHeaderCodec
from src.tests.c_toolchains import default_c_compiler, default_cxx_compiler
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
#define PAREN_STRING ("drift")
#define JOINED "ab" "cd"
#define NESTED_STRING STRING
#define EMPTY_STRING ""
#define WIDE_STRING L"w"
#define NUL_STRING "a\\0b"
#define STRING_ARITH ("x" + 1)
#define FUNCTION_LIKE(x) ((x) + 1)
#define USES_FUNCTION FUNCTION_LIKE(2)
#define U32C(x) x##U
#define WIDE_VIA U32C(4294967295)
#define BARE_FUNCTION FUNCTION_LIKE
#define UNTERMINATED FUNCTION_LIKE(1
#define UNSELECTED 99
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
    ("symbol", "value"),
    [("STRING", "uid"), ("PAREN_STRING", "drift"), ("JOINED", "abcd"), ("NESTED_STRING", "uid"), ("EMPTY_STRING", "")],
)
def test_string_macro_imports_as_a_const_char_pointer(reader, tmp_path, symbol, value) -> None:
    result = _read(reader, tmp_path, symbol)

    assert result.returncode == 0, result.stderr
    NativeHeaderCodec().decode(result.stdout)
    declaration = json.loads(result.stdout)["declarations"][0]
    assert declaration["name"] == symbol
    assert declaration["kind"] == "string_constant"
    assert declaration["value"] == value
    assert declaration["type"]["kind"] == "pointer"
    assert not declaration["type"]["const"]
    assert declaration["type"]["pointee"]["name"] == "char"
    assert declaration["type"]["pointee"]["const"]


def test_unselected_macro_is_not_exported(reader, tmp_path) -> None:
    result = _read(reader, tmp_path, "STRING")

    assert result.returncode == 0, result.stderr
    assert [declaration["name"] for declaration in json.loads(result.stdout)["declarations"]] == ["STRING"]


@pytest.mark.parametrize(
    ("symbol", "reason"),
    [
        ("WIDE_STRING", "is not an ordinary string literal"),
        ("NUL_STRING", "is a string literal with an embedded NUL"),
        ("STRING_ARITH", "is not an integer or string constant"),
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


STRING_PROGRAM = """int main() {
\tconst char* key = STRING;
\tvar shifted = SHIFTED;
\tprintf("%s %s %s %s [%s] %ld %d\\n", key, PAREN_STRING, JOINED, NESTED_STRING, EMPTY_STRING, shifted, NEG);
\treturn 0;
}
"""
STRING_MANIFEST = """manifest-version = 1
[package]
name = "macroStrings"

[[native.bindings]]
module = "Main"
header = "Macros.h"
language = "c"
standard = "c11"
symbols = [{symbols}]

[[native.include-directories]]
path = "."
"""
SELECTED = ["STRING", "PAREN_STRING", "JOINED", "NESTED_STRING", "EMPTY_STRING", "SHIFTED", "NEG"]


def _compile(tmp_path: Path, request, frontend: str, program: str, symbols: list[str]) -> tuple:
    (tmp_path / "Macros.h").write_text(MACROS, encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(
        STRING_MANIFEST.format(symbols=", ".join(f'"{symbol}"' for symbol in symbols)), encoding="utf-8"
    )
    source = tmp_path / "Main.btrc"
    source.write_text(program, encoding="utf-8")
    generated = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    flags = ["--no-cache", "--target", "linux-x64", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", *flags, "-o", str(generated)]
        if frontend == "python"
        else [request.getfixturevalue("btrcc_bin"), *flags]
    )
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT)
    if frontend == "selfhost" and compiled.returncode == 0:
        generated.write_text(compiled.stdout, encoding="utf-8")
    return compiled, generated, plan


@pytest.mark.skipif(sys.platform != "linux", reason="the macro proof builds against the Linux C toolchain")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_string_and_integer_macro_constants_build_and_run(reader, tmp_path, request, frontend) -> None:
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    compiled, generated, plan = _compile(tmp_path, request, frontend, STRING_PROGRAM, SELECTED)
    assert compiled.returncode == 0, compiled.stderr
    text = generated.read_text(encoding="utf-8")
    assert '"uid"' not in text and "const char* key = STRING;" in text
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "uid drift abcd uid [] 4 -5\n"


@pytest.mark.skipif(sys.platform != "linux", reason="the macro proof builds against the Linux C toolchain")
@pytest.mark.parametrize(
    ("statement", "symbols", "diagnostic"),
    [
        ("var unselected = UNSELECTED;", SELECTED, "error: Unresolved identifier 'UNSELECTED' used as a value"),
        ('STRING = "other";', SELECTED, "error: Cannot modify read-only native global"),
        (
            "const char** slot = &STRING;",
            SELECTED,
            "error: Addressing a read-only native pointer slot requires qualified-pointer lowering",
        ),
        ("int number = JOINED;", SELECTED, "error: Cannot assign 'const char*' to variable 'number' of type 'int'"),
        ("int number = 0;", [*SELECTED, "FUNCTION_LIKE"], "Native macro FUNCTION_LIKE is a function-like macro"),
        ("int number = 0;", [*SELECTED, "WIDE_STRING"], "Native macro WIDE_STRING is not an ordinary string literal"),
    ],
)
def test_macro_constant_diagnostics_match_across_compilers(reader, tmp_path, request, statement, symbols, diagnostic):
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    program = f"int main() {{\n\t{statement}\n\treturn 0;\n}}\n"
    reports = []
    for frontend in ("python", "selfhost"):
        directory = tmp_path / frontend
        directory.mkdir()
        compiled, _, _ = _compile(directory, request, frontend, program, symbols)
        assert compiled.returncode != 0, frontend
        lines = [line for line in compiled.stderr.splitlines() if diagnostic in line]
        assert lines, (frontend, compiled.stderr)
        # Each compiler frames a diagnostic its own way (a trailing `at line:col`,
        # an exception prefix for header-reader failures); the message must match.
        reports.append(re.sub(r" at \d+:\d+$", "", lines[0][lines[0].index(diagnostic) :]))
    assert reports[0] == reports[1]


WEBGPU_PROGRAM = """import Library.GPU.GPUSurfaceRenderer;

void frame(GPUSurfaceRenderer renderer) {
\trenderer.beginFrame(0.0, 0.0, 0.0);
}

int main(int argc, char** argv) {
\tGPUSurfaceRenderer? renderer = null;
\tif (argc > 100 && renderer != null) { frame(renderer); }
\tprintf("%u\\n", WGPU_DEPTH_SLICE_UNDEFINED);
\treturn 0;
}
"""


@pytest.mark.skipif(sys.platform != "linux", reason="the WebGPU proof builds against the Linux SDK")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_webgpu_binding_names_the_sdk_depth_slice_macro(reader, tmp_path, request, frontend) -> None:
    """The stdlib GPU binding selects WGPU_DEPTH_SLICE_UNDEFINED with no wrapper re-spelling."""
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "wgpu-native"], timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional wgpu-native SDK through pkg-config")
    assert "WGPU_DEPTH_SLICE_UNDEFINED" not in (REPO / "src/stdlib/GPU/WebGPUImports.h").read_text(encoding="utf-8")
    source = tmp_path / "Main.btrc"
    source.write_text(WEBGPU_PROGRAM, encoding="utf-8")
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
    assert re.search(r"color\.depthSlice\b.*= WGPU_DEPTH_SLICE_UNDEFINED\)", generated.read_text(encoding="utf-8"))
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "4294967295\n"


SHARED = """#define SHARED_FLAG 0x20
#define SHARED_WIDE (1UL << 40)
"""
CXX_VALUES = """#include "Shared.h"
namespace demo { enum class Mode : long { off = -3, on = 4 }; }
"""
CXX_MANIFEST = """manifest-version = 1
[package]
name = "foldedConstants"

[[native.bindings]]
module = "Main"
header = "Values.hpp"
language = "c++"
standard = "c++17"
symbols = ["SHARED_FLAG", "SHARED_WIDE", "demo::Mode::off", "demo::Mode::on"]

[[native.include-directories]]
path = "."
"""
CXX_PROGRAM = """#include "Shared.h"
int main() {
\tunsigned long wide = SHARED_WIDE;
\tlong mode = demo_Mode_off;
\tprintf("%d %lu %ld %ld\\n", SHARED_FLAG, wide, mode, (long)demo_Mode_on);
\treturn 0;
}
"""


def _compile_cxx_constants(tmp_path: Path, request, frontend: str, program: str) -> tuple:
    (tmp_path / "Shared.h").write_text(SHARED, encoding="utf-8")
    (tmp_path / "Values.hpp").write_text(CXX_VALUES, encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(CXX_MANIFEST, encoding="utf-8")
    source = tmp_path / "Main.btrc"
    source.write_text(program, encoding="utf-8")
    generated = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    flags = ["--no-cache", "--target", "linux-x64", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", *flags, "-o", str(generated)]
        if frontend == "python"
        else [request.getfixturevalue("btrcc_bin"), *flags]
    )
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT)
    if frontend == "selfhost" and compiled.returncode == 0:
        generated.write_text(compiled.stdout, encoding="utf-8")
    return compiled, generated, plan


@pytest.mark.skipif(sys.platform != "linux", reason="the macro proof builds against the Linux C toolchain")
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_foreign_binding_constants_fold_beside_a_visible_macro(reader, tmp_path, request, frontend) -> None:
    """A C++ (or Objective-C) binding's C unit never declares a constant under its SDK name.

    That unit does not include the binding's header, but it may see a macro of
    the same name through another header, as AppKit's C unit sees IOLLEvent.h's
    NX_DEVICE*KEYMASK through CoreGraphics. A `static const int SHARED_FLAG = 32;`
    expands the macro inside its own declaration, so references fold to the
    value cast to the projected type instead.
    """
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    compiled, generated, plan = _compile_cxx_constants(tmp_path, request, frontend, CXX_PROGRAM)
    assert compiled.returncode == 0, compiled.stderr
    text = generated.read_text(encoding="utf-8")
    for name in ("SHARED_FLAG", "SHARED_WIDE", "demo_Mode_off", "demo_Mode_on"):
        assert not re.search(rf"\b{name}\s*=", text), name
    assert "unsigned long wide = ((unsigned long)1099511627776U);" in text
    assert "long mode = ((long)-3);" in text
    assert '"%d %lu %ld %ld\\n", ((int)32), wide, mode, ((long)((long)4))' in text
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "32 1099511627776 -3 4\n"


@pytest.mark.skipif(sys.platform != "linux", reason="the macro proof builds against the Linux C toolchain")
@pytest.mark.parametrize(
    ("language", "statement", "name"),
    [
        ("c", "const long* slot = &SHIFTED;", "SHIFTED"),
        ("c++", "const int* slot = &SHARED_FLAG;", "SHARED_FLAG"),
        ("c++", "const long* slot = &demo_Mode_on;", "demo_Mode_on"),
    ],
)
def test_native_constant_address_is_refused_identically(reader, tmp_path, request, language, statement, name):
    """An imported enumerator or integer macro is a value: neither compiler gives it an address."""
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    program = f"int main() {{\n\t{statement}\n\treturn 0;\n}}\n"
    diagnostic = f"error: Native constant '{name}' is a value and has no address"
    reports = []
    for frontend in ("python", "selfhost"):
        directory = tmp_path / frontend
        directory.mkdir()
        compiled, _, _ = (
            _compile(directory, request, frontend, program, SELECTED)
            if language == "c"
            else _compile_cxx_constants(directory, request, frontend, program)
        )
        assert compiled.returncode != 0, frontend
        lines = [line for line in compiled.stderr.splitlines() if diagnostic in line]
        assert lines, (frontend, compiled.stderr)
        reports.append(re.sub(r" at \d+:\d+$", "", lines[0][lines[0].index(diagnostic) :]))
    assert reports[0] == reports[1]


POINTER_MACROS = """#pragma once
typedef void* SentinelHandle;
typedef const unsigned char* ReadOnlyBytes;
#define PTR_NULL ((void*)0)
#define PTR_ALL ((SentinelHandle)(__INTPTR_TYPE__)-1)
#define PTR_CAST ((int*)(__UINTPTR_TYPE__)16)
#define PTR_CONST ((ReadOnlyBytes)(__UINTPTR_TYPE__)32)
#define PTR_ALIAS PTR_ALL
#define PTR_TRUNCATED ((void*)(__UINTPTR_TYPE__)0x100000001ULL)
#define PTR_SIGNED ((void*)(__INTPTR_TYPE__)-2)
extern int pointerObject;
extern int pointerCounter;
extern void* pointerRuntime;
extern void* pointerFactory(void);
extern void pointerFunction(void);
#define PTR_OBJECT ((void*)&pointerObject)
#define PTR_OBJECT_OFFSET ((void*)(&pointerObject + 1))
#define PTR_NULL_ARITH ((char*)0 + 1)
#define PTR_RUNTIME pointerRuntime
#define PTR_CALL pointerFactory()
#define PTR_EFFECT ((++pointerCounter), (void*)0)
#define PTR_FUNCTION (&pointerFunction)
#define PTR_STRING ((const char*)"sentinel")
#define PTR_STRING_OFFSET ((const char*)"sentinel" + 1)
#define PTR_ADDRESS_SPACE ((void __attribute__((address_space(1)))*)0)
static inline int pointerMatchesSdk(void* zero, SentinelHandle all, int* castValue,
                                   ReadOnlyBytes readOnly, void* alias, void* truncated) {
    return zero == PTR_NULL && all == PTR_ALL && castValue == PTR_CAST &&
           readOnly == PTR_CONST && alias == PTR_ALIAS && truncated == PTR_TRUNCATED;
}
"""
POINTER_SYMBOLS = ["PTR_NULL", "PTR_ALL", "PTR_CAST", "PTR_CONST", "PTR_ALIAS", "PTR_TRUNCATED"]
POINTER_REJECTED_TYPES = """typedef void (*PointerCallback)(void);
typedef void __attribute__((address_space(1)))* AddressSpacePointer;
#define PTR_FUNCTION_NULL ((PointerCallback)0)
#define PTR_ADDRESS_SPACE_ALIAS ((AddressSpacePointer)0)
"""


def _read_pointer(reader: str, tmp_path: Path, symbol: str, triple: str) -> subprocess.CompletedProcess[str]:
    header = tmp_path / "Pointers.h"
    header.write_text(POINTER_MACROS + POINTER_REJECTED_TYPES, encoding="utf-8")
    return subprocess.run(
        [reader, f"--symbol={symbol}", str(header), "--", "-x", "c", "-std=c11", "-target", triple],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )


@pytest.mark.parametrize(
    ("triple", "bits"),
    [("i686-w64-windows-gnu", 32), ("x86_64-w64-windows-gnu", 64), ("aarch64-w64-windows-gnu", 64)],
)
@pytest.mark.parametrize("symbol", [*POINTER_SYMBOLS, "PTR_SIGNED"])
def test_pointer_macro_reader_preserves_target_type_and_bits(reader, tmp_path, triple, bits, symbol):
    result = _read_pointer(reader, tmp_path, symbol, triple)

    assert result.returncode == 0, result.stderr
    assert not result.stderr
    header = NativeHeaderCodec().decode(result.stdout)
    declaration = next(item for item in json.loads(result.stdout)["declarations"] if item["name"] == symbol)
    projected = next(item for item in header.exports if item.name == symbol)
    expected = {
        "PTR_NULL": 0,
        "PTR_ALL": (1 << bits) - 1,
        "PTR_ALIAS": (1 << bits) - 1,
        "PTR_CAST": 16,
        "PTR_CONST": 32,
        "PTR_TRUNCATED": 0x100000001 & ((1 << bits) - 1),
        "PTR_SIGNED": (1 << bits) - 2,
    }
    assert declaration["kind"] == "pointer_constant"
    assert declaration["pointer_bits"] == bits
    assert declaration["value"] == str(expected[symbol])
    assert declaration["source"].endswith("Pointers.h")
    assert isinstance(projected, NativePointerConstant)
    assert projected.pointer_bits == bits and projected.decimal_value == str(expected[symbol])
    native_type = declaration["type"]
    if symbol in {"PTR_ALL", "PTR_ALIAS", "PTR_CONST"}:
        assert native_type["kind"] == "typedef"
        assert native_type["name"] == ("ReadOnlyBytes" if symbol == "PTR_CONST" else "SentinelHandle")
    while native_type["kind"] in {"typedef", "qualified"}:
        native_type = native_type["underlying"]
    assert native_type["kind"] == "pointer"
    pointee = native_type["pointee"]
    assert pointee["name"] == ("int" if symbol == "PTR_CAST" else "unsigned char" if symbol == "PTR_CONST" else "void")
    assert pointee["const"] == (symbol == "PTR_CONST")


@pytest.mark.parametrize(
    "symbol",
    [
        "PTR_OBJECT",
        "PTR_OBJECT_OFFSET",
        "PTR_NULL_ARITH",
        "PTR_RUNTIME",
        "PTR_CALL",
        "PTR_EFFECT",
        "PTR_FUNCTION",
        "PTR_FUNCTION_NULL",
        "PTR_STRING",
        "PTR_STRING_OFFSET",
        "PTR_ADDRESS_SPACE",
        "PTR_ADDRESS_SPACE_ALIAS",
    ],
)
def test_pointer_macro_reader_rejects_nonrepresentable_values(reader, tmp_path, symbol):
    result = _read_pointer(reader, tmp_path, symbol, "x86_64-w64-windows-gnu")

    assert result.returncode != 0
    if symbol in {"PTR_ADDRESS_SPACE", "PTR_ADDRESS_SPACE_ALIAS"}:
        assert symbol in result.stderr or "Native address spaces are not implemented" in result.stderr
    else:
        assert f"Native macro {symbol}" in result.stderr
    assert not result.stdout, "a rejected macro must not publish a partial native document"


def _compile_pointer_constants(tmp_path: Path, request, frontend: str, program: str) -> tuple:
    (tmp_path / "Pointers.h").write_text(POINTER_MACROS, encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(
        STRING_MANIFEST.replace('header = "Macros.h"', 'header = "Pointers.h"').format(
            symbols=", ".join(json.dumps(symbol) for symbol in [*POINTER_SYMBOLS, "pointerMatchesSdk"])
        ),
        encoding="utf-8",
    )
    source = tmp_path / "Main.btrc"
    source.write_text(program, encoding="utf-8")
    generated = tmp_path / "Program.c"
    plan = tmp_path / "plan.json"
    flags = [
        "--no-cache",
        "--strict-imports",
        "--target",
        TargetCatalog().host_target(),
        "--emit-link-plan",
        str(plan),
        str(source),
        "-o",
        str(generated),
    ]
    command = (
        [sys.executable, "-B", "-m", "src.compiler.python.main", *flags]
        if frontend == "python"
        else [str(request.getfixturevalue("btrcc_bin")), *flags]
    )
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT)
    return compiled, generated, plan


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_pointer_macro_values_match_actual_c_and_keep_sdk_names(reader, tmp_path, request, frontend):
    del reader
    program = """int main() {
    void* zero = PTR_NULL;
    void* all = PTR_ALL;
    int* castValue = PTR_CAST;
    const unsigned char* readOnly = PTR_CONST;
    void* alias = PTR_ALIAS;
    void* truncated = PTR_TRUNCATED;
    assert(pointerMatchesSdk(zero, all, castValue, readOnly, alias, truncated) != 0);
    assert(zero == null && alias == all);
    printf("PASS: native pointer macro constants\\n");
    return 0;
}
"""
    compiled, generated, plan = _compile_pointer_constants(tmp_path, request, frontend, program)
    assert compiled.returncode == 0, compiled.stderr
    assert not compiled.stderr
    text = generated.read_text(encoding="utf-8")
    for symbol in POINTER_SYMBOLS:
        assert re.search(rf"=\s*{symbol}\s*;", text), symbol
        assert not re.search(rf"\b{symbol}\s*=", text), "a macro value must not acquire fabricated storage"
    executable = tmp_path / "Program"
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=default_c_compiler(),
        cxx=default_cxx_compiler(),
    )
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: native pointer macro constants\n"
    assert not ran.stderr


@pytest.mark.parametrize(
    ("statement", "diagnostic"),
    [
        ("PTR_ALL = null;", "error: Cannot modify read-only native global"),
        ("PTR_ALL++;", "error: Cannot modify read-only native global"),
        ("++PTR_ALL;", "error: Cannot modify read-only native global"),
        ("var slot = &PTR_ALL;", "error: Native constant 'PTR_ALL' is a value and has no address"),
        ("int number = PTR_ALL;", "error: Cannot assign"),
        ("unsigned char* bytes = PTR_CONST;", "error: Cannot assign"),
    ],
)
def test_pointer_macro_value_only_and_type_diagnostics_match(reader, tmp_path, request, statement, diagnostic):
    del reader
    program = f"int main() {{\n\t{statement}\n\treturn 0;\n}}\n"
    reports = []
    for frontend in ("python", "selfhost"):
        directory = tmp_path / frontend
        directory.mkdir()
        compiled, generated, plan = _compile_pointer_constants(directory, request, frontend, program)
        assert compiled.returncode != 0, frontend
        assert not generated.exists() and not plan.exists(), "rejected use must not publish native outputs"
        lines = [line for line in compiled.stderr.splitlines() if diagnostic in line]
        assert lines, (frontend, compiled.stderr)
        reports.append(re.sub(r" at \d+:\d+$", "", lines[0][lines[0].index(diagnostic) :]))
    assert reports[0] == reports[1]
