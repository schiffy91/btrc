"""Native shared frame delivery through the Library.GUI control."""

import contextlib
import os
import re
import select
import shlex
import shutil
import struct
import subprocess
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


def send(process, address, width, format_code):
    process.stdin.write(f"{address} {width} {format_code}\n")
    process.stdin.flush()
    assert select.select([process.stdout], [], [], 3)[0], "producer timed out"
    return process.stdout.readline().strip()


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
    if not os.environ.get("WAYLAND_DISPLAY"):
        pytest.skip("requires a Wayland compositor")
    nodes = sorted(Path("/dev/dri").glob("renderD*"))
    if not nodes:
        pytest.skip("requires a DRM render node")
    source = REPO / "src/tests/native/gui/shared_frame_view"
    viewer = build_provider_program(source / "Main.btrc", tmp_path, frontend, False, request)
    sender = tmp_path / "sender"
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
    exercise_viewer(tmp_path, provider_environment(False), viewer, [sender, nodes[0]], "1", "0")


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_wayland_preview_shared_frame_view(tmp_path, request, frontend):
    from src.tests.python.test_wayland_public_preview import build_app

    if not os.environ.get("WAYLAND_DISPLAY") or not os.access("/dev/udmabuf", os.R_OK | os.W_OK):
        pytest.skip("requires Wayland and the Linux udmabuf device")
    if not shutil.which("grim"):
        pytest.skip("requires grim for the independent compositor pixel capture")
    source = REPO / "src/tests/native/gui/shared_frame_view"
    viewer = build_app(frontend, source / "Main.btrc", tmp_path, request)
    sender = tmp_path / "sender"
    subprocess.run(
        ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", source / "ProducerLinuxKernel.c", "-o", sender],
        check=True,
    )
    exercise_viewer(tmp_path, os.environ.copy(), viewer, [sender], "1", "0", observe=observe_shared_pixels)


def observe_shared_pixels():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ppm = subprocess.check_output(["grim", "-t", "ppm", "-"], timeout=5)
        header = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", ppm)
        assert header
        width, height = map(int, header.groups())
        pixels = memoryview(ppm)[header.end() :]
        assert len(pixels) == width * height * 3
        reds = blues = red_y = blue_y = 0
        for i, (r, g, b) in enumerate(struct.iter_unpack("BBB", pixels)):
            if (r, g, b) == (255, 0, 0):
                reds += 1
                red_y += i // width
            elif (r, g, b) == (0, 0, 255):
                blues += 1
                blue_y += i // width
        if min(reds, blues) >= 80000 and red_y * blues < blue_y * reds:
            return
        time.sleep(0.05)
    pytest.fail("shared-frame pixels did not show the producer's red upper and blue lower halves")


def exercise_viewer(root, env, viewer, sender, valid, invalid, observe=None):
    with contextlib.ExitStack() as stack:

        def launch(argv):
            proc = subprocess.Popen(
                argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stack.enter_context(proc)
            stack.callback(lambda: proc.kill() if proc.poll() is None else None)
            return proc

        producer = launch(sender)
        stranger = launch(sender)
        app = launch([viewer, root, str(producer.pid)])
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
                address = wait_file(root / "second", app)
                assert address != first
                assert send(producer, first, width, fourcc) == "closed"
            assert send(peer, address, width, fourcc) == "sent"
            (root / f"sent-{step}").touch()
            wait_file(root / f"done-{step}", app)
            if step == 2 and observe:
                observe()
        assert app.wait(timeout=5) == 0, app.stderr.read()
        assert send(producer, address, 320, valid) == "closed"
