"""The target predefined-macro table (src/language/targets.toml) against C compilers.

``#if`` evaluates a target macro from the table before C compilation, so the
table must say exactly what the C compiler of that target will define
(docs/design/c-preprocessor-conditionals.md, test 3, and
docs/design/platform-target-contract.md §1.3). For each spec row, clang's
``-dM`` dump for the row's triple must define exactly the table names and
undefined names the table selects, with the table's values; the host's gcc
must agree on its own target. The names left out on purpose must stay out of
the table.

Two checks are Mac-bound (MAC-P1-05): Apple clang must agree with the portable
``TARGET_OS_*`` table for the four Apple rows, with every vendor-only extra
explicitly classified as foreign in the shared spec, and the iOS SDK's
``<TargetConditionals.h>`` must accept the predefined values. They run on the
acceptance Mac, whose Xcode build the design pins, and are classified skips
everywhere else.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import (
    TARGET_FOREIGN_MACRO_NAMES,
    TARGET_PREDEFINED_MACRO_ROWS,
    TARGET_ROWS,
    TARGET_UNDEFINED_MACRO_NAMES,
)
from src.compiler.python.frontend.packages import PackageTarget
from src.tests.c_toolchains import HOST_CLANG, HOST_GCC
from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.native_import_fixtures import apple_environment

# Left out on purpose (c-preprocessor-conditionals.md, "Left out on purpose",
# and platform-target-contract.md §1.3, "Still left out"): toolchain or
# invocation identity, CPU features and header-defined names. #if refuses
# each one as reserved.
LEFT_OUT = (
    "__GNUC__",
    "__OBJC_BOOL_IS_BOOL",
    "__OPTIMIZE__",
    "__STDC_HOSTED__",
    "__STDC_NO_THREADS__",
    "__STRICT_ANSI__",
    "__WIN32__",
    "__WINNT__",
    "__clang__",
    "__gnu_linux__",
    "_INTEGRAL_MAX_BITS",
    "_MSC_BUILD",
    "_MSC_EXTENSIONS",
    "_MSC_FULL_VER",
    "_MSC_VER",
    "__MSVCRT__",
)

# The Xcode build that Apple's checks are pinned to (platform-target-contract.md
# §1.3), and the operating systems whose rows it covers.
APPLE_XCODE_BUILD = "27A266a"
APPLE_OPERATING_SYSTEMS = ("ios", "macos")
# §1.3 checks the predefined values against the iOS SDK's <TargetConditionals.h>.
IOS_SDK = "iphoneos"
APPLE_TARGET_NAME = re.compile(r"TARGET_(?:OS_[A-Z0-9_]+|IPHONE_SIMULATOR)\Z")
# Predefined by clang on Apple targets but never by GCC.
CLANG_ONLY = frozenset({"__ENVIRONMENT_OS_VERSION_MIN_REQUIRED__"})

_DEFINE = re.compile(r"#define ([A-Za-z_][A-Za-z0-9_]*) (.*)\Z")
_INTEGER = re.compile(r"([0-9]+)[uUlL]*\Z")


def _row(label: str):
    return next(row for row in TARGET_ROWS if row.label == label)


def _unwrapped_clang() -> str | None:
    """The clang binary itself, not nix's cc-wrapper.

    The wrapper adds host flags (its -fPIC makes clang refuse the msvc
    environment) and warns on every foreign --target; its
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


