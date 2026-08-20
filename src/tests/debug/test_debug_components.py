"""Focused unit tests for debug build ownership and breakpoint identity."""

import ast
import os
import signal
import subprocess
import sys
import time
import types
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.devex.debug.backend import lldb as lldb_session
from src.devex.debug.backend import values as summaries
from src.devex.debug.toolchain import build as builder

REPO = Path(__file__).resolve().parents[3]


def _materialize_output(command):
    output = Path(command[command.index("-o") + 1])
    output.write_text("generated")


class CompletedTool:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = None
        self.stderr = None
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, **_options):
        return self._stdout, self._stderr


def test_default_build_is_isolated_from_source_and_cleanup_is_owned(tmp_path):
    source_dir = tmp_path / "read-only-source"
    source_dir.mkdir()
    program = source_dir / "main.btrc"
    program.write_text("int main() { return 0; }")

    def materializing_process(command, **_options):
        _materialize_output(command)
        return CompletedTool()

    source_dir.chmod(0o555)
    try:
        artifact = builder.ProgramBuilder(["btrcpy"], process_factory=materializing_process).build(program)
    finally:
        source_dir.chmod(0o755)

    artifact_dir = Path(artifact.directory)
    assert artifact_dir.parent != source_dir
    assert not (source_dir / ".btrc-debug").exists()
    assert Path(artifact.executable).is_file()

    artifact.cleanup()
    assert not artifact_dir.exists()


def test_failed_build_removes_its_temporary_directory(tmp_path):
    program = tmp_path / "main.btrc"
    program.write_text("int main() { return 0; }")
    artifact_dirs = []

    def process_factory(command, **_options):
        artifact_dirs.append(Path(command[command.index("-o") + 1]).parent)
        if command[0] == "btrcpy":
            _materialize_output(command)
            return CompletedTool()
        return CompletedTool(returncode=1, stderr="compile failed")

    with pytest.raises(builder.BuildError, match="compile failed"):
        builder.ProgramBuilder(["btrcpy"], process_factory=process_factory).build(program)

    assert artifact_dirs
    assert not artifact_dirs[0].exists()


def test_debug_build_preserves_the_compiler_strict_import_default(tmp_path):
    (tmp_path / "owner.btrc").write_text("class Hidden {}\n")
    (tmp_path / "consumer.btrc").write_text("Hidden makeHidden() { return new Hidden(); }\n")
    program = tmp_path / "main.btrc"
    program.write_text("import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n")

    with pytest.raises(builder.BuildError, match=r"consumer\.btrc does not import it"):
        builder.ProgramBuilder(
            ["python3", "-m", "src.compiler.python.main"],
            cwd=str(REPO),
        ).build(program)


def test_missing_build_tool_is_reported_as_a_build_error():
    def missing_tool(*_args, **_kwargs):
        raise FileNotFoundError("compiler not found")

    with pytest.raises(builder.BuildError, match="transpile failed: compiler not found"):
        builder.ProgramBuilder(["missing-btrcpy"], process_factory=missing_tool)._run(
            ["missing-btrcpy"],
            "transpile",
        )


def test_hung_build_tool_is_reported_as_a_bounded_build_error():
    class HungTool:
        pid = 123
        stdout = None
        stderr = None

        def __init__(self):
            self.communications = 0

        def communicate(self, **_options):
            self.communications += 1
            if self.communications == 1:
                raise subprocess.TimeoutExpired(
                    "hung-btrcpy",
                    builder.ProgramBuilder.DEFAULT_BUILD_TIMEOUT_SECONDS,
                )
            return ("", "")

        def poll(self):
            return None

        def kill(self):
            pass

    tool = HungTool()
    terminated = []
    program_builder = builder.ProgramBuilder(
        ["hung-btrcpy"],
        process_factory=lambda *_args, **_options: tool,
        process_group_killer=lambda pid, sig: terminated.append((pid, sig)),
    )

    with pytest.raises(builder.BuildError, match="transpile timed out after 300 seconds"):
        program_builder._run(["hung-btrcpy"], "transpile")

    assert terminated == [(tool.pid, signal.SIGKILL)]
    assert tool.communications == 2


