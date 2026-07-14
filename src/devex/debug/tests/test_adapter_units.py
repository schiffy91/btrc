"""Protocol-level adapter tests using deterministic fake LLDB sessions."""

import threading
import types

import adapter as adapter_module
import adapter_events
import builder
import pytest

from src.devex.debug.tests.adapter_test_support import (
    FakeArtifact,
    FakeSession,
)
from src.devex.debug.tests.adapter_test_support import (
    adapter as _adapter,
)
from src.devex.debug.tests.adapter_test_support import (
    request as _request,
)


@pytest.mark.parametrize(
    ("command", "action"),
    [
        ("configurationDone", "start"),
        ("continue", "continue"),
        ("next", "next"),
        ("stepIn", "stepIn"),
        ("stepOut", "stepOut"),
        ("pause", "pause"),
    ],
)
def test_failing_execution_action_emits_exactly_one_failure_response(command, action):
    session = FakeSession(failing_action=action)
    instance = _adapter(_request(command, {"threadId": 7}), session)

    instance.run()

    assert len(instance.writer.responses) == 1
    assert instance.writer.responses[0]["success"] is False
    assert instance.writer.responses[0]["message"] == f"{action} failed"


def test_build_failure_emits_one_launch_response(monkeypatch):
    def fail_build(*_args, **_kwargs):
        raise builder.BuildError("compiler exploded")

    monkeypatch.setattr(adapter_module.builder, "build", fail_build)
    request = _request("launch", {"program": "/tmp/source.btrc"})
    instance = _adapter(request, FakeSession())
    instance._launch = None
    instance._program = None

    instance.run()

    assert len(instance.writer.responses) == 1
    assert instance.writer.responses[0]["success"] is False
    assert instance.writer.responses[0]["message"] == "build failed"


def test_target_failure_cleans_the_new_build_artifact(monkeypatch):
    artifact = FakeArtifact()
    monkeypatch.setattr(adapter_module.builder, "build", lambda *_args, **_kwargs: artifact)
    request = _request("launch", {"program": "/tmp/source.btrc"})
    instance = _adapter(request, FakeSession(failing_action="create_target"))
    instance._launch = None
    instance._artifact = None
    instance._program = None

    instance.run()

    assert len(instance.writer.responses) == 1
    assert instance.writer.responses[0]["success"] is False
    assert artifact.cleanup_calls == 1


def test_disconnect_terminates_once_and_cleans_owned_artifact_once():
    artifact = FakeArtifact()
    session = FakeSession()
    instance = _adapter(_request("disconnect"), session, artifact)

    instance.run()

    assert len(instance.writer.responses) == 1
    assert instance.writer.responses[0]["success"] is True
    assert session.terminate_calls == 1
    assert artifact.cleanup_calls == 1


def test_launch_parses_quoted_commands_and_resolves_program_from_cwd(monkeypatch, tmp_path):
    artifact = FakeArtifact()
    captured = {}

    def build(program, **options):
        captured["program"] = program
        captured.update(options)
        return artifact

    monkeypatch.setattr(adapter_module.builder, "build", build)
    request = _request(
        "launch",
        {
            "program": "source/main.btrc",
            "cwd": str(tmp_path),
            "btrcpy": '"/Applications/Btrc Compiler/bin/btrcpy" --trace',
            "cflags": '-DNAME="hello world" -Wall',
        },
    )
    instance = _adapter(request, FakeSession())
    instance._launch = None
    instance._program = None

    instance.run()

    assert captured["program"] == str(tmp_path / "source" / "main.btrc")
    assert captured["btrcpy_cmd"] == ["/Applications/Btrc Compiler/bin/btrcpy", "--trace"]
    assert captured["cflags"] == ["-DNAME=hello world", "-Wall"]
    assert captured["cwd"] == str(tmp_path)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ([], "launch: 'arguments' must be an object"),
        ({"program": "/tmp/p.btrc", "args": "one two"}, "launch: 'args' must be a list of strings"),
        ({"program": "/tmp/p.btrc", "stopOnEntry": "false"}, "launch: 'stopOnEntry' must be a boolean"),
    ],
)
def test_invalid_launch_request_shape_gets_one_failure_response(arguments, message):
    instance = _adapter(_request("launch", arguments), FakeSession())
    instance._launch = None
    instance._program = None

    instance.run()

    assert len(instance.writer.responses) == 1
    assert instance.writer.responses[0]["success"] is False
    assert instance.writer.responses[0]["message"] == message


def test_request_without_sequence_is_rejected_without_crashing(capsys):
    request = _request("threads")
    request.pop("seq")
    instance = _adapter(request, FakeSession())

    instance.run()

    assert instance.writer.responses == []
    assert "request has no valid sequence number" in capsys.readouterr().err


class ExitProcess:
    def __init__(self):
        self.stdout = [b"ok\xff", b""]
        self.stderr = [b""]

    def GetSTDOUT(self, _size):
        return self.stdout.pop(0) if self.stdout else b""

    def GetSTDERR(self, _size):
        return self.stderr.pop(0) if self.stderr else b""

    def GetExitStatus(self):
        return 0


