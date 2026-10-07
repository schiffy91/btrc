"""One accepted target set, one message and one host inference in both compilers.

platform-target-contract.md §1.4-§1.7 and §1.11: both compilers accept the 11
canonical labels and their 19 alias spellings, reject everything else with the
same message at the same point (after argument errors, before any input is
read), and infer the same host row from the same normalized tokens.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi import hosted as hosted_module
from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.abi.hosted import TargetRepository, TargetSelectionError
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import (
    CompilerFailure,
    CompilerFailureKind,
    CompilerOptions,
    CompilerOutput,
)
from src.compiler.python.artifacts.archive import TargetCatalog
from src.compiler.python.cli.compiler import CompilerCommand, CompilerDiagnostics
from src.compiler.python.frontend.packages import PackageTarget
from tools.qualification.schema import TARGET_SLICES

REPO = Path(__file__).resolve().parents[3]
DRIVER = REPO / "src/tests/btrc/fixtures/TargetContractDriver.btrc"
TIMEOUT = 300

LABELS = (
    "android-aarch64",
    "android-x86_64",
    "ios-aarch64",
    "ios-aarch64-simulator",
    "linux-aarch64",
    "linux-x86_64",
    "macos-aarch64",
    "macos-x86_64",
    "windows-aarch64",
    "windows-aarch64-msvc",
    "windows-x86_64",
)
UNSUPPORTED = (
    "unsupported target '{raw}'; expected one of android-aarch64, android-x86_64, ios-aarch64, "
    "ios-aarch64-simulator, linux-aarch64, linux-x86_64, macos-aarch64, macos-x86_64, windows-aarch64, "
    "windows-aarch64-msvc, windows-x86_64"
)
UNKNOWN_HOST = "cannot infer a supported target from this host; pass --target"
REPEATED = "--target may be specified only once"

# §1.5: the 11 labels, then x64/arm64 on each row (11), -gnu on the four
# linux and windows-gnu rows (4), and both forms together there (4).
ACCEPTED = {
    **{label: label for label in LABELS},
    "android-arm64": "android-aarch64",
    "android-x64": "android-x86_64",
    "ios-arm64": "ios-aarch64",
    "ios-arm64-simulator": "ios-aarch64-simulator",
    "linux-arm64": "linux-aarch64",
    "linux-x64": "linux-x86_64",
    "macos-arm64": "macos-aarch64",
    "macos-x64": "macos-x86_64",
    "windows-arm64": "windows-aarch64",
    "windows-arm64-msvc": "windows-aarch64-msvc",
    "windows-x64": "windows-x86_64",
    "linux-aarch64-gnu": "linux-aarch64",
    "linux-x86_64-gnu": "linux-x86_64",
    "windows-aarch64-gnu": "windows-aarch64",
    "windows-x86_64-gnu": "windows-x86_64",
    "linux-arm64-gnu": "linux-aarch64",
    "linux-x64-gnu": "linux-x86_64",
    "windows-arm64-gnu": "windows-aarch64",
    "windows-x64-gnu": "windows-x86_64",
}
REJECTED = (
    "linux-x86",
    "ios-x86_64-simulator",
    "macos-arm64-gnu",
    "windows-x86_64-msvc",
    "android-arm64-29",
    "ios-aarch64-device",
    "macos-aarch64-",
    "linux-x86_64-",
    "",
    "-",
    "linux-",
)
# Every spelling btrc accepted before Stage 24: {linux, macos, windows} with
# x86_64, aarch64, x64 or arm64. Each keeps its (os, arch) and is labelled os-arch.
TODAY = {
    f"{operating_system}-{spelled}": f"{operating_system}-{architecture}"
    for operating_system in ("linux", "macos", "windows")
    for spelled, architecture in (("x86_64", "x86_64"), ("aarch64", "aarch64"), ("x64", "x86_64"), ("arm64", "aarch64"))
}
# §1.7: the host seam, Python's (system, machine) strings and btrcc's
# (platform, architecture) codes, through the normalized tokens to a row.
HOST_SEAM = (
    (("Darwin", "arm64"), (1, 2), "macos-aarch64"),
    (("Darwin", "x86_64"), (1, 1), "macos-x86_64"),
    (("Linux", "x86_64"), (2, 1), "linux-x86_64"),
    (("Linux", "aarch64"), (2, 2), "linux-aarch64"),
    (("Windows", "AMD64"), (3, 1), "windows-x86_64"),
    (("Windows", "x86_64"), (3, 1), "windows-x86_64"),
    (("Windows", "ARM64"), (3, 2), "windows-aarch64"),
    (("Linux", "riscv64"), (2, 0), None),
    (("Windows", "x86"), (3, 0), None),
    (("ios", "arm64"), (0, 2), None),
    (("android", "aarch64"), (0, 2), None),
    (("MSYS_NT-10.0-19045", "x86_64"), (0, 1), None),
    (("FreeBSD", "amd64"), (0, 1), None),
    (("", ""), (0, 0), None),
)
# §1.2: each P0 qualification slice maps to its rows.
SLICE_ROWS = {
    "windows-x64": ("windows-x86_64",),
    "windows-arm64": ("windows-aarch64", "windows-aarch64-msvc"),
    "ios-device": ("ios-aarch64",),
    "ios-simulator": ("ios-aarch64-simulator",),
    "android-arm64": ("android-aarch64",),
    "android-x86_64": ("android-x86_64",),
}


def _row(label: str):
    return next(row for row in TARGET_ROWS if row.label == label)


def _environment(tmp_path: Path) -> dict[str, str]:
    return {**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(tmp_path / "cache")}


def _btrcc(binary: Path, tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *arguments],
        cwd=tmp_path,
        env=_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def _btrcpy(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", *arguments],
        cwd=REPO,
        env={**_environment(tmp_path), "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


@pytest.fixture(scope="module")
def target_driver(selfhost_driver) -> Path:
    """btrc's FePackageTarget, built once per btrcc fingerprint."""

    return selfhost_driver(DRIVER, compile_flags=("-pedantic-errors",))


