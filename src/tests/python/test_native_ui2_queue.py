"""Private UI2 semantic owner executes through both compilers and native C11."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_ui2_semantic_queue(tmp_path, request, frontend, sanitized):
    root = Path(__file__).resolve().parents[3]
    data = request.getfixturevalue("gui_provider_root")
    source = root / "src/tests/native/gui/ui2/ControlEventQueue.btrc"
    generated = tmp_path / "Queue.c"
    environment = os.environ | {"BTRC_HOME": str(data)}
    if frontend == "python":
        command = [sys.executable, "-m", "src.tests.gui_provider_root", str(data), "--no-cache", str(source), "-o", str(generated)]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), str(source)]
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    if frontend == "selfhost":
        generated.write_text(result.stdout)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"] if sanitized else []
    executable = tmp_path / "Queue"
    compile_result = subprocess.run(
        [os.environ.get("BTRC_NATIVE_PROVIDER_CC", "cc"), "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O1", "-pthread", *flags, str(generated), "-lm", "-o", str(executable)],
        cwd=root, env=environment, capture_output=True, text=True, timeout=180,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: UI2 semantic order reservations cancellation and eligibility" in result.stdout
