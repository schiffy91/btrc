import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TRAY = ROOT / "src" / "stdlib" / "tray"
HARNESS = ROOT / "src" / "tests" / "native" / "tray_linux_wire.c"
DISCONNECT_HARNESS = ROOT / "src" / "tests" / "native" / "tray_linux_disconnect.c"


def test_macos_tray_backend_is_strict_objc(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS Cocoa backend")
    clang = shutil.which("clang")
    if not clang:
        pytest.skip("clang is unavailable")
    subprocess.run(
        [
            clang,
            "-std=c11",
            "-fobjc-arc",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-deprecated-declarations",
            f"-I{TRAY}",
            "-c",
            str(TRAY / "btrc_tray_macos.m"),
            "-o",
            str(tmp_path / "tray-macos.o"),
        ],
        check=True,
    )


def test_linux_tray_dbus_wire_contract(tmp_path: Path) -> None:
    pkg_config = shutil.which("pkg-config")
    if not pkg_config:
        pytest.skip("pkg-config is unavailable")
    flags = subprocess.run(
        [pkg_config, "--cflags", "--libs", "dbus-1"],
        capture_output=True,
        check=False,
        text=True,
    )
    if flags.returncode != 0:
        pytest.skip("libdbus development files are unavailable")

    executable = tmp_path / "tray-wire"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{TRAY}",
            str(HARNESS),
            *flags.stdout.split(),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_linux_tray_survives_session_bus_disconnect(tmp_path: Path) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux D-Bus backend")
    pkg_config = shutil.which("pkg-config")
    daemon_path = shutil.which("dbus-daemon")
    if not pkg_config or not daemon_path:
        pytest.skip("D-Bus development/runtime tools are unavailable")
    flags = subprocess.run(
        [pkg_config, "--cflags", "--libs", "dbus-1"],
        capture_output=True,
        check=False,
        text=True,
    )
    if flags.returncode != 0:
        pytest.skip("libdbus development files are unavailable")

    source = (TRAY / "btrc_tray_linux.c").read_text()
    connection = source.index("dbus_bus_get_private")
    disable_exit = source.index("dbus_connection_set_exit_on_disconnect(conn, FALSE)", connection)
    allocation = source.index("calloc(1, sizeof(btrc_tray))", connection)
    assert connection < disable_exit < allocation

    executable = tmp_path / "tray-disconnect"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            f"-I{TRAY}",
            str(DISCONNECT_HARNESS),
            str(TRAY / "btrc_tray_linux.c"),
            *flags.stdout.split(),
            "-o",
            str(executable),
        ],
        check=True,
    )

    # sun_path caps unix sockets at 108 bytes; pytest's tmp_path embeds the
    # username and test name, which can exceed that. Bind somewhere short.
    socket_dir = tempfile.mkdtemp(dir="/tmp", prefix="btrc-bus-")
    daemon_root = Path(os.path.realpath(daemon_path)).parent.parent
    packaged_session_config = daemon_root / "share" / "dbus-1" / "session.conf"
    session_config = (
        [f"--config-file={packaged_session_config}"] if packaged_session_config.is_file() else ["--session"]
    )
    daemon = subprocess.Popen(
        [
            daemon_path,
            *session_config,
            "--nofork",
            "--nopidfile",
            "--print-address=1",
            f"--address=unix:tmpdir={socket_dir}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    application = None
    try:
        assert daemon.stdout is not None
        readable, _, _ = select.select([daemon.stdout], [], [], 10)
        assert readable, "dbus-daemon did not publish its address"
        address = daemon.stdout.readline().strip()
        assert address
        application = subprocess.Popen(
            [str(executable)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": address},
        )
        assert application.stdout is not None
        readable, _, _ = select.select([application.stdout], [], [], 10)
        assert readable, "tray fixture did not connect to the private bus"
        assert application.stdout.readline().strip() == "READY"

        daemon.terminate()
        daemon.wait(timeout=10)
        assert application.stdin is not None
        application.stdin.write("\n")
        application.stdin.flush()
        _, stderr = application.communicate(timeout=10)
        assert application.returncode == 0, stderr
    finally:
        if application is not None and application.poll() is None:
            application.kill()
            application.wait(timeout=10)
        if daemon.poll() is None:
            daemon.kill()
            daemon.wait(timeout=10)
        shutil.rmtree(socket_dir, ignore_errors=True)
