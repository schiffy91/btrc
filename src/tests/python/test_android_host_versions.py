"""Android host version drift and executor transport contracts, without a device."""

from __future__ import annotations

import hashlib
import json
import shlex
import struct
import subprocess
from pathlib import Path

import pytest

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
    """A deterministic transport double; its results are not emulator evidence."""

    def __init__(
        self, exit_status=0, *, app_timeout=False, signum=0, timed_out=False, shell_status=0, status_error=None
    ):
        self.calls = []
        self.exit_status = exit_status
        self.app_timeout = app_timeout
        self.signum, self.timed_out, self.shell_status = signum, timed_out, shell_status
        self.status_error = status_error

    def __call__(self, command, **options):
        arguments = command[3:]
        self.calls.append((arguments, options))
        code, stdout, stderr = 0, b"", b""
        if arguments[:2] == ["shell", "-T"]:
            code, stdout = self.shell_status, b"stdout\x00bytes"
        elif arguments[:2] == ["exec-out", "cat"]:
            stdout = (
                f"{self.exit_status} {self.signum} {int(self.timed_out)}\n".encode()
                if arguments[-1].endswith("/status")
                else b"stderr\x00bytes"
            )
        elif arguments[-1] == "files/exit_status":
            if self.status_error == "timeout":
                raise subprocess.TimeoutExpired(command, options["timeout"])
            if self.status_error == "transport":
                return subprocess.CompletedProcess(command, 255, b"", b"disconnected")
            code, stdout = (1, b"") if self.app_timeout else (0, b"3\n")
        elif arguments[-1] == "files/signal":
            code = 1
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
    writes = [(args, options["input"]) for args, options in transport.calls if args[0] == "exec-in"]
    assert writes[1][1] == b"input"
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
    assert all(0 < options["timeout"] <= 1 for args, options in transport.calls if args[-1] == "files/exit_status")
    assert any(args[:3] == ["shell", "am", "force-stop"] for args, _ in transport.calls)


@pytest.mark.parametrize("error", ["timeout", "transport"])
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
