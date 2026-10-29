"""The Windows launch seam in the runtime's separately compiled windows_os.c (CL-P2-02).

docs/design/windows-os-services.md ("Process and shell", "Selection unit")
specifies it: the runtime manifest's ``[[external_objects]]`` row binds the
SDK-free declaration sections of windows_os.h to windows_os.c, which every
build driver links whole when an emitted unit retains one of them.

On every host this test proves the object builds under the strict C11 flags
for x64 and ARM64 Windows and for the host, that the portable quoting entry
produces exactly the command line CommandLineToArgvW splits back into the
original argv, that a launch off Windows reports an unsupported host, and
that the manifest's selection follows retained code, never a comment or a
string literal. It also builds the native harness
(src/tests/native/windows_launch/launch_harness.c); with
BTRC_WIN32_EVIDENCE_DIR set the executables are copied there and windows.yml's
process-native job runs them on Windows x64 and ARM64, where the harness
checks quoting, exit codes, tree-killing deadlines and explicit terminates,
inherited-handle isolation, capture limits, stdin, refusals, PATH and
environment rules.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import RUN_TIMEOUT, TOOL_TIMEOUT
from tools.compiler_codegen.runtime import RuntimeManifest, RuntimeManifestError
from tools.native_plan import RuntimeObjects

REPO = Path(__file__).resolve().parents[3]
RUNTIME = REPO / "src" / "runtime" / "c"
NATIVE = REPO / "src" / "tests" / "native" / "windows_launch"
TARGETS = {"windows-x64": "x86_64-windows-gnu", "windows-arm64": "aarch64-windows-gnu"}
STRICT = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
PASS_LINE = "windows-launch-seam PASS checks="


def zig_compile(target: str, sources: list[Path], output: Path, *libraries: str) -> None:
    built = subprocess.run(
        [
            shutil.which("zig"),
            "cc",
            "-target",
            TARGETS[target],
            *STRICT,
            "-I",
            str(RUNTIME),
            *(str(source) for source in sources),
            "-o",
            str(output),
            *libraries,
        ],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, built.stderr


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> Path:
    """windows_os.c's portable entries, built for this host."""
    output = tmp_path_factory.mktemp("quote-probe") / "quote_probe"
    built = subprocess.run(
        [
            *configured_c_compiler(),
            *STRICT,
            "-I",
            str(RUNTIME),
            str(NATIVE / "quote_probe.c"),
            str(RUNTIME / "windows_os.c"),
            "-o",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    return output


def split_command_line(line: str) -> list[str]:
    """CommandLineToArgvW's documented split: argv[0] takes no escapes; later
    arguments end at unquoted spaces or tabs, 2n backslashes before a quote
    give n and toggle quoting, 2n+1 give n and a literal quote, and other
    backslashes are literal."""
    arguments: list[str] = []
    index = 0
    if line.startswith('"'):
        end = line.index('"', 1)
        arguments.append(line[1:end])
        index = end + 1
    else:
        while index < len(line) and line[index] not in " \t":
            index += 1
        arguments.append(line[:index])
    while True:
        while index < len(line) and line[index] in " \t":
            index += 1
        if index >= len(line):
            return arguments
        current: list[str] = []
        quoted = False
        while index < len(line):
            character = line[index]
            if character == "\\":
                run = index
                while run < len(line) and line[run] == "\\":
                    run += 1
                count = run - index
                if run < len(line) and line[run] == '"':
                    current.append("\\" * (count // 2))
                    if count % 2:
                        current.append('"')
                        index = run + 1
                    else:
                        index = run
                else:
                    current.append("\\" * count)
                    index = run
                continue
            if character == '"':
                if quoted and index + 1 < len(line) and line[index + 1] == '"':
                    current.append('"')
                    index += 2
                    continue
                quoted = not quoted
                index += 1
                continue
            if character in " \t" and not quoted:
                break
            current.append(character)
            index += 1
        arguments.append("".join(current))


def quote(probe: Path, arguments: list[str | bytes]) -> str:
    completed = subprocess.run([str(probe), *arguments], capture_output=True, timeout=RUN_TIMEOUT, check=False)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.decode("ascii")


def decode(output: str) -> str:
    units, nul = output.splitlines()
    assert nul == "nul=0"
    return bytes.fromhex(units).decode("utf-16-be") if units else ""


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_runtime_object_builds_strictly_for_windows(target, tmp_path):
    zig_compile(target, [RUNTIME / "windows_os.c"], tmp_path / "windows_os.o", "-c")


ROUND_TRIPS = [
    ["program", "a b"],
    ["program", 'q"x'],
    ["program", ""],
    ["program", "tail\\"],
    ["program", 'a\\\\"b'],
    ["program", "\\\\server\\share\\"],
    ["program", "tab\there", "new\nline", "vertical\vtab"],
    ["program", "trailing space ", " leading space"],
    ["program", "two\\\\", "back\\slash"],
    ["program", '"', '\\"', '""'],
    ["program", "x", "", "y"],
    ["C:\\Program Files\\tool\\tool.exe", "--flag=value with spaces"],
    ["program", "\u00e9", "\u4e2d\u6587", "\U0001f600"],
    ["program", "plain-ascii", "--long-option=1"],
]


@pytest.mark.parametrize("arguments", ROUND_TRIPS, ids=lambda arguments: repr(arguments[1:])[:40])
def test_quoting_round_trips_through_command_line_to_argv(probe, arguments):
    line = decode(quote(probe, arguments))
    assert split_command_line(line) == arguments


def test_quoting_is_the_canonical_form(probe):
    line = decode(quote(probe, ["p", "a b", 'q"x', "", "tail\\", "end space\\", 'a\\"b', "plain"]))
    # A bare argument keeps its backslashes; a quoted one doubles those before its closing quote.
    assert line == '"p" "a b" "q\\"x" "" tail\\ "end space\\\\" "a\\\\\\"b" plain'


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (['a"b', "x"], "error stage=1 code=3"),
        (["p", "a" * 40000], "error stage=1 code=4"),
        (["p", b"\xff"], "error stage=2 code=2"),
        (["p", b"\xed\xa0\x80"], "error stage=2 code=2"),
        (["p", b"\xc0\xaf"], "error stage=2 code=2"),
    ],
    ids=["quoted-program", "too-long", "invalid-byte", "surrogate", "overlong"],
)
def test_quoting_refuses_what_cannot_round_trip(probe, arguments, expected):
    assert quote(probe, arguments).strip() == expected


def test_a_launch_off_windows_reports_an_unsupported_host(probe):
    assert quote(probe, ["--launch"]).strip() == "launch=1 owner=null stage=15 domain=4 wait=1 close=0"


def test_supervisor_off_windows_clears_outputs_and_preserves_copy_buffer(probe):
    assert quote(probe, ["--supervisor"]).strip() == (
        "accept=1 owner=null copy=1 prepare=1 commit=1 ack=1 delivered=0 "
        "spawn=1 poll=1 running=0 code=0 terminate=1 "
        "required=0 output=165 stage=15 domain=4 close=0"
    )


def test_runtime_object_builds_strictly_for_the_host(probe):
    assert probe.is_file()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('"C:\\app.exe" --btrc-daemon-bootstrap-v1 4 8', "0 10 4 8"),
        ('"C:\\space \U0001f600\\app.exe" --btrc-daemon-bootstrap-v1 8 16', "0 19 8 16"),
        ('"app" --btrc-daemon-bootstrap-v1 0 8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 04 8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 +4 8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 -4 8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 4', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 18446744073709551616', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 18446744073709551615', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 8 ', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 8 extra', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4  8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4\t8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v2 4 8', "-1 0 0 0"),
        ('"app" --btrc-daemon-bootstrap-v1 4 8\0', "-1 0 0 0"),
        ('"app\0" --btrc-daemon-bootstrap-v1 4 8', "-1 0 0 0"),
        ('"app\n" --btrc-daemon-bootstrap-v1 4 8', "-1 0 0 0"),
        ('"" --btrc-daemon-bootstrap-v1 4 8', "-1 0 0 0"),
        ("app --btrc-daemon-bootstrap-v1 4 8", "-1 0 0 0"),
        ('"' + "a" * 32767 + '" --btrc-daemon-bootstrap-v1 4 8', "-1 0 0 0"),
    ],
)
def test_reserved_bootstrap_invocation_is_exact_and_clears_failed_outputs(probe, command, expected):
    completed = subprocess.run(
        [str(probe), "--bootstrap-invocation"],
        input=command.encode("utf-16-be").hex().encode("ascii"),
        capture_output=True,
        timeout=RUN_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.decode("ascii").strip() == expected


DECLARATION = (RUNTIME / "windows_os.h").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "selected"),
    [
        (DECLARATION, True),
        ("int main(void) { return __btrc_windows_launch_close(0, 0, 0); }", True),
        ('static const char *names[] = { "__btrc_windows_launch", "__btrc_windows_launch_wait" };', False),
        ("/* __btrc_windows_launch */ int main(void) { return 0; } // __btrc_windows_launch_wait", False),
        ("typedef int __btrc_windows_launch_types_t; int __btrc_windows_launchers;", False),
        ("int main(void) { return 0; }", False),
    ],
    ids=["declarations", "call", "string-literals", "comments", "longer-identifiers", "unrelated"],
)
def test_runtime_objects_follow_retained_code(text, selected):
    rows = RuntimeObjects.selected([text])
    assert [row.source for row in rows] == (["windows_os.c"] if selected else [])


