"""Instructions retired for one private-body edit compile, by default at --jobs 1.

Run it inside bsm_env.sh::

    edit_instr.py <btrcc> <tag> [--prime] [--sample] [--fixtures audio-preparation,navigation,ui-controller]
                  [--value N] [--repeat N] [--jobs N]

Each fixture edit starts from the same primed artifact-cache snapshot, so two
binaries compare on equal work; budget_bench's edit scenarios time the same
fixtures end to end (tools.budget_bench.EDIT_FIXTURES is their one definition).
--sample attaches macOS `sample` for 60 s to the compile; the sample_*.py
scripts read those call graphs.

    BTRC_REPO        the tree whose stdlib the binary is paired with (default: this repository)
    BSM_WORKSPACE    the BTRSmith copy, copied once per tag (default ~/.cache/btrc/bsm-measure)
    BTRC_BENCH_HOME  measurement root; evidence goes to <root>/perf/ei-<tag> (default ~/.cache/btrc)
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.budget_bench import EDIT_FIXTURES, ENTRY, HostTarget

CACHE = Path(os.environ.get("BTRC_BENCH_HOME", Path.home() / ".cache/btrc"))
WORKSPACE = Path(os.environ.get("BSM_WORKSPACE", CACHE / "bsm-measure"))
REPO = Path(os.environ.get("BTRC_REPO", ROOT))
FIXTURES = {fixture.name: fixture for fixture in EDIT_FIXTURES}
ALIASES = {"audio": "audio-preparation", "ui": "ui-controller"}


def compile_once(
    btrcc: Path, work: Path, cache: Path, jobs: int | None, *, measure: bool = False, sample: Path | None = None
) -> tuple[float, str]:
    command = [
        str(btrcc),
        *(["--jobs", str(jobs)] if jobs else []),
        "--strict-imports",
        "--target",
        HostTarget.resolve(None),
        "--debug",
        "--emit-link-plan",
        str(work / "out/p.json"),
        "--emit-units",
        str(work / "out/p"),
        "--module-units",
        ENTRY,
        "-o",
        str(work / "out/p.c"),
    ]
    if measure:
        command = ["/usr/bin/time", "-l", *command]
    environment = {**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(cache), "BTRC_TIMING": "1"}
    started = time.perf_counter()
    process = subprocess.Popen(
        command, cwd=work / "ws", env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    sampler = None
    if sample is not None:
        time.sleep(0.15)
        pid = process.pid
        if measure:
            children = subprocess.run(
                ["pgrep", "-P", str(process.pid)], capture_output=True, text=True, timeout=60
            ).stdout.split()
            pid = int(children[0]) if children else process.pid
        sampler = subprocess.Popen(
            ["sample", str(pid), "60", "1", "-file", str(sample)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    _, error = process.communicate()
    elapsed = time.perf_counter() - started
    if sampler is not None:
        sampler.wait()
    if process.returncode != 0:
        sys.exit(f"btrcc failed:\n{error[-3000:]}")
    return elapsed, error


def phases(stderr: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for line in stderr.splitlines():
        if line.startswith("btrcc") and "timing:" in line:
            for name, value in re.findall(r"(\S+?)=(\d+)us", line):
                totals[name] = totals.get(name, 0) + int(value)
    return totals


def clone(source: Path, destination: Path) -> None:
    shutil.rmtree(destination, ignore_errors=True)
    subprocess.run(["/bin/cp", "-c", "-R", str(source), str(destination)], check=True, timeout=600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("btrcc")
    parser.add_argument("tag")
    parser.add_argument("--prime", action="store_true", help="recopy the workspace and rebuild the primed cache")
    parser.add_argument("--sample", action="store_true")
    parser.add_argument("--fixtures", default="audio-preparation,navigation,ui-controller")
    parser.add_argument("--value", type=int, default=4321, help="the edit revision; equal values compare equal work")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1, help="0 = btrcc's default workers")
    options = parser.parse_args()
    btrcc = Path(options.btrcc).resolve()
    work = CACHE / "perf" / f"ei-{options.tag}"
    snapshot, cache = work / "cache.snap", work / "cache"
    if options.prime or not cache.exists():
        shutil.rmtree(work, ignore_errors=True)
        (work / "out").mkdir(parents=True)
        shutil.copytree(WORKSPACE, work / "ws", symlinks=True)
        for index in range(2):
            elapsed, _ = compile_once(btrcc, work, cache, None)
            print(f"prime {index} {elapsed:.2f}s", flush=True)
    if not snapshot.exists():
        clone(cache, snapshot)
    for requested in options.fixtures.split(","):
        fixture = FIXTURES[ALIASES.get(requested, requested)]
        source = work / "ws" / fixture.module
        pristine = (WORKSPACE / fixture.module).read_text()
        for repeat in range(options.repeat):
            clone(snapshot, cache)
            source.write_text(pristine.replace(fixture.original, fixture.render(options.value + repeat), 1))
            sample = work / f"{fixture.name}-{repeat}.sample.txt" if options.sample else None
            elapsed, error = compile_once(btrcc, work, cache, options.jobs or None, measure=True, sample=sample)
            instructions = re.search(r"(\d+)\s+instructions retired", error)
            peak = re.search(r"(\d+)\s+peak memory footprint", error)
            totals = phases(error)
            top = " ".join(
                f"{name}={value / 1e6:.2f}" for name, value in sorted(totals.items(), key=lambda item: -item[1])[:14]
            )
            print(
                f"{options.tag} jobs={options.jobs} {fixture.name} wall={elapsed:.2f}s "
                f"instr={int(instructions.group(1)) / 1e9 if instructions else float('nan'):.2f}G "
                f"peak={int(peak.group(1)) / 2**30 if peak else float('nan'):.2f}GiB "
                f"nb={totals.get('n-bindings', 0) / 1e6:.2f}",
                flush=True,
            )
            print(f"   {top}", flush=True)
            (work / f"{fixture.name}-{repeat}.timing").write_text(error)
        source.write_text(pristine)


if __name__ == "__main__":
    main()
