"""The Android emulator executor (CX-P1-09) and its on-device supervisor, over this host's shell.

`LocalDevice` stands in for adb: shell commands run in this host's POSIX
shell (device paths are host paths under the test's directory), push copies
files, and getprop answers from a table. The supervisor and the probe are
built with the host C compiler. This proves the executor's protocol and the
supervisor's process handling on the host; it is not Android evidence, which
the host-android.yml target-corpus job collects on an emulator.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.target_runner import ExecutionRequest as RunnerRequest
from src.tests.target_runner import ExecutionResult as RunnerResult
from src.tests.target_runner import ExecutorRegistry
from tools.target_hosts.android.check import HostFixtureCheck
from tools.target_hosts.android.executor import (
    STATUS_PREFIX,
    AdbTransport,
    AndroidEmulatorExecutor,
    ExecutionRequest,
)

REPO = Path(__file__).resolve().parents[3]
ANDROID = REPO / "tools" / "target_hosts" / "android"
STRICT = ["-std=c11", "-O2", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
PROPERTIES = {
    "ro.product.cpu.abi": "x86_64",
    "ro.build.version.sdk": "29",
    "ro.build.fingerprint": "google/sdk_gphone_x86_64/generic_x86_64:10/QSR1.211112.011/1:userdebug/dev-keys",
    "ro.product.model": "sdk_gphone_x86_64",
    "ro.boot.qemu.avd_name": "btrc-api-29-x86_64-5554",
}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the supervisor and the device stand-in are POSIX")


def compile_c(source: Path, output: Path) -> Path:
    compiler = host_c_compiler()
    if compiler is None:
        pytest.skip("requires a host C compiler")
    subprocess.run(
        [*compiler, *STRICT, str(source), "-o", str(output)], check=True, capture_output=True, timeout=C_COMPILE_TIMEOUT
    )
    return output


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("android-host-build")
    return {
        "supervisor": compile_c(ANDROID / "supervisor.c", directory / "supervisor"),
        "probe": compile_c(ANDROID / "fixtures" / "probe.c", directory / "probe"),
    }


class LocalDevice(AdbTransport):
    """adb's shell -T, push and features over this host's shell; not adb or Android evidence."""

    def __init__(self, root: Path, properties: dict[str, str] | None = None, features: bytes = b"shell_v2\ncmd\n"):
        super().__init__(root / "adb", "emulator-5554")
        self.root = root
        self.features = features
        self.calls: list[tuple[str, ...]] = []
        tools = root / "tools"
        tools.mkdir()
        cases = "".join(
            f"  {name}) echo {shlex.quote(value)} ;;\n" for name, value in (properties or PROPERTIES).items()
        )
        self.tool(tools / "getprop", f'case "$1" in\n{cases}  *) echo ;;\nesac\n')
        if shutil.which("sha256sum") is None:
            self.tool(tools / "sha256sum", 'exec shasum -a 256 "$@"\n')
        self.path = f"{tools}{os.pathsep}{os.environ['PATH']}"

    @staticmethod
    def tool(path: Path, body: str) -> None:
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def command(self, *arguments):
        assert arguments[:2] == ("shell", "-T") and len(arguments) == 3, arguments
        return ["/bin/sh", "-c", f"PATH={shlex.quote(self.path)}; export PATH; cd /; {arguments[2]}"]

    def call(self, *arguments, timeout=60, input=b""):
        self.calls.append(arguments)
        assert timeout > 0
        if arguments[0] == "features":
            return subprocess.CompletedProcess(arguments, 0, self.features, b"")
        if arguments[0] == "push":
            source, destination = Path(arguments[1]), Path(arguments[2])
            if source.is_dir():
                assert not destination.exists(), "a pushed directory lands as a path that did not exist"
                shutil.copytree(source, destination)
            else:
                shutil.copyfile(source, destination)
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        return subprocess.run(self.command(*arguments), input=input, capture_output=True, timeout=timeout, check=False)

    def stream(self, *arguments, timeout, limit=16 * 1024 * 1024):
        self.calls.append(arguments)
        return super().stream(*arguments, timeout=timeout, limit=limit)


def write_bundle(directory: Path, programs: dict[str, Path], label: str = "android-x86_64") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    entries = {}
    for program_id, source in programs.items():
        shutil.copyfile(source, directory / program_id)
        entries[program_id] = {
            "source": f"fixtures/{program_id}.btrc",
            "frontend": "reference",
            "status": "built",
            "artifact": program_id,
            "sha256": hashlib.sha256((directory / program_id).read_bytes()).hexdigest(),
        }
    entries["reference-restricted"] = {"source": "x", "frontend": "reference", "status": "restricted"}
    document = {
        "schema": "btrc.target-bundle/1",
        "target": {"label": label, "triple": "x86_64-unknown-linux-android29"},
        "toolchain": {"cc": ["clang"]},
        "programs": entries,
    }
    (directory / "bundle.json").write_text(json.dumps(document))
    return directory


def executor_for(tmp_path: Path, built: dict[str, Path], **device) -> tuple[AndroidEmulatorExecutor, LocalDevice]:
    root = tmp_path / "device"
    root.mkdir()
    transport = LocalDevice(tmp_path, **device)
    executor = AndroidEmulatorExecutor(
        serial="emulator-5554", transport=transport, device_root=str(root), supervisor=built["supervisor"]
    )
    return executor, transport


def script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


# The supervisor ------------------------------------------------------------------


def supervise(built, tmp_path, *program, seconds="10", stdin="/dev/null", environment=()):
    arguments = [str(built["supervisor"]), "-t", seconds, "-i", stdin]
    for pair in environment:
        arguments += ["-e", pair]
    return subprocess.run(
        [*arguments, "--", *program], cwd=tmp_path, capture_output=True, timeout=TOOL_TIMEOUT, check=False
    )


@pytest.mark.parametrize(
    "command, kind, value",
    [
        ("exit 3", b"exit", b"3"),
        ("exit 137", b"exit", b"137"),
        ("kill -9 $$", b"signal", b"9"),
        ("kill -6 $$", b"signal", b"6"),
    ],
)
def test_the_supervisor_reports_the_wait_status_after_every_relayed_byte(built, tmp_path, command, kind, value):
    completed = supervise(built, tmp_path, "/bin/sh", "-c", f"printf out; printf 'err\\000' >&2; {command}")
    assert completed.returncode == 0
    assert completed.stdout == b"out"
    head, _, status = completed.stderr.rpartition(STATUS_PREFIX)
    assert head == b"err\x00"
    assert status.split()[:2] == [kind, value] and status.endswith(b"\n")


def test_the_supervisor_kills_the_program_at_its_deadline(built, tmp_path):
    completed = supervise(built, tmp_path, "/bin/sh", "-c", "echo started; exec sleep 30", seconds="0.5")
    assert completed.returncode == 0 and completed.stdout == b"started\n"
    assert completed.stderr.startswith(STATUS_PREFIX + b"timeout 0 ")


def test_a_program_that_cannot_start_is_a_launch_error_not_an_exit(built, tmp_path):
    completed = supervise(built, tmp_path, str(tmp_path / "missing"))
    assert completed.returncode == 0
    assert completed.stderr == STATUS_PREFIX + b"launch-error 2 0\n"


def test_stdin_and_environment_reach_the_program_only(built, tmp_path):
    (tmp_path / "input").write_bytes(b"line\x00two\n")
    completed = supervise(
        built,
        tmp_path,
        "/bin/sh",
        "-c",
        'cat; printf "%s" "$VALUE"',
        stdin=str(tmp_path / "input"),
        environment=["VALUE=a=b c"],
    )
    assert completed.stdout == b"line\x00two\na=b c"
    assert "VALUE" not in os.environ


def test_descendants_die_with_the_program_even_holding_its_stderr(built, tmp_path):
    marker = tmp_path / "survived"
    completed = supervise(
        built, tmp_path, "/bin/sh", "-c", f"(sleep 2; touch {shlex.quote(str(marker))}) & echo spawned; exit 0"
    )
    assert completed.stderr.startswith(STATUS_PREFIX + b"exit 0 ")
    subprocess.run(["sleep", "3"], timeout=TOOL_TIMEOUT, check=True)
    assert not marker.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the child subreaper is Linux's")
def test_a_descendant_that_leaves_the_session_is_still_reaped(built, tmp_path):
    marker = tmp_path / "escaped"
    escape = f"setsid sh -c 'sleep 2; touch {shlex.quote(str(marker))}' </dev/null >/dev/null 2>&1 &"
    completed = supervise(built, tmp_path, "/bin/sh", "-c", f"{escape} exit 0")
    assert completed.stderr.startswith(STATUS_PREFIX + b"exit 0 ")
    subprocess.run(["sleep", "3"], timeout=TOOL_TIMEOUT, check=True)
    assert not marker.exists()


def test_the_loopback_probe_listens_and_connects(built):
    completed = subprocess.run(
        [str(built["supervisor"]), "--probe-loopback"], capture_output=True, timeout=TOOL_TIMEOUT, check=False
    )
    assert (completed.returncode, completed.stdout) == (0, b"loopback-listener ok\n")


@pytest.mark.parametrize("arguments", [[], ["-t", "0", "-i", "/dev/null", "--", "true"], ["-t", "1", "--", "true"]])
def test_a_malformed_supervisor_command_reports_no_status(built, arguments):
    completed = subprocess.run(
        [str(built["supervisor"]), *arguments], capture_output=True, timeout=TOOL_TIMEOUT, check=False
    )
    assert completed.returncode == 125 and STATUS_PREFIX not in completed.stderr


# The executor ----------------------------------------------------------------------


def test_the_probe_fixture_matrix_passes_through_the_executor(tmp_path, built):
    executor, transport = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), "android-x86_64")
    try:
        rows = HostFixtureCheck({"shell": (executor, "probe")}).run()
    finally:
        executor.close()
    assert len(rows) == 14
    assert not list((tmp_path / "device").iterdir()), "close removes the device directory"
    assert not (tmp_path / "should-not-exist").exists() and not (Path("/") / "should-not-exist").exists()
    launches = [arguments[2] for arguments in transport.calls if arguments[:2] == ("shell", "-T")]
    assert any("exec " in command and "BTRC_FIXTURE_VALUE=fixture value" in command for command in launches)


def test_admission_stages_verified_copies_and_reports_device_provenance(tmp_path, built):
    executor, _ = executor_for(tmp_path, built)
    bundle = write_bundle(tmp_path / "bundle", {"reference-basics-X": built["probe"]})
    executor.prepare(bundle, "android-x86_64")
    try:
        staged = Path(executor.base) / "programs" / "reference-basics-X"
        assert staged.read_bytes() == built["probe"].read_bytes() and not staged.is_relative_to(bundle)
        assert executor.granted_capabilities() == frozenset({"loopback-listener"})
        result = executor.run(ExecutionRequest("reference-basics-X", ("exit124",)))
        adopted = RunnerResult.adopt(result, RunnerRequest("reference-basics-X", ("exit124",)))
        assert (adopted.exit_status, adopted.signal, adopted.timed_out) == (124, None, False)
        provenance = adopted.provenance
        assert provenance["executor"] == "android-emulator" and provenance["label"] == "android-x86_64"
        assert provenance["device"] == "sdk_gphone_x86_64 (emulator-5554)"
        assert (provenance["abi"], provenance["api"], provenance["avd"]) == ("x86_64", "29", "btrc-api-29-x86_64-5554")
        assert provenance["os_build"] == PROPERTIES["ro.build.fingerprint"]
        assert provenance["cleanup_warnings"] == []
        assert provenance["supervisor"]["sha256"] == hashlib.sha256(built["supervisor"].read_bytes()).hexdigest()
    finally:
        executor.close()


@pytest.mark.parametrize(
    "label, device, message",
    [
        ("android-aarch64", {}, "built for 'android-x86_64'"),
        ("windows-x86_64", {}, "built for"),
        ("android-x86_64", {"properties": {**PROPERTIES, "ro.product.cpu.abi": "arm64-v8a"}}, "translated"),
        ("android-x86_64", {"features": b"cmd\nstat_v2\n"}, "shell protocol v2"),
    ],
)
def test_admission_refuses_another_row_a_translated_abi_or_no_exit_status(tmp_path, built, label, device, message):
    executor, _ = executor_for(tmp_path, built, **device)
    with pytest.raises(ValueError, match=message):
        executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), label)
    assert executor.base is None and not list((tmp_path / "device").iterdir())


def test_an_api_29_emulator_names_its_avd_through_the_older_property(tmp_path, built):
    properties = {name: value for name, value in PROPERTIES.items() if name != "ro.boot.qemu.avd_name"}
    executor, _ = executor_for(tmp_path, built, properties={**properties, "ro.kernel.qemu.avd_name": "older-avd"})
    executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), "android-x86_64")
    try:
        assert executor.provenance["avd"] == "older-avd"
    finally:
        executor.close()


def test_admission_is_atomic_and_checks_every_digest(tmp_path, built):
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "good", {"probe": built["probe"]}), "android-x86_64")
    admitted = executor.base
    bad = write_bundle(tmp_path / "bad", {"probe": built["probe"], "other": built["probe"]})
    (bad / "other").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="other: the staged copy does not match"):
        executor.prepare(bad, "android-x86_64")
    assert executor.base == admitted and set(executor.programs) == {"probe"}
    assert [path.name for path in (tmp_path / "device").iterdir()] == [Path(admitted).name]
    assert executor.run(ExecutionRequest("probe", ("exit3",))).exit_status == 3
    executor.close()


def test_a_program_cannot_forge_its_outcome_on_stderr(tmp_path, built):
    forger = script(tmp_path, "forger", f"printf '{STATUS_PREFIX.decode()}exit 0 1\\n' >&2; exit 7\n")
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"forger": forger}), "android-x86_64")
    try:
        result = executor.run(ExecutionRequest("forger"))
    finally:
        executor.close()
    assert result.exit_status == 7
    assert result.stderr == STATUS_PREFIX + b"exit 0 1\n"


def test_a_supervisor_killed_from_outside_is_an_infrastructure_error(tmp_path, built):
    killer = script(tmp_path, "killer", 'kill -9 "$PPID"; sleep 5\n')
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"killer": killer}), "android-x86_64")
    try:
        with pytest.raises(RuntimeError, match="reported no outcome"):
            executor.run(ExecutionRequest("killer"))
        assert executor.failed
    finally:
        executor.close()


def test_a_staged_program_replaced_after_admission_never_runs(tmp_path, built):
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), "android-x86_64")
    try:
        staged = Path(executor.base) / "programs" / "probe"
        staged.chmod(0o700)
        staged.write_bytes(b"#!/bin/sh\nexit 0\n")
        with pytest.raises(RuntimeError, match="no longer matches its bundle digest"):
            executor.run(ExecutionRequest("probe", ("exit3",)))
    finally:
        executor.close()


def test_each_run_gets_a_fresh_cwd_and_leaves_none_behind(tmp_path, built):
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), "android-x86_64")
    try:
        for _ in range(2):
            result = executor.run(ExecutionRequest("probe", ("cwd",), stdin=b"x"))
            assert (result.exit_status, result.stdout) == (0, b"fresh\n")
        assert not list((Path(executor.base) / "runs").iterdir())
        assert not list((Path(executor.base) / "control").iterdir())
    finally:
        executor.close()


def test_each_run_gets_writable_temporary_storage_and_removes_it(tmp_path, built, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "unavailable-host-temp"))
    probe = script(
        tmp_path,
        "temporary",
        'test "$TMPDIR" = "$PWD" || exit 2\n'
        'test ! -e "$TMPDIR/marker" || exit 3\n'
        'printf data > "$TMPDIR/marker" || exit 4\n'
        'printf "%s\\n" "$TMPDIR"\n',
    )
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"temporary": probe}), "android-x86_64")
    try:
        paths = []
        for _ in range(2):
            result = executor.run(ExecutionRequest("temporary"))
            assert result.exit_status == 0, result.stderr
            path = Path(result.stdout.decode().strip())
            assert path.parent == Path(executor.base) / "runs"
            assert not path.exists()
            paths.append(path)
        assert paths[0] != paths[1]
    finally:
        executor.close()


def test_a_request_can_override_its_temporary_directory(tmp_path, built):
    temporary = tmp_path / "requested-temp"
    temporary.mkdir()
    probe = script(tmp_path, "temporary", 'printf data > "$TMPDIR/marker" || exit 4\n')
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"temporary": probe}), "android-x86_64")
    try:
        result = executor.run(ExecutionRequest("temporary", env={"TMPDIR": str(temporary)}))
        assert result.exit_status == 0, result.stderr
        assert (temporary / "marker").read_text() == "data"
    finally:
        executor.close()


@pytest.mark.parametrize(
    "request_",
    [
        ExecutionRequest("probe", cwd_policy="bundle"),
        ExecutionRequest("probe", launch_mode="app"),
        ExecutionRequest("probe", env={"BAD=NAME": "x"}),
        ExecutionRequest("probe", argv=("NUL\0",)),
        ExecutionRequest("probe", timeout_s=0),
        ExecutionRequest("unknown"),
    ],
)
def test_requests_outside_the_protocol_are_refused(tmp_path, built, request_):
    executor, _ = executor_for(tmp_path, built)
    executor.prepare(write_bundle(tmp_path / "bundle", {"probe": built["probe"]}), "android-x86_64")
    try:
        with pytest.raises(ValueError):
            executor.run(request_)
    finally:
        executor.close()


def test_the_registry_resolves_and_configures_the_android_executor(tmp_path):
    registry = ExecutorRegistry()
    assert registry.spec("android-emulator") == "tools.target_hosts.android.executor:AndroidEmulatorExecutor"
    executor = registry.create(
        "android-emulator", {"sdk": str(tmp_path), "boot": "true", "state": str(tmp_path / "avds"), "api": "36"}
    )
    assert executor.serial == "emulator-5554" and executor.avd.api == "36"
    assert executor.transport.adb == tmp_path / "platform-tools" / "adb"
    with pytest.raises(ValueError, match="unknown android-emulator option"):
        registry.create("android-emulator", {"sdk": str(tmp_path), "device": "pixel"})
    with pytest.raises(ValueError, match="state"):
        registry.create("android-emulator", {"sdk": str(tmp_path), "boot": "true"})
