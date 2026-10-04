"""Read three real AT-SPI wire objects from a separately compiled btrc process."""

import json
import os
import subprocess
import sys
import time

from gi.repository import Gio, GLib

session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
address = session.call_sync(
    "org.a11y.Bus",
    "/org/a11y/bus",
    "org.a11y.Bus",
    "GetAddress",
    None,
    GLib.VariantType.new("(s)"),
    Gio.DBusCallFlags.NONE,
    5000,
    None,
).unpack()[0]
connection = Gio.DBusConnection.new_for_address_sync(
    address,
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
    None,
    None,
)
process = subprocess.Popen([sys.argv[1]], env={**os.environ, "BTRC_A11Y_ADDRESS": address})
name = "org.btrc.AccessibilitySpike"
root = "/org/a11y/atspi/accessible/root"


def call(path, interface, method, arguments=None):
    return connection.call_sync(
        name, path, interface, method, arguments, None, Gio.DBusCallFlags.NONE, 2000, None
    ).unpack()


def node(path):
    interface = "org.a11y.atspi.Accessible"
    label = call(path, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (interface, "Name")))[0]
    role = call(path, interface, "GetRole")[0]
    role_name = call(path, interface, "GetRoleName")[0]
    children = call(path, interface, "GetChildren")[0]
    return {
        "path": path,
        "name": label,
        "role": role,
        "role_name": role_name,
        "children": [node(child_path) for bus, child_path in children],
    }


try:
    deadline = time.monotonic() + 10
    while True:
        try:
            tree = node(root)
            break
        except GLib.Error:
            if process.poll() is not None or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    assert tree["role"] == 23
    assert [(child["role"], child["name"]) for child in tree["children"]] == [
        (43, "Native contract button"),
        (29, "Virtual GPU child"),
    ]
    assert all(not child["children"] for child in tree["children"])
    # This deliberately tests wire exposure only, not registry embedding or a
    # full screen-reader contract (State, Parent, actions and events are absent).
    document = {
        "transport": "actual org.a11y.Bus",
        "server": "btrc executable",
        "registry_embedded": False,
        "full_atspi_contract": False,
        "tree": tree,
    }
    call(root, "org.btrc.Spike", "Quit")
    assert process.wait(timeout=5) == 0
    with open(sys.argv[2], "w") as output:
        json.dump(document, output, indent=2)
        output.write("\n")
    print(json.dumps({"nodes": 3, "server_exit": 0, "wire_roles": [23, 43, 29]}))
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    connection.close_sync(None)