class OneExitListener:
    def __init__(self):
        self.sent = False

    def WaitForEvent(self, _timeout, _event):
        if self.sent:
            return False
        self.sent = True
        return True


def test_configuration_response_precedes_events_and_output_is_utf8(monkeypatch):
    fake_process_type = types.SimpleNamespace(
        EventIsProcessEvent=lambda _event: True,
        GetStateFromEvent=lambda _event: 2,
        GetRestartedFromEvent=lambda _event: False,
    )
    fake_lldb = types.SimpleNamespace(
        SBEvent=object,
        SBProcess=fake_process_type,
        eStateStopped=1,
        eStateExited=2,
        eStateCrashed=3,
    )
    monkeypatch.setattr(adapter_events, "lldb", fake_lldb)
    artifact = FakeArtifact()
    instance = _adapter(_request("configurationDone"), FakeSession(), artifact)
    instance.session.listener = OneExitListener()
    instance.session.process = ExitProcess()

    instance.do_configurationDone(_request("configurationDone"))
    event_thread = instance._event_thread

    assert instance.writer.terminated.wait(2)
    event_thread.join(2)
    assert instance.writer.operations[0] == ("response", "configurationDone")
    assert instance.writer.events[0] == ("output", {"category": "stdout", "output": "ok\ufffd"})
    assert instance.writer.operations[-2:] == [("event", "exited"), ("event", "terminated")]
    assert artifact.cleanup_calls == 1
    assert instance.session.terminate_calls == 0


class BlockingSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.terminate_started = threading.Event()
        self.allow_terminate = threading.Event()

    def terminate(self):
        self.terminate_calls += 1
        self.terminate_started.set()
        assert self.allow_terminate.wait(2)


def test_concurrent_shutdown_has_one_terminator_and_cleanup_owner():
    artifact = FakeArtifact()
    session = BlockingSession()
    instance = _adapter(_request("disconnect"), session, artifact)
    first = threading.Thread(target=instance._terminate_and_cleanup)
    second = threading.Thread(target=instance._terminate_and_cleanup)

    first.start()
    assert session.terminate_started.wait(2)
    second.start()
    second.join(2)
    assert artifact.cleanup_calls == 0
    session.allow_terminate.set()
    first.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert session.terminate_calls == 1
    assert artifact.cleanup_calls == 1


def test_terminate_response_precedes_single_terminated_event():
    instance = _adapter(_request("terminate"), FakeSession(), FakeArtifact())

    instance.run()

    assert instance.writer.operations == [("response", "terminate"), ("event", "terminated")]


def test_event_loop_failure_terminates_and_cleans_up(monkeypatch, capsys):
    class FailingListener:
        def WaitForEvent(self, _timeout, _event):
            raise RuntimeError("listener failed")

    monkeypatch.setattr(adapter_events, "lldb", types.SimpleNamespace(SBEvent=object))
    artifact = FakeArtifact()
    instance = _adapter(_request("configurationDone"), FakeSession(), artifact)
    instance.session.listener = FailingListener()

    instance.do_configurationDone(_request("configurationDone"))
    event_thread = instance._event_thread
    assert instance.writer.terminated.wait(2)
    event_thread.join(2)

    assert instance.writer.operations == [
        ("response", "configurationDone"),
        ("event", "terminated"),
    ]
    assert instance.session.terminate_calls == 1
    assert artifact.cleanup_calls == 1
    assert "event loop failed: listener failed" in capsys.readouterr().err


def test_configuration_setup_failure_after_launch_cleans_process_and_artifact(monkeypatch):
    artifact = FakeArtifact()
    session = FakeSession()
    instance = _adapter(_request("configurationDone"), session, artifact)
    monkeypatch.setattr(instance, "_prepare_event_loop", lambda: (_ for _ in ()).throw(RuntimeError("thread failed")))

    instance.run()

    assert instance.writer.responses[0]["success"] is False
    assert instance.writer.responses[0]["message"] == "thread failed"
    assert session.terminate_calls == 1
    assert artifact.cleanup_calls == 1


def test_zero_based_client_lines_are_translated_at_breakpoint_boundary():
    class BreakpointSession(FakeSession):
        target = object()

        def set_breakpoints(self, path, specs):
            assert path == "/tmp/source.btrc"
            assert specs[0]["line"] == 1
            return [{"verified": True, "line": 3}]

    instance = _adapter(_request("initialize", {"linesStartAt1": False}), BreakpointSession())
    instance.do_initialize(_request("initialize", {"linesStartAt1": False}))
    instance.do_setBreakpoints(
        _request(
            "setBreakpoints",
            {"source": {"path": "/tmp/source.btrc"}, "breakpoints": [{"line": 0}]},
        )
    )

    assert instance.writer.responses[-1]["body"]["breakpoints"][0]["line"] == 2
