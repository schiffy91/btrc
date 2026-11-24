"""Native shared frame delivery through the Library.GUI control."""

import contextlib
import os
import queue
import re
import shlex
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_provider_program, provider_environment, require_linux_reader
from src.tests.python.native_import_fixtures import REPO, apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def wait_file(path, process):
    deadline = time.monotonic() + 12
    while not path.exists():
        if process.poll() is not None:
            pytest.fail(f"viewer exited early: {process.stderr.read()}")
        if time.monotonic() >= deadline:
            pytest.fail(f"viewer did not publish {path.name}")
        time.sleep(0.01)
    return path.read_text()


def read_output(process):
    lines = queue.Queue()

    def collect():
        for line in process.stdout:
            lines.put(line.strip())
        lines.put("<producer exited>")

    threading.Thread(target=collect, daemon=True).start()
    return lines


def send(process, lines, address, width, format_code):
    process.stdin.write(f"{address} {width} {format_code}\n")
    process.stdin.flush()
    return lines.get(timeout=10)


@pytest.mark.macos_gui
def test_shared_frame_view_checks_sender_format_and_session(native_project, native_compile, gui_provider_root):
    root = native_project[0].parent.parent / "frame-view"
    shutil.copytree(REPO / "src/tests/native/gui/shared_frame_view", root)
    plan = root / "Program.link.json"
    compiled = native_compile(root / "Main.btrc", plan_path=plan)
    assert compiled.successful, str(compiled.failure) + "\n" + "\n".join(map(str, compiled.diagnostics))
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)
    env = apple_environment()

    def run(command, **kwargs):
        return subprocess.run(command, env=env, **kwargs)

    viewer = root / "viewer"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=viewer, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    sender = root / "sender"
    run(
        [
            "/usr/bin/clang",
            "-Wall",
            "-Wextra",
            "-Werror",
            root / "Producer.m",
            "-framework",
            "Foundation",
            "-framework",
            "CoreFoundation",
            "-framework",
            "IOSurface",
            "-o",
            sender,
        ],
        check=True,
    )
    exercise_viewer(root, env, viewer, [sender], "42475241", "52474241")


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_linux_shared_frame_view(tmp_path, request, frontend):
    require_linux_reader()
    sources = [("/dev/udmabuf", []), ("/dev/dma_heap/system", ["system"])]
    available = [args for device, args in sources if os.access(device, os.R_OK | os.W_OK)]
    if not os.environ.get("WAYLAND_DISPLAY") or not available:
        pytest.skip("requires Wayland and udmabuf or the Linux system DMA heap")
    source = REPO / "src/tests/native/gui/shared_frame_view"
    viewer = build_provider_program(source / "Main.btrc", tmp_path, frontend, False, request)
    sender = tmp_path / "kernel-producer"
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", source / "ProducerLinuxKernel.c", "-o", sender],
        check=True,
    )
    for args in available:
        folder = tmp_path / ("system" if args else "udmabuf")
        folder.mkdir()
        exercise_viewer(folder, provider_environment(False), viewer, [sender, *args], "1", "0")


