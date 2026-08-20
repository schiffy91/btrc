#!/usr/bin/env python3
"""Reproducible compile-time + code-size benchmark harness for btrc.

For each program under ``src/tests/benchmarks/*.btrc`` this measures, in-process
(no subprocess, so it is immune to shell/path overhead):

  * per-phase wall time — lex, parse, analyze, ir_gen, optimize, emit;
  * dead-code-elimination effectiveness — IR function count before vs. after the
    optimizer, plus the emitted-C line count;
  * optionally, gcc compile time and stripped binary size (``--cc``).

Run it::

    python3 -m src.tests.bench                 # table to stdout
    python3 -m src.tests.bench --json out.json # machine-readable, for CI deltas
    python3 -m src.tests.bench --cc            # also time gcc + measure binary

The harness is deterministic: it compiles each program ``--repeat`` times
(default 5) and reports the best (minimum) timing per phase, which is the most
stable estimator under a noisy machine. Output size is exact, not sampled.

Why this exists: a trivial program used to emit the *entire* resolved standard
library because dead-function elimination was a flat "referenced anywhere" scan
rather than a reachability walk. The ``funcs_before -> funcs_after`` column makes
that class of regression impossible to merge unnoticed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

BENCH_DIR = os.path.join(os.path.dirname(__file__), "benchmarks")
SOURCE_RESOLVER = FrontendStage().resolver


@dataclasses.dataclass
class Result:
    """One benchmark program's measured outcome (best-of-N for timings)."""

    name: str
    phases_ms: dict[str, float]  # best per-phase milliseconds
    funcs_before: int  # IR functions before optimization
    funcs_after: int  # IR functions after optimization
    helpers_after: int  # runtime helpers after optimization
    c_lines: int  # emitted C line count
    total_ms: float  # best end-to-end milliseconds
    cc_ms: float = 0.0  # gcc compile time (0 if not measured)
    bin_bytes: int = 0  # binary size (0 if not measured)

    @property
    def dce_ratio(self) -> float:
        """Fraction of IR functions removed by dead-function elimination."""
        if self.funcs_before == 0:
            return 0.0
        return 1.0 - self.funcs_after / self.funcs_before


