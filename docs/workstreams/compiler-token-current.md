# Current compiler token-lifetime candidate

## Claim and status

Integrator assignment under D29, 2026-10-08. Branch
`codex/compiler-token-current` starts at exact baseline
`56d548c49ca027c9698c8546acdaf4df918630bd` in the existing `http-contract`
clone. Own only `src/compiler/btrc/pipeline/Pipeline.btrc`, this report and the
corresponding `WORKSTREAMS.md` claim row. The Windows branch remains at
`110a514c5f91bc6c647f84f944f80ff8eae3fecc`; the historical token branch remains
at `d6309c7ca4e71c92415851359a50223e1cfdba48` (implementation `69ca0f17`).
The separate Linux UI2 branch remains frozen at `44a6f04a`.

Reapply only the reviewed lexical lexer/parser/token ownership change from
`69ca0f17eb95aaf5213e93d9b134c6e15a30d3b9`. No stale report/claim merge, Python
pipeline change, runtime change, generated edit, ownership escape or benchmark
baseline adjustment is authorized. Python owns its existing reference lifetime
and remains unchanged by design. Preserve the exact AST strings, diagnostics,
phase marks and downstream ownership.

Status: source preparation only. No current candidate build, test, emitted-C
inspection, sanitizer qualification, benchmark, PR or CI run has occurred.
Baseline qualification is parent-owned and incomplete. A lexical scope change
is a mechanism hypothesis, not proof of peak-memory or instruction improvement.

## Source checkpoint

Production candidate: `01c172754a30c5debce9fc4e822eaed125988a3c`. The only production difference from
baseline `56d548c49ca027c9698c8546acdaf4df918630bd` is the original 27-line Pipeline hunk. The resulting Git
blob is `29e905f4d0b945bd5a27759e1e904add25c6a264`, identical to `69ca0f17`.
Pipeline SHA256 is `60694619faa0c197c2966ed19e2825ef59cfb25b10f7723ddda6c7f8aebce272` for baseline and `4e957652cef278b5aff5e5e5a59301f172c2e2780af19c38a959e32f5f74c5bc` for candidate.
The change initializes the outer managed AST slot, parses within a nested scope,
then ends lexer/parser/vector ownership before source stamping. Error branches
render diagnostics before their owners leave scope. AST-managed string aliases,
resolved input ownership, timers and later explicit keeps stay unchanged.

Only read-only source comparison, patch applicability and `git diff --check`
have run. No compiler was invoked. Source remains unqualified on this current
base. The additional managed assignment/poll-cycle cost from the original
candidate remains and must be measured; this packet adds no speculative tuning.

## Historical evidence, bounded scope

The retained old evidence directory is
`~/.cache/btrc/plan-consolidation-2026-10-07/subagent-delivery/token-lifetime/69ca0f17/`.
Its normal and instrumented campaigns passed 120 production diagnostic checks,
8 paired managed-literal/ARC cases and 18 scope/capture checks (146 total).
The explicit ASan/UBSan report scan observed 93 main-parse boundaries and 2,296
watched token destructions, including lexer failure, parser failure and success
before stamping. Successful later stages still consumed AST strings. Both
frontends' emitted ownership sequence was reviewed. This is historical bounded
correctness evidence only, not current qualification, whole-compiler leak proof,
bootstrap completion or a measured performance improvement. The failed Nix
sanitizer-startup probe and the separate Apple clang sanitizer provenance remain
part of that record; do not relabel the latter as Nix qualification.

## Current qualification recipe (not run)

1. Parent first finishes its baseline build at exact `56d548c4` and records
   baseline compiler binary/generated-C hashes, full source inventory, target,
   flags, SDK/reader/environment and C compiler identity. Use the same qualified
   Nix clang 21.1.8 `-O2` build for candidate `01c17275`; if the actual baseline
   uses another toolchain, pair both builds on that exact toolchain instead.
   Never use old binaries `85c40290`/`e9333376` as current samples. Their source is
   different. Hold the existing `gate` and allocated `btrcc-build` slot, check
   at least 80 GB free, and run no build alongside bootstrap/C11 or a measurement.
2. Retain baseline C, then reference-emit current candidate MacOSMain with
   `python3 -m src.compiler.python.main src/compiler/btrc/cli/MacOSMain.btrc
   --strict-imports --no-cache --target macos-arm64 -o <candidate.c>`.
   Build it with the baseline's exact C compiler/flags. Hash the result before
   setting `BTRC_TEST_BTRCC` and `BTRC_HOME` to the immutable candidate paths.
   Self-transpile once with that binary, using the same flags and clean cache.
3. Inspect the actual `CompilerPipeline_compileResolved` from both candidate
   emissions against baseline: outer program slot NULL before the inner mark;
   owned AST handoff; parser/vector/lexer releases before source stamping;
   diagnostic construction before error cleanup; no premature program release.
   Preserve complete generated files and extracted functions. Do not substitute
   source-brace matching for generated ownership proof.
