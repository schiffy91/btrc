"""The private Linux software window client, driven by an independent compositor."""

import ctypes.util
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.tests.gui_provider_root import GUIProviderRoot
from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.linux_provider_fixtures import require_linux_reader, transpile_provider_program
from src.tests.python.test_headless_session import ROOT, SESSION, _require_session_tools
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

NATIVE = ROOT / "src/tests/native/gui/linux"
PROVIDER = ROOT / "src/stdlib/GUI/Linux/Wayland"
PROBE = NATIVE.parent / "conformance/probes/linux"
CLIENT_SOURCES = tuple(
    PROVIDER / f"{name}.c"
    for name in ("Wire", "Window", "Input", "Keymap", "GPUWire", "Cursor", "TextInput", "Clipboard")
)

PLATFORM_SOURCES = tuple(
    PROVIDER / f"{name}.c"
    for name in (
        "Platform",
        "Scene",
        "Slider",
        "Button",
        "ControlText",
        "Tooltip",
        "Label",
        "Select",
        "TextLines",
        "EditBuffer",
        "TextField",
    )
) + (PROVIDER.parent.parent / "Text/LineBreak.c", PROVIDER.parent.parent / "Text/Grapheme.c")
SYSTEM_TEXT = PROVIDER.parent.parent / "Text/SystemText.c"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    _require_session_tools("labwc")
    binary = tmp_path_factory.mktemp("wayland") / "window"
    subprocess.run(
        [
            *shlex.split(os.environ.get("CC", "cc")),
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            f"-I{PROVIDER}",
            NATIVE / "WaylandWindow.c",
            *CLIENT_SOURCES,
            "-o",
            binary,
        ],
        check=True,
    )
    return binary


def test_software_window_lifecycle(client):
    subprocess.run([SESSION, "--wayland", "--", sys.executable, __file__, "lifecycle", client], check=True, timeout=90)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.qualification.dependencies",
            "binary",
            "--target",
            f"linux-{platform.machine()}",
            client,
        ],
        check=True,
        cwd=ROOT,
    )


def test_gpu_display_window_lifecycle(client):
    if not ctypes.util.find_library("wayland-client"):
        pytest.skip("driver-facing GPU surfaces need libwayland-client")
    subprocess.run([SESSION, "--wayland", "--", client, "gpu"], check=True, timeout=90)


@contextmanager
def connected_mouse(probe):
    """Advertise a virtual seat before the GUI client binds its Wayland pointer."""
    with subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse:

        def send(command, x, y):
            mouse.stdin.write(f"{command} {x} {y}\n")
            mouse.stdin.flush()
            assert mouse.stdout.readline().strip() == "sent"

        try:
            send("m", 1, 1)
            yield send
        finally:
            mouse.stdin.close()


@pytest.fixture(scope="module")
def input_device(client):
    if not shutil.which("grim"):
        pytest.skip("the compositor pixel comparison uses grim")
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True)
    probe = client.parent / "input"
    subprocess.run(
        [
            *shlex.split(os.environ.get("CC", "cc")),
            NATIVE / "WaylandWindowInput.c",
            PROBE / "WaylandInput.c",
            *sorted((PROBE / "wayland").glob("*-protocol.c")),
            *shlex.split(flags),
            "-o",
            probe,
        ],
        check=True,
    )
    return probe


def test_software_window_compositor_pixels_and_input(client, input_device):
    subprocess.run([SESSION, "--wayland", "--", sys.executable, __file__, client, input_device], check=True, timeout=50)


@pytest.fixture(scope="module")
def portal_child(client):
    scanner = shutil.which("wayland-scanner")
    directory = os.environ.get("WAYLAND_PROTOCOLS_DIR")
    if not directory:
        path = subprocess.run(
            ["pkg-config", "--variable=pkgdatadir", "wayland-protocols"], capture_output=True, text=True
        )
        directory = path.stdout.strip()
    if not scanner or not directory:
        pytest.skip("building the independent portal client needs the Wayland protocol SDK")
    folder = client.parent
    units = []
    for name, spec in (
        ("xdg-shell", "stable/xdg-shell/xdg-shell.xml"),
        ("xdg-foreign-v1", "unstable/xdg-foreign/xdg-foreign-unstable-v1.xml"),
        ("xdg-foreign-v2", "unstable/xdg-foreign/xdg-foreign-unstable-v2.xml"),
    ):
        header, unit = folder / f"{name}.h", folder / f"{name}.c"
        subprocess.run([scanner, "client-header", Path(directory) / spec, header], check=True)
        subprocess.run([scanner, "private-code", Path(directory) / spec, unit], check=True)
        units.append(unit)
    program = folder / "portal-child"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True))
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{folder}",
            NATIVE / "WaylandPortalParent.c",
            *units,
            *flags,
            "-o",
            program,
        ],
        check=True,
    )
    return program


