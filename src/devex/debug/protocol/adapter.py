"""btrc Debug Adapter Protocol application and process event loop.

``BtrcDebugAdapter`` owns request validation and dispatch. ``ProcessEventLoop``
owns the asynchronous LLDB process lifecycle, output decoding, and the debug
artifact for exactly one launch.
"""

from __future__ import annotations

import codecs
import os
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import lldb

from ..backend.lldb import LldbSession
from ..toolchain.build import BuildArtifact, BuildError, LaunchConfig, ProgramBuilder
from .transport import DapProtocolError, DapReader, DapWriter


@dataclass(frozen=True)
class DapCoordinates:
    """Translate LLDB's 1-based locations to one client's DAP conventions."""

    lines_start_at_one: bool = True
    columns_start_at_one: bool = True
    path_format: str = "path"

    @classmethod
    def from_initialize(cls, arguments: dict) -> DapCoordinates:
        lines = cls._optional_bool(arguments, "linesStartAt1", True)
        columns = cls._optional_bool(arguments, "columnsStartAt1", True)
        path_format = arguments.get("pathFormat", "path")
        if path_format not in ("path", "uri"):
            raise ValueError("initialize: 'pathFormat' must be 'path' or 'uri'")
        return cls(lines, columns, path_format)

    @property
    def minimum_line(self) -> int:
        return 1 if self.lines_start_at_one else 0

    def client_line_to_debugger(self, line: int) -> int:
        return line if self.lines_start_at_one else line + 1

    def debugger_line_to_client(self, line: int) -> int:
        line = max(1, line)
        return line if self.lines_start_at_one else line - 1

    def debugger_column_to_client(self, column: int) -> int:
        column = max(1, column)
        return column if self.columns_start_at_one else column - 1

    def client_path_to_native(self, value: str) -> str:
        if self.path_format == "path":
            return value
        parsed = urlparse(value)
        if parsed.scheme != "file":
            raise ValueError("setBreakpoints: only file URIs are supported")
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"
        if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path

    def native_path_to_client(self, value: str) -> str:
        if self.path_format == "path":
            return value
        return Path(value).absolute().as_uri()

    @staticmethod
    def _optional_bool(arguments: dict, name: str, default: bool) -> bool:
        value = arguments.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"initialize: '{name}' must be a boolean")
        return value


