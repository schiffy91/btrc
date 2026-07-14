"""lldb wrapper for the btrc debug adapter.

Owns the SBDebugger/SBTarget/SBProcess and translates between DAP concepts
(threads, frames, scopes, variables, breakpoints by .btrc location) and lldb.
Because the generated C carries ``#line`` directives, lldb already resolves
breakpoints and frames in .btrc source coordinates — this layer just shuttles
them across, applying btrc-aware value rendering from :mod:`summaries`.
"""

from __future__ import annotations

import os

import summaries
from lldb_translation import dot_to_arrow as _dot_to_arrow
from lldb_translation import filespec_path as _filespec_path
from lldb_translation import require_success as _require_success
from lldb_translation import source_identity as _source_identity
from lldb_translation import thread_name as _thread_name


class LldbSession:
    def __init__(self, lldb_module):
        self.lldb = lldb_module
        self.debugger = lldb_module.SBDebugger.Create()
        self.debugger.SetAsync(True)
        self.target = None
        self.process = None
        self.listener = self.debugger.GetListener()
        # DAP handle registries, rebuilt on every stop (lldb objects are only
        # valid while the process is stopped).
        self._frames = {}  # frameId -> SBFrame
        self._vars = {}  # variablesReference -> ('locals', frame) | ('value', SBValue)
        self._next_id = 1
        self._logpoints = {}  # breakpoint id -> logMessage (auto-continue + print)
        self._breakpoints_by_source = {}  # canonical source path -> breakpoint ids
        self._closed = False

    # --- lifecycle ---

    def create_target(self, program):
        """Create the debug target (so breakpoints can bind before the run)."""
        self.target = self.debugger.CreateTarget(program)
        if not self.target.IsValid():
            raise RuntimeError(f"could not create debug target for {program}")
        self._logpoints.clear()
        self._breakpoints_by_source.clear()
        return self.target

    def start(self, program, argv, cwd, stop_on_entry):
        """Launch the process under the debugger's listener (async)."""
        flags = self.lldb.eLaunchFlagNone
        err = self.lldb.SBError()
        self.process = self.target.Launch(
            self.listener,
            argv or [],
            None,
            None,
            None,
            None,
            cwd or os.path.dirname(program) or ".",
            flags,
            stop_on_entry,
            err,
        )
        if not err.Success():
            raise RuntimeError(err.GetCString() or "launch failed")
        if not self.process or not self.process.IsValid():
            raise RuntimeError("launch returned an invalid process")
        return self.process

    def terminate(self):
        if self.process and self.process.IsValid():
            if self.process.GetState() in {
                self.lldb.eStateExited,
                self.lldb.eStateDetached,
                self.lldb.eStateInvalid,
            }:
                return
            _require_success(self.process.Kill(), "terminate process")

    def close(self):
        """Release the process-independent LLDB debugger exactly once."""
        if self._closed:
            return
        self._closed = True
        self.reset_handles()
        self.target = None
        self.process = None
        self.lldb.SBDebugger.Destroy(self.debugger)

    # --- breakpoints ---

    def set_breakpoints(self, source_path, specs):
        """Replace breakpoints for *source_path* with ones from *specs*.

        Each spec is a DAP SourceBreakpoint (``line`` plus optional
        ``condition``, ``hitCondition``, ``logMessage``). Returns DAP Breakpoint
        dicts (verified + resolved line)."""
        source_location, source_key = _source_identity(source_path)
        for bid in self._breakpoints_by_source.pop(source_key, set()):
            self.target.BreakpointDelete(bid)
            self._logpoints.pop(bid, None)

        results = []
        breakpoint_ids = set()
        for spec in specs:
            line = spec["line"]
            bp = self.target.BreakpointCreateByLocation(source_location, line)
            breakpoint_ids.add(bp.GetID())
            cond = spec.get("condition")
            if cond:
                bp.SetCondition(cond)
            hit = spec.get("hitCondition")
            if hit and str(hit).strip().isdigit():
                bp.SetIgnoreCount(max(0, int(hit) - 1))
            if spec.get("logMessage"):
                self._logpoints[bp.GetID()] = spec["logMessage"]
            verified = bp.GetNumLocations() > 0
            resolved_line = line
            if verified:
                le = bp.GetLocationAtIndex(0).GetAddress().GetLineEntry()
                resolved_line = le.GetLine() or line
            results.append({"verified": bool(verified), "line": resolved_line})
        self._breakpoints_by_source[source_key] = breakpoint_ids
        return results

    def logpoint_message(self, thread):
        """If the thread stopped at a logpoint, render its message (with {expr}
        interpolation against the top frame) and return it; else None."""
        if thread.GetStopReason() != self.lldb.eStopReasonBreakpoint:
            return None
        # A breakpoint stop carries (bp_id, loc_id) pairs in its stop-reason data.
        for i in range(0, thread.GetStopReasonDataCount(), 2):
            bp_id = thread.GetStopReasonDataAtIndex(i)
            msg = self._logpoints.get(bp_id)
            if msg is not None:
                return self._interpolate(thread.GetFrameAtIndex(0), msg)
        return None

    def _interpolate(self, frame, msg):
        import re

        def repl(m):
            val = frame.EvaluateExpression(m.group(1))
            if val and val.IsValid() and not val.GetError().Fail():
                return summaries.summarize(val)
            return m.group(0)

        return re.sub(r"\{([^}]+)\}", repl, msg)

    # --- stop bookkeeping ---

    def reset_handles(self):
        self._frames.clear()
        self._vars.clear()
        self._next_id = 1

    def _alloc(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # --- threads / frames ---

    def threads(self):
        out = []
        if not self.process:
            return out
        for t in self.process:
            out.append({"id": t.GetThreadID(), "name": _thread_name(t)})
        return out

    def stack_frames(self, thread_id):
        thread = self.process.GetThreadByID(thread_id)
        frames = []
        for fr in thread:
            fid = self._alloc()
            self._frames[fid] = fr
            line_entry = fr.GetLineEntry()
            fe = line_entry.GetFileSpec()
            path = _filespec_path(fe)
            frame = {
                "id": fid,
                "name": fr.GetFunctionName() or fr.GetDisplayFunctionName() or "??",
                "line": line_entry.GetLine(),
                "column": line_entry.GetColumn() or 0,
            }
            if path:
                frame["source"] = {"name": os.path.basename(path), "path": path}
            frames.append(frame)
        return frames

    # --- scopes / variables ---

    def scopes(self, frame_id):
        frame = self._frames.get(frame_id)
        if frame is None:
            return []
        ref = self._alloc()
        self._vars[ref] = ("locals", frame)
        return [{"name": "Locals", "variablesReference": ref, "expensive": False}]

    def variables(self, var_ref):
        src = self._vars.get(var_ref)
        if src is None:
            return []
        kind, payload = src
        if kind == "locals":
            frame = payload
            sbvals = frame.GetVariables(True, True, False, True)  # args + locals
            out = []
            for i in range(sbvals.GetSize()):
                v = sbvals.GetValueAtIndex(i)
                name = v.GetName() or ""
                if name.startswith("__"):  # compiler temporaries / ARC bookkeeping
                    continue
                out.append(self._var_dict(v))
            return out
        # kind == "value": expand a structured btrc value
        return [self._var_dict(child, name) for name, child in summaries.children(payload)]

    def _var_dict(self, sbval, name_override=None):
        name = name_override if name_override is not None else (sbval.GetName() or "?")
        value_str = summaries.summarize(sbval)
        ref = 0
        if summaries.children(sbval):
            ref = self._alloc()
            self._vars[ref] = ("value", sbval)
        return {
            "name": name,
            "value": value_str,
            "type": sbval.GetTypeName() or "",
            "variablesReference": ref,
        }

    def evaluate(self, frame_id, expression):
        frame = self._frames.get(frame_id)
        if frame is None:
            return None
        val = frame.EvaluateExpression(expression)
        if not val.IsValid() or val.GetError().Fail():
            # Fall back to btrc-style member access: objects are C pointers, so
            # `obj.field` is `obj->field`. Lets watch/hover/console use btrc
            # syntax. (Float literals like 3.14 are left alone.)
            translated = _dot_to_arrow(expression)
            if translated != expression:
                val = frame.EvaluateExpression(translated)
            if not val.IsValid() or val.GetError().Fail():
                return None
        ref = 0
        if summaries.children(val):
            ref = self._alloc()
            self._vars[ref] = ("value", val)
        return {"result": summaries.summarize(val), "type": val.GetTypeName() or "", "variablesReference": ref}

    # --- execution control ---

    def _selected_thread(self, thread_id=None):
        if self.process is None or not self.process.IsValid():
            raise RuntimeError("debug process is not running")
        if thread_id is not None:
            t = self.process.GetThreadByID(thread_id)
            if t.IsValid():
                return t
        thread = self.process.GetSelectedThread()
        if not thread.IsValid():
            raise RuntimeError("no valid debug thread is selected")
        return thread

    def cont(self):
        _require_success(self.process.Continue(), "continue process")

    def step_over(self, thread_id=None):
        self._selected_thread(thread_id).StepOver()

    def step_into(self, thread_id=None):
        self._selected_thread(thread_id).StepInto()

    def step_out(self, thread_id=None):
        self._selected_thread(thread_id).StepOut()

    def pause(self):
        _require_success(self.process.Stop(), "pause process")
