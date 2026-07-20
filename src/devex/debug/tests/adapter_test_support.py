"""Deterministic fakes shared by DAP adapter protocol tests."""

import threading
import types

import adapter as adapter_module
from dap_coordinates import DapCoordinates


class QueueReader:
    def __init__(self, messages):
        self.messages = list(messages)

    def read(self):
        return self.messages.pop(0) if self.messages else None


class RecordingWriter:
    def __init__(self):
        self.responses = []
        self.events = []
        self.operations = []
        self.terminated = threading.Event()

    def respond(self, request, body=None, success=True, message=None):
        self.responses.append(
            {
                "request": request,
                "body": body,
                "success": success,
                "message": message,
            }
        )
        self.operations.append(("response", request.get("command")))

    def event(self, event, body=None):
        self.events.append((event, body))
        self.operations.append(("event", event))
        if event == "terminated":
            self.terminated.set()


class FakeSession:
    def __init__(self, failing_action=None):
        self.failing_action = failing_action
        self.terminate_calls = 0

    def _perform(self, action):
        if action == self.failing_action:
            raise RuntimeError(f"{action} failed")

    def create_target(self, _program):
        self._perform("create_target")

    def start(self, *_args):
        self._perform("start")

    def cont(self):
        self._perform("continue")

    def step_over(self, _thread_id):
        self._perform("next")

    def step_into(self, _thread_id):
        self._perform("stepIn")

    def step_out(self, _thread_id):
        self._perform("stepOut")

    def pause(self):
        self._perform("pause")

    def terminate(self):
        self.terminate_calls += 1


class FakeArtifact:
    executable = "/tmp/fake-debug-program"

    def __init__(self):
        self.cleanup_calls = 0

    def cleanup(self):
        self.cleanup_calls += 1


def request(command, arguments=None):
    return {
        "seq": 1,
        "type": "request",
        "command": command,
        "arguments": {} if arguments is None else arguments,
    }


def adapter(request_message, session, artifact=None):
    instance = object.__new__(adapter_module.BtrcAdapter)
    instance.reader = QueueReader([request_message])
    instance.writer = RecordingWriter()
    instance.session = session
    instance.coordinates = DapCoordinates()
    instance._launch = types.SimpleNamespace(argv=[], stop_on_entry=False)
    instance._artifact = artifact
    instance._program = artifact.executable if artifact else "/tmp/program"
    instance._cwd = "/tmp"
    instance._running = False
    instance._terminated = False
    instance._lifecycle_lock = threading.Lock()
    instance._events_enabled = threading.Event()
    instance._event_thread = None
    instance._await_entry = False
    instance._output_decoders = {}
    return instance
