"""Real runtime contention with independent foreground/background objects.

The fixture prints batch timings for profiling; correctness checks do not depend
on a wall-clock threshold or scheduler fairness on a busy test host.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

FIXTURE = Path(__file__).with_name("fixtures") / "arc_contention.c"
COMPILERS = tuple(path for name in ("clang", "gcc") if (path := shutil.which(name)))


@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda value: Path(value).name)
@pytest.mark.parametrize("portable", (False, True), ids=("native", "portable"))
def test_foreground_and_background_arc_complete(tmp_path: Path, c_compiler: str, portable: bool) -> None:
    definitions = RuntimeHelperCatalog().definitions_for({"__btrc_arc_retain", "__btrc_arc_release_acyclic"})
    runtime = "\n\n".join(helper.c_source for helper in definitions)
    if portable:
        # Compile the production fallback too, without pretending to run Linux.
        runtime = runtime.replace("#if defined(__APPLE__)", "#if 0")
    source = tmp_path / "contention.c"
    source.write_text(FIXTURE.read_text().replace("/* BTRC_RUNTIME_HELPERS */", runtime))
    binary = tmp_path / "contention"
    built = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert built.returncode == 0, built.stderr
    for workers in (0, 2):
        run = subprocess.run([str(binary), str(workers)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr
        rows = [line.split(",") for line in run.stdout.splitlines()]
        samples = sorted(float(row[2]) for row in rows if row[0] == "batch")
        assert len(samples) == 200
        print(
            f"{Path(c_compiler).name} portable={portable} workers={workers}: p50={samples[99]:.3f} p95={samples[189]:.3f} max={samples[-1]:.3f} ms; {rows[-1]}"
        )
