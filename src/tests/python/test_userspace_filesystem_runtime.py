"""Library.FileSystem.Userspace, through both frontends.

Mounting a filesystem needs root, so the program that serves the in-memory,
forwarding and held-answer filesystems is only built here; the flake's
userspace-filesystem check runs it in a VM. What can run anywhere does: a
mount without privilege is refused with a reason, and a target without the
kernel protocol refuses the import.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from src.tests.python.test_network_runtime import _compile, _transpile

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "userspace"
RUN_TIMEOUT = 60
COMPILE_TIMEOUT = 240


def _require_linux() -> None:
    if sys.platform != "linux":
        pytest.skip("requires Linux: Library.FileSystem.Userspace speaks the Linux kernel's FUSE protocol")


def test_mount_program_builds_and_plans_alike(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Both frontends build the three filesystems and plan the program identically."""
    _require_linux()
    generated = tmp_path / f"mounts-{compiler}.c"
    plan = _transpile(compiler, FIXTURE / "UserspaceMounts.btrc", generated, request)
    _compile("clang", generated, tmp_path / f"mounts-{compiler}")
    if compiler == "btrc":
        reference_plan = _transpile(
            "python", FIXTURE / "UserspaceMounts.btrc", tmp_path / "mounts-reference.c", request
        )
        assert plan.read_bytes() == reference_plan.read_bytes()


def test_a_mount_without_privilege_is_refused_with_a_reason(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """Without the right to mount, mounting throws why and leaves nothing behind."""
    _require_linux()
    generated = tmp_path / f"refused-{compiler}.c"
    _transpile(compiler, FIXTURE / "UserspaceMounts.btrc", generated, request)
    _compile("clang", generated, tmp_path / f"refused-{compiler}")
    # A suite run as root could mount, so the program runs as nobody there,
    # from a place nobody can reach.
    unprivileged = {"user": 65534, "group": 65534, "extra_groups": []} if os.geteuid() == 0 else {}
    with tempfile.TemporaryDirectory() as shared:
        os.chmod(shared, 0o755)
        executable = Path(shared) / "userspace-mounts"
        shutil.copy(tmp_path / f"refused-{compiler}", executable)
        executable.chmod(0o755)
        directory = Path(shared) / "mounted"
        directory.mkdir()
        ran = subprocess.run(
            [str(executable), "memory", str(directory)],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            **unprivileged,
        )
        assert ran.returncode == 1, ran.stdout
        assert ran.stdout.startswith(("FAIL: Cannot mount a filesystem at ", "FAIL: Cannot open /dev/fuse: ")), (
            ran.stdout
        )
        assert ran.stderr == ""
        assert list(directory.iterdir()) == []
        assert str(directory) not in Path("/proc/mounts").read_text()


def test_windows_has_no_userspace_filesystems(compiler: str, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """The module has a Linux provider only; another target refuses the import."""
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache"), "BTRC_HOME": str(ROOT / "src")}
    source = tmp_path / "Mount.btrc"
    source.write_text("import Library.FileSystem.Userspace;\n\nint main() { return Userspace.supported() ? 0 : 1; }\n")
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main", str(source), "--strict-imports"]
        command += ["--target", "windows-x86_64", "--no-cache", "-o", str(source.with_suffix(".c"))]
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [str(btrcc), "--strict-imports", "--target", "windows-x86_64", str(source)]
    refused = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
    )
    assert refused.returncode != 0
    assert "provider" in refused.stderr
