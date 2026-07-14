"""btrc Debug Adapter Protocol server.

Speaks DAP over stdio and drives lldb (via :class:`LldbSession`) so VSCode can
debug .btrc programs natively: breakpoints, stepping, call stack, and
btrc-aware variable inspection. Run via ``btrc_dap.py`` (which bootstraps the
lldb-capable interpreter first).
"""

from __future__ import annotations

import sys
import threading

import builder
import lldb
from adapter_events import AdapterEventsMixin
from dap_coordinates import DapCoordinates
from dap_io import DapProtocolError, DapReader, DapWriter
from launch_config import parse_launch_config
from lldb_session import LldbSession


class BtrcAdapter(AdapterEventsMixin):
    def __init__(self, stdin, stdout):
        self.reader = DapReader(stdin)
        self.writer = DapWriter(stdout)
        self.session = LldbSession(lldb)
        self.coordinates = DapCoordinates()
        self._launch = None  # stored launch config until configurationDone
        self._artifact = None  # owned builder.BuildArtifact
        self._program = None  # built binary path
        self._cwd = None
        self._running = False
        self._terminated = False
        self._lifecycle_lock = threading.Lock()
        self._events_enabled = threading.Event()
        self._event_thread = None
        self._await_entry = False  # report the first (reasonless) stop as "entry"
        self._output_decoders = {}

    # --- main loop ---

    def run(self):
        try:
            while True:
                try:
                    msg = self.reader.read()
                except DapProtocolError as error:
                    sys.stderr.write(f"btrc debug adapter: protocol error: {error}\n")
                    break
                if msg is None:
                    break
                if msg.get("type") != "request":
                    continue
                error = _request_shape_error(msg)
                if error is not None:
                    if _can_respond(msg):
                        self.writer.respond(msg, success=False, message=error)
                        continue
                    sys.stderr.write(f"btrc debug adapter: {error}\n")
                    break
                command = msg["command"]
                handler = getattr(self, "do_" + command, None)
                try:
                    if handler is None:
                        self.writer.respond(msg, success=False, message=f"unsupported request: {command}")
                    else:
                        handler(msg)
                except Exception as error:
                    self.writer.respond(msg, success=False, message=str(error))
                if command == "disconnect":
                    break
        finally:
            self._terminate_and_cleanup()

    # --- request handlers ---

    def do_initialize(self, req):
        self.coordinates = DapCoordinates.from_initialize(_arguments(req))
        self.writer.respond(
            req,
            body={
                "supportsConfigurationDoneRequest": True,
                "supportsEvaluateForHovers": True,
                "supportsTerminateRequest": True,
                "supportsConditionalBreakpoints": True,
                "supportsHitConditionalBreakpoints": True,
                "supportsLogPoints": True,
            },
        )
        self.writer.event("initialized")

    def do_launch(self, req):
        if self._launch is not None or self._artifact is not None:
            raise RuntimeError("launch has already been processed")
        config = parse_launch_config(_arguments(req))
        try:
            artifact = builder.build(
                config.program,
                btrcpy_cmd=config.btrcpy_command,
                cc=config.cc,
                cflags=config.cflags,
                cwd=config.compiler_cwd,
            )
        except builder.BuildError as error:
            self._output("stderr", str(error) + "\n")
            self.writer.respond(req, success=False, message="build failed")
            self.writer.event("terminated")
            return
        try:
            self.session.create_target(artifact.executable)
        except Exception:
            artifact.cleanup()
            raise
        self._artifact = artifact
        self._program = artifact.executable
        self._cwd = config.runtime_cwd
        self._terminated = False
        self._launch = config
        self.writer.respond(req)

    def do_setBreakpoints(self, req):
        args = _arguments(req)
        source = args.get("source")
        if not isinstance(source, dict):
            raise ValueError("setBreakpoints: 'source' must be an object")
        path = source.get("path") or source.get("name")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("setBreakpoints: source path is required")
        path = self.coordinates.client_path_to_native(path)
        specs = _breakpoint_specs(args, minimum_line=self.coordinates.minimum_line)
        debugger_specs = [{**spec, "line": self.coordinates.client_line_to_debugger(spec["line"])} for spec in specs]
        verified = self.session.set_breakpoints(path, debugger_specs) if self.session.target else []
        for breakpoint in verified:
            if "line" in breakpoint:
                breakpoint["line"] = self.coordinates.debugger_line_to_client(breakpoint["line"])
        self.writer.respond(req, body={"breakpoints": verified})

    def do_setExceptionBreakpoints(self, req):
        self.writer.respond(req, body={"breakpoints": []})

    def do_configurationDone(self, req):
        if self._launch is None or self._program is None:
            raise RuntimeError("configurationDone received before a successful launch")
        config = self._launch
        self._await_entry = config.stop_on_entry
        try:
            self.session.start(self._program, config.argv, self._cwd, config.stop_on_entry)
            self._prepare_event_loop()
            self.writer.respond(req)
        except Exception:
            self._terminate_and_cleanup()
            raise
        self._enable_events()

    def do_threads(self, req):
        self.writer.respond(req, body={"threads": self.session.threads()})

    def do_stackTrace(self, req):
        tid = _required_int(_arguments(req), "threadId", "stackTrace")
        frames = self.session.stack_frames(tid)
        for frame in frames:
            frame["line"] = self.coordinates.debugger_line_to_client(frame.get("line", 0))
            frame["column"] = self.coordinates.debugger_column_to_client(frame.get("column", 0))
            source = frame.get("source")
            if source and source.get("path"):
                source["path"] = self.coordinates.native_path_to_client(source["path"])
        self.writer.respond(req, body={"stackFrames": frames, "totalFrames": len(frames)})

    def do_scopes(self, req):
        frame_id = _required_int(_arguments(req), "frameId", "scopes")
        self.writer.respond(req, body={"scopes": self.session.scopes(frame_id)})

    def do_variables(self, req):
        ref = _required_int(_arguments(req), "variablesReference", "variables")
        self.writer.respond(req, body={"variables": self.session.variables(ref)})

    def do_evaluate(self, req):
        args = _arguments(req)
        expression = args.get("expression")
        if not isinstance(expression, str):
            raise ValueError("evaluate: 'expression' must be a string")
        frame_id = _optional_int(args, "frameId", "evaluate")
        res = self.session.evaluate(frame_id, expression)
        if res is None:
            self.writer.respond(req, success=False, message="cannot evaluate")
        else:
            self.writer.respond(req, body=res)

    def do_continue(self, req):
        self.session.cont()
        self.writer.respond(req, body={"allThreadsContinued": True})

    def do_next(self, req):
        thread_id = _optional_int(_arguments(req), "threadId", "next")
        self.session.step_over(thread_id)
        self.writer.respond(req)

    def do_stepIn(self, req):
        thread_id = _optional_int(_arguments(req), "threadId", "stepIn")
        self.session.step_into(thread_id)
        self.writer.respond(req)

    def do_stepOut(self, req):
        thread_id = _optional_int(_arguments(req), "threadId", "stepOut")
        self.session.step_out(thread_id)
        self.writer.respond(req)

    def do_pause(self, req):
        self.session.pause()
        self.writer.respond(req)

    def do_terminate(self, req):
        terminated = self._terminate_and_cleanup()
        self.writer.respond(req)
        if terminated:
            self.writer.event("terminated")

    def do_disconnect(self, req):
        self._terminate_and_cleanup()
        self.writer.respond(req)


