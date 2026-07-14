"""Focused unit tests for debug build ownership and breakpoint identity."""

import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import builder
import lldb_session
import pytest
import summaries


def _materialize_output(command):
    output = Path(command[command.index("-o") + 1])
    output.write_text("generated")


def test_default_build_is_isolated_from_source_and_cleanup_is_owned(monkeypatch, tmp_path):
    source_dir = tmp_path / "read-only-source"
    source_dir.mkdir()
    program = source_dir / "main.btrc"
    program.write_text("int main() { return 0; }")
    monkeypatch.setattr(builder, "_run", lambda command, *_args, **_kwargs: _materialize_output(command))

    source_dir.chmod(0o555)
    try:
        artifact = builder.build(program, btrcpy_cmd=["btrcpy"])
    finally:
        source_dir.chmod(0o755)

    artifact_dir = Path(artifact.directory)
    assert artifact_dir.parent != source_dir
    assert not (source_dir / ".btrc-debug").exists()
    assert Path(artifact.executable).is_file()

    artifact.cleanup()
    assert not artifact_dir.exists()


def test_failed_build_removes_its_temporary_directory(monkeypatch, tmp_path):
    program = tmp_path / "main.btrc"
    program.write_text("int main() { return 0; }")
    artifact_dirs = []

    def run(command, phase, **_kwargs):
        artifact_dirs.append(Path(command[command.index("-o") + 1]).parent)
        if phase == "C compile":
            raise builder.BuildError("compile failed")
        _materialize_output(command)

    monkeypatch.setattr(builder, "_run", run)
    with pytest.raises(builder.BuildError, match="compile failed"):
        builder.build(program, btrcpy_cmd=["btrcpy"])

    assert artifact_dirs
    assert not artifact_dirs[0].exists()


def test_missing_build_tool_is_reported_as_a_build_error(monkeypatch):
    def missing_tool(*_args, **_kwargs):
        raise FileNotFoundError("compiler not found")

    monkeypatch.setattr(builder.subprocess, "Popen", missing_tool)

    with pytest.raises(builder.BuildError, match="transpile failed: compiler not found"):
        builder._run(["missing-btrcpy"], "transpile")


def test_hung_build_tool_is_reported_as_a_bounded_build_error(monkeypatch):
    class HungTool:
        pid = 123
        stdout = None
        stderr = None

        def __init__(self):
            self.communications = 0

        def communicate(self, **_options):
            self.communications += 1
            if self.communications == 1:
                raise subprocess.TimeoutExpired("hung-btrcpy", builder._BUILD_TIMEOUT_SECONDS)
            return ("", "")

        def poll(self):
            return None

        def kill(self):
            pass

    tool = HungTool()
    terminated = []

    monkeypatch.setattr(builder.subprocess, "Popen", lambda *_args, **_options: tool)
    monkeypatch.setattr(builder, "_terminate_process_group", lambda proc: terminated.append(proc))

    with pytest.raises(builder.BuildError, match="transpile timed out after 300 seconds"):
        builder._run(["hung-btrcpy"], "transpile")

    assert terminated == [tool]
    assert tool.communications == 2


def test_builds_start_in_an_owned_platform_process_group(monkeypatch):
    monkeypatch.setattr(builder, "_IS_WINDOWS", False)
    assert builder._process_group_options() == {"start_new_session": True}

    monkeypatch.setattr(builder, "_IS_WINDOWS", True)
    expected = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert builder._process_group_options() == {"creationflags": expected}


@pytest.mark.parametrize(
    "ctype",
    ["char *", "const char*", "char* volatile", "volatile char * restrict", "_Atomic char*"],
)
def test_string_type_recognizes_debug_info_qualifiers(ctype):
    assert summaries._is_string_type_name(ctype)


@pytest.mark.parametrize("ctype", ["char", "char **", "unsigned char *", "btrc_String *"])
def test_string_type_rejects_non_string_shapes(ctype):
    assert not summaries._is_string_type_name(ctype)


@pytest.mark.parametrize("field", ["__arc", "__rc"])
def test_arc_headers_are_hidden_from_object_views(field):
    assert summaries._is_arc_header(field)


def test_user_fields_are_not_mistaken_for_arc_headers():
    assert not summaries._is_arc_header("arc")


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group contract")
def test_hung_build_terminates_descendant_process_group(monkeypatch, tmp_path):
    child_pid_file = tmp_path / "child.pid"
    spawner = tmp_path / "spawn_child.py"
    spawner.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    monkeypatch.setattr(builder, "_BUILD_TIMEOUT_SECONDS", 0.5)

    with pytest.raises(builder.BuildError, match=r"timed out after 0\.5 seconds"):
        builder._run([sys.executable, str(spawner), str(child_pid_file)], "transpile")

    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 3
    while _process_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert not _process_exists(child_pid)
    finally:
        if _process_exists(child_pid):
            os.kill(child_pid, signal.SIGKILL)


def _process_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class FakeBreakpoint:
    def __init__(self, breakpoint_id):
        self.breakpoint_id = breakpoint_id

    def GetID(self):
        return self.breakpoint_id

    def GetNumLocations(self):
        return 0

    def SetCondition(self, _condition):
        pass

    def SetIgnoreCount(self, _count):
        pass


class FakeTarget:
    def __init__(self):
        self.created = []
        self.deleted = []
        self.next_id = 1

    def BreakpointCreateByLocation(self, path, line):
        breakpoint = FakeBreakpoint(self.next_id)
        self.next_id += 1
        self.created.append((path, line, breakpoint.GetID()))
        return breakpoint

    def BreakpointDelete(self, breakpoint_id):
        self.deleted.append(breakpoint_id)


def test_breakpoints_with_equal_basenames_are_owned_by_full_source_path(tmp_path):
    target = FakeTarget()
    session = object.__new__(lldb_session.LldbSession)
    session.target = target
    session._logpoints = {}
    session._breakpoints_by_source = {}

    left = tmp_path / "left" / "main.btrc"
    right = tmp_path / "right" / "main.btrc"
    session.set_breakpoints(str(left), [{"line": 10, "logMessage": "left"}])
    session.set_breakpoints(str(right), [{"line": 20, "logMessage": "right"}])
    session.set_breakpoints(str(left), [{"line": 30}])

    assert target.created == [
        (os.path.realpath(left), 10, 1),
        (os.path.realpath(right), 20, 2),
        (os.path.realpath(left), 30, 3),
    ]
    assert target.deleted == [1]
    assert 2 in session._logpoints
    assert 1 not in session._logpoints


def test_launch_rejects_an_invalid_process_even_when_lldb_reports_success():
    class Success:
        def Success(self):
            return True

    class InvalidProcess:
        def IsValid(self):
            return False

    session = object.__new__(lldb_session.LldbSession)
    session.lldb = types.SimpleNamespace(eLaunchFlagNone=0, SBError=Success)
    session.listener = object()
    session.target = types.SimpleNamespace(Launch=lambda *_args: InvalidProcess())

    with pytest.raises(RuntimeError, match="launch returned an invalid process"):
        session.start("/tmp/program", [], "/tmp", False)


def test_terminate_does_not_kill_an_already_exited_process():
    class ExitedProcess:
        def __init__(self):
            self.kill_calls = 0

        def IsValid(self):
            return True

        def GetState(self):
            return 2

        def Kill(self):
            self.kill_calls += 1

    process = ExitedProcess()
    session = object.__new__(lldb_session.LldbSession)
    session.lldb = types.SimpleNamespace(eStateExited=2, eStateDetached=3, eStateInvalid=4)
    session.process = process

    session.terminate()

    assert process.kill_calls == 0
