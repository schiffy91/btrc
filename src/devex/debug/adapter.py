"""btrc Debug Adapter Protocol server.

Speaks DAP over stdio and drives lldb (via :class:`LldbSession`) so VSCode can
debug .btrc programs natively: breakpoints, stepping, call stack, and
btrc-aware variable inspection. Run via ``btrc_dap.py`` (which bootstraps the
lldb-capable interpreter first).
"""

from __future__ import annotations

import os
import sys
import threading

import lldb  # noqa: E402  (available after bootstrap)

import builder
from dap_io import DapReader, DapWriter
from lldb_session import LldbSession


class BtrcAdapter:
    def __init__(self, stdin, stdout):
        self.reader = DapReader(stdin)
        self.writer = DapWriter(stdout)
        self.session = LldbSession(lldb)
        self._launch = None          # stored launch config until configurationDone
        self._program = None         # built binary path
        self._cwd = None
        self._running = False
        self._event_thread = None
        self._await_entry = False     # report the first (reasonless) stop as "entry"

    # --- main loop ---

    def run(self):
        while True:
            msg = self.reader.read()
            if msg is None:
                break
            if msg.get("type") != "request":
                continue
            handler = getattr(self, "do_" + msg["command"], None)
            try:
                if handler is None:
                    self.writer.respond(msg, success=False,
                                        message=f"unsupported request: {msg['command']}")
                else:
                    handler(msg)
            except Exception as e:  # noqa: BLE001  report, don't crash the session
                self.writer.respond(msg, success=False, message=str(e))
            if msg["command"] == "disconnect":
                break

    # --- request handlers ---

    def do_initialize(self, req):
        self.writer.respond(req, body={
            "supportsConfigurationDoneRequest": True,
            "supportsEvaluateForHovers": True,
            "supportsTerminateRequest": True,
            "supportsConditionalBreakpoints": True,
            "supportsHitConditionalBreakpoints": True,
            "supportsLogPoints": True,
        })
        self.writer.event("initialized")

    def do_launch(self, req):
        args = req.get("arguments", {})
        program = args.get("program")
        if not program:
            raise RuntimeError("launch: missing 'program' (.btrc file)")
        btrcpy_cmd = args.get("btrcpy") or [sys.executable, "-m",
                                            "src.compiler.python.main"]
        if isinstance(btrcpy_cmd, str):
            btrcpy_cmd = btrcpy_cmd.split()
        cc = args.get("cc", "cc")
        self._cwd = args.get("cwd") or os.path.dirname(os.path.abspath(program))
        try:
            self._program = builder.build(
                program, btrcpy_cmd=btrcpy_cmd, cc=cc, cflags=args.get("cflags"),
                cwd=args.get("btrcpyCwd") or self._cwd)
        except builder.BuildError as e:
            self._output("stderr", str(e) + "\n")
            self.writer.respond(req, success=False, message="build failed")
            self.writer.event("terminated")
            return
        self.session.create_target(self._program)
        self._launch = {
            "argv": args.get("args", []),
            "stop_on_entry": bool(args.get("stopOnEntry", False)),
        }
        self.writer.respond(req)

    def do_setBreakpoints(self, req):
        args = req["arguments"]
        source = args.get("source", {})
        path = source.get("path") or source.get("name")
        specs = args.get("breakpoints")
        if specs is None:
            specs = [{"line": ln} for ln in args.get("lines", [])]
        verified = self.session.set_breakpoints(path, specs) if self.session.target else []
        self.writer.respond(req, body={"breakpoints": verified})

    def do_setExceptionBreakpoints(self, req):
        self.writer.respond(req, body={"breakpoints": []})

    def do_configurationDone(self, req):
        self.writer.respond(req)
        self._await_entry = self._launch["stop_on_entry"]
        self.session.start(self._program, self._launch["argv"], self._cwd,
                           self._launch["stop_on_entry"])
        self._running = True
        self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._event_thread.start()

    def do_threads(self, req):
        self.writer.respond(req, body={"threads": self.session.threads()})

    def do_stackTrace(self, req):
        tid = req["arguments"]["threadId"]
        frames = self.session.stack_frames(tid)
        self.writer.respond(req, body={"stackFrames": frames,
                                       "totalFrames": len(frames)})

    def do_scopes(self, req):
        self.writer.respond(req, body={
            "scopes": self.session.scopes(req["arguments"]["frameId"])})

    def do_variables(self, req):
        ref = req["arguments"]["variablesReference"]
        self.writer.respond(req, body={"variables": self.session.variables(ref)})

    def do_evaluate(self, req):
        args = req["arguments"]
        res = self.session.evaluate(args.get("frameId"), args.get("expression", ""))
        if res is None:
            self.writer.respond(req, success=False, message="cannot evaluate")
        else:
            self.writer.respond(req, body=res)

    def do_continue(self, req):
        self.writer.respond(req, body={"allThreadsContinued": True})
        self.session.cont()

    def do_next(self, req):
        self.writer.respond(req)
        self.session.step_over(req["arguments"].get("threadId"))

    def do_stepIn(self, req):
        self.writer.respond(req)
        self.session.step_into(req["arguments"].get("threadId"))

    def do_stepOut(self, req):
        self.writer.respond(req)
        self.session.step_out(req["arguments"].get("threadId"))

    def do_pause(self, req):
        self.writer.respond(req)
        self.session.pause()

    def do_terminate(self, req):
        self.session.terminate()
        self.writer.respond(req)

    def do_disconnect(self, req):
        self._running = False
        self.session.terminate()
        self.writer.respond(req)

    # --- lldb event loop ---

    def _event_loop(self):
        while self._running:
            event = lldb.SBEvent()
            if not self.session.listener.WaitForEvent(1, event):
                continue
            if not lldb.SBProcess.EventIsProcessEvent(event):
                continue
            self._drain_output()
            state = lldb.SBProcess.GetStateFromEvent(event)
            if state == lldb.eStateStopped:
                # A stop event whose process was auto-restarted (e.g. a
                # conditional breakpoint whose condition was false) is not a real
                # user-visible stop — lldb resumes it itself.
                if lldb.SBProcess.GetRestartedFromEvent(event):
                    continue
                self._on_stop()
            elif state == lldb.eStateExited:
                code = self.session.process.GetExitStatus()
                self._drain_output()
                self.writer.event("exited", {"exitCode": code})
                self.writer.event("terminated")
                self._running = False
            elif state == lldb.eStateCrashed:
                self.writer.event("stopped", {"reason": "exception",
                                              "threadId": self._stopped_tid(),
                                              "allThreadsStopped": True})

    def _on_stop(self):
        proc = self.session.process
        tid = self._stopped_tid()
        if tid is None:
            # The stop-on-entry halt carries no breakpoint/step reason; surface
            # it once as an "entry" stop. Any other reasonless stop is transient
            # (e.g. a false conditional breakpoint lldb auto-resumes) — ignore it.
            if self._await_entry:
                self._await_entry = False
                sel = proc.GetSelectedThread()
                if sel.IsValid():
                    self.session.reset_handles()
                    self.writer.event("stopped", {
                        "reason": "entry",
                        "threadId": sel.GetThreadID(),
                        "allThreadsStopped": True,
                    })
            return
        thread = proc.GetThreadByID(tid)
        # Logpoint: print its (interpolated) message and resume without stopping.
        logmsg = self.session.logpoint_message(thread)
        if logmsg is not None:
            self._output("console", logmsg + "\n")
            self.session.cont()
            return
        self.session.reset_handles()
        if self._await_entry:
            self._await_entry = False
            reason = "entry"   # first stop under stopOnEntry, whatever lldb called it
        else:
            reason = _dap_stop_reason(thread.GetStopReason())
        self.writer.event("stopped", {
            "reason": reason,
            "threadId": tid,
            "allThreadsStopped": True,
        })

    def _stopped_tid(self):
        # Return a thread with a genuine stop reason; None for transient stops
        # (e.g. a conditional breakpoint whose condition was false and which lldb
        # auto-resumes) so we don't surface a spurious "pause" to the client.
        proc = self.session.process
        for t in proc:
            if t.GetStopReason() not in (lldb.eStopReasonNone,
                                         lldb.eStopReasonInvalid):
                return t.GetThreadID()
        return None

    def _drain_output(self):
        proc = self.session.process
        if not proc:
            return
        while True:
            chunk = proc.GetSTDOUT(4096)
            if not chunk:
                break
            self._output("stdout", chunk)
        while True:
            chunk = proc.GetSTDERR(4096)
            if not chunk:
                break
            self._output("stderr", chunk)

    def _output(self, category, text):
        self.writer.event("output", {"category": category, "output": text})


def _dap_stop_reason(reason):
    mapping = {
        lldb.eStopReasonBreakpoint: "breakpoint",
        lldb.eStopReasonPlanComplete: "step",
        lldb.eStopReasonWatchpoint: "data breakpoint",
        lldb.eStopReasonSignal: "exception",
        lldb.eStopReasonException: "exception",
    }
    return mapping.get(reason, "pause")


def main():
    BtrcAdapter(sys.stdin.buffer, sys.stdout.buffer).run()
