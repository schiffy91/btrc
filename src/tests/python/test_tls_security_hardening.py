"""Portable security regression checks for TLS alerts, record overflow, mid-fragment alerts, and RSA bounds."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_tls_security_hardening(tmp_path, request, compiler, sanitized):
    cc = "clang" if sanitized else "cc"
    if not shutil.which(cc):
        pytest.skip(f"{cc} is unavailable")
    for module in (ROOT / "src/stdlib/TLS").glob("*.btrc"):
        shutil.copy(module, tmp_path / module.name)
    source = tmp_path / "SecurityHardening.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated = tmp_path / "Program.c"
    exe = tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    # On macOS, Nix clang ASan runtime hangs at startup; run UBSan locally and full ASan+UBSan on Linux.
    if sanitized:
        flags = (
            ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
            if sys.platform == "linux"
            else ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
        )
    else:
        flags = []
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=exe,
        cc=cc,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
    )
    assert not DependencyAudit().binary_problems(exe, PackageTarget.parse(None).label)
    run = subprocess.run([exe], capture_output=True, text=True, timeout=30, check=True)
    assert run.stdout.strip() == "PASS TLS security hardening" and not run.stderr