def compile_gpu_producer(source, sender):
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "egl", "glesv2", "gbm"], text=True)
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            source / "ProducerLinux.c",
            *shlex.split(flags),
            "-o",
            sender,
        ],
        check=True,
    )


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("case", ["session", "capture", "driver"])
def test_wayland_preview_shared_frame_view(tmp_path, request, frontend, case):
    from src.tests.python.test_wayland_public_preview import build_app

    sources = [("/dev/udmabuf", []), ("/dev/dma_heap/system", ["system"])]
    available = [args for device, args in sources if os.access(device, os.R_OK | os.W_OK)]
    if not os.environ.get("WAYLAND_DISPLAY") or not available:
        pytest.skip("requires Wayland and udmabuf or the Linux system DMA heap")
    if not shutil.which("grim"):
        pytest.skip("requires grim for the independent compositor pixel capture")
    source = REPO / "src/tests/native/gui/shared_frame_view"
    gpu_producer = tmp_path / "egl-producer"
    if case == "driver":
        nodes = sorted(Path("/dev/dri").glob("renderD*"))
        if not nodes or subprocess.run(["pkg-config", "--exists", "egl", "glesv2", "gbm"]).returncode:
            pytest.skip("the GPU producer requires a render node and EGL/GBM development files")
        compile_gpu_producer(source, gpu_producer)
    fixture = "Main.btrc" if case == "session" else "WaylandSharedFrameCapture.btrc"
    viewer = build_app(frontend, source / fixture, tmp_path, request)
    sender = tmp_path / "sender"
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", source / "ProducerLinuxKernel.c", "-o", sender],
        check=True,
    )
    for args in available:
        folder = tmp_path / ("system" if args else "udmabuf")
        folder.mkdir()
        if case == "session":
            exercise_viewer(folder, os.environ.copy(), viewer, [sender, *args], "1", "0", observe=observe_shared_pixels)
        else:
            with contextlib.ExitStack() as stack:
                command = [sender, *args]
                if case == "driver":
                    command = [sender, folder.name, gpu_producer, nodes[0]]
                producer = launch(stack, command, os.environ)
                lines = read_output(producer)
                app = launch(stack, [viewer, folder, str(producer.pid)], os.environ)
                address = wait_file(folder / "address", app)
                assert send(producer, lines, address, 640, "1") == "sent"
                (folder / "sent").touch()
                wait_file(folder / "shown", app)
                observe_shared_pixels()
                if case == "driver":
                    assert send(producer, lines, address, 320, "1") == "sent"
                    (folder / "reject").touch()
                (folder / "observe-overlay").touch()
                wait_file(folder / "mixed", app)
                observe_shared_pixels(mixed=True)
                if case == "capture":
                    assert send(producer, lines, address, 320, "1") == "sent"
                    (folder / "alpha").touch()
                    wait_file(folder / "blended", app)
                    observe_shared_pixels(mixed=True, red=128)
                (folder / "finish").touch()
                assert app.wait(timeout=5) == 0, app.stderr.read()


def observe_shared_pixels(mixed=False, red=255):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ppm = subprocess.check_output(["grim", "-t", "ppm", "-"], timeout=5)
        header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", ppm)
        assert header
        width, height = map(int, header.groups())
        pixels = memoryview(ppm)[header.end() :]
        assert len(pixels) == width * height * 3
        reds = blues = greens = red_y = blue_y = 0
        for i, (r, g, b) in enumerate(struct.iter_unpack("BBB", pixels)):
            if (r, g, b) == (red, 0, 0):
                reds += 1
                red_y += i // width
            elif (r, g, b) == (0, 0, 255):
                blues += 1
                blue_y += i // width
            elif (r, g, b) == (0, 255, 0):
                greens += 1
        if red_y * blues < blue_y * reds:
            if mixed and reds >= 24000 and greens >= 18500 and blues >= 12500:
                return
            if not mixed and min(reds, blues) >= 80000:
                return
        time.sleep(0.05)
    pytest.fail("shared-frame pixels did not show the producer's red upper and blue lower halves")


def launch(stack, argv, env):
    proc = subprocess.Popen(
        argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stack.enter_context(proc)
    stack.callback(lambda: proc.kill() if proc.poll() is None else None)
    return proc


def exercise_viewer(root, env, viewer, sender, valid, invalid, *, verify_dxgi=False, observe=None):
    with contextlib.ExitStack() as stack:
        producer = launch(stack, sender, env)
        stranger = launch(stack, sender, env)
        outputs = {peer: read_output(peer) for peer in (producer, stranger)}
        app = launch(stack, [viewer, root, str(producer.pid)], env)
        first = wait_file(root / "first", app)
        address = first
        for step, (peer, width, fourcc) in enumerate(
            [
                (stranger, 640, valid),
                (producer, 640, invalid),
                (producer, 640, valid),
                (producer, 320, valid),
                (producer, 320, valid),
            ]
        ):
            if step == 4:
                (root / "reconnect").touch()
                address = wait_file(root / "second", app)
                assert address != first
                assert send(producer, outputs[producer], first, width, fourcc) == "closed"
            assert send(peer, outputs[peer], address, width, fourcc) == "sent"
            (root / f"sent-{step}").touch()
            wait_file(root / f"done-{step}", app)
            if verify_dxgi:
                assert outputs[peer].get(timeout=5) == ("accepted" if step >= 2 else "rejected")
                if step >= 2:
                    subprocess.run([*sender, "--pixels", str(app.pid)], check=True, timeout=10, env=env)
            if step == 2 and observe:
                observe()
        (root / "finish").touch()
        assert app.wait(timeout=5) == 0, app.stderr.read()
        assert send(producer, outputs[producer], address, 320, valid) == "closed"