class ProcessEventLoop:
    """Own one launched process, its LLDB events, and its build artifact."""

    def __init__(self, session: LldbSession, writer: DapWriter):
        self.session = session
        self.writer = writer
        self.lldb = session.lldb
        self._launch: LaunchConfig | None = None
        self._artifact: BuildArtifact | None = None
        self._running = False
        self._terminated = False
        self._lifecycle_lock = threading.Lock()
        self._events_enabled = threading.Event()
        self._event_thread = None
        self._await_entry = False
        self._output_decoders = {}

    @property
    def has_launch(self) -> bool:
        return self._launch is not None or self._artifact is not None

    def stage_launch(self, configuration: LaunchConfig, artifact: BuildArtifact) -> None:
        if self.has_launch:
            raise RuntimeError("launch has already been processed")
        self._launch = configuration
        self._artifact = artifact
        self._terminated = False

    def prepare(self) -> None:
        configuration = self._launch
        artifact = self._artifact
        if configuration is None or artifact is None:
            raise RuntimeError("configurationDone received before a successful launch")
        self._await_entry = configuration.stop_on_entry
        self.session.start(
            artifact.executable,
            list(configuration.argv),
            configuration.runtime_cwd,
            configuration.stop_on_entry,
        )
        self._prepare_event_thread()

    def enable(self) -> None:
        self._events_enabled.set()

    def output(self, category, output) -> None:
        output = self._decode_output_chunk(category, output)
        if output:
            self._send_output(category, output)

    def terminate(self) -> bool:
        claimed, artifact = self._claim_shutdown()
        if not claimed:
            return False
        try:
            self.session.terminate()
        finally:
            thread = self._event_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2)
            try:
                self._drain_output()
                self._flush_output_decoders()
            finally:
                self._close_session_and_artifact(artifact)
        return True

    def _prepare_event_thread(self) -> None:
        with self._lifecycle_lock:
            if self._running or self._event_thread is not None:
                raise RuntimeError("configurationDone has already been processed")
            self._running = True
            self._events_enabled.clear()
            thread = threading.Thread(target=self._event_loop, daemon=True)
            self._event_thread = thread
        try:
            thread.start()
        except Exception:
            with self._lifecycle_lock:
                self._running = False
                self._event_thread = None
            raise

    def _event_loop(self) -> None:
        self._events_enabled.wait()
        try:
            while self._is_running():
                event = self.lldb.SBEvent()
                if not self.session.listener.WaitForEvent(1, event):
                    continue
                if not self._is_running():
                    break
                if not self.lldb.SBProcess.EventIsProcessEvent(event):
                    continue
                self._handle_process_event(event)
        except Exception as error:
            sys.stderr.write(f"btrc debug adapter: event loop failed: {error}\n")
            try:
                terminated = self.terminate()
            except Exception as shutdown_error:
                sys.stderr.write(f"btrc debug adapter: cleanup failed: {shutdown_error}\n")
            else:
                if terminated:
                    with suppress(Exception):
                        self.writer.event("terminated")
        finally:
            with self._lifecycle_lock:
                if self._event_thread is threading.current_thread():
                    self._event_thread = None

    def _handle_process_event(self, event) -> None:
        self._drain_output()
        state = self.lldb.SBProcess.GetStateFromEvent(event)
        if state == self.lldb.eStateStopped:
            if not self.lldb.SBProcess.GetRestartedFromEvent(event):
                self._on_stop()
        elif state == self.lldb.eStateExited:
            self._on_exit()
        elif state == self.lldb.eStateCrashed:
            body = {"reason": "exception", "allThreadsStopped": True}
            thread_id = self._stopped_thread_id()
            if thread_id is not None:
                body["threadId"] = thread_id
            self.writer.event("stopped", body)
        elif state == getattr(self.lldb, "eStateDetached", None):
            self._on_detached()

    def _on_exit(self) -> None:
        code = self.session.process.GetExitStatus()
        self._drain_output()
        self._flush_output_decoders()
        claimed, artifact = self._claim_shutdown()
        if not claimed:
            return
        try:
            self.writer.event("exited", {"exitCode": code})
            self.writer.event("terminated")
        finally:
            self._close_session_and_artifact(artifact)

    def _on_detached(self) -> None:
        self._flush_output_decoders()
        claimed, artifact = self._claim_shutdown()
        if not claimed:
            return
        try:
            self.writer.event("terminated")
        finally:
            self._close_session_and_artifact(artifact)

    def _on_stop(self) -> None:
        process = getattr(self.session, "process", None)
        thread_id = self._stopped_thread_id()
        if thread_id is None:
            selected = process.GetSelectedThread()
            if selected.IsValid():
                reason = "entry" if self._await_entry else "pause"
                self._await_entry = False
                self.session.reset_handles()
                self._send_stopped(reason, selected.GetThreadID())
            return
        thread = process.GetThreadByID(thread_id)
        log_message = self.session.logpoint_message(thread)
        if log_message is not None:
            self.output("console", log_message + "\n")
            self.session.cont()
            return
        self.session.reset_handles()
        if self._await_entry:
            self._await_entry = False
            reason = "entry"
        else:
            reason = self._dap_stop_reason(thread.GetStopReason())
        self._send_stopped(reason, thread_id)

    def _send_stopped(self, reason, thread_id) -> None:
        self.writer.event(
            "stopped",
            {
                "reason": reason,
                "threadId": thread_id,
                "allThreadsStopped": True,
            },
        )

    def _stopped_thread_id(self):
        process = self.session.process
        if process is None:
            return None
        for thread in process:
            if thread.GetStopReason() not in (self.lldb.eStopReasonNone, self.lldb.eStopReasonInvalid):
                return thread.GetThreadID()
        return None

    def _drain_output(self) -> None:
        process = getattr(self.session, "process", None)
        if not process:
            return
        for category, read in (("stdout", process.GetSTDOUT), ("stderr", process.GetSTDERR)):
            while chunk := read(4096):
                self.output(category, chunk)

    def _send_output(self, category, output) -> None:
        self.writer.event(
            "output",
            {
                "category": category,
                "output": self._output_text(output),
            },
        )

    def _decode_output_chunk(self, category, output):
        decoder = self._output_decoders.get(category)
        if isinstance(output, bytes):
            if decoder is None:
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                self._output_decoders[category] = decoder
            return decoder.decode(output)
        prefix = ""
        if decoder is not None:
            prefix = decoder.decode(b"", final=True)
            del self._output_decoders[category]
        return prefix + self._output_text(output)

    def _flush_output_decoders(self) -> None:
        decoders = self._output_decoders
        self._output_decoders = {}
        for category, decoder in decoders.items():
            if output := decoder.decode(b"", final=True):
                self._send_output(category, output)

    def _is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._running

    def _claim_shutdown(self):
        with self._lifecycle_lock:
            self._running = False
            self._events_enabled.set()
            if self._terminated:
                return False, None
            self._terminated = True
            artifact = self._artifact
            self._artifact = None
            self._launch = None
            return True, artifact

    def _close_session_and_artifact(self, artifact) -> None:
        try:
            self.session.close()
        finally:
            if artifact is not None:
                artifact.cleanup()

    def _dap_stop_reason(self, reason):
        mapping = {
            self.lldb.eStopReasonBreakpoint: "breakpoint",
            self.lldb.eStopReasonPlanComplete: "step",
            self.lldb.eStopReasonWatchpoint: "data breakpoint",
            self.lldb.eStopReasonSignal: "exception",
            self.lldb.eStopReasonException: "exception",
        }
        return mapping.get(reason, "pause")

    @staticmethod
    def _output_text(output):
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        if not isinstance(output, str):
            output = str(output)
        return output.encode("utf-8", errors="replace").decode("utf-8")


