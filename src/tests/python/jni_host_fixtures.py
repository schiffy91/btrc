"""Desktop consumers explicitly opt in to the JDK-backed JavaHost package."""

import os
import platform
import shutil
import subprocess
import sys

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import REPO, apple_native_target


def require_desktop_jdk():
    if (
        not shutil.which("pkg-config")
        or subprocess.run(["pkg-config", "--exists", "btrc-jni"], check=False, timeout=TOOL_TIMEOUT).returncode
    ):
        pytest.skip("requires the optional JavaHost JDK (nix develop .#jni)")


def desktop_dependency(root):
    path = os.path.relpath(REPO / "src/optional/JavaHost", root)
    return f'[dependencies]\nJavaHost = {{ path = "{path}" }}\n'


def desktop_compiler(cxx=False):
    name = "clang++" if cxx else "clang"
    return f"/usr/bin/{name}" if sys.platform == "darwin" else shutil.which(name)


@pytest.fixture
def desktop_jni_source(tmp_path, monkeypatch):
    if sys.platform == "darwin":
        apple_native_target(monkeypatch)
    elif sys.platform.startswith("linux") and os.environ.get("BTRC_NATIVE_HEADER_READER"):
        architecture = "aarch64" if platform.machine() in ("aarch64", "arm64") else "x86_64"
        monkeypatch.setenv("BTRC_NATIVE_TARGET", f"{architecture}-unknown-linux-gnu")
        monkeypatch.setenv("BTRC_NATIVE_SYSROOT", "/")
    else:
        pytest.skip("requires a Linux or macOS native header reader")
    (tmp_path / "src").mkdir()
    return tmp_path / "src/Main.btrc"