def _compile_once(source: str, filename: str) -> tuple[dict[str, float], dict]:
    """Run the full pipeline once, returning (phase_ms, artifacts).

    artifacts carries the counts/output we report exactly (not best-of-N).
    """
    prof: dict[str, float] = {}

    t = time.perf_counter()
    tokens = Lexer(source, filename).tokenize()
    prof["lex"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    program = Parser(tokens).parse()
    prof["parse"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    analyzed = SemanticAnalyzer().analyze(program)
    prof["analyze"] = (time.perf_counter() - t) * 1000
    if analyzed.errors:
        raise RuntimeError(f"{filename}: analyzer errors: {analyzed.errors[:3]}")

    t = time.perf_counter()
    ir_module = IRLowerer(analyzed).lower()
    prof["ir_gen"] = (time.perf_counter() - t) * 1000
    funcs_before = len(ir_module.function_defs)

    t = time.perf_counter()
    ir_module = IROptimizer(ir_module).optimize()
    prof["optimize"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    c_source = CEmitter().emit(ir_module)
    prof["emit"] = (time.perf_counter() - t) * 1000

    artifacts = {
        "funcs_before": funcs_before,
        "funcs_after": len(ir_module.function_defs),
        "helpers_after": len(ir_module.helper_decls),
        "c_lines": c_source.count("\n") + 1,
        "c_source": c_source,
    }
    return prof, artifacts


def _prepare_source(btrc_path: str) -> tuple[str, str]:
    """Resolve the program's explicit imports exactly as the test runner does."""
    with open(btrc_path) as f:
        source = f.read()
    source = SOURCE_RESOLVER.resolve(source, btrc_path).source
    return source, os.path.basename(btrc_path)


def benchmark(btrc_path: str, repeat: int, cc: str | None) -> Result:
    source, filename = _prepare_source(btrc_path)

    best: dict[str, float] | None = None
    best_total = float("inf")
    artifacts: dict = {}
    for _ in range(repeat):
        t0 = time.perf_counter()
        prof, artifacts = _compile_once(source, filename)
        total = (time.perf_counter() - t0) * 1000
        if best is None:
            best = dict(prof)
        else:
            for k, v in prof.items():
                best[k] = min(best[k], v)
        best_total = min(best_total, total)

    cc_ms = 0.0
    bin_bytes = 0
    if cc:
        cc_ms, bin_bytes = _measure_cc(cc, artifacts["c_source"])

    name = os.path.relpath(btrc_path, BENCH_DIR)
    return Result(
        name=name,
        phases_ms=best or {},
        funcs_before=artifacts["funcs_before"],
        funcs_after=artifacts["funcs_after"],
        helpers_after=artifacts["helpers_after"],
        c_lines=artifacts["c_lines"],
        total_ms=best_total,
        cc_ms=cc_ms,
        bin_bytes=bin_bytes,
    )


def _measure_cc(cc: str, c_source: str) -> tuple[float, int]:
    """Compile emitted C with the given compiler; return (ms, binary bytes)."""
    with tempfile.NamedTemporaryFile(suffix=".c", delete=False, mode="w") as f:
        f.write(c_source)
        c_path = f.name
    bin_path = c_path.removesuffix(".c")
    try:
        flags = [cc, "-std=c11", "-O2", c_path, "-o", bin_path, "-lm"]
        if "pthread.h" in c_source:
            flags.append("-lpthread")
        t = time.perf_counter()
        r = subprocess.run(flags, capture_output=True, text=True, timeout=60)
        cc_ms = (time.perf_counter() - t) * 1000
        if r.returncode != 0:
            print(f"  warning: cc failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            return cc_ms, 0
        return cc_ms, os.path.getsize(bin_path)
    finally:
        for p in (c_path, bin_path):
            if os.path.exists(p):
                os.unlink(p)


def _discover() -> list[str]:
    if not os.path.isdir(BENCH_DIR):
        return []
    return sorted(os.path.join(BENCH_DIR, f) for f in os.listdir(BENCH_DIR) if f.endswith(".btrc"))


_PHASES = ["lex", "parse", "analyze", "ir_gen", "optimize", "emit"]


def _print_table(results: list[Result], show_cc: bool) -> None:
    name_w = max((len(r.name) for r in results), default=4)
    header = f"{'program':<{name_w}}  " + "".join(f"{p:>9}" for p in _PHASES)
    header += f"{'total':>9}  {'funcs':>13}  {'C-lines':>8}"
    if show_cc:
        header += f"{'cc(ms)':>9}{'bin(KB)':>9}"
    print(header)
    print("-" * len(header))
    for r in results:
        row = f"{r.name:<{name_w}}  "
        row += "".join(f"{r.phases_ms.get(p, 0.0):9.2f}" for p in _PHASES)
        funcs = f"{r.funcs_before}->{r.funcs_after}"
        row += f"{r.total_ms:9.2f}  {funcs:>13}  {r.c_lines:8d}"
        if show_cc:
            row += f"{r.cc_ms:9.1f}{r.bin_bytes / 1024:9.1f}"
        print(row)
    print("-" * len(header))
    avg_dce = sum(r.dce_ratio for r in results) / max(len(results), 1)
    print(f"mean dead-function elimination: {avg_dce * 100:.1f}% ({len(results)} programs)")


def main() -> None:
    ap = argparse.ArgumentParser(description="btrc compile-time benchmark")
    ap.add_argument("--repeat", type=int, default=5, help="iterations (best wins)")
    ap.add_argument("--json", help="write machine-readable results to this path")
    ap.add_argument(
        "--cc", nargs="?", const="cc", default=None, help="also compile emitted C with this compiler (default cc)"
    )
    args = ap.parse_args()

    programs = _discover()
    if not programs:
        print(f"no benchmark programs found in {BENCH_DIR}", file=sys.stderr)
        sys.exit(1)

    results = [benchmark(p, args.repeat, args.cc) for p in programs]
    _print_table(results, show_cc=bool(args.cc))

    if args.json:
        with open(args.json, "w") as f:
            json.dump([dataclasses.asdict(r) for r in results], f, indent=2)
            f.write("\n")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
