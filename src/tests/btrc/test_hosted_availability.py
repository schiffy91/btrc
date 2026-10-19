"""The hosted-ABI availability check in both optimizers (Stage 24 commit 2b).

platform-target-contract.md §2.4: once the reachability graph is final, every
hosted name the surviving code takes must be one the target row declares
(``[[platform_targets]]`` in ``hosted_abi.toml``). The reference that sorts
first by (owner, name) fails the compile, with one message and exit status 1
in both compilers. Dead-code elimination runs first, so an unreachable
reference compiles, and a C4 branch the row does not take is never seen; with
``--no-dce`` every reference counts, as in C. Under ``--module-units`` the
workers report their units' references and only the owner process refuses.

Every compile stops at C: no C compiler, sysroot or SDK is involved, so every
row runs on any host.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import HOSTED_PLATFORM_UNAVAILABLE
from src.compiler.python.abi.hosted import HOSTED_ABI

REPO = Path(__file__).resolve().parents[3]
TIMEOUT = 300
TARGETS = ("linux-x86_64", "windows-x86_64", "ios-aarch64", "android-aarch64")


@dataclass(frozen=True)
class Probe:
    """A hosted name some rows lack, and the body of a function that calls it."""

    name: str
    header: str
    body: str

    def program(self, main: str = "return probe();", guard: str | None = None) -> str:
        """``probe`` calls the name, unless ``guard`` holds; ``main`` is main's body."""

        body = f"    {self.body}\n"
        if guard is not None:
            body = f"#if {guard}\n    return 0;\n#else\n{body}#endif\n"
        return f"#include <{self.header}>\nint probe() {{\n{body}}}\nint main() {{\n    {main}\n}}\n"


PROBES = {
    probe.name: probe
    for probe in (
        Probe("arc4random_uniform", "stdlib.h", "return (int)arc4random_uniform(1);"),
        Probe("fork", "unistd.h", "int pid = fork();\n    return pid < 0 ? 1 : 0;"),
        Probe(
            "clock_settime",
            "time.h",
            "struct timespec now;\n    now.tv_sec = 0;\n    now.tv_nsec = 0;\n"
            "    return clock_settime((clockid_t)CLOCK_REALTIME, &now);",
        ),
        Probe("explicit_bzero", "string.h", "char buffer[4];\n    explicit_bzero(buffer, 4);\n    return 0;"),
    )
}
# The probes each row's extracted table refuses (§2.5's spot names): glibc's
# 2.31 floor has no arc4random, MinGW has no fork or explicit_bzero, the iOS
# SDK marks clock_settime unavailable, and NDK r29 bionic has no
# explicit_bzero at any API level. Every other probe compiles on the row.
REFUSED = {
    "linux-x86_64": {"arc4random_uniform"},
    "windows-x86_64": {"arc4random_uniform", "explicit_bzero", "fork"},
    "ios-aarch64": {"clock_settime", "explicit_bzero"},
    "android-aarch64": {"explicit_bzero"},
}
# A C4 condition only the row itself takes.
GUARDS = {
    "linux-x86_64": "defined(__linux__) && !defined(__ANDROID__)",
    "windows-x86_64": "defined(_WIN32)",
    "ios-aarch64": "defined(__APPLE__)",
    "android-aarch64": "defined(__ANDROID__)",
}


def message(name: str, target: str, owner: str) -> str:
    return f"error: '{name}' is not available on target {target} (hosted ABI); referenced from {owner}\n"


@dataclass(frozen=True)
class Outcome:
    """One compiler's run and the C file it was asked to write."""

    result: subprocess.CompletedProcess[str]
    output: Path