def test_runtime_object_libraries_are_per_operating_system():
    rows = RuntimeObjects.selected([DECLARATION])
    assert RuntimeObjects.library_flags(rows, "windows") == ["-lkernel32", "-ladvapi32"]
    assert RuntimeObjects.library_flags(rows, "linux") == []
    assert RuntimeObjects.sources(rows) == [RUNTIME / "windows_os.c"]


@pytest.fixture
def runtime_copy(tmp_path) -> Path:
    copy = tmp_path / "c"
    shutil.copytree(RUNTIME, copy)
    return copy


def test_manifest_refuses_a_declaration_section_that_defines(runtime_copy):
    header = runtime_copy / "windows_os.h"
    header.write_text(
        header.read_text(encoding="utf-8").replace(
            "    __btrc_windows_launch_owner_t **out, __btrc_windows_launch_error_t *error);",
            "    __btrc_windows_launch_owner_t **out, __btrc_windows_launch_error_t *error) { return 0; }",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeManifestError, match="defines a function"):
        RuntimeManifest.load(runtime_copy / "manifest.toml")


def test_manifest_refuses_an_object_that_does_not_include_its_declarations(runtime_copy):
    source = runtime_copy / "windows_os.c"
    source.write_text(source.read_text(encoding="utf-8").replace('#include "windows_os.h"', "", 1), encoding="utf-8")
    with pytest.raises(RuntimeManifestError, match="must include its declarations"):
        RuntimeManifest.load(runtime_copy / "manifest.toml")


def test_manifest_refuses_an_unknown_library_system(runtime_copy):
    manifest = runtime_copy / "manifest.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('os = ["windows"]', 'os = ["plan9"]', 1), encoding="utf-8"
    )
    with pytest.raises(RuntimeManifestError, match="unknown systems"):
        RuntimeManifest.load(manifest)


