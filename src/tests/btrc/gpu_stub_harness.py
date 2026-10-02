"""Build @gpu programs against the stub GPU runtime fixture, without a WebGPU device."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler

REPO = Path(__file__).resolve().parents[3]


CC = configured_c_compiler()


FIXTURES = REPO / "src/tests/btrc/fixtures"


GPU_INCLUDE = REPO / "src/runtime/gpu"


def run_in_repo(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


def compile_with_stub(
    generated: str,
    tmp_path: Path,
    stub: str,
    *defines: str,
    extra_sources: tuple[Path, ...] = (),
    sanitize: bool = False,
) -> Path:
    c_path = tmp_path / "generated.c"
    binary = tmp_path / "generated"
    c_path.write_text(generated)
    effective_sanitize = sanitize and sys.platform != "darwin"
    compiler = (
        shlex.split(
            os.environ.get(
                "BTRC_ASAN_CC",
                "/usr/bin/clang" if sys.platform == "darwin" else CC[0],
            )
        )
        if effective_sanitize
        else CC
    )
    result = run_in_repo(
        [
            *compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(("-fsanitize=address", "-fno-omit-frame-pointer") if effective_sanitize else ()),
            *(f"-D{define}" for define in defines),
            f"-I{GPU_INCLUDE}",
            str(c_path),
            *(str(source) for source in extra_sources),
            str(FIXTURES / stub),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return binary