@pytest.mark.parametrize("mode", ["export-v1", "export-v2", "export-gpu-v2"])
def test_portal_parent_export_lifetime(mode, client, portal_child):
    status = subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, mode, client, portal_child], timeout=25
    )
    if status.returncode == 77:
        pytest.skip("the compositor does not provide the selected xdg-foreign protocol")
    assert status.returncode == 0


def foreign_parent(mode, program, child):
    with subprocess.Popen([program, mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as app:
        try:
            for _ in range(2):
                identifier = app.stdout.readline().strip()
                if identifier == "exporter unavailable":
                    sys.exit(77)
                assert identifier.startswith("wayland:")
                with subprocess.Popen([child, mode, identifier], stdout=subprocess.PIPE, text=True) as other:
                    try:
                        assert other.stdout.readline().strip() == "parent attached"
                        app.stdin.write("\n")
                        app.stdin.flush()
                        assert other.wait(timeout=4) == 0
                    finally:
                        if other.poll() is None:
                            other.kill()
            assert app.wait(timeout=4) == 0
        finally:
            if app.poll() is None:
                app.kill()


@pytest.mark.parametrize("mode", ["ime", "gpu-ime"])
def test_compositor_input_method_transaction(mode, client):
    if subprocess.run(["pkg-config", "--exists", "wayland-client"]).returncode:
        pytest.skip("the independent input method fixture needs the Wayland client SDK")
    peer = client.parent / "ime"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True))
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", NATIVE / "WaylandInputMethod.c", *flags, "-o", peer],
        check=True,
    )
    result = subprocess.run([SESSION, "--wayland", "--", sys.executable, __file__, mode, client, peer], timeout=25)
    if result.returncode == 77:
        pytest.skip("compositor does not advertise an input method manager")
    assert result.returncode == 0


def ime(mode, client, peer):
    with subprocess.Popen([peer], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as method:
        try:
            ready = method.stdout.readline().strip()
            if ready == "IM unavailable":
                sys.exit(77)
            assert ready == "IM ready"
            with subprocess.Popen([client, mode], stdout=subprocess.PIPE, text=True) as app:
                try:
                    assert app.stdout.readline().strip() == "text window ready"
                    assert ("libwayland-client" in Path(f"/proc/{app.pid}/maps").read_text()) == (mode == "gpu-ime")
                    assert app.stdout.readline().strip() == "preedit"
                    method.stdin.write("\n")
                    method.stdin.flush()
                    assert method.wait(timeout=4) == 0 and app.wait(timeout=4) == 0
                finally:
                    if app.poll() is None:
                        app.kill()
        finally:
            if method.poll() is None:
                method.kill()


@pytest.mark.parametrize("mode", ["cursor", "core-cursor"])
def test_wayland_pointer_cursor_shapes(mode, client, input_device):
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, mode, client, input_device], check=True, timeout=25
    )


