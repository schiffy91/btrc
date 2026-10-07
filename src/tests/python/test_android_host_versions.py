"""Android host version drift and executor transport contracts, without a device."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import struct
import subprocess
import sys
from pathlib import Path
from xml.dom import minidom

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from tools.target_hosts.android.avd import AvdManager
from tools.target_hosts.android.build import AndroidHostBuilder
from tools.target_hosts.android.executor import AndroidEmulatorExecutor, ExecutionRequest
from tools.target_hosts.android.sdk import SDKVersions

REPO = Path(__file__).resolve().parents[3]
ANDROID = REPO / "tools/target_hosts/android"


def test_sdkmanager_package_list_uses_the_integrator_pins():
    versions = SDKVersions()
    packages = versions.packages()
    assert len(packages) == len(set(packages))
    assert f"ndk;{versions.ndk}" in packages
    assert f"cmdline-tools;{versions.commandline}" in packages
    for api in versions.apis:
        assert f"platforms;android-{api}" in packages
        assert f"system-images;android-{api};google_apis;x86_64" in packages
    assert not any("ps16k" in name or "arm64" in name for name in packages)
    overlay = json.loads((REPO / "nix/android-repo-overlay.json").read_text())["packages"]
    for name, revision in (
        ("emulator", versions.emulator),
        ("platform-tools", versions.platform_tools),
        ("cmdline-tools", versions.commandline),
    ):
        assert overlay[name][revision]["revision"] == revision


def test_pin_change_updates_packages_and_cache_key(tmp_path):
    original = (REPO / "nix/platforms.nix").read_text()
    original_versions = SDKVersions()
    changed = tmp_path / "platforms.nix"
    changed.write_text(original.replace(f'ndkVersion = "{original_versions.ndk}"', 'ndkVersion = "99.0.123"'))
    current = SDKVersions(changed)
    assert "ndk;99.0.123" in current.packages()
    assert f"ndk;{original_versions.ndk}" not in current.packages()
    assert current.cache_key() != original_versions.cache_key()


def test_nonliteral_pin_cannot_silently_select_latest(tmp_path):
    path = tmp_path / "platforms.nix"
    path.write_text(
        (REPO / "nix/platforms.nix").read_text().replace('emulatorVersion = "37.2.12";', "emulatorVersion = latest;")
    )
    with pytest.raises(ValueError, match="emulatorVersion"):
        SDKVersions(path)


def test_installed_sdk_revisions_are_checked(tmp_path):
    versions = SDKVersions()
    directories = {
        "emulator": versions.emulator,
        "platform-tools": versions.platform_tools,
        f"cmdline-tools/{versions.commandline}": versions.commandline,
        f"ndk/{versions.ndk}": versions.ndk,
        **{f"build-tools/{version}": version for version in versions.build_tools},
    }
    for relative, revision in directories.items():
        path = tmp_path / relative / "source.properties"
        path.parent.mkdir(parents=True)
        path.write_text(f"Pkg.Revision = {revision}\n")
    for api in versions.apis:
        for relative in (
            f"platforms/android-{api}/android.jar",
            f"system-images/android-{api}/google_apis/x86_64/system.img",
        ):
            path = tmp_path / relative
            path.parent.mkdir(parents=True)
            path.touch()
    versions.verify(tmp_path)
    (tmp_path / "emulator/source.properties").write_text("Pkg.Revision = 99.0.0\n")
    with pytest.raises(ValueError, match="expected revision"):
        versions.verify(tmp_path)


@pytest.mark.parametrize("package", ["emulator", "platform-tools"])
def test_pinned_archive_keeps_sdk_registration_with_actual_revision(tmp_path, package):
    versions = SDKVersions()
    expected = {"emulator": versions.emulator, "platform-tools": versions.platform_tools}[package]
    directory = tmp_path / package
    directory.mkdir()
    (directory / "source.properties").write_text(f"Pkg.Revision={expected}\n")
    registration = f'''<repository xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xmlns:generic="http://schemas.android.com/repository/android/generic/02">
        <license id="android-sdk-license" type="text">original license</license>
        <localPackage path="{package}" obsolete="false">
        <type-details xsi:type="generic:genericDetailsType"/>
        <revision><major>99</major><minor>0</minor><micro>1</micro><preview>2</preview></revision>
        <dependencies><dependency path="future-package"/></dependencies>
        <display-name>Android tools</display-name><uses-license ref="android-sdk-license"/>
        </localPackage></repository>'''
    versions.register_archive(tmp_path, package, registration)
    document = minidom.parse(str(directory / "package.xml"))
    row = document.getElementsByTagName("localPackage")[0]
    assert row.getAttribute("path") == package
    revision = row.getElementsByTagName("revision")[0]
    assert (
        ".".join(revision.getElementsByTagName(part)[0].firstChild.data for part in ("major", "minor", "micro"))
        == expected
    )
    assert not revision.getElementsByTagName("preview")
    assert not row.getElementsByTagName("dependencies")
    assert document.documentElement.getAttribute("xmlns:generic").endswith("/generic/02")
    assert row.getElementsByTagName("type-details")[0].getAttribute("xsi:type") == "generic:genericDetailsType"
    assert document.getElementsByTagName("license")[0].firstChild.data == "original license"


def test_archive_registration_refuses_wrong_payload_and_identity(tmp_path):
    versions = SDKVersions()
    directory = tmp_path / "emulator"
    directory.mkdir()
    properties = directory / "source.properties"
    properties.write_text("Pkg.Revision=99.0.0\n")
    with pytest.raises(ValueError, match="expected revision"):
        versions.register_archive(tmp_path, "emulator", "<repository/>")
    properties.write_text(f"Pkg.Revision={versions.emulator}\n")
    with pytest.raises(ValueError, match="wrong package identity"):
        versions.register_archive(
            tmp_path, "emulator", '<repository><localPackage path="platform-tools"/></repository>'
        )
    assert not (directory / "package.xml").exists()


def test_gradle_wrapper_is_the_pinned_official_artifact():
    wrapper = ANDROID / "app/gradle/wrapper"
    assert (
        hashlib.sha256((wrapper / "gradle-wrapper.jar").read_bytes()).hexdigest()
        == "497c8c2a7e5031f6aa847f88104aa80a93532ec32ee17bdb8d1d2f67a194a9c7"
    )
    properties = (wrapper / "gradle-wrapper.properties").read_text()
    assert "gradle-9.6.0-bin.zip" in properties
    assert "distributionSha256Sum=bbaeb2fef8710818cf0e261201dab964c572f92b942812df0c3620d62a529a01" in properties


@pytest.mark.parametrize(
    "row",
    [
        "",
        "LOAD 0x000000 0x0 0x0 0x10 0x10 R E 0x1000",
        "LOAD 0x0 0x0 0x0 0x10 0x10 RW 0x4000\nLOAD 0x0 0x0 0x0 0x10 0x10 R 0x1000",
    ],
)
def test_alignment_check_rejects_any_small_load_segment(row):
    with pytest.raises(ValueError, match="LOAD"):
        AndroidHostBuilder.load_alignment(row)


def test_alignment_check_accepts_all_16k_or_larger_segments():
    AndroidHostBuilder.load_alignment(
        "LOAD 0x0 0x0 0x0 0x10 0x10 R E 0x4000\nLOAD 0x4000 0x4000 0x4000 0x10 0x10 RW 0x10000"
    )


def test_builder_cannot_claim_pinned_provenance_for_another_ndk(tmp_path):
    (tmp_path / "source.properties").write_text("Pkg.Revision = 99.0.0\n")
    with pytest.raises(ValueError, match=r"platforms\.nix revision"):
        AndroidHostBuilder(tmp_path, tmp_path / "output")


@pytest.mark.parametrize("api,port", [("1", 5554), ("29", 5555), ("29", 1)])
def test_avd_rejects_unpinned_apis_and_invalid_ports(tmp_path, api, port):
    with pytest.raises(ValueError):
        AvdManager(tmp_path, tmp_path / "state", api=api, port=port)


def test_avd_requires_kvm_before_spawning(tmp_path, monkeypatch):
    manager = AvdManager(tmp_path, tmp_path / "state")
    monkeypatch.setattr("tools.target_hosts.android.avd.os.access", lambda *_: False)
    with pytest.raises(RuntimeError, match="KVM"):
        manager.boot()
    assert manager.process is None


class FakeAdb:
    """Stateful shell-v2 transport model, not Android execution evidence."""

    def __init__(
        self,
        exit_status=0,
        *,
        app_timeout=False,
        signum=0,
        timed_out=False,
        shell_status=0,
        status_error=None,
        app_exit_status=3,
        pending_polls=0,
        fail_write=False,
        lingering_polls=0,
        uninstall_error=False,
        cleanup_uninstall_error=False,
        stop_error=False,
        install_error=False,
    ):
        self.calls = []
        self.exit_status = exit_status
        self.app_timeout = app_timeout
        self.signum, self.timed_out, self.shell_status = signum, timed_out, shell_status
        self.status_error = status_error
        self.app_exit_status = app_exit_status
        self.pending_polls = pending_polls
        self.fail_write = fail_write
        self.lingering_polls = lingering_polls
        self.uninstall_error = uninstall_error
        self.cleanup_uninstall_error = cleanup_uninstall_error
        self.stop_error = stop_error
        self.install_error = install_error
        self.installed = self.launched = False
        self.files = {}
        self.writes = {}
        self.status_polls = 0

    def __call__(self, command, **options):
        arguments = command[3:]
        self.calls.append((arguments, options))
        code, stdout, stderr = 0, b"", b""
        if arguments[:2] == ["shell", "-T"]:
            words = shlex.split(arguments[2])
            if words[0] == "cd":
                code, stdout = self.shell_status, b"stdout\x00bytes"
            else:
                assert words[:4] == ["run-as", "dev.btrc.testhost.fixture", "sh", "-c"]
                assert len(words) == 5 and self.installed
                script = words[4]
                if script.startswith("cat > files/"):
                    name = script.removeprefix("cat > files/")
                    assert name in ("request.bin", "stdin")
                    if self.fail_write:
                        code, stderr = 1, b"write failed"
                    else:
                        self.files[name] = self.writes[name] = options["input"]
                else:
                    match = re.fullmatch(r"if \[ ! -e files/([a-z_]+) \]; then exit 42; fi; cat files/\1", script)
                    assert match is not None, f"unknown remote script: {script}"
                    name = match[1]
                    assert self.launched
                    if name == "exit_status":
                        self.status_polls += 1
                        if self.status_error == "timeout":
                            raise subprocess.TimeoutExpired(command, options["timeout"])
                        if self.status_error in ("transport", "client"):
                            return subprocess.CompletedProcess(
                                command, 255 if self.status_error == "transport" else 1, b"", b"disconnected"
                            )
                        if self.pending_polls:
                            self.pending_polls -= 1
                            return subprocess.CompletedProcess(command, 42, b"", b"")
                    code, stdout = (0, self.files[name]) if name in self.files else (42, b"")
        elif arguments[:2] == ["exec-out", "cat"]:
            # Shell-mode raw reads use content validation, not a remote exit code.
            stdout = (
                f"{self.exit_status} {self.signum} {int(self.timed_out)}\n".encode()
                if arguments[-1].endswith("/status")
                else b"stderr\x00bytes"
            )
        elif arguments[0] == "install":
            assert not self.installed
            self.installed = True
            if self.install_error:
                code, stderr = 1, b"install failed after creating package"
        elif arguments[0] == "uninstall":
            if self.uninstall_error or (self.cleanup_uninstall_error and self.launched):
                code, stderr = 1, b"uninstall failed"
            elif not self.installed:
                code, stderr = 1, b"package is not installed"
            else:
                self.installed = False
                self.files.clear()
        elif arguments[:4] == ["shell", "pm", "list", "packages"]:
            stdout = b"package:dev.btrc.testhost.fixture\n" if self.installed else b""
        elif arguments[:3] == ["shell", "am", "start"]:
            assert self.installed and set(self.files) == {"request.bin", "stdin"}
            self.launched = True
            self.files.update(stdout=b"app\x00stdout", stderr=b"app\x00stderr")
            if not self.app_timeout:
                self.files.update(exit_status=f"{self.app_exit_status}\n".encode(), signal=f"{self.signum}\n".encode())
        elif arguments[:3] == ["shell", "am", "force-stop"]:
            if self.stop_error:
                code, stderr = 1, b"force-stop failed"
        elif arguments[:2] == ["shell", "pidof"]:
            if self.lingering_polls:
                self.lingering_polls -= 1
                stdout = b"1234\n"
            else:
                code = 1
        elif arguments[:2] == ["shell", "run-as"]:
            assert arguments[3:] == ["mkdir", "-p", "files"] and self.installed
        elif arguments[:2] == ["shell", "getprop"]:
            stdout = b"fake-build\n"
        elif arguments[:2] in (["shell", "mkdir"], ["shell", "chmod"], ["shell", "rm"]) or arguments[0] == "push":
            pass
        else:
            raise AssertionError(f"unexpected adb command: {arguments}")
        return subprocess.CompletedProcess(command, code, stdout, stderr)


def executor_bundle(tmp_path, transport, mode="shell"):
    artifact = "probe" if mode == "shell" else "host.apk"
    (tmp_path / artifact).touch()
    row = {"mode": mode, "executable" if mode == "shell" else "apk": artifact}
    if mode == "app":
        row["package"] = "dev.btrc.testhost.fixture"
    else:
        (tmp_path / "supervisor").touch()
        row["supervisor"] = "supervisor"
    (tmp_path / "programs.json").write_text(json.dumps({"probe": row}))
    executor = AndroidEmulatorExecutor(tmp_path, "emulator-5554", transport=transport)
    executor.prepare(tmp_path, "unit fixture")
    return executor


def test_shell_preserves_binary_streams_exit_status_and_argument_boundaries(tmp_path):
    transport = FakeAdb(3)
    executor = executor_bundle(tmp_path, transport)
    result = executor.run(
        ExecutionRequest("probe", ("a b", "'quoted'", "$(touch nope)", ""), b"stdin", {"FIXTURE": "space ; value"})
    )
    assert (result.exit_status, result.stdout, result.stderr, result.timed_out) == (
        3,
        b"stdout\x00bytes",
        b"stderr\x00bytes",
        False,
    )
    command = next(args[2] for args, _ in transport.calls if args[:2] == ["shell", "-T"])
    words = shlex.split(command)
    assert "FIXTURE=space ; value" in words
    assert words[-6:-2] == ["a b", "'quoted'", "$(touch nope)", ""]
    assert any(args[:3] == ["shell", "rm", "-rf"] for args, _ in transport.calls)
    assert all(options["timeout"] > 0 for _, options in transport.calls)


@pytest.mark.parametrize(
    "status,signum,timed_out", [(124, 0, False), (137, 0, False), (-1, 6, False), (-1, 9, False), (-1, 9, True)]
)
def test_shell_reports_abort_and_timeout_separately(tmp_path, status, signum, timed_out):
    executor = executor_bundle(tmp_path, FakeAdb(status, signum=signum, timed_out=timed_out))
    result = executor.run(ExecutionRequest("probe"))
    assert (result.exit_status, result.signal, result.timed_out) == (
        None if signum or timed_out else status,
        signum or None,
        timed_out,
    )


def test_transport_failure_is_not_a_program_failure(tmp_path):
    transport = FakeAdb(shell_status=255)
    executor = executor_bundle(tmp_path, transport)
    with pytest.raises(RuntimeError, match="transport or outer supervisor guard failed"):
        executor.run(ExecutionRequest("probe"))
    assert any(args[:3] == ["shell", "rm", "-rf"] for args, _ in transport.calls)


def test_app_mode_collects_exit_and_uninstalls_a_fresh_sandbox(tmp_path):
    transport = FakeAdb()
    executor = executor_bundle(tmp_path, transport, "app")
    result = executor.run(ExecutionRequest("probe", ("arg",), b"input"))
    assert result.exit_status == 3 and not result.timed_out
    assert len([args for args, _ in transport.calls if args[0] == "uninstall"]) == 2
    assert transport.writes["stdin"] == b"input"
    assert transport.writes["request.bin"] == executor.configuration(ExecutionRequest("probe", ("arg",)))
    assert result.stdout == b"app\x00stdout" and result.stderr == b"app\x00stderr"
    assert result.signal is None
    assert result.provenance["install_s"] >= 0 and result.provenance["launch_s"] >= 0


def test_app_timeout_force_stops_and_verifies_process_exit(tmp_path):
    transport = FakeAdb(app_timeout=True)
    executor = executor_bundle(tmp_path, transport, "app")
    result = executor.run(ExecutionRequest("probe", timeout_s=0.000001))
    assert result.exit_status is None and result.timed_out
    assert any(args[:3] == ["shell", "am", "force-stop"] for args, _ in transport.calls)
    assert any(args[:2] == ["shell", "pidof"] for args, _ in transport.calls)


def test_app_poll_timeout_is_bounded_by_remaining_program_budget(tmp_path):
    transport = FakeAdb(status_error="timeout")
    executor = executor_bundle(tmp_path, transport, "app")
    result = executor.run(ExecutionRequest("probe", timeout_s=1))
    assert result.timed_out
    assert all(
        0 < options["timeout"] <= 1
        for args, options in transport.calls
        if args[:2] == ["shell", "-T"] and "files/exit_status" in args[-1]
    )
    assert any(args[:3] == ["shell", "am", "force-stop"] for args, _ in transport.calls)


@pytest.mark.parametrize("error", ["timeout", "transport", "client"])
def test_app_infrastructure_failure_always_force_stops_and_uninstalls(tmp_path, error):
    transport = FakeAdb(status_error=error)
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(RuntimeError, match="transport"):
        executor.run(ExecutionRequest("probe", timeout_s=60))
    assert any(args[:3] == ["shell", "am", "force-stop"] for args, _ in transport.calls)
    assert transport.calls[-1][0][0] == "uninstall"


@pytest.mark.parametrize(
    "execution_request",
    [
        ExecutionRequest("probe", env={"BAD=KEY": "x"}),
        ExecutionRequest("probe", argv=("NUL\0",)),
        ExecutionRequest("probe", timeout_s=0),
        ExecutionRequest("probe", cwd_policy="host"),
    ],
)
def test_request_validation_rejects_ambiguous_transport_inputs(execution_request):
    with pytest.raises(ValueError):
        AndroidEmulatorExecutor.validate(execution_request)


def test_native_configuration_is_length_delimited_not_shell_source():
    request = ExecutionRequest("probe", ("space and ; shell", ""), env={"VALUE": "line\nvalue"})
    payload = AndroidEmulatorExecutor.configuration(request)
    assert struct.unpack_from("<I", payload)[0] == 3
    assert b"space and ; shell" in payload and b"line\nvalue" in payload


def test_bundle_cannot_escape_its_artifact_directory(tmp_path):
    (tmp_path / "programs.json").write_text(json.dumps({"probe": {"mode": "shell", "executable": "../outside"}}))
    transport = FakeAdb()
    with pytest.raises(ValueError, match="inside the bundle"):
        AndroidEmulatorExecutor(tmp_path, "emulator-5554", transport=transport).prepare(tmp_path, "fixture")
    assert transport.calls == []


@pytest.mark.parametrize("status,signum", [(0, 0), (3, 0), (124, 0), (137, 0), (134, 6), (137, 9)])
def test_app_pending_status_then_normal_or_signal_exit(tmp_path, status, signum):
    transport = FakeAdb(app_exit_status=status, signum=signum, pending_polls=1)
    executor = executor_bundle(tmp_path, transport, "app")
    result = executor.run(ExecutionRequest("probe"))
    assert (result.exit_status, result.signal, result.timed_out) == (
        None if signum else status,
        signum or None,
        False,
    )
    assert transport.status_polls == 2
    assert not transport.installed


def test_failed_app_payload_write_never_launches_and_cleans_up(tmp_path):
    transport = FakeAdb(fail_write=True)
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(RuntimeError, match="write failed"):
        executor.run(ExecutionRequest("probe"))
    assert not transport.launched and not transport.installed


@pytest.mark.parametrize("payload", [b"cat: not found\n", b"", b"-1\n", b"256\n", b"3\n4\n", b"9" * 5000])
def test_app_rejects_corrupt_exit_status(payload):
    with pytest.raises(RuntimeError, match="invalid exit status"):
        AndroidEmulatorExecutor.status_number(payload, "exit status", 255)


def test_app_shutdown_waits_for_a_dying_process(tmp_path):
    transport = FakeAdb(lingering_polls=1)
    executor = executor_bundle(tmp_path, transport, "app")
    executor.run(ExecutionRequest("probe"))
    assert len([args for args, _ in transport.calls if args[:2] == ["shell", "pidof"]]) == 2


def test_unknown_program_is_a_request_error(tmp_path):
    executor = executor_bundle(tmp_path, FakeAdb())
    with pytest.raises(ValueError, match="unknown program_id"):
        executor.run(ExecutionRequest("unknown"))


class LocalAdbProtocol:
    """Run the real POSIX shell boundary with AOSP client quoting/status rules.

    This exercises shell parsing, files and streams on the host. It is not adb,
    run-as permission, NativeActivity or emulator execution evidence.
    """

    def __init__(self, root):
        self.root = root
        (root / "files").mkdir()
        shim = root / "run-as"
        shim.write_text('#!/bin/sh\nshift\nexec "$@"\n')
        shim.chmod(0o755)

    def __call__(self, command, **options):
        arguments = command[3:]
        if arguments[:2] == ["shell", "-T"]:
            script = " ".join(arguments[2:])
            raw = False
        else:
            assert arguments[0] in ("exec-in", "exec-out")
            # AOSP client/commandline.cpp: argv[1] verbatim, then escape_arg.
            script = arguments[1] + "".join(" " + shlex.quote(word) for word in arguments[2:])
            raw = True
        completed = subprocess.run(
            ["sh", "-c", script],
            cwd=self.root,
            env={**os.environ, "PATH": str(self.root) + os.pathsep + os.environ["PATH"]},
            input=options["input"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if raw else subprocess.PIPE,
            timeout=TOOL_TIMEOUT,
            check=False,
        )
        return subprocess.CompletedProcess(
            command,
            0 if raw else completed.returncode,
            b"" if arguments[0] == "exec-in" else completed.stdout,
            b"" if raw else completed.stderr,
        )


def test_app_transfer_and_missing_file_status_use_real_shell_boundaries(tmp_path):
    transport = LocalAdbProtocol(tmp_path)
    executor = AndroidEmulatorExecutor(tmp_path, "emulator-5554", transport=transport)
    request = ExecutionRequest(
        "probe", ("space and ' quote", "", "$(touch should-not-exist)"), env={"VALUE": "line\nvalue"}
    )
    payloads = {"request.bin": executor.configuration(request), "stdin": bytes(range(256)) + b"\r\n\x00"}
    for name, payload in payloads.items():
        executor.remote("run-as", "dev.btrc.testhost.fixture", "sh", "-c", f"cat > files/{name}", input=payload)
        assert (tmp_path / "files" / name).read_bytes() == payload
    assert executor.app_file("dev.btrc.testhost.fixture", "exit_status", optional=True) is None
    (tmp_path / "files/exit_status").write_bytes(b"3\n")
    assert executor.app_file("dev.btrc.testhost.fixture", "exit_status") == b"3\n"
    (tmp_path / "files/exit_status").unlink()
    (tmp_path / "files/exit_status").mkdir()
    with pytest.raises(RuntimeError, match="transport failed for exit_status"):
        executor.app_file("dev.btrc.testhost.fixture", "exit_status", optional=True)
    with pytest.raises(RuntimeError, match="transport failed for signal"):
        executor.app_file("dev.btrc.testhost.fixture", "signal")
    completed = executor.remote("sh", "-c", "printf 'output'; printf 'error' >&2; exit 7", check=False)
    assert (completed.returncode, completed.stdout, completed.stderr) == (7, b"output", b"error")
    assert not (tmp_path / "should-not-exist").exists()


def test_raw_exec_regression_reproduces_double_quote_and_missing_file(tmp_path):
    transport = LocalAdbProtocol(tmp_path)
    executor = AndroidEmulatorExecutor(tmp_path, "emulator-5554", transport=transport)
    executor.adb(
        "exec-in",
        "run-as",
        "dev.btrc.testhost.fixture",
        "sh",
        "-c",
        shlex.quote("cat > files/request.bin"),
        input=b"lost",
    )
    assert not (tmp_path / "files/request.bin").exists()
    missing = executor.adb("exec-out", "run-as", "dev.btrc.testhost.fixture", "cat", "files/exit_status")
    assert missing.returncode == 0 and missing.stderr == b"" and b"files/exit_status" in missing.stdout
    # Without prequoting, one raw-client escape pass reaches the inner shell.
    executor.adb("exec-in", "run-as", "dev.btrc.testhost.fixture", "sh", "-c", "cat > files/request.bin", input=b"ok")
    assert (tmp_path / "files/request.bin").read_bytes() == b"ok"


def test_fixture_checks_remain_enabled_with_optimized_python():
    script = """