def _driver(driver: Path, *arguments: str) -> list[str]:
    result = subprocess.run([str(driver), *arguments], capture_output=True, text=True, timeout=TIMEOUT)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


# -- the accepted set and the message ---------------------------------------


def test_the_accepted_set_is_the_rows_and_their_thirty_spellings() -> None:
    assert len(ACCEPTED) == 30
    assert TargetRepository.labels() == LABELS == tuple(sorted(row.label for row in TARGET_ROWS))
    assert Compiler.target_labels() == LABELS
    assert set(ACCEPTED.values()) == set(LABELS)
    assert set(TODAY) <= set(ACCEPTED)


@pytest.mark.parametrize("spelling", sorted(ACCEPTED))
def test_reference_parses_each_accepted_spelling_to_its_row(spelling: str) -> None:
    row = TargetRepository.parse(spelling)
    assert row.label == ACCEPTED[spelling]
    target = PackageTarget.parse(spelling)
    assert (target.operating_system, target.architecture, target.environment) == (
        row.operating_system,
        row.architecture,
        row.environment,
    )
    assert target.label == row.label and target.row == row
    assert Compiler.select_target(spelling) == row.label


@pytest.mark.parametrize("spelling", REJECTED)
def test_reference_rejects_with_the_shared_message(spelling: str) -> None:
    message = UNSUPPORTED.format(raw=spelling)
    with pytest.raises(TargetSelectionError) as raised:
        TargetRepository.parse(spelling)
    assert str(raised.value) == message
    assert isinstance(raised.value, ValueError)
    with pytest.raises(TargetSelectionError, match=r"^unsupported target "):
        PackageTarget.parse(spelling)
    assert Compiler.select_target(spelling) == CompilerFailure(CompilerFailureKind.INPUT, message)


def test_every_spelling_accepted_today_round_trips() -> None:
    for spelling, label in TODAY.items():
        target = PackageTarget.parse(spelling)
        assert f"{target.operating_system}-{target.architecture}" == label
        assert target.environment == TargetRepository.default_environment(target.operating_system)
        assert target.label == label
        assert PackageTarget(target.operating_system, target.architecture) == target


def test_selfhost_parses_and_rejects_as_the_reference(target_driver: Path) -> None:
    spellings = [*sorted(ACCEPTED), *REJECTED]
    expected = []
    for spelling in spellings:
        if spelling in ACCEPTED:
            row = _row(ACCEPTED[spelling])
            expected.append(f"ok {row.label} {row.operating_system} {row.architecture} {row.environment or '-'}")
        else:
            expected.append("error " + UNSUPPORTED.format(raw=spelling))
    assert _driver(target_driver, "parse", *spellings) == expected
    assert _driver(target_driver, "labels") == list(LABELS)


