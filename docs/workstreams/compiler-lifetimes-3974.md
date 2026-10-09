# Combined compiler lifetime candidate on3974

Source preparation only; this combined tree has not been built, tested or
measured. D29 owner: performance_review. Exact base:
`3974d47bc87851b1ac19b8d2b4bd5022f2d94676`. The two production files are copied
byte-for-byte from independently reviewed sources:

- `pipeline/Pipeline.btrc` from token candidate
  `71352c50120a20d250be2e8243fd2b8271aa1271`.
- `pipeline/ModuleUnits.btrc` from reply candidate
  `d7268b467967073c6c04f85086bdad0fba13b97b`.

No generic4d930 code, runtime, generated data, Python compiler, stdlib, workflow,
benchmark threshold, cache key or wire format change is included. Exact changed
paths versus3974 are those two files, this report and the WORKSTREAMS claim.
The preparation uses a private index; the active generic branch, checkout and
real index remain unchanged. No new clone or worktree is created.

## Interaction and ownership review

CompilerPipeline.compileResolved finishes lexing/parsing inside a nested scope.
The outer managed program retains the AST and its strings; parse inputs leave
scope before source stamping, visibility and analysis. Existing lexical/parser
errors are converted to positioned results before cleanup. Phase marks remain
at their original source points. Intentional program/resolved/analyzer/analyzed
keeps later in the module path remain unchanged.

That same pipeline eventually calls ModuleUnitCompiler.compile. Its finished
reply vector is a later, independent owner populated by the existing worker
exchange. The loop first acquires an owning local reply, then clears that slot.
The local survives header parsing, substring creation, diagnostics and cache
serialization. The record's C text is an independent owning substring. Existing
loop cleanup retires the original reply before the next record. Worker exchange,
request order, unit keys, generation publication and graph keeps are unchanged.

There is no token pointer or parser owner transferred into the reply vector;
there is no changed wire/data dependency between these edits. Releasing parse
owners earlier changes the live heap/collector schedule under the later module
path, so combined execution still requires qualification. Do not add the two
separate measured/observed results or infer a combined peak from them. The finish
batch is still fully gathered before consumption; its initial peak is unchanged.
Whole-program CompileStdlibHeavy reaches the token edit but not the reply loop.

## Existing evidence, not combined acceptance

Token-only3974/71352 source-matched qualification passed292 rows across the two
binaries, with exact literal/selfhost emission evidence. Hosted Linux run
37732563990 passed all three original candidate peak checks. The reported8.241%
heavy reduction is the median of three checker results, each of which selects
the minimum of three samples; it is not a product footprint result. Existing
limits and the baseline's failed checks are retained.

Reply-only d726 passed its original Nix Clang21.1.8 build. Actual jobs1/3 baseline
runs retained six watched replies each; candidate runs destroyed all six before
the next-record/end boundary while preserving seven exact emitted C files.
Eighteen existing semantic rows passed with zero skips; actual Apple clang
ASan/UBSan compiler jobs1/3 also passed exact C/lifetime checks with zero reports
(leak detection disabled). Independent evidence review passed. Earlier unique-
anchor and differing-BTRC_HOME comparison refusals remain preserved.

Evidence directories under `~/.cache/btrc/plan-consolidation-2026-10-07/`:
`token-current-3974`, `token-linux-peak-3974-hosted`, and
`module-finish-reply-3974/d7268b46`. Generic4d930 removed unused maps but did not
pass its three heavy peak checks; that experiment remains separate.

## Focused qualification before full gates

1. Freeze/archive this exact combined source and inventory every file/mode.
   Reuse the authenticated3974 baseline binary55170f40 and token71352 binary
   only if their original receipt/tool/source identities still verify. Build the
   combined candidate with original tools/bench/scripts/build_btrcc.sh, the same
   retained vn9 shell, Nix Clang21.1.8 and actual Python3.14.6, original flags.
   Set BTRC_TEST_BTRCC only to that newly built candidate. Existing binaries are
   not source-matched to this combination. Inspect both emitted ownership edges.