def test_the_windows_harness_exercises_every_seam_section():
    """Every declaration section of windows_os.h is used by the launch harness the Windows runners execute:
    the type section through its records, each entry point by a call. Only a windows-gnu build retains
    these sections, so no host corpus program can pin them (test_platform_inventory's target-only rows)."""
    harness = (NATIVE / "launch_harness.c").read_text(encoding="utf-8")
    uses = {
        "__btrc_windows_launch_types": (
            "__btrc_windows_launch_owner_t",
            "__btrc_windows_launch_options_t",
            "__btrc_windows_launch_error_t",
            "__btrc_windows_launch_result_t",
        ),
        "__btrc_windows_launch": ("__btrc_windows_launch(",),
        "__btrc_windows_launch_wait": ("__btrc_windows_launch_wait(",),
        "__btrc_windows_launch_copy_output": ("__btrc_windows_launch_copy_output(",),
        "__btrc_windows_launch_terminate": ("__btrc_windows_launch_terminate(",),
        "__btrc_windows_launch_close": ("__btrc_windows_launch_close(",),
        "__btrc_windows_quote_argv_utf8": ("__btrc_windows_quote_argv_utf8(",),
        "__btrc_windows_supervisor_types": ("__btrc_windows_supervisor_owner",),
        "__btrc_windows_supervisor_accept": ("__btrc_windows_supervisor_accept(",),
        "__btrc_windows_supervisor_copy_startup": ("__btrc_windows_supervisor_copy_startup(",),
        "__btrc_windows_supervisor_prepare": ("__btrc_windows_supervisor_prepare(",),
        "__btrc_windows_supervisor_ready_wait_commit": ("__btrc_windows_supervisor_ready_wait_commit(",),
        "__btrc_windows_supervisor_ack": ("__btrc_windows_supervisor_ack(",),
        "__btrc_windows_supervisor_spawn_managed": ("__btrc_windows_supervisor_spawn_managed(",),
        "__btrc_windows_supervisor_poll_managed": ("__btrc_windows_supervisor_poll_managed(",),
        "__btrc_windows_supervisor_terminate_managed": ("__btrc_windows_supervisor_terminate_managed(",),
        "__btrc_windows_supervisor_close": ("__btrc_windows_supervisor_close(",),
    }
    manifest = RuntimeManifest.load(RUNTIME / "manifest.toml")
    declared = {helper.name for helper in manifest.helpers if helper.asset == "windows_os.h"}
    assert set(uses) == declared
    for section, spellings in uses.items():
        for spelling in spellings:
            assert spelling in harness, f"{section}: the harness never uses {spelling}"


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_launch_harness_builds_for_windows(target, tmp_path):
    executable = tmp_path / f"windows-launch-seam-{target}.exe"
    zig_compile(target, [NATIVE / "launch_harness.c", RUNTIME / "windows_os.c"], executable, "-lshell32", "-ladvapi32")
    assert executable.read_bytes()[:2] == b"MZ"
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
    if sys.platform == "win32":
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=600, check=False)
        last = ran.stdout.strip().splitlines()[-1] if ran.stdout.strip() else ""
        assert ran.returncode == 0 and last.startswith(PASS_LINE), (ran.stdout, ran.stderr)
