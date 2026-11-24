"""Reconnect a running public GUI application to private, real accessibility services."""

import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from src.tests.python.test_wayland_public_preview import empty_root_command

REGISTRY = "org.a11y.atspi.Registry"
ROOT = "/org/a11y/atspi/accessible/root"
ACCESSIBLE = "org.a11y.atspi.Accessible"


@contextmanager
def process(command, **kwargs):
    child = subprocess.Popen(command, **kwargs)
    try:
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


def call(address, owner, path, method, *args):
    result = subprocess.run(
        ["gdbus", "call", "--address", address, "--dest", owner, "--object-path", path, "--method", method, *args],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def children(address, owner, path):
    reply = call(address, owner, path, ACCESSIBLE + ".GetChildren")
    return re.findall(r"\('(:[\d.]+)', (?:objectpath )?'([^']+)'\)", reply)


def button(address, app):
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        assert app.poll() is None
        for owner, root in children(address, REGISTRY, ROOT):
            for _, window in children(address, owner, root):
                for _, control in children(address, owner, window):
                    name = call(address, owner, control, "org.freedesktop.DBus.Properties.Get", ACCESSIBLE, "Name")
                    if "'Quit'" in name:
                        assert call(address, owner, control, ACCESSIBLE + ".GetRole") == "(uint32 43,)"
                        return owner, control
        time.sleep(0.1)
    raise AssertionError("the running Wayland app did not register its Quit button")


def run(executable, work, registryd):
    with tempfile.TemporaryDirectory(prefix="btrc-atspi-") as private:
        address = "unix:path=" + private + "/bus"
        options = ["--ro-bind", private, "/a11y", "--setenv", "AT_SPI_BUS_ADDRESS", "unix:path=/a11y/bus"]
        env = os.environ | {"AT_SPI_BUS_ADDRESS": address, "DBUS_SESSION_BUS_ADDRESS": address}
        with process(empty_root_command(executable, work, options), stdout=subprocess.PIPE, text=True) as app:
            # Observe the mapped public window before making any accessibility socket available.
            deadline = time.monotonic() + 15
            while bytes((37, 179, 125)) * 240 not in subprocess.check_output(["grim", "-t", "ppm", "-"]):
                assert app.poll() is None and time.monotonic() < deadline
                time.sleep(0.1)

            daemon = ["dbus-daemon", "--session", "--nofork", "--print-address=1", "--address=" + address]
            for generation in range(2):
                with process(daemon, stdout=subprocess.PIPE, text=True) as bus:
                    assert bus.stdout.readline().startswith(address)
                    for launch in range(2 if generation == 0 else 1):
                        with process([registryd], env=env):
                            owner, control = button(address, app)
                            print(
                                f"bus {generation + 1}, registry {launch + 1} exposed the public Quit button",
                                flush=True,
                            )
                            if generation == 1:
                                action = call(address, owner, control, "org.a11y.atspi.Action.DoAction", "0")
                                assert action == "(true,)"
                                output, _ = app.communicate(timeout=8)
                                assert app.returncode == 0 and output.strip() == "Clicked Quit"
                                return
                    # Stop the entire first bus and registry before binding their address again.


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