4. Run the existing production diagnostic, string/ARC and scope tests against
   current source. Reuse the retained production-driver assertion selector from
   `test_production_boundaries.py`, updating only exact source/binary provenance;
   it exercises actual driver failure paths rather than a toy parser. Retain
   every diagnostic/status, original failure and zero-skip count. Commands for
   the existing paired bodies are:

   ```sh
   python3 -m pytest -q src/tests/runner.py --compilers=both -k 'FstringEscapes or StringCharEscapes or ExceptionCleanupScopeMarkers or SwitchCaseScopeArc'
   python3 -m pytest -q src/tests/btrc/test_scope_capture_parity.py
   ```

   The full lexer/parser modules and strict-import audit remain normal gate
   obligations; the bounded selector is not their replacement. Re-run current
   compiler sanitizers before current lifetime acceptance, with the retained
   fail-closed instrument/report scan adapted to the new emitted source hashes.
   Never ignore a current candidate fault because an old candidate passed.
5. Normal paired corpus, bootstrap fixed point, strict C11, boundary checks and
   remaining final-tree gates still belong to integration. Qualification or a
   measurement result below does not waive them.

## Whole-process measurement recipe (not run)

Use the existing `tools/bench/scripts/instr.sh` and reviewed private runner at
`/private/tmp/btrc-audit-repair/token-lifetime-quiet/`, with a fresh evidence copy
and an explicit repin after both new build receipts exist. That old runner is
**not directly runnable for this candidate**: its old binary/source constants
must fail admission, never be silently reused. Pin the current baseline and
candidate above, full binary SHA256s and build receipts, the exact current quiet
harness at the same baseline revision, and the retained official SDK/reader/
package environment. Read and retain each actual build command; repository
revision alone does not prove which C compiler built a binary.

Reuse immutable D9 BTRSmith `aeeca0fdcd676832b5e152c0e5340a2118918dd0`: 851
tracked paths checked against exact Git blob bytes, plus the explicit canonical
JSON path-to-SHA256 inventory used by the reviewed runner. Do not refresh the
product pin or infer the old unretained `f67f` serialization. Stage the workload
under `~/.cache/btrc/bench.noindex/`, evidence under
`~/.cache/btrc/plan-consolidation-2026-10-07/token-current/<candidate>/`.

Hold `bench` plus `gate`. Before every sample require the unchanged quiet
60-second window, 5-second sampling, 5% background CPU ceiling and strict
180-second preflight deadline. Keep all guests stopped and the parent-declared
no-active-agent/remote-job barrier; idle-service recognition is not proof that
unobserved remote jobs are absent. A blocker means zero accepted samples for
that attempt, not permission to weaken quiet settings. Enter the retained Nix
shell once **before** quiet admission, then preserve that environment for direct
sample execution. Do not alter system settings or terminate unrelated work.

Discard warmup B,C. Measure alternating pairs B,C; C,B; B,C, with jobs1,
`BTRC_TIMING=1`, strict imports, fresh cold cache/output per sample and the same
module-unit options. Bound each compiler process group at 240 seconds, TERM
then 10-second grace and group KILL; a timeout is a failed sample. Capture
`/usr/bin/time -l` retired instructions and peak memory footprint for the whole
single compiler process. Require positive counters, printed compiler rc0 and
wrapper rc0, complete emitted C/unit/header/plan inventories and semantic output
equality. Preserve raw bytes; only the existing documented path/unit-name
normalization is allowed and must be described as normalized equality.
Rehash binaries, source, workload, tools and native environment after all runs.
Report every sample, medians and deltas. A phase shift can be cleanup newly
included before the timer, not a process regression. This remains diagnostic
until current Stage4/BTRSmith pin prerequisites close.

## Linux small-workload failures (separate required outcome)

Parent-provided hosted failures are `CompileStdlibHeavy` 45,973,504 bytes versus
tracked 44,789,760, and `RunDispatch` 18,989,056 versus 17,924,096. These are
Linux child maxrss metrics, not macOS footprint; do not compare the counters
across operating systems. The preserved tracked baseline and default 2% memory
slack remain unchanged. No command in this packet uses `bench baseline`,
`--peak-tolerance`, `--tolerance` or a replacement baseline file.

After an allocated Linux lane builds exact baseline and candidate on the same
native toolchain/image (host-appropriate BtrccMain), run the existing harness
for each source-matched binary and corresponding source data in immutable trees:

```sh
python3 -m tools.bench check --btrcc <exact-binary> --cc <same-qualified-cc> --programs CompileStdlibHeavy,RunDispatch --peak-only --no-reference --repeat 3 --strict --timings report --json <fresh-results.json> --out-dir <fresh-scratch>
```

Retain both statuses and compare each against the same tracked baseline. Use
separate fresh invocations for alternating B,C; C,B; B,C observations rather than
turning a lucky sample into closure. A lower candidate peak may still fail the
existing threshold. These targeted peaks are diagnostic; final closure requires
the unchanged complete hosted command, including its parity/size/runtime checks:
`make NIX= bench-check BENCH_ARGS="--repeat 3 --strict --timings report"` in the
qualified image. Mac D9 benefit does not imply these Linux regressions are fixed.

Decision: retain the change only after current correctness proof and measured
peak/instruction tradeoffs are reviewed. If it does not reduce current peak or
adds unacceptable instructions, retain the evidence and leave the candidate
unlanded. No historical improvement or current acceptance is claimed here.
