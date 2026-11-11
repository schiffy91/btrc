"""Library.USB with an emulated device, through both frontends.

The emulated device is exported over USB/IP and driven by a user-space host
through a socket pair. The kernel-host program needs vhci_hcd and root, so it
is only built here; the flake's usb-kernel-host check runs it in a VM.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_network_runtime import _compile, _transpile

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "usb"
RUN_TIMEOUT = 60
COMPILE_TIMEOUT = 240


def _require_host() -> None:
    if sys.platform not in ("linux", "darwin"):
        pytest.skip("Library.USB carries transfers over Library.Network, which has Linux and macOS rows only")


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_emulated_usb_device_over_usbip_on_both_frontends(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    if sanitized and sys.platform == "darwin":
        c_compiler = "/usr/bin/clang"
    generated = tmp_path / f"usb-{compiler}.c"
    executable = tmp_path / f"usb-{compiler}"
    _transpile(compiler, FIXTURE / "USBEmulatedDevice.btrc", generated, request)
    _compile(c_compiler, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: emulated USB device over USB/IP\n"
    assert ran.stderr == ""


def test_kernel_host_program_builds_and_plans_alike(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Both frontends build the vhci_hcd and usbfs program and plan it identically."""
    _require_host()
    generated = tmp_path / f"kernel-host-{compiler}.c"
    plan = _transpile(compiler, FIXTURE / "USBKernelHost.btrc", generated, request)
    _compile("clang", generated, tmp_path / f"kernel-host-{compiler}")
    if compiler == "btrc":
        reference_plan = _transpile(
            "python", FIXTURE / "USBKernelHost.btrc", tmp_path / "kernel-host-reference.c", request
        )
        assert plan.read_bytes() == reference_plan.read_bytes()


def test_windows_builds_usb_values_but_no_transport(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Descriptors and emulated devices are portable; USB/IP and the host need a provider."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}
    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.USB.USBDescriptors;\nimport Library.USB.USBVirtualDevice;\n\n"
        "int main() { return USBSetup(0x80, 6, 0x0100, 0, 18).deviceToHost() ? 0 : 1; }\n"
    )

    def transpile(source: Path) -> subprocess.CompletedProcess[str]:
        if compiler == "python":
            command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
            command += ["--target", "windows-x86_64", "--no-cache", "-o", str(source.with_suffix(".c"))]
        else:
            btrcc = request.getfixturevalue("immutable_btrcc")
            command = [str(btrcc), "--strict-imports", "--target", "windows-x86_64", str(source)]
        return subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )

    portable = transpile(values)
    assert portable.returncode == 0, portable.stderr
    for module in ("USBIP", "USBHost"):
        source = tmp_path / f"{module}.btrc"
        source.write_text(f"import Library.USB.{module};\n\nint main() {{ return 0; }}\n")
        refused = transpile(source)
        assert refused.returncode != 0
        assert "provider" in refused.stderr
