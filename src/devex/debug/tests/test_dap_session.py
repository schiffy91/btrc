"""Integration test for the btrc debug adapter: a real DAP session over lldb.

Skips gracefully where the toolchain is unavailable (no lldb / no C compiler),
so it is safe in CI; where lldb exists it exercises the whole path — build,
breakpoint, stop, stack, btrc-aware variables, step, and program output.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
ADAPTER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "btrc_dap.py")

def _lldb_scripting_available() -> bool:
    """lldb's binary can exist while its Python scripting bridge is unavailable
    (e.g. an lldb built against a different Python than the one on PATH). The
    adapter loads lldb via `lldb -P`; when that fails the session can't even
    initialize, so skip rather than fail — matching this module's "skips
    gracefully where the toolchain is unavailable" contract."""
    lldb = shutil.which("lldb")
    if lldb is None:
        return False
    try:
        return subprocess.run(
            [lldb, "-P"], capture_output=True).returncode == 0
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _lldb_scripting_available()
    or (shutil.which("cc") is None and shutil.which("gcc") is None),
    reason="needs lldb (with Python scripting) and a C compiler",
)

PROGRAM = """\
class Point { public int x; public int y;
  public Point(int x, int y) { self.x = x; self.y = y; } }
int main() {
  Vector<int> v = [10, 20, 30];
  string s = "hi";
  Point p = Point(3, 4);
  print(v.len);
  return 0;
}
"""
BP_LINE = 7  # print(v.len)


class DapClient:
    def __init__(self, proc):
        self.proc = proc
        self.seq = 0
        self.responses = {}
        self.events = []
        self.cv = threading.Condition()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        f = self.proc.stdout
        while True:
            n = None
            while True:
                line = f.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    break
                if line.lower().startswith(b"content-length:"):
                    n = int(line.split(b":", 1)[1])
            if n is None:
                continue
            msg = json.loads(f.read(n))
            with self.cv:
                if msg.get("type") == "response":
                    self.responses[msg["request_seq"]] = msg
                elif msg.get("type") == "event":
                    self.events.append(msg)
                self.cv.notify_all()

    def request(self, command, args=None, timeout=60):
        self.seq += 1
        s = self.seq
        body = json.dumps({"seq": s, "type": "request",
                           "command": command, "arguments": args or {}}).encode()
        self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
        self.proc.stdin.flush()
        with self.cv:
            end = time.time() + timeout
            while s not in self.responses and time.time() < end:
                self.cv.wait(0.2)
            return self.responses.get(s)

    def wait_event(self, name, timeout=60):
        with self.cv:
            end = time.time() + timeout
            while time.time() < end:
                for e in self.events:
                    if e["event"] == name:
                        self.events.remove(e)
                        return e
                self.cv.wait(0.2)
            return None


LOOP_PROGRAM = """\
int main() {
  int sum = 0;
  for (int i = 0; i < 5; i = i + 1) {
    sum = sum + i * 10;
  }
  print(sum);
  return 0;
}
"""