class Frontends:
    """Both compilers' command lines over one set of source files."""

    def __init__(self, btrcc: Path, root: Path) -> None:
        self.btrcc = btrcc
        self.root = root
        self.compiles = 0

    def compile(self, files: dict[str, str], target: str, *flags: str, cache: Path | None = None) -> dict[str, Outcome]:
        """Compile Main.btrc through each compiler in a fresh directory.

        With ``cache``, the directory is the same for every call, since a
        module unit's record is keyed by its group's path.
        """

        self.compiles += 1
        results = {}
        for frontend in ("reference", "selfhost"):
            directory = self.root / ("cached" if cache is not None else str(self.compiles)) / frontend
            directory.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                (directory / name).write_text(text)
            arguments = [*flags, "--target", target, "-o", str(directory / "Main.c")]
            if "--module-units" in flags:
                arguments.extend(("--emit-units", str(directory / "units")))
            if cache is None:
                arguments.insert(0, "--no-cache")
            environment = {**os.environ, "BTRC_HOME": str(REPO / "src")}
            if cache is not None:
                environment["BTRC_CACHE_DIR"] = str(cache / frontend)
            command = (
                [sys.executable, "-m", "src.compiler.python.main", str(directory / "Main.btrc"), *arguments]
                if frontend == "reference"
                else [str(self.btrcc), *arguments, str(directory / "Main.btrc")]
            )
            result = subprocess.run(
                command,
                cwd=REPO if frontend == "reference" else directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
            results[frontend] = Outcome(result, directory / "Main.c")
        return results


@pytest.fixture
def frontends(immutable_btrcc: Path, tmp_path: Path) -> Frontends:
    return Frontends(immutable_btrcc, tmp_path)


def assert_refused(outcomes: dict[str, Outcome], expected: str) -> None:
    for frontend, outcome in outcomes.items():
        assert (outcome.result.returncode, outcome.result.stderr) == (1, expected), frontend
        assert not outcome.output.exists(), frontend


def assert_compiled(outcomes: dict[str, Outcome]) -> None:
    for frontend, outcome in outcomes.items():
        assert outcome.result.returncode == 0, (frontend, outcome.result.stderr)
        assert outcome.output.is_file(), frontend


# -- The tables the check reads ---------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_refused_probes_are_exactly_the_rows_unavailable_names(target: str) -> None:
    unavailable = HOSTED_ABI.platform_unavailable_names(target)
    assert {name for name in PROBES if name in unavailable} == REFUSED[target]


def test_a_label_without_a_table_refuses_nothing() -> None:
    assert HOSTED_ABI.platform_unavailable_names("") == frozenset()


@pytest.mark.parametrize("label", sorted(HOSTED_PLATFORM_UNAVAILABLE))
def test_each_row_lacks_a_name_in_every_kind_it_has_or_in_none(label: str) -> None:
    """The check reads one set per row, which is exact only while §2.3's single identifier set holds."""

    row = HOSTED_PLATFORM_UNAVAILABLE[label]
    platform = {
        "functions": HOSTED_ABI.platform_function_names,
        "macros": HOSTED_ABI.platform_macro_names,
        "objects": HOSTED_ABI.platform_object_names,
        "types": HOSTED_ABI.platform_type_names,
        "typedefs": HOSTED_ABI.platform_typedef_names,
    }
    mixed = sorted(
        (name, kind)
        for name in HOSTED_ABI.platform_unavailable_names(label)
        for kind, names in platform.items()
        if name in names and name not in getattr(row, kind)
    )
    assert mixed == []


# -- Reachable, unreachable and guarded references ---------------------------


@pytest.mark.parametrize("name", sorted(PROBES))
@pytest.mark.parametrize("target", TARGETS)
def test_a_reachable_reference_is_refused_only_where_the_row_lacks_it(
    target: str, name: str, frontends: Frontends
) -> None:
    results = frontends.compile({"Main.btrc": PROBES[name].program()}, target)
    if name in REFUSED[target]:
        assert_refused(results, message(name, target, "probe"))
    else:
        assert_compiled(results)


@pytest.mark.parametrize("target", TARGETS)
def test_an_unreachable_reference_compiles_and_no_dce_refuses_it(target: str, frontends: Frontends) -> None:
    name = sorted(REFUSED[target])[0]
    program = {"Main.btrc": PROBES[name].program(main="return 0;")}
    assert_compiled(frontends.compile(program, target))
    assert_refused(frontends.compile(program, target, "--no-dce"), message(name, target, "probe"))


@pytest.mark.parametrize("target", TARGETS)
def test_a_reference_in_a_branch_the_row_does_not_take_compiles(target: str, frontends: Frontends) -> None:
    name = sorted(REFUSED[target])[0]
    program = {"Main.btrc": PROBES[name].program(guard=GUARDS[target])}
    assert_compiled(frontends.compile(program, target))
    assert_compiled(frontends.compile(program, target, "--no-dce"))


def test_a_branch_for_another_row_does_not_guard_the_reference(frontends: Frontends) -> None:
    program = {"Main.btrc": PROBES["fork"].program(guard=GUARDS["linux-x86_64"])}
    assert_compiled(frontends.compile(program, "linux-x86_64"))
    assert_refused(frontends.compile(program, "windows-x86_64"), message("fork", "windows-x86_64", "probe"))


def test_a_row_that_declares_every_name_compiles_them_all(frontends: Frontends) -> None:
    """linux-x86_64 declares fork, clock_settime and explicit_bzero: one program reaching all three compiles."""

    names = sorted(set(PROBES) - REFUSED["linux-x86_64"])
    headers = "".join(f"#include <{PROBES[name].header}>\n" for name in names)
    functions = "".join(f"int probe_{index}() {{\n    {PROBES[name].body}\n}}\n" for index, name in enumerate(names))
    calls = " + ".join(f"probe_{index}()" for index in range(len(names)))
    program = {"Main.btrc": f"{headers}{functions}int main() {{\n    return {calls};\n}}\n"}
    assert_compiled(frontends.compile(program, "linux-x86_64", "--no-dce"))


# -- What counts as a reference ----------------------------------------------


def test_identifiers_types_and_global_initializers_count(frontends: Frontends) -> None:
    target = "windows-x86_64"
    macro = "#include <signal.h>\nint main() {\n    return SIGKILL > 0 ? 0 : 1;\n}\n"
    assert_refused(frontends.compile({"Main.btrc": macro}, target), message("SIGKILL", target, "main"))
    typedef = "#include <sys/types.h>\nint main() {\n    blksize_t size = 0;\n    return (int)size;\n}\n"
    assert_refused(frontends.compile({"Main.btrc": typedef}, target), message("blksize_t", target, "main"))
    initialized = "#include <signal.h>\nint signals = SIGKILL;\nint main() {\n    return signals > 0 ? 0 : 1;\n}\n"
    assert_refused(frontends.compile({"Main.btrc": initialized}, target), message("SIGKILL", target, "signals"))


def test_a_local_or_parameter_that_binds_the_name_is_not_a_reference(frontends: Frontends) -> None:
    program = (
        "int probe(int fork) {\n    return fork;\n}\n"
        "int main() {\n    int explicit_bzero = 3;\n    return probe(explicit_bzero - 3);\n}\n"
    )
    assert_compiled(frontends.compile({"Main.btrc": program}, "windows-x86_64", "--no-dce"))


def test_the_first_reference_by_owner_then_name_is_reported(frontends: Frontends) -> None:
    """zeta is defined first, but alpha sorts first, and within alpha SIGKILL sorts before explicit_bzero."""

    program = (
        "#include <signal.h>\n#include <string.h>\n#include <unistd.h>\n"
        "int zeta() {\n    int pid = fork();\n    return pid < 0 ? 1 : 0;\n}\n"
        "int alpha() {\n    char buffer[4];\n    explicit_bzero(buffer, 4);\n    return SIGKILL;\n}\n"
        "int main() {\n    return zeta() + alpha();\n}\n"
    )
    expected = message("SIGKILL", "windows-x86_64", "alpha")
    assert_refused(frontends.compile({"Main.btrc": program}, "windows-x86_64"), expected)
    assert_refused(frontends.compile({"Main.btrc": program}, "windows-x86_64", "--module-units"), expected)


# -- Stdlib reachability ------------------------------------------------------


def test_an_unused_stdlib_import_that_names_unavailable_symbols_compiles(frontends: Frontends) -> None:
    program = {"Main.btrc": "import Library.Process;\nint main() {\n    return 0;\n}\n"}
    assert_compiled(frontends.compile(program, "windows-x86_64"))


def test_both_compilers_agree_on_a_reached_stdlib_provider(frontends: Frontends) -> None:
    """The POSIX child-process provider: refused on windows until its Win32 provider lands (Stage 26)."""

    program = {
        "Main.btrc": (
            "import Library.Process;\nimport Library.Vector;\n"
            'int main() {\n    Vector<string> arguments = [];\n    ChildProcess.run("/bin/true", arguments);\n'
            "    return 0;\n}\n"
        )
    }
    outcomes = frontends.compile(program, "windows-x86_64")
    reference, selfhost = outcomes["reference"].result, outcomes["selfhost"].result
    assert (reference.returncode, reference.stderr) == (selfhost.returncode, selfhost.stderr)
    if reference.returncode != 0:
        assert reference.stderr.startswith("error: '"), reference.stderr
        assert "' is not available on target windows-x86_64 (hosted ABI); referenced from " in reference.stderr


# -- Module units -------------------------------------------------------------


MODULE_PROGRAM = {
    "Main.btrc": "import ./Probe.btrc;\nint main() {\n    return probe();\n}\n",
    "Probe.btrc": "#include <unistd.h>\nint probe() {\n    int pid = fork();\n    return pid < 0 ? 1 : 0;\n}\n",
}


def test_module_units_refuse_in_the_owner_with_the_whole_program_message(frontends: Frontends) -> None:
    expected = message("fork", "windows-x86_64", "probe")
    assert_refused(frontends.compile(MODULE_PROGRAM, "windows-x86_64"), expected)
    assert_refused(frontends.compile(MODULE_PROGRAM, "windows-x86_64", "--module-units"), expected)
    assert_refused(frontends.compile(MODULE_PROGRAM, "windows-x86_64", "--module-units", "--no-dce"), expected)
    assert_compiled(frontends.compile(MODULE_PROGRAM, "linux-x86_64", "--module-units"))


def test_a_refused_unit_is_never_stored_so_a_warm_build_refuses_again(frontends: Frontends, tmp_path: Path) -> None:
    expected = message("fork", "windows-x86_64", "probe")
    for _ in range(2):
        assert_refused(
            frontends.compile(MODULE_PROGRAM, "windows-x86_64", "--module-units", cache=tmp_path / "cache"),
            expected,
        )


def test_module_units_refuse_what_a_unit_emits(frontends: Frontends) -> None:
    """A unit keeps its exported functions, since other units may call them.

    Whole-program DCE drops the uncalled probe and compiles; Probe.btrc's
    unit still defines it, so its C names fork and the compile is refused,
    as that unit's C compile for the row would fail.
    """

    program = {**MODULE_PROGRAM, "Main.btrc": "import ./Probe.btrc;\nint main() {\n    return 0;\n}\n"}
    assert_compiled(frontends.compile(program, "windows-x86_64"))
    assert_refused(
        frontends.compile(program, "windows-x86_64", "--module-units"), message("fork", "windows-x86_64", "probe")
    )