def _predefines(command: list[str], *, environment: dict[str, str] | None = None) -> dict[str, int | None]:
    """Every macro the compiler predefines, with its integer value (None when not an integer).

    An object-like alias (``__BYTE_ORDER__`` is ``__ORDER_LITTLE_ENDIAN__``,
    ``__ANDROID_API__`` is ``__ANDROID_MIN_SDK_VERSION__``) resolves through
    the dump, and integer suffixes are stripped.
    """

    completed = subprocess.run(
        [*command, "-std=c11", "-dM", "-E", "-x", "c", "-"],
        input="",
        capture_output=True,
        text=True,
        check=False,
        timeout=C_COMPILE_TIMEOUT,
        env=environment,
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
    target = _row(label)
    rows = [
        (row.name, row.value)
        for row in TARGET_PREDEFINED_MACRO_ROWS
        if (not row.operating_systems or target.operating_system in row.operating_systems)
        and (not row.architectures or target.architecture in row.architectures)
        and (not row.environments or target.environment in row.environments)
    ]
    selected = dict(rows)
    assert len(selected) == len(rows), f"{label}: two rows select one name"
    return selected


def _checked_names() -> set[str]:
    return {row.name for row in TARGET_PREDEFINED_MACRO_ROWS} | set(TARGET_UNDEFINED_MACRO_NAMES)


def _assert_agrees(label: str, predefined: dict[str, int | None], names: set[str] | None = None) -> None:
    names = _checked_names() if names is None else names
    expected = {name: value for name, value in _selected(label).items() if name in names}
    defined = {name: predefined[name] for name in names if name in predefined}
    assert defined == expected, f"{label}: compiler {defined!r} != table {expected!r}"


def _apple_labels() -> tuple[str, ...]:
    return tuple(row.label for row in TARGET_ROWS if row.operating_system in APPLE_OPERATING_SYSTEMS)


def _apple_toolchain() -> str | None:
    """Why the Mac-bound checks cannot run here, or None on the acceptance Mac's Xcode."""

    reason = f"Mac-bound: requires macOS with xcrun and Xcode {APPLE_XCODE_BUILD} (MAC-P1-05)"
    if platform.system() != "Darwin" or shutil.which("/usr/bin/xcrun") is None:
        return reason
    completed = subprocess.run(
        ["/usr/bin/xcrun", "xcodebuild", "-version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=C_COMPILE_TIMEOUT,
        env=apple_environment(),
    )
    build = re.search(r"Build version (\S+)", completed.stdout)
    if completed.returncode != 0 or build is None or build.group(1) != APPLE_XCODE_BUILD:
        return f"{reason}; this host has {build.group(1) if build else 'no Xcode'}"
    return None


def _xcrun(sdk: str, *arguments: str) -> list[str]:
    return ["/usr/bin/xcrun", "--sdk", sdk, *arguments]


def test_apple_toolchain_uses_selected_xcode_when_shell_points_to_nix(monkeypatch):
    monkeypatch.setenv("DEVELOPER_DIR", "/nix/store/apple-sdk")
    monkeypatch.setenv("SDKROOT", "/nix/store/apple-sdk/MacOSX.sdk")
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shutil, "which", lambda name: name)

    def run(command, **options):
        assert command == ["/usr/bin/xcrun", "xcodebuild", "-version"]
        assert not {"DEVELOPER_DIR", "SDKROOT"} & options["env"].keys()
        return subprocess.CompletedProcess(command, 0, f"Xcode 27.0\nBuild version {APPLE_XCODE_BUILD}\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert _apple_toolchain() is None


def test_every_spec_row_has_a_clang_triple() -> None:
    assert len(TARGET_ROWS) == 11
    for row in TARGET_ROWS:
        assert row.target_arguments == (f"--target={row.triple}",), row.label


def test_left_out_names_stay_out_of_the_table() -> None:
    assert not set(LEFT_OUT) & _checked_names()


@pytest.mark.parametrize("label", tuple(row.label for row in TARGET_ROWS))
def test_clang_defines_exactly_the_selected_table_rows(label: str) -> None:
    clang = _unwrapped_clang()
    if clang is None:
        pytest.skip("requires clang to dump each target's predefined macros")
    _assert_agrees(label, _predefines([clang, *_row(label).target_arguments]))


@pytest.mark.parametrize("label", tuple(row.label for row in TARGET_ROWS))
def test_clang_maps_every_triple_alias_to_the_row_triple(label: str) -> None:
    clang = _unwrapped_clang()
    if clang is None:
        pytest.skip("requires clang to print each target's cc1 triple")
    row = _row(label)
    for spelling in (row.triple, *row.triple_aliases):
        completed = subprocess.run(
            [clang, f"--target={spelling}", "-###", "-c", "-x", "c", "-"],
            input="",
            capture_output=True,
            text=True,
            check=False,
            timeout=C_COMPILE_TIMEOUT,
        )
        assert completed.returncode == 0, completed.stderr
        assert f'"-triple" "{row.triple}"' in completed.stderr, f"{spelling}: {completed.stderr}"


def test_host_gcc_agrees_on_its_own_target() -> None:
    if HOST_GCC is None:
        pytest.skip("requires the host gcc to dump its predefined macros")
    try:
        host = PackageTarget.parse(None)
    except ValueError:
        pytest.skip("requires a host that is a btrc target")
    label = next(
        row.label
        for row in TARGET_ROWS
        if row.compiler_host and (row.operating_system, row.architecture) == (host.operating_system, host.architecture)
    )
    # GCC predefines none of clang's Apple-only names: the TARGET_OS_* set
    # (clang's -fdefine-target-os-macros) and __ENVIRONMENT_OS_VERSION_MIN_REQUIRED__.
    # test_clang_defines_exactly_the_selected_table_rows checks those on every row.
    names = {name for name in _checked_names() if name not in CLANG_ONLY and not APPLE_TARGET_NAME.match(name)}
    _assert_agrees(label, _predefines([HOST_GCC]), names)


@pytest.mark.parametrize("label", _apple_labels())
def test_apple_clang_defines_the_table_target_os_set(label: str) -> None:
    reason = _apple_toolchain()
    if reason is not None:
        pytest.skip(reason)
    row = _row(label)
    predefined = _predefines(_xcrun(row.sysroot_name, "clang", *row.target_arguments), environment=apple_environment())
    # Every Apple name must be accounted for by the shared spec. Vendor-only
    # names are explicitly foreign, so btrc refuses to evaluate or redefine
    # them; any new, unclassified Apple name still fails this comparison.
    names = {
        name
        for name in _checked_names() | set(predefined)
        if APPLE_TARGET_NAME.fullmatch(name) and name not in TARGET_FOREIGN_MACRO_NAMES
    }
    _assert_agrees(label, predefined, names)


def test_apple_target_os_check_rejects_unclassified_vendor_names(monkeypatch):
    label = _apple_labels()[0]
    predefined = _selected(label) | {"TARGET_OS_UNCLASSIFIED": 1}
    monkeypatch.setattr(sys.modules[__name__], "_apple_toolchain", lambda: None)
    monkeypatch.setattr(sys.modules[__name__], "_predefines", lambda *args, **kwargs: predefined)
    with pytest.raises(AssertionError, match="TARGET_OS_UNCLASSIFIED"):
        test_apple_clang_defines_the_table_target_os_set(label)


@pytest.mark.parametrize("label", _apple_labels())
def test_target_conditionals_header_accepts_the_predefined_values(label: str, tmp_path: Path) -> None:
    reason = _apple_toolchain()
    if reason is not None:
        pytest.skip(reason)
    row = _row(label)
    selected = {name: value for name, value in _selected(label).items() if APPLE_TARGET_NAME.fullmatch(name)}
    probe = tmp_path / "conditionals.c"
    probe.write_text(
        "#include <TargetConditionals.h>\n"
        + "".join(f'_Static_assert({name} == {value}, "{name}");\n' for name, value in sorted(selected.items()))
    )
    completed = subprocess.run(
        [*_xcrun(IOS_SDK, "clang"), *row.target_arguments, "-std=c11", "-fsyntax-only", str(probe)],
        env=apple_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=C_COMPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr
