"""Record a headless GUI session's accessibility tree while a command runs in it.

    tools/ui/headless-session.sh --wayland -- \\
        python3 tools/ui/session_evidence.py --output build/linux-gui/wayland -- python3 -m pytest ...

The command runs as a child. While it runs, the AT-SPI desktop is sampled every
``--interval`` seconds, and once it exits the whole tree is dumped again; both
go to ``<output>/atspi.json``. Every sample walks the tree in a child process
with a timeout, so an application that stops answering can stall one sample but
never the session. The walk is bounded in depth and node count.

The command's exit status is this program's, and TERM and INT reach the
command. Without an accessibility bus, or without the AT-SPI typelibs pyatspi
loads (the dev shell's GI_TYPELIB_PATH), each sample records why it could not
read the tree and the command runs exactly as it would without this wrapper:
the dump is evidence of what the session exposed, never a gate.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "btrc.atspi-session/1"
# Seconds one sample may take before it is abandoned.
SAMPLE_TIMEOUT = 30
MAX_DEPTH = 24
MAX_NODES = 4000


class AccessibilityTreeWalker:
    """Walk the AT-SPI desktop into plain JSON, within fixed depth and node budgets."""

    def __init__(self, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> None:
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.nodes = 0
        self.truncated = False

    def snapshot(self) -> dict[str, object]:
        try:
            import gi

            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
        except (ImportError, ValueError) as error:
            return {"status": "unavailable", "reason": f"pyatspi typelibs: {error}"}
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return {"status": "unavailable", "reason": "no session bus (DBUS_SESSION_BUS_ADDRESS is unset)"}
        Atspi.init()
        # Milliseconds: one unresponsive application costs one call, not the sample.
        Atspi.set_timeout(2000, 5000)
        desktop = Atspi.get_desktop(0)
        tree = self.node(desktop, 0)
        return {"status": "observed", "nodes": self.nodes, "truncated": self.truncated, "desktop": tree}

    def node(self, accessible, depth: int) -> dict[str, object]:
        self.nodes += 1
        record: dict[str, object] = {}
        for field, read in (
            ("name", accessible.get_name),
            ("role", accessible.get_role_name),
            ("description", accessible.get_description),
        ):
            try:
                record[field] = read()
            except Exception as error:
                record[field] = None
                record.setdefault("errors", []).append(f"{field}: {error}")
        try:
            record["states"] = sorted(state.value_nick for state in accessible.get_state_set().get_states())
        except Exception as error:
            record.setdefault("errors", []).append(f"states: {error}")
        try:
            count = accessible.get_child_count()
        except Exception as error:
            record.setdefault("errors", []).append(f"children: {error}")
            return record
        record["child_count"] = count
        if depth >= self.max_depth:
            self.truncated = self.truncated or count > 0
            return record
        children = []
        for index in range(count):
            if self.nodes >= self.max_nodes:
                self.truncated = True
                break
            try:
                child = accessible.get_child_at_index(index)
            except Exception as error:
                children.append({"errors": [f"child {index}: {error}"]})
                continue
            if child is not None:
                children.append(self.node(child, depth + 1))
        record["children"] = children
        return record


class SessionEvidence:
    """Run a command, sampling the accessibility tree until it exits, then dump it once more."""

    def __init__(self, output: Path, interval: float) -> None:
        self.output = output
        self.interval = interval
        self.samples: list[dict[str, object]] = []
        self.applications: dict[str, dict[str, object]] = {}
        self.stopped = threading.Event()

    def sample(self) -> dict[str, object]:
        command = [sys.executable, os.path.abspath(__file__), "--snapshot"]
        taken = datetime.now(UTC).isoformat()
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=SAMPLE_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"taken_at": taken, "status": "timeout", "reason": f"exceeded {SAMPLE_TIMEOUT} seconds"}
        try:
            snapshot = json.loads(result.stdout)
        except json.JSONDecodeError:
            reason = (result.stderr.strip() or f"exit status {result.returncode}")[-2000:]
            return {"taken_at": taken, "status": "error", "reason": reason}
        return {"taken_at": taken, **snapshot}

    def record(self, snapshot: dict[str, object]) -> None:
        desktop = snapshot.get("desktop")
        applications = desktop.get("children", []) if isinstance(desktop, dict) else []
        names = []
        for application in applications:
            name = str(application.get("name") or "<unnamed>")
            names.append(name)
            seen = self.applications.setdefault(name, {"first_seen": snapshot["taken_at"]})
            seen["last_seen"] = snapshot["taken_at"]
            # Keep the largest tree an application exposed while it lived.
            if len(json.dumps(application)) >= len(json.dumps(seen.get("tree", {}))):
                seen["tree"] = application
        self.samples.append(
            {key: snapshot.get(key) for key in ("taken_at", "status", "reason", "nodes", "truncated")}
            | {"applications": names}
        )

    def watch(self) -> None:
        while not self.stopped.wait(self.interval):
            self.record(self.sample())

    def run(self, command: list[str]) -> int:
        self.output.mkdir(parents=True, exist_ok=True)
        child = subprocess.Popen(command)

        def forward(signum: int, _frame: object) -> None:
            child.send_signal(signum)

        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGINT, forward)
        watcher = threading.Thread(target=self.watch, daemon=True)
        started = time.monotonic()
        watcher.start()
        status = child.wait()
        self.stopped.set()
        watcher.join(SAMPLE_TIMEOUT + 5)
        final = self.sample()
        self.record(final)
        document = {
            "schema": SCHEMA,
            "session": "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11" if os.environ.get("DISPLAY") else None,
            "display": os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
            "command": command,
            "returncode": status,
            "seconds": round(time.monotonic() - started, 1),
            "interval": self.interval,
            "samples": self.samples,
            "applications": self.applications,
            "final": final,
        }
        (self.output / "atspi.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # A command a signal ended exits as a shell reports it: 128 plus the signal.
        return 128 - status if status < 0 else status


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--output", type=Path, help="directory for atspi.json")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    parser.add_argument("--snapshot", action="store_true", help="print one tree snapshot as JSON and exit")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command to run")
    options = parser.parse_args(arguments)
    if options.snapshot:
        print(json.dumps(AccessibilityTreeWalker().snapshot()))
        return 0
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if options.output is None or not command or not 0 < options.interval <= 3600:
        parser.error("--output, an interval in (0, 3600] and a command after -- are required")
    return SessionEvidence(options.output, options.interval).run(command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