def cursor_shapes(mode, client, probe):
    def cursor_pixels(x, y, logical_x, accept):
        mouse.stdin.write(f"{x} {y}\n")
        mouse.stdin.flush()
        assert mouse.stdout.readline().strip() == "moved"
        while True:
            event = process.stdout.readline()
            assert event, "the cursor client exited before observing the pointer"
            if event.strip() == f"pointer {logical_x}":
                break
        end = time.monotonic() + 3
        while time.monotonic() < end:
            ppm = subprocess.check_output(["grim", "-c", "-t", "ppm", "-"], timeout=5)
            header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", ppm)
            assert header
            width = int(header[1])
            rows = []
            for row in range(y - 18, y + 26):
                offset = header.end() + (row * width + x - 18) * 3
                rows.append(ppm[offset : offset + 44 * 3])
            shape = b"".join(rows)
            if shape != bytes((37, 179, 125)) * (44 * 44) and accept(shape):
                return shape
            time.sleep(0.02)
        pytest.fail("the compositor did not display the requested pointer cursor")

    with (
        subprocess.Popen([client, mode], stdout=subprocess.PIPE, text=True) as process,
        subprocess.Popen([probe, "motion"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:
            mechanism = process.stdout.readline().strip()
            assert mechanism in ("core shapes", "system shapes")
            if mode == "core-cursor":
                assert mechanism == "core shapes"
            cx, cy = map(int, locate_color(160, 100))
            # Request a text cursor first: the compositor may supply its own
            # arrow while the new input device enters the client's window.
            cursor_pixels(
                cx + 32, cy, 112, lambda shape: mechanism != "core shapes" or bytes((25, 25, 25)) * 4 in shape
            )
            arrow = cursor_pixels(
                cx - 32, cy, 48, lambda shape: mechanism != "core shapes" or bytes((25, 25, 25)) * 4 in shape
            )
            cursor_pixels(cx + 32, cy, 112, lambda shape: shape != arrow)
            cursor_pixels(cx - 32, cy, 48, lambda shape: shape == arrow)
            subprocess.run([probe, "close"], check=True)
            assert process.wait(timeout=3) == 0
        finally:
            mouse.stdin.close()
            if process.poll() is None:
                process.kill()


def test_wayland_held_key_repeats_until_release(client, input_device):
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "repeat", client, input_device], check=True, timeout=20
    )


def test_wayland_focused_scene_receives_text_before_window_subscription(client, input_device):
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "scene-text", client, input_device],
        check=True,
        timeout=20,
    )


def keyboard_input(mode, client, probe):
    with subprocess.Popen([client, mode], stdout=subprocess.PIPE, text=True) as process:
        try:
            assert process.stdout.readline().strip() == "keyboard ready"
            subprocess.run([probe, mode], check=True, timeout=6)
            output = process.communicate(timeout=5)[0]
            assert process.returncode == 0, output
        finally:
            if process.poll() is None:
                process.kill()


def shim_program(fixture, directory, link_flags=()):
    program = directory / fixture
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-pthread",
            f"-I{PROVIDER}",
            NATIVE / f"{fixture}.c",
            *CLIENT_SOURCES,
            *PLATFORM_SOURCES,
            SYSTEM_TEXT,
            *link_flags,
            "-lm",
            "-o",
            program,
        ],
        check=True,
    )
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    return program


def test_control_changes_submit_one_software_frame(client):
    program = shim_program("WaylandFrameChanges", client.parent, ["-Wl,--wrap=btrcWaylandWindowPaint"])
    subprocess.run([SESSION, "--wayland", "--", program], check=True, timeout=15)


@pytest.mark.parametrize(
    ("fixture", "scenario"),
    [
        ("WaylandScene", "scene"),
        ("WaylandIndicators", "indicators"),
        ("WaylandScrollbars", "scrollbars"),
        ("WaylandSlider", "slider"),
    ],
)
def test_software_control_placement_and_capture(fixture, scenario, client, input_device):
    program = shim_program(fixture, client.parent)
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, scenario, program, input_device], check=True, timeout=45
    )


@pytest.mark.parametrize("mode", ["clipboard", "gpu-clipboard"])
def test_clipboard_interoperability(mode, client, input_device):
    if not all(shutil.which(t) for t in ("wl-copy", "wl-paste")):
        pytest.skip("independent clipboard transfers use wl-clipboard")
    program = shim_program("WaylandClipboard", client.parent)
    reader = client.parent / "clipboard-reader"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True))
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", NATIVE / "WaylandClipboardReader.c", *flags, "-o", reader],
        check=True,
    )
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, mode, program, input_device, reader],
        check=True,
        timeout=45,
    )


