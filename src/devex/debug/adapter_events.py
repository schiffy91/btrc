"""LLDB event translation and lifecycle ownership for the DAP adapter."""

from __future__ import annotations

import codecs
import sys
import threading
from contextlib import suppress

import lldb


class AdapterEventsMixin:
    """Own the listener thread and make process shutdown single-owner."""

    def _prepare_event_loop(self):
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

    def _enable_events(self):
        self._events_enabled.set()

    def _event_loop(self):
        self._events_enabled.wait()
        try:
            while self._is_running():
                event = lldb.SBEvent()
                if not self.session.listener.WaitForEvent(1, event):
                    continue
                if not self._is_running():
                    break
                if not lldb.SBProcess.EventIsProcessEvent(event):
                    continue
                self._handle_process_event(event)
        except Exception as error:
            sys.stderr.write(f"btrc debug adapter: event loop failed: {error}\n")
            try:
                terminated = self._terminate_and_cleanup()
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

    def _handle_process_event(self, event):
        self._drain_output()
        state = lldb.SBProcess.GetStateFromEvent(event)
        if state == lldb.eStateStopped:
            if not lldb.SBProcess.GetRestartedFromEvent(event):
                self._on_stop()
        elif state == lldb.eStateExited:
            self._on_exit()
        elif state == lldb.eStateCrashed:
            body = {"reason": "exception", "allThreadsStopped": True}
            thread_id = self._stopped_tid()
            if thread_id is not None:
                body["threadId"] = thread_id
            self.writer.event("stopped", body)
        elif state == getattr(lldb, "eStateDetached", None):
            self._on_detached()

    def _on_exit(self):
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

    def _on_detached(self):
        self._flush_output_decoders()
        claimed, artifact = self._claim_shutdown()
        if not claimed:
            return
        try:
            self.writer.event("terminated")
        finally:
            self._close_session_and_artifact(artifact)

    def _on_stop(self):
        process = getattr(self.session, "process", None)
        thread_id = self._stopped_tid()
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
            self._output("console", log_message + "\n")
            self.session.cont()
            return
        self.session.reset_handles()
        if self._await_entry:
            self._await_entry = False
            reason = "entry"
        else:
            reason = _dap_stop_reason(thread.GetStopReason())
        self._send_stopped(reason, thread_id)

    def _send_stopped(self, reason, thread_id):
        self.writer.event(
            "stopped",
            {
                "reason": reason,
                "threadId": thread_id,
                "allThreadsStopped": True,
            },
        )

    def _stopped_tid(self):
        process = self.session.process
        if process is None:
            return None
        for thread in process:
            if thread.GetStopReason() not in (lldb.eStopReasonNone, lldb.eStopReasonInvalid):
                return thread.GetThreadID()
        return None

    def _drain_output(self):
        process = getattr(self.session, "process", None)
        if not process:
            return
        for category, read in (("stdout", process.GetSTDOUT), ("stderr", process.GetSTDERR)):
            while chunk := read(4096):
                self._output(category, chunk)

    def _output(self, category, output):
        output = self._decode_output_chunk(category, output)
        if not output:
            return
        self._send_output(category, output)

    def _send_output(self, category, output):
        self.writer.event(
            "output",
            {
                "category": category,
                "output": _output_text(output),
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
        return prefix + _output_text(output)

    def _flush_output_decoders(self):
        decoders = self._output_decoders
        self._output_decoders = {}
        for category, decoder in decoders.items():
            if output := decoder.decode(b"", final=True):
                self._send_output(category, output)

    def _is_running(self):
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
            self._program = None
            self._launch = None
            return True, artifact

    def _terminate_and_cleanup(self):
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

    def _close_session_and_artifact(self, artifact):
        try:
            close = getattr(self.session, "close", None)
            if close is not None:
                close()
        finally:
            self._cleanup_owned_artifact(artifact)

    @staticmethod
    def _cleanup_owned_artifact(artifact):
        if artifact is not None:
            artifact.cleanup()


def _output_text(output):
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    if not isinstance(output, str):
        output = str(output)
    return output.encode("utf-8", errors="replace").decode("utf-8")


def _dap_stop_reason(reason):
    mapping = {
        lldb.eStopReasonBreakpoint: "breakpoint",
        lldb.eStopReasonPlanComplete: "step",
        lldb.eStopReasonWatchpoint: "data breakpoint",
        lldb.eStopReasonSignal: "exception",
        lldb.eStopReasonException: "exception",
    }
    return mapping.get(reason, "pause")
