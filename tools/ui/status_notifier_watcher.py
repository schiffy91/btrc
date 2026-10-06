"""Host a stand-in StatusNotifierWatcher on the session bus while a command runs.

    tools/ui/headless-session.sh --x11 -- \\
        python3 tools/ui/status_notifier_watcher.py -- python3 -m pytest src/tests/python/test_native_tray_runtime.py

A headless session's private bus has no desktop shell on it, so nothing owns
``org.kde.StatusNotifierWatcher`` and the Linux tray provider (``Library.Tray``
over D-Bus) has nowhere to register its item. This owns that name at
``/StatusNotifierWatcher`` with the watcher's methods, properties and signals,
records each item and host that registers, and forgets an item whose bus name
goes away, as a desktop's watcher does. It draws nothing and activates nothing:
it proves the provider's D-Bus registration lifecycle, not a visible tray icon.

The command starts once the name is owned; its exit status is this program's,
and TERM and INT reach it. Without a session bus or the GLib typelibs (the dev
shell's GI_TYPELIB_PATH) this exits 2 before starting the command, so a broken
session is never mistaken for one without a watcher.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

WATCHER = "org.kde.StatusNotifierWatcher"
PATH = "/StatusNotifierWatcher"
INTERFACE = """
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
    <method name="RegisterStatusNotifierHost"><arg name="service" type="s" direction="in"/></method>
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="ProtocolVersion" type="i" access="read"/>
    <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
    <signal name="StatusNotifierHostRegistered"/>
  </interface>
</node>
"""


class StandInWatcher:
    """Own the watcher name, track registered items, and run the command beside it."""

    def __init__(self, command: list[str]) -> None:
        from gi.repository import Gio, GLib

        self.Gio = Gio
        self.GLib = GLib
        self.command = command
        self.items: list[str] = []
        self.watches: dict[str, int] = {}
        self.child: subprocess.Popen[bytes] | None = None
        self.status = 2
        self.loop = GLib.MainLoop()
        self.connection = None

    def run(self) -> int:
        Gio, GLib = self.Gio, self.GLib
        info = Gio.DBusNodeInfo.new_for_xml(INTERFACE).interfaces[0]
        owner = Gio.bus_own_name(
            Gio.BusType.SESSION,
            WATCHER,
            Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
            lambda connection, _name: self.export(connection, info),
            self.acquired,
            self.lost,
        )
        try:
            import gi

            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix

            add_signal = GLibUnix.signal_add
        except (ImportError, ValueError):
            add_signal = GLib.unix_signal_add
        for signum in (signal.SIGTERM, signal.SIGINT):
            add_signal(GLib.PRIORITY_HIGH, signum, self.forward, signum)
        self.loop.run()
        Gio.bus_unown_name(owner)
        return self.status

    def export(self, connection, info) -> None:
        self.connection = connection
        # GLib 2.84 renamed the closure-taking registration; older GLib has only the first.
        register = getattr(connection, "register_object_with_closures2", None) or connection.register_object
        register(PATH, info, self.call, self.property, None)

    def acquired(self, _connection, _name) -> None:
        self.child = subprocess.Popen(self.command)
        self.GLib.child_watch_add(self.GLib.PRIORITY_DEFAULT, self.child.pid, self.exited)

    def lost(self, _connection, _name) -> None:
        if self.child is None:
            print(f"status_notifier_watcher: could not own {WATCHER} on the session bus", file=sys.stderr)
            self.loop.quit()

    def exited(self, _pid, status) -> None:
        # GLib reaped the command and reports its wait status; a command a
        # signal ended exits as a shell reports it, 128 plus the signal.
        code = os.waitstatus_to_exitcode(status)
        self.status = 128 - code if code < 0 else code
        if self.child is not None:
            self.child.returncode = code
        self.loop.quit()

    def forward(self, signum: int) -> bool:
        if self.child is not None and self.child.poll() is None:
            self.child.send_signal(signum)
        elif self.child is None:
            self.status = 128 + signum
            self.loop.quit()
        return True

    def call(self, connection, sender, _path, _interface, method, parameters, invocation) -> None:
        (service,) = parameters.unpack()
        if method == "RegisterStatusNotifierHost":
            invocation.return_value(None)
            connection.emit_signal(None, PATH, WATCHER, "StatusNotifierHostRegistered", None)
            return
        # An item names its bus name or its object path; either way it lives on the sender.
        item = service if service.startswith(":") or "." in service.split("/")[0] else f"{sender}{service}"
        invocation.return_value(None)
        if item not in self.items:
            self.items.append(item)
            self.watches[item] = self.Gio.bus_watch_name_on_connection(
                connection, sender, self.Gio.BusNameWatcherFlags.NONE, None, lambda *_: self.forget(item)
            )
            connection.emit_signal(
                None, PATH, WATCHER, "StatusNotifierItemRegistered", self.GLib.Variant("(s)", (item,))
            )

    def forget(self, item: str) -> None:
        if item in self.items:
            self.items.remove(item)
            self.Gio.bus_unwatch_name(self.watches.pop(item))
            if self.connection is not None:
                self.connection.emit_signal(
                    None, PATH, WATCHER, "StatusNotifierItemUnregistered", self.GLib.Variant("(s)", (item,))
                )

    def property(self, _connection, _sender, _path, _interface, name):
        GLib = self.GLib
        return {
            "RegisteredStatusNotifierItems": GLib.Variant("as", self.items),
            "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
            "ProtocolVersion": GLib.Variant("i", 0),
        }.get(name)


def main(arguments: list[str]) -> int:
    command = arguments[1:] if arguments[:1] == ["--"] else arguments
    if not command:
        print("usage: status_notifier_watcher.py -- <command> [args...]", file=sys.stderr)
        return 2
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
    except (ImportError, ValueError) as error:
        print(f"status_notifier_watcher: GLib typelibs are unavailable: {error}", file=sys.stderr)
        return 2
    return StandInWatcher(command).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
