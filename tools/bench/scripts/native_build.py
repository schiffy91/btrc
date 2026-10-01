"""Compile a module-unit build's C units to objects, eight at a time, the way the native plan does.

    native_build.py <outdir> [--prelude <btrc-tree>] [extra clang flags...]

<outdir> is gen_units.sh's: the primary out/p.c plus every emitted unit its
out/p.json names, compiled with the product's strict C11 -O0 -g command and the
packages' pkg-config flags. --prelude applies that tree's precompiled preludes
exactly as its native builder does. Run it under /usr/bin/time -l for the
total CPU; the plan reference cites it as the native compile CPU measurement.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main() -> int:
    out = Path(sys.argv[1]) / "out"
    extra = sys.argv[2:]
    prelude_repo = None
    if "--prelude" in extra:
        at = extra.index("--prelude")
        prelude_repo = extra[at + 1]
        del extra[at : at + 2]
    plan = json.loads((out / "p.json").read_text())
    packages = sorted({package["name"] for package in plan["pkg-config"]})
    cflags = shlex.split(subprocess.run(["pkg-config", "--cflags", *packages], capture_output=True, text=True).stdout)
    units = [out / "p.c", *map(Path, plan["emitted-units"])]
    objects = out.parent / "objects"
    shutil.rmtree(objects, ignore_errors=True)
    objects.mkdir()
    base = [
        "clang",
        "-x",
        "c",
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-g",
        *cflags,
        "-O0",
        *extra,
    ]
    started = time.perf_counter()
    preludes: dict[Path, list[str]] = {}
    if prelude_repo:
        sys.path.insert(0, prelude_repo)
        from tools.native_plan import _PreludeAccelerator

        commands = [([*base, "-c", str(source), "-o", str(objects / (source.stem + ".o"))], source) for source in units]
        accelerator = _PreludeAccelerator(subprocess.run, objects)
        preludes = accelerator.arguments(commands, 8)
        print(f"prelude status={accelerator.status} served={len(preludes)} build={accelerator.seconds:.2f}s")

    def compile_unit(source: Path) -> tuple[float, Path, int, str]:
        unit_started = time.perf_counter()
        completed = subprocess.run(
            [*base, *preludes.get(source, []), "-c", str(source), "-o", str(objects / (source.stem + ".o"))],
            capture_output=True,
            text=True,
        )
        return time.perf_counter() - unit_started, source, completed.returncode, completed.stderr[:400]

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(compile_unit, sorted(units, key=lambda source: -source.stat().st_size)))
    wall = time.perf_counter() - started
    failures = [result for result in results if result[2]]
    lines = sum(source.read_text(errors="replace").count("\n") for source in units)
    print(f"units={len(units)} lines={lines:,} wall={wall:.2f}s fails={len(failures)}")
    for failure in failures[:3]:
        print("   FAIL", failure[1].name, failure[3])
    slowest = sorted(results, key=lambda result: -result[0])[:3]
    print("   slowest:", ", ".join(f"{result[1].name} {result[0]:.1f}s" for result in slowest))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
