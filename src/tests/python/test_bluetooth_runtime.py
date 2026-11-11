"""Library.Bluetooth through both frontends.

The runners have no Bluetooth controller, so what runs here is the values and
every refusal; the flake's bluetooth-hid-loopback check boots a VM with two
emulated controllers and runs the loopback program, which is only built here.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "bluetooth"
RUN_TIMEOUT = 60
COMPILE_TIMEOUT = 240
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
SANITIZED = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
PASSED = (
    "PASS: Bluetooth values, and refusals without Bluetooth\n",
    "PASS: Bluetooth values, with Bluetooth present\n",
)


def _require_host() -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux: Library.Bluetooth's BlueZ and L2CAP providers have Linux rows only")


def _build(c_compiler: str, plan: Path, generated: Path, executable: Path, *, sanitized: bool = False) -> None:
    """Build from the link plan, which names libdbus for pkg-config."""
    assert NativePlanReader().read(plan).pkg_config == ("dbus-1",)
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc=c_compiler,
        optimization=1 if sanitized else 2,
        compile_flags=STRICT + (SANITIZED if sanitized else []),
        link_flags=SANITIZED if sanitized else [],
    )


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_bluetooth_values_and_refusals_on_both_frontends(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"bluetooth-{compiler}.c"
    executable = tmp_path / f"bluetooth-{compiler}"
    plan = _transpile(compiler, FIXTURE / "BluetoothConformance.btrc", generated, request)
    _build(c_compiler, plan, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout in PASSED
    assert ran.stderr == ""


def test_loopback_program_builds_and_plans_alike(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Both frontends build the two-controller program and plan it identically."""
    _require_host()
    generated = tmp_path / f"loopback-{compiler}.c"
    plan = _transpile(compiler, FIXTURE / "BluetoothHIDLoopback.btrc", generated, request)
    _build("clang", plan, generated, tmp_path / f"loopback-{compiler}")
    if compiler == "btrc":
        reference = _transpile(
            "python", FIXTURE / "BluetoothHIDLoopback.btrc", tmp_path / "loopback-reference.c", request
        )
        assert plan.read_bytes() == reference.read_bytes()


def test_windows_builds_bluetooth_values_but_no_channels(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Addresses, HIDP and the pairing window are portable; channels and the adapter need a provider."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}

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

    values = tmp_path / "Values.btrc"
    values.write_text(
        "import Library.Bluetooth.BluetoothAddress;\nimport Library.Bluetooth.BluetoothPairing;\n"
        "import Library.Bluetooth.HIDP;\n\n"
        "int main() { return BluetoothAddress.any().isAny() && !BluetoothPairingWindow().isOpen() ? 0 : 1; }\n"
    )
    portable = transpile(values)
    assert portable.returncode == 0, portable.stderr
    for module in ("L2CAP", "BluetoothAdapter", "BluetoothHID", "Bluetooth"):
        source = tmp_path / f"{module}.btrc"
        source.write_text(f"import Library.Bluetooth.{module};\n\nint main() {{ return 0; }}\n")
        refused = transpile(source)
        assert refused.returncode != 0
        assert "provider" in refused.stderr
