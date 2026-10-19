"""The Windows overlay's regex.h, fnmatch.h and glob.h stay out of the caller's way.

Each header compiles musl's engine into the unit that includes it
(src/runtime/windows/btrc_win_musl.h). Generated btrc code, MinGW headers and
windows.h share that unit, so the engine must leave nothing behind but the
POSIX interface: no macro of its own, no caller macro changed (an earlier
MIN, END or assert keeps its meaning), and every file-scope name it declares
in btrc's namespace with internal linkage. These tests check that from the
preprocessor's and the compiler's own view of real units, check that two
units of one program link with their own copies, and build two Windows
programs for windows.yml's win32-native job: glob over non-ASCII names, and
the two linked units.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.windows_evidence_fixtures import (
    WINDOWS_TARGETS,
    build_c_fixture,
    publish,
    windows_toolchain,
)
from tools.hosted_platform import HostedPlatformError, HostedPlatformExtractor

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "src" / "tests" / "native" / "posix_matching"

REGEX_MACROS = {
    "regcomp",
    "regexec",
    "regfree",
    "regerror",
    "REG_EXTENDED",
    "REG_ICASE",
    "REG_NEWLINE",
    "REG_NOSUB",
    "REG_NOTBOL",
    "REG_NOTEOL",
    "REG_OK",
    "REG_NOMATCH",
    "REG_BADPAT",
    "REG_ECOLLATE",
    "REG_ECTYPE",
    "REG_EESCAPE",
    "REG_ESUBREG",
    "REG_EBRACK",
    "REG_EPAREN",
    "REG_EBRACE",
    "REG_BADBR",
    "REG_ERANGE",
    "REG_ESPACE",
    "REG_BADRPT",
    "REG_ENOSYS",
    "BTRC_WIN_MUSL_REGEX",
    "BTRC_WIN_MUSL_C_LOCALE",
}
FNMATCH_MACROS = {
    "fnmatch",
    "FNM_PATHNAME",
    "FNM_NOESCAPE",
    "FNM_PERIOD",
    "FNM_LEADING_DIR",
    "FNM_CASEFOLD",
    "FNM_FILE_NAME",
    "FNM_NOMATCH",
    "FNM_NOSYS",
    "BTRC_WIN_MUSL_FNMATCH",
    "BTRC_WIN_MUSL_C_LOCALE",
}
GLOB_MACROS = FNMATCH_MACROS | {
    "glob",
    "globfree",
    "GLOB_ERR",
    "GLOB_MARK",
    "GLOB_NOSORT",
    "GLOB_DOOFFS",
    "GLOB_NOCHECK",
    "GLOB_APPEND",
    "GLOB_NOESCAPE",
    "GLOB_NOSPACE",
    "GLOB_ABORTED",
    "GLOB_NOMATCH",
    "BTRC_WIN_MUSL_GLOB",
}
HEADERS = {"regex.h": REGEX_MACROS, "fnmatch.h": FNMATCH_MACROS, "glob.h": GLOB_MACROS}
# The types the POSIX interfaces declare.
PUBLIC_DECLARATIONS = {"regex_t", "re_pattern_buffer", "regmatch_t", "regoff_t", "glob_t"}
# Engine files whose declarations must stay in btrc's namespace (btrc_win_compat.h and
# its realpath and error seams predate the engine and are covered by test_native_win_compat.py).
ENGINE_FILES = ("regex.h", "fnmatch.h", "glob.h", "btrc_win_musl.h", "/musl/")

# What a caller has defined before it includes an overlay header: the system
# headers the engine itself includes, an assert, and macros named like the
# engine's own (MIN, END, TAG, UNION) with other meanings.
CALLER = """#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <io.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
#define MIN(a, b) ((a) + (b))
#define END "caller"
#define TAG 7
#define UNION struct
"""

_DEFINE = re.compile(r"^#define ([A-Za-z_]\w*)(.*)$")


def _preprocess(target: str, source: Path, *flags: str) -> str:
    toolchain = windows_toolchain(WINDOWS_TARGETS[target])
    completed = subprocess.run(
        [
            *toolchain.drivers["cc"],
            *toolchain.arguments,
            "-std=c11",
            *toolchain.generated_arguments,
            *flags,
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT * 5,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _macros(target: str, source: Path) -> dict[str, str]:
    definitions = {}
    for line in _preprocess(target, source, "-E", "-dM").splitlines():
        match = _DEFINE.match(line)
        if match:
            definitions[match.group(1)] = match.group(2).strip()
    return definitions


@pytest.mark.parametrize("header", sorted(HEADERS))
def test_overlay_adds_only_its_posix_macros(header, tmp_path):
    before = tmp_path / "before.c"
    before.write_text(CALLER, encoding="utf-8")
    after = tmp_path / "after.c"
    after.write_text(f"{CALLER}#include <{header}>\n", encoding="utf-8")
    old, new = _macros("windows-x64", before), _macros("windows-x64", after)
    assert set(new) - set(old) == HEADERS[header]
    assert set(old) - set(new) == set()
    assert {name for name in old if old[name] != new[name]} == set()
    assert new["regcomp" if header == "regex.h" else "fnmatch"].startswith("btrc_win_")


def _top_level(ast: dict) -> list[tuple[str, str, str, dict]]:
    """(kind, name, file, node) for each named file-scope declaration, in dump order.

    clang's JSON dump prints a location's file only when it differs from the
    previous location printed, so the current file is tracked over every
    location in the tree, in order."""
    state = {"file": ""}

    def see(location):
        if not isinstance(location, dict):
            return
        if "spellingLoc" in location or "expansionLoc" in location:
            see(location.get("spellingLoc"))
            see(location.get("expansionLoc"))
            return
        state["file"] = location.get("presumedFile", location.get("file", state["file"]))

    def walk(node):
        see(node.get("loc"))
        span = node.get("range") or {}
        see(span.get("begin"))
        see(span.get("end"))
        for child in node.get("inner", []) or []:
            walk(child)

    declarations = []
    for node in ast.get("inner", []):
        see(node.get("loc"))
        file = state["file"]
        span = node.get("range") or {}
        see(span.get("begin"))
        see(span.get("end"))
        if node.get("name") and not node.get("isImplicit"):
            declarations.append((node["kind"], node["name"], file, node))
        if node.get("kind") == "EnumDecl":
            declarations.extend(
                ("EnumConstantDecl", child["name"], file, child)
                for child in node.get("inner", [])
                if child.get("kind") == "EnumConstantDecl"
            )
        for child in node.get("inner", []) or []:
            walk(child)
    return declarations


@pytest.mark.parametrize("header", sorted(HEADERS))
def test_engine_declarations_stay_internal_and_namespaced(header, tmp_path):
    try:
        clang = HostedPlatformExtractor().clang()
    except HostedPlatformError as error:
        pytest.skip(str(error))
    unit = tmp_path / "unit.c"
    unit.write_text(f"#include <{header}>\n", encoding="utf-8")
    preprocessed = tmp_path / "unit.i"
    preprocessed.write_text(_preprocess("windows-x64", unit, "-E"), encoding="utf-8")
    dumped = subprocess.run(
        [clang, "--target=x86_64-w64-windows-gnu", "-std=c11", "-w", "-fsyntax-only", "-x", "cpp-output"]
        + ["-Xclang", "-ast-dump=json", str(preprocessed)],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT * 5,
        check=False,
    )
    assert dumped.returncode == 0, dumped.stderr
    declarations = [
        entry for entry in _top_level(json.loads(dumped.stdout)) if any(part in entry[2] for part in ENGINE_FILES)
    ]
    assert declarations, "the engine declared nothing the dump attributes to its files"
    foreign = sorted({name for _, name, _, _ in declarations} - PUBLIC_DECLARATIONS)
    assert [name for name in foreign if not name.startswith("btrc_win_")] == []
    functions: dict[str, list[dict]] = {}
    for kind, name, _, node in declarations:
        if kind == "FunctionDecl" and name.startswith("btrc_win_"):
            functions.setdefault(name, []).append(node)
        if kind == "VarDecl":
            assert node.get("storageClass") == "static", name
    assert functions
    assert [
        name for name, nodes in functions.items() if not any(n.get("storageClass") == "static" for n in nodes)
    ] == []


@pytest.mark.parametrize("order", ["windows-h-first", "windows-h-last"])
@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_overlays_build_beside_windows_h(order, target, tmp_path):
    overlays = "#include <regex.h>\n#include <fnmatch.h>\n#include <glob.h>\n"
    windows = "#include <windows.h>\n"
    source = tmp_path / "beside.c"
    source.write_text(
        (windows + overlays if order == "windows-h-first" else overlays + windows)
        + "int main(void) {\n"
        + "\tregex_t compiled;\n\tglob_t found;\n"
        + '\tint status = regcomp(&compiled, "a+", REG_EXTENDED);\n'
        + "\tif (status == 0) regfree(&compiled);\n"
        + '\tif (glob("*", 0, NULL, &found) == 0) globfree(&found);\n'
        + '\treturn status + fnmatch("*", "x", 0) + (int)GetCurrentProcessId() * 0;\n}\n',
        encoding="utf-8",
    )
    build_c_fixture([source], target, tmp_path / "beside.exe")


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_two_units_link_their_own_engines(target, tmp_path):
    executable = build_c_fixture(
        [FIXTURES / "OverlayUnitMain.c", FIXTURES / "OverlayUnitHelper.c"], target, tmp_path / "units.exe"
    )
    publish(executable, f"posix-overlay-units-{target}", b"posix-overlay units regex=1 span=1-4 fnmatch=1 glob=1\n")


@pytest.mark.parametrize("target", sorted(WINDOWS_TARGETS))
def test_glob_reads_non_ascii_names(target, tmp_path):
    executable = build_c_fixture([FIXTURES / "GlobUnicode.c"], target, tmp_path / "glob-unicode.exe")
    publish(executable, f"glob-unicode-{target}", b"glob-unicode status=0 count=3 matched=1\n")
