import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.runner_capabilities import linux_tray_backend_error
from tools.native_plan import NativePlanBuilder

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
def test_native_tray_lifecycle_linux(tmp_path, sanitized):
    """The D-Bus provider hosts the same lifecycle on a live StatusNotifierWatcher."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    generated = tmp_path / "Tray.c"
    plan = tmp_path / "Tray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            "linux-x86_64" if platform.machine() in ("x86_64", "AMD64") else "linux-aarch64",
            str(ROOT / "src/tests/native/tray/TrayNative.btrc"),
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
    executable = tmp_path / "Tray"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
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
        assert [child[1]["label"] for child in root[2]] == ["Open", "Settings"]
        settings = root[2][1]
        assert settings[1]["children-display"] == "submenu"
        mode, reset = settings[2]
        assert mode[1]["label"] == "Mode"
        assert reset[1]["label"] == "Reset"
        assert [child[1]["toggle-type"] for child in mode[2]] == ["radio", "radio"]
        assert [child[1]["toggle-state"] for child in mode[2]] == [1, 0]
        assert layout(mode[0], -1) == mode
        assert layout(settings[0], 0)[2] == []
        assert all(child[2] == [] for child in layout(0, 1)[2])
        with pytest.raises(GLib.Error, match="InvalidMenuItem"):
            layout(999, -1)
    finally:
        process.terminate()
        process.communicate(timeout=10)
