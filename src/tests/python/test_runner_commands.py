import errno
import platform
from types import SimpleNamespace

import pytest

from src.tests import runner
from src.tests import runner_capabilities as capabilities


@pytest.mark.parametrize("standard", ("-std=c11", "-std=gnu11"))
def test_darwin_tray_command_preserves_configured_cflags_once(
    standard: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = [standard, "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O3"]
    monkeypatch.setattr(runner, "BTRC_CC", ["clang"])
    monkeypatch.setattr(runner, "BTRC_CFLAGS", configured)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="Apple clang version 18.0.0"),
    )

    command = runner._gcc_flags("/* btrc_tray.h */", "/tmp/program.c", "/tmp/program")

    assert "-fobjc-arc" in command
    assert [argument for argument in command if argument.startswith("-std=")] == [standard]
    for flag in configured:
        assert command.count(flag) == 1


def _mock_built_gpu_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "libbtrc_gpu.a").write_bytes(b"")
    monkeypatch.setattr(runner, "_GPU_BUILD", str(build))
    monkeypatch.setattr(runner, "_GPU_DIR", str(tmp_path))
    monkeypatch.delenv("GPU_CFLAGS", raising=False)
    monkeypatch.delenv("GPU_LDFLAGS", raising=False)


def test_darwin_gpu_without_homebrew_is_a_precise_skip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_built_gpu_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(capabilities.shutil, "which", lambda _command: None)

    with pytest.raises(pytest.skip.Exception, match="Homebrew is not on PATH"):
        runner._gcc_flags("/* btrc_gpu.h */", "/tmp/program.c", "/tmp/program")


def test_darwin_gpu_missing_formula_is_a_precise_skip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_built_gpu_runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(capabilities.shutil, "which", lambda _command: "/opt/homebrew/bin/brew")
    monkeypatch.setattr(
        capabilities.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="not installed"),
    )

    with pytest.raises(pytest.skip.Exception, match="Homebrew wgpu-native: not installed"):
        runner._gcc_flags("/* btrc_gpu.h */", "/tmp/program.c", "/tmp/program")


def test_gpu_environment_flags_must_be_configured_as_a_pair(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_built_gpu_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv("GPU_CFLAGS", "-I/toolchain/include")

    with pytest.raises(pytest.skip.Exception, match="GPU_CFLAGS and GPU_LDFLAGS must be set together"):
        runner._gcc_flags("/* btrc_gpu.h */", "/tmp/program.c", "/tmp/program")


def test_linux_tray_without_pkg_config_is_a_precise_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.shutil, "which", lambda _command: None)

    with pytest.raises(pytest.skip.Exception, match=r"dbus-1 \(pkg-config\) on Linux"):
        runner._gcc_flags("/* btrc_tray.h */", "/tmp/program.c", "/tmp/program")


def test_loopback_listener_probe_reports_permission_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    class DeniedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, _address):
            raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(capabilities.socket, "socket", lambda *_args: DeniedSocket())

    assert capabilities.loopback_listener_error() == (
        "IPv4 loopback listeners are unavailable: bind failed: Operation not permitted (errno 1)"
    )


def test_loopback_listener_probe_reports_listen_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    class ListenDeniedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, _address):
            pass

        def listen(self, _backlog):
            raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(capabilities.socket, "socket", lambda *_args: ListenDeniedSocket())

    assert capabilities.loopback_listener_error() == (
        "IPv4 loopback listeners are unavailable: listen failed: Permission denied (errno 13)"
    )