def _spawn(tmp_path, program, name="prog", stop_on_entry=False):
    prog = tmp_path / f"{name}.btrc"
    prog.write_text(program)
    proc = subprocess.Popen(
        [sys.executable, ADAPTER], cwd=REPO,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    c = DapClient(proc)
    assert c.request("initialize", {"adapterID": "btrc"})["success"]
    c.wait_event("initialized")
    assert c.request("launch", {
        "program": str(prog),
        "btrcpy": [sys.executable, "-m", "src.compiler.python.main"],
        "btrcpyCwd": REPO,
        "stopOnEntry": stop_on_entry,
    })["success"]
    return proc, c, prog


def test_stop_on_entry(tmp_path):
    proc, c, prog = _spawn(tmp_path, LOOP_PROGRAM, name="entry", stop_on_entry=True)
    try:
        c.request("setBreakpoints", {"source": {"path": str(prog)}, "breakpoints": []})
        c.request("configurationDone")
        stop = c.wait_event("stopped")
        assert stop and stop["body"]["reason"] == "entry", stop
        c.request("disconnect")
    finally:
        proc.kill()


def test_logpoint_prints_without_stopping(tmp_path):
    proc, c, prog = _spawn(tmp_path, LOOP_PROGRAM, name="log")
    try:
        c.request("setBreakpoints", {
            "source": {"path": str(prog)},
            "breakpoints": [{"line": 4, "logMessage": "iter i={i}"}]})
        c.request("configurationDone")
        assert c.wait_event("terminated", timeout=30) is not None
        time.sleep(0.3)  # let any trailing output events arrive
        # The logpoint fires every iteration and auto-resumes (no stop).
        out = "".join(e["body"]["output"] for e in c.events if e["event"] == "output")
        assert "iter i=0" in out and "iter i=4" in out, out
        assert not any(e["event"] == "stopped" for e in c.events)
        c.request("disconnect")
    finally:
        proc.kill()


def test_conditional_breakpoint_stops_at_the_right_iteration(tmp_path):
    proc, c, prog = _spawn(tmp_path, LOOP_PROGRAM, name="loop")
    try:
        bps = c.request("setBreakpoints", {
            "source": {"path": str(prog)},
            "breakpoints": [{"line": 4, "condition": "i == 3"}]})
        assert bps["body"]["breakpoints"][0]["verified"]
        c.request("configurationDone")
        stop = c.wait_event("stopped")
        assert stop and stop["body"]["reason"] == "breakpoint"
        tid = stop["body"]["threadId"]
        frames = c.request("stackTrace", {"threadId": tid})["body"]["stackFrames"]
        scope = c.request("scopes", {"frameId": frames[0]["id"]}) \
            ["body"]["scopes"][0]["variablesReference"]
        vals = {v["name"]: v["value"]
                for v in c.request("variables", {"variablesReference": scope})["body"]["variables"]}
        # Condition i==3 ⇒ sum has accumulated 0 + 10 + 20 = 30 (before this iter).
        assert vals.get("sum") == "30", vals
        c.request("disconnect")
    finally:
        proc.kill()


def test_full_debug_session(tmp_path):
    prog = tmp_path / "prog.btrc"
    prog.write_text(PROGRAM)
    proc = subprocess.Popen(
        [sys.executable, ADAPTER], cwd=REPO,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        c = DapClient(proc)
        assert c.request("initialize", {"adapterID": "btrc"})["success"]
        assert c.wait_event("initialized") is not None
        launch = c.request("launch", {
            "program": str(prog),
            "btrcpy": [sys.executable, "-m", "src.compiler.python.main"],
            "btrcpyCwd": REPO,
            "stopOnEntry": False,
        })
        assert launch["success"], launch
        bps = c.request("setBreakpoints", {
            "source": {"path": str(prog)},
            "breakpoints": [{"line": BP_LINE}]})
        assert bps["body"]["breakpoints"][0]["verified"]
        c.request("configurationDone")

        stop = c.wait_event("stopped")
        assert stop and stop["body"]["reason"] == "breakpoint"
        tid = stop["body"]["threadId"]

        frames = c.request("stackTrace", {"threadId": tid})["body"]["stackFrames"]
        assert frames[0]["source"]["name"] == "prog.btrc"
        assert frames[0]["line"] == BP_LINE

        scope_ref = c.request("scopes", {"frameId": frames[0]["id"]}) \
            ["body"]["scopes"][0]["variablesReference"]
        variables = c.request("variables", {"variablesReference": scope_ref})["body"]["variables"]
        byname = {v["name"]: v["value"] for v in variables}
        assert "10" in byname["v"] and "30" in byname["v"]      # Vector summary
        assert "hi" in byname["s"]                              # string text
        assert "3" in byname["p"] and "4" in byname["p"]        # class fields

        # watch/console evaluation accepts btrc member syntax (p.x -> p->x)
        ev = c.request("evaluate", {"expression": "p.x", "frameId": frames[0]["id"],
                                    "context": "watch"})
        assert ev["success"] and ev["body"]["result"] == "3", ev

        # step over, then run to completion and capture output (v.len == 3)
        c.request("next", {"threadId": tid})
        assert c.wait_event("stopped")["body"]["reason"] == "step"
        c.request("continue", {"threadId": tid})
        out = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            e = c.wait_event("output", timeout=2)
            if e:
                out += e["body"]["output"]
            if "3" in out:
                break
        assert out.strip() == "3", repr(out)
        c.request("disconnect")
    finally:
        proc.kill()
