"""The Winsock HTTPSocket provider through both compilers, for x64 and ARM64.

src/stdlib/HTTP/Windows/ is selected only on windows rows (the package
manifest's provider for HTTPSocket). Its C is spliced into the program, not
bound, and resolves ws2_32 at run time, so compiling for a windows row needs
zig's MinGW-w64 headers but no native header reader and no import library.
This driver compiles src/tests/native/http_windows/WindowsHttpCases.btrc with
the reference compiler and btrcc for windows-x64 and windows-arm64, requires
both to splice the provider's C and to carry platform adaptations row 6's
warning byte for byte, and links each under the strict C11 flags with the
runtime object the emitted C retains (Library.Process launches curl.exe for
the client case) and ws2_32 for the cases' own peer. It also bundles the HTTP
corpus through both compilers with the target runner. When
BTRC_WIN32_EVIDENCE_DIR is set, the executables and bundles are copied there
and windows.yml's win32-native job runs them on a Windows runner of each
architecture; on Windows itself the test runs the cases. Elsewhere it proves
the selection, the generated C and the link, not the execution.

It also pins what the provider must leave alone: every other row compiles
exactly the BSD-socket bodies, with no Winsock C, and every Winsock value
and layout the provider spells itself (it includes no Winsock header) equals
MinGW's own winsock2.h declaration on each architecture.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT
from src.tests.target_runner import FRONTENDS, TargetBundle, TargetCorpusRunner
from tools.native_plan import RuntimeObjects, TargetToolchain

REPO = Path(__file__).resolve().parents[3]
CASES = REPO / "src/tests/native/http_windows/WindowsHttpCases.btrc"
PROVIDER_C = "src/stdlib/HTTP/Windows/Win32Sockets.c"
PEER_C = "src/tests/native/http_windows/WinsockPeer.c"
ROWS = {row.label: row for row in TARGET_ROWS}
TARGETS = {"windows-x64": "windows-x86_64", "windows-arm64": "windows-aarch64"}
STRICT = ["-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
ADAPTATIONS = REPO / "docs/design/platform-adaptations.md"
# Every case the program runs; curl-client may report a classified skip where
# no curl.exe is on PATH.
CASE_NAMES = (
    "lifecycle",
    "exclusive-port",
    "bind-any-warning",
    "accept-timeout",
    "split-request",
    "chunked-split",
    "body-limit",
    "slow-peer",
    "send-backpressure",
    "reset-peer",
    "response-framing",
    "bodyless-status",
    "binary-body",
    "stale-descriptor",
    "close-wakes-wait",
    "curl-client",
    "released",
)
SKIPPABLE = frozenset({"curl-client"})
# The HTTP corpus and each program's Windows verdict (target-applicability.toml).
CORPUS = ("stdlib/Http*.btrc",)
WINDOWS_CORPUS = {
    "stdlib/Http.btrc": "built",
    "stdlib/HttpBytesResponse.btrc": "restricted",
    "stdlib/HttpClientLocal.btrc": "built",
    "stdlib/HttpFramingSafety.btrc": "built",
    "stdlib/HttpListenerPort.btrc": "built",
    "stdlib/HttpParseBytes.btrc": "built",
    "stdlib/HttpParseEdges.btrc": "built",
    "stdlib/HttpSocketIo.btrc": "restricted",
    "stdlib/HttpUtil.btrc": "built",
}
PROBE = """import Library.HTTP.HTTPResponse;
import Library.HTTP.HTTPServer;

int main() {
	HTTPServer server = HTTPServer(0);
	if (!server.start()) { return 1; }
	int connection = server.acceptConn();
	server.respond(connection, HTTPResponse.text("probe"));
	server.closeConn(connection);
	server.stop();
	return 0;
}
"""


def row_six_warning() -> str:
    """Platform adaptations row 6's Windows warning, as the document spells it."""

    text = ADAPTATIONS.read_text(encoding="utf-8")
    match = re.search(r"When bound to all interfaces, a warning \(not a failure\): `([^`]+)`", text)
    assert match is not None, "platform-adaptations.md no longer states the Windows row 6 warning"
    return match[1]