def test_only_declared_listener_tests_run_the_loopback_probe(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = tmp_path / "listener.btrc"
    listener.write_text("// BTRC_TEST_REQUIRES: loopback-listener\nint main() { return 0; }\n")
    socketpair_only = tmp_path / "socketpair.btrc"
    socketpair_only.write_text("int main() { socketpair(0, 0, 0, null); return 0; }\n")
    probes = 0

    def unavailable():
        nonlocal probes
        probes += 1
        return "IPv4 loopback listeners are unavailable"

    monkeypatch.setattr(runner, "loopback_listener_error", unavailable)

    runner._require_test_capabilities(socketpair_only)
    with pytest.raises(pytest.skip.Exception, match="loopback listeners are unavailable"):
        runner._require_test_capabilities(listener)
    assert probes == 1


def test_darwin_tray_probe_treats_early_clean_exit_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr(capabilities.subprocess, "run", lambda *_args, **_kwargs: next(results))

    error = capabilities.darwin_tray_backend_error(("clang",), ("-std=c11",), "/tmp/tray")

    assert error == "native tray backend is unavailable: Cocoa terminated the capability probe during initialization"


def test_darwin_tray_probe_build_failure_is_not_a_runtime_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        capabilities.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="Objective-C compile failed"),
    )

    with pytest.raises(capabilities.CapabilityProbeBuildError, match="Objective-C compile failed"):
        capabilities.darwin_tray_backend_error(("clang",), ("-std=c11",), "/tmp/tray")


def test_darwin_tray_probe_nonzero_exit_is_not_a_runtime_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=70, stdout="", stderr="probe crashed"),
        ]
    )
    monkeypatch.setattr(capabilities.subprocess, "run", lambda *_args, **_kwargs: next(results))

    with pytest.raises(capabilities.CapabilityProbeRuntimeError, match="probe crashed"):
        capabilities.darwin_tray_backend_error(("clang",), ("-std=c11",), "/tmp/tray")


def test_runtime_capability_check_runs_after_successful_c_compilation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "listener.btrc"
    source.write_text("// BTRC_TEST_REQUIRES: loopback-listener\nint main() { return 0; }\n")
    subprocess_calls = []

    def run(command, **_kwargs):
        subprocess_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_gcc_flags", lambda *_args: ["cc", "program.c"])
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(
        runner,
        "_require_test_capabilities",
        lambda _path: pytest.skip("IPv4 loopback listeners are unavailable"),
    )

    with pytest.raises(pytest.skip.Exception, match="loopback listeners are unavailable"):
        runner._compile_run_check("int main(void) { return 0; }", str(source), source.name)

    assert subprocess_calls == [["cc", "program.c"]]


@pytest.mark.parametrize("raw", ("", "0", "-1", "nan", "inf", "not-a-number"))
def test_transpile_timeout_rejects_non_positive_or_non_finite_values(raw: str) -> None:
    with pytest.raises(ValueError, match="BTRC_TEST_TRANSPILE_TIMEOUT must be a positive number"):
        runner._positive_timeout_seconds(raw, name="BTRC_TEST_TRANSPILE_TIMEOUT", default=300.0)


def test_transpile_timeout_uses_default_and_accepts_fractional_seconds() -> None:
    assert runner._positive_timeout_seconds(None, name="timeout", default=300.0) == 300.0
    assert runner._positive_timeout_seconds("12.5", name="timeout", default=300.0) == 12.5


def test_selfhost_transpile_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0, stdout="int main(void) { return 0; }\n", stderr="")

    monkeypatch.setattr(runner, "BTRC_TRANSPILE_TIMEOUT", 432.5)
    monkeypatch.setattr(runner.subprocess, "run", run)

    output = runner._transpile_btrc("/tmp/btrcc", "/tmp/program.btrc")

    assert output.startswith("int main")
    assert observed == {
        "command": ["/tmp/btrcc", "/tmp/program.btrc"],
        "timeout": 432.5,
    }


def test_python_corpus_runner_uses_the_strict_import_default(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text("int main() { return 0; }\n")
    observed = {}

    class CapturingCompiler:
        def compile_frontend(self, _source, _source_path, options, *, filename):
            observed["options"] = options
            observed["filename"] = filename
            raise RuntimeError("captured before lowering")

    monkeypatch.setattr(runner, "_PYTHON_COMPILER", CapturingCompiler())

    with pytest.raises(RuntimeError, match="captured before lowering"):
        runner._transpile_python(str(program), program.name)

    assert observed["options"].strict_imports is True
    assert observed["filename"] == program.name
