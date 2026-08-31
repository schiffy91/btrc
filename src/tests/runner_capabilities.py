"""Host-capability probes for the shared language-corpus runner."""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

CAPABILITY_DIRECTIVE = "BTRC_TEST_REQUIRES:"
KNOWN_CAPABILITIES = frozenset({"loopback-listener", "native-tray"})

_TRAY_PROBE_MARKER = "BTRC_TRAY_BACKEND_READY"
_TRAY_PROBE_SOURCE = f"""
#include "btrc_tray.h"
#include <stdio.h>

int main(void) {{
    void* tray = btrc_tray_create("btrc capability probe");
    if (tray != NULL) {{ btrc_tray_destroy(tray); }}
    puts("{_TRAY_PROBE_MARKER}");
    return 0;
}}
"""


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


def darwin_gpu_flags() -> tuple[list[str], str | None]:
    """Resolve Homebrew WebGPU/GLFW flags without assuming brew exists."""
    brew = shutil.which("brew")
    if brew is None:
        return [], (
            "WebGPU toolchain is unavailable on macOS: GPU_CFLAGS/GPU_LDFLAGS are unset and Homebrew is not on PATH"
        )
    prefixes: dict[str, str] = {}
    for formula in ("wgpu-native", "glfw"):
        try:
            result = subprocess.run(
                [brew, "--prefix", formula],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return [], f"WebGPU toolchain lookup failed for {formula}: {error}"
        prefix = result.stdout.strip()
        if result.returncode != 0 or not prefix:
            detail = result.stderr.strip() or "formula is not installed"
            return [], f"WebGPU toolchain is unavailable: Homebrew {formula}: {detail[:300]}"
        prefixes[formula] = prefix
    wgpu_prefix = prefixes["wgpu-native"]
    glfw_prefix = prefixes["glfw"]
    return [
        f"-I{wgpu_prefix}/include",
        f"-L{wgpu_prefix}/lib",
        "-lwgpu_native",
        f"-I{glfw_prefix}/include",
        f"-L{glfw_prefix}/lib",
        "-lglfw",
        "-framework",
        "Metal",
        "-framework",
        "QuartzCore",
        "-framework",
        "Cocoa",
        "-framework",
        "IOKit",
        "-framework",
        "CoreVideo",
    ], None


def darwin_app_flags() -> tuple[list[str], str | None]:
    """Resolve Homebrew GLFW flags without probing for WebGPU."""
    brew = shutil.which("brew")
    if brew is None:
        return [], (
            "GLFW toolchain is unavailable on macOS: APP_CFLAGS/APP_LDFLAGS are unset and Homebrew is not on PATH"
        )
    try:
        result = subprocess.run(
            [brew, "--prefix", "glfw"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return [], f"GLFW toolchain lookup failed for glfw: {error}"
    prefix = result.stdout.strip()
    if result.returncode != 0 or not prefix:
        detail = result.stderr.strip() or "formula is not installed"
        return [], f"GLFW toolchain is unavailable: Homebrew glfw: {detail[:300]}"
    return [
        "-DGLFW_INCLUDE_NONE",
        f"-I{prefix}/include",
        f"-L{prefix}/lib",
        "-lglfw",
        "-framework",
        "Cocoa",
        "-framework",
        "IOKit",
        "-framework",
        "CoreVideo",
    ], None


def darwin_tray_backend_error(
    compiler: tuple[str, ...],
    cflags: tuple[str, ...],
    tray_dir: str,
) -> str | None:
    """Probe whether Cocoa tray initialization returns control to a CLI app."""
    with tempfile.TemporaryDirectory(prefix="btrc-tray-probe-") as temporary:
        source_path = Path(temporary, "probe.m")
        binary_path = Path(temporary, "probe")
        source_path.write_text(_TRAY_PROBE_SOURCE)
        command = [
            *compiler,
            *cflags,
            "-fobjc-arc",
            f"-I{tray_dir}",
            str(source_path),
            str(Path(tray_dir, "btrc_tray_macos.m")),
            "-framework",
            "Cocoa",
            "-o",
            str(binary_path),
        ]
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CapabilityProbeBuildError(f"native tray backend probe could not be built: {error}") from error
        if compiled.returncode != 0:
            detail = compiled.stderr.strip() or compiled.stdout.strip() or "compiler failed"
            raise CapabilityProbeBuildError(f"native tray backend probe could not be built: {detail[:300]}")
        try:
            result = subprocess.run([str(binary_path)], capture_output=True, text=True, timeout=10)
        except OSError as error:
            return f"native tray backend probe could not run: {error}"
        except subprocess.TimeoutExpired as error:
            raise CapabilityProbeRuntimeError(f"native tray backend probe timed out: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise CapabilityProbeRuntimeError(f"native tray backend probe failed: {detail[:300]}")
    if _TRAY_PROBE_MARKER not in result.stdout:
        return "native tray backend is unavailable: Cocoa terminated the capability probe during initialization"
    return None
