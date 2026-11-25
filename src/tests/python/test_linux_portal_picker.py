"""Exercise the Linux public directory-picker contract against an independent desktop service."""

import os
import platform
import selectors
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.gui_provider_root import GUIProviderRoot
from src.tests.python.linux_provider_fixtures import require_linux_reader, transpile_provider_program
from src.tests.python.test_dbus_runtime import private_bus
from tools.native_plan import NativePlanBuilder, NativePlanReader
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "src/tests/native/gui/linux"
CASES = {
    "selected": "1 /tmp/Folder é+#",
    "early": "1 /tmp/Folder é+#",
    "old-path": "1 /tmp/Folder é+#",
    "broadcast": "1 /tmp/Folder é+#",
    "cancel": "2",
    "quit": "2",
    "disconnect": "3",
    "missing": "3",
    "remote": "3",
    "nul": "3",
    "slash": "3",
    "many": "3",
    "escape": "3",
    "failed": "3",
    "bad-reply": "3",
    "old": "3",
    "absent": "3",
    "invalid": "3",
    "dispatch": "exception Native event dispatch is already active",
}


@pytest.fixture(scope="module")
def portal_data_root(tmp_path_factory):
    root = GUIProviderRoot.create(tmp_path_factory.mktemp("portal-data"))
    manifest = root / "stdlib/GUI/btrc.toml"
    manifest.write_text(
        manifest.read_text().replace(
            "exports = [", 'exports = ["Linux.PortalDirectoryPicker", "Linux.PortalFilePicker", ', 1
        )
    )
    return root


def next_line(stream):
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        assert selector.select(3), "portal peer did not report the expected event"
    return stream.readline().strip()


def run_case(program, mode, env, peer_python):
    peer = None
    try:
        if mode not in {"absent", "invalid", "dispatch"}:
            peer = subprocess.Popen(
                [peer_python, NATIVE / "PortalChooserPeer.py", mode], env=env, stdout=subprocess.PIPE, bufsize=0
            )
            assert next_line(peer.stdout) == b"ready"
        result = subprocess.run([program], env=env, check=True, capture_output=True, text=True, timeout=8)
        lines = [line.strip() for line in result.stdout.splitlines()]
        assert lines[0] == CASES[mode], (mode, result.stdout)
        if lines[0] == "3":
            expected_error = 3 if mode in {"old", "absent"} else 1 if mode == "invalid" else 4
            assert lines[1].startswith(f"error {expected_error} ")
        if peer and mode != "old":
            assert next_line(peer.stdout) == b"opened"
            assert int(lines[-1].split()[1]) > 0
        if mode == "quit":
            assert next_line(peer.stdout) == b"closed"
    finally:
        if peer:
            peer.terminate()
            peer.wait(timeout=5)
            peer.stdout.close()


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_portal_picker(frontend, portal_data_root, tmp_path, request):
    require_linux_reader()
    peer_python = sys.executable
    if subprocess.run([peer_python, "-c", "from gi.repository import Gio, GLib"], capture_output=True).returncode:
        pytest.skip("the independent portal service needs PyGObject Gio")
    generated, plan, program = [tmp_path / name for name in ("program.c", "plan.json", "program")]
    transpile_provider_program(
        NATIVE / "PortalDirectoryPicker.btrc", generated, plan, frontend, request, portal_data_root
    )
    assert NativePlanReader().read(plan).pkg_config == ()
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=program, optimization=1)
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    imports = subprocess.check_output(["readelf", "-d", program], text=True)
    assert all(name not in imports for name in ("libdbus", "libgio", "libglib", "libgtk", "libwayland"))
    for mode in CASES:
        with private_bus() as address:
            run_case(
                program,
                mode,
                {**os.environ, "DBUS_SESSION_BUS_ADDRESS": address, "BTRC_PORTAL_TEST": mode},
                peer_python,
            )


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_gui_routes_parented_directory_picker_to_portal(frontend, tmp_path, request):
    require_linux_reader()
    if not all(shutil.which(tool) for tool in ("pkg-config", "labwc", "wlr-randr", "dbus-daemon")):
        pytest.skip("requires a private Wayland desktop")
    if subprocess.run(["pkg-config", "--exists", "wgpu-native"]).returncode:
        pytest.skip("the Linux GUI provider's GPU surface needs the wgpu-native SDK")
    if subprocess.run([sys.executable, "-c", "from gi.repository import Gio, GLib"], capture_output=True).returncode:
        pytest.skip("the independent portal service needs PyGObject Gio")
    generated, plan, program = [tmp_path / name for name in ("program.c", "plan.json", "program")]
    transpile_provider_program(NATIVE / "PortalGUI.btrc", generated, plan, frontend, request)
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=program, optimization=0)
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    subprocess.run(
        [
            ROOT / "tools/ui/headless-session.sh",
            "--wayland",
            "--",
            sys.executable,
            NATIVE / "PortalChooserPeer.py",
            "--drive-gui",
            program,
        ],
        check=True,
        timeout=45,
    )