def test_builds_start_in_an_owned_platform_process_group():
    posix_builder = builder.ProgramBuilder(["btrcpy"], platform_name="posix")
    assert posix_builder._process_group_options() == {"start_new_session": True}

    windows_builder = builder.ProgramBuilder(["btrcpy"], platform_name="nt")
    expected = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert windows_builder._process_group_options() == {"creationflags": expected}


def test_program_builder_owns_toolchain_commands_and_working_directory(tmp_path):
    program = tmp_path / "main.btrc"
    program.write_text("int main() { return 0; }")
    output_directory = tmp_path / "debug-output"
    commands = []

    def process_factory(command, **options):
        commands.append((command, options["cwd"]))
        _materialize_output(command)
        return CompletedTool()

    artifact = builder.ProgramBuilder(
        ["custom-btrcpy", "--trace"],
        c_compiler="custom-cc",
        c_flags=["-Wall", "-DDEBUG=1"],
        output_directory=output_directory,
        cwd=tmp_path,
        process_factory=process_factory,
    ).build(program)

    c_path = str(output_directory / "main.c")
    executable = str(output_directory / "main")
    assert commands == [
        (
            ["custom-btrcpy", "--trace", str(program), "--debug", "--no-cache", "-o", c_path],
            str(tmp_path),
        ),
        (
            [
                "custom-cc",
                "-g",
                "-O0",
                "-std=c11",
                c_path,
                "-o",
                executable,
                "-lm",
                "-lpthread",
                "-Wall",
                "-DDEBUG=1",
            ],
            str(tmp_path),
        ),
    ]
    assert artifact == builder.BuildArtifact(executable, str(output_directory))


def test_launch_config_is_an_immutable_normalized_value(tmp_path):
    arguments = {
        "program": "src/main.btrc",
        "cwd": str(tmp_path),
        "btrcpy": ["btrcpy", "--trace"],
        "args": ["first"],
        "cflags": ["-Wall"],
    }

    config = builder.LaunchConfig.from_arguments(arguments)
    arguments["btrcpy"].append("--changed")
    arguments["args"].append("second")
    arguments["cflags"].append("-Wextra")

    assert config.program == str(tmp_path / "src" / "main.btrc")
    assert config.btrcpy_command == ("btrcpy", "--trace")
    assert config.argv == ("first",)
    assert config.cflags == ("-Wall",)
    with pytest.raises(FrozenInstanceError):
        config.cc = "clang"


@pytest.mark.parametrize("name", ["btrcpy", "cflags"])
def test_launch_config_rejects_empty_command_elements(name):
    with pytest.raises(ValueError, match=rf"launch: '{name}' command must contain only non-empty strings"):
        builder.LaunchConfig.from_arguments({"program": "/tmp/main.btrc", name: [""]})


def test_launch_config_allows_empty_runtime_arguments():
    config = builder.LaunchConfig.from_arguments(
        {"program": "/tmp/main.btrc", "args": [""]},
    )

    assert config.argv == ("",)


