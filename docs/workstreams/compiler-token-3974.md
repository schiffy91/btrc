# Token lifetime on the current combined tree

## Claim and status

D29 integrator assignment, 2026-10-08. Branch `codex/compiler-token-3974`
starts at exact combined baseline
`3974d47bc87851b1ac19b8d2b4bd5022f2d94676`. Own only
`src/compiler/btrc/pipeline/Pipeline.btrc`, this report and the corresponding
WORKSTREAMS claim row. Preserve previous token-current `fb6145b9`, tuple
fixtures `67950115`, and original token evidence branch `d6309c7c` unchanged.
The existing http-contract clone is reused; harmonize remains frozen.

Reapply only the independently reviewed Pipeline lexical-scope change from
`01c172754a30c5debce9fc4e822eaed125988a3c` / original `69ca0f17`.
No Python compiler, runtime, cache-key, generated source, benchmark threshold,
quiet admission or product-pin changes. Current source preparation is not
current correctness qualification or evidence of a performance improvement.

The BTRSmith lane owns execution. No builds, compiler invocations, tests or
measurements are authorized for this packet until the integrator allocates a
lane. The next evidence must name exact baseline/candidate source and binary
hashes; earlier 56d/69ca binaries are not source-exact combined3974 builds.

## Exact source delta

Production checkpoint: `2ffcbeba6325bc69f93d2eaf1cd9da60092bc1b1`.
The only production delta from combined3974 is the original Pipeline hunk:
16 lines added, 11 removed. The full diff is byte-identical to the patch from
01c17275, and the resulting Pipeline Git blob is
`29e905f4d0b945bd5a27759e1e904add25c6a264`, identical to original69ca.
Baseline Pipeline SHA256:
`60694619faa0c197c2966ed19e2825ef59cfb25b10f7723ddda6c7f8aebce272`.
Candidate Pipeline SHA256:
`4e957652cef278b5aff5e5e5a59301f172c2e2780af19c38a959e32f5f74c5bc`.

An outer managed AST slot survives an inner scope containing lexer, token
vector and parser. That inner scope ends after the existing parser diagnostic
check, before source stamping, visibility, analysis and lowering. Diagnostic
construction remains before cleanup, AST strings retain their managed owners,
phase marks and resolved-source lifetime remain unchanged. The extra managed
assignment and ARC poll costs remain; they must be included in measurement.

Only source inspection, exact Git patch/blob comparisons and diff whitespace
checks ran. Earlier evidence at
`~/.cache/btrc/plan-consolidation-2026-10-07/subagent-delivery/token-lifetime/69ca0f17/`
contains 146 bounded correctness checks and instrumented ASan/UBSan observation
of 93 parse boundaries and 2,296 token destructions. It remains historical
correctness evidence, including the failed Nix sanitizer probe and separately
identified Apple sanitizer toolchain. It proves neither current acceptance nor
whole-process memory benefit. Earlier quiet attempts produced zero accepted
samples; they supply no numerical speed or memory result.

## Fresh paired build and correctness admission

Freeze and archive exact3974 and exact2ff production input inventories outside
Drive. Record full final branch HEAD if a report-only descendant is used, and
verify that it differs only in the owned documentation/claim. Preserve the
existing source refs, report all source deltas, and use separate build/output/
cache directories. The combined tree includes integrated Linux providers and
the Windows header repair; never substitute a pre-integration baseline binary.

Before each allocated stage require at least80GB free and the established
locks. Hold gate plus one btrcc-build slot; never build beside bootstrap/C11,
controlled GUI work or measurements. The integrator owns scheduling.

For each source tree, use the same qualified toolchain, optimization and target:

```sh
# macOS: retained Nix Clang21.1.8, identical SDK/reader/environment for both.
python3 -m src.compiler.python.main src/compiler/btrc/cli/MacOSMain.btrc --strict-imports --no-cache --target macos-arm64 -o <source-specific.c>
clang -std=c11 -Wall -Wextra -Werror -pedantic -O2 <source-specific.c> -o <source-specific-btrcc> -Wl,-stack_size,0x20000000 -lm -lpthread

# Linux x86-64: same pinned native image and actual CC for both; no cross-counter substitution.
python3 -m src.compiler.python.main src/compiler/btrc/BtrccMain.btrc --strict-imports --no-cache --target linux-x86_64 -o <source-specific.c>
<same-qualified-cc> -std=c11 -Wall -Wextra -Werror -pedantic -O2 <source-specific.c> -o <source-specific-btrcc> -lm -lpthread
```