FILE_CASES = {
    "open-file": "1 /tmp/Disk é+#.raw",
    "open-files": "1 /tmp/one.raw|/tmp/two.qcow2",
    "open-dir": "1 /tmp/vm-dir",
    "open-dirs": "1 /tmp/dir-a|/tmp/dir-b",
    "save-file": "1 /tmp/snapshot.qcow2",
    "save-v2": "1 /tmp/snapshot.qcow2",
    "old-file": "1 /tmp/Disk é+#.raw",
    "cancel": "2",
    "mixed": "3",
    "old-dir": "3",
    "many-for-single": "3",
    "invalid": "3",
    "dispatch": "exception Native event dispatch is already active",
}


def run_file_case(program, mode, env, peer_python):
    peer = None
    try:
        if mode not in {"mixed", "invalid", "dispatch"}:
            peer = subprocess.Popen(
                [peer_python, NATIVE / "PortalFileChooserPeer.py", mode], env=env, stdout=subprocess.PIPE, bufsize=0
            )
            assert next_line(peer.stdout) == b"ready"
        result = subprocess.run([program], env=env, check=True, capture_output=True, text=True, timeout=8)
        lines = [line.strip() for line in result.stdout.splitlines()]
        assert lines[0] == FILE_CASES[mode], (mode, result.stdout)
        if lines[0] == "3":
            expected_error = 3 if mode in {"mixed", "old-dir"} else 1 if mode == "invalid" else 4
            assert lines[1].startswith(f"error {expected_error} "), (mode, lines)
        if peer and mode != "old-dir":
            assert next_line(peer.stdout) == b"opened"
            assert int(lines[-1].split()[1]) > 0
    finally:
        if peer:
            peer.terminate()
            peer.wait(timeout=5)
            peer.stdout.close()


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_portal_file_picker(frontend, portal_data_root, tmp_path, request):
    require_linux_reader()
    peer_python = sys.executable
    if subprocess.run([peer_python, "-c", "from gi.repository import Gio, GLib"], capture_output=True).returncode:
        pytest.skip("the independent portal service needs PyGObject Gio")
    generated, plan, program = [tmp_path / name for name in ("program.c", "plan.json", "program")]
    transpile_provider_program(NATIVE / "PortalFilePicker.btrc", generated, plan, frontend, request, portal_data_root)
    assert NativePlanReader().read(plan).pkg_config == ()
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=program, optimization=1)
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    imports = subprocess.check_output(["readelf", "-d", program], text=True)
    assert all(name not in imports for name in ("libdbus", "libgio", "libglib", "libgtk", "libwayland"))
    for mode in FILE_CASES:
        with private_bus() as address:
            run_file_case(
                program,
                mode,
                {**os.environ, "DBUS_SESSION_BUS_ADDRESS": address, "BTRC_PORTAL_TEST": mode},
                peer_python,
            )