def _request_shape_error(request):
    sequence = request.get("seq")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        return "request has no valid sequence number"
    command = request.get("command")
    if not isinstance(command, str) or not command:
        return "request has no valid command"
    if "arguments" in request and not isinstance(request["arguments"], dict):
        return f"{command}: 'arguments' must be an object"
    return None


def _can_respond(request):
    sequence = request.get("seq")
    return (
        isinstance(sequence, int)
        and not isinstance(sequence, bool)
        and sequence >= 1
        and isinstance(request.get("command"), str)
        and bool(request["command"])
    )


def _arguments(request):
    return request.get("arguments", {})


def _required_int(arguments, name, command):
    value = _optional_int(arguments, name, command)
    if value is None:
        raise ValueError(f"{command}: missing '{name}'")
    return value


def _optional_int(arguments, name, command):
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{command}: '{name}' must be a positive integer")
    return value


def _breakpoint_specs(arguments, *, minimum_line=1):
    specs = arguments.get("breakpoints")
    if specs is None:
        lines = arguments.get("lines", [])
        if not isinstance(lines, list):
            raise ValueError("setBreakpoints: 'lines' must be a list")
        specs = [{"line": line} for line in lines]
    if not isinstance(specs, list):
        raise ValueError("setBreakpoints: 'breakpoints' must be a list")
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError("setBreakpoints: each breakpoint must be an object")
        line = spec.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line < minimum_line:
            convention = "positive" if minimum_line else "non-negative"
            raise ValueError(f"setBreakpoints: breakpoint line must be {convention}")
        condition = spec.get("condition")
        if condition is not None and not isinstance(condition, str):
            raise ValueError("setBreakpoints: 'condition' must be a string")
        hit_condition = spec.get("hitCondition")
        if hit_condition is not None:
            if not isinstance(hit_condition, str) or not hit_condition.isdigit() or int(hit_condition) < 1:
                raise ValueError("setBreakpoints: 'hitCondition' must be a positive decimal string")
        log_message = spec.get("logMessage")
        if log_message is not None and not isinstance(log_message, str):
            raise ValueError("setBreakpoints: 'logMessage' must be a string")
    return specs


def main():
    BtrcAdapter(sys.stdin.buffer, sys.stdout.buffer).run()