2. Reuse token-current-3974's exact production-boundary adapter, existing
   test_scope_capture_parity.py and the four corpus cases FstringEscapes,
   StringCharEscapes, ExceptionCleanupScopeMarkers and SwitchCaseScopeArc.
   Collect exact identities first; preserve baseline diagnostics, byte comparisons
   and zero-skip requirements. Reuse the module reply packet's unchanged11
   selectors yielding18 original rows (worker timing/count/inline, replay/edit/
   corrupt generations, record/error paths and paired native corpus execution).
3. Reuse the reviewed scratch lifetime observer on the combined generated C,
   jobs1/3, with authenticated baseline process/build receipts and identical
   common BTRC_HOME. Require original C filenames and bytes plus actual reply
   destruction; pin source/tool/fixture before and after every process. Reuse the
   existing token ownership proof for parse cleanup with the new generated C,
   and run actual combined compiler ASan/UBSan correctness at original flags.
   Observers remain scratch-only; never benchmark an instrumented binary.
4. Qualify the exact combined tree with original make test, bootstrap and
   test-c11 in the required serial order; lint, format, generated-source,
   extension and repository-hygiene gates also remain required. Capture all311
   original boundary records through their original producers, inspect effective
   artifacts/status/equality deltas, and preserve normal checker incompatibility
   counts rather than claiming311 checker passes. Hosted/current-tree original
   Linux peak checks must retain their baselines and allowances.

## Current-product measurement using existing owners

Do not measure the live product checkout. At the next allocated quiet lane,
freeze/archive a specific current BTRSmith source revision and its tracked-file
inventory outside Drive under ~/.cache/btrc/bench.noindex/. The source observed
at preparation is d3fb25f491137ebb0f9c1f06757301cb39595a80; confirm with its owner
before making it the run pin, since its native qualification is still active.
Retain its existing flake.lock and compiler-source override separately; do not
silently change its locked compiler. Use the already realized matching product
shell, native reader, SDK and package-config closure. First prove a successful
unmeasured application compile/link-plan parity on the exact snapshot using the
original application-frontend-check owner or its authenticated prior result.

Reuse tools/bench/scripts/instr.sh for the real src/BTRSmith.btrc module-unit
compile: strict imports, macos-arm64, --debug, --jobs1, fresh private output/cache
per sample, BTRC_TIMING=1. Enter the saved product shell once BEFORE quiet;
BSM_ENV_ACTIVE=1 prevents a Nix invocation after admission. Use one common
byte-verified compiler stdlib root so canonical unit identities remain exact.
Reuse the retained token quiet runner's existing bounded process owner and
provenance-only repinning, not a new benchmark harness. Keep the unmodified
QuietCheck60s window,5s samples,5% threshold,180s admission deadline; all guests
stopped, >=80GB and bench+gate locks. A quiet refusal remains a refusal.

Primary comparison:3974 versus combined, discarded warmup pair followed by
BC/CB/BC. Record each printed compiler rc as well as wrapper status (instr.sh
can exit0 after compiler failure), wall time, instructions retired, peak memory
footprint and per-phase lines; reject missing/nonpositive counters or incomplete
outputs. Preserve raw C/unit/header/plan inventories. Compare through existing
path normalization only where output paths require it, label that normalization,
and never discard semantic differences. Validate all inputs/tools again at end.

An optional separately scheduled token71352 versus combined comparison isolates
reply-slot incremental benefit on the same product snapshot; it cannot reuse a
different workload or claim additivity. Keep historical851-file aeeca0fd D9 as a
separate diagnostic, never relabel it current product. Original3GiB guard and
<=1.5GiB final target remain unchanged. Stage4 current-pin/product prerequisites
and Stage5 full matrix remain separate from a valid labelled current-product
A/B diagnostic. No measured product saving or combined acceptance exists yet.
