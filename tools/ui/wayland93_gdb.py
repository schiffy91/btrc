"""Executed inside GDB, only by the temporary Wayland diagnostic branch."""

import hashlib
import json
import os
import signal
from pathlib import Path

import gdb


class InferiorEvidence:
    def __init__(self):
        self.directory = Path(os.environ["BTRC_WAYLAND93_CASE"])
        self.status = {"state": "starting"}
        self.libraries = {"loaded": [], "errors": []}
        self.write_libraries()
        self.write()

    def write(self):
        temporary = self.directory / "gdb-status.tmp"
        temporary.write_text(json.dumps(self.status, indent=2) + "\n")
        temporary.replace(self.directory / "gdb-status.json")

    def write_libraries(self):
        temporary = self.directory / "gdb-loaded-libraries.tmp"
        temporary.write_text(json.dumps(self.libraries, indent=2) + "\n")
        temporary.replace(self.directory / "gdb-loaded-libraries.json")

    def loaded(self, event):
        filename = event.new_objfile.filename
        if not filename:
            return
        name = Path(filename).name
        if not (name == "libdecor-gtk.so" or name.startswith("libdecor-0.so") or name.startswith("libSDL3.so")):
            return
        try:
            path = Path(filename).resolve(strict=True)
            record = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            if record not in self.libraries["loaded"]:
                self.libraries["loaded"].append(record)
        except Exception as error:
            self.libraries["errors"].append({"filename": filename, "error": str(error)})
        self.write_libraries()

    def continued(self, _event):
        self.status = {"state": "running", "pid": gdb.selected_inferior().pid}
        self.write()

    def stopped(self, event):
        self.status = {
            "state": "signal" if isinstance(event, gdb.SignalEvent) else "unexpected-stop",
            "signal": getattr(event, "stop_signal", None),
            "pid": gdb.selected_inferior().pid,
        }
        self.write()
        for name, command in (
            ("backtrace", "thread apply all bt full"),
            ("registers", "thread apply all info registers"),
            ("libraries", "info sharedlibrary"),
            ("mappings", "info proc mappings"),
        ):
            try:
                (self.directory / f"gdb-{name}.txt").write_text(gdb.execute(command, to_string=True))
            except Exception as error:
                self.status[name + "_error"] = str(error)
        try:
            core = self.directory / "NativeShell.core"
            gdb.execute(f"generate-core-file {core}", to_string=True)
            self.status["core"] = str(core)
        except Exception as error:
            self.status["core_error"] = str(error)
        self.write()

    def exited(self, event):
        self.write_libraries()
        # A signal receipt remains authoritative if shutdown follows capture.
        if self.status["state"] not in {"signal", "unexpected-stop"}:
            self.status = {
                "state": "exited",
                "exit_code": getattr(event, "exit_code", None),
                "pid": self.status.get("pid"),
            }
            self.write()

    def run(self):
        gdb.events.new_objfile.connect(self.loaded)
        gdb.events.cont.connect(self.continued)
        gdb.events.stop.connect(self.stopped)
        gdb.events.exited.connect(self.exited)
        try:
            for command in (
                "set pagination off",
                "set confirm off",
                "set disable-randomization off",
                "set startup-with-shell off",
                "set print thread-events off",
                "set debuginfod enabled off",
                "run",
            ):
                gdb.execute(command)
        except Exception as error:
            self.status["debugger_error"] = str(error)
            self.write()
        if "debugger_error" in self.status:
            code = 125
        elif self.status["state"] == "exited" and isinstance(self.status.get("exit_code"), int):
            code = self.status["exit_code"]
        else:
            number = getattr(signal, self.status.get("signal") or "", None)
            code = 128 + int(number) if number is not None else 125
        # Explicit status matters: ordinary GDB batch completion can return
        # success even when the inferior stopped at a fatal signal.
        gdb.execute(f"quit {code}")


InferiorEvidence().run()
