"""Library.Bluetooth through both frontends.

The runners have no Bluetooth controller, so what runs here is the values,
every refusal, and the adapter's conversation with the Bluetooth daemon held
with a stand-in for BlueZ on a bus of the test's own; the flake's
bluetooth-hid-loopback check boots a VM with two emulated controllers and runs
the loopback program, which is only built here.
"""

import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.tests.python.test_dbus_runtime import assert_links_no_dbus_library, private_bus
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "bluetooth"
RUN_TIMEOUT = 60
COMPILE_TIMEOUT = 240
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
SANITIZED = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
PASSED = (
    "PASS: Bluetooth values, and refusals without Bluetooth\n",
    "PASS: Bluetooth values, with Bluetooth present\n",
)


def _require_host() -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux: Library.Bluetooth's BlueZ and L2CAP providers have Linux rows only")


def _build(c_compiler: str, plan: Path, generated: Path, executable: Path, *, sanitized: bool = False) -> None:
    """Build from the link plan, which names no pkg-config package: the bus is spoken to first-party."""
    assert NativePlanReader().read(plan).pkg_config == ()
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=STRICT + (SANITIZED if sanitized else []),
        link_flags=SANITIZED if sanitized else [],
    )
    assert_links_no_dbus_library(executable)


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_bluetooth_values_and_refusals_on_both_frontends(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"bluetooth-{compiler}.c"
    executable = tmp_path / f"bluetooth-{compiler}"
    plan = _transpile(compiler, FIXTURE / "BluetoothConformance.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout in PASSED
    assert ran.stderr == ""


def test_loopback_program_builds_and_plans_alike(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Both frontends build the two-controller program and plan it identically."""
    _require_host()
    generated = tmp_path / f"loopback-{compiler}.c"
    plan = _transpile(compiler, FIXTURE / "BluetoothHIDLoopback.btrc", generated, request)
    _build("clang", plan, generated, tmp_path / f"loopback-{compiler}")
    if compiler == "btrc":
        reference = _transpile(
            "python", FIXTURE / "BluetoothHIDLoopback.btrc", tmp_path / "loopback-reference.c", request
        )
        assert plan.read_bytes() == reference.read_bytes()


BLUEZ = """
<node>
  <interface name="org.bluez.Adapter1">
    <method name="RemoveDevice"><arg name="device" type="o" direction="in"/></method>
    <property name="Address" type="s" access="read"/>
    <property name="Alias" type="s" access="readwrite"/>
    <property name="Powered" type="b" access="readwrite"/>
    <property name="Discoverable" type="b" access="readwrite"/>
    <property name="DiscoverableTimeout" type="u" access="readwrite"/>
    <property name="Pairable" type="b" access="readwrite"/>
    <property name="PairableTimeout" type="u" access="readwrite"/>
  </interface>
  <interface name="org.bluez.Device1">
    <property name="Bonded" type="b" access="read"/>
    <property name="Connected" type="b" access="read"/>
  </interface>
  <interface name="org.bluez.ProfileManager1">
    <method name="RegisterProfile">
      <arg name="profile" type="o" direction="in"/>
      <arg name="uuid" type="s" direction="in"/>
      <arg name="options" type="a{sv}" direction="in"/>
    </method>
    <method name="UnregisterProfile"><arg name="profile" type="o" direction="in"/></method>
  </interface>
  <interface name="org.bluez.AgentManager1">
    <method name="RegisterAgent">
      <arg name="agent" type="o" direction="in"/>
      <arg name="capability" type="s" direction="in"/>
    </method>
    <method name="RequestDefaultAgent"><arg name="agent" type="o" direction="in"/></method>
    <method name="UnregisterAgent"><arg name="agent" type="o" direction="in"/></method>
  </interface>
</node>
"""


def test_adapter_drives_a_stand_in_bluez_over_the_bus(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Every call the adapter makes on the daemon, in order, and every answer its pairing agent gives.

    GDBus owns org.bluez on a private bus named as the system bus. It checks each call's signature against
    BlueZ's interfaces, so a property set with the wrong type or a call with the wrong arguments fails here.
    """
    _require_host()
    from gi.repository import Gio, GLib

    generated = tmp_path / f"adapter-{compiler}.c"
    executable = tmp_path / f"adapter-{compiler}"
    plan = _transpile(compiler, FIXTURE / "BluetoothAdapterBus.btrc", generated, request)
    _build("clang", plan, generated, executable, sanitized=True)

    adapter, manager = "/org/bluez/hci0", "/org/bluez"
    device = f"{adapter}/dev_11_22_33_44_55_66"
    agent, profile = "/org/btrc/bluetooth/hci0/agent", "/org/btrc/bluetooth/hci0/profile"
    uuid = "00001124-0000-1000-8000-00805f9b34fb"
    properties = {
        (adapter, "Address"): GLib.Variant("s", "00:AA:01:00:00:23"),
        (adapter, "Alias"): GLib.Variant("s", "stand-in"),
        (adapter, "Powered"): GLib.Variant("b", False),
        (adapter, "Discoverable"): GLib.Variant("b", False),
        (adapter, "DiscoverableTimeout"): GLib.Variant("u", 180),
        (adapter, "Pairable"): GLib.Variant("b", False),
        (adapter, "PairableTimeout"): GLib.Variant("u", 7),
        (device, "Bonded"): GLib.Variant("b", True),
        (device, "Connected"): GLib.Variant("b", False),
    }
    log: list[tuple] = []
    clients: set[str] = set()

    def call(_connection, sender, path, interface, method, parameters, invocation):
        clients.add(sender)
        log.append(("call", path, f"{interface}.{method}", parameters.get_type_string(), parameters.unpack()))
        if method == "RemoveDevice" and parameters.unpack() != (device,):
            invocation.return_dbus_error("org.bluez.Error.DoesNotExist", "Does Not Exist")
        else:
            invocation.return_value(None)

    def read(_connection, sender, path, interface, name):
        clients.add(sender)
        log.append(("get", path, f"{interface}.{name}"))
        return properties[(path, name)]

    def write(_connection, sender, path, interface, name, value):
        clients.add(sender)
        log.append(("set", path, f"{interface}.{name}", value.get_type_string(), value.unpack()))
        properties[(path, name)] = value
        return True

    with private_bus() as address:
        bus = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )
        interfaces = {info.name: info for info in Gio.DBusNodeInfo.new_for_xml(BLUEZ).interfaces}
        register = getattr(bus, "register_object_with_closures2", None) or bus.register_object
        register(adapter, interfaces["org.bluez.Adapter1"], call, read, write)
        register(device, interfaces["org.bluez.Device1"], call, read, write)
        register(manager, interfaces["org.bluez.ProfileManager1"], call, read, write)
        register(manager, interfaces["org.bluez.AgentManager1"], call, read, write)
        owned = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            GLib.Variant("(su)", ("org.bluez", 0)),
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        assert owned.unpack() == (1,)

        done = tmp_path / "done"
        process = subprocess.Popen(
            [str(executable)],
            env={**os.environ, "DBUS_SYSTEM_BUS_ADDRESS": address, "BTRC_TEST_DONE": str(done)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # The daemon's objects answer from this thread's main loop while the program sets itself up.
            deadline = time.monotonic() + RUN_TIMEOUT
            ready = ""
            while not ready and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                assert process.poll() is None, process.communicate()
                if select.select([process.stdout], [], [], 0.005)[0]:
                    ready = process.stdout.readline()
            assert ready == "READY\n", ready
            assert len(clients) == 1
            (client,) = clients

            def ask(member, parameters=None, path=agent, interface="org.bluez.Agent1"):
                return bus.call_sync(
                    client, path, interface, member, parameters, None, Gio.DBusCallFlags.NONE, 5000, None
                )

            # The pairing window is open: every question about a device is answered yes.
            assert ask("RequestConfirmation", GLib.Variant("(ou)", (device, 123456))).unpack() == ()
            pin = ask("RequestPinCode", GLib.Variant("(o)", (device,)))
            assert (pin.get_type_string(), pin.unpack()) == ("(s)", ("0000",))
            passkey = ask("RequestPasskey", GLib.Variant("(o)", (device,)))
            assert (passkey.get_type_string(), passkey.unpack()) == ("(u)", (0,))
            assert ask("AuthorizeService", GLib.Variant("(os)", (device, uuid))).unpack() == ()
            assert ask("RequestAuthorization", GLib.Variant("(o)", (device,))).unpack() == ()
            # What is not a question is acknowledged.
            assert ask("DisplayPasskey", GLib.Variant("(ouq)", (device, 1, 2))).unpack() == ()
            assert ask("Cancel").unpack() == ()
            # BlueZ supplies a socket descriptor when a published profile connects.
            import socket

            with socket.socket() as channel:
                descriptors = Gio.UnixFDList.new()
                index = descriptors.append(channel.fileno())
                reply, _ = bus.call_with_unix_fd_list_sync(
                    client,
                    profile,
                    "org.bluez.Profile1",
                    "NewConnection",
                    GLib.Variant("(oha{sv})", (device, index, {})),
                    None,
                    Gio.DBusCallFlags.NONE,
                    5000,
                    descriptors,
                    None,
                )
                assert reply.unpack() == ()
            assert ask("Release", path=profile, interface="org.bluez.Profile1").unpack() == ()
            # A question about what is not a device is refused the way BlueZ expects.
            with pytest.raises(GLib.Error, match=r"org\.bluez\.Error\.Rejected: Pairing is not open"):
                ask("RequestConfirmation", GLib.Variant("(ou)", (adapter, 1)))
            with pytest.raises(GLib.Error, match=r"org\.bluez\.Error\.Rejected: Pairing is not open"):
                ask("RequestPinCode")
            with pytest.raises(GLib.Error, match=r"org\.freedesktop\.DBus\.Error\.UnknownMethod: Unknown method"):
                ask("RequestConfirmation", GLib.Variant("(ou)", (device, 1)), interface="org.bluez.Other")
            with pytest.raises(GLib.Error, match=r"org\.freedesktop\.DBus\.Error\.UnknownMethod: Unknown method"):
                ask("Release", path="/org/btrc/bluetooth/hci0/elsewhere", interface="org.bluez.Profile1")

            done.touch()
            while process.poll() is None and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.002)
            output, errors = process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    assert process.returncode == 0, errors
    assert output == "PASS: the adapter's conversation with the Bluetooth daemon\n"
    assert errors == ""

    def got(name, path=adapter, interface="org.bluez.Adapter1"):
        return ("get", path, f"{interface}.{name}")

    def put(name, signature, value):
        return ("set", adapter, f"org.bluez.Adapter1.{name}", signature, value)

    def called(path, member, signature, *arguments):
        return ("call", path, member, signature, arguments)

    options = {
        "ServiceRecord": '<record><attribute id="0x0001"/></record>',
        "Role": "server",
        "RequireAuthentication": False,
        "RequireAuthorization": False,
        "AutoConnect": False,
    }
    expected = [
        got("Address"),
        got("Address"),
        got("Alias"),
        put("Alias", "s", "renamed \u2713"),
        got("Alias"),
        got("Powered"),
        put("Powered", "b", True),
        got("Powered"),
        got("Discoverable"),
        put("DiscoverableTimeout", "u", 30),
        put("Discoverable", "b", True),
        got("Discoverable"),
        got("Bonded", device, "org.bluez.Device1"),
        got("Connected", device, "org.bluez.Device1"),
        called(manager, "org.bluez.ProfileManager1.RegisterProfile", "(osa{sv})", profile, uuid, options),
        called(manager, "org.bluez.AgentManager1.RegisterAgent", "(os)", agent, "NoInputNoOutput"),
        called(manager, "org.bluez.AgentManager1.RequestDefaultAgent", "(o)", agent),
        put("PairableTimeout", "u", 0),
        got("Pairable"),
        put("Pairable", "b", True),
        got("Pairable"),
        got("Pairable"),
        called(adapter, "org.bluez.Adapter1.RemoveDevice", "(o)", device),
        called(adapter, "org.bluez.Adapter1.RemoveDevice", "(o)", f"{adapter}/dev_66_55_44_33_22_11"),
        called(manager, "org.bluez.AgentManager1.UnregisterAgent", "(o)", agent),
        got("Pairable"),
        put("Pairable", "b", False),
        got("Pairable"),
        got("Pairable"),
        called(manager, "org.bluez.ProfileManager1.UnregisterProfile", "(o)", profile),
    ]
    assert log == expected
    # The options are a dictionary on the wire: their order is the provider's.
    assert list(log[14][4][2]) == list(options)


def test_windows_builds_bluetooth_values_but_no_channels(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Addresses, HIDP and the pairing window are portable; channels and the adapter need a provider."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}

    def transpile(source: Path) -> subprocess.CompletedProcess[str]:
        if compiler == "python":
            command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
            command += ["--target", "windows-x86_64", "--no-cache", "-o", str(source.with_suffix(".c"))]
        else:
            btrcc = request.getfixturevalue("immutable_btrcc")
            command = [str(btrcc), "--strict-imports", "--target", "windows-x86_64", str(source)]
        return subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )

    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.Bluetooth.BluetoothAddress;\nimport Library.Bluetooth.BluetoothPairing;\n"
        "import Library.Bluetooth.HIDP;\n\n"
        "int main() { return BluetoothAddress.any().isAny() && !BluetoothPairingWindow().isOpen() ? 0 : 1; }\n"
    )
    portable = transpile(values)
    assert portable.returncode == 0, portable.stderr
    for module in ("L2CAP", "BluetoothAdapter", "BluetoothHID", "Bluetooth"):
        source = tmp_path / f"{module}.btrc"
        source.write_text(f"import Library.Bluetooth.{module};\n\nint main() {{ return 0; }}\n")
        refused = transpile(source)
        assert refused.returncode != 0
        assert "provider" in refused.stderr