class BtrcDebugAdapter:
    """Own DAP request parsing, validation, dispatch, and stage composition."""

    def __init__(
        self,
        stdin,
        stdout,
        *,
        program_builder_factory=ProgramBuilder,
        lldb_module=lldb,
        session=None,
    ):
        self.reader = DapReader(stdin)
        self.writer = DapWriter(stdout)
        self.session = LldbSession(lldb_module) if session is None else session
        self._program_builder_factory = program_builder_factory
        self.coordinates = DapCoordinates()
        self.events = ProcessEventLoop(self.session, self.writer)

    def run(self) -> None:
        try:
            while True:
                try:
                    message = self.reader.read()
                except DapProtocolError as error:
                    sys.stderr.write(f"btrc debug adapter: protocol error: {error}\n")
                    break
                if message is None:
                    break
                if message.get("type") != "request":
                    continue
                shape_error = self._request_shape_error(message)
                if shape_error is not None:
                    if self._can_respond(message):
                        self.writer.respond(message, success=False, message=shape_error)
                        continue
                    sys.stderr.write(f"btrc debug adapter: {shape_error}\n")
                    break
                command = message["command"]
                handler = getattr(self, "do_" + command, None)
                try:
                    if handler is None:
                        self.writer.respond(message, success=False, message=f"unsupported request: {command}")
                    else:
                        handler(message)
                except Exception as error:
                    self.writer.respond(message, success=False, message=str(error))
                if command == "disconnect":
                    break
        finally:
            self.events.terminate()

    def do_initialize(self, request) -> None:
        self.coordinates = DapCoordinates.from_initialize(self._arguments(request))
        self.writer.respond(
            request,
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

    def do_launch(self, request) -> None:
        if self.events.has_launch:
            raise RuntimeError("launch has already been processed")
        configuration = LaunchConfig.from_arguments(self._arguments(request))
        try:
            builder = self._program_builder_factory(
                configuration.btrcpy_command,
                c_compiler=configuration.cc,
                c_flags=configuration.cflags,
                cwd=configuration.compiler_cwd,
            )
            artifact = builder.build(configuration.program)
        except BuildError as error:
            self.events.output("stderr", str(error) + "\n")
            self.writer.respond(request, success=False, message="build failed")
            self.writer.event("terminated")
            return
        try:
            self.session.create_target(artifact.executable)
        except Exception:
            artifact.cleanup()
            raise
        self.events.stage_launch(configuration, artifact)
        self.writer.respond(request)

    def do_setBreakpoints(self, request) -> None:
        arguments = self._arguments(request)
        source = arguments.get("source")
        if not isinstance(source, dict):
            raise ValueError("setBreakpoints: 'source' must be an object")
        path = source.get("path") or source.get("name")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("setBreakpoints: source path is required")
        path = self.coordinates.client_path_to_native(path)
        specs = self._breakpoint_specs(arguments, minimum_line=self.coordinates.minimum_line)
        debugger_specs = [{**spec, "line": self.coordinates.client_line_to_debugger(spec["line"])} for spec in specs]
        verified = self.session.set_breakpoints(path, debugger_specs) if self.session.target else []
        for breakpoint in verified:
            if "line" in breakpoint:
                breakpoint["line"] = self.coordinates.debugger_line_to_client(breakpoint["line"])
        self.writer.respond(request, body={"breakpoints": verified})

    def do_setExceptionBreakpoints(self, request) -> None:
        self.writer.respond(request, body={"breakpoints": []})

    def do_configurationDone(self, request) -> None:
        try:
            self.events.prepare()
            self.writer.respond(request)
        except Exception:
            self.events.terminate()
            raise
        self.events.enable()

    def do_threads(self, request) -> None:
        self.writer.respond(request, body={"threads": self.session.threads()})

    def do_stackTrace(self, request) -> None:
        thread_id = self._required_int(self._arguments(request), "threadId", "stackTrace")
        frames = self.session.stack_frames(thread_id)
        for frame in frames:
            frame["line"] = self.coordinates.debugger_line_to_client(frame.get("line", 0))
            frame["column"] = self.coordinates.debugger_column_to_client(frame.get("column", 0))
            source = frame.get("source")
            if source and source.get("path"):
                source["path"] = self.coordinates.native_path_to_client(source["path"])
        self.writer.respond(request, body={"stackFrames": frames, "totalFrames": len(frames)})

    def do_scopes(self, request) -> None:
        frame_id = self._required_int(self._arguments(request), "frameId", "scopes")
        self.writer.respond(request, body={"scopes": self.session.scopes(frame_id)})

    def do_variables(self, request) -> None:
        reference = self._required_int(self._arguments(request), "variablesReference", "variables")
        self.writer.respond(request, body={"variables": self.session.variables(reference)})

    def do_evaluate(self, request) -> None:
        arguments = self._arguments(request)
        expression = arguments.get("expression")
        if not isinstance(expression, str):
            raise ValueError("evaluate: 'expression' must be a string")
        frame_id = self._optional_int(arguments, "frameId", "evaluate")
        result = self.session.evaluate(frame_id, expression)
        if result is None:
            self.writer.respond(request, success=False, message="cannot evaluate")
        else:
            self.writer.respond(request, body=result)

    def do_continue(self, request) -> None:
        self.session.cont()
        self.writer.respond(request, body={"allThreadsContinued": True})

    def do_next(self, request) -> None:
        thread_id = self._optional_int(self._arguments(request), "threadId", "next")
        self.session.step_over(thread_id)
        self.writer.respond(request)

    def do_stepIn(self, request) -> None:
        thread_id = self._optional_int(self._arguments(request), "threadId", "stepIn")
        self.session.step_into(thread_id)
        self.writer.respond(request)

    def do_stepOut(self, request) -> None:
        thread_id = self._optional_int(self._arguments(request), "threadId", "stepOut")
        self.session.step_out(thread_id)
        self.writer.respond(request)

    def do_pause(self, request) -> None:
        self.session.pause()
        self.writer.respond(request)

    def do_terminate(self, request) -> None:
        terminated = self.events.terminate()
        self.writer.respond(request)
        if terminated:
            self.writer.event("terminated")

    def do_disconnect(self, request) -> None:
        self.events.terminate()
        self.writer.respond(request)

    @staticmethod
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

    @staticmethod
    def _can_respond(request) -> bool:
        sequence = request.get("seq")
        return (
            isinstance(sequence, int)
            and not isinstance(sequence, bool)
            and sequence >= 1
            and isinstance(request.get("command"), str)
            and bool(request["command"])
        )

    @staticmethod
    def _arguments(request):
        return request.get("arguments", {})

    @classmethod
    def _required_int(cls, arguments, name, command):
        value = cls._optional_int(arguments, name, command)
        if value is None:
            raise ValueError(f"{command}: missing '{name}'")
        return value

    @staticmethod
    def _optional_int(arguments, name, command):
        value = arguments.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{command}: '{name}' must be a positive integer")
        return value

    @staticmethod
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