def test_build_module_exposes_no_loose_behavior_functions():
    tree = ast.parse(Path(builder.__file__).read_text())
    assert not [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


@pytest.mark.parametrize(
    "ctype",
    ["char *", "const char*", "char* volatile", "volatile char * restrict", "_Atomic char*"],
)
def test_string_type_recognizes_debug_info_qualifiers(ctype):
    assert summaries.BtrcValuePresenter()._is_string_type_name(ctype)


@pytest.mark.parametrize("ctype", ["char", "char **", "unsigned char *", "btrc_String *"])
def test_string_type_rejects_non_string_shapes(ctype):
    assert not summaries.BtrcValuePresenter()._is_string_type_name(ctype)


@pytest.mark.parametrize("field", ["__arc", "__rc"])
def test_arc_headers_are_hidden_from_object_views(field):
    assert summaries.BtrcValuePresenter()._is_arc_header(field)


def test_user_fields_are_not_mistaken_for_arc_headers():
    assert not summaries.BtrcValuePresenter()._is_arc_header("arc")


class FakeValueType:
    def __init__(self, name, *, pointee=None, fields=(), valid=True):
        self.name = name
        self.pointee = pointee
        self.fields = list(fields)
        self.valid = valid

    def GetName(self):
        return self.name

    def GetUnqualifiedType(self):
        return self

    def IsPointerType(self):
        return self.pointee is not None

    def GetPointeeType(self):
        return self.pointee

    def IsValid(self):
        return self.valid

    def GetNumberOfFields(self):
        return len(self.fields)

    def GetFieldAtIndex(self, index):
        return types.SimpleNamespace(GetName=lambda: self.fields[index])


class FakeValue:
    def __init__(
        self,
        *,
        name="",
        value=None,
        value_type=None,
        signed=0,
        unsigned=1,
        children=(),
        members=None,
        pointee=None,
        valid=True,
    ):
        self.name = name
        self.value = value
        self.value_type = value_type or FakeValueType("int")
        self.signed = signed
        self.unsigned = unsigned
        self.child_values = list(children)
        self.members = members or {}
        self.pointee = pointee
        self.valid = valid

    def __bool__(self):
        return self.valid

    def GetType(self):
        return self.value_type

    def GetTypeName(self):
        return self.value_type.GetName()

    def GetName(self):
        return self.name

    def GetValue(self):
        return self.value

    def GetSummary(self):
        return None

    def GetValueAsSigned(self):
        return self.signed

    def GetValueAsUnsigned(self):
        return self.unsigned

    def GetNumChildren(self):
        return len(self.child_values)

    def GetChildAtIndex(self, index, *_options):
        return self.child_values[index]

    def GetChildMemberWithName(self, name):
        return self.members.get(name, FakeValue(valid=False))

    def Dereference(self):
        return self.pointee

    def IsValid(self):
        return self.valid


def _fake_vector(values):
    elements = [FakeValue(name=f"[{index}]", value=str(value)) for index, value in enumerate(values)]
    data = FakeValue(name="data", children=elements)
    struct_type = FakeValueType("btrc_Vector_int")
    struct_value = FakeValue(
        value_type=struct_type,
        members={
            "len": FakeValue(name="len", signed=len(elements)),
            "data": data,
        },
    )
    return FakeValue(
        name="values",
        value_type=FakeValueType("btrc_Vector_int *", pointee=struct_type),
        pointee=struct_value,
    )


def test_value_presenter_owns_one_configurable_collection_limit():
    presenter = summaries.BtrcValuePresenter(max_elements=2)
    value = _fake_vector([10, 20, 30])

    assert presenter.classify(value) == "vector"
    assert presenter.summarize(value) == "[10, 20, ... +1]  (len=3)"
    assert [name for name, _ in presenter.children(value)] == ["[0]", "[1]"]


def test_value_presenter_honors_a_zero_object_field_limit():
    struct_type = FakeValueType("btrc_Node", fields=("__arc", "value"))
    struct_value = FakeValue(
        value_type=struct_type,
        children=(FakeValue(name="__arc"), FakeValue(name="value", value="42")),
        members={"value": FakeValue(name="value", value="42")},
    )
    value = FakeValue(
        value_type=FakeValueType("btrc_Node *", pointee=struct_type),
        pointee=struct_value,
    )

    assert summaries.BtrcValuePresenter(max_object_fields=0).summarize(value) == "btrc_Node {}"


def test_lldb_session_composes_and_reuses_its_value_presenter():
    class FakeDebugger:
        def SetAsync(self, _enabled):
            pass

        def GetListener(self):
            return object()

    class FakeSBDebugger:
        @classmethod
        def Create(cls):
            return FakeDebugger()

    presenter = summaries.BtrcValuePresenter(max_elements=2)
    session = lldb_session.LldbSession(
        types.SimpleNamespace(SBDebugger=FakeSBDebugger),
        value_presenter=presenter,
    )

    variable = session._var_dict(_fake_vector([10, 20, 30]))

    assert session.value_presenter is presenter
    assert variable["value"] == "[10, 20, ... +1]  (len=3)"
    expanded = session.variables(variable["variablesReference"])
    assert [child["name"] for child in expanded] == ["[0]", "[1]"]


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
    with pytest.raises(builder.BuildError, match=r"timed out after 0\.5 seconds"):
        builder.ProgramBuilder(["unused"], build_timeout_seconds=0.5)._run(
            [sys.executable, str(spawner), str(child_pid_file)],
            "transpile",
        )

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
