"""Windows HTTP selection, native plans and SDK-linked x64/ARM64 fixtures.

Cross builds prove compilation and linking. The Windows workflow runs both
frontends' executables and retains their output beside corpus results.
"""

from __future__ import annotations

import hashlib
import json
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
from src.tests.native_build import NativeCorpusBuild
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT
from src.tests.target_runner import FRONTENDS, TargetBundle, TargetCorpusRunner
from tools.native_plan import TargetToolchain

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


def transpile_native(frontend, source: Path, label: str, work: Path, request) -> NativeCorpusBuild:
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(use_cache=False, use_ast_cache=False, target=label),
        )
        assert result.failure is None, result.failure
        assert result.analyzed is None or not result.analyzed.errors, result.analyzed.errors
        return NativeCorpusBuild.publish(result, work)
    artifact = NativeCorpusBuild(work / "program.c", work / "program.json")
    completed = subprocess.run(
        [
            str(request.getfixturevalue("immutable_btrcc")),
            "--no-cache",
            "--target",
            label,
            str(source),
            "-o",
            str(artifact.primary),
            "--emit-link-plan",
            str(artifact.plan),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return artifact


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
    artifact = transpile_native(frontend, CASES, label, tmp_path, request)
    c_source = artifact.primary.read_text(encoding="utf-8")
    assert "Win32Sockets.c" not in c_source and "WinsockPeer.c" not in c_source
    assert row_six_warning() in c_source
    executable = tmp_path / f"windows-http-cases-{frontend}-{target}.exe"
    report = artifact.build(executable, compile_flags=STRICT)
    assert {str(REPO / PROVIDER_C), str(REPO / PEER_C)} <= {unit.source for unit in report.units}
    assert report.link_command.count("-lws2_32") == 1
    assert executable.read_bytes()[:2] == b"MZ"
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
    if sys.platform == "win32":
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT * 4, check=False)
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
    """The MinGW rows select the Winsock provider. The MSVC row stays missing:
    Library.Timer's monotonic clock, which every deadline here reads, has no
    MSVC body yet."""

    probe = tmp_path / "Probe.btrc"
    probe.write_text(PROBE, encoding="utf-8")
    if frontend == "reference":
        source = transpile_reference(probe, label)
    else:
        source = transpile_selfhost(request.getfixturevalue("immutable_btrcc"), probe, label)
    assert "Win32Sockets.c" not in source and "btrcWinSocketListen" in source
    for posix in ("poll(", "fcntl(", "SHUT_RDWR", "SHUT_WR", "MSG_NOSIGNAL", "<sys/socket.h>", "<poll.h>"):
        assert posix not in source, posix


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_native_failure_cleanup(target, zig, tmp_path):
    """Real SDK builds retain deterministic allocation/inheritance failure probes."""
    toolchain = TargetToolchain(ROWS[TARGETS[target]])
    source = REPO / "src/tests/native/http_windows/SocketFailures.c"
    object_path = tmp_path / "failures.o"
    executable = tmp_path / f"windows-http-failures-{target}.exe"
    commands = [
        toolchain.compile_command(source, object_path, generated=False, flags=STRICT),
        [*toolchain.drivers["cc"], *toolchain.arguments, str(object_path), "-lws2_32", "-o", str(executable)],
    ]
    for command in commands:
        built = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert built.returncode == 0, built.stderr
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
    if sys.platform == "win32":
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
        assert ran.returncode == 0 and ran.stdout == "PASS: Windows socket failures\n" and not ran.stderr, (
            ran.stdout,
            ran.stderr,
        )


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


@pytest.mark.skipif(sys.platform != "win32", reason="requires the real Windows native runner")
@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("fixture", ["reference", "selfhost", "failures"])
def test_preserved_native_executables_run(target, fixture):
    directory = Path(os.environ.get("BTRC_WIN32_EVIDENCE_DIR", "win32"))
    name = f"windows-http-failures-{target}" if fixture == "failures" else f"windows-http-cases-{fixture}-{target}"
    executable = (directory / f"{name}.exe").resolve()
    from tools.target_hosts.windows.bundle import TARGETS as WINDOWS_TARGETS
    from tools.target_hosts.windows.bundle import pe_machine
    from tools.target_hosts.windows.executor import WindowsNativeExecutor

    hardware = WindowsNativeExecutor.native_machine()
    executable_bytes = executable.read_bytes()
    assert pe_machine(executable_bytes) == hardware == WINDOWS_TARGETS[TARGETS[target]][1], (
        "native architecture mismatch"
    )
    report = REPO / "build/windows-http-native"
    report.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT * 4, check=False)
        stdout, stderr = result.stdout, result.stderr
        status = {"exit_status": result.returncode, "timed_out": False}
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        stdout = stdout.decode("utf-8", "replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
        status = {"exit_status": None, "timed_out": True}
    status.update(
        target=TARGETS[target], native_machine=hardware, executable_sha256=hashlib.sha256(executable_bytes).hexdigest()
    )
    (report / f"{name}.stdout").write_text(stdout, encoding="utf-8")
    (report / f"{name}.stderr").write_text(stderr, encoding="utf-8")
    (report / f"{name}.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    assert status["exit_status"] == 0 and not status["timed_out"], (status, stdout, stderr)
    if fixture == "failures":
        assert stdout == "PASS: Windows socket failures\n" and not stderr, (stdout, stderr)
    else:
        check_output(stdout, stderr)
