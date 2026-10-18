"""The target ABI fixture, through both compilers, for every target row.

`src/tests/native/target_abi` is one C surface whose layout depends on the
target's data model, and `TargetAbi.btrc` checks each fact across the C
boundary (platform-target-contract.md section 7).

Static half (Stage 24, section 7.1). For each row with a toolchain on this
host, both compilers turn the program into C for that row, reading
`target_abi.h` through the row's sysroot; their link plans must be
byte-identical. The native reader's record layouts for the row's triple then
become `target_abi_static.h`, whose `_Static_assert`s on the row's data model
(widths and signedness) and on every field offset the row's own C compiler
checks against the fixture's C side. Each compiler's generated C compiles for
the row too. Nothing links or runs: a row without a toolchain here is a
classified skip naming its bound (Mac-bound, NDK-bound, runner-bound).

Run mode (section 7.2). The host row builds through `tools/native_plan.py`,
runs, and must print `target_abi.expected`, the lines every row prints. Every
other row runs in its Stage 25 host lane, on the executor its granted
BTRC_TEST_CAPABILITIES capability names (windows-native, ios-simulator,
android-emulator) through `src/tests/target_runner.py`; until those executors
exist it skips with "Stage 25 host lane".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS, GeneratedTargetRow
from src.compiler.python.frontend.packages import PackageTarget
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TOOL_TIMEOUT, TRANSPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder, NativePlanError, TargetToolchain

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "src" / "tests" / "native" / "target_abi"
LABELS = tuple(row.label for row in TARGET_ROWS)
ROWS = {row.label: row for row in TARGET_ROWS}
RECORDS = ("TargetAbiMixed", "TargetAbiPacked")
STRICT = ["-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
# What a row's toolchain is bound to when this host has none.
BOUNDS = {
    "xcrun": "Mac-bound",
    "ndk": "NDK-bound",
    "windows-sdk": "runner-bound",
    "zig-mingw": "zig-bound",
    "none": "zig-bound",
}
# The Stage 25 executor capability each mobile or Windows row runs under.
EXECUTORS = {"windows": "windows-native", "ios": "ios-simulator", "android": "android-emulator"}


def _environment(row: GeneratedTargetRow, sysroot: Path) -> dict[str, str]:
    """The compile environment of a build for `row`: its triple and sysroot."""

    return {
        **os.environ,
        "BTRC_HOME": str(REPO / "src"),
        "BTRC_NATIVE_TARGET": row.triple,
        "BTRC_NATIVE_SYSROOT": str(sysroot),
    }


def _reader_arguments(row: GeneratedTargetRow, sysroot: Path) -> list[str]:
    """The target and sysroot arguments both compilers give the reader for `row`."""

    if row.sysroot_kind == "ndk":
        return [f"--target={row.triple}", f"--sysroot={sysroot}"]
    arguments = [f"--target={row.triple}", "-isysroot", str(sysroot)]
    if row.operating_system == "linux":
        arguments += ["-isystem", str(sysroot / "usr" / "include")]
    elif row.operating_system == "windows":
        arguments += ["-isystem", str(sysroot / "include" / "any-windows-any")]
    return arguments


class TargetAbiBuild:
    """One row's toolchain, sysroot and both compilers' output for the fixture."""

    _built: ClassVar[dict[str, TargetAbiBuild]] = {}

    def __init__(self, row: GeneratedTargetRow, directory: Path, btrcc: Path) -> None:
        self.row = row
        self.directory = directory
        if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
            pytest.skip("requires the native header reader (BTRC_NATIVE_HEADER_READER; the dev shell provides it)")
        try:
            self.toolchain = TargetToolchain(row)
            if row.sysroot_kind == "none":
                # Its headers are freestanding, so an empty directory is a
                # complete sysroot for a row whose sysroot is the host's.
                self.sysroot = directory / "sysroot"
                self.sysroot.mkdir()
            else:
                self.sysroot = self.toolchain.sysroot()
        except NativePlanError as error:
            pytest.skip(f"{row.label} is {BOUNDS[row.sysroot_kind]}: {error}")
        self.package = directory / "target_abi"
        shutil.copytree(FIXTURE, self.package)
        self.source = self.package / "TargetAbi.btrc"
        self.reference_c = directory / "reference.c"
        self.reference_plan = directory / "reference.link.json"
        self.selfhost_c = directory / "selfhost.c"
        self.selfhost_plan = directory / "selfhost.link.json"
        environment = _environment(row, self.sysroot)
        flags = ["--no-stdlib", "--strict-imports", "--no-cache", "--target", row.label]
        reference = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                *flags,
                "--emit-link-plan",
                str(self.reference_plan),
                str(self.source),
                "-o",
                str(self.reference_c),
            ],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert reference.returncode == 0, reference.stderr
        selfhost = subprocess.run(
            [str(btrcc), *flags, "--emit-link-plan", str(self.selfhost_plan), str(self.source)],
            cwd=REPO,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert selfhost.returncode == 0, selfhost.stderr
        self.selfhost_c.write_text(selfhost.stdout, encoding="utf-8")

    @classmethod
    def for_row(cls, label: str, factory: pytest.TempPathFactory, btrcc: Path) -> TargetAbiBuild:
        """One build per row and worker, shared by the static half and the run mode."""

        if label not in cls._built:
            cls._built[label] = cls(ROWS[label], factory.mktemp(f"target-abi-{label}"), btrcc)
        return cls._built[label]

    def plan(self) -> dict:
        return json.loads(self.reference_plan.read_text(encoding="utf-8"))

    def layouts(self) -> dict[str, dict]:
        """The reader's records for this row's triple, read as the compilers read them."""

        completed = subprocess.run(
            [
                os.environ["BTRC_NATIVE_HEADER_READER"],
                *(f"--symbol={name}" for name in RECORDS),
                str(self.package / "target_abi.h"),
                "--",
                "-x",
                "c",
                "-std=c11",
                *_reader_arguments(self.row, self.sysroot),
            ],
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        records = {record["name"]: record for record in json.loads(completed.stdout)["records"]}
        assert set(RECORDS) <= records.keys(), sorted(records)
        return records

    def static_header(self) -> Path:
        """target_abi_static.h: the row's data model and the reader's layouts as assertions."""

        row = self.row
        lines = [
            f"/* The target ABI fixture's static half for {row.label} ({row.triple}). */",
            "#include <stddef.h>",
            f'#include "{self.package / "target_abi.h"}"',
            f'_Static_assert(sizeof(long) == {row.sizeof_long}, "long is {row.sizeof_long} bytes");',
            f'_Static_assert(sizeof(wchar_t) == {row.sizeof_wchar_t}, "wchar_t is {row.sizeof_wchar_t} bytes");',
            f"_Static_assert(sizeof(long double) == {row.sizeof_long_double}, "
            f'"long double is {row.sizeof_long_double} bytes");',
            f'_Static_assert(sizeof(void*) == {row.sizeof_pointer}, "pointers are {row.sizeof_pointer} bytes");',
            f'_Static_assert(sizeof(size_t) == {row.sizeof_pointer}, "size_t is {row.sizeof_pointer} bytes");',
            # A promoted minus one is positive exactly when the type is unsigned.
            f"_Static_assert(((char)-1 > 0) == {int(not row.char_signed)}, "
            f'"char is {"signed" if row.char_signed else "unsigned"}");',
            f"_Static_assert(((wchar_t)-1 > 0) == {int(not row.wchar_signed)}, "
            f'"wchar_t is {"signed" if row.wchar_signed else "unsigned"}");',
        ]
        for name, record in sorted(self.layouts().items()):
            if name not in RECORDS:
                continue
            size, alignment = int(record["size_bits"]) // 8, int(record["alignment_bits"]) // 8
            lines.append(f'_Static_assert(sizeof({name}) == {size}, "{name} is {size} bytes");')
            lines.append(f'_Static_assert(_Alignof({name}) == {alignment}, "{name} aligns to {alignment}");')
            for field in record["fields"]:
                offset_bits = int(field["offset_bits"])
                assert offset_bits % 8 == 0, (name, field)
                lines.append(
                    f"_Static_assert(offsetof({name}, {field['name']}) == {offset_bits // 8}, "
                    f'"{name}.{field["name"]} is at byte {offset_bits // 8}");'
                )
        header = self.directory / "target_abi_static.h"
        header.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return header

    def compile(self, source: Path, *, generated: bool, flags: list[str] = ()) -> None:
        """Compile one C file for the row, without linking it."""

        command = self.toolchain.compile_command(
            source, source.with_suffix(".o"), generated=generated, flags=[*STRICT, *flags]
        )
        completed = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert completed.returncode == 0, (command, completed.stderr)


@pytest.fixture
def target_abi(request, tmp_path_factory) -> TargetAbiBuild:
    return TargetAbiBuild.for_row(request.param, tmp_path_factory, request.getfixturevalue("immutable_btrcc"))


@pytest.mark.parametrize("target_abi", LABELS, indirect=True)
def test_target_abi_static_half_compiles_for_the_row(target_abi: TargetAbiBuild) -> None:
    row = target_abi.row
    # The two compilers' plans agree byte for byte. Their C need not: they
    # spell the native callback's thunk and lease release differently, and
    # both translations must compile for the row. The callback's receiver
    # cannot cycle, so neither may bring in the cycle collector.
    assert target_abi.selfhost_plan.read_bytes() == target_abi.reference_plan.read_bytes()
    for generated in (target_abi.reference_c, target_abi.selfhost_c):
        assert "__btrc_flush_cycles" not in generated.read_text(encoding="utf-8"), generated.name
    plan = target_abi.plan()
    assert plan["schema"] == 5 and plan["target"]["label"] == row.label
    assert plan["toolchain"]["target-arguments"] == list(row.target_arguments)
    # The fixture's C side holds the row's data model and the reader's layouts.
    target_abi.compile(
        target_abi.package / "target_abi.c", generated=False, flags=["-include", str(target_abi.static_header())]
    )
    includes = [f"-I{record['path']}" for record in plan["include-directories"]]
    for generated in (target_abi.reference_c, target_abi.selfhost_c):
        target_abi.compile(generated, generated=True, flags=includes)


@pytest.mark.parametrize("target_abi", LABELS, indirect=True)
def test_target_abi_run_mode_prints_the_expected_facts(target_abi: TargetAbiBuild) -> None:
    row = target_abi.row
    if not target_abi.toolchain.host:
        executor = EXECUTORS.get(row.operating_system)
        where = f"the {executor} executor" if executor else "a host of its own"
        pytest.skip(f"Stage 25 host lane: {row.label} runs on {where} (src/tests/target_runner.py)")
    executable = target_abi.directory / "TargetAbi"
    NativePlanBuilder().build(plan_path=target_abi.selfhost_plan, generated_c=target_abi.selfhost_c, output=executable)
    completed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout == (FIXTURE / "target_abi.expected").read_text(encoding="utf-8")


def test_every_row_has_an_expected_bound() -> None:
    """A row with no toolchain here must skip naming its bound, never silently pass."""

    assert {row.sysroot_kind for row in TARGET_ROWS} <= BOUNDS.keys()
    assert PackageTarget.parse(None).label in LABELS