def transpile_reference(source: Path, label: str) -> str:
    result = Compiler().compile(
        source.read_text(encoding="utf-8"),
        str(source),
        CompilerOptions(use_cache=False, use_ast_cache=False, target=label),
    )
    assert result.failure is None, result.failure
    assert result.analyzed is None or not result.analyzed.errors, result.analyzed.errors
    assert result.c_source is not None
    return result.c_source


def transpile_selfhost(btrcc: Path, source: Path, label: str) -> str:
    completed = subprocess.run(
        [str(btrcc), "--no-cache", "--target", label, str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def build(c_source: str, label: str, executable: Path, work: Path) -> None:
    """The target runner's build: the generated unit with the Windows overlay,
    each retained runtime object as its own unit, one link; plus ws2_32,
    which only the cases' own peer (WinsockPeer.c) links."""

    toolchain = TargetToolchain(ROWS[label])
    generated = work / f"{executable.stem}.c"
    generated.write_text(c_source, encoding="utf-8")
    objects = [work / f"{executable.stem}.o"]
    commands = [toolchain.compile_command(generated, objects[0], generated=True, flags=STRICT)]
    rows = RuntimeObjects.selected([c_source])
    for index, source in enumerate(RuntimeObjects.sources(rows)):
        objects.append(work / f"{executable.stem}.runtime-{index}.o")
        commands.append(toolchain.compile_command(source, objects[-1], generated=False, flags=STRICT))
    commands.append(
        [
            *toolchain.drivers["cc"],
            *toolchain.arguments,
            *(str(path) for path in objects),
            *RuntimeObjects.library_flags(rows, ROWS[label].operating_system),
            *toolchain.runtime_libraries(),
            "-lws2_32",
            "-o",
            str(executable),
        ]
    )
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert completed.returncode == 0, completed.stderr


def check_output(stdout: str, stderr: str) -> None:
    """The program's report: every case once, ok or a classified skip, then
    PASS; and on stderr only row 6's warning, once, for the one
    all-interfaces listener."""

    lines = [line for line in stdout.replace("\r", "").split("\n") if line]
    assert lines and lines[-1] == "PASS: windows http cases", lines
    reported = {}
    for line in lines[:-1]:
        name, _, verdict = line.removeprefix("case=").partition(" ")
        assert line.startswith("case=") and name not in reported, line
        reported[name] = verdict
    assert tuple(reported) == CASE_NAMES, reported
    for name, verdict in reported.items():
        assert verdict == "ok" or (name in SKIPPABLE and verdict.startswith("skipped ")), (name, verdict)
    assert [line for line in stderr.replace("\r", "").split("\n") if line] == [row_six_warning()], stderr


@pytest.fixture(scope="module")
def zig() -> str:
    found = shutil.which("zig")
    if found is None:
        pytest.skip("requires zig, which cross-compiles the windows rows (the dev shell provides it)")
    return found


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_both_frontends_build_the_windows_http_cases(frontend, target, zig, request, tmp_path):
    label = TARGETS[target]
    if frontend == "reference":
        c_source = transpile_reference(CASES, label)
    else:
        c_source = transpile_selfhost(request.getfixturevalue("immutable_btrcc"), CASES, label)
    spliced = c_source.replace("\\", "/")
    assert f'{PROVIDER_C}"' in spliced and f'{PEER_C}"' in spliced
    assert row_six_warning() in c_source, "the all-interfaces warning is platform adaptations row 6's, byte for byte"
    assert [row.source for row in RuntimeObjects.selected([c_source])] == ["windows_os.c"]
    executable = tmp_path / f"windows-http-cases-{frontend}-{target}.exe"
    build(c_source, label, executable, tmp_path)
    assert executable.read_bytes()[:2] == b"MZ"
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
    if sys.platform == "win32":
        ran = subprocess.run(
            [str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT * 4, check=False
        )
        assert ran.returncode == 0, (ran.stdout, ran.stderr)
        check_output(ran.stdout, ran.stderr)


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_http_corpus_builds_for_windows_through_both_frontends(target, immutable_btrcc, tmp_path):
    """The target runner's compile-only bundle; windows.yml's win32-native job
    runs it with the windows-native executor against the same goldens."""

    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    bundle = Path(evidence) / f"http-corpus-{target}" if evidence else tmp_path / "bundle"
    runner = TargetCorpusRunner(
        TARGETS[target], FRONTENDS, output=tmp_path / "run", bundle=bundle, btrcc=immutable_btrcc, programs=CORPUS
    )
    report = runner.run(compile_only=True)
    assert not report.failed, [outcome.as_dict() for outcome in report.outcomes if outcome.status == "failed"]
    statuses = {
        (entry["source"], entry["frontend"]): entry["status"] for entry in TargetBundle.load(bundle).programs.values()
    }
    assert statuses == {
        (source, frontend): status for source, status in WINDOWS_CORPUS.items() for frontend in FRONTENDS
    }


@pytest.mark.parametrize("label", ["linux-x86_64", "macos-aarch64", "ios-aarch64", "android-aarch64"])
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_other_rows_compile_no_winsock_c(frontend, label, request, tmp_path):
    """The provider is selected for windows rows only: elsewhere the package's
    BSD-socket bodies compile and no Winsock C is spliced in."""

    probe = tmp_path / "Probe.btrc"
    probe.write_text(PROBE, encoding="utf-8")
    if frontend == "reference":
        source = transpile_reference(probe, label)
    else:
        source = transpile_selfhost(request.getfixturevalue("immutable_btrcc"), probe, label)
    assert "Win32Sockets.c" not in source and "btrcWinSocket" not in source and "httpWinsockRegistry" not in source
    for posix in ("poll(", "accept(", "shutdown(", "MSG_NOSIGNAL"):
        assert posix in source, posix


@pytest.mark.parametrize("label", sorted(TARGETS.values()))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_windows_rows_compile_no_bsd_socket_bodies(frontend, label, request, tmp_path):
    """The MinGW rows splice the Winsock provider. The MSVC row stays missing:
    Library.Timer's monotonic clock, which every deadline here reads, has no
    MSVC body yet."""

    probe = tmp_path / "Probe.btrc"
    probe.write_text(PROBE, encoding="utf-8")
    if frontend == "reference":
        source = transpile_reference(probe, label)
    else:
        source = transpile_selfhost(request.getfixturevalue("immutable_btrcc"), probe, label)
    assert f'{PROVIDER_C}"' in source.replace("\\", "/")
    for posix in ("poll(", "fcntl(", "SHUT_RDWR", "SHUT_WR", "MSG_NOSIGNAL", "<sys/socket.h>", "<poll.h>"):
        assert posix not in source, posix


def sdk_assertions_compile(zig: str, target: str, directory: Path, name: str, headers: str, checks: str) -> None:
    """One translation unit of _Static_asserts over MinGW's own headers."""

    unit = directory / f"{name}.c"
    unit.write_text(f"#include <stddef.h>\n{headers}\n{checks}\nint main(void) {{ return 0; }}\n", encoding="utf-8")
    built = subprocess.run(
        [zig, "cc", "-target", ROWS[TARGETS[target]].zig_target, "-std=c11", *STRICT]
        + ["-c", str(unit), "-o", str(directory / f"{name}.o")],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
        check=False,
    )
    assert built.returncode == 0, (name, built.stderr)


# The provider's spelling of each Winsock value, and the SDK name it stands for.
WINSOCK_VALUES = {
    "BTRC_WIN_AF_INET": "AF_INET",
    "BTRC_WIN_SOCK_STREAM": "SOCK_STREAM",
    "BTRC_WIN_IPPROTO_TCP": "IPPROTO_TCP",
    "BTRC_WIN_SOL_SOCKET": "SOL_SOCKET",
    "BTRC_WIN_SO_EXCLUSIVEADDRUSE": "SO_EXCLUSIVEADDRUSE",
    "BTRC_WIN_WSA_FLAG_NO_HANDLE_INHERIT": "WSA_FLAG_NO_HANDLE_INHERIT",
    "BTRC_WIN_FD_READ": "FD_READ",
    "BTRC_WIN_FD_WRITE": "FD_WRITE",
    "BTRC_WIN_FD_ACCEPT": "FD_ACCEPT",
    "BTRC_WIN_FD_CLOSE": "FD_CLOSE",
    "BTRC_WIN_FD_MAX_EVENTS": "FD_MAX_EVENTS",
    "BTRC_WIN_SD_SEND": "SD_SEND",
    "BTRC_WIN_SOCKET_ERROR": "SOCKET_ERROR",
}


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_the_winsock_values_the_provider_names_are_the_sdk_declarations(target, zig, tmp_path):
    """Win32Sockets.c includes no Winsock header, so it spells the few values
    and layouts it needs; each must equal MinGW's winsock2.h on each
    architecture."""

    provider = (REPO / PROVIDER_C).read_text(encoding="utf-8")
    defined = set(re.findall(r"^#define (BTRC_WIN_[A-Z_]+) ", provider, re.MULTILINE))
    assert set(WINSOCK_VALUES) <= defined, set(WINSOCK_VALUES) - defined
    checks = [f'_Static_assert({ours} == {theirs}, "{ours}");' for ours, theirs in WINSOCK_VALUES.items()]
    checks += [
        '_Static_assert(BTRC_WIN_INVALID_SOCKET == (uintptr_t)INVALID_SOCKET, "INVALID_SOCKET");',
        '_Static_assert(sizeof(SOCKET) == sizeof(uintptr_t), "SOCKET is pointer-width");',
        '_Static_assert(sizeof(BtrcWinSocketAddress) == sizeof(struct sockaddr_in), "sockaddr_in size");',
        '_Static_assert(offsetof(BtrcWinSocketAddress, family) == offsetof(struct sockaddr_in, sin_family), "family");',
        '_Static_assert(offsetof(BtrcWinSocketAddress, port) == offsetof(struct sockaddr_in, sin_port), "port");',
        '_Static_assert(offsetof(BtrcWinSocketAddress, address) == offsetof(struct sockaddr_in, sin_addr), "address");',
        '_Static_assert(sizeof(BtrcWinNetworkEvents) == sizeof(WSANETWORKEVENTS), "WSANETWORKEVENTS size");',
        '_Static_assert(offsetof(BtrcWinNetworkEvents, events) == offsetof(WSANETWORKEVENTS, lNetworkEvents), "events");',
        '_Static_assert(offsetof(BtrcWinNetworkEvents, errors) == offsetof(WSANETWORKEVENTS, iErrorCode), "errors");',
        '_Static_assert(sizeof(BtrcWinSocketStartupData) >= sizeof(WSADATA), "room for WSADATA");',
    ]
    headers = f'#include <winsock2.h>\n#include <ws2tcpip.h>\n#include "{REPO / PROVIDER_C}"'
    sdk_assertions_compile(zig, target, tmp_path, "winsock-values", headers, "\n".join(checks))


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("before", ["#include <windows.h>", "#include <winsock2.h>", ""])
def test_the_provider_compiles_whatever_the_program_included_first(before, target, zig, tmp_path):
    """The provider's C lands wherever the program's other C put windows.h,
    whose winsock.h refuses a later winsock2.h: it includes neither."""

    sdk_assertions_compile(zig, target, tmp_path, "order", f'{before}\n#include "{REPO / PROVIDER_C}"', "")


def test_the_report_checker_accepts_only_complete_reports():
    good = "\n".join([*(f"case={name} ok" for name in CASE_NAMES), "PASS: windows http cases"])
    warning = row_six_warning() + "\r\n"
    check_output(good, warning)
    check_output(good.replace("case=curl-client ok", "case=curl-client skipped no curl.exe on PATH"), warning)
    for broken, stderr in (
        (good.replace("case=lifecycle ok", "case=lifecycle skipped no"), warning),
        (good.replace("case=released ok\n", ""), warning),
        (good.replace("PASS: windows http cases", ""), warning),
        (good, ""),
        (good, warning + warning),
    ):
        with pytest.raises(AssertionError):
            check_output(broken, stderr)