def test_the_compiler_api_compiles_every_spelling_as_its_label(tmp_path: Path) -> None:
    compiler = Compiler()
    path = str(tmp_path / "Main.btrc")
    aliased = compiler.compile(
        "int main() { return 0; }\n", path, CompilerOptions(output=CompilerOutput.AST, target="linux-x64")
    )
    assert aliased.failure is None and aliased.options.target == "linux-x86_64"
    rejected = compiler.compile("int main() { return 0; }\n", path, CompilerOptions(target="linux-x86"))
    assert rejected.failure == CompilerFailure(CompilerFailureKind.INPUT, UNSUPPORTED.format(raw="linux-x86"))


# -- the CLIs: argument errors, then the target, then the input --------------


@pytest.mark.parametrize("spelling", REJECTED)
def test_both_clis_reject_before_reading_the_input(spelling: str, immutable_btrcc: Path, tmp_path: Path) -> None:
    missing = tmp_path / "Missing.btrc"
    plan = tmp_path / "plan.json"
    arguments = ("--target", spelling, "--emit-link-plan", str(plan), str(missing))
    expected = f"error: {UNSUPPORTED.format(raw=spelling)}\n"
    selfhost = _btrcc(immutable_btrcc, tmp_path, *arguments)
    reference = _btrcpy(tmp_path, *arguments)
    for result in (selfhost, reference):
        assert result.returncode == 1, result.stderr
        assert result.stderr == expected
        assert result.stdout == ""
    assert not plan.exists()


@pytest.mark.parametrize("first", ["linux-x86_64", "", "bogus"])
def test_both_clis_refuse_a_repeated_target(first: str, immutable_btrcc: Path, tmp_path: Path) -> None:
    missing = tmp_path / "Missing.btrc"
    arguments = ("--target", first, "--target", "linux-x86_64", str(missing))
    for result in (_btrcc(immutable_btrcc, tmp_path, *arguments), _btrcpy(tmp_path, *arguments)):
        assert result.returncode == 1, result.stderr
        assert result.stderr == f"error: {REPEATED}\n"


def test_argument_errors_precede_the_target(immutable_btrcc: Path, tmp_path: Path) -> None:
    selfhost = _btrcc(immutable_btrcc, tmp_path, "--target", "bogus", "--module-units", "Missing.btrc")
    reference = _btrcpy(tmp_path, "--target", "bogus", "--module-units", "Missing.btrc")
    assert selfhost.returncode == 1 and "--module-units requires --emit-units" in selfhost.stderr
    assert reference.returncode == 2 and "--module-units requires --emit-units" in reference.stderr
    for result in (selfhost, reference):
        assert "unsupported target" not in result.stderr


def test_a_valid_target_then_reads_the_input(immutable_btrcc: Path, tmp_path: Path) -> None:
    missing = tmp_path / "Missing.btrc"
    for result in (
        _btrcc(immutable_btrcc, tmp_path, "--target", "linux-x64", str(missing)),
        _btrcpy(tmp_path, "--target", "linux-x64", str(missing)),
    ):
        assert result.returncode == 1
        assert "unsupported target" not in result.stderr
        assert "Missing.btrc" in result.stderr


@pytest.mark.parametrize("spelling", sorted(ACCEPTED))
def test_both_clis_select_the_same_row_for_each_spelling(spelling: str, immutable_btrcc: Path, tmp_path: Path) -> None:
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    plans = []
    for name, run in (("selfhost", _btrcc), ("reference", None)):
        plan = tmp_path / f"{name}.json"
        output = tmp_path / f"{name}.c"
        arguments = ("--no-cache", "--target", spelling, "--emit-link-plan", str(plan), str(source), "-o", str(output))
        result = run(immutable_btrcc, tmp_path, *arguments) if run is not None else _btrcpy(tmp_path, *arguments)
        assert result.returncode == 0, result.stderr
        plans.append(plan.read_text(encoding="utf-8"))
    assert plans[0] == plans[1]
    row = _row(ACCEPTED[spelling])
    assert json.loads(plans[0])["target"] == {"arch": row.architecture, "os": row.operating_system}


