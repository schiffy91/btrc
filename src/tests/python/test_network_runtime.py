"""Library.Network over real loopback sockets, through both frontends."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]
CONFORMANCE = ROOT / "src" / "tests" / "native" / "network" / "NetworkConformance.btrc"
PASSED = "PASS: network listener, streams, deadlines, resolver and bulk transfer\n"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 60

PLANNED_CONSUMER = """\
import Library.Network;

int main() {
    TCPListener listener = TCPListener.listen(IPv4Address.loopback(), 0);
    TCPStream client = TCPStream.connect(IPv4Address.loopback(), listener.port(), 2000);
    if (listener.accept(2000) == null || !client.setNoDelay(true)) { return 2; }
    print("PASS: planned network runtime");
    return 0;
}
"""


def _require_host() -> None:
    if sys.platform not in ("linux", "darwin"):
        pytest.skip("Library.Network has providers for Linux and macOS only")


def _transpile(frontend: str, source: Path, output: Path, request: pytest.FixtureRequest) -> Path:
    target = PackageTarget.parse(None)
    target_text = f"{target.operating_system}-{target.architecture}"
    plan = output.with_suffix(".json")
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(output.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(source),
            "--strict-imports",
            "--target",
            target_text,
            "--emit-link-plan",
            str(plan),
            "--no-cache",
            "-o",
            str(output),
        ]
        result = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(btrcc), "--strict-imports", "--target", target_text, "--emit-link-plan", str(plan), str(source)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr
    assert result.stderr == "", result.stderr
    return plan


def _compile(c_compiler: str, generated: Path, executable: Path, *, sanitized: bool = False) -> None:
    environment = dict(os.environ)
    plan = NativePlanReader().read(generated.with_suffix(".json"))
    assert plan.units == ()
    definitions = [f"-D{name}={value}" if value else f"-D{name}" for name, value in plan.defines]
    sanitizer_flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    sdk_flags = []
    if sanitized and sys.platform == "darwin":
        environment.pop("DEVELOPER_DIR", None)
        environment.pop("SDKROOT", None)
        sdk_flags = ["-isysroot", environment["BTRC_NATIVE_SYSROOT"], "-target", environment["BTRC_NATIVE_TARGET"]]
    result = subprocess.run(
        [
            c_compiler,
            *definitions,
            *sanitizer_flags,
            *sdk_flags,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            str(generated),
            "-o",
            str(executable),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_network_streams_over_loopback_on_both_frontends(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    if sanitized and sys.platform == "darwin":
        c_compiler = "/usr/bin/clang"
    generated = tmp_path / f"network-{compiler}.c"
    executable = tmp_path / f"network-{compiler}"
    _transpile(compiler, CONFORMANCE, generated, request)
    _compile(c_compiler, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == PASSED
    assert ran.stderr == ""


def test_import_plans_and_links_the_network_group(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    _require_host()
    project = tmp_path / "project"
    project.mkdir()
    source = project / "Main.btrc"
    source.write_text(PLANNED_CONSUMER)
    (project / "btrc.toml").write_text('manifest-version = 1\n\n[package]\nname = "planned_network"\n')
    generated = tmp_path / f"planned-{compiler}.c"
    plan = _transpile(compiler, source, generated, request)
    if compiler == "btrc":
        reference = tmp_path / "planned-reference.c"
        reference_plan = _transpile("python", source, reference, request)
        assert plan.read_bytes() == reference_plan.read_bytes()
    executable = tmp_path / f"planned-{compiler}"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: planned network runtime\n"
    assert ran.stderr == ""


def test_windows_has_no_network_provider_yet(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """The socket modules name no Windows row; the address values build there."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}
    sockets = tmp_path / "Sockets.btrc"
    sockets.write_text("import Library.Network.TCPListener;\n\nint main() { return 0; }\n")
    addresses = tmp_path / "Addresses.btrc"
    addresses.write_text(
        "import Library.Network.IPv4Address;\n\nint main() { return IPv4Address.loopback().isLoopback() ? 0 : 1; }\n"
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

    refused = transpile(sockets)
    assert refused.returncode != 0
    assert "provider" in refused.stderr
    portable = transpile(addresses)
    assert portable.returncode == 0, portable.stderr
