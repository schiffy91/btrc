"""Host- and target-capability probes for the test suites.

A corpus source declares what it needs with ``BTRC_TEST_REQUIRES:``. Host
capabilities are probed. Target capabilities name an executor's facilities --
a simulator, an emulator, a display server, an audio loopback, a physical
device -- and are absent until the runner grants them through
``BTRC_TEST_CAPABILITIES`` and their host precondition holds, so a test that
needs one skips with a reason naming that variable. Every probe records its
verdict in `CapabilityGateLog`, which the skip ledger reports.
"""

from __future__ import annotations

import functools
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import TOOL_TIMEOUT

CAPABILITY_DIRECTIVE = "BTRC_TEST_REQUIRES:"
HOST_CAPABILITIES = frozenset({"loopback-listener"})
TARGET_CAPABILITIES = frozenset(
    {
        "android-emulator",
        "audio-loopback",
        "ios-simulator",
        "physical-device",
        "wayland",
        "windows-native",
        "x11",
    }
)
KNOWN_CAPABILITIES = HOST_CAPABILITIES | TARGET_CAPABILITIES
GRANTED_CAPABILITIES_VARIABLE = "BTRC_TEST_CAPABILITIES"


class CapabilityGateLog:
    """Every capability verdict reached in this process, until the skip ledger drains it."""

    _pending: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def record(cls, capability: str, error: str | None) -> str | None:
        """Note one verdict against the running test, and return `error` unchanged."""

        current = os.environ.get("PYTEST_CURRENT_TEST", "")
        cls._pending.append(
            {
                "capability": capability,
                "available": error is None,
                "reason": error,
                "nodeid": current.rsplit(" (", 1)[0] if current else None,
            }
        )
        return error

    @classmethod
    def drain(cls) -> list[dict[str, Any]]:
        drained = list(cls._pending)
        cls._pending.clear()
        return drained

    @classmethod
    def gate[**P, R](cls, capability: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Record a probe's verdict: its result is an error string, or a (value, error) pair."""

        def decorate(probe: Callable[P, R]) -> Callable[P, R]:
            @functools.wraps(probe)
            def evaluate(*args: P.args, **kwargs: P.kwargs) -> R:
                result = probe(*args, **kwargs)
                cls.record(capability, result[1] if isinstance(result, tuple) else result)
                return result

            return evaluate

        return decorate


class TargetCapabilities:
    """Executor facilities a test may require; each is absent until a runner grants it."""

    def __init__(self, environ: Mapping[str, str] | None = None, host: str | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self.host = sys.platform if host is None else host

    def granted(self) -> frozenset[str]:
        raw = self.environ.get(GRANTED_CAPABILITIES_VARIABLE, "")
        return frozenset(name.strip() for name in raw.split(",") if name.strip())

    def error(self, capability: str) -> str | None:
        """Return why `capability` is unavailable to this runner, or None."""

        if capability not in TARGET_CAPABILITIES:
            raise ValueError(f"unknown target capability: {capability}")
        if capability not in self.granted():
            return (
                f"{capability} is not granted to this runner: an executor that provides it "
                f"sets {GRANTED_CAPABILITIES_VARIABLE}={capability}"
            )
        if problem := self.precondition_error(capability):
            return f"{capability} is granted but unavailable: {problem}"
        return None

    def precondition_error(self, capability: str) -> str | None:
        """The host-side fact a granted capability still depends on."""

        if capability == "windows-native" and self.host not in {"win32", "cygwin"}:
            return "the host is not Windows"
        if capability == "ios-simulator" and self.host != "darwin":
            return "iOS simulators run only on a macOS host"
        if capability == "wayland" and not self.environ.get("WAYLAND_DISPLAY"):
            return "WAYLAND_DISPLAY is unset"
        if capability == "x11" and not self.environ.get("DISPLAY"):
            return "DISPLAY is unset"
        return None


def target_capability_error(capability: str) -> str | None:
    """Return why a target capability is absent for this process, recording the verdict."""
    return CapabilityGateLog.record(capability, TargetCapabilities().error(capability))


class PkgConfig:
    """Bounded pkg-config queries that report a missing tool as an absent package."""

    @staticmethod
    def flags(package: str) -> tuple[list[str], str | None]:
        """Compile and link flags for `package`, or why they are unavailable."""
        tool = shutil.which("pkg-config")
        if tool is None:
            return [], "pkg-config is not installed"
        try:
            result = subprocess.run(
                [tool, "--cflags", "--libs", package], capture_output=True, text=True, timeout=TOOL_TIMEOUT
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return [], f"pkg-config failed for {package}: {error}"
        if result.returncode != 0:
            return [], f"pkg-config cannot find {package}"
        return shlex.split(result.stdout), None

    @classmethod
    def missing(cls, package: str) -> str | None:
        """Why `package` is unavailable through pkg-config, or None."""
        return cls.flags(package)[1]


class CapabilityProbeBuildError(RuntimeError):
    """A capability probe could not be built, so the test infrastructure failed."""


class CapabilityProbeRuntimeError(RuntimeError):
    """A built capability probe failed in a way that does not prove absence."""


def declared_capabilities(source_path: str | Path) -> frozenset[str]:
    """Read explicit host requirements declared by a corpus source."""
    required: set[str] = set()
    with open(source_path) as source:
        for line in source:
            _, marker, values = line.partition(CAPABILITY_DIRECTIVE)
            if not marker:
                continue
            required.update(value.strip() for value in values.split(",") if value.strip())
    unknown = required - KNOWN_CAPABILITIES
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown corpus capability in {source_path}: {names}")
    return frozenset(required)


@CapabilityGateLog.gate("loopback-listener")
def loopback_listener_error() -> str | None:
    """Return why an ephemeral IPv4 loopback listener cannot be created."""
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        return _socket_error("socket creation", error)
    with listener:
        try:
            listener.bind(("127.0.0.1", 0))
        except OSError as error:
            return _socket_error("bind", error)
        try:
            listener.listen(1)
        except OSError as error:
            return _socket_error("listen", error)
    return None


def _socket_error(operation: str, error: OSError) -> str:
    detail = error.strerror or str(error)
    errno = f" (errno {error.errno})" if error.errno is not None else ""
    return f"IPv4 loopback listeners are unavailable: {operation} failed: {detail}{errno}"


@CapabilityGateLog.gate("webgpu-toolchain")
def darwin_gpu_flags() -> tuple[list[str], str | None]:
    """Resolve Homebrew compute-only WebGPU flags without assuming brew exists."""
    brew = shutil.which("brew")
    if brew is None:
        return [], (
            "WebGPU toolchain is unavailable on macOS: GPU_CFLAGS/GPU_LDFLAGS are unset and Homebrew is not on PATH"
        )
    try:
        result = subprocess.run(
            [brew, "--prefix", "wgpu-native"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return [], f"WebGPU toolchain lookup failed for wgpu-native: {error}"
    prefix = result.stdout.strip()
    if result.returncode != 0 or not prefix:
        detail = result.stderr.strip() or "formula is not installed"
        return [], f"WebGPU toolchain is unavailable: Homebrew wgpu-native: {detail[:300]}"
    return [
        f"-I{prefix}/include",
        f"-L{prefix}/lib",
        "-lwgpu_native",
        "-lpthread",
        "-framework",
        "Metal",
        "-framework",
        "QuartzCore",
        "-framework",
        "Foundation",
    ], None


_TRAY_WATCHER_NAME = "org.kde.StatusNotifierWatcher"


@CapabilityGateLog.gate("native-tray")
def linux_tray_backend_error() -> str | None:
    """Return why a StatusNotifierItem cannot be hosted on this session bus."""
    if error := PkgConfig.missing("dbus-1"):
        return f"native tray backend is unavailable: {error}"
    dbus_send = shutil.which("dbus-send")
    if dbus_send is None:
        return "native tray backend is unavailable: dbus-send is not installed"
    command = [
        dbus_send,
        "--session",
        "--print-reply",
        "--dest=org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus.NameHasOwner",
        f"string:{_TRAY_WATCHER_NAME}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"native tray backend is unavailable: {error}"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        return f"native tray backend is unavailable: no session bus ({detail[:200]})"
    if "boolean true" not in result.stdout:
        return f"native tray backend is unavailable: {_TRAY_WATCHER_NAME} is not on the session bus"
    return None


@CapabilityGateLog.gate("native-display")
def linux_display_error() -> str | None:
    """Return why a Wayland or X11 window cannot be opened from this session."""
    if error := PkgConfig.missing("sdl3"):
        return f"native GUI backend is unavailable: {error}"
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "native GUI backend is unavailable: no WAYLAND_DISPLAY or DISPLAY"
    return None


@CapabilityGateLog.gate("native-display-wayland")
def linux_wayland_display_error() -> str | None:
    """Return why a Wayland window cannot be opened from this session, such as
    `tools/ui/headless-session.sh --wayland` provides."""
    if error := PkgConfig.missing("sdl3"):
        return f"native Wayland backend is unavailable: {error}"
    display = os.environ.get("WAYLAND_DISPLAY")
    if not display:
        return "native Wayland backend is unavailable: no WAYLAND_DISPLAY"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not os.path.isabs(display) and not runtime:
        return "native Wayland backend is unavailable: XDG_RUNTIME_DIR is unset"
    socket_path = Path(runtime or "", display)
    if not socket_path.is_socket():
        return f"native Wayland backend is unavailable: no compositor listens at {socket_path}"
    return None


@CapabilityGateLog.gate("native-atspi")
def linux_atspi_error() -> str | None:
    """Return why this session has no AT-SPI accessibility bus to publish or read a tree on."""
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        # Without an address, libdbus may autolaunch a stray bus on the display.
        return "AT-SPI is unavailable: no session bus (DBUS_SESSION_BUS_ADDRESS is unset)"
    dbus_send = shutil.which("dbus-send")
    if dbus_send is None:
        return "AT-SPI is unavailable: dbus-send is not installed"
    command = [
        dbus_send,
        "--session",
        "--print-reply",
        "--dest=org.a11y.Bus",
        "/org/a11y/bus",
        "org.a11y.Bus.GetAddress",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"AT-SPI is unavailable: {error}"
    if result.returncode != 0 or '"unix:' not in result.stdout:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        return f"AT-SPI is unavailable: no accessibility bus on the session bus ({detail[:200]})"
    # The launcher caches its address, so a socket another session deleted is still advertised.
    address = result.stdout.split('"unix:', 1)[1].split('"', 1)[0]
    for part in address.split(","):
        key, _, value = part.partition("=")
        if key == "path" and not Path(value).is_socket():
            return f"AT-SPI is unavailable: the accessibility bus socket {value} is gone"
    return None


@CapabilityGateLog.gate("native-audio")
def linux_audio_backend_error() -> str | None:
    """Return why no ALSA PCM can be opened from this session."""
    if os.environ.get("BTRC_SKIP_AUDIO_TESTS"):
        return "native audio backend tests are disabled by BTRC_SKIP_AUDIO_TESTS"
    flags, error = PkgConfig.flags("alsa")
    if error:
        return f"native audio backend is unavailable: {error}"
    with tempfile.TemporaryDirectory(prefix="btrc-alsa-probe-") as temporary:
        source = Path(temporary, "probe.c")
        binary = Path(temporary, "probe")
        source.write_text(
            "#include <alsa/asoundlib.h>\n#include <stdio.h>\n"
            "int main(void) {\n"
            "    snd_pcm_t *pcm = NULL;\n"
            '    int status = snd_pcm_open(&pcm, "default", SND_PCM_STREAM_PLAYBACK, SND_PCM_NONBLOCK);\n'
            '    if (status < 0) { fprintf(stderr, "%s\\n", snd_strerror(status)); return 77; }\n'
            "    return snd_pcm_close(pcm) < 0 ? 1 : 0;\n"
            "}\n"
        )
        try:
            compiled = subprocess.run(
                [*configured_c_compiler(), str(source), "-o", str(binary), *flags],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CapabilityProbeBuildError(f"ALSA probe could not be built: {error}") from error
        if compiled.returncode != 0:
            raise CapabilityProbeBuildError(f"ALSA probe could not be built: {compiled.stderr[:300]}")
        try:
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CapabilityProbeRuntimeError(f"ALSA probe could not run: {error}") from error
    if result.returncode == 77:
        return f"native audio backend is unavailable: cannot open default ALSA PCM ({result.stderr.strip()[-300:]})"
    if result.returncode != 0:
        raise CapabilityProbeRuntimeError(f"ALSA probe failed with status {result.returncode}: {result.stderr[:300]}")
    return None