# -- host inference -----------------------------------------------------------


@pytest.mark.parametrize(("seam", "codes", "expected"), HOST_SEAM)
def test_reference_host_seam(seam: tuple[str, str], codes: tuple[int, int], expected: str | None) -> None:
    del codes
    row = TargetRepository.host(*seam)
    assert (row.label if row is not None else None) == expected
    assert row is None or row.compiler_host


def test_selfhost_host_seam_matches_the_reference(target_driver: Path) -> None:
    codes = [str(code) for _seam, pair, _expected in HOST_SEAM for code in pair]
    expected = [label or "none" for _seam, _pair, label in HOST_SEAM]
    assert _driver(target_driver, "host", *codes) == expected
    # Every row of the table whose tokens agree gives the same answer.
    by_codes: dict[tuple[int, int], set[str | None]] = {}
    for _seam, pair, label in HOST_SEAM:
        by_codes.setdefault(pair, set()).add(label)
    assert all(len(labels) == 1 for labels in by_codes.values())


def test_reference_cli_refuses_an_unknown_host_before_reading_the_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(hosted_module.platform, "system", lambda: "Plan9")
    stderr = io.StringIO()
    command = CompilerCommand(Compiler(), diagnostics=CompilerDiagnostics(stderr=stderr))
    with pytest.raises(SystemExit) as raised:
        command.run([str(tmp_path / "Missing.btrc")])
    assert raised.value.code == 1
    assert stderr.getvalue() == f"error: {UNKNOWN_HOST}\n"
    assert Compiler.select_target(None) == CompilerFailure(CompilerFailureKind.INPUT, UNKNOWN_HOST)
    # An explicit target needs no host.
    assert Compiler.select_target("android-x64") == "android-x86_64"


def test_selfhost_refuses_an_unknown_host_before_reading_the_input(selfhost_driver, tmp_path: Path) -> None:
    """A btrcc whose runtime reports platform code 0, the unknown-host seam."""

    unknown = selfhost_driver(
        REPO / "src/compiler/btrc/BtrccMain.btrc", compile_flags=("-DBTRC_TARGET_PLATFORM_OVERRIDE=0",)
    )
    result = _btrcc(unknown, tmp_path, str(tmp_path / "Missing.btrc"))
    assert result.returncode == 1
    assert result.stderr == f"error: {UNKNOWN_HOST}\n"
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    explicit = _btrcc(unknown, tmp_path, "--no-cache", "--target", "linux-x86_64", str(source), "-o", "main.c")
    assert explicit.returncode == 0, explicit.stderr


# -- consumers of the rows ----------------------------------------------------


def test_slices_map_to_rows() -> None:
    assert set(SLICE_ROWS) == set(TARGET_SLICES)
    named = set()
    for slice_name, labels in SLICE_ROWS.items():
        platform, _variant = TARGET_SLICES[slice_name]
        for label in labels:
            assert _row(label).operating_system == platform.value, slice_name
            named.add(label)
    desktop = {row.label for row in TARGET_ROWS if row.compiler_host}
    assert {row.label for row in TARGET_ROWS} - desktop <= named


def test_only_compiler_host_rows_reach_the_release_catalog() -> None:
    catalog = TargetCatalog()
    hosts = [row for row in TARGET_ROWS if row.compiler_host]
    names = {TargetCatalog.release_name(row) for row in hosts}
    assert names == {"linux-x64", "linux-arm64", "macos-x64", "macos-arm64", "windows-x64", "windows-arm64"}
    for name in names:
        assert catalog.spec(name).machine
    # Release names spell no environment, so the MSVC row shares windows-arm64.
    others = {TargetCatalog.release_name(row) for row in TARGET_ROWS if not row.compiler_host} - names
    assert others == {"android-arm64", "android-x64", "ios-arm64"}
    for name in others:
        with pytest.raises(ValueError, match="unsupported bundle target"):
            catalog.spec(name)
    for (system, machine), _codes, label in HOST_SEAM:
        if label is None:
            continue
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("src.compiler.python.artifacts.archive.platform.system", lambda system=system: system)
            patch.setattr("src.compiler.python.artifacts.archive.platform.machine", lambda machine=machine: machine)
            assert catalog.host_target() == TargetCatalog.release_name(_row(label))
