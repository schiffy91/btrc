"""Independent desktop portal peer for the Linux folder picker protocol test."""

import os
import subprocess
import sys

from gi.repository import Gio, GLib

DESKTOP = "org.freedesktop.portal.Desktop"
OBJECT = "/org/freedesktop/portal/desktop"
CHOOSER = "org.freedesktop.portal.FileChooser"
REQUEST = "org.freedesktop.portal.Request"
CHOOSER_XML = f"""<node><interface name="{CHOOSER}">
<property name="version" type="u" access="read"/>
<method name="OpenFile"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method></interface></node>"""
REQUEST_XML = f"""<node><interface name="{REQUEST}"><method name="Close"/></interface></node>"""


def main():
    mode = sys.argv[1]
    loop = GLib.MainLoop()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    other = Gio.DBusConnection.new_for_address_sync(
        os.environ["DBUS_SESSION_BUS_ADDRESS"],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None,
        None,
    )

    def closed(_, sender, path, iface, method, params, invocation):
        assert method == "Close"
        print("closed", flush=True)
        invocation.return_value(None)

    def open_file(_, sender, path, iface, method, params, invocation):
        parent, title, options = params.unpack()
        assert method == "OpenFile" and title == mode, (method, title)
        if mode == "public":
            assert parent.startswith("wayland:") and len(parent) > len("wayland:")
        else:
            assert parent == "wayland:parent", parent
        initial = os.fsencode(os.path.join(os.getcwd(), "input folder")) + b"\0"
        assert options == {
            "directory": True,
            "multiple": False,
            "modal": True,
            "handle_token": "btrc",
            "current_folder": list(initial),
        }, options
        namespace = OBJECT + "/request/" + sender[1:].replace(".", "_") + "/"
        handle = namespace + ("old_path" if mode == "old-path" else options["handle_token"])
        request = Gio.DBusNodeInfo.new_for_xml(REQUEST_XML).interfaces[0]
        bus.register_object(handle, request, closed, None, None)
        print("opened", flush=True)

        def response(connection=bus, code=0, uris=None, destination=sender, object_path=handle):
            if uris is None:
                uris = ["file://localhost/tmp/Folder%20%C3%A9+%23"]
            body = GLib.Variant(
                "(ua{sv})", (code, {"other": GLib.Variant("b", True), "uris": GLib.Variant("as", uris)})
            )
            connection.emit_signal(destination, object_path, REQUEST, "Response", body)
            connection.flush_sync(None)
            return False

        response(other, uris=["file:///forged"])
        response(object_path=namespace + "unrelated", uris=["file:///unrelated"])
        if mode == "early":
            response()
            response(object_path=namespace + "another_request", uris=["file:///unrelated"])
        invocation.return_value(GLib.Variant("(o)", (handle,)))
        if mode in {"selected", "old-path", "public"}:
            GLib.timeout_add(100, response)
        elif mode == "cancel":
            GLib.timeout_add(100, lambda: response(code=1))
        elif mode == "failed":
            GLib.timeout_add(100, lambda: response(code=2))
        elif mode == "broadcast":
            GLib.timeout_add(100, lambda: response(destination=None))
        elif mode == "disconnect":
            GLib.timeout_add(80, lambda: (bus.close_sync(None), loop.quit(), False)[-1])
        elif mode == "bad-reply":
            GLib.timeout_add(
                100,
                lambda: bus.emit_signal(sender, handle, REQUEST, "Response", GLib.Variant("(s)", ("bad",))) and False,
            )
        elif mode in {"missing", "remote", "nul", "slash", "many", "escape"}:
            uris = {
                "missing": [],
                "remote": ["smb://server/share"],
                "nul": ["file:///wrong%00name"],
                "slash": ["file:///bad%2fname"],
                "many": ["file:///one", "file:///two"],
                "escape": ["file:///bad%zz"],
            }[mode]
            GLib.timeout_add(100, lambda: response(uris=uris))

    interface = Gio.DBusNodeInfo.new_for_xml(CHOOSER_XML).interfaces[0]
    bus.register_object(OBJECT, interface, open_file, lambda *_: GLib.Variant("u", 2 if mode == "old" else 4), None)
    result = bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", (DESKTOP, 4)),
        None,
        Gio.DBusCallFlags.NONE,
        1000,
        None,
    )
    assert result.unpack() == (1,)
    print("ready", flush=True)
    loop.run()


def drive_gui(*program):
    env = {**os.environ, "BTRC_PORTAL_TEST": "public"}
    with subprocess.Popen([sys.executable, __file__, "public"], env=env, stdout=subprocess.PIPE, text=True) as peer:
        try:
            assert peer.stdout.readline().strip() == "ready"
            result = subprocess.run(program, env=env, check=True, capture_output=True, text=True, timeout=12)
            assert result.stdout.splitlines() == ["1 /tmp/Folder é+#"], result
            assert peer.stdout.readline().strip() == "opened"
        finally:
            peer.terminate()


if __name__ == "__main__":
    if sys.argv[1] == "--drive-gui":
        drive_gui(*sys.argv[2:])
    else:
        main()
