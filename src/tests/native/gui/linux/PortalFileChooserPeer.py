"""Independent desktop portal peer for the Linux file-and-folder picker protocol test."""

import os
import sys

from gi.repository import Gio, GLib

DESKTOP = "org.freedesktop.portal.Desktop"
OBJECT = "/org/freedesktop/portal/desktop"
CHOOSER = "org.freedesktop.portal.FileChooser"
REQUEST = "org.freedesktop.portal.Request"
CHOOSER_XML = f"""<node><interface name="{CHOOSER}">
<property name="version" type="u" access="read"/>
<method name="OpenFile"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method>
<method name="SaveFile"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{{sv}}" direction="in"/><arg type="o" direction="out"/></method></interface></node>"""
REQUEST_XML = f"""<node><interface name="{REQUEST}"><method name="Close"/></interface></node>"""


def main():
    mode = sys.argv[1]
    loop = GLib.MainLoop()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def closed(_, sender, path, iface, method, params, invocation):
        assert method == "Close"
        print("closed", flush=True)
        invocation.return_value(None)

    def handle_call(_, sender, path, iface, method, params, invocation):
        parent, title, options = params.unpack()
        assert parent == "wayland:parent", parent
        assert title == mode, (method, title)
        initial = list(os.fsencode(os.path.join(os.getcwd(), "input folder")) + b"\0")
        expected_filters = [("Disk images", [(0, "*.raw"), (0, "*.qcow2")])]
        if mode in {"save-file", "save-v2"}:
            assert method == "SaveFile", method
            assert options == {
                "handle_token": "btrc",
                "modal": True,
                "current_name": "snapshot.qcow2",
                "current_folder": initial,
                "filters": expected_filters,
            }, options
        else:
            assert method == "OpenFile", method
            want_dir = mode in {"open-dir", "open-dirs"}
            want_multi = mode in {"open-files", "open-dirs"}
            expected = {
                "handle_token": "btrc",
                "modal": True,
                "directory": want_dir,
                "multiple": want_multi,
                "current_folder": initial,
            }
            if not want_dir:
                expected["filters"] = expected_filters
            assert options == expected, options
        namespace = OBJECT + "/request/" + sender[1:].replace(".", "_") + "/"
        handle = namespace + options["handle_token"]
        request = Gio.DBusNodeInfo.new_for_xml(REQUEST_XML).interfaces[0]
        bus.register_object(handle, request, closed, None, None)
        print("opened", flush=True)

        def emit(code=0, uris=None):
            body = GLib.Variant("(ua{sv})", (code, {"uris": GLib.Variant("as", uris or [])}))
            bus.emit_signal(sender, handle, REQUEST, "Response", body)
            bus.flush_sync(None)
            return False

        invocation.return_value(GLib.Variant("(o)", (handle,)))
        if mode in {"open-file", "old-file"}:
            GLib.timeout_add(80, lambda: emit(uris=["file://localhost/tmp/Disk%20%C3%A9+%23.raw"]))
        elif mode == "open-files":
            GLib.timeout_add(80, lambda: emit(uris=["file:///tmp/one.raw", "file:///tmp/two.qcow2"]))
        elif mode == "open-dir":
            GLib.timeout_add(80, lambda: emit(uris=["file:///tmp/vm-dir"]))
        elif mode == "open-dirs":
            GLib.timeout_add(80, lambda: emit(uris=["file:///tmp/dir-a", "file:///tmp/dir-b"]))
        elif mode in {"save-file", "save-v2"}:
            GLib.timeout_add(80, lambda: emit(uris=["file:///tmp/snapshot.qcow2"]))
        elif mode == "cancel":
            GLib.timeout_add(80, lambda: emit(code=1, uris=[]))
        elif mode == "many-for-single":
            GLib.timeout_add(80, lambda: emit(uris=["file:///tmp/one.raw", "file:///tmp/two.qcow2"]))

    version = 2 if mode in {"old-dir", "old-file", "save-v2"} else 4
    interface = Gio.DBusNodeInfo.new_for_xml(CHOOSER_XML).interfaces[0]
    bus.register_object(OBJECT, interface, handle_call, lambda *_: GLib.Variant("u", version), None)
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


if __name__ == "__main__":
    main()