Retain actual argv, source inventory, generated C/binary hashes, compiler path
and version, native reader/SDK, flags and complete environment provenance.
A label such as `cc` alone is insufficient toolchain evidence. Re-emit the
candidate compiler with its fresh binary and inspect both frontends' actual
`CompilerPipeline_compileResolved`: NULL outer slot, owned AST handoff,
parser/vector/lexer release before stamping, diagnostics before error cleanup,
and AST owner surviving the release. Do not replace emitted ownership proof
with a source-text assertion. Run existing production-driver diagnostics,
managed-string/f-string/ARC and scope cases against current binaries. Reuse the
historical selector and fail-closed sanitizer reporter, repinned to current C;
never suppress an observed sanitizer report on an expected diagnostic path.
All normal parity/bootstrap/C11/final-tree gates remain required separately.

## Two Linux peak regressions: bounded diagnostic first

The retained hosted result is merge7135457 (head71a22734), not current3974.
The baseline record is cdf9d95, on Linux x86-64. Both programs are compiled by
the measured compiler; RunDispatch's name does not make this a runtime-memory
failure. Existing `tools.bench` uses the child's wait4 maxrss, lowest of three
samples, with no BTRC_TIMING memory retained in the peak measurement.

| Workload | Tracked peak | Current hosted peak | Existing permitted limit |
| --- | ---: | ---: | ---: |
| CompileStdlibHeavy | 44,789,760 B | 45,973,504 B | 45,838,336 B |
| RunDispatch | 17,924,096 B | 18,989,056 B | 18,972,672 B |

Limits use the unchanged larger of2% or1MiB slack. Hosted failures exceed them
by132KiB and16KiB respectively. Output sizes and parity were exact, but the
logs have no phase-specific peak or retained raw memory samples to identify a
cause. Neither proximity to a limit nor historical correctness excuses failure.

On one Linux x86-64 image/toolchain, run exact source-matched binaries in bounded
alternating B,C; C,B; B,C invocations, each with its own JSON and scratch path:

```sh
python3 -m tools.bench check --btrcc <exact-binary> --cc <same-qualified-cc> --programs CompileStdlibHeavy,RunDispatch --peak-only --no-reference --repeat 3 --strict --timings report --json <fresh-result.json> --out-dir <fresh-scratch>
```

Each invocation retains the original gate status and minimum-of-three meaning.
Do not treat repetitions as a search for one passing sample. Keep all results,
compare B/C on the same architecture, and preserve source/output parity during
correctness qualification. No baseline update, tolerance override or alternate
baseline file is allowed. A Linux ARM64 or macOS result cannot close this
Linux x86-64 failure. Targeted peaks are diagnostic; closure requires the
unchanged full hosted `make NIX= bench-check BENCH_ARGS="--repeat 3 --strict --timings report"`,
including all output/parity/runtime checks.

The candidate can reduce token-owner overlap with later analysis/lowering.
It cannot lower a peak already reached while parsing; allocator page retention
can hide freed allocations, and extra cleanup can increase instructions. A
negative result remains useful evidence and must not trigger threshold changes.

## D9 instructions and footprint; formal admission unchanged

Reuse the reviewed `tools/bench/scripts/instr.sh` and private runner
`/private/tmp/btrc-audit-repair/token-lifetime-quiet/`, copied into fresh retained
evidence. Its old pins make it unsuitable to execute unchanged. Repin both
source/binary/build receipts and the current quiet harness only after the new
builds qualify. Retain the exact D9 BTRSmith tree
`aeeca0fdcd676832b5e152c0e5340a2118918dd0` (851 Git-verified files and canonical
path-to-SHA256 inventory); do not silently refresh the workload or product lock.
The current Stage4 pin and reconciliation prerequisites govern formal Stage5
admission. Until they close, the result is a D9 diagnostic, not formal budget
acceptance. After they close, run the existing formal runbook/budget_bench
sample counts and scenarios; do not present six diagnostic samples as that gate.

Use `~/.cache/btrc/bench.noindex/` workspaces and retained evidence outsideDrive.
Hold bench plus gate; enter the retained Nix environment before quiet checking.
Before every sample preserve the60-second quiet window,5-second sampling,
5% CPU threshold and180-second preflight deadline. Require all guests stopped
and the integrator's explicit no-active-agent/remote-job barrier. No system
settings changes, unrelated process termination or quiet-rule overrides.

Discard B,C warmups, then measure B,C; C,B; B,C with jobs1, strict imports,
BTRC_TIMING=1, identical module-unit flags and fresh cold caches/outputs.
Preserve the240-second process deadline and TERM/10-second-grace/group-KILL
cleanup. Require compiler and wrapper rc0, positive retired-instruction and
peak-footprint counters, exact output inventories and documented normalized
C/unit/header/plan equality while retaining raw bytes. Rehash source, workload,
binaries and tools afterwards. Report every sample, medians and deltas, including
additional cleanup costs. Phase timing shifts do not establish whole-process
improvement. Mac footprint/instructions are separate from Linux maxrss.

Decision remains open: qualify current correctness, measure current tradeoffs,
and then review whether to retain the change. No current build or measurement
has run, and no performance improvement is claimed.