def clipboard(mode, program, probe, receiver):
    mime = "text/plain;charset=utf-8"

    def copy(data, kind=mime):
        subprocess.run(["wl-copy", "--type", kind], input=data, stdout=subprocess.DEVNULL, check=True, timeout=3)

    def assert_paste(expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = subprocess.run(["wl-paste", "--no-newline", "--type", mime], capture_output=True, timeout=3)
            if not result.returncode and result.stdout == expected:
                return
        pytest.fail(f"external reader failed to receive {len(expected)} bytes: {result.stderr!r}")

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "clipboard"
        with (
            subprocess.Popen([probe, "keyboard"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as keyboard,
            subprocess.Popen([program, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as app,
        ):

            def command(key):
                app.stdin.write(key)
                app.stdin.flush()
                return app.stdout.readline().strip()

            def send_key():
                keyboard.stdin.write(b"k")
                keyboard.stdin.flush()
                assert keyboard.stdout.readline().strip() == b"sent"
                end = time.monotonic() + 3
                while command(b"k") == b"waiting":
                    assert time.monotonic() < end

            def read(expected):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    result = command(b"r")
                    if expected is None and result == b"absent":
                        return
                    if result == b"read" and path.read_bytes() == expected:
                        return
                pytest.fail(f"clipboard read did not match, last reply {result!r}")

            try:
                assert app.stdout.readline().strip() == b"shown"
                maps = Path(f"/proc/{app.pid}/maps")
                assert "libwayland-client" not in maps.read_text()
                read(None)
                incoming = "Externally owned ä🟢完成\n".encode() * 12000
                outgoing = "Program clipboard 🌏é\n".encode() * 12000
                send_key()
                path.write_bytes(outgoing)
                assert command(b"w") == b"written"
                assert_paste(outgoing)
                copy(incoming)
                read(incoming)
                # A freshly mapped, independent window acquires keyboard focus.
                with subprocess.Popen(
                    [program, path, "other window"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
                ) as other:
                    try:
                        assert other.stdout.readline().strip() == b"shown"
                        copy(b"changed in background")
                        read(None)
                        other.stdin.write(b"q")
                        other.stdin.flush()
                        assert other.wait(timeout=3) == 0
                    finally:
                        if other.poll() is None:
                            other.kill()
                send_key()
                read(b"changed in background")
                copy(incoming)
                read(incoming)
                if mode == "gpu-clipboard":
                    assert command(b"g") == b"attached"
                    assert "libwayland-client" in maps.read_text()
                    read(incoming)
                # A foreign source may stop responding after it advertises text.
                with subprocess.Popen(["wl-copy", "--foreground", "--type", mime, "replacement"]) as owner:
                    try:
                        read(b"replacement")
                        owner.send_signal(signal.SIGSTOP)
                        start = time.monotonic()
                        assert command(b"r") == b"unavailable"
                        assert 0.9 <= time.monotonic() - start <= 2.0
                        owner.send_signal(signal.SIGCONT)
                        read(b"replacement")
                    finally:
                        owner.kill()
                copy(b"\x89PNG", "image/png")
                read(None)
                send_key()
                path.write_bytes(outgoing)
                assert command(b"w") == b"written"
                assert_paste(outgoing)
                target = Path(temp) / "pasted"
                target.touch()
                subprocess.run([receiver, target], check=True, timeout=3)
                end = time.monotonic() + 3
                while target.stat().st_size < len(outgoing) and time.monotonic() < end:
                    time.sleep(0.01)
                assert target.read_bytes() == outgoing
                fifo = Path(temp) / "slow-reader"
                os.mkfifo(fifo)
                fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    subprocess.run([receiver, fifo], check=True, timeout=3)
                    assert command(b"r") == b"read"
                finally:
                    os.close(fd)
                assert_paste(outgoing)
                read(outgoing)
                path.write_bytes(b"")
                assert command(b"w") == b"written"
                assert_paste(b"")
                copy(b"new owner")
                read(b"new owner")
                subprocess.run(["wl-copy", "--clear"], check=True, timeout=3)
                read(None)
                if mode == "clipboard":
                    assert "libwayland-client" not in maps.read_text()
                app.stdin.write(b"q")
                app.stdin.flush()
                assert app.wait(timeout=3) == 0
            finally:
                keyboard.stdin.close()
                if app.poll() is None:
                    app.kill()


def indicator_pixels(program, probe):
    green = bytes((37, 179, 125))

    def capture(color, fraction):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            screen = subprocess.check_output(["grim", "-t", "ppm", "-"])
            header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screen)
            assert header
            width = int(header[1])
            start = screen.find(green * 160, header.end())
            if start < 0:
                continue
            offset = start + (width * 22 + 17) * 3
            row = screen[offset : offset + 98 * 3]
            extent = round(98 * fraction)
            if row != bytes(color) * extent + bytes((72, 72, 72)) * (98 - extent):
                time.sleep(0.02)
                continue
            return b"".join(screen[start + (width * y + 72) * 3 : start + (width * y + 88) * 3] for y in range(50, 66))
        pytest.fail("the compositor did not show the expected level value and threshold color")

    with subprocess.Popen([program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as app:
        try:
            assert app.stdout.readline().strip() == "indicators ready"
            empty = green * (16 * 16)
            assert capture((80, 190, 110), 0.5) == empty
            app.stdin.write("\n")
            app.stdin.flush()
            assert app.stdout.readline().strip() == "state 1"
            frames = set()
            end = time.monotonic() + 2
            while len(frames) < 3 and time.monotonic() < end:
                frames.add(capture((235, 180, 50), 0.7))
            assert len(frames - {empty}) >= 2
            app.stdin.write("\n")
            app.stdin.flush()
            assert app.stdout.readline().strip() == "state 2"
            assert capture((220, 70, 70), 0.9) == empty
            subprocess.run([probe, "close"], check=True)
            assert app.wait(timeout=4) == 0
        finally:
            if app.poll() is None:
                app.kill()


def slider_pixels(program, probe):
    green = bytes((37, 179, 125))
    handle = bytes((222, 222, 222))

    def capture(center):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            screen = subprocess.check_output(["grim", "-t", "ppm", "-"])
            header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screen)
            assert header
            width = int(header[1])
            start = screen.find(green * 160, header.end())
            if start < 0:
                continue
            row = start + width * 47 * 3
            if screen[row + (center - 7) * 3 : row + (center + 7) * 3] == handle * 14:
                y, x = divmod((start - header.end()) // 3, width)
                return x, y
        pytest.fail("the native slider did not show its model's thumb position")

    with (
        subprocess.Popen([program], stdout=subprocess.PIPE, text=True) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:
            assert app.stdout.readline().strip() == "shown"
            x, y = capture(80)

            def send(command, dx, dy):
                mouse.stdin.write(f"{command} {x + dx} {y + dy}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            send("d", 80, 47)
            send("m", 145, 47)
            capture(133)
            send("u", 145, 47)
            assert app.stdout.readline().strip() == "commit 10.00"
            send("d", 133, 47)
            send("m", 15, 47)
            capture(27)
            send("e", 15, 47)
            assert app.stdout.readline().strip() == "cancel 10.00"
            send("u", 15, 47)
            capture(133)
            send("l", 15, 47)
            assert app.stdout.readline().strip() == "step 9.00"
            capture(122)
            subprocess.run([probe, "close"], check=True)
            assert app.wait(timeout=3) == 0
        finally:
            mouse.stdin.close()
            if app.poll() is None:
                app.kill()


def scrollbar_pixels(program, probe):
    green = bytes((37, 179, 125))
    thumb = bytes((157, 157, 157))

    def capture(at_end=False):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            screen = subprocess.check_output(["grim", "-t", "ppm", "-"])
            header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screen)
            assert header
            width = int(header[1])
            start = screen.find(green * 160, header.end())
            if start < 0:
                continue
            row = start + width * 85 * 3
            knob = screen[row + 10 * 3 : row + 130 * 3]
            expected = (78, 79) if at_end else (2, 3)
            if knob.find(thumb * 32) // 3 in expected:
                y, x = divmod((start - header.end()) // 3, width)
                return x, y
        pytest.fail("horizontal thumb did not reach the expected compositor pixels")

    with (
        subprocess.Popen([program], stdout=subprocess.PIPE, text=True) as app,
        subprocess.Popen([probe, "mouse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as mouse,
    ):
        try:
            assert app.stdout.readline().strip() == "shown"
            x, y = capture()

            def send(command, dx, dy):
                mouse.stdin.write(f"{command} {x + dx} {y + dy}\n")
                mouse.stdin.flush()
                assert mouse.stdout.readline().strip() == "sent"

            send("d", 24, 85)
            send("m", 148, 90)
            send("u", 148, 90)
            assert app.stdout.readline().strip() == "horizontal 400.00"
            capture(at_end=True)
            send("d", 142, 20)
            send("m", 142, 96)
            send("u", 142, 96)
            assert app.stdout.readline().strip() == "vertical 160.00"
            send("w", 142, 60)
            assert app.stdout.readline().strip() == "vertical 112.00"
            subprocess.run([probe, "close"], check=True)
            assert app.wait(timeout=4) == 0
        finally:
            mouse.stdin.close()
            if app.poll() is None:
                app.kill()


def scene_pixels(program, probe):
    with subprocess.Popen([program], stdout=subprocess.PIPE, text=True) as client:
        try:
            assert client.stdout.readline().strip() == "scene ready"
            assert "libwayland-client" not in Path(f"/proc/{client.pid}/maps").read_text()
            green, yellow, blue = bytes((37, 179, 125)), bytes((255, 255, 0)), bytes((0, 0, 255))
            end = time.monotonic() + 4
            while time.monotonic() < end:
                screen = subprocess.check_output(["grim", "-t", "ppm", "-"])
                header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screen)
                assert header
                start = screen.find(green * 160, header.end())
                if start >= 0:
                    width = int(header[1])
                    for y in range(100):
                        row = [green] * 160
                        if 20 <= y < 70:
                            row[24:120] = [yellow] * 96
                        if 30 <= y < 52:
                            row[50:80] = [green] * 30
                        if 35 <= y < 47:
                            row[56:80] = [blue] * 24
                        offset = start + y * width * 3
                        assert screen[offset : offset + 480] == b"".join(row), y
                    break
                time.sleep(0.03)
            else:
                pytest.fail("the native software control scene did not reach the compositor")
            subprocess.run([probe, "close"], check=True)
            assert client.wait(timeout=4) == 0
        finally:
            if client.poll() is None:
                client.kill()


def locate_color(width, height, *, gpu=False):
    """Read pixels from the compositor; the client cannot discover its own global position."""
    color = b"\x25\xb3\x7d" * 8
    end = time.monotonic() + 4
    while time.monotonic() < end:
        screenshot = subprocess.check_output(["grim", "-t", "ppm", "-"], timeout=4)
        header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", screenshot)
        assert header, "grim returned an invalid PPM header"
        pixels = memoryview(screenshot)[header.end() :]
        screen_width = int(header[1])
        first = screenshot.find(color, header.end()) - header.end()
        if first >= 0:
            last = screenshot.rfind(color) - header.end()
            row, x = divmod(first // 3, screen_width)
            bottom, right = divmod(last // 3, screen_width)
            if bottom - row + 1 == height and right - x + 8 == width:
                green = color[:3] * width
                child = color[:3] * 40 + b"\xff\x00\x00" * 80 + color[:3] * 40
                for dy in range(height):
                    start = ((row + dy) * screen_width + x) * 3
                    expected = child if gpu and 25 <= dy < 75 else green
                    if pixels[start : start + width * 3] != expected:
                        break
                else:
                    return str(x + width // 2), str(row + height // 2)
        time.sleep(0.03)
    raise AssertionError(f"the compositor never displayed a {width}x{height} rectangle of the submitted color")


def lifecycle(client):
    subprocess.run([client], check=True, timeout=60)
    address = str(Path(os.environ["XDG_RUNTIME_DIR"]) / os.environ["WAYLAND_DISPLAY"])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(address)
        fd = connection.fileno()
        with subprocess.Popen(
            [client, "disconnect"],
            env={**os.environ, "WAYLAND_SOCKET": str(fd)},
            pass_fds=(fd,),
            stdout=subprocess.PIPE,
            text=True,
        ) as process:
            assert process.stdout.readline().strip() == "ready"
            connection.shutdown(socket.SHUT_RDWR)
            assert process.wait(timeout=5) == 0


def interact(client, probe):
    assert os.environ["BTRC_UI_PRIVATE_SESSION"] == "1" and "DISPLAY" not in os.environ
    mode = ["wlr-randr", "--output", "HEADLESS-1", "--scale"]
    subprocess.run([*mode, "2"], check=True)
    with subprocess.Popen([client, "interactive"], stdout=subprocess.PIPE, text=True) as process:
        try:
            assert process.stdout.readline().strip() == "ready"
            locate_color(320, 200)
            subprocess.run([*mode, "1"], check=True)
            x, y = locate_color(160, 100)
            subprocess.run([probe, x, y], check=True)
            subprocess.run([*mode, "2"], check=True)
            locate_color(320, 200)
            subprocess.run([probe, "close"], check=True)
            output, _ = process.communicate(timeout=10)
            assert process.returncode == 0, output
        finally:
            if process.poll() is None:
                process.kill()


@pytest.fixture(scope="module")
def native_wayland_root(tmp_path_factory):
    """Qualify native control methods while the shipping Linux GUI still uses GTK."""
    root = GUIProviderRoot.create(tmp_path_factory.mktemp("wayland-provider"))
    manifest = root / "stdlib/GUI/btrc.toml"
    text = manifest.read_text().replace(
        'modules = ["Linux.Fonts.SystemTextABI"]', 'modules = ["Linux.Fonts.SystemTextABI", "Shim.Shim"]'
    )
    sections = re.split(r"(?=^\[\[native\.)", text, flags=re.MULTILINE)
    preserved = []
    for section in sections:
        if section.startswith("[[native.sources]]"):
            source = tomllib.loads(section)["native"]["sources"][0]
            if source["path"].startswith("Linux/"):
                continue
        if section.startswith("[[native.pkg-config]]"):
            package = tomllib.loads(section)["native"]["pkg-config"][0]
            if package.get("os") == ["linux"] and package["name"] != "wgpu-native":
                continue
        preserved.append(section)
    # Real sources and binding definitions, with the intended native platform selection.
    for path in (*CLIENT_SOURCES, *PLATFORM_SOURCES, PROVIDER / "Surface.c"):
        module = "Shim.ShimSurface" if path.name == "Surface.c" else "Shim.Shim"
        preserved.append(
            f'\n[[native.sources]]\npath = "{path.relative_to(PROVIDER.parent.parent).as_posix()}"\nlanguage = "c"\nstandard = "c11"\n'
            f'modules = ["{module}"]\nos = ["linux"]\n'
        )
    manifest.write_text("".join(preserved))
    return root


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_native_control_interfaces(frontend, native_wayland_root, tmp_path, request):
    require_linux_reader()
    _require_session_tools("labwc")
    if subprocess.run(["pkg-config", "--exists", "wgpu-native"]).returncode:
        pytest.skip("the shared GUI painter imports the wgpu-native SDK")
    generated, plan, program = (tmp_path / name for name in ("Program.c", "Program.json", "Program"))
    transpile_provider_program(
        NATIVE / "WaylandControlInterfaces.btrc", generated, plan, frontend, request, native_wayland_root
    )
    dependencies = {entry["name"] for entry in json.loads(plan.read_text())["pkg-config"]}
    assert dependencies <= {"wgpu-native"}
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=program,
        optimization=0,
        compile_flags=["-ffunction-sections", "-fdata-sections"],
        link_flags=["-Wl,--gc-sections", "-lm"],
    )
    assert not DependencyAudit().binary_problems(program, f"linux-{platform.machine()}")
    subprocess.run([SESSION, "--wayland", "--", program], check=True, timeout=25)


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_public_gpu_renderer_attaches_to_an_existing_software_window(frontend, input_device, tmp_path, request):
    require_linux_reader()
    if subprocess.run(["pkg-config", "--exists", "wgpu-native"]).returncode:
        pytest.skip("GPU presentation needs the wgpu-native SDK")
    symbols = (
        "openSoftwareWindow",
        "closeSoftwareWindow",
        "createGPUInstance",
        "attachGPUView",
        "waitForInput",
        "WGPUInstance",
        "WGPUSurface",
        "wgpuInstanceAddRef",
        "wgpuInstanceRelease",
        "wgpuSurfaceAddRef",
        "wgpuSurfaceRelease",
    )
    source = NativeBindingPackage.write(
        NATIVE / "WaylandGPUPresentation.btrc", tmp_path / "package", NATIVE / "WaylandGPUPresentation.h", symbols
    )
    manifest = source.parent.parent / "btrc.toml"
    with manifest.open("a") as output:
        output.write(
            """
owned-results = ["createGPUInstance", "attachGPUView"]
borrowed-parameters = ["attachGPUView.instance"]
[native.bindings.resources.WGPUInstance]
ownership = "reference-counted"
retain = "wgpuInstanceAddRef"
release = "wgpuInstanceRelease"
[native.bindings.resources.WGPUSurface]
ownership = "reference-counted"
retain = "wgpuSurfaceAddRef"
release = "wgpuSurfaceRelease"
[[native.pkg-config]]
name = "wgpu-native"
modules = ["WaylandGPUPresentation"]
os = ["linux"]
"""
        )
    generated, plan, binary = (tmp_path / name for name in ("program.c", "program.json", "program"))
    transpile_provider_program(source, generated, plan, frontend, request)
    sdk = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "wgpu-native"], text=True))
    native = []
    for unit in (
        NATIVE / "WaylandGPUPresentation.c",
        *CLIENT_SOURCES,
        *PLATFORM_SOURCES,
        SYSTEM_TEXT,
        PROVIDER / "Surface.c",
    ):
        obj = tmp_path / (unit.stem + ".o")
        subprocess.run(
            [
                "cc",
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{PROVIDER}",
                *sdk,
                "-c",
                unit,
                "-o",
                obj,
            ],
            check=True,
        )
        native.append(str(obj))
    NativePlanBuilder().build(
        plan_path=plan, generated_c=generated, output=binary, cc="cc", cxx="c++", link_flags=[*native, "-lm"]
    )
    assert not DependencyAudit().binary_problems(binary, f"linux-{platform.machine()}")
    subprocess.run(
        [SESSION, "--wayland", "--", sys.executable, __file__, "gpu", binary, input_device], check=True, timeout=60
    )


def gpu_presentation(program, probe):
    assert os.environ["BTRC_UI_PRIVATE_SESSION"] == "1" and "DISPLAY" not in os.environ
    with subprocess.Popen([program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as client:
        try:
            assert client.stdout.readline().strip() == "software ready"
            maps = Path(f"/proc/{client.pid}/maps")
            assert "libwayland-client" not in maps.read_text()
            position = locate_color(160, 100)
            client.stdin.write("\n")
            client.stdin.flush()
            assert client.stdout.readline().strip() == "GPU ready"
            assert "libwayland-client" in maps.read_text()
            assert locate_color(160, 100, gpu=True) == position
            subprocess.run([probe, *position], check=True)
            assert client.stdout.readline().strip() == "input received"
            subprocess.run([probe, "close"], check=True)
            assert client.wait(timeout=10) == 0
        finally:
            if client.poll() is None:
                client.kill()


if __name__ == "__main__":
    if sys.argv[1] == "lifecycle":
        lifecycle(sys.argv[2])
    elif sys.argv[1].startswith("export-"):
        foreign_parent(*sys.argv[1:])
    elif sys.argv[1] in ("ime", "gpu-ime"):
        ime(*sys.argv[1:])
    elif sys.argv[1] in ("cursor", "core-cursor"):
        cursor_shapes(*sys.argv[1:])
    elif sys.argv[1] in ("repeat", "scene-text"):
        keyboard_input(*sys.argv[1:])
    elif sys.argv[1] in ("clipboard", "gpu-clipboard"):
        clipboard(*sys.argv[1:])
    elif sys.argv[1] == "indicators":
        indicator_pixels(*sys.argv[2:])
    elif sys.argv[1] == "slider":
        slider_pixels(*sys.argv[2:])
    elif sys.argv[1] == "scrollbars":
        scrollbar_pixels(*sys.argv[2:])
    elif sys.argv[1] == "scene":
        scene_pixels(*sys.argv[2:])
    elif sys.argv[1] == "gpu":
        gpu_presentation(*sys.argv[2:])
    else:
        interact(*sys.argv[1:])
