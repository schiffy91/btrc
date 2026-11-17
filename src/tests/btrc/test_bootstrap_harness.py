"""Process-boundary contracts for the bootstrap fixed-point harness."""

import gc
import os
import shutil
import subprocess
import sys
import time
import weakref
from pathlib import Path

import pytest

from src.tests.btrc import bootstrap_harness as bootstrap
from src.tests.process_limits import TOOL_TIMEOUT


@pytest.mark.parametrize(
    "entrypoint", ["BtrccMain.btrc", os.path.join("cli", "WindowsMain.btrc"), os.path.join("cli", "MacOSMain.btrc")]
)
def test_snapshot_preserves_host_entrypoint(tmp_path, monkeypatch, entrypoint) -> None:
    monkeypatch.setattr(bootstrap, "COMPILER_ENTRYPOINT", entrypoint)
    project, source_root, compiler = bootstrap.snapshot_compiler_inputs(str(tmp_path))
    assert compiler == os.path.join(source_root, "compiler", "btrc", entrypoint)
    assert os.path.isfile(compiler)
    assert os.path.commonpath([project, compiler]) == project
    with open(compiler, encoding="utf-8") as source:
        text = source.read()
    assert ("FeNativeHeaderProcess.read" in text) == (entrypoint != os.path.join("cli", "WindowsMain.btrc"))
    assert ("NativeSHA256()" in text) == (entrypoint == os.path.join("cli", "MacOSMain.btrc"))


def test_stage_one_is_the_suites_cached_compiler_unless_the_run_builds_it_differently(tmp_path, monkeypatch) -> None:
    """The cache holds the first stage, so the gate does not spend the reference build a second time."""

    built = []

    class Cache:
        def compiler_binary(self):
            return tmp_path / "cache" / "btrcc"

    monkeypatch.setattr(bootstrap.SelfhostCompilerCache, "configured", classmethod(lambda cls: Cache()))
    monkeypatch.setattr(bootstrap, "transpile_with_python", lambda *arguments: built.append(("transpile", arguments)))
    monkeypatch.setattr(bootstrap, "compile_c", lambda *arguments, **options: built.append(("compile", options)))
    monkeypatch.setattr(bootstrap, "COMPILER_ENTRYPOINT", os.path.relpath(bootstrap.ENTRY, "src/compiler/btrc"))
    for name in bootstrap.STAGE_ONE_OVERRIDES:
        monkeypatch.delenv(name, raising=False)
    own = str(tmp_path / f"btrcc1{bootstrap.EXE_SUFFIX}")

    assert bootstrap.reference_built_compiler("project", "data", "source", str(tmp_path)) == str(
        tmp_path / "cache" / "btrcc"
    )
    assert built == []
    # The cache transpiles with the flags the gate's own first stage uses.
    assert bootstrap.reference_compiler_flags() == bootstrap.REFERENCE_FLAGS
    assert (
        bootstrap.REFERENCE_FLAGS[:2] == ("--strict-imports", "--target") and "--no-cache" in bootstrap.REFERENCE_FLAGS
    )

    # Other C flags, libraries or another interpreter are another build: the gate makes its own.
    for name in bootstrap.STAGE_ONE_OVERRIDES:
        built.clear()
        monkeypatch.setenv(name, "changed")
        assert bootstrap.reference_built_compiler("project", "data", "source", str(tmp_path)) == own
        assert [step for step, _ in built] == ["transpile", "compile"]
        assert built[0][1] == ("project", "data", "source", str(tmp_path / "btrcc1.c"))
        assert built[1][1] == {"workdir": "project", "compiler": True}
        monkeypatch.delenv(name)
    # So is a host composition the cache does not build.
    built.clear()
    monkeypatch.setattr(bootstrap, "COMPILER_ENTRYPOINT", os.path.join("cli", "MacOSMain.btrc"))
    assert bootstrap.reference_built_compiler("project", "data", "source", str(tmp_path)) == own
    assert [step for step, _ in built] == ["transpile", "compile"]


@pytest.mark.parametrize("target", ["x86_64-windows-gnu", "aarch64-windows-gnu"])
def test_snapshot_windows_filesystem_has_its_native_dependency_closure(tmp_path, target) -> None:
    project, source_root, _ = bootstrap.snapshot_compiler_inputs(str(tmp_path))
    result = subprocess.run(
        [
            shutil.which("zig"),
            "cc",
            "-target",
            target,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(Path(source_root) / "stdlib/FileSystem/Windows/Win32FileSystem.c"),
            "-o",
            str(tmp_path / "filesystem.o"),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group contract")
def test_stage_timeout_kills_spawned_descendants(tmp_path) -> None:
    marker = tmp_path / "escaped-child"
    child = "import pathlib,sys,time; time.sleep(1); pathlib.Path(sys.argv[1]).write_text('escaped')"
    parent = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
        "print('spawned', flush=True); "
        "time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired) as timeout:
        bootstrap.run_process(
            [sys.executable, "-c", parent, child, str(marker)],
            timeout=0.2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert timeout.value.stdout == "spawned\n"
    time.sleep(1.1)
    assert not marker.exists()


def test_stage_timeout_releases_process_before_propagating(monkeypatch) -> None:
    processes = []

    class TimedOutProcess:
        pid = 1
        returncode = -1

        def __init__(self, args) -> None:
            self.args = args

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(self.args, timeout)
            return b"", b""

    def process_factory(args, **_kwargs):
        process = TimedOutProcess(args)
        processes.append(weakref.ref(process))
        return process

    monkeypatch.setattr(bootstrap.subprocess, "Popen", process_factory)
    monkeypatch.setattr(bootstrap, "terminate_process_tree", lambda _process: None)

    with pytest.raises(subprocess.TimeoutExpired):
        bootstrap.run_process(["timed-out"], timeout=0.01)

    gc.collect()
    assert processes[0]() is None


@pytest.mark.skipif(os.name != "nt", reason="native Windows executable-release contract")
def test_stage_timeout_releases_native_windows_executable(tmp_path) -> None:
    executable = tmp_path / "timed-out-python.exe"
    shutil.copy2(sys.executable, executable)

    with pytest.raises(subprocess.TimeoutExpired):
        bootstrap.run_process(
            [str(executable), "-c", "import time; time.sleep(30)"],
            timeout=0.2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    executable.unlink()
