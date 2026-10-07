"""C2 aggregate layout follows the emitted C, identically in both compilers (PLAN.md Stage 17).

btrc computes no C2 layout itself (docs/design/c-compatibility.md, "Layout"):
the C compiler lays out the declarations btrc emits. Each layout program
under ``c_compat`` declares its aggregates in btrc and imports a C mirror
that returns ``sizeof`` and ``offsetof`` as ``size_t``; the program fails
unless its own sizes and offsets match. This test requires that

- both compilers emit byte-identical declarations for those aggregates,
- the raw IR (before the optimizer) carries the layout facet itself, so a
  flexible array member is ``is_unsized_array`` storage rather than a
  pointer field, and
- the program built from each compiler's C matches the mirror under every
  host C compiler (gcc and clang here; Apple clang on the macOS workflow).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import compiler_environment
from src.tests.c_toolchains import HOST_C_COMPILERS

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "src/tests/c_compat"

# layout program -> {struct name: {unsized-array field: its element's C type}}
LAYOUT_PROGRAMS = {
    "FlexibleArrayLayout.btrc": {
        "Ints": {"data": "int"},
        "CharDoubles": {"d": "double"},
        "Tail": {"d": "char"},
        "Pairs": {"items": "struct Pair"},
        "Pointers": {"items": "void*"},
    },
}

pytestmark = pytest.mark.skipif(not HOST_C_COMPILERS, reason="layout checks need gcc or clang")


def _reference(arguments: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", *arguments, "--no-cache"],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "reference-cache")},
        capture_output=True,
        text=True,
        timeout=300,
    )


def _selfhost(btrcc: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(btrcc), *arguments], cwd=REPO, capture_output=True, text=True, timeout=300)


def _generated(btrcc: Path, program: Path, tmp_path: Path) -> dict[str, Path]:
    """Each compiler's C for ``program``, compiled in place so its relative C import resolves."""
    reference_c = tmp_path / f"{program.stem}.reference.c"
    reference = _reference([str(program), "-o", str(reference_c)], tmp_path)
    assert reference.returncode == 0, reference.stderr
    selfhost = _selfhost(btrcc, [str(program)])
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_c = tmp_path / f"{program.stem}.selfhost.c"
    selfhost_c.write_text(selfhost.stdout)
    return {"reference": reference_c, "selfhost": selfhost_c}


def _declarations(source: str, names: set[str]) -> dict[str, str]:
    found = {}
    for name in names:
        match = re.search(rf"^struct {name} \{{\n.*?^\}};$", source, re.MULTILINE | re.DOTALL)
        assert match is not None, f"no definition of struct {name}"
        found[name] = match.group(0)
    return found


_SELFHOST_STRUCT = re.compile(r'^  struct name="(?P<name>[^"]+)"')
_SELFHOST_FIELD = re.compile(r'^    field cType="(?P<c_type>[^"]*)" name="(?P<name>[^"]*)"(?P<facets>.*)$')


def _raw_ir_structs(btrcc: Path, program: Path, tmp_path: Path) -> dict[str, dict[str, list[tuple[str, str, bool]]]]:
    """Each compiler's raw IR records as ``{struct: [(field, C type, unsized)]}``.

    The reference dumps its IR as JSON; btrcc dumps ``btrcc-ir-v1`` text, one
    ``field`` line per member with its facets after the name."""
    reference = _reference([str(program), "--emit-ir"], tmp_path)
    assert reference.returncode == 0, reference.stderr
    reference_structs = {
        struct["name"]: [
            (field["name"], field["c_type"]["text"], field["is_unsized_array"] and field["array_size"] is None)
            for field in struct["fields"]
        ]
        for struct in json.loads(reference.stdout)["module"]["struct_defs"]
    }
    selfhost = _selfhost(btrcc, [str(program), "--emit-ir"])
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_structs: dict[str, list[tuple[str, str, bool]]] = {}
    current = None
    for line in selfhost.stdout.splitlines():
        struct = _SELFHOST_STRUCT.match(line)
        if struct is not None:
            current = selfhost_structs.setdefault(struct.group("name"), [])
            continue
        field = _SELFHOST_FIELD.match(line)
        if field is not None and current is not None:
            current.append(
                (field.group("name"), field.group("c_type"), "unsizedArray" in field.group("facets").split())
            )
        elif not line.startswith("    "):
            current = None
    return {"reference": reference_structs, "selfhost": selfhost_structs}


@pytest.mark.parametrize("program_name", sorted(LAYOUT_PROGRAMS))
def test_both_compilers_emit_identical_aggregate_declarations(
    semantic_btrcc: Path, tmp_path: Path, program_name: str
) -> None:
    program = CORPUS / program_name
    generated = _generated(semantic_btrcc, program, tmp_path)
    names = set(LAYOUT_PROGRAMS[program_name])
    reference = _declarations(generated["reference"].read_text(), names)
    selfhost = _declarations(generated["selfhost"].read_text(), names)
    assert selfhost == reference
    for name, fields in LAYOUT_PROGRAMS[program_name].items():
        for field, c_type in fields.items():
            # C's spelling of the member, never btrc's pointer-valued array.
            declarator = rf"^\s+{re.escape(c_type)} {field}\[\];$"
            assert re.search(declarator, reference[name], re.MULTILINE), reference[name]


@pytest.mark.parametrize("program_name", sorted(LAYOUT_PROGRAMS))
def test_raw_ir_carries_unsized_array_storage(semantic_btrcc: Path, tmp_path: Path, program_name: str) -> None:
    program = CORPUS / program_name
    modules = _raw_ir_structs(semantic_btrcc, program, tmp_path)
    for name, unsized in LAYOUT_PROGRAMS[program_name].items():
        assert modules["selfhost"][name] == modules["reference"][name], name
        fields = modules["reference"][name]
        # Array storage of the element type, never btrc's pointer-valued array.
        assert {field: c_type for field, c_type, marked in fields if marked} == unsized, (name, fields)


@pytest.mark.parametrize("program_name", sorted(LAYOUT_PROGRAMS))
def test_layout_matches_the_c_mirror_under_every_host_compiler(
    semantic_btrcc: Path, tmp_path: Path, program_name: str
) -> None:
    program = CORPUS / program_name
    expected = (CORPUS / "expected" / f"{program.stem}.stdout").read_text()
    for frontend, generated in _generated(semantic_btrcc, program, tmp_path).items():
        for compiler in HOST_C_COMPILERS:
            environment = compiler_environment(compiler)
            executable = tmp_path / f"{frontend}-{Path(compiler).name}"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(generated),
                    "-pthread",
                    "-lm",
                    "-o",
                    str(executable),
                ],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert build.returncode == 0, (frontend, compiler, build.stderr)
            run = subprocess.run(
                [str(executable)], cwd=REPO, env=environment, capture_output=True, text=True, timeout=60
            )
            assert (run.returncode, run.stdout) == (0, expected), (frontend, compiler, run.stdout, run.stderr)