from tools.target_hosts.android.check import HostFixtureCheck
from tools.target_hosts.android.executor import ExecutionResult
class BrokenExecutor:
    programs = {"app": {}}
    def run(self, request):
        if request.argv[0] != "stdout":
            raise RuntimeError("the first fixture's incorrect exit status was accepted")
        return ExecutionResult(7, None, b"stdout\\n", b"", False, 0, {})
try:
    HostFixtureCheck(BrokenExecutor()).run()
except AssertionError as error:
    if "exit status" not in str(error):
        raise RuntimeError("fixture failed for an unrelated reason") from error
else:
    raise RuntimeError("optimized Python disabled fixture validation")
"""
    subprocess.run([sys.executable, "-O", "-c", script], cwd=REPO, check=True, timeout=TOOL_TIMEOUT)


def test_failed_uninstall_cannot_reuse_an_installed_apps_stale_success(tmp_path):
    transport = FakeAdb(uninstall_error=True)
    transport.installed = True
    transport.files.update(exit_status=b"0\n", signal=b"0\n", stdout=b"stale", stderr=b"")
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(RuntimeError, match="still installed"):
        executor.run(ExecutionRequest("probe"))
    assert not transport.launched
    assert not any(args[0] == "install" for args, _ in transport.calls)
    assert transport.files["stdout"] == b"stale"


def test_missing_package_is_confirmed_before_fresh_install(tmp_path):
    transport = FakeAdb()
    executor = executor_bundle(tmp_path, transport, "app")
    executor.run(ExecutionRequest("probe"))
    commands = [args for args, _ in transport.calls]
    inventory = next(index for index, args in enumerate(commands) if args[:4] == ["shell", "pm", "list", "packages"])
    install = next(index for index, args in enumerate(commands) if args[0] == "install")
    assert inventory < install


def test_app_cleanup_preserves_primary_error_and_attempts_both_actions(tmp_path):
    transport = FakeAdb(status_error="transport", stop_error=True, cleanup_uninstall_error=True)
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(RuntimeError, match="app file transport failed") as caught:
        executor.run(ExecutionRequest("probe"))
    notes = " ".join(caught.value.__notes__)
    assert "force-stop failed" in notes and "still installed" in notes
    assert len([args for args, _ in transport.calls if args[0] == "uninstall"]) == 2


def test_install_failure_still_attempts_package_cleanup(tmp_path):
    transport = FakeAdb(install_error=True)
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(RuntimeError, match="install failed"):
        executor.run(ExecutionRequest("probe"))
    assert not transport.installed
    assert any(args[:3] == ["shell", "am", "force-stop"] for args, _ in transport.calls)


def test_cleanup_failure_cannot_turn_a_successful_fixture_into_a_pass(tmp_path):
    transport = FakeAdb(stop_error=True)
    executor = executor_bundle(tmp_path, transport, "app")
    with pytest.raises(ExceptionGroup, match="app cleanup failed"):
        executor.run(ExecutionRequest("probe"))
    assert not transport.installed
