import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.test_dbus_runtime import assert_links_no_dbus_library
from src.tests.python.test_network_runtime import _transpile
from src.tests.runner_capabilities import linux_tray_backend_error
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("sanitized", [False, True])
@pytest.mark.macos_gui
def test_native_tray_lifecycle(native_project, native_compile, tmp_path, sanitized):
    source = ROOT / "src/tests/native/tray/TrayNative.btrc"
    plan = tmp_path / "Tray.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = tmp_path / "Tray.c"
    generated.write_text(compiled.c_source)
    executable = tmp_path / "Tray"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    result = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: test_tray_native\n"


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_tray_lifecycle_linux(compiler, tmp_path, sanitized, request):
    """The D-Bus provider hosts the same lifecycle on a live StatusNotifierWatcher, from both frontends.

    It speaks to the bus through Library.DBus, so the plan asks pkg-config for nothing and the program
    links no D-Bus library."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    generated = tmp_path / "Tray.c"
    plan = _transpile(compiler, ROOT / "src/tests/native/tray/TrayNative.btrc", generated, request)
    assert NativePlanReader().read(plan).pkg_config == ()
    executable = tmp_path / "Tray"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    assert_links_no_dbus_library(executable)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: test_tray_native\n"


@pytest.mark.parametrize("target", ["windows-x86_64"])
def test_native_tray_unsupported_target(target, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/native/tray/TrayNative.btrc"),
            "-o",
            str(tmp_path / "Tray.c"),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "provider" in result.stderr.lower()


def test_linux_tray_nested_menu_protocol(tmp_path):
    """Query the real provider's nested layouts, depth limit and radio state."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    from gi.repository import Gio, GLib

    source = tmp_path / "NestedTray.btrc"
    source.write_text("""import Library.Tray;
int main() {
    var modes = Tray("Modes").radioItem("Fast", "true", "true").radioItem("Slow", "true", "false");
    var options = Tray("Options").submenu("Mode", modes).item("Reset", "true");
    var tray = SystemTray("Nested").item("Open", "true").submenu("Settings", options);
    tray.show();
    for (int i = 0; i < 3000; i++) { if (!tray.pump(10)) { break; } }
    tray.close();
    return 0;
}
""")
    generated = tmp_path / "NestedTray.c"
    plan = tmp_path / "NestedTray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "NestedTray"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    process = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        deadline = time.monotonic() + 10
        service = None
        while time.monotonic() < deadline:
            names = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ListNames",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            ).unpack()[0]
            service = next(
                (name for name in names if name.startswith(f"org.kde.StatusNotifierItem-{process.pid}-")), None
            )
            if service:
                break
            assert process.poll() is None, process.communicate()
            time.sleep(0.01)
        assert service is not None

        def layout(node, depth):
            return bus.call_sync(
                service,
                "/MenuBar",
                "com.canonical.dbusmenu",
                "GetLayout",
                GLib.Variant("(iias)", (node, depth, [])),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            ).unpack()[1]

        root = layout(0, -1)
        assert [child[1]["label"] for child in root[2]] == ["Open", "Settings\u2003\u2003"]
        settings = root[2][1]
        assert settings[1]["children-display"] == "submenu"
        mode, reset = settings[2]
        assert mode[1]["label"] == "Mode\u2003\u2003"
        assert reset[1]["label"] == "Reset"
        assert [child[1]["toggle-type"] for child in mode[2]] == ["radio", "radio"]
        assert [child[1]["toggle-state"] for child in mode[2]] == [1, 0]
        assert layout(mode[0], -1) == mode
        about_to_show = bus.call_sync(
            service,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "AboutToShow",
            GLib.Variant("(i)", (mode[0],)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        ).unpack()
        assert about_to_show == (False,)  # answered from cached states; they refresh after the reply
        assert [child[1]["toggle-state"] for child in layout(mode[0], -1)[2]] == [1, 0]
        assert layout(settings[0], 0)[2] == []
        assert all(child[2] == [] for child in layout(0, 1)[2])
        with pytest.raises(GLib.Error, match="InvalidMenuItem"):
            layout(999, -1)
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_linux_tray_answers_libdbus_clients(tmp_path):
    """libdbus's dbus-send reads the item's properties and the menu's layout, and clicks an item: the
    first-party provider and the reference implementation agree on the wire in both directions."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    dbus_send = shutil.which("dbus-send")
    assert dbus_send is not None  # the backend gate found it
    clicked = tmp_path / "clicked"
    source = tmp_path / "WiredTray.btrc"
    source.write_text(f"""import Library.Tray;
int main() {{
    var tray = SystemTray("Wired").tip("a tip").item("Open", "touch {clicked}").checkItem("Marked", "true", "true");
    tray.show();
    for (int i = 0; i < 3000; i++) {{ if (!tray.pump(10)) {{ break; }} }}
    tray.close();
    return 0;
}}
""")
    generated = tmp_path / "WiredTray.c"
    plan = tmp_path / "WiredTray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "WiredTray"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    process = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:

        def send(destination, path, member, *arguments):
            command = [dbus_send, "--session", "--print-reply", f"--dest={destination}", path, member, *arguments]
            return subprocess.run(command, capture_output=True, text=True, timeout=30)

        prefix = f"org.kde.StatusNotifierItem-{process.pid}-"
        service = None
        deadline = time.monotonic() + 10
        while service is None and time.monotonic() < deadline:
            assert process.poll() is None, process.communicate()
            listed = send("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames").stdout
            service = next((word.strip('"') for word in listed.split() if word.strip('"').startswith(prefix)), None)
            time.sleep(0.01)
        assert service is not None

        def flat(result):
            assert result.returncode == 0, result.stderr
            return " ".join(result.stdout.split())

        item = flat(
            send(
                service,
                "/StatusNotifierItem",
                "org.freedesktop.DBus.Properties.GetAll",
                "string:org.kde.StatusNotifierItem",
            )
        )
        tooltip = 'variant struct { string "application-x-executable" array [ ] string "Wired" string "a tip" }'
        for expected in (
            'dict entry( string "Category" variant string "ApplicationStatus" )',
            'dict entry( string "Title" variant string "Wired" )',
            'dict entry( string "Status" variant string "Active" )',
            'dict entry( string "ItemIsMenu" variant boolean true )',
            'dict entry( string "Menu" variant object path "/MenuBar" )',
            f'dict entry( string "ToolTip" {tooltip} )',
        ):
            assert expected in item, (expected, item)
        version = send(
            service,
            "/MenuBar",
            "org.freedesktop.DBus.Properties.Get",
            "string:com.canonical.dbusmenu",
            "string:Version",
        )
        assert "variant uint32 3" in flat(version)

        layout = flat(
            send(service, "/MenuBar", "com.canonical.dbusmenu.GetLayout", "int32:0", "int32:-1", "array:string:label")
        )
        assert layout.count("variant struct { int32") == 2, layout  # the two items, each a (ia{sv}av) in a variant
        for expected in (
            "uint32 1 struct { int32 0",
            'dict entry( string "label" variant string "Open" )',
            'dict entry( string "label" variant string "Marked" )',
            'dict entry( string "toggle-type" variant string "checkmark" )',
            'dict entry( string "toggle-state" variant int32 1 )',
            'dict entry( string "enabled" variant boolean true )',
        ):
            assert expected in layout, (expected, layout)

        refused = send(
            service, "/StatusNotifierItem", "org.freedesktop.DBus.Properties.Get", "string:any", "string:Missing"
        )
        assert refused.returncode != 0 and "org.freedesktop.DBus.Error.UnknownProperty" in refused.stderr
        unknown = send(
            service, "/MenuBar", "com.canonical.dbusmenu.GetLayout", "int32:99", "int32:-1", "array:string:x"
        )
        assert unknown.returncode != 0 and "com.canonical.dbusmenu.Error.InvalidMenuItem" in unknown.stderr

        # A click, as a host sends it: (id, eventId, data, timestamp).
        click = send(
            service,
            "/MenuBar",
            "com.canonical.dbusmenu.Event",
            "int32:1",
            "string:clicked",
            "variant:int32:0",
            "uint32:0",
        )
        assert click.returncode == 0, click.stderr
        deadline = time.monotonic() + 10
        while not clicked.exists() and time.monotonic() < deadline:
            assert process.poll() is None, process.communicate()
            time.sleep(0.01)
        assert clicked.exists()
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_linux_tray_click_and_live_state(tmp_path):
    """A click on the icon runs its command; a new icon and tooltip are announced and served."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    from gi.repository import Gio, GLib

    clicked = tmp_path / "clicked"
    switch = tmp_path / "switch"
    icon = tmp_path / "second.png"
    icon.write_bytes(b"not read by the provider")
    source = tmp_path / "LiveTray.btrc"
    source.write_text(f"""import Library.FileSystem;
import Library.Tray;
int main() {{
    var plain = SystemTray("Plain").item("Open", "true");
    plain.show();
    var tray = SystemTray("Live").tip("first").onClick("touch {clicked}").item("Quit", TraySignal.quit());
    tray.show();
    for (int i = 0; i < 3000; i++) {{
        if (!tray.pump(10) || !plain.pump(0)) {{ break; }}
        if (FileSystem.isFile("{switch}")) {{ tray.setIcon("{icon}"); tray.setTip("second"); }}
    }}
    tray.close();
    plain.close();
    return 0;
}}
""")
    generated = tmp_path / "LiveTray.c"
    plan = tmp_path / "LiveTray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "LiveTray"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    process = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def names():
            listed = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ListNames",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            ).unpack()[0]
            return sorted(name for name in listed if name.startswith(f"org.kde.StatusNotifierItem-{process.pid}-"))

        def item(service, name):
            return bus.call_sync(
                service,
                "/StatusNotifierItem",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", name)),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            ).unpack()[0]

        def eventually(condition):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                if condition():
                    return True
                assert process.poll() is None, process.communicate()
                time.sleep(0.01)
            return False

        assert eventually(lambda: len(names()) == 2)
        services = {item(service, "Title"): service for service in names()}
        plain, live = services["Plain"], services["Live"]
        assert item(plain, "ItemIsMenu") is True  # no click command: the host opens the menu
        assert item(live, "ItemIsMenu") is False
        assert item(live, "ToolTip")[2:] == ("Live", "first")
        first_icon = item(live, "IconName")

        announced = []
        bus.signal_subscribe(
            live,
            "org.kde.StatusNotifierItem",
            None,
            "/StatusNotifierItem",
            None,
            Gio.DBusSignalFlags.NONE,
            lambda _bus, _sender, _path, _interface, member, _arguments: announced.append(member),
        )
        # The subscription's match rule is sent from another thread. One round trip later the bus has it,
        # so nothing is announced into a rule that is not there yet.
        names()
        switch.touch()
        assert eventually(lambda: "NewIcon" in announced and "NewToolTip" in announced), announced
        assert item(live, "IconName") == str(icon) != first_icon
        assert item(live, "ToolTip") == (str(icon), [], "Live", "second")
        count = len(announced)
        time.sleep(0.2)
        GLib.MainContext.default().iteration(False)
        assert len(announced) == count  # saying the same again announces nothing

        def click(service):
            bus.call_sync(
                service,
                "/StatusNotifierItem",
                "org.kde.StatusNotifierItem",
                "Activate",
                GLib.Variant("(ii)", (0, 0)),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )

        click(plain)
        assert not clicked.exists()
        click(live)
        assert eventually(clicked.exists)
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_linux_tray_status_lines_and_attention(tmp_path):
    """A status line is its label and the first line its command prints, fresh when its menu opens; the icon
    asks for attention while a command exits 0. Read over D-Bus: nothing is clicked."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    from gi.repository import Gio, GLib

    volume, pad, alarm, warning = (tmp_path / name for name in ("volume", "pad", "alarm", "warning.png"))
    volume.write_text("  locked  \nand a second line\n")
    pad.write_text("absent\n")
    warning.write_bytes(b"not read by the provider")
    source = tmp_path / "StatusTray.btrc"
    source.write_text(f"""import Library.Tray;
int main() {{
    var devices = Tray("Devices").status("Pad", "cat {pad}");
    var tray = SystemTray("Status").status("Volume", "cat {volume}", "test -e {alarm}")
        .submenu("Devices", devices).attentionIcon("{warning}").item("Quit", TraySignal.quit());
    tray.model.attentionSeconds = 1;
    tray.show();
    for (int i = 0; i < 6000; i++) {{ if (!tray.pump(10)) {{ break; }} }}
    tray.close();
    return 0;
}}
""")
    generated = tmp_path / "StatusTray.c"
    plan = tmp_path / "StatusTray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "StatusTray"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    process = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def call(path, interface, member, arguments, service=None):
            return bus.call_sync(
                service or tray, path, interface, member, arguments, None, Gio.DBusCallFlags.NONE, 5000, None
            ).unpack()

        def eventually(condition):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                if condition():
                    return True
                assert process.poll() is None, process.communicate()
                time.sleep(0.01)
            return False

        def registered():
            names = call("/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None, "org.freedesktop.DBus")[0]
            return next((name for name in names if name.startswith(f"org.kde.StatusNotifierItem-{process.pid}-")), None)

        assert eventually(lambda: registered() is not None)
        tray = registered()

        def layout(node=0):
            return call("/MenuBar", "com.canonical.dbusmenu", "GetLayout", GLib.Variant("(iias)", (node, -1, [])))[1]

        def labels(node=0):
            return [child[1]["label"] for child in layout(node)[2]]

        def opens(node):
            return call("/MenuBar", "com.canonical.dbusmenu", "AboutToShow", GLib.Variant("(i)", (node,)))

        def status(name="Status"):
            return call(
                "/StatusNotifierItem",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", name)),
            )[0]

        # The label and the first line the command printed, trimmed; the rest of its output is not shown.
        assert labels() == ["Volume: locked", "Devices\u2003\u2003", "Quit"]
        line, devices, _quit = layout()[2]
        assert line[1]["enabled"] is False and "toggle-type" not in line[1]  # a line to read, not to choose
        assert [child[1]["label"] for child in devices[2]] == ["Pad: absent"]

        updated = []
        announced = []
        bus.signal_subscribe(
            tray,
            "com.canonical.dbusmenu",
            "ItemsPropertiesUpdated",
            "/MenuBar",
            None,
            Gio.DBusSignalFlags.NONE,
            lambda *signal: updated.extend(signal[5].unpack()[0]),
        )
        bus.signal_subscribe(
            tray,
            "org.kde.StatusNotifierItem",
            "NewStatus",
            "/StatusNotifierItem",
            None,
            Gio.DBusSignalFlags.NONE,
            lambda *signal: announced.append(signal[5].unpack()[0]),
        )

        # What stands behind the lines changes; a shut menu costs nothing and says what it said.
        volume.write_text("open\n")
        pad.write_text("connected\n")
        time.sleep(0.3)
        assert labels() == ["Volume: locked", "Devices\u2003\u2003", "Quit"]
        # The menu opens: it is answered at once, and its own lines are read again and changed in place.
        assert opens(0) == (False,)
        assert eventually(lambda: labels()[0] == "Volume: open")
        assert eventually(lambda: (line[0], {"label": "Volume: open"}) in updated), updated
        assert [child[1]["label"] for child in layout(devices[0])[2]] == ["Pad: absent"]  # another menu's line waits
        opens(devices[0])
        assert eventually(lambda: [child[1]["label"] for child in layout(devices[0])[2]] == ["Pad: connected"])
        # A command that prints nothing leaves the label alone.
        volume.write_text("")
        opens(0)
        assert eventually(lambda: labels()[0] == "Volume")

        # The icon asks for attention while the command exits 0, and stops when it no longer does.
        assert status() == "Active" and announced == []
        assert status("AttentionIconName") == str(warning) != status("IconName")
        alarm.touch()
        assert eventually(lambda: status() == "NeedsAttention")
        assert eventually(lambda: announced == ["NeedsAttention"]), announced
        alarm.unlink()
        assert eventually(lambda: status() == "Active")
        assert eventually(lambda: announced == ["NeedsAttention", "Active"]), announced
        properties = call(
            "/StatusNotifierItem",
            "org.freedesktop.DBus.Properties",
            "GetAll",
            GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)),
        )[0]
        assert properties["Status"] == "Active" and properties["AttentionIconName"] == str(warning)
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_linux_tray_survives_a_watcher_replaced_during_registration(tmp_path):
    """A watcher takes the registration and is replaced, with nothing registered, before the item reads the
    reply: a desktop does this when it reloads its tray host during login. The item listens for a new watcher
    before it registers, so it hears of this one and registers again."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    daemon_program = shutil.which("dbus-daemon")
    if daemon_program is None:
        pytest.skip("native tray backend is unavailable: no session bus (dbus-daemon is not installed)")
    from gi.repository import Gio, GLib

    from tools.ui.status_notifier_watcher import INTERFACE, PATH, WATCHER

    source = tmp_path / "ReplacedWatcher.btrc"
    source.write_text("""import Library.Tray;
int main() {
    var tray = SystemTray("Replaced").item("Quit", TraySignal.quit());
    tray.show();
    for (int i = 0; i < 3000; i++) { if (!tray.pump(10)) { break; } }
    tray.close();
    return 0;
}
""")
    generated = tmp_path / "ReplacedWatcher.c"
    plan = tmp_path / "ReplacedWatcher.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "ReplacedWatcher"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")

    # A bus of the test's own: the session's watcher must not be the one that answers. Nix's dbus looks for
    # its configuration under /etc, which a container lacks, so the one installed beside the daemon is named,
    # as .github/ci/headless-session.sh does.
    shipped = Path(os.path.realpath(daemon_program)).parent.parent / "share/dbus-1/session.conf"
    configuration = f"--config-file={shipped}" if shipped.is_file() else "--session"
    daemon = subprocess.Popen(
        [daemon_program, configuration, "--nofork", "--nopidfile", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    )
    process = None
    try:
        address = daemon.stdout.readline().strip()
        assert address, "dbus-daemon printed no address"
        bus = Gio.DBusConnection.new_for_address_sync(
            address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None,
            None,
        )

        def name(member):
            arguments = (
                GLib.Variant("(su)", (WATCHER, 0)) if member == "RequestName" else GLib.Variant("(s)", (WATCHER,))
            )
            return bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                member,
                arguments,
                None,
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            ).unpack()[0]

        registrations = []
        replaced = []
        items = []

        def call(_connection, _sender, _path, _interface, method, parameters, invocation):
            (service,) = parameters.unpack()
            if method == "RegisterStatusNotifierItem":
                registrations.append(service)
                if len(registrations) == 1:
                    # This watcher goes and a new one, holding nothing, takes the name; then the old reply arrives.
                    replaced.extend((name("ReleaseName"), name("RequestName")))
                else:
                    items.append(service)
            invocation.return_value(None)

        def read(_connection, _sender, _path, _interface, wanted):
            return {
                "RegisteredStatusNotifierItems": GLib.Variant("as", items),
                "IsStatusNotifierHostRegistered": GLib.Variant("b", True),
                "ProtocolVersion": GLib.Variant("i", 0),
            }.get(wanted)

        info = Gio.DBusNodeInfo.new_for_xml(INTERFACE).interfaces[0]
        register = getattr(bus, "register_object_with_closures2", None) or bus.register_object
        register(PATH, info, call, read, None)
        assert name("RequestName") == 1  # the primary owner

        process = subprocess.Popen(
            [str(executable)],
            env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": address},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        expected = f"org.kde.StatusNotifierItem-{process.pid}-"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not items:
            GLib.MainContext.default().iteration(False)
            assert process.poll() is None, process.communicate()
            time.sleep(0.01)
        assert replaced == [1, 1], replaced  # released, and owned again as primary
        assert len(registrations) == 2 and items == [registrations[0]], (registrations, items)
        assert items[0].startswith(expected)
    finally:
        if process is not None:
            process.terminate()
            process.communicate(timeout=10)
        daemon.terminate()
        daemon.wait(timeout=10)
