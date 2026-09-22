# Compile performance: where the time goes and what to do about it

**Current priority, September 22:** unchanged latency is closed at ≤5 s.
The latest edit/cold campaign is recorded at the end of this document; the
September 19 profiles below are historical and use a different host/mode.

Measured 2026-09-19 on the BTRSmith application (`src/BTRSmith.btrc`: 361
product files, 72k lines, plus 21 packages; 604k lines / 46.6 MB of C out,
19,208 functions, 1,495 structs, 183 `Vector` instances) on a 32-core x86_64
NixOS host. Everything below is single-threaded wall time unless noted.

## Measurements

### The build

| Stage | Wall | Peak RSS |
| --- | --- | --- |
| `btrcc` transpile (self-hosted compiler) | **542 s** | 5.2 GB |
| `btrcpy` transpile (reference compiler) | **742 s** | 2.5 GB |
| `btrcpy` with its compile cache "warm" | 746 s | 2.5 GB |
| `clang -O2` on the one emitted unit | 83 s | 1.2 GB |
| `clang -O1` | 75 s | 1.2 GB |
| `clang -O0` | 9 s | 0.9 GB |
| `clang -O2 -g` | 114 s | 3.1 GB (80 MB object vs 25 MB) |
| `gcc -O2` | 120 s | 1.9 GB |
| link | ~9 s | |

A warm `make btrsmith-native` is therefore ~10.5 min, of which **86 % is
the btrc compiler** and the remaining 14 % is clang on a single translation
unit that nothing can parallelise. The btrcpy cache never hits: the
`Makefile`s pass `--no-cache`, and the key is the entire resolved source, so
it is all-or-nothing anyway.

Every product check (`tests/macos/*.btrc`, 37 targets × 2 frontends) imports
the whole application and pays the full transpile again. That multiplier,
not the single build, is what makes the suite take hours.

### Phase split inside btrcc (`BTRCC_TIMING=1`)

| Phase | Time |
| --- | --- |
| resolve + native header import + lex + parse + visibility | 4.9 s |
| analyze | 209 s |
| lower | 248 s |
| optimize | 46 s |
| emit | 2.8 s |

The front end is irrelevant. Analysis and lowering are 84 % of the run.

### Scaling: it is not the output size

btrcc compiling itself emits *more* C than BTRSmith (608k lines, 21,919
functions) but takes **64 s** (analyze 11 s, lower 35 s, optimize 6.5 s). The
difference is 442 structs vs 1,495: the cost grows with the square of the
number of classes, not with the amount of code. That is the signature of
the hot spots below.

### btrcc hot spots (gprof, `-pg` build, 788 s sampled)

| Bucket | Inclusive | Root cause |
| --- | --- | --- |
| `CycleSemantics.appendRuntimeTypes` → `Analyzed.isSubclass` (276 M calls) | ~200 s (40 %) | For every class-typed field it walks **every** class (`classTable.keys()`, 1,495 entries) and calls `isSubclass`, which allocates a `Vector` and a `Map` per call and walks the parent chain. O(fields × classes × depth). |
| `OwnershipOperandEnvironment.copyTypes` (2.5 M calls) | ~88 s (19 %) | Every expression-type query copies the whole variable-type map (`variables()` returns a fresh copy). |
| `Node.new`/`Node.init` (4.17 M nodes) | ~75 s | One 103-field AST node class; the constructor eagerly allocates 21 empty vectors per node (88 M allocations). Also most of the 5.2 GB. |
| `SetjmpSafetyPlanner` / `SetjmpEffectAnalysis` | ~36 s | Re-walks pointer flow per function; most of the "optimize" phase. |
| `Analyzed.nativeGlobalReturnsOwned` / `nativeGlobalReadOnly` (366 k calls) | ~30 s | Linear scan of every imported native declaration per query. |
| `IROptimizer.containsName` (206 M vector reads) | ~7 s | DCE tests membership in a `Vector<string>` by linear scan. |
| ARC/cleanup runtime: `__btrc_arc_release_impl`, `__btrc_arc_replace_edge`, `__btrc_reverse_add`, `__btrc_register_cleanup_kind` (12.3 **billion** cleanup registrations) | ~60 % of self time, spread across the above | Temporaries in hot loops: every `keys()` vector, every copied map, every `pending`/`seen` in `isSubclass` is refcounted, reverse-edge tracked and cleanup-registered. Fixing the algorithms removes most of it. |

### btrcpy hot spots (cProfile, 2,100 s instrumented)

The reference compiler has the same shape with different constants:
lowering is 69 %; `generics._thaw` / `codec.decode` (frozen type trees stored
as JSON and `json.loads`-ed **36.5 million** times, 690 s), `_is_subclass`
(220 M calls, 177 s) under `type_may_cycle`, tuple-type collection that
re-walks the AST 4 M times (305 s), and the setjmp planner (480 s).

## The axes, and where btrc stands on each

| Axis | Today | What matters |
| --- | --- | --- |
| **Cold latency** | 10.5 min | Dominated by two quadratic algorithms and one serial clang unit. |
| **Incrementality** | None. `--no-cache` in every Makefile; the cache is keyed on the whole closure; the front end concatenates the closure into one source string before lexing, so there is no per-module boundary to cache at. | Edit one adapter → 10 min. The test suite re-transpiles the app 74 times. |
| **Parallelism** | None. One thread in btrcc; one translation unit for clang. | 32 cores idle. Per-function lowering (19,386 bodies) and per-unit clang are both embarrassingly parallel. |
| **Memory** | 5.2 GB (btrcc), 2.5 GB (btrcpy), 1.2 GB (clang), 3.1 GB with `-g`. | Fat nodes: ~0.7 KB × 4.2 M nodes. The whole AST, analysis and IR are live at once. Hostile to laptops and CI runners. |
| **Debuggability** | No `#line` directives: assertion failures and gdb frames point at generated C lines. `-g` costs +30 s and 3× the object. The native plan does accept `--opt 0` (9 s compile) but the Makefiles always build `-O2`. | A developer loop wants `-O0 -g` with source-mapped frames; a release wants `-O2`. |
| **Determinism / verification** | Strong: each compiler's output is deterministic, btrcc reproduces itself bit-for-bit (bootstrap fixed point), the corpus runs on gcc+clang at O0–O3 from both compilers. The two compilers do *not* emit identical C to each other (different include ordering, temporaries, DCE decisions), so parity is behavioural plus link-plan equality. | Every optimisation must be implemented twice (Python and btrc) and keep each compiler's own output identical. This is the real cost multiplier on the work below. |

## Proposal

Ordered by payoff per unit of effort. Each step is independently shippable
and verified by the existing gates (`make test`, `make bootstrap`,
`make test-c11`, BTRSmith `application-frontend-check` parity).

### 0. Algorithmic fixes (days; ~4× on the transpile)

All are local changes inside the two compilers, no format or ABI change.

1. **Subclass index.** Build `parent → children` and `class → ancestor set`
   once after declaration registration; `isSubclass` becomes a set lookup and
   `appendRuntimeTypes` iterates only the descendants of the field's type.
   Removes ~200 s. Same fix in `ownership._is_subclass` / `_runtime_type_candidates`
   for btrcpy.
2. **Scoped variable environments.** Replace `copyTypes` with a chain of
   scopes (lookup walks outward; a new scope is a pointer to the parent), or
   copy-on-write. Removes ~85 s.
3. **Index the native declarations** by name (`nativeGlobalReturnsOwned`,
   `nativeGlobalReadOnly`, `nativeClassLanguage` callers). Removes ~30 s.
4. **Memoise the setjmp analysis** per function and stop re-walking pointer
   flow for functions without `try`. ~25 s here, ~400 s in btrcpy.
5. **Sets, not vectors, in DCE** (`containsName`). ~7 s.
6. **Lazy vectors in `Node`** (allocate the 21 child vectors on first push).
   ~40 s and roughly a third of the memory.
7. **Pointer-keyed memo maps** instead of `AstIdentity.key` formatting the
   node address into a string for every lookup (68 call sites).
8. btrcpy only: stop storing resolved types as JSON strings that are
   `json.loads`-ed on every `_thaw` (36 M decodes); keep them as frozen
   tuples with an interned cache. ~700 s of the instrumented run.

Expected: btrcc 542 s → **~120–150 s**; btrcpy 742 s → ~200 s; memory
5.2 GB → ~3.5 GB. The ARC overhead falls with the temporaries.

### 1. Multiple translation units (about a week; the clang minutes → seconds)

Cut the emitted C at package boundaries (`packages` in the link plan already
name them: 12 stdlib groups, `btrsmith`, and the 8 native packages):

- one generated header with every struct, typedef, function prototype and
  the runtime prelude;
- one `.c` per package with its functions; each generic instantiation and
  each runtime helper assigned to exactly one unit (the package that first
  demanded it), `static` dropped from anything referenced across units;
- the native plan compiles units in parallel and links; `-flto` optional for
  release builds if cross-unit inlining turns out to matter (it usually does
  not for this code).

Whole-program analysis, DCE and instantiation stay exactly as they are; only
`emit` and the plan change. `clang -O2` 83 s → ~15 s on 8+ cores; link stays
~10 s. `IRFunction` needs an origin field (declarations are already stamped
with their source file by `stampProgramSources`).

### 2. Developer build mode and source mapping (days)

- Emit `#line` directives (the line map already exists for diagnostics:
  `sourceFileForLine`). gdb, sanitizer reports and `assert` messages then
  name `AlbumGrid.btrc:97` instead of `btrsmith.reference.c:489457`.
- `make btrsmith-native BUILD=dev` → `--opt 0 -g` through the native plan:
  9 s compile instead of 83 s. Release stays `-O2`.
- With per-unit compiles, `-g` cost also parallelises.

### 3. Incremental compilation (weeks; the test suite → minutes)

The front end has to stop concatenating the closure into one string. Per
module: hash of source + imports + toolchain fingerprint → cached parsed
declarations and per-module analysis results. Whole-program passes
(instantiation, DCE, cycle analysis, lowering) still run every time, but
after step 0 they are the cheap part; the emitted units that did not change
are not recompiled by clang. Expected incremental rebuild after editing one
product file: **30–60 s**. The 74 whole-app test transpiles in the check
suite become ~1 min each because the application's modules come from cache.

If the instantiation set turns out not to be stable enough to cache lowered
output per module, the fallback is caching only parse + analysis and always
re-lowering; that still lands around 1–2 min incremental.

### 4. Parallel lowering (later, optional)

`FunctionLowerer.lowerBody` runs 19,386 times with per-function state; it is
the obvious thread-pool candidate once the shared tables are read-only after
analysis. Gated on the btrc ARC runtime being safe for objects confined to
one thread plus read-only shared tables — worth doing only if steps 0–3
leave lowering as the bottleneck.

### 5. Slimmer AST (later)

Per-kind node structs instead of one 103-field `Node` would cut memory by
~3× and allocation time further, but it touches every pass in both
compilers. Not before 0–3.

## Targets

| | `make btrsmith-native` cold | incremental (one file) | peak RSS |
| --- | --- | --- | --- |
| today | ~10.5 min | ~10.5 min | 5.2 GB |
| after 0 | ~4 min | ~4 min | ~3.5 GB |
| after 0 + 1 | **~2.5–3 min** | ~2.5–3 min | ~3.5 GB (clang units ~300 MB each) |
| after 0 + 1 + 2 (dev mode) | ~2.5 min | ~2.5 min | |
| after 0–3 | ~2.5–3 min | **~30–60 s** | |

## Verification

Every step is gated by the existing suite: `make test` (both compilers on the
corpus), `make bootstrap` (fixed point), `make test-c11` (gcc + clang at
O0–O3), and BTRSmith's `application-frontend-check`, which already proves
the reference and self-hosted outputs and link plans are identical. Steps 0
and 2 must produce byte-identical C to today for the corpus, which is the
cheapest possible proof that an optimisation changed nothing. Step 1 changes
the emitted shape, so its proof is the corpus plus the BTRSmith check suite
on both frontends.

## Harness (M0, subsequently extended)

`python3 -m tools.perf <program.btrc>` (Makefile: `perf-btrsmith`, `perf-self`)
runs both compilers under `BTRC_TIMING=1` in a fresh measuring process.
The original harness reported wall, CPU, peak RSS, phases and single-unit C
compilation. The current harness builds all emitted/native/adapter units and
links through the production native-plan builder, in dev and release modes;
see the full-build checkpoint below. Historical tables retain their original
scope and are not retroactively qualified by the new harness.
Both compilers now print the same one-line `<name> timing: phase=NNNus …`
form; btrcpy's `--profile` is also switched on by `BTRC_TIMING`.

### Baseline: the compiler compiling itself (`perf-self`, 2026-09-19)

| Compiler | Wall | CPU | Peak RSS | front end | analyze | lower | optimize | emit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| btrcpy | 257.1 s | 255.9 s | 846 MB | 5.6 s | 10.9 s | 61.9 s | 159.5 s | 14.0 s |
| btrcc | 63.6 s | 63.3 s | 3728 MB | 3.3 s | 11.2 s | 34.4 s | 6.6 s | 2.9 s |

| Output | Lines | Bytes | Functions | Structs | Vector instances |
| --- | --- | --- | --- | --- | --- |
| btrcpy | 690,509 | 54.5 MB | 22,596 | 437 | 84 |
| btrcc | 608,703 | 48.0 MB | 21,930 | 442 | 85 |

`cc -O2` on btrcc's unit: 110.6 s, 1.7 GB. Note btrcpy's `optimize` phase
(159 s: the setjmp planner) dominates its self-compile, where btrcc's is 6.6 s.

## Progress

### After M1–M3 (2026-09-20, BTRSmith, every step byte-identical per compiler)

| Compiler | Before | After | What moved |
| --- | --- | --- | --- |
| btrcc | 542 s / 5.2 GB | **85 s** / 5.4 GB | analyze 209 s → 13 s, lower 248 s → 34 s, optimize 46 s → 17 s |
| btrcpy | 742 s / 2.5 GB | **344 s** / 1.7 GB | lower 531 s → 139 s; optimize (setjmp planner) still 130 s |

The largest single item was not an algorithm: releasing the validator and
realtime analyzer at the end of analysis cost **200 s**, because the ARC
runtime proves reverse reachability (`__btrc_arc_reverse_proves_live`) for
every reference an object drops once its only remaining owners are edges,
and those indices held a reference to most of the program. The compiler now
keeps its analysis and IR graphs alive until the process exits. The same
cost model applies to any btrc program that tears down a large object
graph; a runtime-side fix (bounding the proof, or a generational witness)
is worth its own milestone.

The other items, in order of what they removed: the subclass index (~200 s
of gprof time in `isSubclass`), shared operand environments (~88 s), the
native-declaration index (~60 s including its ARC churn), the setjmp
worklist (optimize 36 → 17 s), typedef fast paths, DCE sets.

### M4: translation units (2026-09-20)

`--emit-units PREFIX` (both compilers) splits the program into a primary unit
plus secondaries of about 40k lines of function definitions each
(`BTRC_UNIT_LINES` overrides the target), written as `PREFIX.unit-<k>.c`;
the link plan originally counted them in schema 3. Schema 4 now records their
ordered absolute paths in `emitted-units`, so a distinct prefix works;
`btrc-native-plan` retains legacy schema-3 reading and
compiles them in parallel (`--jobs`, default: CPU count). Every unit carries
the prologue, helpers, types and prototypes; the primary defines globals and
kernels, the secondaries declare them; functions and globals lose internal
linkage so units can reference each other. The runtime's file-scope state
(the ARC tables, the string registry, the thread-local try record) stays
written as plain `static` definitions; the unit emitters reshape that text
the way the stdlib archive already does — the primary unit drops `static`
and defines each variable once, every other unit declares it `extern`
without an initializer — so no runtime source changed for the split.

| | units | C compile + link |
| --- | --- | --- |
| BTRSmith, btrcpy output | 16 secondaries | **8.6 s** (84.9 s with `--jobs 1`) |
| BTRSmith, btrcc output | 14 secondaries | **7.8 s** |

The whole corpus splits, links and runs with its goldens through both
compilers (the three GPU programs need the GPU runtime library the corpus
runner links separately), and the split BTRSmith passes its library smoke
from either compiler's units.

### M5: source mapping and the dev build (2026-09-20)

`--debug` now works in btrcc as it did in btrcpy: every statement lowers to
an `IRK_LINE_MARKER` naming its `.btrc` file and line, and the emitter stamps
a `#line` before each content line of a function body — the marker's
location for user statements, the generated file's own line (patched in once
the layout is final) for synthesized code, so a debugger never points into
the wrong file. `-o PATH` lets btrcc know that name; with `--emit-units` each
secondary resets to itself. Release output is untouched: the corpus is
byte-identical to M4 through both compilers without `--debug`.
`btrc-native-plan --debug-info` adds `-g`, and BTRSmith's `BUILD=dev` turns
both on with `--optimization 0`; the dev binaries pass the goldens and their
DWARF line tables name the `.btrc` sources.

### M6: incremental rebuilds (2026-09-20)

The front end is 3 s of btrcc's 58 s on BTRSmith after M1–M5, so caching
parsed modules was dropped for cause; the milestone became the C side of an
edit-rebuild. Every lowered function now records its `.btrc` module and
`--emit-units` packs consecutive same-module runs to the line target, so an
edit changes one unit and the others stay byte-identical. `btrc-native-plan
--object-cache DIR` then reuses their objects (keyed on compiler identity,
flags and source bytes; entries idle for two weeks are pruned).

| BTRSmith, btrcc, 15 units | wall |
| --- | --- |
| cold (empty cache) | 101 s |
| no change (make re-runs the transpile) | 94 s |
| one-line edit in `NavigationHistory.btrc` | 98 s, 1 of 15 units recompiled |

The rebuild is now the transpile; the C compiler is a few seconds.

### M7: profile-driven cuts (2026-09-20)

Parallel lowering was ruled out by the runtime: every ARC retain and
release takes the global spinlock `__btrc_arc_lock_mutation`, so worker
threads inside btrcc would serialise on it. The work instead follows the
profile with new sub-phase marks (`l-*`, `o-*` under `BTRC_TIMING=1`).

| btrcc on BTRSmith | before | after |
| --- | --- | --- |
| cleanup validator adapter lookup | 54k linear scans of 30k functions | one name index |
| `TypeIdentity.utf8Hex` | 2 string concatenations per byte | one builder |
| setjmp body scans | per use | memoised per function |
| setjmp alias states | every origin set copied per branch | copy-on-write, shared empty sets |
| boundary context variables | map snapshot per query (144k) | shared table |
| **wall** | **85 s** | **76 s** |

Remaining split: lower 28 s (generic class instances 12 s, declarations
15 s), setjmp safety planner 12 s, analyze 12 s, DCE 2.8 s, emit 2.8 s.
The planner allocates about 35 million origin vectors per compile, one per
expression flow result; interning those sets is the next cut. btrcpy is
unchanged at 259 s (lower 140 s, optimize 57 s).

### Beyond M7

`PLAN.md` now carries the next four milestones with their reasoning: M8
per-kind AST and IR nodes (~30 s), M11 separate compilation with module
interface summaries and per-module C units so an edit rebuilds one module
(under 10 s), M9 arena allocation for compiler-lifetime data (~10–15 s, and
the end of the global ARC lock on the compiler's hot path), M10 parallel
analysis and lowering (3–5 s, parity with clang -O0 per line of input).

### M6a correctness and measurement checkpoint (2026-09-20)

Implementation is in progress under `PLAN.md`; this checkpoint does not
complete M6a or qualify the product build targets. The native object cache now
uses compiler preprocessing plus a system-inclusive dependency scan on every
lookup. Its versioned manifest fingerprints transitive header contents,
preprocessed output, source paths, driver bytes/version, target, compile flags,
working directory and environment (hashed without persisting environment
values). A fresh scan detects new headers earlier on the include path.
Unsupported module/PCH validation falls back to a normal uncached compile.

Objects carry checksums and publish through unique temporary directories,
with metadata published last. Corrupt/incomplete entries are misses; inputs
are validated again after compilation before publication. Failed builds retain
the previous executable. This closes the reproduced stale transitive-header
and `__FILE__` behavior. It does not yet establish complete wrapper/subtool
identity, whole-build artifact generations, stable generated-adapter paths,
link caching, or the BTRSmith no-op goal.

Small-workload cost, measured after the compiler build and formatter finished:
native-package example, three translation units, Apple Clang, arm64 macOS 27,
Python 3.13.13, `-O2`, one native job, dependencies already installed. Five cold
object-cache runs and twenty warm runs per implementation; every resulting
executable prints the expected native-package result. Timings include the real
native-plan compile/link path and exclude fixture transpilation and execution.

| Native-plan scenario | Previous median / p95 | Validated-cache median / p95 | Compiles / scans / links per run after repair |
| --- | --- | --- | --- |
| Empty object cache | 0.1542 / 0.1564 s | 0.3747 / 0.3797 s | 3 / 6 / 1 |
| Warm object cache | 0.0691 / 0.0728 s | 0.1669 / 0.1715 s | 0 / 3 / 1 |

The extra scan cost is a correctness tradeoff, not a speedup. Product-size
scan cost and the ≤2 s no-op budget remain unmeasured. Keep this oracle while
developing a cheaper validated path; rehashing yesterday's header list alone
would reintroduce include-shadowing defects. Local raw samples, source/tool
fingerprints and the rerun script are under
`build/perf/native-cache-2026-09-20/`; these are not durable CI artifacts or
complete product provenance. The baseline tool was taken from `4e5c982`.

Verification: the initial native-plan/perf baseline passed 34 tests. Six new
regressions failed on the old cache, then passed after repair. Native-plan
coverage passed 41 cases under Apple Clang and GNU GCC 15.2 before adding the
unavailable-cache and both-frontends integration cases. The expanded combined
suite passed 51 tests, including a fresh immutable self-host compiler
`da4fd10514d564858ed1d3e35d509d21`; the subsequent forced-split integration
test passed through both frontends. Cache/structure/emitted-unit regression
coverage passed 78 tests with 5 host-gated skips. Evidence is in
`build/plan-cache-and-perf.xml`, `build/plan-split-cache-both-frontends.xml` and
`build/plan-build-regressions.xml`. Full compiler/product/device qualification
remains open.

`tools/perf.py` now normalizes Darwin's byte RSS to KiB and reports MiB.
Source inspection corrected an assumption in the plan: btrcc's `mark()` resets
the timer, so `a-*`, `l-*` and `o-*` are consecutive stage slices plus a final
remainder. The report groups those slices into the correct stage once, retains
unknown marks separately and exposes unattributed wall time. The single-unit
limitation was subsequently removed by the full-build checkpoint below.

Environment note: the pinned Nix Python 3.14 aborts in libffi/`ctypes` on this
host. The focused tests and generated checks ran in `build/plan-venv` with
Python 3.13; pinned Ruff 0.15.14 passed lint/format, and the canonical BTRC
formatter passed when invoked with that Python. No signing setting changed.

### Full native-build measurement checkpoint (2026-09-20)

`tools/native_plan.py --report-json PATH` writes successful-build evidence
atomically: every emitted, native and generated-adapter unit; cache reason/key;
dependency scan, cache validation, compile and publication durations; ordered
commands; linker time; output size and build wall time. Parallel per-unit
durations are sums of work and must not be added as sequential wall stages.
Reports cannot overwrite the input plan, source units or output executable.

`tools/perf.py` invokes that same production path for both compilers. Defaults
are the inferred host target, dev with source mapping and `-O0 -g`, and release
with `-O2`. It retains fresh run directories with generated files, raw logs,
object manifests, executables and schema-2 reports, including compiler/native
failure evidence. `--samples 5 --warm-native-runs 4` produces five fresh-object
builds and twenty native-only warm samples per frontend/mode. Warm samples
validate objects and relink; they do not transpile or measure a product no-op.
Native-header, package and OS caches remain uncontrolled.

Reports include source/build-file snapshots, Git revisions, locks, tool bytes,
versions where available, selected environment, target, host and worker count.
Before/after checks reject observed source or driver changes. Snapshot scope
is explicit: it is not a complete resolver/SDK dependency manifest and cannot
detect edits reverted between observations. Power/thermal state is unmeasured;
RSS is normalized per-process usage, not aggregate concurrent build memory.

The combined native-plan/performance suite passed **71 tests**
(`build/plan-full-build-measurement.xml`). Subsequent provenance refinements
passed all **23 performance tests** (`build/plan-measurement-final.xml`). These
execute forced split units through both frontends in both modes, C/C++ and
macOS Objective-C/Objective-C++ fixture units, warm reuse and real linking.
A separate native-plan case compiles and links a generated C++ RAII adapter.
Failure cases preserve frontend/linker diagnostics and reject measurements
after a package source changes during a real build. Pinned Ruff lint/format
also pass. Full compiler/product release gates remain open.

The local BTRSmith Nix development shell failed to build its pinned compiler:
Python/libffi aborted during transpilation. A diagnostic environment combining
the product's native dependencies and this repository's SDK environment can use
the fresh local self-host compiler; it does not qualify the pinned package or
repair that environment failure. Keep any resulting timings separately labeled.

#### BTRSmith diagnostic build on this host

One self-host dev build completed against the **older local product revision
`292deaff4373c4dba2a58c992e79d733ca47b0cd`**, compiler revision `4e5c982` with the
working-tree measurement/cache changes, on arm64 Darwin 27.0.0. The native
compiler was Nix Clang 21.1.8, Python 3.13.13, four native jobs, source-mapped
`-O0 -g`; the fresh self-host binary SHA-256 was
`ac9fab70c007bc1e9976005ba819fd53731bd6ffee842fb3242816078e4bc1aa`.
Before/after observed inputs and tool bytes were unchanged. Native dependencies
were already provisioned; OS caches, thermal/power state and background load
were uncontrolled. This is **one diagnostic sample**, not a median/p95 estimate
or qualification of remote product `5549c261` or its pinned release package.

| Observed stage/scenario | Wall time | Evidence |
| --- | ---: | --- |
| Self-host transpilation | 158.733 s | 4,740.1 MiB compiler peak RSS; grouped frontend/analyze/lower/optimize/emit: 37.975 / 21.757 / 38.234 / 19.978 / 31.733 s; 9.056 s unattributed |
| Native cold compile/link subprocess | 14.044 s | 15 emitted C units + 2 generated adapters compiled; 1 link (0.351 s) |
| Complete measured cold build | 173.619 s | Includes transpilation, C-stat collection, native build and harness overhead |
| Warm native only | 5.204 s | 15 reused objects, 2 adapter cache misses, 1 link (0.282 s); no retranspilation |

The executable is 18,938,344 bytes. The 15 emitted C files total 1,991,683 lines
and 202,456,087 bytes, including repeated prologues/source mapping; these are
not counts of unique program definitions. The executable was linked, not
launched or packaged for this measurement.

The warm run spent a summed 6.306 s in dependency scans, 3.736 s in other cache
validation and 1.002 s compiling adapters. These durations overlap across
workers. Both adapters missed because each build materializes their source in
a different temporary directory; changing the cache key to ignore observable
source paths would reintroduce correctness problems. Establish stable owned
adapter artifacts as part of the generation cache, then prove unchanged
header/flag/path semantics before claiming reuse. Scan cost and unconditional
linking also exceed the work permitted by the product no-op objective.

Local raw evidence is `build/perf/btrsmith-diagnostic/run-sr4kp3yz/` and
`build/perf/btrsmith-diagnostic.json`, including exact argv/environment, source
fingerprints, unit reports and logs. Source snapshots are
`38f337ec3d561fd1b1988a9a0e17690816e058b65172b957bcd6ea395265bc79` (compiler/tools)
and `4363d9aff3fad2f9dfc23413f12fca9b8cbab054c3476c966725ebe0711f2dbe`
(product source/build subset). The Nix environment combined the product and
compiler development dependencies, removed only the crashing pinned `btrcc`
derivation, inherited the compiler's native-header SDK variables, and put the
Python 3.13 virtualenv first on PATH. Retain this distinction from the canonical
product shell and rerun the complete product matrix after that shell is repaired.

#### Repeated native-package measurement

The repository's native-package example was also measured with forced split
units (`--unit-lines 1`), two native jobs, Apple Clang 21.0.0 and the same fresh
self-host compiler/Python 3.13 on this host. Each frontend/mode has five fresh
object-cache builds and twenty warm native repeats. All 20 retained sample
executables print the expected result; the 100 native builds succeeded and
before/after observed inputs were unchanged.

| Frontend / mode | Cold median / p95 | Warm native median / p95 |
| --- | --- | --- |
| Reference / dev | 1.025 / 1.052 s | 0.361 / 0.367 s |
| Reference / release | 1.045 / 1.053 s | 0.361 / 0.368 s |
| Self-host / dev | 0.792 / 0.795 s | 0.362 / 0.368 s |
| Self-host / release | 0.797 / 0.804 s | 0.363 / 0.370 s |

Every cold sample compiles two generated C files plus C, C++, Objective-C and
Objective-C++ native units; every warm repeat reuses all six objects and links
once. This fixture has no generated adapters, so it does not contradict the
product's two adapter misses. These are small-workload distributions, not
BTRSmith budget evidence. Reproduce with:

```sh
build/plan-venv/bin/python -m tools.perf examples/native-package/src/Main.btrc \
  --btrcc build/test-btrcc/da4fd10514d564858ed1d3e35d509d21/btrcc \
  --samples 5 --warm-native-runs 4 --unit-lines 1 --jobs 2 \
  --out build/perf/full-native-measurement --json build/perf/full-native-measurement.json
```

Local evidence is `build/perf/full-native-measurement/run-0iqxdebu/`; raw report
provenance records the compiler source fingerprint and exact host/tool inputs.

### M6a retained adapter sources (2026-09-20)

The shared native-plan builder now materializes generated adapters as one
verified source generation when object caching is configured and available.
The generation's identity covers ordered file names, source hashes, language,
standard and ownership policy. Complete directories publish atomically under
the native output directory; concurrent builders verify the winning generation.
Each reuse verifies exact contents and file inventory, rejecting symlinks,
missing files and unexpected neighbors. Corrupt/unavailable generations fall
back to temporary compilation without modifying artifacts another builder may
be reading. Source generations are retained until build-directory cleanup.

Paths remain real inputs to preprocessing and cache validation. Both temporary
and retained sources are one directory below the output parent, preserving
parent-relative quoted headers. Source changes select a new generation; changed
headers still invalidate the affected objects. No source-path normalization or
weakened dependency key is used. Debugger source files survive a cached build.
The native-plan JSON schema and both compilers' emitted adapter text are unchanged.
This is an adapter artifact slice, not whole-program generation or link caching.

Verification: three new executable regressions failed against the prior builder
and passed after retention. The final native-plan/performance suite passes
**85 tests**, including C/C++ header changes, real `__FILE__` output, switching
source generations, concurrent publication, corruption, failed publication,
report aliases and cache metadata denial. Two metadata-denial cases exposed
and then verified fixes to optional-cache failure handling. **11 adapter cases**
also passed with GNU GCC 15.2. The real pugixml owner traversal/copy/lifetime
suite and warm adapter reuse passed **6 cases across both frontends**, including
the existing sanitizer cases. AppKit text editing and scroll composition after
warm adapter reuse passed **4 cases across both frontends**. Evidence:
`build/plan-adapter-final.xml`, `build/plan-adapter-gcc.xml`,
`build/plan-adapter-cxx-frontends.xml` and `build/plan-adapter-appkit-frontends.xml`.
The SDK tests built a fresh Nix-Clang self-host compiler at fingerprint
`98d0fb3fb7d9e43703aa6854896d09f1`; compiler production sources were unchanged.
Pinned Ruff and `git diff --check` pass. Full product/platform gates remain open.

The final builder was compared with the staged pre-retention builder against
the same previously emitted BTRSmith `292deaff` dev plan: Nix Clang 21.1.8,
four jobs, one empty-object-cache build and five warm native repeats per variant.
All 12 builds succeeded, the emitted sources/plan were unchanged, and all
retained adapter contents matched their generation manifest. The SDK/compiler
fixture jobs had finished before timing began; power, thermals and other
background load were uncontrolled.

| Native-only scenario | Before retention | After retention | Compiled / reused / links |
| --- | ---: | ---: | --- |
| Empty object cache, one sample | 13.050 s | 13.034 s | 17 / 0 / 1 in both |
| Warm median, five samples | 5.001 s | 3.297 s | Before: 2 / 15 / 1; after: 0 / 17 / 1 |
| Warm observed range | 4.963–5.103 s | 3.269–3.311 s | Every repeat has the counts above |

Warm native median improved by about **34%**, with both generated adapters now
reused. This excludes transpilation, still scans dependencies and always links;
it does **not** satisfy the product no-op goal. The executable was linked but
not launched or packaged in this timing experiment. Retained source-generation
space is reclaimed by build-directory cleanup; automatic eviction with active
reader protection remains part of broader artifact-generation work.

Raw samples, exact commands, object-cache manifests, source/builder hashes and
the comparison script are under `build/perf/adapter-retention-2026-09-20/`;
the final run is `run-4yri3nc7/results.json`. The earlier `run-nnxz4__s` measured
the retention implementation before the two metadata-denial guards; its warm
medians were 5.050 s / 3.326 s. Keep these runs separate. Both use the diagnostic
Nix environment described above, not the pinned product package.

## Reference compiler artifact generations (2026-09-20)

The reference compiler now uses `CompilerCache.load_artifacts/store_artifacts`
instead of its single-C-text cache port. The value-only application boundary
returns the primary C, ordered secondary units and canonical link plan. Debug
source maps are embedded in those C files. Each generation has a schema/key
manifest, exact file inventory, byte counts and SHA-256 hashes. The existing
`ArtifactPublisher` owns locked publication, rollback and crash recovery;
readers never accept an in-progress transaction. Old single-C cache entries
are ignored. Oversized or unavailable caches do not prevent compilation.

The initial checkpoint enabled non-SDK split/debug and no-DCE generations.
Every hit still resolves current imports; options, debug output paths, unit
prefix/packing, source-map/parse modes, source provenance and compiler/runtime
source identity participate in invalidation. The application checks the stored
link plan against the freshly resolved plan and recovered unit count. Results
with diagnostics were not stored. Native SDK bindings were excluded pending
complete semantic dependency identity, as do profiling, freestanding and
prebuilt-stdlib builds.

Evidence: **187 passed, 8 skipped** in `build/plan-artifact-final.xml`, covering
cache/application/CLI behavior, real split/debug cached executables, source-map
preservation, emission-option changes, import edits/deletion, corruption,
bounded reads, concurrent readers/writers and actual writer-process death.
The existing transaction/storage/reparse suites pass. Eight skips are one XDG
case, four Linux-only emitted-unit cases and three native Windows storage/CRT
cases. The real SDK transitive-header removal regression also passes with the
actual `CompilerCache` injected (`build/plan-artifact-native-header.xml`),
confirming that this change leaves native SDK artifact reuse disabled.

These were correctness results, not a BTRSmith timing claim. See the follow-up
below for SDK identity and diagnostics. Self-host artifact reuse, transactional
CLI output publication, eviction, link reuse and the real product no-op gate
remain open. In particular,
an atomic cache generation does not make separate requested output paths an
atomic publication. Full compiler/bootstrap/C11/platform/product qualification
still has to run on the final implementation tree.

### Native SDK generations and warning preservation

Reference source resolution now returns an authenticated native semantic
fingerprint alongside typed declarations. It reruns the native reader against
current include search paths and package flags on every lookup, hashes the
validated response plus full binding contracts, and records reader executable,
arguments and environment identity in the digest. No raw environment is stored
in the artifact manifest. A missing or changing reader identity disables this
reuse. Fresh resolution covers transitive header/layout changes and newly
shadowing include files; the common native builder still validates preprocessing
and actual compile inputs separately.

Cached native plans restore generated C++/Objective-C adapter units only after
typed validation and exact canonical comparison with the fresh resolved plan.
The initial AppKit integration exposed another gap: successful warnings caused
the generation to be omitted. Artifact schema 2 now includes a checksummed
diagnostics payload and source-space metadata. Hits preserve warning text,
severity and imported-file locations. Failed compilations are not cached.

Evidence before the capacity correction: **288 passed, 8 platform skips** in
`build/plan-sdk-cache-final.xml`; **5 native SDK cases passed** in
`build/plan-sdk-cache-native-final.xml`; **3 real C++/AppKit integration cases
passed** in `build/plan-sdk-cache-adapters-final.xml`. These exercise warm split/
debug executables, transitive headers, include shadowing, binding-contract and
record-layout changes, reader replacement/unavailable identity, generated
adapters and actual text editing/scrolling. CLI tests preserve imported warning
locations through strict/relaxed and debug/plain modes. The two initial AppKit
cache failures remain recorded in `build/plan-sdk-cache-adapters.xml`; the final
cases pass after diagnostic preservation. This is reference-compiler evidence;
it does not qualify a fresh self-host generation cache.

The first complete product probe at
`build/perf/sdk-artifact-cache-2026-09-20/run-t2fcehgl/results.json` compiled local
BTRSmith successfully, but emitted **326,726,292 bytes** (primary, 36 secondary
units and plan), beyond the initial **256 MiB** cache admission limit. That
size independently exposed a capacity defect, but it was not the only reason
the probe could not cache: the measurement script inherited `BTRC_TIMING=1`
from `Perf`, intentionally disabling compiler reuse. The warm recompilation was
deliberately terminated; its `-15` result is a cancellation, not a timing sample
or native build failure. The cold profiled diagnostic took 341.990 s for the reference
compiler and 18.641 s for 39 native units. This is a different frontend/unit
layout from the earlier 17-unit self-host diagnostic; do not compare their times
as before/after performance.

The default cache bound is now **512 MiB**, with a real-file regression that
failed under the old bound and restores an entire large split generation under
the new one. Explicit smaller limits still reject oversized reads. The final
core run has **289 passed, 8 skipped** in
`build/plan-sdk-cache-capacity-final.xml`. The bound remains finite, larger
successful outputs can still forgo caching, and eviction/compression/emission
size work is not complete. A second profiled probe, `run-5q37tfan`, still could
not exercise reuse despite the larger bound; its warm request was also
deliberately cancelled after the inherited profiling setting was identified.
Neither run establishes warm cache behavior. The corrected harness removes
`BTRC_TIMING`, asserts profiling is off, requires a published generation after
the cold compile and checks identical warning output on every warm repeat.

### Reference output preflight

The publication audit reproduced ten CLI overwrite/collision cases involving
primary/secondary C, the link plan, imported BTRC sources, a source symlink,
source hard links, declared native C/headers and package manifests/locks. The
reference CLI now validates the complete requested output set against known
resolved inputs before its first output write. The freestanding runtime seam
also participates, including when it has not yet been created. Native/package
input paths remain owned by `NativeLinkPlan`; `CompilerResult` presents a
value-only input inventory to the CLI. Canonical paths and regular-file identity
cover spelling, symlink and hard-link aliases without quadratic pairwise stats.

**317 passed, 8 skipped** in `build/plan-sdk-cache-preflight-final.xml`, including
the existing cache, CLI, package, transaction and file-I/O suites. The dedicated
file-I/O run has **29 passed** (`build/plan-output-preflight-final.xml`), including
two additional freestanding collisions and a real cache-hit request that must
still preserve an imported source. The ten original failures are retained
in `build/plan-output-alias-before.xml` and `build/plan-output-native-alias-before.xml`.
On the final preflight tree, all **5 SDK cache cases** and **3 C++/AppKit cached
adapter/editing/scrolling cases** also pass, recorded in
`build/plan-sdk-cache-preflight-native.xml` and
`build/plan-sdk-cache-preflight-adapters.xml`.
This preflight is not a filesystem transaction, does not eliminate races after
validation, and inventories known resolved inputs rather than every transitive
SDK include. Multi-file rollback/recovery, cooperating-reader generation checks
and equivalent self-host publication remain required M6a work.

### Unprofiled SDK product reuse, final preflight tree

Raw report and exact diagnostic runner:
`build/perf/sdk-artifact-cache-2026-09-20/run-54rmlp47/{results.json,measure.py}`.
This run explicitly disables `BTRC_TIMING`, requires a published generation
after the cold compile and compares every emitted file plus warning stderr
across five warm repeats. The report confirms unchanged compiler/product input
snapshots and tool identities. It uses local BTRSmith `292deaff`, the combined
Nix diagnostic environment described above, reference dev/debug emission at
40,000 unit lines, Clang `-O0 -g` and four native jobs. The emitted generation
has 37 C units plus two generated adapters and a link plan; its checksummed
cache payloads, including diagnostics, total **326,727,505 bytes**.

| Scenario | Compiler wall | Native wall | Complete compiler + native wall |
| --- | ---: | ---: | ---: |
| One cold build | 376.048 s | 18.471 s | 394.519 s |
| Five warm builds, median | 18.803 s | 5.040 s | 23.912 s |
| Warm observed range | 18.579–19.194 s | 5.031–5.114 s | 23.610–24.275 s |

The complete median is calculated from each paired build, not the sum of
independent stage medians. The runner separately records hashing/report overhead.
All five warm compiler requests are actual cache hits; all five native builds
perform **0 compiles, 39 object reuses and 1 link**. Emitted bytes and all four
warning diagnostics remain identical. Maximum recorded compiler RSS is about
1.70 GiB cold and 682 MiB across warm runs; native subprocess memory is recorded
separately. This is not a `make` no-op, package/install/launch or physical product
test, and does not qualify remote product `5549c261`. The ≤2 s no-op and ≤180 s
reference cold-transpile goals remain open. OS/package caches, thermals and
background load were uncontrolled; targeted tests overlapped part of the cold
run, while the five warm repeats ran after those tests finished.

To choose the next change, a separate cProfile diagnostic executes only fresh
source resolution and key construction with the same product/options. It does
not compile or bypass a native semantic check. Files
`run-54rmlp47/{resolution.prof,resolution.json,profile-resolution.py}` retain the
instrumented evidence: resolution **26.210 s**, including native import
resolution **15.044 s** and import traversal **10.931 s**; **42 subprocess runs**
account for **14.669 s**, and **444 source scans** include **9.663 s** in lexing.
Semantic-key construction is **0.750 s** across 98,607 source-position rows and
444 unique paths; toolchain-key construction is **0.015 s**. Profiling overhead
and a separate shell mean these are attribution evidence, not a decomposition
of the unprofiled 18.803 s median. Prioritize validated import-scan reuse and SDK
process/semantic-resolution cost before speculative key-hash optimization.

### Validated directive-scan reuse

The reference CLI now composes `SourceDirectiveScanner` with a value-only cache
port backed by the existing `CompilerCache`. Each entry stores only ordered
line ranges, keyed by complete normalized source content and the full compiler
fingerprint (including grammar, lexer and parser). It never stores resolved
import paths or directory membership. Checksummed JSON uses the existing
regular-file reader and atomic file publisher; the entry read/write bound is
8 MiB or the configured smaller cache limit. Larger successful scans simply
forgo persistence, without imposing a source or import-count ceiling.

On a hit the scanner reparses each owned fragment through its existing lexer
and import parser, creating fresh typed specs. A fragment requiring preceding
or following multiline-comment context falls back to scanning the entire file.
Invalid ranges, bad checksums, unknown keys, symlinks and unavailable storage
are misses. Lexically malformed input is not stored as an empty successful
scan. CLI `--no-cache` and `--profile` bypass reads and writes. Each invocation
still reads source contents, resolves package visibility and path searches,
enumerates glob membership and runs the native reader.

Evidence: **324 passed, 5 platform skips** in `build/plan-directive-core.xml`,
**4 corpus import checks passed** in `build/plan-directive-corpus-imports.xml`,
**5 native SDK cases passed** in `build/plan-directive-native.xml`, and **3 real
C++/AppKit cached-adapter/editing/scrolling cases passed** in
`build/plan-directive-adapters.xml`. New cases cover all import-spec forms,
multiline/comment context, malformed input, content/toolchain invalidation,
corruption and small/unavailable storage. A real resolver test adds/deletes glob
members, touches unchanged contents, changes an imported file and introduces a
missing dependency while using persisted scans. Explicit CLI bypass is checked
against populated entries.

The alternating BTRSmith resolution diagnostic is retained at
`build/perf/directive-cache-2026-09-20/run-tti9or8r/{results.json,measure.py}`.
After one seeding run it alternates three fresh frontend instances without the
scan cache and three with persisted scans. All seven runs produce identical
resolved source/provenance identity, canonical native plan and native semantic
identity; before/after source and tool snapshots are unchanged.

| Resolution-only metric | Without scan reuse, median | With scan reuse, median |
| --- | ---: | ---: |
| Import traversal/discovery | 2.863 s | 0.587 s |
| Entire resolution, including fresh native reader | 19.223 s | 17.429 s |
| Characters processed by discovery lexing | 4,688,012 | 56,615 |
| Lexer invocations | 444 whole-file scans | 1,743 small directive fragments |

Each run visits the same 444 source paths. The seeded run took 3.223 s in
discovery, including initial cache writes. Baseline discovery ranged
2.825–3.075 s; warm discovery ranged 0.526–0.589 s. These local diagnostics
include uncontrolled load, with targeted tests overlapping some samples;
operation counts and semantic equality establish the avoided work. They are
not new full-build timings or qualification of the ≤2 s product no-op gate.
Fresh SDK-reader work remains the dominant resolution cost. Self-host directive
reuse, cache eviction and the remaining generation/link/publication work remain
open.

### Full build after directive-scan reuse

The completed direct CLI/native-plan diagnostic is retained at
`build/perf/sdk-artifact-cache-2026-09-20/run-r_4fyvuz/{results.json,measure.py}`.
It uses the same local product revision, options and combined Nix environment
as `run-54rmlp47`, with profiling disabled. The report has no failure and its
before/after source/tool snapshots are unchanged.

| Scenario | Compiler wall | Native wall | Paired compiler + native wall |
| --- | ---: | ---: | ---: |
| One cold build | 374.512 s | 20.063 s | 394.575 s |
| Five warm builds, median | 18.650 s | 5.568 s | 24.299 s |
| Warm observed range | 18.411–19.366 s | 5.505–5.888 s | 24.108–24.883 s |

Every warm build hit the artifact cache, reproduced all emitted files and
warning stderr, reused 39 objects, performed zero native compiles and linked
once. The paired median excludes the separately recorded evidence-hash time.
Against the earlier 23.912 s median, this is **not evidence of a full-build
speedup**. Host load, thermal state and OS/package caches remain uncontrolled;
targeted tests overlapped part of the cold run. The alternating resolution
experiment establishes less import scanning, but SDK parsing, native
validation and linking still dominate. This result does not qualify real
`make`, installation, launch or the ≤2 s no-op target.

### Fresh native-header batch extraction

The shared Clang reader now supports independently selected requests against
one fresh translation unit/compile command. Its versioned envelope is described
in `src/language/package-manifest.md`. Every selection owns its own visitor
state, layouts, receiver interfaces and errors. The existing standalone output
and inner semantic schema remain intact. Input may come from a JSON file or
stdin; transport/Clang failures emit no partial response, and a per-request
selection failure has a null document plus its diagnostics.

The real BTRSmith extraction diagnostic is retained at
`build/perf/native-batch-2026-09-20/run-1q5b8573/{results.json,measure.py}`.
It first records all requests made by the actual reference frontend against
local product `292deaff`, then alternates three standalone and three batch
extractions. Grouping compares the complete ordered non-selection arguments:
reader, header, language, standard, target, sysroot, pkg-config dependencies,
include paths, defines and other compile flags. The same 41 requests form 16
groups; one AppKit group contains 24 requests, two other groups contain two
each, and the remaining 13 contain one each. Request IDs, all decoded semantic
documents and errors are checked against standalone extraction.

| Extraction only | Standalone | Batch |
| --- | ---: | ---: |
| Reader process invocations | 41 | 16 |
| Three-run median reader wall time | 15.182 s | 3.442 s |
| Observed reader wall range | 15.149–15.278 s | 3.379–3.500 s |

All semantic documents matched on every run; before/after input and tool
snapshots were unchanged. Timings include subprocess execution/capture but
exclude the separately recorded JSON validation overhead. They are measured
with the combined Nix diagnostic environment and uncontrolled host load; a
self-host compiler build overlapped this diagnostic. The reported reader
binary predates the subsequent stdin option, which has separate equivalence
tests and does not change extraction semantics.

This experiment qualified the shared-reader mechanism before frontend
integration. It is not a whole-build result, a make/package/product
qualification or evidence that the ≤2 s no-op budget is met. The subsequent
consumer integration is recorded separately below.

Verification on the final reader: **170 native-header tests passed, no skips**
(`build/plan-native-batch-all-final.xml`), including existing C/Objective-C/C++
extraction and both compiler decoders. New tests cover independent target
layouts, record-path selections, inherited Objective-C receivers, C++ owner
isolation, a failed request between successful siblings, malformed envelopes,
file/stdin equivalence and no partial output on Clang failure. The standalone
pugixml fixture initially failed to locate `<exception>`; it now obtains the
configured driver's C++ include paths through the same discovery used by
production imports. No test was skipped or weakened to accommodate that error.

The self-host compiler used for decoder tests was rebuilt from the current
compiler sources before reuse in the combined Nix environment. Architecture/
hosted-ABI checks passed **54 tests** (`build/plan-native-batch-structure.xml`);
the shared reader builds with `-Wall -Wextra -Werror`, and generated-source,
Ruff and diff hygiene checks pass. These focused results do not replace the
full test/bootstrap/C11/devex/platform matrix required to complete the plan.

### Native batching in both compiler consumers

The existing Python and btrc native-import owners now construct the same
standalone command per binding, group complete ordered non-selection arguments,
validate response IDs/order/schema and project results in original binding order.
Selection errors retain the original module attribution and cannot borrow a
sibling's permissions. The reference cache hashes the validated typed document
instead of its JSON formatting, along with binding, command, reader and
environment identity. No persistent SDK cache was introduced.

Self-host requests carry stdin and per-request output/time budgets. A group
retains 8 MiB and 60 seconds per member; groups above 255 split into multiple
processes because the capture API uses a signed 32-bit budget. The 256-binding
case verifies partitioning without introducing an import-count ceiling. A
9 MiB whitespace-prefixed response initially timed out: the escaped-NUL scan
recomputed `strlen` in its loop and allocated substrings at escapes. It now
measures source length once and compares the bounded escape bytes directly.
This repairs the existing validator rather than raising the test timeout.
The rebuilt compiler passes **38 consumer/codec checks**
(`build/plan-batch-consumers-both-final.xml`). The formerly timing-out large
response case completed in 0.266 s for each frontend in this test run, without
raising its 90-second harness timeout; this is regression evidence, not a
controlled performance benchmark. The 256-binding test passes on both paths.

Broader qualification (`build/plan-batch-native-integration.xml`) passed all
**170 native-reader tests, 21 C++ ownership tests and 16 AppKit field/scroll
tests**, plus 18 selected cross-binding/record tests. Six additional record/
shared-declaration checks initially failed at native linking: their helper
combined an Xcode 27 SDK with Nix's older linker for non-sanitized builds.
The helper now selects the Apple toolchain consistently with its SDK discovery.
All **8 affected parameter variants** then passed
(`build/plan-batch-native-integration-repair.xml`), including all six failures
and the two sanitizer variants. No implementation failure was hidden by a skip,
and no test expectation was weakened. These runs use the fresh compiler under
`build/test-btrcc/195f752ec20f523d33df53e6f67065f6/`. Generated-source, Ruff,
formatter and diff checks also pass; the complete goal matrix remains open.

The integrated reference-resolution diagnostic is retained at
`build/perf/native-batch-consumers-2026-09-20/run-fobcg6t5/{results.json,resolve.py}`.
It runs the actual frontend and directive cache, changing only whether the
native importer executes the complete commands singly or in compatible groups.
All three alternating pairs resolve the same 444 files and 41 selections with
identical resolved source, canonical native plan and native cache identity.

| Complete frontend resolution only | Standalone | Batch |
| --- | ---: | ---: |
| Reader processes | 41 | 16 |
| Three-run median wall time | 16.548 s | 4.405 s |
| Observed wall range | 16.216–16.733 s | 4.365–4.453 s |

Input/tool snapshots are checked before and after. Host load is uncontrolled
and a self-host rebuild overlapped this diagnostic. These measurements predate
the final process-budget/validator repair and do not time self-host resolution,
later compiler phases, native compilation, linking, make, packaging or launch.
The earlier 24.299 s warm full-build median is the pre-integration baseline.

### Complete product builds with consumer batching

The unprofiled direct CLI/native-plan diagnostic completed at
`build/perf/native-batch-build-2026-09-20/run-4ckexc66/{results.json,full-build.py}`.
It uses local BTRSmith `292deaff`, the current compiler sources and the fresh
self-host binary above in the combined product/compiler Nix environment. The
product shell's pinned compiler is excluded so it uses this working tree;
this is a diagnostic environment, not qualification of the product's normal
packaged toolchain. No other compiler/test workload was deliberately run beside
this measurement. Power, thermal state and OS caches remain uncontrolled.

| Scenario | Compiler wall | Native wall | Paired wall |
| --- | ---: | ---: | ---: |
| Reference cold, one sample | 334.533 s | 19.032 s | 353.565 s |
| Reference warm, five-run median | 5.331 s | 5.080 s | 10.404 s |
| Reference warm observed range | 5.296–5.443 s | 5.069–5.114 s | 10.376–10.557 s |
| Self-host cold, one sample | 123.826 s | 13.629 s | 137.455 s |

Paired values sum the compiler and native measurements for each run; the
paired median is not the sum of the separate stage medians. Separately recorded
evidence hashing adds about 0.22 s per warm pair and is excluded from the table.
All five warm reference runs hit the compiler cache, reproduced every emitted
primary/secondary C file and link plan byte-for-byte, and preserved warning
stderr. They reused all **39 native objects**, compiled none and linked once.
The cold self-host path compiled **17 units** and linked once. Both produced
executables; neither executable was launched by this diagnostic.

The reference emitted generation plus link plan totals **326,726,292 bytes**;
the reference executable is **20,932,440 bytes**, versus **18,938,536 bytes** for
self-host. These different unit/size totals are recorded rather than treated
as byte parity between compilers. Final source/tool snapshots are unchanged
and the report records no failure. The raw directory retains commands, native
unit reports, diagnostics, hashes, runner and provenance.

The observed warm median is lower than the earlier 24.299 s measurement;
the alternating resolution experiment supplies separate evidence for the
avoided SDK work. Do not attribute every cold-build difference to batching.
Neither the **≤2 s no-op** nor the cold reference/self-host compiler targets
are met, and real make/touch/edit, release, install/launch and remote-main
qualification remain open. This run does not establish self-host cache reuse.

For the next optimization, inspect validated lookup costs first. In warm-3,
native internal wall is **5.012 s**, including **0.286 s link time**; summed
per-unit dependency scans are **10.236 s** and cache validation **5.975 s**.
Those sums overlap across four workers and are not wall-time components to add
together. Link elision is still required, but most remaining native warm wall
lies in scan/validation work. Preserve mutable-header/search-path correctness
and same-path compiler replacement checks in any faster reuse strategy.

### Native lookup profile and rejected immutable-file memoization

The native-only diagnostic at
`build/perf/native-lookup-2026-09-20/run-adkjojmn/{results.json,profile.py}`
reuses the actual 39-unit reference product generation above. A fresh object
cache is seeded, followed by three uninstrumented warm builds and one instrumented
warm build. The uninstrumented median is **5.172 s**; the instrumented build is
5.391 s. All warm builds reuse all 39 objects, compile none and link once.
This excludes retranspilation and is not a product no-op timing.

| Instrumented work | Calls | Summed wall time |
| --- | ---: | ---: |
| Fresh preprocessing/dependency scans | 39 | 10.632 s |
| Compiler version probes | 39 | 2.564 s |
| File digests | 20,296 | 2.454 s |
| pkg-config queries | 2 | 0.027 s |
| Link | 1 | 0.301 s |

These are overlapping per-operation durations across four workers, not additive
wall components. Hashing reads **1,077,641,298 bytes** across 2,079 distinct paths.
Nix store files account for 19,731 reads, 280,378,355 bytes and 1.791 s of that
summed time. Preprocessed files account for another 426,985,454 bytes; other
inputs, mainly generated C, account for 326,875,049 bytes. No native compile is
hidden in the warm validation figures. Source/tool identities stayed stable.

A prototype shared read-only Nix store file digests within one build, resolving
symlinks and checking identity, mode, size, mtime and ctime on every reuse. It
left mutable files and preprocessing fresh. Three alternating baseline/shared
pairs retained identical object-cache keys and 39/39 hits, but the native wall
median changed only **5.140 s → 5.124 s** (0.3%, within the observed timing
variation). The instrumented shared run reduced reads to **2,924** and digest
time to **0.849 s**, without a useful total-build improvement. The experiment
does not isolate the remaining metadata/resolution overhead; fewer digest calls
alone did not improve the measured build enough to retain this complexity.

The prototype was **removed**. The comparison and exact experimental patch are
retained at `build/perf/native-lookup-2026-09-20/run-3cv8mm4i/` and
`build/perf/native-lookup-2026-09-20/immutable-digest-experiment.patch`.
Do not repeat this optimization without new evidence. Further lookup work must
address the complete scan/validation path while retaining include-shadowing,
mutable-header and toolchain-replacement correctness. The 62-test native-plan
baseline passes. These measurements precede the subsequent process text-boundary
repair and do not establish a new full-build result.

### Native transport and output-publication correctness checkpoints

A malformed-reader regression reproduced self-host acceptance of a valid JSON
document followed by a raw NUL and trailing bytes, for both standalone and batch
requests. The reference frontend rejected both. `ExecResult` now preserves the
number of bytes captured on stdout/stderr, including through `UnixShell`;
`FeNativeHeaderProcess` compares that count with the selected successful text
stream before handing it to the semantic decoder. This rejects truncation at
the process boundary, separately from the codec's escaped-NUL validation.

The fresh compiler at
`build/test-btrcc/0291e074b3aa18691076bbc8c90b5033/btrcc` passes **40 consumer
cases** (`build/plan-native-nul-final.xml`). Additional results are **31 reference
process/security/descriptor cases**, **7 self-host process corpus cases**,
**6 real C++ owner/AppKit field cases**, and **62 structure/ABI/naming cases**.
Their reports are `build/plan-process-bytes-reference.xml`,
`build/plan-process-bytes-selfhost.xml`, `build/plan-native-nul-sdk.xml` and
`build/plan-process-bytes-structure.xml`. The stdlib symbol catalog was
regenerated and its canonical check passes. These checks do not repeat the
full product timing, bootstrap, physical UI/audio or release gates.

Subsequent reference CLI work reproduced mixed output after an injected primary
or secondary staging failure: the new link plan, and sometimes the primary C,
had already replaced the previous generation. `CompilerFileIO.write_outputs`
now stages all regular C/plan payloads before publishing them in order, with the
link plan last. Stage failures clean temporary files and preserve all prior
destinations, including when outputs span directories. Single-output device,
symlink and permission behavior remains covered by the existing I/O tests.

`build/plan-publication-staging-final.xml` records **122 passed / 4 skipped**
across source I/O, CLI, emitted units, compiler API and publication durability.
The skips require a Linux C toolchain; reference cached split generations do
compile and execute on this host in both debug modes. The change does not yet
provide multi-file atomic replacement, crash recovery or writer serialization;
the freestanding seam also remains separately published. Complete M6a through
the existing publication owner rather than adding a second transaction model.
No speedup is claimed for this correctness change.

The subsequent shared publication audit found a rollback defect:
`ArtifactPublisher._restore_backup` moved the last good backup back into place,
then deleted it if flushing that restored artifact failed. At that point the
backup name was already gone. All three injected cases (directory, payload and
validator) reproduced data loss. Recovery now preserves the restored copy and
pending journal; a fresh owner can retry and restore the complete prior
generation before validating another candidate. The diagnostic baseline is
`build/plan-publication-rollback-baseline.xml` (three expected failures).

Process-crash coverage now exits at five actual filesystem boundaries: backup,
first payload replacement, final validator publication, committed journal and
backup cleanup. Retry preserves the prior generation before commit and the new
complete generation after commit. Together with rollback-flush failures and
existing reader/concurrent-writer checks, the focused recovery module passes
11 tests (`build/plan-publication-recovery-boundaries.xml`). This proves the
existing archive/bundle transaction's tested failure paths, not power-loss
behavior on every filesystem or complete CLI generation transactions.
The broader bundle/security/archive/source-I/O suite passes **130 tests** with
**one native-Windows stat-mode skip** (`build/plan-publication-recovery-final.xml`);
the structure/analyzer/lowering checks pass **92 tests**
(`build/plan-publication-recovery-structure.xml`). Ruff, formatting,
generated-source and diff checks also pass. The full final matrix remains open.

### Publication across output directories

`ArtifactPublisher` now coordinates an ordered inventory across multiple output
directories. Every publisher takes the same directory locks in canonical order,
then its existing named lock. Stages and backups stay beside each destination;
callers supply candidates on the destination filesystem. Participant markers are
durable before the coordinator journal and before any public payload changes.
The coordinator remains the only commit authority. Recovery validates each
marker against the caller's complete inventory rather than following arbitrary
paths from a journal. Cross-directory records use schema 2; existing single-
directory schema-1 recovery remains supported.

A publisher that encounters another pending journal stops before staging or
replacing its payloads, including when its output set touches only a participant
directory. This is deliberately directory-wide serialization. Recovery retires
the coordinator only after payload restoration/commit cleanup has been flushed,
then removes participant markers. A crash between those operations leaves
markers that block other writers; retry cleans them without replaying rollback.
Control-path outputs and nested directory/file destinations are rejected before
locking. The journal read bound now derives from the expected inventory, with
the existing small-document allowance retained.

The initial four cross-directory checks failed against the former one-directory
restriction (`build/plan-publication-directories-baseline.xml`). New real-file
tests cover successful publication, replacement failure and rollback, concurrent
process writers with reversed coordinator order, and actual process exit after
participant creation, payload replacement, commit, coordinator retirement and
rollback retirement. They check complete old/new generations after retry and
that a writer outside the coordinator directory cannot overwrite pending work.
A 260-artifact inventory exceeds 64 KiB and publishes successfully. The focused
module passes 24 tests (`build/plan-publication-directories-boundaries.xml`).
The final bundle/security/archive/source-I/O run passes **143 tests** with one
native-Windows stat-mode skip (`build/plan-publication-directories-final.xml`),
and structure/analyzer/lowering checks pass **92 tests**
(`build/plan-publication-directories-structure.xml`). Ruff, formatting,
generated-source and diff checks pass on this checkpoint.

This was the shared transaction foundation, not completed compiler integration.
Retry at this checkpoint required the same ordered output inventory; the
changing-layout support below removes that publisher restriction. A compiler-owned
stable generation identity must still discover and validate the previous output
inventory before the CLI adopts it; native-plan readers must also observe the
publication protocol. Existing direct readers are not promised an atomic snapshot
of multiple paths. Freestanding create-if-absent behavior and device output
contracts remain part of that integration. Tests assert destination-local
renames, but do not claim physical power-loss or separate-volume qualification.
No build-latency improvement is claimed.

### Explicit secondary-output inventory

A real separate-directory CLI/cache test reproduced a missing-input build:
`--emit-units` wrote and restored the requested secondary files, but the native
builder derived different filenames from the primary C path. The baseline is
`build/plan-explicit-units-baseline.xml`. Both compilers now write schema 4 with
an ordered array of absolute secondary paths; the builder retains schema-3
count-based input for older compiler output. Generated adapters remain embedded
in the plan, and unsplit output retains schema 1/2.

The output naming owner resolves the destination directory without following
the final output file. It first appends the unit suffix so prefixes ending in
`/`, `.` or `..` retain their filename meaning. A follow-up test reproduced
self-host plans changing between first and second writes through a symlinked
directory (`build/plan-explicit-unit-paths-baseline.xml`); resolving the parent
consistently removes that dependence on output existence. Tests also cover
parent traversal through a symlink. Generated debug resets use these actual
secondary names, including when the primary output goes to stdout.

Reference cache restoration validates the complete ordered secondary inventory
against current options; changed paths, reordered entries and damaged counts
cannot restore a stale plan. The native reader validates schema, regular-file
paths and duplicate/hardlink aliases before invoking tools. Its secondary list
does not have schema 3's 4096-unit ceiling; the existing total plan-byte bound
still applies. Real build tests cover legacy/new schemas, generated adapters,
different builder working directories, separate prefixes and cached restoration.

Final qualification on the frozen source tree passes **426 tests** with **5
skips** (`build/plan-output-inventory-qualified.xml`), covering both-frontends
emitted/native plans, cache invalidation/security, compiler API, CLI/source I/O
and performance-tool reporting. Four cases require a Linux C toolchain; the
fifth checks XDG cache placement, which is not used on macOS. Real native builds
and cached split execution pass on this macOS runner. The fresh self-host compiler is
`build/test-btrcc/b3b63f1a4c01d740abb1d17ee66ec6c5/btrcc`; its fingerprint was
rechecked against current sources after the run. Architecture checks pass
**92 tests** (`build/plan-output-inventory-structure.xml`). Ruff, formatting,
generated-source, local documentation-link and diff checks pass. The full
bootstrap/C11/platform/product qualification matrix remains open.

This is an inventory prerequisite for M6a, not a complete generation protocol.
Primary/header/manifest ownership, changed-inventory recovery, obsolete output
retirement and cooperating readers remain open. Consumer plan readers must be
upgraded alongside the compiler; no new build-latency result is claimed here.

### Changing publication layouts and explicit retirement

`ArtifactPublisher.publish` now accepts an optional `previous_inventory` of
`PublicationTarget` values, independent of candidate files. The caller supplies
these authorized destinations and their expected present/absent kinds; recovery
does not discover permission to modify files by following journal paths. The
first destination remains the stable publication anchor. The publisher locks
the union of both layouts' directories in canonical order and retains every
lock through recovery, candidate validation, publication and cleanup. A real
process competitor proves that a directory used only by the prior layout stays
locked during the new publication.

Before changing files, surviving coordinator and participant journals must all
match one supplied layout. This also supports retrying a transition after the
interrupted call had already recovered the old layout and started the new one.
The transition regression initially rejected the new-layout journal in all
three crash cases (`build/plan-publication-transition-baseline.xml`). Matching
either independently supplied inventory repairs that case without accepting
mixed participant records or arbitrary destinations. Both layouts' reserved
control paths and nested destinations are checked before recovery can remove
private stages or backups.

An artifact with no staged candidate requests retirement of a regular file and
must supply its prior SHA-256 digest. That digest belongs to the caller's owned
generation: hashing the current file and then requesting its deletion would
discard the ownership protection. The publisher checks it after replacement
policy validation, while locks are held, before backing up any public output.
Changed contents or a substituted symlink reject the publication. Already-absent
files need no candidate. Omitting a target from the new layout never implicitly
deletes it, and the anchor and final validator cannot be retirements.

Retirement uses the existing destination-local backup, commit and rollback
protocol. Before commit, recovery restores removed files along with the old
payloads and validator. After commit it verifies their absence before removing
backups. A user file that reappears at a retired path is preserved; recovery
reports a conflict and retains its journal rather than deleting the new file.
Write-only recovery journals retain schema 1/2. Recovery schema 3 adds explicit
boolean absence records and absolute target paths; it is distinct from the
native link-plan schema. Duplicate JSON fields, numeric substitutes for boolean
kinds, invalid state values and redirected paths fail validation before recovery
mutation. Three malformed-metadata regressions first failed at
`build/plan-publication-metadata-baseline.xml`.

Real process-exit tests cover retirement, payload and validator replacement,
commit and coordinator retirement, then retry with a different inventory. Layout
tests change output counts to 0/1/4 units and move directories. Additional cases
cover prior-only lock ownership, modified/recreated files, symlink substitution,
mixed journals, old control-path collisions and replacement-policy ordering.

The final durability/bundle/security/archive/source-I/O/cache/compiler-API run
passes **225 tests** with **one native-Windows stat-mode skip**
(`build/plan-changing-publication-qualified.xml`), including **58 durability
cases**. Architecture/analyzer/lowering checks pass **92 tests**
(`build/plan-changing-publication-structure.xml`). Ruff, formatting,
generated-source, local documentation-link and diff checks pass. The compiler
API structure assertion now explicitly requires the typed previous-inventory
argument; existing dependency-boundary checks remain intact.

This completes the shared publisher capability, not compiler generation
integration. The ownership implementation below builds on this protocol;
direct CLI publication was still per-file at this checkpoint, and the full
bootstrap/C11/platform/product qualification matrix remains open. No performance improvement or
physical power-loss guarantee is claimed by these process-crash tests.

### Persistent compiler generation ownership

The reference artifact layer now provides `CompilerGenerationPublisher`,
alongside compiler output storage in `artifacts/cache.py`. Its caller supplies
already staged regular files with canonical, authorized destinations and their
roles: primary C, secondary C, link plan or an owned freestanding header.
Ownership records store the ordered paths, SHA-256 contents and file modes.
The following reference CLI integration now invokes this artifact-layer API;
self-host CLI integration remains open.

Each primary output has one stable identity derived from its canonical path.
A private state entry holds two distinct records:

- `intent.json` is the independently owned inventory of the attempt about to
  run, including explicit retirements. It is durably written before entering
  publication and retained through exceptions or process exit.
- `committed.json` is the final validator in the existing multi-directory
  transaction. Rolling back restores the previous ownership set; committing
  retains the new one. Candidate content and modes are checked again under
  the publication locks before public files change.

A per-primary owner lock covers recovery, reading the committed state,
preparing the next inventory, publication and intent cleanup. The shared
publisher's new recovery-only operation finishes the recorded attempt before
its authority can be replaced. Thus a third requested layout can follow an
interrupted second layout even when both differ from the first successful
one. Obsolete paths are derived from committed ownership and retired using
those recorded hashes, preserving user-modified files. Caller-supplied
validation runs before the final content/mode check, so a validator cannot
silently publish bytes inconsistent with the ownership record.

The caller must provision a **private, durable state directory outside
untrusted source trees**. This directory is not an evictable build cache.
POSIX user ownership and private modes are checked; records reject links,
hard-link aliases, duplicate JSON fields, malformed schemas and noncanonical
paths. A redirected prior parent is rejected. Windows ACL provisioning and
native Windows qualification remain integration prerequisites. These checks
do not claim protection against an adversary controlling the same user or
close every parent-directory replacement race.

Missing recovery authority is an error, not permission to follow paths from
an output journal. Losing the state root requires explicit recovery work;
the owner does not guess which user files it may delete. The record byte
budget defaults to 64 MiB and is configurable; no fixed secondary-unit count
is imposed. Cache storage's best-effort parent flush is insufficient here:
an explicit `ArtifactStorage` directory barrier must succeed before the
publisher is entered. The failed-barrier baseline is
`build/plan-generation-intent-baseline.xml` (one expected failure before the
barrier was added).

Process-exit fixtures cover prepared intent, retirement backup, primary
replacement, final ownership replacement, commit and coordinator retirement.
Fresh owners recover the correct old/new ownership set and then publish a
third layout with obsolete files removed. Additional cases cover automatic
recovery on publish, two competing processes, changed retirement contents,
changed candidate bytes, malformed/missing authority, private-state checks,
redirected directories, primary-only output and optional role retirement.
The special-file audit also reproduced a blocked process when a FIFO replaced
the committed record (`build/plan-generation-fifo-baseline.xml`). Shared
regular-file opening now uses nonblocking admission before checking the opened
file's type and identity; the FIFO is rejected without waiting for a writer.
No physical power-loss or separate-volume durability claim follows from
these tests.

Final qualification passes **245 tests with one native-Windows stat-mode
skip**, including **78 publication durability cases**
(`build/plan-generation-owner-final.xml`). The architecture/analyzer/lowering
suite passes **92 tests** (`build/plan-generation-owner-final-structure.xml`).
Ruff lint/format, canonical generated-source checks, local documentation links
and diff whitespace checks pass. This is artifact-layer qualification; no
fresh self-host bootstrap, installed-product run or speed improvement is
claimed for this change.

The reference integration below composes this owner through an application
port and `main.py`. Add cooperating readers and self-host
ownership/publication parity using the same record/protocol, then replace
BTRSmith's pre-build output deletion. A private ownership validator is not a
public link-plan snapshot protocol; ordinary readers still need coordination.
Rehashing large staged generations also needs end-to-end measurement under
M6a's unchanged performance budgets.

### Reference CLI generation integration

`main.py` now supplies a lazy `CompilerOutputPublication` through the
application's `CompilerOutputPublicationPort` to `CompilerFileIO`. The CLI
continues staging all payloads before publication. Regular primary C,
secondary C and the requested native link plan then enter the shared generation
transaction. CLI code imports only application contracts; artifact code has
no application or frontend dependency. An unconfigured library `CompilerFileIO`
retains its per-file write behavior, while the real process entry point always
composes the generation adapter.

`PreparedCompilerOutputs` captures requested path resolution, output-parent
identities and both names and file identities of compiler inputs. It checks
each target before staging, and its generation guard checks all proposed public
destinations, including retirements. The guard runs **before recovery mutates
an interrupted inventory**, before a new intent is written, and in the staged
publication policy while transaction locks are held. An old output used as a
current input cannot be deleted merely because a prior generation owned it.
Changed symlink resolution or directory identity rejects publication. These
checks detect observed changes; eliminating the final check-to-filesystem-
mutation race still requires stronger path/handle anchoring.

The regular-file transaction preserves existing symlink targets and permissions,
rolls back replacement failures, and discovers obsolete units/plans from durable
ownership instead of scanning filename globs. A fresh compiler invocation can
recover a crashed second output layout and publish a third. Changing from split
output with a plan to primary-only output retires unchanged old units and the
old plan. Modified retirement contents continue to reject the build.

Recovery state is required even for `--no-cache`; that option disables
compilation reuse, not failure recovery. `BTRC_STATE_DIR` selects an absolute
private root. Defaults are `~/Library/Application Support/btrc/generations`
on macOS, `$LOCALAPPDATA/btrc/generations` on Windows, and
`${XDG_STATE_HOME:-~/.local/state}/btrc/generations` on Linux. State creation
is lazy: inspection-only requests and device-only writes do not create it.
Tests isolate it separately from `BTRC_CACHE_DIR`. This state must not be
silently evicted with ordinary caches or reconstructed from untrusted journals.

New roots are created with mode `0700`. The repository requires Python 3.13,
whose Windows implementation creates such directories with access restricted
to the current user and administrators. Existing Windows ACL validation and
live Windows qualification remain open; a POSIX mode check is not evidence
about a Windows DACL. [Python directory creation](https://docs.python.org/3.13/library/os.html#os.mkdir).

Freestanding runtime headers retain their existing separate create-if-absent
operation: existing custom headers and symlinks are preserved, and the CLI
does not adopt them into generation ownership. Requests containing a device
retain direct I/O semantics. These paths have regression coverage but are not
claimed as one recoverable file generation. Coordinating the freestanding
seam, device/mixed-output requests and their failure outcomes remains required
for M6a, alongside self-host parity, cooperating readers and BTRSmith make
integration. A build process opening arbitrary output files directly still
has no snapshot guarantee during publication.

Real CLI fixtures terminate compiler processes after primary publication,
link-plan publication and durable commit, then retry with changed unit paths.
They also inject a replacement failure after the primary has changed, check
full C/unit/plan rollback, shrink a generation, retarget an output symlink after
staging, protect both retired and interrupted files newly used as inputs, and
preserve output permissions and new/custom freestanding seams. The first
integration run caught duplicate requested paths being collapsed during path
freezing (two existing freestanding-alias regressions); validation now retains
the original sequence before constructing the lookup. Full source-alias checks
are performed at generation boundaries rather than repeated quadratically for
each staged unit.

A further regression caught an ownership transition at the freestanding seam:
an earlier invocation had used `btrc_rt.h` as its link-plan destination, then a
freestanding invocation needed to preserve that existing path. Retirement must
not remove it and thereby turn create-if-absent into replacement. The failed
baseline is `build/plan-cli-seam-retirement-baseline.xml`. The publication guard
now includes all reserved outputs excluded from the current transaction, so
this conflict rejects the build before mutation and preserves both prior C and
header bytes. The same guard applies before recovering an interrupted attempt.

Final qualification on frozen production sources:

- **282 passed, 1 skipped** across source I/O, real CLI, compiler API,
  publication durability, cache security and invalidation
  (`build/plan-cli-generation-final.xml`). The skip is XDG cache placement,
  which this macOS host does not use.
- **235 passed, 4 skipped** across emitted units, native packages, native-plan
  building, CLI flags and performance-tool contracts, using a fresh self-host
  compiler (`build/plan-cli-generation-final-product.xml`). Four split/debug
  cases require a Linux C toolchain; applicable native executable builds pass
  through both frontends on this host.
- **175 passed, 1 skipped** across architecture/analyzer/lowering and bundle/
  stdlib artifact checks (`build/plan-cli-generation-final-structure.xml`).
  The skip requires native Windows stat modes.
- Ruff lint/format, canonical generated-source checks, local documentation
  links and both staged/unstaged diff whitespace checks pass.

These are **692 passes and 6 visible skips**, not the full release matrix or
a build-speed improvement. The final self-host fingerprint is
`6b83fe1ee7598a4a00033e2d469d2e3e`; earlier fingerprints from intermediate CLI
changes are superseded. Bootstrap fixed-point, full C11 optimization/compiler
matrix, extension, installed-product and physical-platform gates remain open.


### Cooperating native-build reader checkpoint

`NativePlanReader.generation` and `ArtifactPublisher.read_directories` now
coordinate the native builder with the reference CLI's regular-file publisher.
The reader first locks the primary and plan directories, discovers secondary
paths, releases all locks and reacquires the expanded set in the publisher's
sorted order. It rereads the plan under that set; if a concurrent replacement
moved secondary files again, discovery repeats. Eight unsuccessful discovery
attempts produce an explicit retry diagnostic rather than an unchecked build.
The final directory locks stay held through dependency/cache probes, C
compilation, linking and successful report publication. Generated files keep
their real paths, preserving include lookup, debug paths and cache identity.

Readers reject any pending publication journal in their input directories
before invoking build tools. They do not parse a public journal into recovery
authority or acquire a generation-owner lock while holding directory locks.
The independently authorized compiler owner performs recovery, after which the
build can be retried. Participant markers still reject reads when only cleanup
remains. Journals and private ownership records retain their existing schemas.
Executable/report destinations cannot replace publication control files or
alias their plan/source inputs. Opening a substituted FIFO plan is nonblocking
and rejects it as a non-regular file.

The generated-input directories require usable publication locks, which remain
on disk. Builds sharing directories currently serialize, and cooperating
publishers wait for compilation/link to finish. Read-only distributions of
generated outputs still need a provisioned coordination or immutable-snapshot
policy; do not silently omit a lock when its creation fails. External native
package sources and SDK headers are outside this compiler-output generation,
so the reader does not create locks in their read-only package-store locations.
This is not protection against arbitrary edits to headers, direct/self-host
writes or adversarial parent-directory replacement. Freestanding seams,
self-host transaction parity, the remaining direct consumers and BTRSmith's
pre-build deletions still need integration. No new build-speed claim follows.

The Nix adapter now includes the shared publication module in its narrow source
closure. Its launcher uses only that closure on `PYTHONPATH` and Python's `-P`
mode: a working directory or inherited `PYTHONPATH` must not substitute another
`tools`/`src` package. The first installed-command probe exposed checkout
shadowing and hit this host's known Python 3.14/libffi assertion; the corrected
launcher successfully runs the packaged two-module adapter from the checkout,
including with the checkout explicitly present in the caller's `PYTHONPATH`.

Evidence on the final sources:

- **97 native-builder tests pass** (`build/plan-native-reader-final.xml`),
  including actual writer process exits after primary/plan publication and
  durable commit; rejection before recovery and successful execution after it;
  concurrent publication during cached and uncached compilation/link; a writer
  targeting only a secondary directory; failed-build lock release; moved unit
  directories between discovery passes; reserved output names; FIFO rejection;
  both-frontends plan emission and the standalone source closure.
- **233 boundary tests pass, 1 skips**
  (`build/plan-native-reader-boundaries.xml`): publication durability, source I/O,
  performance-tool, bundle and stdlib artifact tests. The skip requires native
  Windows staging modes. **98 architecture/compiler-API tests pass**
  (`build/plan-native-reader-architecture.xml`). These modules are disjoint:
  **428 passes / 1 visible skip**, not the full release matrix.
- `nix build .#btrc-native-plan --no-link --print-out-paths` succeeds. Installed
  package `/nix/store/akncq1g1lynzcf8nd389l37zc50bk24j-btrc-native-plan` builds and
  runs a two-unit C executable, then rejects a pending secondary journal before
  tool discovery and preserves the executable. Evidence:
  `build/plan-native-reader-package-jkmeq849/qualification.json`. Both packaged
  Python modules were compared byte-for-byte with the working tree.
- The fresh self-host fixture fingerprint is
  `be6389371fb51ab1dd4007e38e0aa439`. Ruff lint/format, canonical generated-source
  checks and diff whitespace checks pass. Full bootstrap fixed-point, full C11,
  extension, installed BTRSmith, native Windows and physical-platform gates
  remain open.

The baseline was **156 passes** (`build/plan-native-reader-baseline.xml`). Three
new pending-journal cases failed before integration
(`build/plan-native-reader-red.xml`); six reserved-control destination cases
failed before their guard (`build/plan-native-reader-control-red.xml`). The
first integrated run had **83 passes / 4 failures**, all from cleanup assertions
that did not account for persistent directory lock files; those assertions now
still reject temporary artifacts while allowing the exact lock filename.
The subsequent qualified and final native-builder runs each pass all 97 cases.

## Self-host output inventory and preflight checkpoint (September 20)

The self-host CLI now validates its complete requested output inventory before
writing the link plan, secondary C units or primary C. `FeSourceFileReader`
records successful reads, including grammar, source/import/include files,
manifest and stdlib metadata. `FeNativeLinkPlan` contributes declared native
sources/headers, selected binding headers and package manifest/lock paths.
`BtrccCompilationResult` carries those inputs and exact secondary destinations;
the CLI no longer derives unit filenames independently of the pipeline.

`BtrccOutputPaths` resolves names and uses metadata-only filesystem snapshots
to reject direct, symlink and hardlink input aliases, aliases between outputs,
nonregular destinations and reserved publication-control filenames. Missing
leaves use the resolved existing parent. A FIFO is rejected without opening it.
The exclusion set reserves package lock names even when initially absent;
package resolution may create its own valid lock before output validation.

This repairs a reproduced root-source overwrite, but remains preflight only.
At this checkpoint, publication still wrote the plan first, then units, then
primary using separate atomic file replacements, without directory coordination,
a generation journal, crash rollback or obsolete-file retirement. The following
checkpoint adds shared directory locking; complete generation recovery and the
reference publisher's output-symlink/mode behavior remain open. Identities
are captured before publication rather than from the original read handles;
final path races, cumulative reader inventory on library reuse and native
Windows identity/reparse behavior remain unqualified. Undeclared transitive C
headers are outside this known-input inventory. Stdout-only operation bypasses
output preflight; explicit nonregular output files are rejected.

Evidence on a fresh self-host compiler:

- Baseline: **22 passed / 4 skipped**
  (`build/plan-selfhost-output-baseline.xml`). The direct-primary/root case
  then reproduced input destruction (`build/plan-selfhost-output-alias-red.xml`).
- Final: **271 passed / 4 skipped**
  (`build/plan-selfhost-output-qualified.xml`): all **57 CLI cases**, emitted
  units, native packages and native-plan builds. The four skips require Linux
  C/debug toolchain coverage. Cases preserve prior outputs across input/output
  aliases, secondary collisions, invalid directories, control names and FIFOs.
- **98 architecture/naming checks passed**
  (`build/plan-selfhost-output-structure.xml`), with canonical generated-source,
  lint, formatting and whitespace checks. The compiler fingerprint is
  `dc3c2c672db4e992326908a06d38583b`.

An initial build caught a boolean-expression type error, fixed before the
successful build. An expanded test run then found six fixture errors: five
expected multiple units from one indivisible source-module run, and one
incorrectly assumed package resolution would not create its lock. The final
fixtures use distinct source modules and require an intact valid dependency
lock. Their corrected assertions pass without changing production behavior.
These focused gates establish neither a full release nor a speed improvement.
Next integrate the existing generation protocol and independently authorized
recovery inventory into the self-host owner; preflight cannot substitute for
that work or for BTRSmith's actual build-entrypoint integration.

## Self-host directory coordination checkpoint (September 20)

The self-host CLI now acquires the same persistent `.btrc-publications.lock`
files used by the reference publisher and native-plan reader. It gathers the
complete named primary/secondary/plan directory set before writing, sorts and
deduplicates it, and retains all locks through the named-file writes. Both the
requested parent and the resolved target parent are protected for output
symlinks; the existing per-file replacement behavior is otherwise unchanged.
Directory identity, lock identity, output resolution and input/output aliases
are checked again after a wait. A pending journal in any participating directory
rejects the write; arbitrary journal contents grant no recovery authority.

`AdvisoryFileLock` in `FileSystemHandles.btrc` owns the reusable POSIX mechanism.
It offers a nonblocking default attempt and explicit blocking acquisition for
command-line callers, metadata checks before and after acquisition, typed
outcomes, idempotent close and exact-handle accounting. It refuses symlink,
nonregular and multiply linked coordination files, uses close-on-exec, and
never removes the persistent lock name. A replaced lock is detected after a
wait and before protected work. This is not a private-directory state lease:
public output directories need not be mode 0700. Windows currently returns an
explicit unsupported outcome; a native locking implementation remains required.

This step prevents the self-host writer from modifying named generated files
while a cooperating build reads them. It does **not** complete M6a: a process
failure between per-file replacements still leaves a mixed generation once its
locks release. No recovery marker is yet created by this writer. Private
prepared/committed ownership records, the shared generation journal and rollback,
retirement, source-read identity, final filesystem race closure and BTRSmith
build-entrypoint integration remain required. External direct writes and shell
redirection of stdout are outside the named-output lock set.

Verification on compiler fingerprint `6a2f813dae6964ac39ef05af456ca6fb`:

- Baseline: **57 CLI tests passed** (`build/plan-selfhost-lock-baseline.xml`).
  Four new regressions failed on the old writer: it ignored a held reader lock
  and journals in primary, plan and secondary directories
  (`build/plan-selfhost-lock-red.xml`).
- Fresh build: **61 initial CLI cases passed**
  (`build/plan-selfhost-lock-first.xml`).
- Final integration: **286 passed / 4 Linux-toolchain skips**
  (`build/plan-selfhost-lock-final.xml`), including **72 CLI cases**, emitted
  units, native packages and the native-plan builder. Tests hold real reader
  locks independently in each output directory; change output symlinks, input
  aliases, lock inodes and pending journals during a wait; reject unsafe lock
  files without hanging; and run writers with opposite output-directory orders.
- Both-frontends filesystem corpus: **12 passed**
  (`build/plan-selfhost-lock-corpus.xml`). The new lock fixture covers contention,
  shared alias closure, 100 acquire/release cycles, replaced inodes, symlinks,
  hardlinks, FIFOs and exact-handle balance. Existing private-directory, regular
  snapshot and exact-handle behavior remains covered.
- **98 architecture/naming checks passed**
  (`build/plan-selfhost-lock-structure-final.xml`). The unused-method audit now
  recognizes ARC-invoked destructors alongside implicit constructors, without
  adding an owner-specific exception. Canonical code generation, lint,
  formatting and whitespace checks also pass.

These disjoint final suites total **396 passes / 4 visible skips**. An earlier
reference fixture needed native setup buffers for `link`/`mkfifo`, whose hosted
ABI does not permit forwarding managed strings; no production ABI exception
was added. An earlier architecture run exposed the implicit-destructor audit
omission. Both corrected checks are included in the final evidence. Source
hashes are recorded in `build/plan-selfhost-lock-inputs.json`. Full bootstrap,
C11 optimization matrix, installed BTRSmith and native Windows qualification
remain open; no performance improvement is claimed.

## Self-host staged output set checkpoint (September 20)

`FePackageFileStore` now separates candidate creation from replacement through
an owned `FeStagedFile`. The candidate is a same-filesystem temporary with
close-on-exec, complete writes, strict file flush and captured identity.
Publication validates candidate revision and destination-directory identity,
then consumes the candidate name on successful rename. A subsequent directory
flush failure reports `DURABLE_REPLACE_DURABILITY_UNCERTAIN`; it cannot be
reported as an unchanged destination or a successful durable write. The existing
single-file package-state API composes these operations and retains its boolean
success contract, now requiring the directory flush to succeed as well.

`BtrccPreparedOutputs` holds all compiler candidates together. The CLI freezes
canonical destination paths when acquiring publication locks, prepares primary,
secondary and link-plan payloads without replacing anything, revalidates the
original requested paths and source aliases, then consumes the prepared set.
A preparation failure cleans owned candidates and leaves the prior output set
intact. Cleanup checks identity and never deletes a different inode substituted
at a candidate name. Existing output symlinks remain in place and their resolved
targets receive the new bytes with their prior permission bits. New files retain
the existing 0644 default; full reference umask parity remains open.

The replacement order is now primary, secondaries, then the requested link plan.
These are still separate replacements: this is preparation for the shared
transaction, not generation rollback or crash recovery. A failure or process
exit during publication can leave mixed outputs after locks release. The
private prepared/committed ownership inventory, journal integration, retirement,
read-handle identity and final filesystem race closure remain required. An
abrupt exit during staging can leave a random candidate without changing public
outputs; durable candidate ownership and cleanup belong in that integration.

Staging qualification on the final recorded inputs: **295 passed, 4 skipped**
in `build/plan-selfhost-stage-qualified.xml` (299 cases), plus **98 architecture/
API passes** in `build/plan-selfhost-stage-qualified-structure.xml`. The four
skips are host-specific emitted-unit coverage. The reference-built staged-owner
fixture also passes separately (one overlapping case). Source hashes in
`build/plan-selfhost-stage-inputs.json` were rechecked after the reader work below;
these compilers/tests were unchanged. Full release and product gates remain open.

## Native generated-file alias checkpoint (September 20)

The native reader previously rejected generated-file symlinks even though both
CLIs preserve those requested output aliases. It now resolves only compiler
primary/secondary/link-plan inputs to real regular files, discovers both requested
and physical parent directories, and reacquires the entire sorted lock set before
reading plan bytes or starting native tools. Each expansion re-resolves the plan
and source bindings; eight unsuccessful attempts produce a retry error and release
the locks. A pending journal in a resolved target directory stops the build without
recovering or modifying it. All locks remain held through cache validation,
compilation, linking and successful report publication.

The compiler receives the original requested C path, preserving quoted-include
lookup and debug source naming. Schema 3 derived unit filenames and schema 4
explicit paths both support aliases. Duplicate physical units, dangling/looping
aliases and nonregular targets remain invalid. Native package units and headers
retain their original no-follow checks; permitting generated aliases is not a
global change to package validation. Coordination still assumes participating
publishers; this does not freeze arbitrary path mutations or native headers.

Baseline: **97 native-builder cases passed**. The ten new alias build, locking,
retargeting and journal cases then failed on the old reader. With the repair,
**25 focused cases passed**, including existing inventory rejection and directory
rediscovery. Five additional boundaries pass: package/header symlinks remain
rejected, and repeated primary/secondary/plan retargeting exhausts the discovery
bound safely and permits a later stable read. Final integration:
**337 passed, 4 skipped in 74.03 s**, recorded in
`build/plan-native-alias-final.xml`: 116 native-builder cases plus emitted-unit,
native-package, performance-harness and self-host CLI coverage. Both frontends
emit primary/secondary/plan aliases that build and execute, then hit the native
object cache. The four skips require a Linux C toolchain. Earlier focused counts
overlap this result. Full-tree lint and format (610 files), generated-source
checks and `git diff --check` pass. The installed reader/publication module hashes
match the working tree; qualification input hashes and self-host fingerprint
`384dc12e19ce3329ce53e9a88880292f` are in `build/plan-native-alias-inputs.json`.

The rebuilt installed adapter is
`/nix/store/jcwglank01fp4gafmxgzzmj2b9zwcc7a-btrc-native-plan`. It compiled and ran a
split-C program with all three input roles aliased into separate directories,
found a quoted header only beside the requested C filename, and hit both cached
objects on a second build. A journal beside the secondary target caused rejection
without modification. Evidence lives in `build/plan-native-alias-installed/` and
`build/plan-native-alias-nix.log`. This is macOS native-build and installed-adapter
evidence, not Windows qualification, BTRSmith acceptance or a measured speedup.

## Self-host generation-owner coordination (September 20)

`BtrccGenerationOwner` begins the self-host transaction integration by using the
reference owner's exact SHA-256 key for the canonical primary path and the same
`.compiler-owner.publish.lock`. It acquires that private per-primary owner before
any sorted output-directory lock, and retains it through staging/publication.
The existing stdlib `PrivateDirectory` and `ExclusiveFileLease` own descriptor
access, bounded no-follow reads, private modes and single-link record checks;
the lease now offers explicit blocking acquisition for command-line owners.
Default lease acquisition remains nonblocking.

`PrivateDirectory.validatePath` distinguishes a valid pinned handle from current
named authority. Existing pinned operations still work across a rename, but a
compiler owner rechecks directory identity and private permissions after waiting
and again before publication. `ExclusiveFileLease.validate` also requires the
persistent lease name to retain the locked inode and its private permissions. Private state may not be an output destination.
Committed records are checked for the existing schema, canonical anchor, unique
paths and non-secondary roles, mode bounds and lowercase SHA-256 identities.
Both the existing record and a pending intent remain untouched by this phase.
Any prepared intent stops the self-host writer before output-directory locks;
recovery still requires the reference transaction owner. This is stronger
coordination and validation, not self-host recovery or ownership publication.

State is provisioned lazily for a successful named-primary build. The absolute
`BTRC_STATE_DIR` override and Unix default locations agree with the reference
CLI; default host selection uses bounded `uname -s`, independently of the
program's compilation target. Missing host/home discovery reports an error and
requires the explicit override. Windows private-state/lock support remains open.
Stdout-only and failed compilations do not provision generation state.

The next phase must compose the existing journal format with this owner: persist
candidate/intent before any public replacement, stage the final committed record
as the validator, retire only outputs whose prior owned digest matches, recover
the old authorized inventory before accepting a changed layout, and retain
recovery controls on uncertain flush/cleanup. Take the union of old/new directory
locks without inverting owner-first order. Reference/self-host cross-recovery and
real process-death tests are required before claiming parity. No new journal
format or second ownership model is introduced by this coordination checkpoint.

Evidence: baseline **85 passes** across self-host CLI and the two filesystem
fixtures through both frontends. The seven initial private-state regressions
failed before the implementation. Final `build/plan-owner-qualified.xml` records
**217 passed, 1,918 deselected in 328.56 s**: 97 self-host CLI cases, 116 native
builder cases, and four both-frontends filesystem cases. The selected set has no
skips; deselected corpus programs were not verified by this run. It includes
actual reference-produced ownership, process-level contention, pending intent
created during a lock wait, permission/directory changes, a replaced owner-lock
inode while blocked on an output lock, default state location, and no state
provisioning for stdout-only/failed builds. The reference filesystem subset also
passed separately (two overlapping cases).

Architecture/naming: **29 passes** in `build/plan-owner-structure-qualified.xml`.
Full-tree lint, formatting (610 files), compiler codegen and `git diff --check`
pass. Compiler/input hashes are recorded in `build/plan-owner-inputs.json`;
the fresh strict C11/O2 self-host fingerprint is
`2853daa49a3da83fe4ad3519221d9321`. The intermediate build was deliberately stopped
for the subsequent path/lease identity checks and is not qualification evidence.
Full bootstrap/C11/release/product gates and self-host transaction recovery remain
open. Existing committed records are validated but not advanced after self-host
writes yet, so mixed-frontend retirement is not qualified by this checkpoint.

## Self-host regular-file generation transaction (September 20; focused qualification)

This supersedes the earlier owner-coordination limitation for named-primary
regular-file generations on POSIX. `BtrccFilePublication` and
`BtrccGenerationOwner` in the existing CLI owner compose the reference journal
and private authority protocols. No alternate journal format or Python runtime
dependency is added to the self-host compiler.

The writer holds the owner lock before the union of current/interrupted output
directory locks and the shared publication lock. Recovery validates every
surviving participant against caller-authorized targets before mutation. It
restores the validator last on rollback, preserves the last good restored copy
when a subsequent flush fails, and retires the coordinator before participant
markers. The owner reloads recovered ownership before planning obsolete-file
retirement and persists candidate/intent records before public replacement.
The final committed manifest records paths, roles, modes and SHA-256 digests.
Current inputs and modified obsolete outputs cannot be retired.

A real linked syscall fault fixture exercises process death without production
test hooks. An additional probe reproduced publication of modified staged bytes;
the repair compares staged data in 64 KiB reads and checks permissions immediately
before journaling, and rechecks retirement digests at that boundary. The private
lease gained durable, no-follow child removal with explicit uncertain durability.

Final evidence on fresh strict C11/O2 self-host fingerprint
`f3bf0ddfd28309c1aa6e7785f2862c26`:

- `build/plan-publication-final.xml`: **192 passed, 1,918 deselected in
  449.24 s** — 86 transaction cases (43 through each frontend), all 102 CLI
  cases and four affected filesystem cases through both frontends. No skips.
  Includes actual native-to-reference recovery of private generation authority
  at payload/validator/commit boundaries, reference-to-self-host CLI recovery
  followed by layout shrink, and final staged-data/retirement revalidation.
- `build/plan-publication-native-reader.xml`: **116 passed in 144.39 s**, with
  no skips, covering native-builder coordination and generated output aliases.
- `build/plan-file-publication-reference.xml`: **78 reference publication
  regressions passed**; the Python publisher was unchanged in this checkpoint.
- `build/plan-publication-final-structure.xml`: **29 architecture/naming
  checks passed**. Full lint, formatting (611 files), generated-source checks
  and `git diff --check` pass. Source/fixture hashes and the compiler binary
  digest are recorded and rechecked in `build/plan-publication-inputs.json`.

These are 415 focused checks, not the complete release matrix. Intermediate
runs are superseded: the staged-byte corruption probe was reproduced before
repair, and the corrected cases pass in the final two-frontend suite. A test
harness `--no-cache` argument unsupported by btrcc and a missing private-state
directory in test setup were corrected without weakening their assertions.
The reference-only private-removal test also passed separately and overlaps
the final filesystem selection; it is not added to the total.

The follow-up below addresses bounded-memory retirement hashing. Remaining
scope includes large BTRSmith generation performance, native Windows private
storage/locks, read-time source identity,
final path-race qualification, stdout/secondary-only transaction policy,
installed consumers and the complete bootstrap/C11/release/product matrix.
The broader performance, platform and native UI milestones remain open.

## Output rebinding and streaming digests (September 20; focused qualification)

`BtrccGenerationOwner.publish` now checks each freshly resolved output after
owner-lock contention and before creating transaction authority. A linked
`flock` probe reproduced three invalid-intent cases: an existing leaf symlink,
and parent symlinks pointing to existing or missing private-state files. The
repair rejects these destinations without modifying public outputs, prior
ownership, candidate or intent records. Tests cover leaf/parent and
existing/missing targets both with and without a committed generation, then
restore the binding and successfully retry. This closes the reproduced race;
it is not a general claim of safety against every uncooperative path mutation.

`Library.Digest.SHA256` now exposes `appendBytes`, `appendText` and idempotent
`finish`, retaining the static APIs and their null-as-empty behavior. Input
chunks are borrowed for the call only; an append after finalization throws.
Fixed embedded state/schedule arrays and at most one pending 64-byte block
replace full-message copies and per-block vectors. The byte count is 64-bit
and rejects lengths exceeding SHA-256's byte-oriented message bound before
mutation. Padding and encoded length follow
[FIPS 180-4](https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf).
The writer hashes retirements through one immutable file snapshot in 64 KiB
reads, including a version check for an empty file, and reports close failures.
Journals retain their separate bounded whole-record reads.

Final evidence on fresh strict C11/O2 compiler
`d6c34f6344fa2a7b2ca2d1921a980601`:

- `build/plan-stream-final.xml`: **222 passed, 1,916 deselected in 600.34 s**:
  114 publication cases (57 per frontend), 102 CLI cases and six digest/file
  capability corpus cases. No skips. Includes bounded retirement reads at
  0/63/65,536/65,537/262,145 bytes and mutation during the actual snapshot read.
- `build/plan-stream-native-builder.xml`: **116 passed in 379.53 s**, no skips;
  this run includes the fresh compiler build shared with the other suite.
- `build/plan-stream-reference-structure.xml`: **107 passed in 27.87 s**:
  78 reference publication regressions plus 29 architecture/naming checks.
  Full lint, formatting (611 Python files), generated sources and whitespace
  checks pass. Total: **445 disjoint focused checks**.
- `build/plan-sha256-c11-{reference,selfhost}.json`: each frontend's expanded
  SHA corpus passes strict C11 with real GCC 15.2 and Apple Clang at
  **-O0/-O1/-O2/-O3**. Address/undefined sanitizers pass both generated programs.
  These repeat the corpus under different configurations; they are not added
  to the 445-test total or presented as the full `make test-c11` matrix.
- `build/plan-large-retirement.json` and
  `build/plan-large-retirement-selfhost.json`: both native writers retire a
  **2,147,483,713-byte (2 GiB + 65-byte)** sparse zero file. The expected digest
  is independently computed with Python hashlib. The linked fixture rejects
  any retirement read above 65,536 bytes. Peak RSS is **3,178,496 bytes** for
  reference-generated C and **3,194,880 bytes** for self-host-generated C,
  below the trial's 32 MiB bound. These are strict C11/O2 fixture executables;
  the measured approximately 20-second times include concurrent qualification
  activity and are capacity/correctness evidence, not product speed claims.
- `build/plan-stream-inputs.json` records source/fixture and compiler hashes,
  rechecked after the final suites. Both large-file records also retain the
  generated-C and executable digests.

The first incremental prototype retained reusable vectors and reduced memory
but was about 15% slower on the preliminary 32 MiB trial. It was replaced by
embedded fixed arrays before final qualification. An intermediate test run
was deliberately stopped for that measured repair; its incomplete results and
compiler directory `ee2bc487770c0f07038d0792f2726982` are not final evidence.
The earlier lock-only checkpoint passed eight reference-built contention cases
and 29 structural checks; the final matrix supersedes it.

The final one-shot text benchmark uses five alternating process samples per
variant and size after warmup, with task builds/tests idle. Wall time includes
constructing the input text and hashing it. Both generated programs use the
same Clang `-O2` configuration; every digest is checked against Python hashlib.
Raw samples, compiler/OS/CPU identity and executable hashes are in
`build/plan-sha256-benchmark.json`.

| Text size | Before median | After median | Speedup | Before peak RSS | After peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 MiB | 0.0258 s | 0.0159 s | 1.62× | 5.83 MiB | 2.67 MiB |
| 32 MiB | 0.6681 s | 0.3618 s | 1.85× | 97.84 MiB | 33.66 MiB |
| 128 MiB | 2.6454 s | 1.4203 s | 1.86× | 385.84 MiB | 129.67 MiB |

The one-shot API still receives a complete caller-owned input; the reduction is
in additional hashing storage. The retirement trial separately proves bounded
storage while reading a file larger than the old Bytes capacity. These results
do not establish a BTRSmith build-speed improvement. Full product timings,
remaining path/read-identity races, native Windows publication, installed
consumers and the complete test/bootstrap/C11/release gates remain open, as do
the rest of PLAN.md's performance, C compatibility, platform and UI milestones.

## Publication cleanup errors (September 20; focused qualification)

The self-host writer now reports explicit lock-release and snapshot-close
failures. `BtrccFilePublication.releaseLocks` consumes the transaction lease and
all directory leases even when one fails; the generation owner and CLI propagate
its diagnostic. Existing read, validation and publication errors stay first,
with cleanup errors appended. Destructors retain best-effort fallback and do
not replace the explicit checked close path.

Journal reads, retirement hashing and prepared-payload validation share checked
snapshot cleanup. Inventory selection catches only schema/inventory mismatch;
a read/close failure cannot be mistaken for permission to try another inventory.
Read bounds cover both independently authorized layouts, including a larger
interrupted generation. A literal JSON null is rejected as an invalid journal.
No journal supplies its own recovery authority.

The linked test shim injects `flock(LOCK_UN)` failure before native unlock and
`close` failure after consuming the real descriptor. It also combines read and
close failure. Fault selection matches the actual open inode; a trace proves
that the requested fault fired. Before exiting, the native fixture checks the
filesystem handle inventory and probes the released locks through independent
opens, including repeated close. This prevents process exit from concealing
retained locks. A cleanup failure after successful commit preserves the complete
new generation and permits a validated retry; an untrusted journal read leaves
the interrupted files untouched.

Evidence:

- Baseline `build/plan-cleanup-baseline.xml`: **6 passed** through both frontends.
- Before repair, `build/plan-cleanup-red.xml`: **9 failed, 3 passed**. Six
  transaction/directory unlock/close failures incorrectly returned success;
  two combined failures lost the cleanup diagnostic; a failed journal close
  still allowed recovery mutations. Existing private-owner release and
  successful-read digest-close diagnostics already passed.
- Final `build/plan-cleanup-final.xml`: **477 passed, 1,916 deselected in
  542.14 s**, no skips, on fresh strict C11/O2 compiler
  `20e450e924c5a1169a4118d25f5a1554`. Breakdown: 146 publication cases (73 per
  frontend), 102 CLI, 116 native-builder, 78 reference-publication,
  29 structure/naming and six filesystem corpus cases. The new backlog contains
  16 cases per frontend, including combined prepared-payload read/close failure,
  larger-current/smaller-prior journal bounds and null-journal refusal.
- `build/plan-cleanup-c11-{reference,selfhost}.json`: each frontend's generated
  native fixture passes all **16 new scenarios** under **GCC 15.2 and Apple
  Clang 21, strict C11, -O2, -Wall -Wextra -Werror**. These are repeated
  configurations, not 64 additional independent checks or the full C11 matrix.
- `build/plan-cleanup-inputs.json` and `build/plan-cleanup-fixtures.json` retain
  source, fixture and fresh compiler identities, rechecked after qualification.
  Full lint, formatting (611 Python files), generated-source and whitespace
  checks pass. The earlier helper compile error (rebinding a borrowed string
  parameter) was fixed by using an owned local; that intermediate setup-error
  run is not qualification evidence.

This closes the reproduced cleanup paths. It does not establish no-op or
BTRSmith speed budgets, installed product qualification, native Windows private
publication, source identity at original read time or complete path-race safety.
The remaining M6a work, full release gates, and all later performance, C,
platform and UI requirements stay open.

## Source identity at read time (September 21)

The reference source reader captures `fstat` metadata from the actual stream,
checks it after reading, and correlates it with the requested path and canonical
resolution. Immutable read identities travel through import dependency graphs,
relaxed stdlib composition and compiler results into the CLI publication guard.
The CLI also retains its root read identity. Reusing the library compiler with
an in-memory root remains supported; read metadata is not a content-cache key,
so an unchanged-content touch between invocations can still reuse artifacts.

The POSIX self-host reader captures the same shared `FileSnapshot` metadata
through `File.snapshot()`, then rechecks all captured reads before publication
and in the generation owner's guard, including after waiting for locks. The
reader also serves grammar, package and stdlib metadata paths used by that
frontend. Source bytes still read to EOF. Source descriptors close immediately
after reading; validation owns only copied path/version values. Reusable
repositories may read refreshed source snapshots; the reader retains the first
identity for each requested path, so a later read cannot bless a mixed output
generation. Publication validates that original inventory. An independent
compilation uses a fresh reader when it needs its own publication inventory.

Qualification exposed a dependency regression: putting filesystem handle types
behind `File.snapshot()` made root IO import a group module and broke relaxed
composition. Immutable `FileSnapshot` and `FileKind` now belong to IO; filesystem
handles reuse them. The stream outcome distinguishes closed, unsupported and
native inspection failure without importing the filesystem error owner. Native
descriptors stay private. Existing filesystem constructor and cache-token bytes
are unchanged; consumers that explicitly name these shared metadata types now
import `Library.IO`. Root-prelude, relaxed cached-warning and archive checks are
part of the regression selection. The `fileno` declaration also moved from
Process to IO, the owner that actually inspects the open stream; Process already
imports IO. The corpus verifies closed-stream outcomes and a renamed/replaced
file's still-open original stream.

The publication fault fixture replaces a file during the actual native stream
read, or edits/renames/retargets/removes it after reading while the generation
owner is contended. Rejection preserves outputs and creates no new intent,
candidate or journal; a fresh read permits retry. Reference CLI tests separately
cover root/import mutation after compilation and after output preparation,
including preserving original source bytes moved into the output path.

Final focused qualification records **742 passed / 6 skipped** in 751.46 s
(`build/plan-read-identity-reuse-final.xml`), covering both frontend publication
fixtures, CLI/frontend boundaries, source/import/cache behavior, native builder,
emitted units/packages and compiler structure/naming. Skips are `/dev/full`,
non-macOS XDG behavior and four Linux split/debug-unit cases; they are not passes.
The separate corpus selection passes **26 checks** through both frontends
(`build/plan-read-identity-reuse-corpus.xml`). Reference CLI/source/archive checks
pass **149 cases** (`build/plan-read-identity-verified-prelude.xml`).

The four reuse checks also pass separately, including a changed reread that must
not erase the original identity (`build/plan-read-identity-reuse.xml`); those
checks overlap the 742 and are not additional coverage. Earlier stopped/failing
runs exposed and drove the IO dependency, fixture cleanup and reuse repairs;
they are superseded by these final results.

Fresh self-host fingerprint `a26a8832357525806c6d3a26fe0a341d` and 22 frozen input
hashes were reverified. Fixture/compiler hashes are recorded in
`build/plan-read-identity-reuse-{inputs,fixtures}.json`. Both frontend-generated
publication fixtures pass the same **21 scenarios** under actual GCC 15.2 and
Apple Clang 21 with strict C11, `-O2`, warnings and `-Werror`
(`build/plan-read-identity-c11-{reference,selfhost}.json`). These repeated
configurations are not additional independent checks or the full C11 matrix.
Lint, format-check (611 files), generated-source and diff checks pass. Full
`make test`, bootstrap and the final release matrix remain required.

This does not establish a complete immutable input snapshot or prevent every
noncooperating writer race. Reference package manifests/locks, grammar, symbol
indexes, SDK and binary inputs use other reader paths and still need explicit
original-read identity coverage. Windows stream inspection reports unsupported;
the self-host keeps its existing Windows source path pending native handle
identity and publication providers. Installed BTRSmith/no-op budgets, full
release gates, and the later performance/C/platform/UI work remain open.

### Product make integration

BTRSmith's clean main checkout was fast-forwarded from `292deaff` to `5549c261`
before the next measurement. Its source-build macro previously deleted the link
plan and every secondary C file before invoking either compiler. A deliberately
failing compiler command through the real `btrsmith-source` recipe reproduced
loss of that prior generation (`build/plan-product-generation-baseline.log`).
The macro now leaves publication and owned retirement to the compiler. A second
probe reproduced `.DELETE_ON_ERROR` removing a newly committed link plan when
the compiler reports a later cleanup failure
(`build/plan-product-generation-postcommit-baseline.log`). The application
explicitly declares its generated C and link-plan targets `.PRECIOUS`, preserving
the complete old or new generation chosen by the compiler. The frontend parity
target forces recompilation with Make's `-W` rather than deleting the generation
in advance. `tests/packaging/BuildGeneration.sh` in BTRSmith checks both failure
boundaries for both frontend selections; all four cases pass under system Make
and GNU Make 4.4.1 (`build/plan-product-generation-final.log`). The check also runs
before `application-frontend-check`.

These tests exercise build-recipe failure handling, not a native product build
or performance acceptance. The following actual-make runs qualify the settings
repair; complete dependency identities and link reuse remain open. Earlier diagnostic timings retain their
original workload revision and must not be relabeled as this checkout.

### Actual product Make baseline (September 21)

`build/perf/product-make-2026-09-21/run-0od68yy0/{results,assessment}.json`
records the completed actual `make -f make/Product.mk btrsmith-native` baseline
on BTRSmith `5549c261` with the generation-preservation make changes and working
compiler `a26a8832357525806c6d3a26fe0a341d`. Each frontend uses a fresh build/object
directory, dev flags and eight native jobs. OS/package caches are uncontrolled;
the host/tool/source records are retained, including background system activity.
Source and tool snapshots stayed unchanged. This is a local compiler override,
not a pinned or installed-product gate.

| Frontend | Cold dev executable, one sample | No-op median / p95 / max, 20 samples | Compiler / native-builder calls on every no-op |
| --- | --- | --- | --- |
| Self-host | 129.619 s | 0.095 / 0.101 / 0.102 s | 0 / 0 |
| Reference | 340.411 s | 0.096 / 0.101 / 0.105 s | 0 / 0 |

**Both mode-switch probes fail correctness:** requesting `BUILD=release` after
dev performs zero work and returns the byte-identical development binary. Make's
toolchain stamp records paths but omits flags and file contents. Consequently,
these fast no-ops do not qualify M6a. A successful command exit in `results.json`
is not acceptance; `assessment.json` records the failed invalidation.

The repair separates per-frontend compilation and native-build settings in the
existing Make graph. Versioned SHA-256 identities include effective flags,
selected executable bytes and the recorded build environment fields. Content
comparisons force the appropriate target, independent of timestamp resolution;
receipts are discarded before an attempt and atomically recorded after success.
Discarding first matters when a compiler reports a cleanup failure after commit:
the old receipt must not bless the newly written generation on a later retry.

`tests/packaging/BuildInputs.py` exercises the real Make graph with recording tools
at process boundaries. The initial 12 cases all failed before the settings
repair. The expanded run had six failing retry checks from reuse of old receipts;
the final 20 cases pass under system Make and GNU Make 4.4.1, as do the four
generation-preservation cases (`build/plan-product-inputs-verified-{system,gnu}.log`).
Tests include mode changes and returning to an earlier mode, native-only options,
quoted values, independent frontend outputs, unit layout, failed attempts before
and after writing, and tool replacements preserving both size and timestamp.
These graph tests do not by themselves prove native compiler behavior.

The completed follow-up is recorded in
`build/perf/product-make-inputs-2026-09-21/run-8vi4ozd5/{results,assessment}.json`.
It uses the same compiler/product revisions, eight native jobs and local override
scope. All 50 invocations completed successfully; source/tool snapshots and the
five frozen product integration files stayed unchanged.

| Frontend | Cold dev executable, one sample | No-op median / p95 / max, 20 samples | Dev → release rebuild | Native optimization 2 → 1 |
| --- | --- | --- | --- | --- |
| Self-host | 131.427 s | 0.199 / 0.210 / 0.210 s | 122.521 s | 17.539 s |
| Reference | 344.744 s | 0.200 / 0.207 / 0.208 s | 333.772 s | 17.976 s |

Every dev no-op invokes neither compiler nor native builder and preserves the
executable digest. Each mode switch invokes both once and produces a different
executable; each native-option change invokes only the native builder. The
subsequent release and native-option no-ops also perform no build work. This
qualifies the tested settings transitions, not the complete no-op KPI or a cold
speedup. Cold results have only one sample per frontend.

Source-invalidation probes against the actual Make graph with recording tools
still fail in both frontend selections (`build/plan-product-content-probe.json`):
touching identical bytes reruns compilation; a same-timestamp content edit and
a removed source omitted from the new prerequisite inventory perform no work.
These probes establish scheduling defects, not native product runtime behavior.

The touch probe also exposed a separate defect: a compiler can invalidate the
native receipt during its recipe while regenerated outputs retain their prior
timestamps. A receipt check performed only while Make parses the graph then
misses the invalidation and leaves the old executable. Two deterministic cases
reproduce this for both frontend selections by preserving generated-output
timestamps (`build/plan-product-native-receipt-red.log`). The native recipe now
checks its receipt after compilation, using a force prerequisite for the cheap
check. Unchanged inputs still skip the native process. Its shell explicitly
enables failure propagation because system Make 3.81 ignores `.SHELLFLAGS`.
The final 22 graph cases and four generation-preservation cases pass under both
system Make and GNU Make 4.4.1
(`build/plan-product-native-receipt-{system,gnu}.log`); lint, format and diff checks
pass. A final actual-product repeat uses the existing release/O1 executables:
`build/perf/native-receipt-wm8gdhbj/results.json` records 20 no-ops per frontend,
all with zero compiler/native calls and unchanged executable digests. Self-host
median/p95/max are 0.183/0.194/0.202 s; reference are 0.182/0.187/0.188 s. The
five product integration files stayed unchanged during this repeat. These are
different modes from the dev rows above, not evidence of a speedup.

The receipts are not a complete build-input identity. Transitive interpreter or
wrapper dependencies, stdlib/SDK/native-library contents and resolution changes
still need validation. Binding configuration state to the compiler/native
generation transaction, including concurrent different configurations, remains
part of M6a. Preserve those obligations rather than interpreting a small no-op
time as the final acceptance result.

## Self-host artifact generations (2026-09-21)

Named-output self-host invocations now reuse complete emitted generations after
fresh source, package and native-header resolution. `Compiler` owns the reuse
decision through `IBtrccArtifactCache`; `CompilerPipeline` separates resolution
from the remaining stages. The optional CLI storage owner uses private
directories, one lease per key and a manifest committed after all payloads.
Entries contain primary C, all secondary units, the canonical native plan and
diagnostics, with a 512 MiB aggregate payload bound. Missing, corrupt or linked
payloads are misses. Output publication still runs through the existing
generation transaction, including its input/alias checks and recovery.

Keys cover compiler executable bytes, source contents and paths, raw API root
text, grammar vocabulary, current package/native facts, native reader bytes and
validated responses/arguments, target and emission settings. A relative or
unverifiable reader executable disables reuse. Every invocation still resolves
imports and scans the actual selected SDK; a cached plan can add generated
artifacts only if reconstruction over today's resolved facts reproduces its
exact canonical representation. The cache never supplies publication authority.

Qualification exposed a derived-lock inconsistency: the first package build
created `btrc.lock`, but only the next invocation included it in the input key.
The resolver now validates the old lock separately and records the resulting
published lock through the shared reader. First-build reuse, lock regeneration,
same-timestamp manifest changes and malformed-lock rejection have direct tests.

Evidence:

- `build/plan-selfhost-cache-verified.xml`: **12 passed**, including real native
  header changes, include shadowing, binding policy/reader changes, source
  touch/edit/removal, complete split/debug restoration, option identity and
  corruption. Restored C is compiled, linked and executed.
- `build/plan-selfhost-cache-integration.xml`: **361 passed, 5 skipped**, covering
  CLI publication, frontend I/O boundaries, native packages/builds and emitted
  units. Skips are `/dev/full` and four Linux-only native split/debug cases.
- After canonical formatting, `build/plan-selfhost-cache-qualified.xml` records
  **114 cache/CLI checks passed** on the final self-compiled compiler. Its SHA-256
  is `f0d95628128bf4751f094ccf16dfd9126f2eb68847a574645a92240bf8a24c5c`.
  Strict Apple Clang 21 C11/-O2 with `-Wall -Wextra -Werror -pedantic-errors`
  succeeds. Formatting preserved the generated compiler C byte-for-byte.
- **23 compiler structure checks**, generated-source checks, full BTRC format,
  Python lint/format and diff checks pass. Source hashes, compiler identity and
  test records are in `build/plan-selfhost-cache-qualification.json`; the final
  475-file build snapshot is `build/plan-selfhost-artifact-qualified-snapshot.json`.

The full BTRSmith workload now exercises this cache in
`build/perf/selfhost-artifact-cache-2026-09-21/run-oxhgrnb4/results.json`.
The diagnostic uses product `5549c261`, the working-tree compiler above, macOS,
development/debug output, eight native jobs, fresh artifact/object/state caches
and the real native reader. Source and selected tool hashes stayed unchanged.
It runs the compiler and native builder directly; OS/package caches and power
state are uncontrolled. It is not an installed or Make-entrypoint qualification.

| Scenario | Compiler command | Native command | Sum of command wall times |
| --- | ---: | ---: | ---: |
| One cold build | 129.108 s | 9.428 s | 138.536 s |
| Five warm builds, median | 10.529 s | 3.146 s | 13.687 s |

Every warm invocation reports `artifact-hit`, skips lexing through emission,
and reproduces all **202,843,943 emitted bytes**, including the plan with two
generated adapters. Each native repeat reuses **17/17 objects**, compiles zero
units and still links once. Executable hashes change with relinking, so these
are not zero-work builds. Compiler peak RSS is **4.601 GiB cold** and about
**306 MiB warm**; this is process peak, not aggregate native-build memory.
Between-command verification hashes are separately timed and excluded from
the summed command wall times. The medians of stages need not sum to the
median of complete runs.

Warm phase medians identify the next costs: **4.334 s native resolution**,
**1.450 s source graph work**, and **2.202 s artifact key/load/plan validation**.
About **2.224 s** of compiler wall time falls outside the phase marks, including
output publication and process overhead; this is not an isolated publication
measurement. The **13.687 s** repeat remains above the **2 s** no-op budget.
The single cold sample is diagnostic, not a qualifying cold-build distribution
or a comparison against earlier runs under different conditions.

Output write/link elision, Make integration that validates inputs on every
invocation, cheaper validated lookups, eviction, Windows storage, required
hosts and the final compiler/product matrix remain open. Cache reuse on this
workload is proven; M6a's no-op and edit budgets are not.

## Product entry-point validation (2026-09-21)

BTRSmith's `btrsmith-source` and `btrsmith-native` targets now invoke the
compiler/native owners for validation on every build. Make no longer uses
settings/tool receipts or broad mtime prerequisites to decide whether the
loaded dependency closure needs checking. Both frontends use their complete
artifact caches by default; explicit `--no-cache` remains available. The
existing `.PRECIOUS` declarations preserve compiler-owned generations on
failed publication, and native work still waits for successful compilation.

GNU Make 4.4's parallel jobserver exposed an unnecessary object-cache miss:
its changing FIFO identity was inherited in `MAKEFLAGS`, while the native
builder correctly fingerprints the complete environment visible to compiler
wrappers. `LINK_BTRC` now excludes `MAKEFLAGS`, `MFLAGS` and `GNUMAKEFLAGS` at
the process boundary. The native builder owns its explicit `--jobs` setting;
its environment-key validation is unchanged. This also avoids adding another
special-case environment exemption inside the compiler cache.

The final test set passes under both system Make 3.81 and GNU Make 4.4.1:

- **22 process-boundary cases** cover settings/quoted arguments, frontend
  output isolation, failures/retries and native invocation after compilation
  even when emitted timestamps are preserved.
- **Four publication-preservation cases** cover both frontends failing before
  publication or after a committed generation.
- **Six real compiler/native cases** use `make -j8`, compile and execute the
  resulting programs, and verify both frontends' cache hits. They cover
  unchanged-content touches, same-size/same-timestamp imported-source edits,
  removed imports, native C/header edits, include shadowing, missing headers
  and complete split-output restoration with native object reuse.

Results are in `build/plan-product-validation-results.json` and
`build/plan-product-validation-{system,gnu}-{BuildInputs,BuildGeneration,BuildArtifacts}.log`.
The real tests use physical private cache/state paths when the product's
`build/` directory is symlinked, and do not enable reference profiling during
cache checks. Python lint/format and diff checks pass. Compiler production
sources are unchanged from the qualified self-host cache checkpoint.

The complete actual Make measurement finished successfully using BTRSmith
`5549c261` plus the seven product Make/test/documentation changes, the qualified
self-host compiler and working-tree reference compiler. It uses macOS arm64,
dev/debug output, eight native workers, and a fresh compiler/object cache followed
by five complete warm invocations per frontend. OS, SDK and package caches were
not controlled. Every invocation runs both owners through the actual
`make -f make/Product.mk btrsmith-native` entry point.

| Measurement | Self-host | Reference |
| --- | ---: | ---: |
| Cold complete Make build, one sample | 132.160 s | 352.890 s |
| Warm complete Make build, median of five | 13.316 s | 11.120 s |
| Warm native-builder wall, median of five | 2.835 s | 4.840 s |
| Warm link time, median of five | 0.301 s | 0.307 s |
| Reused objects / total on every warm run | 17 / 17 | 39 / 39 |
| Native compiles / links on every warm run | 0 / 1 | 0 / 1 |
| Complete emitted generation, including plan | 198,360,372 bytes | 322,523,755 bytes |
| Warm reported process peak RSS, median | 301.55 MiB | 670.98 MiB |

All warm compiler lookups hit, and each frontend's emitted generation remains
byte-identical across its six invocations. Recorded source/tool snapshots are
unchanged; the qualified compiler's 475-file snapshot and the seven product
file hashes were also checked independently. Peak RSS is per-process usage,
not aggregate simultaneous build memory. Different output paths affect source
mapping and generation bytes; do not compare these runs with earlier direct
compiler/native measurements as a controlled speedup.

Raw commands, timings, native reports, generated-file/executable identities and
provenance are in
`build/perf/product-validation-2026-09-21/run-xr_2imb2/results.json` and its
per-invocation logs. `build/plan-product-validation-measure.py` is the runner.
Tracing variables are removed before invoking tools so varying report names do
not alter the native compiler environment key.

Both warm medians exceed the **2 s** no-op goal. These samples do not qualify
p95, a cold distribution, edits, installed/pinned artifacts or other hosts.
Output write/link elision, lookup latency and concurrent different configurations
remain open. The old approximately 0.2 s Make shortcut is historical evidence,
not a valid current no-op result.

## Native translation-unit scheduling (2026-09-21)

The native builder previously completed the emitted-C worker pool before
validating/compiling each package source and generated adapter serially. These
are independent translation units. All now enter one pool bounded by `--jobs`;
report and linker object order remain the plan order, and linking waits for all
workers. The pool also joins outstanding work on failure before deleting its
private temporary inputs. Compiler arguments, dependency scans, cache keys and
publication rules are unchanged.

A comparison uses the actual product's emitted generations, separate native
object caches, one seed followed by five alternating warm baseline/candidate
pairs per frontend, and eight workers. The candidate was a separate copy of
the native builder, so production remained unchanged during the comparison.

| Native-only warm median | Previous scheduling | Shared pool | Reduction |
| --- | ---: | ---: | ---: |
| Self-host generation, 17 units | 3.090 s | 2.567 s | 0.523 s / 16.9% |
| Reference generation, 39 units | 5.102 s | 4.613 s | 0.489 s / 9.6% |

All warm runs have identical ordered object-cache keys, reuse every object,
compile none and link once. All recorded input hashes remain unchanged. This
supports retaining the simpler common scheduling path; it is not the complete
Make no-op KPI. The source/patch, runner inputs, raw reports and timing samples
are under `build/perf/native-scheduling-2026-09-21/`; the runner is
`build/plan-native-scheduling-measure.py`.

The existing native-builder baseline passes **116 tests**. A new process-barrier
regression first failed on the old schedule. On the retained change, **147
native-builder/performance-tool tests** pass, including eight real C/C++ cases
covering package sources and adapters, one/two workers, successful execution,
compiler failure, worker completion before cleanup and prior-output preservation.
Ruff lint/format and repository diff checks pass. Product checks pass again
under system Make 3.81 and GNU Make 4.4.1: 22 process-boundary, four generation
preservation and six real compiler/native cases per Make. Results are recorded
in `build/plan-native-scheduling-product-results.json`; final changed-file hashes
and the seven product-file hashes are in `build/plan-native-scheduling-qualified.json`.
Of the earlier 475-file qualified snapshot, 474 files remain unchanged and the
sole deliberate change is `tools/native_plan.py`; compiler pipeline sources and
the qualified self-host executable are unchanged.

The retained production change also passes five complete actual Make warm builds
per frontend using the original product generation/cache and unchanged ordered
native object keys. Every run invokes both owners, hits the compiler cache,
reproduces the recorded complete emitted-file hashes, reuses all native objects
and links once. Complete Make medians are **12.855 s self-host / 10.892 s reference**.
The earlier full-command medians were 13.316 / 11.120 s; these sequential runs
show a modest change and do not replace the alternating component comparison.
One reference follow-up took 11.482 s, illustrating variation beyond the
component gain. Source snapshots remained unchanged throughout the follow-up.
Raw evidence is in `build/perf/native-scheduling-2026-09-21/product/results.json`;
the runner is `build/plan-native-scheduling-product.py`.

Neither frontend meets the 2 s no-op budget. Cold-build distributions, p95,
body-edit timings, output write/link elision, cheaper lookup, concurrent
configuration binding, required hosts, aggregate memory and full release
qualification remain open.

## Compiler output retention (2026-09-21)

Both CLIs now retain an unchanged, complete owned output generation before
staging payloads. The reference publication port delegates to
`CompilerGenerationPublisher`; the self-host generation owner uses its existing
recovered `BtrccFilePublication` transaction. This is independent of compilation
cache lookup: a full `--no-cache` compilation can also produce unchanged output.

The decision requires the same output paths/roles and complete ownership record,
current file bytes and modes, and the ordinary source/path guards under the
publication directory locks. File revisions are checked while reading and
again after the complete set. Recovery precedes retention. Missing, changed,
permission-changed or unowned outputs use normal generation publication; no
cached metadata alone authorizes a no-op. Snapshot-close and lock-release
failures remain command failures. Device output retains its separate behavior
and does not allocate generation state.

The initial reference and self-host regressions both demonstrated unnecessary
publication. The first reference integration run caught device output creating
state during the retention probe; eligibility now excludes devices before
opening the generation owner. Final evidence on the resulting tree:

- **504 focused checks pass**, covering both compiler CLIs, complete artifact
  caches, publication/recovery, source I/O and durability. New cases verify
  complete split outputs, inode/mtime preservation with and without compiler
  cache hits, byte-identical source touches, same-timestamp output corruption,
  missing files, modes/ownership, source changes after a directory-lock wait,
  an earlier output changing during the complete-generation check, and
  retention snapshot-close failures through both generated frontends.
- **23 architecture checks pass.** Ruff lint/format, canonical Driver formatting,
  generated-source checks and repository diff checks pass.
- **23 publication/cleanup scenarios per frontend pass under both actual GCC
  15.2 and Apple Clang at strict C11/-O2/-Wall/-Wextra/-Werror.** These include
  retention and existing source, recovery, read/close and lock-release faults.
- The product checks pass under system Make 3.81 and GNU Make 4.4.1: 22 process
  cases, four generation-preservation cases and six actual compiler/native
  cases per Make. The latter now assert unchanged output and ownership-manifest
  inodes/mtimes while Make still invokes native dependency validation.

The self-host compiler was built from the frozen current sources using the
previous qualified self-host compiler, then strict Apple Clang C11/-O2. Its
SHA-256 is `f6d4c15c82ab1134bb66b1dcf9a5efbcf8d0a1f50c6a9dabfd00491fdddf2ecd`.
Inputs, commands and generated-C identity are recorded in
`build/plan-retain-snapshot.json`; final source/test/product evidence is in
`build/plan-retain-qualified.json`. Detailed results are
`build/plan-retain-{integration,structure}.xml`,
`build/plan-retain-product-results.json` and
`build/plan-retain-c11-{reference,selfhost}.json`.

The actual Make benchmark completed successfully through
`build/plan-retain-product-measure.py`, with raw output in
`build/perf/product-retention-2026-09-21/run-hdp_zbo5/`. One fresh cold build and
five warm builds per frontend verify byte identity and retained inode/mtime/mode
for the complete emitted generation and ownership manifest, as well as compiler
and native-object hits. All recorded source/tool inputs stayed unchanged.

| Frontend | Cold sample | Warm median (5 samples) | Warm native compiles |
| --- | ---: | ---: | ---: |
| Self-host | 135.512 s | 12.915 s | 0 |
| Reference | 360.260 s | 10.608 s | 0 |

Each warm invocation still calls both owners for fresh validation and links
once. The preceding 12.855 / 10.892 s medians and these sequential measurements
do not establish a retention speedup. Neither frontend meets the 2 s no-op
budget. These are local development-build diagnostics with uncontrolled OS/SDK
caches; required-host distributions, edit/cold acceptance, aggregate memory and
the full compiler/product release matrix remain open.

A subsequent instrumented self-host cache-hit probe is recorded in
`build/perf/warm-profile-2026-09-21/`. The immediate sampler could not attach;
the delayed sampler succeeded and observed 1,423 of 1,658 late-stage samples
inside SHA256 compression, primarily while the generation owner computes output
hashes. This is a sample of the publication tail, not a whole-build percentage
or a speedup estimate. It identifies repeated output hashing as another measured
candidate after the native-resolution investigation.

## Shared native declaration index (2026-09-21)

The current BTRSmith SDK workload has 41 independent selections in 16 header
groups. Batching already shares each Clang parse, but each semantic reader was
still traversing and indexing the entire translation unit. An instrumented
scratch build measured 0.587–0.602 s across those 41 traversals.

`NativeHeaderIndex` now builds one declaration/Objective-C/C++ lookup index per
translation unit. Readers borrow a const view for the duration of semantic
extraction. The union of requested names filters indexing only; each reader
retains its own selected symbols, record-value permissions, record paths,
layouts, interfaces and diagnostics. Ambiguities retain declaration order and
are reported only to requests that selected the ambiguous name. A record path
must select its own root even when another request indexed that root.

Five alternating measured pairs, after a warmup pair, reduce the isolated
reader-process median from **3.227 to 2.759 s (14.5%)**. Every response matches
the original reader's decoded JSON exactly. This is an SDK-reader component
comparison, not a complete build-speed claim. Raw current request captures,
instrumented traversal results and paired samples are in
`build/perf/native-traversal-2026-09-21/`; the scripts are
`build/plan-native-{traversal,index}-measure.py`.

Six new checks cover request-order independence for record-path authorization,
C++ ambiguity scope/order, and Objective-C implicit accessors with distinct
class/protocol namespaces. The old reader passes all 27 batch checks excluding
the separate codec fixture. The final reader builds through its Nix package
with C++17/-Wall/-Wextra/-Werror.

Broader qualification exposed SDK discovery selecting Nix's unavailable
`xcrun`; the runner now selects the real `/usr/bin/xcrun`. After that repair,
consumer failures were reproduced with the original reader: the private-field
negative fixture used a forbidden positional initializer, the pixel-readback
fixture omitted the now-explicit capture option, and the existing GPU view
called through a nullable field immediately after constructing its renderer.
The fixtures now use empty initialization and explicit capture; the consumer
calls through its nonnullable local owner. A fresh strict C11/O2 self-host build
produces byte-identical generated C and the same compiler executable hash as
the prior qualified compiler. Its 475-file snapshot is recorded in
`build/plan-native-index-snapshot.json`.

The next broad run passed 1,713 cases, including all eight actual GPU capture
cases and 20 private-storage checks, before exposing two further stale fixture
expectations. The original reader reproduced both: the closed-prelude package
already exports `MacOSRunLoop`, and current AppKit hit testing can return a
private child inside a slider. Tests now prove the published run-loop import,
include and group-export paths while retaining private-provider negatives.
The slider fixture converts its local point and accepts only the control or its
descendants; actual enabled/disabled tracking assertions remain. All **28**
focused visibility/slider checks pass on both frontends, including sanitized
slider executions. Ruff lint/format, canonical BTRC formatting and diff checks
pass. The final five-module native suite passes **2,512 tests, zero skips, in
1,117.78 s**, using the packaged reader and fresh self-host compiler. The runner
verified the source/test fingerprints after execution; the subsequent product
measurement also verified all 475 frozen compiler/tool inputs before starting.
Evidence is `build/plan-native-index-integration-final2.xml` and
`build/plan-native-index-qualified.json` (return code 0). This qualifies the
native reader and consumer regression scope; it does not replace the full
compiler/bootstrap/C11/release matrix.

The actual Make follow-up at
`build/perf/native-index-product-2026-09-21/run-453u_k8i/results.json` completes
all 12 builds with no failure and unchanged before/after source/tool identities.
Each frontend has one fresh cold build and five warm builds. Every run makes
one compiler/native invocation and one link; the expected compiler miss/hits,
zero warm native recompiles, identical complete generated bytes and retained
output/manifest metadata all pass.

| Frontend | Cold build (one sample) | Warm build median (five samples) | Warm native wall median | Warm link median |
| --- | --- | --- | --- | --- |
| Self-host | 131.744 s | 11.887 s | 2.217 s | 0.287 s |
| Reference | 346.838 s | 9.695 s | 4.272 s | 0.304 s |

Warm medians are below the preceding 12.915 / 10.608 s retention run. The runs
were sequential, so they do not isolate the SDK index's contribution; only the
separate paired reader experiment supports its 14.5% component gain. Both
whole-build medians miss the 2 s goal, and both still link. Link elision alone
cannot close the gap. Local tool overrides and uncontrolled OS/SDK caches still
prevent installed/pinned or required-host qualification. No fresh edit-build,
p95 or simultaneous aggregate-RSS acceptance is established by these samples.

The final Nix reader also reproduces all 41 original BTRSmith semantic documents
exactly (`build/perf/native-traversal-2026-09-21/final-semantics.json`).

## Boundary result volatility experiment (2026-09-21)

The late publication profile points to SHA-256. Its generated compression loop
has eight volatile scalar result slots solely because exception support is
enabled elsewhere in the program. The call-boundary owners in both compilers
previously qualified every result whenever exception cleanup was enabled,
including expressions with no cleanup after evaluating the result.

The bounded change retains the typed result temporary and operand ordering,
but only applies that blanket qualification when a cleanup suffix follows.
Without a suffix, operand effects precede the assignment and the stored value
is consumed immediately. Managed results still register their own volatile
cleanup slots; the existing setjmp planner still qualifies storage crossing an
actual capture. Source-declared volatile types remain intact. There is no
digest memoization or pointer-identity shortcut.

An isolated source-mirror experiment compiles a 128 MiB SHA-256 workload through
the baseline and modified reference compiler, checks every digest, and runs the
existing SHA-256 vector corpus under strict C11/-O2 with actual Clang and GCC.
Both variants pass. After a warmup pair, five alternating measured pairs yield:

| Native compiler | Baseline median | Candidate median | Reduction |
| --- | --- | --- | --- |
| Apple Clang | 1.171 s | 0.630 s | 46.2% |
| GCC 15.2 | 1.455 s | 0.923 s | 36.5% |

The generated compression body has eight volatile result slots before and zero
after. Peak process RSS stays approximately 2.8 MiB in this small workload.
Artifacts and source fingerprints are in
`build/perf/boundary-result-2026-09-21/results.json`; the experiment driver is
`build/plan-boundary-result-probe.py`. These are component measurements from
reference-generated C, not new BTRSmith or self-host compiler timings.

Both production call-boundary owners now contain the change. Four existing
baseline call-result/ownership checks pass with GCC/-O2. A new regression proves
that throwing argument cleanup prevents scalar result delivery, and that an
owned result without a suffix retains its protected slot and is destroyed once;
it passes against the old self-host and modified reference compiler at -O2/-O3.
The scalar `fchmod` regression now requires a nonvolatile result when no suffix
exists, including inside a try body.

The fresh self-host compiler builds through two self-compilation/native stages
under strict Apple Clang C11/-O2. Qualification passes six result-storage smoke
checks, a **276-check** call/ownership/setjmp matrix, **46** additional Clang
checks and the SHA-256 corpus through both frontends with GCC/-O2 and Clang/-O3
(two cases each), with zero skips. The initial matrix stopped after 177 passes
on a unit expectation that all exception-enabled results were volatile. That
unit now checks all four exception/suffix combinations, exact result type and
assignment → cleanup → delivery order; no further production change was needed.
The final source/test snapshots are unchanged. Evidence is
`build/plan-boundary-qualified.json` and its five referenced JUnit reports.

The rebuilt compiler then emits byte-identical C when compiling itself again:
SHA-256 `0d44bf51975fc7b51e02af2f7fe0f5c211e68db65569088e82e6485a289ac4bb`.
That check took 66.944 s, one diagnostic sample, and verified stable source
inputs (`build/plan-boundary-fixedpoint.json`). It establishes the generated-C
fixed point for this snapshot; it does not replace the full `make bootstrap`
or final compiler/C11/release matrix.

Actual Make cold/warm timing completes all 12 builds at
`build/perf/boundary-product-2026-09-21/run-7ctlfooc/results.json`, with no failure
and unchanged before/after source/tool identities. The complete cache,
operation-count and output-retention assertions from the prior reader run all
pass: one compiler/native invocation per build, expected compiler miss/hits,
zero warm native recompiles, one link, identical generated bytes and retained
output/manifest metadata.

| Frontend | Cold build (one sample) | Warm build median (five samples) | Warm native wall median | Warm link median |
| --- | --- | --- | --- | --- |
| Self-host | 127.646 s | 10.377 s | 2.366 s | 0.297 s |
| Reference | 349.113 s | 9.649 s | 4.277 s | 0.305 s |

The prior reader-index run measured 11.887 / 9.695 s warm medians. These are
sequential whole-product observations, not a paired attribution of the storage
change's effect; the isolated hashing experiment establishes its component
gain. Both current build medians still exceed 2 s and both still link. Local
tool overrides and uncontrolled OS/SDK caches remain; edit-build, p95,
required-host, pinned/installed and aggregate-RSS acceptance are still open.

A current warm self-host trace records 3.571 s in native binding resolution,
1.359 s in source-graph resolution and 1.244 s loading cached artifacts. This
is one phase trace, not an additional timing distribution; publication and the
native builder also contribute to total time. Avoiding the remaining 0.3 s link
alone cannot close the no-op gap.

## Link dependency capability probe (2026-09-21)

A six-link fixture exercised Apple Clang and the product's Nix Clang with
Darwin `-dependency_info`. Both record the selected archive and the missing
candidate in an earlier search directory. Adding that earlier archive changes
the executed program from 1 to 2; replacing it while preserving size and mtime
changes the program to 3 and changes its content digest. Apple records 78 input
rows and initially 351 missing candidates; Nix records 41 and 511 respectively.
The records include duplicates, so these are row counts, not unique files.
Every resulting executable passed. Raw records, driver expansions and tool
identities are in `build/perf/link-dependencies-2026-09-21/results.json`; the
fixture is `build/plan-link-dependencies-probe.py`.

This proves a useful dependency-reporting capability, not a complete reusable
link identity. Fresh ordered object contents, driver/linker/toolchain identity,
flags, actual input contents, missing candidates and path bindings still need
to be composed and validated. The Nix driver expansion names a linker wrapper;
its support scripts and final link arguments must be accounted for as well.
Response/file-list/plugin inputs cannot silently receive ordinary-file coverage.
No executable cache or skip-link implementation is qualified by this probe.

## Native debug input lifetime (2026-09-21)

During M6a's link-input audit, actual BTRSmith development executables exposed
a lifetime defect: `dsymutil --dump-debug-map` reported 17 missing objects for
self-host output and 39 for reference output. `NativePlanBuilder` linked the
objects from its temporary directory, then removed that directory. A minimal
real LLDB regression reproduced the result: symbol names existed but source
line lookup and a line breakpoint did not resolve after the build returned.
This is a prerequisite repair for retaining/reusing development executables.

The existing native builder now publishes complete immutable debug-object
generations beside the executable before linking Darwin debug builds. The
identity covers every object name and content digest; retained files have a
fixed, nonzero timestamp matching the linked debug map. Fresh content and
metadata checks validate reuse. A corrupt/foreign generation is never repaired
in place; a private generation supplies the new executable. The build output
directory owns these files, so optional object-cache eviction cannot strand a
debugger. Generated adapter sources also remain available when debug builds
have caching disabled or take the fallback path. Publication failure preserves
the previous executable. Normal build-directory cleanup removes these artifacts.

Baseline native-builder qualification passed 124 tests. The new real debugger
case failed against that baseline. Final qualification passes **165 tests with
zero skips**, covering native-builder/performance reporting and 18 debug cases.
The latter exercise cached/uncached builds, source/line lookup and breakpoint
resolution through LLDB, content/timestamp/missing/linked/empty-generation
corruption, concurrent callers, changed builds, publication failure and output
collision protection. Both actual frontends emit split debug programs that
remain source-debuggable after cache deletion; `dsymutil` can also produce
standalone symbol bundles. Evidence: `build/plan-debug-retention-{baseline,red,final}.xml`
and `src/tests/python/test_native_debug_artifacts.py`.

Product Make checks pass with both system Make 3.81 and GNU Make 4.4.1:
22 process-boundary, four preservation and six actual compiler/native scenarios
each. The subsequent actual Make diagnostic passes all 12 invocations (one seed
plus five warm samples per frontend), with unchanged recorded production/test
inputs. Every invocation hits the compiler cache, reuses every native object
and links once. Emitted output and ownership-manifest bytes/inodes/mtimes/modes
stay unchanged, as do retained debug-object bytes/inodes/timestamps. LLDB resolves
BTRSmith source lines through both full product executables; `dsymutil` reports
no missing objects. The checked debug generations occupy 34,418,448 bytes for
17 self-host objects and 41,935,952 bytes for 39 reference objects. They remain
build artifacts until build-directory cleanup; no automatic retirement is claimed.

| Frontend | Warm actual Make median | Samples | Native compiles / links per warm build |
| --- | --- | --- | --- |
| Self-host | 10.141 s | 5 | 0 / 1 |
| Reference | 9.796 s | 5 | 0 / 1 |

Evidence is `build/perf/debug-retention-2026-09-21/results.json`, its Make logs,
full debug maps and LLDB transcripts; runner `build/plan-debug-retention-product.py`.
The prior checkpoint measured 10.377 / 9.649 s. These sequential observations
establish no speedup attributable to this correctness repair. Local overrides,
uncontrolled OS/SDK caches and one macOS host remain; no new cold/edit/p95,
installed-product or required-host acceptance is claimed. Link reuse and the
2 s no-op goal remain open, as does the final compiler/bootstrap/C11/release
matrix.


## Darwin executable reuse (2026-09-21)

`NativePlanBuilder` now retains an unchanged executable after verifying a Darwin
link receipt. The existing output-parent publication lock covers validation,
linking and publication, including callers with different configurations/caches.
The identity includes the Clang-expanded command, ordered object content and
configuration, compiler/linker/wrapper support and actually loaded toolchain
images, environment, search-root bindings and final executable content/mode.
Darwin dependency-info records supply selected inputs and missing search
candidates. A discovery link followed by a verification link, bracketed by fresh
input snapshots, admits the receipt. Unknown options, response files and
unqualified wrappers use ordinary linking; non-Darwin reuse remains open.
Cold/changed supported builds normally link twice; hits link zero times.

Focused qualification passes **185 tests with zero skips** in
`build/plan-link-reuse-final2.xml`, including 20 new receipt cases and the prior
real LLDB/dsymutil cases. Tests execute changed libraries, newly earlier search
candidates/directories and retargeted aliases; preserve size/mtime while replacing
libraries and compiler executables; exercise corrupt output/receipts, failed or
mutating verification links, debug/release reuse, actual Nix wrappers and
concurrent configurations with shared/separate caches. Performance reporting
now displays measured link counts; its additional Markdown assertions pass
both frontend cases in `perf-report-tests.xml` under the evidence directory.
Both system Make 3.81 and GNU Make 4.4.1 pass the 22 process-boundary, four
preservation and six actual-build cases. The actual-build cases now require
unchanged and byte-identical-touch builds to retain executable identity and
perform zero links on macOS.

The product runner completes **24 native-only builds** (seeds plus five
alternating pairs per frontend) and **12 actual Make builds** (one seed plus
five warm each). All recorded inputs remain unchanged. Every warm build reuses
all objects with identical keys; candidate warm builds perform zero links and
retain executable bytes/inode/mtime. Actual Make also retains compiler artifacts,
emitted-generation bytes and ownership metadata. Both complete product debug
maps remain valid with no missing objects. Evidence:
`build/perf/link-reuse-2026-09-21/results.json`, associated command logs/reports,
`build/plan-link-reuse-measure.py` and `build/plan-link-reuse-qualified.json`.

| Frontend | Native baseline median | Native receipt median | Actual Make warm median | Warm links |
| --- | ---: | ---: | ---: | ---: |
| Self-host | 2.617 s | 2.631 s | 10.293 s | 0 |
| Reference | 4.663 s | 4.732 s | 9.810 s | 0 |

There is **no established elapsed-time gain**. Median link validation costs
0.331/0.347 s, replacing baseline link medians of 0.307/0.322 s. Native process
peak RSS medians fall from 178,976/187,744 KiB to 94,384/96,000 KiB; these are
process peaks, not aggregate native/full-build memory. No fresh cold/edit/p95
or required-host acceptance is established. Prior cold results precede both
debug retention and receipt admission's extra link. Full compiler/bootstrap/C11
and product release qualification remain open.

A subsequent instrumented hit isolates receipt costs without changing production
code: context takes 0.288/0.300 s and dependency/output validation 0.035/0.034 s.
All file hashing totals 0.167/0.170 s; the largest inputs, libLLVM and
libclang-cpp, are each read once (about 0.071/0.032 s). Duplicate digest reuse
therefore has little justification. The profile is
`{selfhost,reference}-validation-profile.json` in the evidence directory,
produced by `build/plan-link-cost-probe.py`. These are single diagnostic samples,
not additional performance acceptance runs. The larger current self-host SDK
validation stage is about 3.7 s, so the next bounded experiment examines
independent reader-group scheduling with identical semantic results.


## Independent SDK-reader scheduling experiment (2026-09-21)

The current packaged reader replayed the actual 16 BTRSmith translation-unit
groups (41 selections), using the captured product commands, stdin and SDK
environment. One warmup pair followed by **five alternating pairs** compares
serial execution with at most four independent reader processes. Every decoded
response matches the captured semantic document, and collection retains request
order. Recorded source, reader and request identities remain unchanged.

| Isolated SDK workload | Serial | Four readers |
| --- | ---: | ---: |
| Median elapsed time, five samples | 2.808 s | 0.907 s |
| Sampled maximum sum of reader RSS, separate diagnostic | 137.5 MiB | 430 MiB |

This is a **67.7% component elapsed-time reduction**, with increased concurrent
memory. The RSS diagnostic samples live reader processes every 50 ms; it is a
lower bound on true peak and excludes compiler memory and retained response
buffers. It does not qualify full-build memory. Sources and commands are in
`build/plan-native-reader-concurrency.py` and
`build/plan-native-reader-memory.py`; raw timings, ordered result digests and
memory samples are in `build/perf/native-reader-concurrency-2026-09-21/`.

Production was serial during this experiment. The measured next M6a change is bounded
independent reader dispatch through the existing host-capability boundary in
both compilers. Preserve declaration/diagnostic order, selection authority,
per-request stdout/time allowances, unsupported-host behavior and reader identity
validation. Bound pending results as well as live processes; a large allowed
response must not multiply into unbounded buffering. Exercise out-of-order
completion, earlier/later failures, timeouts, oversized groups, NUL rejection
and complete child cleanup with real processes. Rebuild the self-host compiler,
run native/consumer regressions and measure actual Make plus aggregate memory
before claiming any product speedup. This schedules input validation within
M6a; it does not advance to M10's compiler-stage parallelism.


## Bounded SDK-reader dispatch implementation (2026-09-21)

Both compilers now schedule independent reader groups in bounded synchronous
waves. The self-host host capability borrows a `FeNativeHeaderBatch`, whose
admission rule permits up to four reads and 128 MiB of combined stdout/stderr
allowances. A larger individually valid request is admitted alone, preserving
the existing per-selection allowance and 255-selection partition on self-host
int32 process captures. The Unix provider uses scoped local thread owners and
completes every request before returning; native semantic code remains independent
of Unix process APIs. Single toolchain probes use the same capability.

The reference frontend uses the same wave policy, with file-backed process
capture before bounded decoding. Timeout cleanup kills and reaps the process
group on POSIX. Each frontier is fully joined before semantic consumption.
Responses and exceptions remain attached to their original declaration, so
out-of-order completion cannot move a later error ahead of an earlier binding.
Unread groups stay within one wave; existing per-group selection results retain
their original ownership. No cross-build SDK-result cache was introduced.

The baseline passes 40 existing native-batch consumer checks. The new barrier
fixtures pass through the reference implementation and reproduce three failures
against the old serial self-host compiler. A four-process native smoke program
also passes. The rebuilt self-host compiler passes both strict C11/-O2 native
compiles; stage self-compilation times are 66.410/67.508 s and native compile
times 99.485/99.187 s. The two generated C files are byte-identical. Compiler
SHA-256 is `d5ecda2ca6c7a67db7c74f63520e1b9574d8425f1e60466bc0bf2e3cf079d17c`;
source snapshot and commands are in `build/plan-sdk-dispatch-snapshot.json`.
These build timings are diagnostics, not compiler KPI acceptance.

Focused qualification passes **68 tests with zero skips**, covering existing
batch semantics plus real concurrent starts, bounded waves, oversized groups,
first-error ordering, stdout overflow, NUL rejection, timeout and descendant
cleanup through both frontends. Structure/bootstrap checks pass **27 tests**,
with the native Windows executable-release check skipped on macOS. Evidence:
`build/plan-sdk-dispatch-{focused,structure}.xml`,
`build/plan-sdk-dispatch-qualified.json` and the retained initial failure logs.
The final fixtures use explicit managed copies of argv strings; an earlier
fixture compilation also hit the source-change guard and passed on the stable
fixture. Production source hashes remain unchanged during qualification.

The first broader run recorded 2,369 passes and one failure before it was
interrupted to inspect that failure. The C++ test runner supplied `env` twice
when link-receipt validation added loader tracing. Its environment adapter now
accepts supplied probe settings while preserving the Apple toolchain environment
filter. No production change was required. All **21 C++ owner tests** pass,
including explicit two-link admission and zero-link warm reuse through both
frontends. Evidence is `build/plan-sdk-dispatch-integration-initial.{xml,log,json}`
and `build/plan-sdk-dispatch-cxx-repair.xml`.

The next integration run recorded **2,424 passes and two failures** before
interruption; the same environment-forwarding collision occurred in the AppKit
test adapter. Both adapter call sites now preserve supplied probe settings and
the existing Apple environment filter. No production change was required.
All **20 AppKit runtime cases pass in 84.78 s**, through both compilers with and
without sanitizers. The failed run is preserved in
`build/plan-sdk-dispatch-integration-app-runner-failure.{xml,log,json}`.
The repaired suite evidence is in
`/Users/alexanderschiffhauer/.cache/btrc/perf/sdk-dispatch-2026-09-21/app-runner-repair.{xml,log}`.

**Integration qualification is complete: 2,520 passes, zero skips.** It retains
2,420 passed cases from unchanged suites, replaces the affected suite with its
20 fresh passes, and completes all 80 remaining cases (120.53 s). Every worker
collected the same 2,520 cases, and the exact union of passing node IDs equals
that collection. Production/test input hashes stayed unchanged. The original
failed reports remain separate; this is composite coverage, not a single green
run. `build/plan-sdk-dispatch-integration.json` records the result and links the
original report, repaired-suite report, resumed report and complete coverage XML
under the local cache's `integration-resume/` directory.

All six BTRSmith Make check invocations pass: BuildInputs, BuildGeneration and
BuildArtifacts under system Make 3.81 and GNU Make 4.4.1, with unchanged inputs.
An initial runner hit a Google Drive log-write timeout after BuildInputs passed;
its result is preserved, and diagnostic output now resides in the local cache
via `build/perf/sdk-dispatch-2026-09-21/product`. The resumed checks passed.
Actual BTRSmith Make measurements and aggregate-memory diagnostics are
complete, as recorded below. Their input record includes both repository
revisions, BTRSmith's tracked/untracked source inputs, the compiler snapshot and
integration qualification inputs. The isolated 67.7% reader gain is not the
full-build improvement; M6a and its two-second no-op goal remain open.

## Bounded SDK dispatch product measurement (2026-09-21)

`build/perf/sdk-dispatch-2026-09-21/product/results.json` records all 12 successful
actual `make btrsmith-native` invocations: one seed and five warm builds per
frontend, followed by two separate full-process-tree memory diagnostics.
The result has no failure and validates unchanged compiler/product/test inputs.
The source compiler is the qualified `d5ecda2c…` self-host above, compiler HEAD
`4e5c9823` and BTRSmith HEAD `5549c261`, including the recorded working-tree
inputs. This is local macOS evidence with overrides, not pinned/installed or
required-host qualification.

| Measurement | Self-host | Reference |
| --- | --- | --- |
| Warm actual-Make median, 5 samples | 9.222392 s | 9.042520 s |
| Previous sequential warm median | 10.293138 s | 9.809639 s |
| Gap above the ≤2 s goal | 7.222392 s | 7.042520 s |
| Warm native-only portion median | 2.286590 s | 4.427826 s |
| Warm native object reuse | 17/17 | 39/39 |
| Warm compiles / links | 0 / 0 | 0 / 0 |
| Sampled complete-process-tree peak | 714.219 MiB | 686.141 MiB |

Every warm invocation has exactly one compiler and one native-plan invocation;
compiler cache hits, all object hits, link receipt hits and complete generation/
ownership/executable byte, inode, mtime and mode retention are asserted. Both
full-product `dsymutil --dump-debug-map` checks pass without missing-object
messages. Native validation remains a substantial part of the elapsed time.
The memory checks sample every 50 ms (115 self-host / 114 reference samples);
their maxima are lower bounds on true peak and are not timed acceptance runs.

The seed samples are 15.079 s self-host (compiler cache hit) and 354.883 s
reference (compiler cache miss); both compile every native unit and perform
two links to admit a receipt. They are not a controlled cold-build series.
Before the successful run, the first self-host seed transpiled successfully but
native building rejected the symlinked report directory. Its logs/result are
preserved as `report-path-failure-*` in the evidence folder and
`product-report-path-failure.log` in its parent. The runner now passes the real
local-cache report path; production validation was unchanged.

Self-host warm phase medians are 2.579 s for native SDK resolution, 1.304 s for
source-graph resolution and 1.251 s for artifact identity/loading. Separate
instrumented Make diagnostics live in the local cache's `profiles/` directory.
Self-host warm sampling completes with compiler/object hits, zero compiles/links
and output retention. Its call graph shows roughly 730 samples each in cached
payload SHA validation and publication's second SHA pass, over about 188 MiB of
generated output. These are stack samples, not elapsed-time savings. The next
bounded candidate is to carry verified content/digest pairs between those owners,
without trusting caller-supplied hashes, caching borrowed pointer addresses,
dropping current-file validation or duplicating the whole payload in memory.
It requires an isolated comparison and ownership/corruption/publication checks
before adoption. An isolated `ArtifactDigests.btrc` prototype now passes through
both compilers under strict Apple Clang C11/-O2, and both generated executables
also pass address/undefined sanitizers. It verifies equal-length and long-to-short
replacement, null/empty and Unicode inputs, separate inventories, source-value
replacement, a copied byte buffer being mutated/freed, and rejection of a wrong
claimed digest. The inventory owns immutable managed text and constructs each
digest itself; it accepts no caller-provided digest. Evidence is in
`/Users/alexanderschiffhauer/.cache/btrc/perf/artifact-digests-2026-09-21/`.

The implemented composition keeps this inventory in the CLI: one compilation shares
it between `BtrccArtifactCache` and `BtrccGenerationOwner`, leaving mutable pipeline
result transports unchanged. Every lookup compares the actual current payload
with the owned text before reusing a digest. Failed cache loads must clear the
inventory before fallback compilation, so corrupt cached payloads do not extend
their lifetime into a fresh compile. Direct callers that do not explicitly share
an inventory retain the existing hashing path. The rebuilt compiler passes two
strict Apple Clang C11/-O2 self-host stages with byte-identical generated C and
unchanged source inputs. Its SHA-256 is
`795cb8db789cc708b3f2bdf51f7c2951cb6bff689ad17f0c7f876afd99e67631`.
Cache/publication qualification using this compiler passes 181 cases with one
SDK skip in 240.10 s. The skipped native-header invalidation case passes separately
with the reader explicitly configured (3.36 s). This includes both frontends'
digest replacement, Unicode, clearing, preserved-mtime output corruption and
cache tail/digest corruption cases. Evidence is `checkpoint-tests.xml` and
`checkpoint-sdk-test.xml` beside the experiment reports. Broader regression
qualification remains pending; the actual-product comparison below now measures
this implementation. This is a work-in-progress checkpoint, not final M6a acceptance.

`build/plan-artifact-digest-probe.py` completed 48 executions against the actual
197,096,694-byte emitted C payload through both frontends and GCC/Clang: one
warm-up pair and five alternating measured pairs per combination. All expected
digests match, the inputs remain unchanged and the report records no failure.

| Frontend / native compiler | Two SHA passes, median | Owned digest reuse, median |
| --- | --- | --- |
| Self-host / Clang | 1.828232 s | 0.919560 s |
| Reference / Clang | 1.833418 s | 0.920292 s |
| Self-host / GCC | 2.675637 s | 1.348219 s |
| Reference / GCC | 2.735642 s | 1.370118 s |

Median peak RSS stays approximately 209–211 MiB in both variants. These are
component measurements, not a whole-build speedup or required-host memory
acceptance. A roughly 0.9 s Clang component saving leaves most of the seven-second
gap to the no-op target. PLAN.md now allocates explicit budgets to SDK validation,
native validation, source resolution, publication and orchestration.

The reference/native profile run completed with unchanged inputs, warm cache
hits, zero native compiles/links and retained outputs. The warm reference profile
records 5.713 instrumented seconds: 2.047 s sleeping, 291,800 lstat calls,
116,643 stat calls and 24,216 realpath calls. The native command profile records
6.538 instrumented seconds; a separate serialized replay of 39 native probes
matches every actual cache key and records 14.952 instrumented seconds, including
10.999 s polling subprocesses. Serialized replay is not parallel native-command
elapsed time. SDK waits, repeated path checks and subprocess validation remain
larger opportunities than reference-compiler hashing.

Profiling wrappers alter Make
configuration identity, so their first invocation seeds that configuration;
only the subsequent hit is the warm diagnostic. The first reference cold seed
was unnecessarily instrumented and was deliberately interrupted with SIGINT;
its partial cProfile and failure record are preserved in
`profiles/interrupted-cold-profile/`. The runner now seeds without instrumentation
and profiles only warm hits, retaining the already completed self-host evidence.
This was a correction to diagnostic scope, not an observation-timeout restart.
The partial cold profile records 4,788,736,524 calls over 1123.088 instrumented
seconds; it is incomplete and cannot establish a cold-build KPI. It identifies
repeated generic-parameter scans in `CallLowerer._binding_conflicts_with_type`
as an M7 candidate, alongside expensive IR traversal. That work stays queued. Initial failed diagnostic
attempts remain in `profiles/unseeded-attempt` and
`profiles/missing-timing-marker`; the latter missed the original wrapper's
`BTRC_TIMING=1` marker and did not prove a compiler miss. The driver now preserves
that marker. The diagnostic runs do not replace the successful benchmark.
Five warm samples and sequential historical runs do not establish p95,
required-host acceptance or an isolated causal effect. No headline build KPI
is yet proven met.

### Owned digest reuse: actual Make comparison (2026-09-21)

The production composition removes one repeated payload digest pass on cache
hits. On the actual BTRSmith development Make command, five alternating pairs
measure **9.035265 s baseline → 8.341154 s current medians**, a **0.694111 s
(7.7%) reduction**. All five individual pairs favor the new compiler. This is
less than the isolated ~0.9 s digest saving; retain the whole-command result as
the product evidence.

| Measurement | Self-host baseline | Self-host with owned digests | Reference control |
| --- | --- | --- | --- |
| Warm Make median, five samples | 9.035265 s | 8.341154 s | 9.168521 s |
| Native command median | 2.246122 s | 2.341902 s | 4.413353 s |
| Native objects reused, every warm run | 17 / 17 | 17 / 17 | 39 / 39 |
| Native compiles / links, every warm run | 0 / 0 | 0 / 0 | 0 / 0 |

The compiler variant changes behind one stable recording wrapper, so both
self-host variants use the same Make arguments, output paths and environment.
Each variant is seeded before timing; pair order alternates. Reference runs
form a control series after its seed; the Python implementation is unchanged
by this digest change. Do not attribute its difference from the historical
9.043 s median to this implementation. Every measured warm run hits the compiler
cache and preserves the generated files, ownership record and executable bytes,
inodes, mtimes and modes. Both executable debug maps remain complete.

The runner completes **18 builds** (three seeds and 15 measured warm runs), six
product check invocations under system/GNU Make, and two separate process-tree
memory diagnostics. Source, test, tool and product input hashes remain unchanged;
the report records no failure. Current sampled peaks are **725,728 KiB
(708.7 MiB) self-host / 705,760 KiB (689.2 MiB) reference**, over 101/111 samples.
These 50 ms samples are lower bounds on true process-tree peaks, not exact or
required-host memory acceptance.

Current self-host phase medians are **2.614961 s SDK**, **1.284844 s source
graph**, and **1.276784 s artifact identity/load**. Baseline medians are
2.552549 / 1.271479 / 1.251117 s respectively. The digest removed from publication
was outside those phase timers; the remaining multi-second SDK/native validation
costs still dominate the path to two seconds. Phase medians are not an additive
decomposition of the median Make wall time.

Seed costs are 14.591 s for the baseline (compiler hit, native admission),
120.270 s for the new self-host (compiler miss), and 351.272 s for reference
(compiler miss). These seed conditions differ, and there is only one sample
each; they are not a controlled cold-build comparison. The final no-op gaps
remain **6.341 s / 7.169 s**. Five warm samples do not establish p95 or
required-host acceptance.

Evidence is in
`/Users/alexanderschiffhauer/.cache/btrc/perf/artifact-digests-2026-09-21/product/`:
`results.json`, per-build stdout/stderr, native reports, invocation traces,
debug maps and Make check logs. `build/plan-artifact-digests-product.py` records
the commands and verifies output/input retention. The current self-host binary
SHA remains `795cb8db789cc708b3f2bdf51f7c2951cb6bff689ad17f0c7f876afd99e67631`.
Qualification after timing passes **156 CLI/structure/frontend-I/O tests with
two platform skips**, and **11 GCC digest/corruption/publication tests with no
skips**, with unchanged input hashes. The skips require `/dev/full` and native
Windows executable-release behavior. Evidence is in the sibling
`qualification-repaired/` directory. Generated-source, lint and Python-format
checks also pass (599 files already formatted).

The original qualification attempt stopped after 116 passes when the structural
audit incorrectly classified `BtrccArtifactDigest.matches` as unused. Its
receiver inference discarded generic arguments on member access and treated
`Map.get` as returning the key type. The repaired audit preserves collection
types through fields, methods and inferred locals, and a new regression checks
map values and vector elements independently. No method was exempted; production
code and the measured binary stayed unchanged. The initial failure remains in
`qualification/` rather than being overwritten. The full final-tree and
required-host matrix remains open.

### SDK validation feasibility (2026-09-21)

The SDK experiments replay the actual 16 reader groups / 41 selections. They
do not change production behavior or the **8.341 / 9.169 s** Make medians.
The production scheduler allows four readers and 128 MiB combined capture,
with an oversized group running alone. These requests form five waves; the
24-selection AppKit group has a 200 MiB allowance and runs alone. First-fit
packing produces the same waves. Dropping capture constraints is not an
equivalent optimization.

| Isolated experiment | Median | Evidence / scope |
| --- | --- | --- |
| Actual reader, production waves | 1.936544 s | Five measured runs after warmup; all semantic documents match |
| Unconstrained four-worker reader | 0.914271 s | Diagnostic only; does not preserve production capture constraints |
| Serial reader | 2.932057 s | Diagnostic control |
| Full AST reader in preprocessing comparison | 1.905271 s | Five accepted alternating pairs |
| Fresh preprocessing plus SHA | 1.330543 s | Same waves; insufficient semantic identity |
| Replay original filesystem traces | 0.391916 s | Five runs; includes JSON parsing and duplicate elimination |
| Replay compact filesystem witness | 0.280059 s | Five alternating pairs; same operations/bytes checked |

The preprocessing prototype preserves the normal AST-reader output, but its
hash cannot identify semantic documents. Eleven probes include two decisive
counterexamples: `-fpack-struct=1` changes layout without changing preprocessed
text; an intra-line whitespace edit changes a declaration column without
changing that text or the compiler arguments. Request flags alone cannot repair
the second case. One final comparison pair overlapped another probe; that pair
is retained but excluded, and a complete replacement pair was measured on an
idle host. The table uses five accepted pairs.

The filesystem recorder wraps Clang's VFS and observes opened bytes, metadata,
failed lookups, real paths and cwd operations. All 16 normal SDK responses still
match. Compaction removes exact duplicate observations without reordering:
**33,349 → 9,901 operations**, **12,802,851 → 3,197,213 JSON bytes**. Verification
hashes **24,768,454 bytes**. Timed witnesses require one stable cwd and absolute
opened-file paths. No directory iteration occurs in this workload; the recorder
marks such an operation incomplete rather than pretending to record it.

Nine focused filesystem probes cover unchanged inputs, same-size edits with
preserved mtime, declaration-column edits, new earlier headers, new
`__has_include` headers, removed shadow headers, newly available parent
directories, symlink retargeting and byte-identical touches. All produce the
expected validation decision. Touches conservatively invalidate metadata even
when the semantic document remains identical; the byte-identical-touch KPI
still needs qualification. A separate counterexample proves that the diagnostic
verifier's exact-row deduplication is unsound across cwd changes: a repeated
relative negative lookup can be skipped in a different directory. Stable-cwd
timings are unaffected, but this verifier must not become a general cache as-is.

Production admission remains to be designed and proved. Bind each semantic
document to exact arguments, target, selections, tool/runtime identity and
relevant environment. Preserve raw contents and search outcomes, including
negative lookups, cwd and open-handle context. Handle volatile macros, modules,
PCH, overlays, filesystem races and unsupported VFS behavior explicitly;
unsupported cases must fall back to fresh extraction. Retain private cache
ownership, corruption checks and atomic publication. Prove both frontends,
invalidations and concurrent behavior, then measure actual Make hits, touch/edit
cases, memory and required-host distributions. **0.280 s is a validation kernel,
not the complete 0.4 s SDK budget or a forecast of product latency.**

Evidence and prototype sources are under
`/Users/alexanderschiffhauer/.cache/btrc/perf/sdk-validation-2026-09-21/`:
`baseline.json`, `preprocess-comparison.json`, `preprocess-contracts.json`,
`traces.json`, `witness-comparison.json` and `witness-contracts.json`. Input
hashes remain unchanged within the successful experiments. The initial recorder
incorrectly stored borrowed LLVM JSON string views; it now owns those strings,
and failed artifacts remain privately retained in
`trace-initial-ownership-failure/`. Sanitizer qualification remains open. The
first witness test wrote its trace into an observed directory and invalidated
that directory's metadata; its failure is retained separately and the corrected
fixture creates the trace file before recording. The effective Nix C++ command
already uses `-O2`; adding a missing optimization flag is not an opportunity.

### SDK witness ownership and request sharing (2026-09-21)

The second isolated prototype closes the demonstrated cwd bug: deduplication
includes the current working directory. Each opened-file observation also
retains its opening cwd and binary/text mode, so a later cwd change cannot
redirect the buffer check. Buffer validation compares metadata on the actual
opened handle before and after reading, alongside the captured content hash.
The VFS wrapper now forwards `File::getWithPath` correctly and marks the witness
ineligible for reuse when remapping occurs. Directory iteration remains an
explicit fallback. This remains a diagnostic, with no production SDK cache.

Ten contract probes pass, including the formerly unsound relative negative
lookup in a second cwd. Four additional native fixtures exercise real files:
reading a retained handle after cwd changes, symlinks followed by `..`, replacing
a pathname while its original handle remains open, and remapping a handle's
display path. The first two replay successfully; replacement is rejected and
remapping preserves normal VFS behavior but rejects cache admission.

All 16 SDK responses match the recorded semantic documents in both normal and
ASan/UBSan runs. The instrumented verifier successfully rechecks all those
witnesses, and all four native fixtures also pass under ASan/UBSan. The linked
LLVM/Clang libraries are not instrumented. The Nix sanitizer runtime could not
initialize on this macOS host: the first SDK run hit its 60-second subprocess
deadline, and a separate `--help` probe was sampled in a recursive ASan
initialization spinlock before `main`. That confirmed probe was terminated;
its stack and failed results are preserved. Rebuilding the same sources using
Apple Clang and its sanitizer runtime, against the same LLVM/Clang libraries,
produces the passing qualification. This is not a passing Nix-sanitizer result.

| Revised validation path | Median, five measured runs | Bytes / operations checked |
| --- | --- | --- |
| One process, original 16 traces | 0.552590 s | 24,768,454 / 9,901 |
| One process, compact shared witness | 0.345757 s | 24,768,454 / 9,901 |
| Sixteen processes, current production waves | 0.869744 s | 70,575,443 / 33,333 |

The stronger checks make the original 0.280 s result historical. These three
variants alternate order, with one warmup and five measured runs each. A
separate representation check measures **0.886790 s** for original per-group
JSON and **0.879848 s** for compact per-group JSON, versus **0.345395 s** shared.
Removing JSON whitespace alone does not remove repeated file verification or
process startup. Both series retain unchanged input hashes and successful
validation decisions. None includes complete cache admission, semantic response
publication, tool identity or the whole Make command.

The implementation direction is now a native-reader-owned validation session
per compiler invocation. Its atomic responsibilities are:

1. Bind each cached semantic response to its exact request and full effective
   compiler/tool/runtime/environment identity. Resolve dependency flags before
   lookup. Unsupported external or volatile inputs trigger fresh extraction.
2. Read owned cache entries and validate their filesystem witnesses through
   one invocation-scoped observer, sharing equal filesystem observations across
   groups while keeping each group's declarations and diagnostics independent.
3. Deliver admitted documents in binding order under the existing response and
   memory limits. A small session result may identify verified documents in a
   private invocation directory; such files must be tied to the request and
   content digest and checked when consumed. Do not return unchecked cache paths
   or enlarge aggregate capture allowances to make a benchmark pass.
4. Send misses through the existing bounded fresh-reader path, and publish new
   entries only after eligibility and input consistency checks. Prove private
   ownership, corruption recovery, concurrent readers/writers and interruption.
5. Integrate both frontends, then measure actual Make no-op/touch/edit behavior,
   process-tree memory and required-host distributions. The product KPI remains
   **8.341 / 9.169 s** until that end-to-end experiment proves otherwise.

Evidence is in the preceding experiment folder's `v2/` directory:
`witness-contracts.json`, `fixtures.json`, `traces.json`,
`apple-sanitizers.json`, `comparison.json` and `grouped-comparison.json`.
The failed Nix run remains in `sanitizers.json`, with its separate startup
diagnostic in `sanitizer-startup.sample`. Prototype sources, binaries and
runner scripts are retained alongside the reports.

### SDK effective inputs and loaded runtime (2026-09-21)

The next isolated reader captures `CompilerInvocation` at the factory boundary,
after driver and dependency-flag resolution and before header parsing. The
identity contains the generated cc1 arguments, the invocation's actual VFS cwd,
ordered semantic selections and a digest of the complete environment. Capturing
the process cwd only after `ClangTool.run` would miss compilation-database cwd
changes; the real two-directory fixture proves the invocation boundary matters.
The diagnostic uses ordered JSON arrays for the key, avoiding object-iteration
order. Environment entries use a canonical length-delimited byte encoding,
without storing their values in the report. Duplicate or malformed environment
entries reject reuse; non-UTF-8 environment values can still be hashed safely.

**25 input probes** pass: repeated identities, used `__TIME__`/`__DATE__`/
`__TIMESTAMP__`, macro aliases, inactive branches, unused macro definitions,
literal text, a user-defined constant replacing a builtin, conservative handling
of `SOURCE_DATE_EPOCH`, ABI options, selections, environment changes/order,
non-UTF-8 environment bytes, warnings, modules, overlays, batch ids, changed
`pkg-config` output and compilation-database directories. Two additional actual
`execve` fixtures reject duplicate and malformed environment entries. Successful
PCH and dynamically loaded plugin fixtures reject reuse too. These are focused
input contracts, not proof that every Clang option has been admitted safely.

The overlay-only-header fixture initially failed to compile. The unchanged
production reader produces the identical failure, so the prototype did not
introduce it. A follow-up with the physical header present preserves normal
semantics and rejects reuse for the overlay option. Keep the initial failure
and reference comparison; do not describe this as qualified overlay support.
SDK parity still needs a supported overlay path if that feature is required.

The runtime prototype observes all loaded Mach-O images before and after
extraction. On this host it sees **396 images**. Its current provider admits
root-owned, read-only Nix store objects with protected parent paths, and
identified macOS system shared-cache images. The reported loaded path and its
resolved target must both satisfy the Nix policy; resolving a mutable alias
alone is not proof of immutable provenance. Cache identity includes the
qualified image paths and loaded UUIDs. This depends on those immutable store
and OS providers, not on trusting UUIDs for arbitrary writable libraries.
Other runtime hosts and mutable toolchains remain unsupported by this
diagnostic provider and must use fresh extraction until qualified.

**Eight runtime cases** pass: immutable package, repeat, package wrapper,
loader-resolved launch alias, mutable executable copy, retargeted alias and two
versions of an injected mutable library at the same pathname. macOS reports the
canonical immutable image for the initial launch alias; retargeting that alias
to the mutable copy rejects reuse. The initial test incorrectly expected the
first alias to be rejected and is retained separately. The corrected test
checks the actual loaded-image boundary and the retargeting case.

The final Nix-packaged prototype runs all **16 SDK groups twice**, preserving
every semantic response and producing stable input/runtime identities. All 16
groups satisfy the macOS-runtime predicate, but only **11 / 16** satisfy the
conservative input predicate. Groups 2, 3, 6, 8 and 9 emit `#pragma once in main
file` warnings and are excluded for diagnostics. The cache must retain and
replay diagnostics faithfully; leaving those groups on fresh extraction would
leave substantial SDK work in the warm path. An Apple
ASan/UBSan build also runs all 16 groups twice with identical semantics and no
sanitizer failures; its mutable executable and sanitizer library correctly
make it ineligible for runtime reuse. LLVM/Clang shared libraries themselves
are not instrumented. No new Make timing was measured; the product remains
**8.341 / 9.169 s**.

Before production admission, compose faithful diagnostics with cached semantic
responses, and audit the remaining external inputs and observable
side effects, including serialized AST merges, C++ module inputs and requested
diagnostic/dependency/statistics outputs. Then compose effective identity,
loaded-runtime identity and filesystem witnesses with private atomic cache
storage and the shared validation session. The diagnostic `eligible_inputs`
and `eligible_runtime` fields are separate partial predicates, not a complete
cache-admission decision. Other required hosts, corruption/interruption/race
coverage, both compiler integrations and actual Make acceptance remain open.

Evidence lives under the experiment directory's `inputs/` and `runtime-v2/`
directories. The former contains `contracts.json`, `environment.json`,
`external-qualified.json` and `product.json`; the latter contains
`contracts-qualified.json`, `product.json`, `sanitizers.json` and `package.json`.
`input-runtime-summary.json` records their hashes and successful counts. The
final immutable probe is
`/nix/store/9mv0dc3hysairhc3ql9wcvcxm8a343j7-btrc-native-input-probe-0`.
The first package attempt passed a host-local source path into the Nix sandbox;
its failure is retained, and the successful builder explicitly imports the
source with `builtins.path`. Prototype sources and runners are retained locally;
no SDK cache has been enabled in production.

### Diagnostic capture boundary (2026-09-21)

An isolated `DiagnosticConsumer` tee was compiled with the native reader's
normal C++17 warnings-as-errors toolchain and compared with the original reader
on all five warning-producing product groups (2, 3, 6, 8 and 9). All five
return codes, semantic responses and emitted stderr streams match. The tee's
captured bytes nevertheless omit `1 warning generated.` in every case: Clang
prints that summary outside this consumer. The tee therefore fails the complete
diagnostic-replay contract and is not a cache-admission implementation.

Use complete stdout/stderr capture at the bounded worker boundary when composing
the shared session. This experiment does not qualify error/note/color behavior,
consumer lifetime under sanitizers or any integrated performance improvement.
The source, build log, actual stderr and comparison report are retained under
`sdk-validation-2026-09-21/diagnostics/` in the local evidence directory.
Actual Make medians remain **8.341 / 9.169 s**.

### SDK admission guards, group isolation and owned buffers (2026-09-21)

The isolated reader's exclusion predicates now cover serialized AST inputs and
merges, additional module/PCH modes, API notes, external instrumentation and
record-layout files, diagnostic suppression maps, requested diagnostic and
dependency files, statistics/timing output, alternate frontend actions and
experimental LLVM/MLIR options. The supported ordinary source path remains
unchanged. This extends the input audit; it does not establish a complete
persistent-cache admission protocol.

The final input/output fixture runs **23 real-reader comparisons**. Both readers
return identical stdout, stderr and exit status, including the deliberately
invalid PCH request. Six requested side files are deleted between executions
and recreated: serialized diagnostics, diagnostic logs, dependencies, header
includes, dependency graphs and statistics. The cases use the effective cc1
options where the driver or ClangTool strips the corresponding driver spelling.
Initial fixture/argument failures are retained separately. The final owned
reader also passes these 23 cases. All **16 actual SDK groups**, repeated twice
with the expanded guards, retain their semantic documents and stable identities;
the same five warning-producing groups remain excluded pending full-response
capture.

The shared filesystem verifier now validates every group independently. It
commits new reusable observations only after that group succeeds; failures
discard them. Each group restores its initial cwd, and a restoration failure
disables later validation. Ten filesystem isolation cases pass normally and
under Apple ASan/UBSan. A private LLVM filesystem was tested and rejected here:
its cwd spelling after `setcwd(".")` differs from the reader's filesystem.
The current verifier uses the same filesystem provider as the reader, with
serial execution and explicit restoration. Historical SDK traces correctly
missed after `/nix/store` metadata changed; freshly captured traces pass for all
16 groups. Injecting the same failed group twice does not prevent any of the
other 15 groups from validating.

The recording wrapper now copies each returned buffer before hashing and
returning it to Clang, so the recorded bytes and parsed bytes share one owned
snapshot. A controlled mutable-buffer VFS fixture changes the borrowed buffer
after hashing; the owned variant stays stable. Both ordinary macOS file-backed
variants stayed stable after an in-place write on this host, so this is **not**
evidence of a reproduced macOS mmap defect. All four ownership cases pass
Apple ASan/UBSan. The owned reader and shared verifier also pass the complete
16-group SDK extraction/validation and repeated-failure isolation sequence,
both normally and with those sanitizers. Linked LLVM/Clang libraries themselves
are not instrumented.

Sources, reports and drivers are retained in `admission/`, `shared/` and
`snapshot/` under the SDK experiment directory. The final composed prototype
source is `snapshot/reader.cpp`; the group validator is `shared/verify.cpp`.
No production cache is enabled, and no new performance result is claimed:
actual Make remains **8.341 / 9.169 s**. The next implementation is the native
reader session, complete bounded worker-response retention and private atomic
cache storage, followed by both frontend integrations and Make acceptance.

### Native SDK session and persistent cache prototype (2026-09-21)

The SDK components are now composed into an experimental native reader, packaged
as `/nix/store/3bvsd70y7l923n27djj6zv7gcplna5z1-btrc-native-session-probe-0`.
Its `session/reader.cpp` source SHA-256 is
`54a95669379f7c56767b0c4faa842a62454f18ad2f3c7e617c409263bd3d2f21`.
The package uses the existing Nix compiler/library derivation and its immutable
loaded-runtime admission policy. It is not installed as the production reader.

Session preparation builds the same effective Clang invocation as a fresh worker
and stops before AST extraction. Both paths share selection parsing, package
resolution and identity construction. The identity now also includes raw driver
arguments and the digest of dependency-resolver stderr: ignored driver options
can affect diagnostics without changing cc1, and an external resolver can change
its diagnostic output while returning identical flags. Successful resolution of
the same ordered package list and cwd is shared within a session. The actual
16-group workload makes **one** package query. A focused five-case executable
fixture proves shared resolution, complete package-warning retention, a
diagnostic-only invalidation and a distinct key for an ignored driver argument.

Fresh workers record their exit status and produce owned input snapshots,
filesystem witnesses and complete stdout/stderr. A private cache accepts only
successful, eligible workers; diagnostic warnings are admissible because the
complete stream is retained. Response blobs are content-addressed. A checksummed
receipt binds their sizes/hashes, input identity and filesystem witness, and is
published by atomic rename after the blobs. Ownership, modes, hardlink counts,
no-follow opens, size limits and metadata stability are checked. Lookup verifies
both streams and the shared filesystem witness before returning descriptors;
consumers must verify descriptor size/hash again when reading the response.

The real 16-group / 41-selection replay preserves the existing four-process,
128 MiB wave policy and the large-group-alone rule for fresh workers. All 16
entries store successfully, and the next session gets **16/16 hits** with
byte-identical stdout and stderr, including all five warning-producing groups.
Single diagnostic observations are **0.460 s for empty-cache preparation** and
**0.766 s for warm lookup**. The latter includes input preparation, cache reads,
shared validation and descriptor output, but not frontend integration. These
are not a timing distribution, a paired speedup, a Make result or acceptance of
the proposed 0.4 s SDK budget.

**25 cache contract cases pass:** receipt/blob corruption (including preserved
size/mtime), symlinks/hardlinks, non-private roots, response allowances, changed
environment/options, source edits with preserved mtime, new shadowing and
`__has_include` headers, failed workers, volatile macros and requested output
files. Two simultaneous publishers and four readers complete successfully;
all returned hits match the original complete streams. A separate publisher is
stopped after an owned temporary file is observed and then killed with SIGKILL.
That temporary was still zero bytes; this is not a mid-payload-write or
power-loss test. All 16 prior entries remain usable afterward.

The cache storage/validation owner also validates all 16 real entries under
Apple ASan/UBSan using the immutable reader's already-qualified preparation
record. This tests that owner, not a sanitizer runtime's eligibility for cache
admission; the tool's runtime policy is unchanged. Linked LLVM/Clang libraries
remain uninstrumented. `session/cache-owner-sanitized.json` records the run.

Evidence is in `session/package.json`, `cache-product.json`,
`cache-contracts.json`, `cache-concurrency.json` and `key-contracts.json` under
the SDK experiment directory. An earlier shared-preparation run was invalidated
by editing its source while it ran; its failed input-stability assertion is
retained and its timing is not accepted. The final immutable-package replay
passes input stability. The dependency fixture invokes the immutable wrapped
binary directly so the package wrapper does not override its controlled
`pkg-config` provider; normal SDK tests use the package wrapper.

Production tool/frontend integration, ordinary-path overhead, cache lifecycle,
other runtime hosts and final memory/cold/miss/Make qualification remain open.
Actual BTRSmith Make medians remain **8.341 / 9.169 s**.

## Raw data

`/tmp/claude-1000/prof/`: `btrcc-timing.txt`, `gprof-flat.txt`,
`gprof-graph.txt`, `btrcpy-pstats.txt`, `clang-time-report.txt`.


### Production reader session integration (2026-09-21)

The shared input/runtime identity, filesystem recorder/verifier, private cache
and session owners now live in `tools/NativeHeaderReader.cpp`. The existing
semantic extraction and per-selection authority remain unchanged. Normal
extraction instantiates no input/runtime observer or traced filesystem, adds no
macro callbacks, and leaves pkg-config stderr inherited. Explicit receipt
requests enable observation and complete dependency-diagnostic capture. Session
control replies, like their inputs, are limited to 8 MiB independently of the
larger per-group semantic capture allowance. A Windows storage fallback returns
misses; it is not a qualified Windows provider. Runtime admission remains limited
to the previously qualified immutable macOS/Nix closure.

The built production package is
`/nix/store/z92xdsh89k6hql0z7l36a07vzdn805rq-btrc-native-header-0`.
The ordinary and observed paths produce byte-identical stdout/stderr and equal
exit status on all **16 BTRSmith groups / 41 selections**. All 16 private-cache
publications and subsequent lookups succeed, including the five warning groups.
Fresh workers retain the existing four-process/128 MiB wave limits and the large
group runs alone. The single lookup diagnostic is **0.772 s**; it is not an
end-to-end Make result or acceptance of the proposed 0.4 s SDK allocation.

`src/tests/python/test_native_header_cache.py` adds **24 real-process cases**:
ordinary/observed success, warning and error equivalence; full warning retention;
changed bytes with restored timestamps; newly shadowing and newly available
headers; receipt/response corruption; permissions, symlinks and hardlinks;
environment, raw-driver and ABI identities; response allowances; unsafe roots;
failed workers, temporal macros and requested side files; invalid-group isolation;
concurrent publication/readers; and a mutable executable rejected by runtime
admission. Cache cases require an admitted reader/runtime; qualification sets
`BTRC_NATIVE_CACHE_REQUIRED=1` so unavailable admission cannot silently skip them.
The focused run passes these 24 cases plus 69 existing reader cases. The final
full reader/cache run passes **200 tests**, including semantic decoding through
both reference and self-hosted compilers, in 83.89 s with no skips.

Five additional real pkg-config/driver checks pass: one query shared across four
groups, full dependency warning retention, warning-only changes causing misses,
updated warning replay, and an ignored raw driver argument producing a distinct
key even when effective cc1 arguments are unchanged. An Apple ASan/UBSan harness
validates all 16 product cache entries through the production storage/verifier
owner; linked LLVM/Clang libraries remain uninstrumented, and the harness does
not qualify a sanitizer runtime for cache admission.

Both compiler integrations remain open. Call preparation once per invocation,
consume responses in binding/error order and verify each descriptor's size/SHA
again while reading. Miss workers need private stages and complete bounded
stdout/stderr capture; storage errors must fall back to valid ordinary
extraction. Staging cleanup/cache lifecycle, remaining host providers, cold/miss
memory overhead and actual Make distributions still require qualification.
Actual Make medians remain **8.341 s self-host / 9.169 s reference**.

Evidence is under `sdk-validation-2026-09-21/production/` in the local performance
evidence directory: package build/path, baseline and reader test logs,
`cache-product.json`, `key-contracts.json` and `cache-owner-sanitized.json`.
Initial test-environment failures are retained separately: missing SDK variables,
the Nix xcrun shim, and selecting the host C++ driver instead of the recorded Nix
Clang provider. Correct the environment rather than skipping SDK cases.


### SDK cache integration in both frontends (2026-09-21)

Both frontends now request one shared preparation session per compilation and
retain their existing bounded worker waves and binding/error order. Preparation
returns compact per-group eligibility and response descriptors. Consumers recheck
response sizes and SHA digests before decoding; corrupted or unavailable blobs
use fresh extraction. Both the returned launcher path and its immutable-provider
eligibility must match the configured reader, so a forwarding wrapper cannot
silently bypass its own behavior through leaf-reader reuse. `--no-cache` disables
SDK persistence as well as compiler artifact reuse.

The native reader owns fresh-worker staging, full stdout/stderr capture, optional
publication and normal stage cleanup. Unsafe or unavailable cache storage falls
back to ordinary extraction. Abrupt interruption may leave orphan stages;
lifecycle/garbage collection and remaining storage/provider qualification are
still open. Runtime admission remains limited to the immutable macOS/Nix provider.

The final package for this checkpoint is
`/nix/store/v1abv60gj53vkg2p03p9ppl7c3i3hdhk-btrc-native-header-0`.
The final self-host build uses unchanged production inputs through two strict
C11/O2 stages, with byte-identical generated C. Binary SHA-256 is
`10c033717a792138ad99ff372660b177288127e510d08509049707f6efad4843`.
The focused frontend suite passes **47 tests**, including real SDK cold/warm
reuse, preserved-timestamp invalidation and `--no-cache` through both compilers.
The cache suite passes **30 tests**; additions cover consumer-side corruption
after preparation, launcher mismatch, unsafe-storage fallback and complete
success/warning/error replay with normal stage cleanup. Python lint/format and
whitespace checks pass. The combined reader/cache, process-lifecycle, frontend
I/O and structure suite passes **268 tests** in 427.01 s, with one `/dev/full`
case skipped on macOS. These checks do not replace the full final-tree matrix.

Evidence is retained under `sdk-validation-2026-09-21/production/`, including
`frontend-integration-tests.log`, `frontend-final-cache-tests.log`, final package
build/path logs and the two-stage source snapshot. A prior intermediate build
finished but failed its final source-stability check because integration changes
were still being made; it is retained under `pre-launcher-build/` and is excluded
from qualification. Actual Make timing and memory must be measured on this final
integration before crediting an end-to-end saving.


### SDK-cache actual-Make comparison (2026-09-21)

The final SDK integration is now measured through BTRSmith's actual
`make btrsmith-native` entry point. Five alternating old/current self-host pairs
use unchanged source and configuration, switching only the compiler selected by
the measurement wrapper. Initial cache-population runs are excluded. Five current
reference runs follow a separate seed. All six system/GNU Make product check
invocations pass before timing. This is local macOS working-tree evidence, not
installed-product, p95 or required-host acceptance.

| Measurement | Self-host baseline | Self-host SDK cache | Reference SDK cache |
| --- | --- | --- | --- |
| Warm Make median, five samples | 8.284899 s | 7.020999 s | 7.748165 s |
| Current gap to 2 s | — | 5.020999 s | 5.748165 s |
| Native objects reused per build | 17 | 17 | 39 |
| Native compiles / links per warm build | 0 / 0 | 0 / 0 | 0 / 0 |

The paired self-host improvement is **1.263900 s / 15.3%**. The reference column
is a current measurement, not a paired old/new reference comparison. Every warm
run hits the compiler artifact cache and preserves all recorded generation,
ownership, executable and debug-object bytes/inodes/mtimes/modes. Both executable
debug maps pass. All **1,314** recorded source, tool, test and product inputs stay
unchanged. All 16 SDK group receipts retain their contents and metadata during
each current frontend series; 32 receipts accumulate across the two distinct
frontend request environments. Instrumentation paths stay constant during the
series, because environment changes intentionally invalidate SDK identity.

Self-host phase medians move from **2.577559 → 1.354360 s for SDK work**.
The current source graph is **1.298246 s**, artifact identity/loading
**1.262498 s**, and native command **2.278436 s**. The reference native command
is **4.353847 s**. These component medians diagnose remaining work; they are
not additive wall-time accounting. The 0.4 s SDK allocation remains unmet.
The next large optimization is native validation, followed by remaining
source/publication work, after finishing SDK fallback/lifecycle qualification.

Separate 50 ms process-tree sampling observes warm peaks of **713.6 MiB
self-host / 683.7 MiB reference**. Additional runs start with an empty SDK cache
and warm compiler/native artifacts, preserve outputs, recreate 16 receipts per
frontend, leave no normal worker stages and perform zero compiles/links.
Those runs sample **713.2 / 688.5 MiB**, with instrumented wall observations
**10.096 / 11.119 s**. The sampling adds overhead: these are diagnostic single
observations, not cold-build distributions or headline throughput evidence.
Sampled peaks are lower bounds on true peak. The initial full-cache seeds were
126.912 s old self-host, 123.368 s current self-host and 349.665 s reference;
these single cache-population runs do not establish cold-build speedups.

Evidence: `sdk-validation-2026-09-21/production/product/results.json`, per-run
stdout/stderr, native reports and operation logs, both debug maps, six Make
check logs, and `sdk-miss-diagnostics.json`. The retained runner is
`build/plan-native-session-product.py`; the separate miss-memory diagnostic is
`build/plan-native-session-miss-memory.py`. Both reports finish without failure
and verify unchanged inputs. The final compiler and native-reader identities
are recorded in the preceding integration checkpoint. Full compiler/host/product
gates, non-macOS runtime providers, storage/lifecycle qualification and the
**≤2 s median / ≤3 s p95** acceptance matrix remain open.


### SDK worker failure and interruption cleanup (2026-09-21)

The optional cached worker now falls back to ordinary extraction when process
launch fails. LLVM's separate crash/timeout status still fails without retrying.
Real Mach-O spawn interposition reproduces denied execution and a moved cache
directory: both failed on the previous reader, and both now preserve ordinary
stdout/stderr/exit status. A killed worker still returns failure.

Private worker captures now have their own `workers/` namespace. A directory
lock protects creation and cleanup gaps, and an inherited per-worker lease
remains held when the parent dies while its child is alive. Later invocations
collect only abandoned private stages. Explicit session publication stages remain
caller-owned. Publication temporary files likewise retain a writer lease; a
directory lock protects creation until that lease exists. Collection checks at
most 128 candidates of each kind per invocation, uses no-follow/private-file
checks and never deletes a live writer's payload or a published blob/receipt.
Collection is best effort; general receipt/blob eviction and other providers
remain separate work.

Tracked real-process tests prove:

- Launch failure falls back, while a killed child does not retry.
- Creation/cleanup directory locks and live leases exclude concurrent collection.
- A stopped SDK child retains its stage after its parent is killed; the next
  invocation removes the stage after the child exits and keeps the old receipt.
- A real publisher stopped after its first 64 KiB payload write survives another
  reader's collection. Killing it permits cleanup, with prior published bytes
  and inodes unchanged.
- Unsafe worker directories and symlinks fall back without touching other files;
  caller-owned session stages remain intact.

The final immutable package is
`/nix/store/i7cg3k1q6si81l776qm84p2lm3cs39nh-btrc-native-header-0`, built from
reader SHA-256 `b784d61deccc991c7e5b927c3f8de6a7d7bc6bb563a28c2037af6e5c28111b98`.
All **39 cache tests**, the **215-test reader/cache suite**, and the separate
**47-test frontend integration suite** pass without skips. Python lint/format
and whitespace checks pass. Compiler/stdlib/language/runtime inputs are unchanged
from the qualified two-stage compiler; only the separately built reader changed.

The actual Make recheck measures **7.052777 s self-host / 7.696929 s reference**,
five warm samples each after excluded seeds. Every warm run retains outputs and
SDK receipts, hits compiler/object caches, reuses 17/39 objects and performs zero
compiles/links. Both debug maps pass and all **1,317 recorded inputs** stay
unchanged. This is a current qualification run, not a paired speedup claim for
cleanup. Separate 50 ms process-tree samples observe **711.4 / 684.4 MiB**, lower
bounds on true peaks. SDK/source/artifact medians are **1.365410 / 1.349172 /
1.284401 s**; native commands are **2.296812 / 4.324667 s**. The two-second and
required-host acceptance targets remain open. Initial seeds are excluded from
KPI evidence; a separate parser experiment ran during the reference seed.

Evidence is under `sdk-validation-2026-09-21/production/lifecycle/`: the initial
launch-failure baseline, intermediate lease and publication baselines, final
`publication/` package/test logs and `product/results.json`. The initial lease
fixture created marker files after cache population and correctly caused a
filesystem-witness miss; that failure is retained. Precreating those markers
isolates the intended process-lifetime contract without weakening validation.

### Native dependency parser and filename identity probe (2026-09-21)

A separate experiment captures the actual **39 reference dependency files** and
checks a regex-based decoder against the current decoder, under the native
builder's working directory, with every decoded dependency present. Five
alternating unprofiled parsing passes measure **0.384451 → 0.151606 s** medians.
This is approximately **0.233 s of component savings**, not a build-time result;
the earlier 2.025 s serialized cProfile cost includes profiling overhead. The
production decoder is unchanged.

Seven real Apple Clang filename fixtures cover spaces, dollars, hashes, tabs,
backslashes, mixed characters and Unicode. Three expose lossy driver depfiles:
unescaped tabs and backslashes normalized to slashes. The full cache probe
rejects the fixtures when the incorrectly decoded paths do not exist. However,
a follow-up creates a real backslash-bearing header and a distinct file at the
normalized slash path. Changing only a comment in the actual header, with its
mtime restored, leaves the native cache key unchanged. The cache restores an
object containing the old DWARF-5 source MD5, while a fresh compilation contains
the new MD5. This is a **reproduced stale native-object hit**, and is the next
contract to repair before promoting the faster parser.

Evidence: `native-validation-2026-09-21/dependencies/results.json`, all captured
depfiles/commands and real filename cases; and
`native-validation-2026-09-21/dependency-collision/results.json`, which records
`stale_hit_reproduced: true`, equal keys and the differing object digests. The
first collision attempt using macro-debug info crashed Apple Clang 21; its report
is retained and excluded. The successful counterexample uses ordinary debug info
with explicit DWARF-5 and verifies the source-checksum bytes in real objects.
These findings do not change production native validation yet and do not qualify
any new end-to-end performance saving.

### Native physical-header identity repair (2026-09-21)

The native object cache now reconciles Clang's physical-header report with its
Make dependency rule on POSIX hosts. The report preserves literal backslashes
and tabs in included paths; the Make rule retains additional inputs, including
existence-only probes. Neither report replaces the other. The reconciliation
preserves multiplicity because two different physical headers can have the same
Make spelling. Cache schema 3 prevents reuse of entries admitted by the previous
identity contract. Unsupported or unreadable reports produce an ordinary cache
miss. Clang's report conflates CR, LF and CRLF in names, so those ambiguous
reports also decline reuse while ordinary compilation remains available.

This follows the actual Clang contracts in
[HeaderIncludeGen.cpp](https://github.com/llvm/llvm-project/blob/release/21.x/clang/lib/Frontend/HeaderIncludeGen.cpp)
and [DependencyFile.cpp](https://github.com/llvm/llvm-project/blob/release/21.x/clang/lib/Frontend/DependencyFile.cpp).
An inventory of all 39 reference native units found headers named by
`__has_include` that the include report omits; replacing the Make rule outright
would lose that coverage. The composed inventory retains those inputs and
recovers all physical header paths. Other compiler providers retain their
existing dependency mechanism; this is not new Windows/GCC filename qualification.

The new real-Clang regression suite checks unchanged cache hits followed by
same-size, restored-mtime comment edits, and inspects the old/new DWARF-5 source
checksums in actual objects. It covers single/double backslashes, tabs, mixed
spaces/hashes/dollars, both colliding files included together, forced includes,
macro includes, system headers, repeated guarded includes, existence-only probes,
and logical `#line` names. It also checks unavailable/corrupt header reports and
ambiguous control-character paths. The real native builder proves that the
backslash and tab cases compile once, hit, recompile after the header edit, then
hit again and produce a working executable.

The dependency word decoder now uses the measured regex approach, retaining
its original escaping semantics. Physical-name reconciliation avoids encoding
and decoding every known header again; the common unescaped header-report path
also avoids unnecessary regular-expression work. Performance qualification is
recorded below separately from the correctness evidence.

Qualification: **185 existing native build/link/debug/performance tests** pass,
including the Nix Clang link-reuse case, and all **15 final identity regressions**
pass. The separate GCC 15 object-cache selection passes **12 tests**. Initial
fixture failures are retained: newline-bearing `-include` arguments were rejected
by Clang, so the valid-input fixture uses a newline-bearing include directory;
two builder assertions used an incorrect report attribute, then passed using
`NativeBuildReport.as_dict()`. Neither correction changes production admission.
The broad log's other 185 tests pass on the final production source; the final
15-test run supplies the corrected regression results. Lint, format and
whitespace checks pass. These are focused gates, not the full compiler matrix.

Five alternating isolated passes over the 39 actual depfile/header-report pairs
measure **1.103841 → 0.305952 s** medians for dependency reconciliation. This
baseline is the correctness repair before parsing optimization, not the former
Make-only decoder. All recovered path lists are equal, and 10,000 generated
escaping inputs preserve the prior decoder's results/refusals. The component
comparison does not establish an end-to-end speedup.

Actual `make btrsmith-native` now measures **6.720382 s self-host / 7.406721 s
reference** medians, five warm samples each. All ten runs hit compiler/native
caches, retain the complete output metadata and SDK receipts, reuse all 17/39
objects and perform zero compiles/links. Both debug maps pass and all **1,319
recorded inputs** remain unchanged. This is a current qualification checkpoint,
not a paired speedup claim. Excluded schema-population seeds take 12.554/14.586 s
with warm compiler artifacts; neither is a cold-build KPI measurement.

Separate 50 ms full-process-tree samples observe **713.1 / 684.4 MiB**, lower
bounds on true peaks. These runs also retain outputs/SDK receipts and perform
zero compiles/links. Current self-host source graph, SDK and artifact-hit medians
are **1.255095 / 1.290919 / 1.236471 s**. Native command medians remain **2.153928 /
4.137733 s**, well above the proposed 0.7 s allocation. The next M6a work is
measuring and reducing repeated native tool identity, process and preprocessing
work, then the remaining source/publication/SDK costs. The two-second goal is
still unmet by **4.720 / 5.407 s**; required-host and final-tree gates remain open.

Evidence under `native-validation-2026-09-21/`: `header-inventory/`,
`identity-parser-final/results.json`, `identity-product/results.json` and
`identity-product/memory.json`. Drivers and test logs are retained in the
`native-dependency-identity.tar.gz` checkpoint alongside the complete Git patches.

### Bounded native process workers (2026-09-21)

The remaining native-validation profile counts **17/39 version queries** and
**9,411/20,257 file hashes** for the self-host/reference plans. Serialized,
instrumented version queries take 0.977/2.204 s and preprocessing takes
4.687/8.962 s; these sums are diagnostics, not parallel build wall times.
Per-worker cProfile could not run concurrently under Python 3.13, so the
retained profile explicitly serializes probes. All production inputs remained
unchanged during these diagnostics.

Three balanced rounds of actual native builds reject reducing the existing
worker count. Two/four/eight workers measure **4.091/2.709/2.220 s self-host** and
**7.671/4.696/4.119 s reference** medians. The build remains bounded at eight
native jobs for the product comparison. A separate 64 KiB hash-prefix experiment
still reads every input byte but avoids large temporary hashing buffers for small
files. Five alternating native-only pairs measure 2.172 → 2.151 s self-host and
4.177 → 4.075 s reference. That small optimization remains unpromoted; it is not
part of the process-worker change.

An isolated eight-process prototype preserves every object key and retained
output, and three alternating native-only pairs measure **2.232 → 2.102 s
self-host / 4.157 → 3.149 s reference**. The improvement justifies qualifying
process workers for native validation. This is M6a's existing native-build
worker pool, not the later compiler analysis/lowering parallelism milestone.

The guarded native CLI entry point now enables spawned workers for cached
builds with more translation units than available jobs. Small batches and
uncached builds retain the existing thread pool. `NativePlanBuilder` and an
imported `main()` remain suitable for unguarded embedding; custom runner/reader
capabilities stay in their calling process. Workers execute the same compile,
probe, restore and publication methods. Each still validates current contents;
there is no digest memoization, skipped preprocessing or change to cache schema.
Results are collected in plan order and the existing job bound remains intact.

Spawn avoids inheriting the parent's publication locks and thread state.
Unexpected worker exit becomes a native-build error and leaves the previous
executable in place. A real parent-kill test reproduced indefinitely surviving
pool workers. Each worker now watches the inherited parent sentinel and exits
when that ownership handle closes, without relying on PID polling. This test
qualifies the new Python workers' lifetime; it does not establish cancellation
of the entire native compiler process tree.

Qualification includes **200 existing native build/link/debug/performance and
identity cases**, plus **six final real process-boundary cases**: bounded cold
compilation and warm reuse, compiler error, worker death, parent death, unguarded
embedding and custom runner callbacks. The original broad run passes 205 tests;
the subsequent six-case run qualifies the added parent-sentinel initializer.
An early preservation assertion incorrectly compared access time after reading
the executable; the final test checks inode, modification time, mode and bytes.
The packaged Nix launcher also passes all four CLI process cases using Python
3.14.6. Its source is byte-identical to the working tree, SHA-256
`37b609f9c78a9d75d0558fdff96d058c289b9a3820e0b99fa23e5f768fb2a9ae`, in
`/nix/store/gjma5i1lxr9if8x602d7hb54sa431ab1-btrc-native-plan`.

Evidence under `native-validation-2026-09-21/`: `remaining-profile/qualified/`,
`worker-grid/`, `hash-prefix/`, `process-workers/` and the actual-Make comparison
below. The Python 3.13 product measurements and Python 3.14 packaged fixture
checks are separate qualifications; required-host and final-tree acceptance
remain open.

Five alternating actual-Make baseline/current pairs per frontend measure:

| Frontend | Baseline Make median | Process workers | Change | Native-command median, baseline → current |
| --- | --- | --- | --- | --- |
| Self-host | 7.079069 s | 7.027067 s | 0.052 s / 0.7%; effectively flat | 2.305063 → 2.248891 s |
| Reference | 7.766417 s | 6.814147 s | 0.952 s / 12.3% faster | 4.371225 → 3.379559 s |

The variant loader uses explicit source copies and one constant wrapper path;
production source is never swapped. All **20 warm runs** hit compiler/native
caches, retain complete output metadata and SDK receipts, preserve object keys
and perform zero compiles/links. Excluded baseline seeds take 9.839/10.640 s;
these have warm compiler artifacts and are not cold-build KPI measurements.
Both debug maps pass and all **1,324 recorded inputs** remain unchanged. Current
self-host source graph, SDK and artifact-hit phase medians are **1.308516 /
1.359442 / 1.258783 s**. They are diagnostic medians, not additive wall accounting.
The no-op KPI remains unmet by **5.027 / 4.814 s**. The earlier independent
6.720 s self-host checkpoint is not this experiment's paired baseline.

Separate 50 ms process-tree samples observe **709.8 → 1,066.0 MiB self-host /
677.1 → 1,000.4 MiB reference**. Extra interpreter processes increase sampled
aggregate RSS by about 350/323 MiB for the reference wall-time gain; self-host
shows no material wall improvement. This explicitly accepts a local
memory-for-time tradeoff while keeping native concurrency bounded at eight.
Samples are lower bounds on true peak and do not prove the required-host
6 GiB aggregate objective or cold-build memory acceptance.

The initial memory assertion failed because it compared the shared SDK receipt
set with the self-host snapshot taken before the reference seed. Exactly six
reference receipts had been refreshed by that seed; all output metadata was
unchanged, and the final receipt set equaled both the reference seed and every
reference warm snapshot. `process-product/results.json` preserves that failed
assertion and all original timings. `process-product/qualification.json`
records the diagnosis and resumes only the four separate memory checks using
the current shared receipt snapshot. All four retain outputs/receipts and
object keys, hit the compiler cache and perform zero compiles/links. Wrapper
restoration, debug maps and input hashes also pass. Neither benchmark failure
history nor timing samples have been overwritten.

Next: remove repeated tool-identity and preprocessing work under the existing
correctness contract, then remaining source/publication/SDK cost. A receipt
experiment must account for newly shadowing and absent headers as well as
positive dependencies; old depfiles alone are insufficient. More processes
cannot close the remaining five-second gap. Required-host and full final-tree
qualification remain open.

### Native preprocessing witness prototype (2026-09-21)

Production remains unchanged at the 7.027/6.814 s actual-Make checkpoint. The
next experiments isolate work reduction rather than add native workers.
Five alternating native-only pairs query version once per distinct fixed tool:
**2.117409 → 2.107089 s self-host / 3.147614 → 2.966669 s reference**. All 20
warm builds retain outputs and object keys, perform zero compiles/links, and
all 1,324 recorded inputs remain unchanged. The 0.010/0.181 s best-case saving
precedes general tool/runtime stability admission; the candidate is unpromoted.

A separate C++ prototype copies the existing SDK trace and verifier owners into
an isolated package and executes the real driver's expanded `-cc1` preprocessing
invocation. It changes no production compiler, reader or native-plan source.
All **17 self-host / 39 reference units** have byte-identical preprocessed text,
depfiles, physical-header reports and diagnostics against the ordinary compiler.
All are eligible under the prototype's explicit preprocessing input policy and
immutable macOS runtime checks. This does not yet bind an arbitrary selected
compiler to the helper's runtime or admit a production cache entry.

The first comparison exposed a real composition requirement: parsing `-cc1`
arguments alone does not initialize diagnostic mappings. Without
`ProcessWarningOptions`, `-pedantic-errors` changes `__has_extension` results
and SDK enum preprocessing differs. The corrected prototype initializes those
settings. A separate fixture error reused a Clang header-report path; Clang
appends to that report, so each comparison now gives it a fresh file. The first
failed parity report and diff remain in `native-witness/`. A subsequent build
with an incomplete LLVM API call remains in `native-witness-qualified/`; the
working correction is retained in `native-witness-v3/`.

Fourteen final fixtures exercise preserved-mtime header edits, comment-only
header/source edits, earlier-header shadowing, negative `__has_include`,
removed headers, symlink retargeting, backslash/normalized-path collisions,
pedantic feature queries, warning/error diagnostics, and three volatile builtins.
All changed-input cases invalidate the witness; comment-only cases do so even
when preprocessing output stays identical. `__TIME__`, `__DATE__` and
`__TIMESTAMP__` refuse reusable input admission. A fixed `SOURCE_DATE_EPOCH`
makes comparison deterministic without removing those refusals. An early
`#warning` fixture was an error under C11/pedantic policy; the final warning case
uses `#pragma message` and asserts successful execution. Error tests compare
success/failure and exact diagnostics; the prototype's failure status is 16,
not the compiler's status 1. They do not prove exit-code transparency.

Each product trace initially repeats SDK observations across units. Under one
verified fixed cwd, storing exact observations once preserves all distinct
checks. Cwd transitions are refused by this compaction experiment.

| Workload | Original observations | Distinct observations | Original JSON | Compact JSON | Current buffer bytes still hashed |
| --- | --- | --- | --- | --- | --- |
| Self-host | 52,817 | 9,763 | 30,394,188 B | 4,945,725 B | 222,034,399 B |
| Reference | 115,143 | 9,851 | 65,726,230 B | 4,995,157 B | 347,248,775 B |

Five alternating full/compact validation pairs on fresh witnesses measure
**1.355345 → 0.983504 s self-host / 2.285740 → 1.357772 s reference**. Each
buffer path is still hashed once from current contents; this is not a digest
memo keyed by metadata. A platform SHA-256 experiment then validates the same
LLVM-captured digests using CommonCrypto. Five alternating compact-validation
pairs measure **0.975925 → 0.419102 s self-host / 1.359301 → 0.477077 s
reference**. All fourteen final fixtures also pass with compact witnesses and
the platform hash provider. This provider is an experiment, not a production
port or cross-platform crypto qualification.

The first post-build verification correctly rejected a stale `/nix/store`
directory status after building the new helper changed its size/mtime. That
failed measurement is retained; no witness was patched. All 56 units were
recaptured and compared against the ordinary compiler after package construction,
then the alternating measurements were repeated on those fresh witnesses.
`native-witness-current/product.json` and the final timing reports verify all
1,324 recorded production/product inputs remained unchanged.

Five additional passes expand every unit's driver invocation afresh at eight
jobs, verify exact equality with each recorded `-cc1` argv, then validate the
compact witness. Driver-expansion medians are **0.219597 / 0.386035 s** and
combined medians **0.624461 / 0.867318 s**. These exclude complete tool/runtime
admission, object/executable integrity, link-receipt work and cache publication.
The prior actual-Make native reports spend another **0.331/0.342 s** in link
validation alone. Do not add medians into a claimed wall result or call the
0.7 s native budget achieved. No actual-Make speedup, cold/miss cost or memory
acceptance is established by this prototype.

The helper and selected Nix compiler declare the exact same immutable
`libclang-cpp` and LLVM dylibs. The stored `otool` result supports a concrete
provider-admission design; declared dependencies alone do not prove actual
loaded images or runtime identity. Next, integrate with the existing native
input/trace/cache owners, validate actual tool/runtime binding and ordinary-path
fallback, qualify storage/lifecycle/debug/invalidation behavior, then run paired
actual Make and aggregate-memory comparisons through both frontends. Preserve
fresh driver expansion until measurements and correctness evidence justify
sharing it.

Evidence under `native-validation-2026-09-21/`: `tool-identity/`,
`native-witness/`, `native-witness-qualified/`, `native-witness-v3/`,
`native-witness-current/` and `native-witness-crypto/`. The latter's
`measurements-current.json`, `driver-measurements.json` and `cases-final.json`
are the final platform-provider results; `measurements.json` preserves the stale
store-directory refusal. Production KPI and required-host gates remain open.

### Native compiler runtime binding (2026-09-21)

The first production prerequisite for preprocessing receipts is implemented in
`NativeHeaderReader.cpp`: `--native-compiler-context` binds selected drivers to
this packaged helper's actual Clang/LLVM runtime. `flake.nix` supplies the exact
configured Clang, Clang++ and underlying compiler paths. Admission currently
supports that immutable Nix provider on macOS. Other providers return a
structured refusal; matching version banners cannot establish eligibility.
Native-plan does not consume this protocol yet. The latest actual-Make result
remains the earlier **7.027 / 6.814 s** checkpoint, not a measurement of this
new reader. No build-speed improvement is claimed here.

The context includes the selected drivers, canonical compiler, compiler image
UUID, active and mapped image identities, complete helper runtime (including
its executable), a digest of the current environment and compiler version
output. Raw environment values are not returned. Ambiguous environment entries,
dynamic shell/loader settings, mutable or unconfigured drivers and unsupported
helper runtimes refuse admission. Observation runs the configured underlying
compiler's `-cc1 -version` with a ten-second deadline and bounded captures,
reusing the existing private WorkerStage lease and cleanup owner. Capture
storage failures also refuse admission.

Actual Darwin loader diagnostics exposed deferred image transitions: the raw
compiler trace maps 157 images that later leave the active set. The final
implementation replays explicit loaded/delayed transitions and requires exact
agreement with the helper's **395 active library images**, excluding each
process's own executable. Ambiguous, unknown or inconsistent transitions
refuse admission. All mapped identities remain in the context key. The first
strict raw-set mismatch and diagnostic traces are preserved; no image mismatch
was silently ignored.

Qualification on the final package passes **235 tests in 89.41 s, no skips**:
20 new compiler-context cases, 39 existing native-cache cases and 176 existing
native-reader cases. Coverage includes stable identities, environment changes,
forwarding wrappers, mutable symlinks/copies, another compiler, shell/loader
configuration, malformed requests, unsafe capture storage and a mutable helper
copy. The existing cache baseline passed 39 cases before implementation.
An initial fixture incorrectly returned from TemporaryDirectory; changing it
to yield fixed its lifetime. The initial failed run and loader mismatch remain
in the evidence alongside the corrected results. Nix compilation uses
`-Wall -Wextra -Werror`; focused Ruff/format and whitespace checks pass.

Final package: `/nix/store/pscja97wg74drvjyi5b4rkz8j13qqgy5-btrc-native-header-0`.
The final test driver/log are `build/plan-native-provider-qualified-tests.py`
and `build/plan-native-provider-qualified-tests.log`. Runtime comparison
captures are under `native-validation-2026-09-21/compiler-context/`; the
checkpoint archive includes source, package/log hashes and failure history.

Next integrate preprocessing action policy, receipt capture/compaction and
private persistence into the existing input/trace/cache owners. Native-plan
must validate the reported launcher and fresh effective driver invocation
against the bound compiler before consuming receipts, with ordinary
preprocessing on unsupported or invalid inputs. Then qualify invalidation,
corruption, interrupted publication, output/debug retention and both frontends;
measure paired actual Make time, memory and cold/miss costs. Cross-host provider
support, the 0.7 s native allocation and full M6a acceptance remain open.

### Native preprocessing receipt owner (2026-09-21)

The reader now implements `--native-preprocess` sessions using the existing
NativeHeaderInputs, filesystem trace/verifier and NativeHeaderCache owners.
This is the storage/capture/replay half of native-build integration. Native-plan
still uses ordinary preprocessing; actual Make remains the earlier
**7.027 / 6.814 s** checkpoint. This change does not establish a build speedup.

Each unit supplies a fresh driver-expanded `-cc1` invocation. Preparation
requires the configured immutable compiler and an admitted preprocessing action,
normalizes only owned output destinations, and binds the complete effective
invocation, environment and compiler context into the receipt identity. The
caller must still prove that its selected driver's fresh expansion produced
those arguments. Unsupported inputs return a refusal for ordinary fallback.
The session reports ordered unit results and bounded, hashed blob descriptors.
Its control input and response are each limited to 8 MiB.

Fresh capture uses Clang's PrintPreprocessedAction, initializes diagnostic
mappings, and records current owned source/header bytes and positive/negative
filesystem observations. Exact duplicate observations are compacted only under
a verified fixed working directory. The response records preprocessing,
dependency-file and physical-header-report digests plus observed buffer paths
and content digests. This preserves comment-only source/header changes that do
not alter preprocessing text but do affect debug inputs. Existing private
storage, atomic receipt publication, corruption checks and worker leases own
the files. A cache hit revalidates the filesystem witness and stored blobs.

The first product run exposed a necessary extension to compiler binding:
Nix's underlying `clang++` is a separate executable, with different bytes and
inode from `clang-21`. Unit 15, the C++ adapter, was refused rather than borrowing
the C executable's identity. The package now configures both exact underlying
compiler paths and observes each actual executable's loader images independently.
A session shares the resulting contexts across units using that executable.
The native-preprocess response contains `contexts`; each unit's input identity
includes its own verified context.

Qualification on the corrected package compares **17 self-host / 39 reference
product units** with ordinary compiler preprocessing. All 56 produce matching
preprocessed bytes, dependency files, physical-header reports and diagnostics.
The first endpoint pass captures all units; the next gets **17/17 and 39/39
cache hits**, with all returned blob sizes/hashes checked and worker directories
empty afterward. This exercises the receipt endpoint against the product's
actual native commands, not native-plan consumption or an actual Make build.

Single endpoint observations, provided only to expose remaining work:

| Endpoint pass | Self-host, 17 units | Reference, 39 units |
| --- | ---: | ---: |
| Fresh capture/publication | 9.387 s | 17.399 s |
| Validated receipt hits | 1.892 s | 3.166 s |

These are single observations, not paired performance results or distributions.
They exclude fresh driver expansion, object/executable checks, linking and Make.
The production verifier still uses LLVM SHA-256; the earlier CommonCrypto
experiment is not yet integrated. Receipt metadata and validation overhead also
need profiling. Persisted per-unit receipts total **30,187,253 / 65,993,068
bytes** for self-host/reference: compaction inside each unit does not remove
observations shared across units, unlike the earlier whole-session prototype.
Neither the **0.7 s native allocation** nor full build acceptance is proven,
and cold/miss costs need end-to-end qualification before promotion.

The new regression suite passes **28 cases** on the final C/C++-binding package.
It covers miss/hit parity, option/environment identities, output-destination
normalization, preserved timestamps, comment-only changes, include shadowing,
negative lookups, removed headers, symlink retargeting, physical backslash/name
collisions, volatile builtins, corrupt receipts/blobs, diagnostics/feature
policy, unsupported actions and actual C++ compiler binding. A real process test
stops the helper after observing Clang's temporary output, kills that process,
then proves collection removes the abandoned stage and preserves prior receipts.
The existing reader/cache/context suite separately passes **235 cases in
90.70 s**, with no skips. Together these provide **263 distinct passing cases**
on the final package; the result is two runs, not one combined 263-case run.
Ruff, format and whitespace checks also pass.

Failure history remains preserved. Initial capture refused Clang's replacement
files because their modes inherited the caller's umask; capture now scopes a
private umask. Clang's warning summary used its verbose stream, so that stream
now joins the same diagnostic capture as the diagnostic printer. A test initially
resolved relative buffer paths against the pytest cwd instead of the recorded
source cwd; its assertion was corrected. The interruption regression reproduced
an abandoned Clang temporary file: cleanup now unlinks entries inside the leased
private worker namespace without following symlinks or descending directories.
An intermediate full run passed 262 cases before the independent C++ binding
repair; it is not the final-package regression result.

Final package:
`/nix/store/8p1jfs28xgjhnl784944s8a1asrx5zxq-btrc-native-header-0`.
Drivers/logs use `build/plan-native-receipt-*`; product results are under
`native-validation-2026-09-21/native-receipt-product-qualified/`. The initial
C++ refusal is retained in `native-receipt-product/`. The final new-test log is
`build/plan-native-receipt-cxx-tests.log` (28 passes, 17.36 s), with existing
coverage in `build/plan-native-receipt-existing-tests.log` (235 passes, 90.70 s).

Next connect this protocol to NativePlanBuilder and _ObjectCache using one
batched initial validation and fresh effective driver expansion. Verify the
launcher and response descriptors before using them, include context/invocation
and current buffer content in object identity, and perform fresh post-compile
validation before publishing an object. Keep ordinary preprocessing fallback.
Then qualify object/debug/link retention, profile the remaining receipt costs,
integrate the measured platform hashing provider, and run paired actual Make,
aggregate-memory and miss/cold checks. Required-host and full final-tree gates
remain open; the active milestone is still M6a.


### Native preprocessing consumer integration (2026-09-21)

NativePlanBuilder now expands the real configured driver for every unit and
batches receipt lookups through the existing bounded reader-session owner.
It checks the launcher, compiler binding, response schema and checksummed blobs
before admitting an object key. The key includes the original compile arguments,
effective preprocessing invocation/context and all observed source/header bytes.
A real compile still receives fresh post-compile validation before publication.
Unsupported tools, unavailable storage and malformed responses fall back to
ordinary preprocessing.

Lookup-only preparation defers cold captures to the bounded compile workers;
fully admitted batches use threads because validation and preprocessing execute
in the native helper. Ordinary Python validation retains the process-worker
path. Reports distinguish initial batch time, receipt hits/captures and ordinary
preprocessing; overlapping worker durations are not wall-time components.

Consumer tests exposed directory over-invalidation: unrelated output creation
changed the source directory's size/mtime and caused unnecessary rescanning.
The supported preprocessing view now returns and records stable directory
identity, preserving inode/device, ownership, permissions and type. Individual
child and negative lookups remain traced. Modules and directory enumeration are
excluded from this admission path; SDK extraction retains its existing view.
Regression cases cover unrelated entries, changed permissions and replacement
of a directory while preserving the header's inode and bytes.

On macOS, owned-buffer hashing now uses CommonCrypto SHA-256 in bounded chunks;
other hosts retain LLVM hashing. Boundary-size fixtures compare its output with
Python SHA-256. The context is bound by its verified digest instead of repeating
the full context document inside each unit's invocation identity.

The new packaged helper matches ordinary preprocessing, dependency files,
physical-header records and diagnostics on all 17 self-host and 39 reference
BTRSmith units. Each frontend's second pass hits every receipt; blob checks and
worker cleanup also pass. Single endpoint observations were 6.886/12.764 seconds
for capture and 1.083/1.847 seconds for warm validation (self-host/reference).
These observations exclude driver expansion, native object/link work and Make;
they are not paired speedup measurements. Receipt documents still total
27,130,284/58,979,802 bytes, so duplicated metadata remains a profiling candidate.

Package: `/nix/store/84nxcya9a8ys0g822vxcgqak61nwf9rf-btrc-native-header-0`.
Evidence: `native-validation-2026-09-21/native-consumer-product-qualified/`;
driver/log: `build/plan-native-consumer-product-qualified.py` and `.log`.
Full final-tree, required-host and end-to-end miss/cold acceptance remain open.


Targeted consumer qualification covers **487 distinct cases across split runs**.
The initial 487-case run passed 466 and failed 21 because Apple C++ was paired
with a recorded Nix SDK environment. Re-running the 206 native-build cases with
the Nix toolchain passed 202. Three remaining cases require Clang paths containing
CR/LF, which the Nix driver wrapper does not preserve; the full 15-case physical
header suite passes with the clean Apple toolchain. The fourth exposed a test
setup mismatch: it seeded receipt keys with a real runner, then expected hits
through a custom runner that deliberately uses ordinary validation. Both sides
of that lock fixture now use the injected-runner path; both cases pass under
Nix. The 281 consumer/receipt/context/cache/reader cases passed in the initial
run. This is combined coverage, not one all-green 487-case invocation. No skips
are counted as passes, and all failure logs are retained.

Logs: `build/plan-native-consumer-qualified-tests.log` (466/21),
`build/plan-native-consumer-native-tests.log` (202/4),
`build/plan-native-consumer-apple-dependencies.log` (15 passes), and
`build/plan-native-consumer-lock-tests.log` (two passes). The new consumer cases
exercise real warm object/executable/debug reuse, preserved-mtime edits, fresh
post-compile invalidation, malformed/unavailable provider fallback and batched
CLI scheduling. Ruff and formatting pass for all four touched Python files.


Five alternating **actual Make** baseline/current pairs per frontend now give:

| Frontend | Ordinary validation | Receipt consumer | Change | Native-command median, baseline → current |
| --- | ---: | ---: | ---: | ---: |
| Self-host | 6.596291 s | 6.244532 s | 0.351759 s / 5.3% faster | 2.116037 → 1.751723 s |
| Reference | 6.313901 s | 5.793740 s | 0.520161 s / 8.2% faster | 3.138862 → 2.656617 s |

Both variants use the final reader package and identical environment, preserving
the production CLI's process-worker selection. The shared platform-hash change
is therefore outside this comparison. Frozen source copies and a checked loader
select variants without swapping production source. Separate variant object
caches prevent link receipts from replacing each other. Seeds are excluded.
All **20 warm runs** hit compiler/object caches, retain output inode, mtime, mode
and bytes, preserve SDK receipts and object keys within each variant, and
perform zero compiles/links. Current runs hit all 17/39 preprocessing receipts.
Debug maps pass and all **1,330 recorded inputs** remain unchanged.

Separate 50 ms process-tree RSS samples fall from **1,065.0 → 304.3 MiB** for
self-host and **1,030.0 → 551.9 MiB** for reference. These are sampling lower
bounds, outside the timing comparisons. The current receipt path avoids the
extra Python worker interpreters. Self-host phase medians remain 1.263101 s
source graph, 1.211268 s SDK and 1.248653 s artifact hit; initial native receipt
batches take 1.352036/2.220703 s. Phase medians are diagnostic, not an additive
wall-time breakdown. The 0.7 s native allocation is still unmet.

The first comparison loader accidentally used embedding defaults rather than
CLI worker selection. Its partial self-host observations were stopped, the
wrapper restored and child completion verified. That failed/partial comparison
is retained in `consumer-product/` and is excluded from the results above.
The corrected complete run is `consumer-product-cli/results.json`, with
`failure: null`, unchanged inputs and verified wrapper restoration. Its driver
and log are `build/plan-native-consumer-product-cli.py` and `.log`.

Additional actual-product **native-only** checks use fresh private output/cache
directories, the same generated inputs and eight CLI workers. Each observation
below is a single sample, not a cold-product distribution or a Make KPI:

| Frontend / cache condition | Ordinary validation | Receipt consumer |
| --- | ---: | ---: |
| Self-host, empty native cache | 7.533 s | 9.619 s |
| Reference, empty native cache | 11.364 s | 14.255 s |
| Self-host, one missing C++ object | 2.481 s | 2.557 s |
| Reference, one missing C++ object | 3.677 s | 3.535 s |

Cold runs compile every unit and perform two verification links. Warm runs
compile/link nothing. Removing only the private cached C++ object recompiles
exactly one unit, retains all object keys and executable bytes, and requires
no relink. The consumer retains receipt hits for every warm/missing-object unit.
All recorded production inputs remain unchanged. Evidence is
`consumer-misses/results.json`; driver/log: `build/plan-native-consumer-misses.py`
and `.log`. These samples expose a **2.086/2.891 s cold-native overhead** that
needs repeated qualification and profiling before declaring the tradeoff
accepted. Initial full-Make cache seeds of 123.152 s self-host and 330.937 s
reference used ordinary native validation; they are not current-consumer cold
KPI measurements or a controlled comparison with historical cold results.

**Next:** reproduce and reduce cold receipt-capture overhead, then profile the
remaining batch cost: repeated runtime/context preparation, 27/59 MB of receipt
metadata, fresh driver expansion and blob decoding. Existing SDK sessions
already share runtime snapshots; any analogous preprocessing reuse must prove
runtime stability across the entire batch and preserve fallback behavior.
Source graph, artifact loading/publication and SDK validation each still exceed
the proposed budgets. Required-host distributions, full cold/edit Make workloads
and final-tree gates remain open; M6a is still active.


### Owned preprocessing capture and stable blobs (2026-09-21)

Cold native-build profiling confirms that fresh capture dominates the added
validation cost. Instrumented self-host/reference builds took 9.462/13.612 s.
Across concurrent workers, initial helper calls sum to 18.200/29.882 s and
post-compile helper calls to 6.274/12.526 s; these overlapping sums are not
wall-time components. Driver expansions sum to 3.582/8.041 s.

An isolated instrumented helper then measures sequential product captures.
Runtime/invocation preparation totals only 0.049/0.114 s and post-preprocessing
runtime reports 0.030/0.070 s. The larger removable work is staging structured
records and looking up a just-published receipt: 0.236 + 0.497 s self-host,
0.514 + 1.088 s reference. Store itself totals 0.981/1.882 s, including necessary
input validation and publication. This evidence prioritizes owned records over
runtime snapshot memoization. Profiles live in `capture-profile/` and
`capture-helper-profile/` under `native-validation-2026-09-21/`; the profiling
helper is isolated and never installed as the production provider.

Fresh in-process preprocessing now passes its owned input contract and
filesystem witness directly to the existing NativeHeaderCache publisher.
External SDK capture still reads and validates its stage files through the same
publisher. The publisher verifies current observed inputs, checks stream files,
creates checksummed blobs and atomically commits the receipt before returning
response descriptors. Fresh capture still requires the prepared and completed
input identities to agree, and rechecks published blob bytes. This removes two
stage files and their serialization/parsing roundtrip, plus the immediate
receipt reread; it does not remove current-input or blob validation.

The first performance comparison stopped on an ordinary-validation fallback in
one reference unit using the old helper. It successfully built but published
no object for that unit after the validation method changed. Two subsequent
builds proved recovery: one object compiled with two verification links, then
zero compiles/links, all 39 receipt hits and unchanged executable bytes. Those
partial timings and the failed assertion remain in `capture-comparison/`;
`recovery.json` records recovery and unchanged inputs. The original helper
refusal reason was not captured, so its precise cause is not claimed.

Investigation reproduced a concrete concurrent-publication defect: every blob
publication replaced its destination even when the digest and bytes were
identical. Existing readers' descriptors became unlinked, violating the cache's
before/after file checks. Two deterministic tests hold stdout/stderr descriptors
across repeat publication and observe link counts dropping from one to zero on
the old implementation. The publisher now holds the existing cache-directory
lock while checking or repairing a blob, preserves a verified existing inode,
and atomically replaces only missing or invalid entries. Repair tests cover
corrupt bytes, incorrect permissions and hard links, preserving the other alias.
The initial hard-link fixture changed the source directory itself; moving that
alias into the cache isolates the intended blob contract. The corrected baseline
is two expected failures and three passes.

To isolate the owned-record performance change, the next comparison uses a
baseline containing the stable-blob repair but retaining the previous staging
and reread path. Both variants use the same CLI and optional-refusal logger;
no production Python compiler, native-plan or stdlib changes are involved.
The last full-Make KPI remains the preceding 6.245/5.794 s checkpoint until a
new complete Make comparison is recorded. M6a and final-tree/required-host gates
remain open.


Final package: `/nix/store/b3skmbvjbr5dcdyksdpr1w6d43jrw46w-btrc-native-header-0`.
The complete targeted reader/context/cache/receipt/consumer selection passes
**288 tests in 146.45 s, with no skips**. This includes seven added cases for
failed publication, concurrent captures, stable active readers and damaged-blob
repair. All **56 product units** again match ordinary preprocessing, dependency
files, header reports and diagnostics, and every receipt hits on the second
pass. Evidence: `stable-capture-product-qualified/results.json`;
`build/plan-native-capture-stable-tests.log` and
`build/plan-native-capture-stable-product.log`. These are local provider checks;
required-host and full final-tree gates remain open.

Three alternating cold-native-cache pairs per frontend, each followed by warm
reuse, measure the owned-record change against the repaired publisher baseline:

| Frontend | Baseline cold median | Owned records cold median | Change | Warm median, baseline → current |
| --- | ---: | ---: | ---: | ---: |
| Self-host | 9.778924 s | 9.133768 s | 0.645156 s / 6.6% faster | 1.948646 → 1.967512 s |
| Reference | 14.087218 s | 13.681170 s | 0.406049 s / 2.9% faster | 2.901257 → 2.899482 s |

These are native CLI timings, excluding the compiler frontend and Make. Warm
time is essentially unchanged. All 12 cold runs compile every unit and perform
two verification links; all 12 warm runs compile/link nothing, hit every receipt
and retain executable inode, mtime, mode, bytes and per-variant object keys.
The refusal logger is empty and all **1,333 recorded inputs** remain unchanged.
No performance samples were discarded from this complete comparison. The
baseline package is
`/nix/store/kd2lsrk73509w1vysv4y86x92w85hj6n-btrc-native-capture-baseline-0`;
its isolated source differs from the preceding reader only in blob preservation.
Results and source provenance: `capture-stable-comparison/results.json` and
`capture-stable-baseline/`. Driver/log:
`build/plan-native-capture-stable-comparison.py` and `.log`.

This recovers part of the cold overhead and repairs a real publication race.
It does not establish the full-product cold goal, a new Make no-op KPI, a memory
improvement or required-host acceptance. Further cold micro-optimizations need
measured impact. The next M6a experiment should profile the remaining **warm**
receipt batch, particularly repeated receipt JSON/trace processing, then address
source resolution and artifact publication. The profile above does not justify
prioritizing runtime snapshot memoization.

### Structured filesystem trace sharing (2026-09-21)

The next warm-path profile isolates NativeHeaderCache lookup without changing
production sources. Each frontend first seeds the instrumented helper's own
private cache, then performs three complete warm requests. Instrumented helper
medians are 1.107 s self-host / 1.844 s reference, excluding driver expansion,
Python consumption, the compiler frontend and Make. The profile validates all
returned blob bytes and hashes. Stage medians are diagnostics and need not sum
to process wall time; trace includes key creation and actual observations.

| Helper stage | Self-host | Reference |
| --- | ---: | ---: |
| Invocation/runtime preparation | 0.052 s | 0.116 s |
| Receipt JSON parsing | 0.142 s | 0.296 s |
| Trace validation, total | 0.615 s | 1.060 s |
| Trace-key creation within validation | 0.288 s | 0.613 s |
| Current filesystem observations within validation | 0.268 s | 0.333 s |
| Published blob verification | 0.009 s | 0.018 s |

The 17/39 units contain 52,817/115,143 trace rows; only 9,779/9,889 need actual
observations after the existing per-session sharing. The old verifier still
serialized every row to create a string key. NativeTraceVerifier now groups
candidates by working directory, operation and path, then compares the complete
owned JSON observation. Grouping alone never permits a hit: status, content
hashes, errors, open working directory and all other fields must match. CWD
transitions remain ordered, failed groups publish no new observations, and
sharing remains limited to one verifier session. Receipt reading/checksums,
current filesystem/content observations, runtime admission and private blob
validation remain intact. This changes neither receipt format nor consumers.

The five new contract tests pass against the old helper and the new helper:
conflicting existence or buffer digests must not share within/across groups,
and relative paths must obey repeated working-directory transitions. The final
reader/context/cache/receipt/consumer run passes **293 tests in 152.29 s**, with
no skips. All **56 product units** match ordinary preprocessing, dependency
files, header reports and diagnostics, with every receipt hitting on reuse.
C++17 warning-as-error build, Python lint/format and whitespace checks pass.
The full final-tree and required-host matrix remains open.

Three alternating native-only cold-cache pairs per frontend, each followed by
warm reuse, give the following medians:

| Frontend | Cold, baseline → current | Warm, baseline → current | Warm saving |
| --- | ---: | ---: | ---: |
| Self-host | 9.794269 → 9.761248 s | 2.000394 → 1.884405 s | 0.115989 s / 5.8% |
| Reference | 14.149564 → 14.140615 s | 2.995671 → 2.630245 s | 0.365427 s / 12.2% |

Cold time is essentially unchanged. All 12 cold runs compile all units and
perform two verification links; all 12 warm runs compile/link nothing, hit
every receipt, and retain executable inode/mtime/mode/SHA and per-variant unit
keys. All 1,333 recorded inputs remain unchanged; the refusal logger is empty.
These native CLI measurements exclude the compiler frontend and Make.

Evidence under `~/.cache/btrc/perf/native-validation-2026-09-21/`:
`warm-lookup-profile/`, `warm-trace-product-qualified/`, and
`warm-trace-native-comparison/`. Build/test/measurement drivers and logs:
`build/plan-native-warm-*`. The production helper is
`/nix/store/byjhlxcgh7mzg6lxi8fag622wv2hk36d-btrc-native-header-0`;
the paired baseline is
`/nix/store/b3skmbvjbr5dcdyksdpr1w6d43jrw46w-btrc-native-header-0`.

The first actual-Make attempt stopped after the helper's unrooted Nix outputs
were removed: the reference candidate could not launch the reader. Its failed
seed and completed self-host pairs remain in `warm-trace-product-make/` and
are excluded from the complete comparison. Both original derivations were
rebuilt to their original output paths; the baseline executable SHA-256 matches
its preceding qualified record. Indirect GC roots now retain the helpers at
`~/.cache/btrc/gcroots/native-header-warm` and `native-header-warm-baseline`.
All source inputs and the restored benchmark wrapper were unchanged.

The complete rerun uses five alternating actual-Make pairs per frontend, the
same native consumer and eight CLI workers, with separate native object caches
for each helper. It includes the compiler frontend, SDK receipts, artifact
publication and native validation. Seeds are excluded.

| Frontend | Baseline Make median | Structured traces Make median | Saving | Remaining to 2 s |
| --- | ---: | ---: | ---: | ---: |
| Self-host | 6.407718 s | 6.139242 s | 0.268476 s / 4.2% | 4.139242 s |
| Reference | 6.043750 s | 5.611816 s | 0.431933 s / 7.1% | 3.611816 s |

All 20 timed builds hit compiler/native caches, reuse all 17/39 units, perform
zero compiles and links, retain emitted generation/executable inode/mtime/mode/SHA
and SDK receipts, and pass debug-map checks. All **1,330 recorded inputs**
remain unchanged. Native command medians are 1.789 → 1.624 s
self-host / 2.781 → 2.419 s reference; initial receipt batches are
1.380 → 1.210 / 2.329 → 1.965 s. Separate 50 ms process-tree
RSS samples are **302.2 → 303.6 MiB / 551.8 → 552.6 MiB**.
These are sampling lower bounds, not guaranteed peak memory or required-host
acceptance. The benchmark wrapper was restored after both attempts.

Current self-host phase medians are source graph **1.311265 s**,
SDK **1.136184 s**, and artifact identity/load
**1.259673 s**. Phase medians are diagnostic rather than an
additive wall-time decomposition. Evidence and raw outputs:
`warm-trace-product-make-qualified/results.json`; driver/log:
`build/plan-native-warm-make-qualified.py` and `.log`.

The no-op targets remain unmet, along with full cold/edit Make workloads,
required-host distributions and final-tree gates. Next profile source resolution
and artifact publication before adding another cache layer. In particular,
FeFrontendResolver.enter reads a dependency before beginSource checks whether
it was already composed; measure repeated nested-source reads, directive
scanning and path validation separately. Any reuse must retain distinct path
bindings, symlink checks and original-read validation. Revisit the remaining
SDK/native metadata and driver costs after measuring these larger phases.

A subsequent self-host compiler sample records an artifact-cache hit, unchanged
emitted files/executable, unchanged source inputs, and unchanged SDK receipt
set/inodes/mtimes/modes/bytes. It is a diagnostic outside the timed comparison.
The first direct invocation used a different process environment from Make and
spent 4.178 s in SDK processing; SDK reuse was not verified for that sample.
It is retained in `warm-source-sample/`, not used as a warm SDK measurement.
The second sample, `warm-source-sample-qualified/`, explicitly verifies SDK
receipt retention. Its instrumented phase times are not KPI samples.

The retained-SDK call tree shows 588 samples under directive-scanner tokenization
in one major source-graph branch, including repeated operator selection and
Vector<string> access. The current Lexer.readOperator scans the vocabulary's
entire ordered operator list for each operator. An indexed grammar-derived
lookup is therefore a concrete next experiment; longest-match ordering,
dynamic grammar behavior and diagnostics must remain intact. In artifact-cache
loading, one payload-digest branch has 741 SHA256_compress samples. Across the
main thread there are 3,274 samples and 871 leaf samples in SHA256_compress.
These overlapping call-tree/leaf counts are attribution, not additive wall-time
shares or speedup predictions. They justify measuring digest execution and
payload handling at their owners, not another unsafe digest memo or restarting
the previously rejected TLS/substring experiments. Repeated source reads remain
a secondary candidate, requiring distinct alias bindings and original-read
validation. Source and artifact phases now take priority over further small
receipt-key tuning.


### Grammar-derived operator lookup (2026-09-21)

The self-hosted TokenVocabulary now derives a byte trie from runtime grammar
registrations. Lexer.readOperator follows matching bytes instead of scanning
every spelling. Terminal ordinals preserve the previous registration priority;
the EBNF parser supplies longest-first order. Duplicate registrations still
replace token names, independent vocabularies remain isolated, UTF-8 bytes are
indexed unsigned, and arbitrary-length spellings work. The derived index does
not change vocabulary cache identity. No source-length rescan, new cache owner,
hardcoded operator list or additional production file is introduced.

Baseline lexer/diagnostic checks passed 304 cases; the nine new behavioral cases
also passed before the change. Expanded candidate qualification passed 540 cases,
with one failure for the now-unused operatorCount accessor and one macOS skip
because /dev/full is absent. Removing the obsolete accessor resolved the
structure failure (24 passed). A fresh Apple Clang two-stage self-host build
produces byte-identical C; its final compiler passes 74 operator/frontend/structure
checks, including both compilers for all nine new vocabulary cases. The expanded
run is retained with its original failure; this is not a full final-tree gate.
Ruff lint/format and repository whitespace checks pass.

Five alternating actual-Make self-host pairs use matching Apple Clang -O2
compiler builds, the same rooted native helper and eight native CLI workers.
The earlier Nix-built test compiler is excluded from this timing comparison.
Seeds and separate memory diagnostics are excluded from the medians.

| Measurement | Baseline | Current | Scope |
| --- | --- | --- | --- |
| Self-host Make | 5.902392 s | 5.467038 s | 0.435353 s / 7.4% reduction |
| Reference Make | unchanged implementation | 5.305695 s | Five warm control runs; no attributed improvement |
| Self-host source graph | 1.230080 s | 0.831632 s | Phase diagnostics, included in Make |
| Sampled self-host process-tree RSS | 307.391 MiB | 353.344 MiB | 50 ms sampling lower bounds |
| Sampled reference process-tree RSS | — | 552.234 MiB | Unchanged control; lower bound |

All 15 timed builds hit compiler caches, hit every native preprocessing receipt
(17 self-host / 39 reference), perform zero compiles and zero links, and retain
emitted artifacts/executables and SDK receipts by inode, timestamp, mode and
SHA-256. Native unit keys remain identical across compiler variants. Both debug
maps pass, all 1,334 recorded inputs remain unchanged, and the owned
benchmark wrapper is restored. Current self-host SDK/artifact phases are
1.087145/1.242250 s. Native command medians are
1.566539/2.286275 s; initial receipt batches are
1.172700/1.851846 s. These medians are diagnostic, not
an additive wall-time decomposition.

The sampled self-host memory increase is **45.953 MiB (15.0%)**. It is an
observed tradeoff, not a demonstrated peak or a proven attribution to the trie.
A follow-up of three alternating pairs measured baseline 304.141/302.609/305.766 MiB
and candidate 308.453/308.578/305.844 MiB: medians 304.141 → 308.453 MiB
(+4.313 MiB / 1.4%). The 353 MiB sample did not recur. Every follow-up build
retains outputs, receipts and native keys. The original sample remains in the
record; true peak-memory qualification is still required. Follow-up evidence:
`operator-lookup-2026-09-21/memory-repeat/results.json`.

The remaining two-second gaps are **3.467 / 3.306 s**. Full cold/edit Make
workloads, required-host distributions, true peak-memory acceptance and final-tree
gates remain open. Next measure artifact digest execution and payload handling,
then remaining source and SDK/native validation costs. Keep all integrity and
invalidation proofs; no new digest memo is justified by this result.

Evidence: `~/.cache/btrc/perf/operator-lookup-2026-09-21/` contains
`bootstrap.json`, complete stage logs, `product-make/results.json`, every raw
Make/native report, debug maps, wrapper backup and `phase-summary.json`.
Drivers and test logs are `build/plan-operator-*`. Prior trial/failure evidence
is retained separately. No p95, other-host or final-cold/edit claim follows
from these five warm samples.


### Native artifact digest (2026-09-21)

The real artifact load reads 16 payloads totaling 197,263,389 bytes. Its measured
portable cost is 0.052 s reading, 0.190 s validating/copying text, 0.917 s SHA-256
and 0.001 s parsing the link plan. Clang -O3 did not materially improve the hash.
Five alternating component pairs reduce hashing 0.914 → 0.084 s and complete
loading 1.163 → 0.327 s through self-host; the reference-compiled probe confirms
the result. All bytes match the existing manifest. These component timings
are separate from the Make comparison below.

ISHA256Digest is an ordinary managed interface retained by the artifact inventory.
Its optional NativeSHA256 implementation selects a checked CommonCrypto binding
on macOS and portable SHA256 on Linux/Windows. The input is borrowed for one
call and the lowercase hex result is owned. MacOSMain supplies this capability;
portable Unix/Windows entries preserve their previous default. Ordinary SHA256
imports and its incremental API remain SDK-independent. Make and Nix select
the native macOS entry only for native host builds; generic cross-release C
keeps the portable entry. No manual native ABI or C shim is introduced.

A global replacement was rejected because it imposed SDK/target requirements on
ordinary SHA users. Bare C callback transport was rejected by the managed-return
ABI proof; using the managed interface preserves that boundary. Both rejected
trials remain in the evidence. Managed-interface lifetime/return tests pass
through both compilers normally and under ASan/UBSan on the real 197 MB input.
The binary/null/empty/Unicode/negative-length/padding/chunk-boundary suite has
96 cases across both frontends and three provider selections. Portable target
C executes on this host; it does not prove a foreign platform ABI.

A fresh Apple Clang -O2 compiler reaches a byte-identical two-stage self-host
fixed point (selfcompiles 68.233/69.367 s, native builds 100.245/100.311 s).
The final binary passes 410 artifact/cache/publication/CLI/provider/bootstrap/
structure checks, with one Windows-only cleanup skip. This is focused local
qualification, not the complete final-tree matrix.

Five alternating actual-Make pairs compare that binary with the qualified
operator-trie compiler built by the same Apple Clang recipe. Current sources,
the rooted native helper and eight CLI workers are held fixed. Setup cache
misses and separate RSS diagnostics are excluded from warm medians.

| Measurement | Baseline | Current | Scope |
| --- | --- | --- | --- |
| Self-host Make | 5.763258 s | 4.909668 s | 0.853589 s / 14.8% saving |
| Reference Make | unchanged | 5.977176 s | Five control runs; no attributed improvement |
| Self-host artifact-hit phase | 1.276858 s | 0.419795 s | Included in Make, not an additional saving |
| Sampled self-host tree RSS | 305.250 MiB | 295.031 MiB | 50 ms lower bounds, separate runs |
| Sampled reference tree RSS | — | 552.703 MiB | Lower bound |

All 15 timed builds hit compiler and native caches, reuse all preprocessing
receipts (17/39 units), perform zero compiles/links, retain generated/executable
and SDK bytes/inodes/timestamps/modes, and keep native unit keys. Debug maps
pass; all recorded inputs are unchanged and the owned wrapper is restored.
Source/SDK/artifact diagnostic phases are 0.890525/
1.152607/0.419795 s. Native medians
are 1.619121/2.490910 s; receipt batch medians are
1.204085/2.014538 s. These medians are not additive.

The remaining 2 s gaps are 2.910/3.977 s. Next profile source resolution,
then SDK/native validation. Cold/edit workloads, required-host distributions,
true peak-memory acceptance and full final-tree gates remain open.

Evidence: `~/.cache/btrc/perf/artifact-execution-2026-09-21/` retains the component
breakdown, native/interface and rejected trials, bootstrap JSON/stage logs,
`product-make/results.json`, raw reports, debug maps and `phase-summary.json`.
Drivers/tests are `build/plan-artifact-*`. No p95 or cross-host claim follows.

#### Native package startup qualification

The first Nix package build aborted before compiler work: importing ctypes in
Nix Python 3.14.6 triggers a libffi trampoline assertion. A standalone import
reproduces it outside the build; directly loading libffi-trampolines reports
`chained fixups, seg_count exceeds number of segments`. The store's content
verification and library code-signature verification pass. This evidence
isolates a host loader/package incompatibility; no compiler behavior or
performance result is inferred from the abort.

The analyzer used ctypes only to read host integer widths. CIntegerWidths now
uses struct.calcsize with explicit native-size formats, retaining the same
ABI semantics without loading a foreign-function runtime. Python documents
that native sizes use the C compiler's sizeof values:
[struct native size and alignment](https://docs.python.org/3/library/struct.html#byte-order-size-and-alignment).
Tests compare every integer rank against compiled C and execute the real
reference compiler with ctypes unavailable. The initial startup regression
fails before the repair; the final numeric suite passes 27 cases. A secondary
fixture error (expecting C on stdout rather than the emitted file) was corrected
and its original failing log is retained. The previously failing Nix Python
now imports the compiler type model successfully. No Nix store binary was
patched and no compiler gate was disabled.

The Make comparison above predates this startup-only Python repair. It remains
a recorded checkpoint, not final-tree timing qualification. The corrected native package
build succeeds, and its output seeds a byte-stable self-host fixed point. Evidence
is in `build/plan-artifact-native-{nix-package*,python-ctypes,libffi-*,width-*}`
and `artifact-execution-2026-09-21/host-width-startup/`.

The next package attempt reached output publication and failed because Nix's
`/homeless-shelter` home is unwritable. The build recipe now supplies the existing
BTRC_STATE_DIR and BTRC_CACHE_DIR settings under TMPDIR. Publication retains its
private journal, lock and atomic recovery behavior; the build does not alter
HOME or bypass publication. The failed log is preserved as
`build/plan-artifact-native-package-publication-failure.log`; the corrected
attempt is `build/plan-artifact-native-nix-package-state.{out,log}`.


Final package `/nix/store/mxzzvyaqmz3pb53wip5as8pb2bh9kv1p-btrcc-0` is retained by
`~/.cache/btrc/gcroots/artifact-native-btrcc`. Its compiler generates itself in
74.480 s; strict Apple Clang -O2 compilation takes 99.574 s; the resulting compiler
reproduces the first generated C byte for byte in 68.713 s. No normalization is
used for this fixed-point comparison. All source snapshot hashes remain unchanged.
The resulting compiler passes 152 final numeric/provider/bootstrap/structure
checks, with one Windows-only cleanup skip (28.27 s). Earlier cache/publication/
CLI qualification remains the separate 410-pass run; these counts overlap and
must not be summed as unique cases. Final touched-file lint/format, codegen and
whitespace checks pass; full final-tree and host/cold/edit acceptance stays open.

Across the old and new private source snapshots, generated compiler C differs
only in the absolute CommonDigest.h include path at line 14. A separate
comparison replacing those two private root prefixes is identical; both raw
files are retained unchanged. That cross-snapshot comparison is additional
emission evidence, separate from the unmodified byte-equality fixed-point gate.
`host-width-startup/` retains package/binary hashes, the final bootstrap source
manifest and stage logs, and `emission-comparison.json`. Final descendant SHA-256:
`951f1c2929bccd2ae3cfb1bc38a6b8b78f53efdb8de4bb97f4fd8513b3886ca1`.

### Source-resolution costs (2026-09-21)

The final packaged-descendant compiler above was profiled on a warm BTRSmith
compiler invocation. The seed was excluded. A native stack sample retained
compiler outputs and SDK receipts, but its attribution was too coarse to choose
the next source optimization. A separate generated-C derivative adds nested
monotonic wall timers around the existing source owners. It compiles under
strict Apple Clang C11 at -O2, preserves managed-return signatures and uses
stack-local profiling frames without a fixed recursion limit. Production
compiler sources and the Make wrapper are unchanged.

Five warm instrumented runs all hit the artifact cache. Output and SDK receipt
bytes, inodes, timestamps and modes are retained; recorded source/input hashes
remain unchanged. The seed is excluded. These measurements are diagnostic:
the actual-Make KPI remains **4.910 s self-host / 5.977 s reference**, and the
instrumented compiler is not a release candidate.

| Owner / work within graph resolution | Calls | Median inclusive time | Median exclusive time |
| --- | ---: | ---: | ---: |
| Graph resolution | 1 | 829.449 ms | 123.918 ms |
| Directive scanning | 444 | 387.945 ms | 98.711 ms |
| Lexer tokenization within scanning | 444 | 289.636 ms | 289.636 ms |
| Source reads | 1,307 | 218.714 ms | 31.986 ms |
| Read-identity validation | 2,614 | 48.058 ms | 5.325 ms |
| Source-path normalization | 11,390 | 78.520 ms | 78.520 ms |
| UTF-8 decoding | 1,307 | 14.565 ms | 14.565 ms |
| SHA-256 | 2,614 | 79.807 ms | 79.807 ms |
| PathTools.absolute | 6,340 | 105.031 ms | 105.031 ms |

Inclusive rows overlap: lexer time is part of scanning; read validation,
decoding, hashing and path handling can be nested in other rows. Exclusive
counters sum exactly to the graph duration in each individual run; medians
need not sum exactly. Import-resolver construction is only 0.029 ms across two
calls and is not a useful optimization target.

**Next experiment:** bring the self-host scanner to parity with the reference
compiler's directive-range reuse. The reference stores ranges keyed by source
content and compiler fingerprint, then lexes/parses only the actual directive
fragments. It falls back to full scanning when a fragment needs surrounding
comment context. Paths, wildcard membership and package/target decisions remain
fresh. The self-host scanner currently lexes each complete source every time.
Its measured scanning cost is 0.388 s: even eliminating that entire cost would
leave most of the 2.910 s Make gap. Cache I/O and fragment parsing reduce the
possible saving further; only a paired Make comparison can establish a gain.

The implementation must use a frontend-owned optional capability and CLI-owned
bounded, atomic storage without a frontend-to-pipeline/CLI dependency. Bind
source bytes, full compiler identity, grammar and schema; reuse typed ranges,
not resolved paths. Bad ranges, corruption, optional storage failures and
context-dependent fragments must cause a miss. Lexical failure must not store
an empty successful scan. The current self-host scanner exits on invalid import
syntax, so speculative fragment validation needs a non-terminating failure
path before cache integration. Preserve ordinary whole-source diagnostics and
the explicit no-cache path. Do not reuse artifact-cache open() for each source:
it validates the entire growing input inventory and would add repeated work.

After scanning, investigate the 0.219 s spent reading sources and remaining
path/traversal work. Both resolvers read a dependency before checking duplicate
inclusion. That also records distinct alias bindings. Moving the duplicate
guard ahead of the read would silently lose that validation. Any reuse must
retain every requested path and its original read identity; a later reread
must still observe changed bytes without blessing a mixed input generation.
Timestamp-only persistent source reuse is not acceptable.

Run the existing directive/import and source-I/O baselines before production
edits. Add self-host cache/fragment/corruption/invalidation regressions, then
prove fresh self-hosting and actual Make retention, cold/edit behavior and
memory. Follow with SDK/native validation, whose proposed 0.4/0.7 s budgets
remain unmet. No optimization implementation or new KPI gain is claimed here.

Evidence: `~/.cache/btrc/perf/source-resolution-2026-09-21/` contains the native
sample, input/output inventories and results. Its `instrumented/` directory
retains the generated C, strict build log, binary identity and all six raw runs
(one seed plus five warm samples). Diagnostic binary SHA-256:
`be7bb298bfb5ffb3b006c287a8a1c47ef588fb71ff5e77322fadb17024813d9a`.
Drivers and logs: `build/plan-source-resolution-{profile,instrument,measure}.*`.

#### Directive cache candidate and interface prerequisite

The self-host candidate now implements FeDirectiveCache with typed source
ranges. FeDirectiveScanner reparses each cached fragment and falls back on
invalid ranges or context-dependent comments. Lexical failure is not stored;
speculative invalid import syntax returns a miss without terminating the
compiler. Compiler/Pipeline composition preserves the explicit no-cache path.
BtrccDirectiveCache owns private, per-key nonblocking leases and bounded atomic
JSON storage under `selfhost-directives-v1`. Keys bind the compiler executable,
grammar vocabulary and source bytes. Stored records validate schema, key,
integer ranges and a checksum, with an 8 MiB read/write bound. Cache failures
are optional misses. Fresh path, package, provider and input validation stays
with the existing frontend/publication owners.

This uncovered a prerequisite in self-host generic normalization. A method
returning `Vector<Part>?` and accepting `Vector<Part>` was rejected despite
matching its interface: the implementation's nested class argument was
normalized to its managed pointer representation, while the interface's was
not. GenericAnalyzer now applies the same existing pass to interface return
and parameter types, preserving unresolved interface type parameters. The
minimal runtime regression fails against the old compiler and passes against
the candidate; negative cases retain distinct class argument identities.

Before production changes, the import/cache-security/source-I/O baseline passes
179 tests with one `/dev/full` skip on macOS (260.69 s). Seven new CLI cases fail
against the old compiler because directive storage is absent. An initial
scanner fixture used unsupported grouped local-path syntax; it was corrected
to the documented `Library.{Math,Vector}` form. The corrected reference scanner
run passes ten cases; subsequent qualification includes grammar mutation too.

The Python reference compiler builds the candidate because the old self-host
compiler rejects the new typed interface. Strict Apple Clang C11/-O2 builds pass,
and the new compiler reaches a raw byte-identical self-host fixed point. Initial
candidate SHA-256 is
`d314749b564c86e1b93ffe6b5ce9090a15cc0659dddc1fc332531714757abfed`.
The focused suite passes 194 checks with one structural-audit failure (81.41 s).
Its cache cases cover corrupt schema/key/checksum/ranges/fragments, truncated
and oversized records, unavailable storage, no-cache behavior, retained warm
entries and changed grammar. Interface/runtime and scanner checks pass through
both frontends.

The structural audit previously counted unknown interface calls only when a
method name identified one implementation. Adding a second `load`/`store`
implementation exposed that limitation. The audit now follows declared
interface conformance and inheritance, with a regression excluding unrelated
methods sharing those names. No definition-only exemptions were added. All
25 structural checks pass in the follow-up (6.37 s); these overlap the initial
suite and must not be summed as unique cases.

The formatted source now reaches another raw byte-identical self-host fixed
point: self-emission takes 66.188 s, strict Apple Clang C11/-O2 compilation
99.047 s, and the resulting compiler reproduces that C in 66.038 s. Its binary
is byte-identical to the initial candidate above. A separate root-normalized
comparison shows no other C changes across the two private source roots;
normalization is not used for either fixed-point proof. All source hashes remain
unchanged. The combined final suite passes **375 checks with one `/dev/full`
skip on macOS** in 343.88 s; this includes the original source/import baseline,
cache/fragment/invalidation behavior, interface/runtime checks and the corrected
structural audit. Touched-file Python lint/format and BTRC format checks pass.

#### Directive cache actual-Make comparison

Five alternating self-host baseline/current pairs, followed by five unchanged
reference controls, measure the complete `make btrsmith-native` invocation:

| Frontend | Baseline median | Current median | Paired saving | Gap to 2 s |
| --- | ---: | ---: | ---: | ---: |
| Self-host | 4.673 s | 4.526 s | 0.147 s / 3.1% | 2.526 s |
| Reference control | — | 5.586 s | Not a paired change | 3.586 s |

Both self-host binaries use matching Apple Clang C11/-O2 builds and consume the
same current source tree, native helper, native-plan implementation and eight
CLI workers. The candidate is faster in all five pairs. All 15 timed runs hit
the compiler/native caches, retain emitted outputs, executable and SDK receipt
bytes/inodes/timestamps/modes, and perform zero native compiles or links. All
17 self-host / 39 reference preprocessing receipts hit; native unit keys and
debug maps remain valid. All 444 self-host directive entries remain unchanged
in every warm run. All 1,348 recorded input fingerprints remain unchanged and
the harness restores its Make wrapper exactly.

The source-graph phase falls from 0.840 to 0.707 s. Current self-host SDK
validation takes 1.076 s and artifact identity/load 0.398 s. Native command
medians are 1.576 s self-host / 2.406 s reference; their initial receipt batches
take 1.182 / 1.950 s. These nested phase medians are diagnostic and are not
additive wall-time accounting. Separate 50 ms process-tree RSS samples measure
307.2 → 302.4 MiB self-host and 551.2 MiB reference; these are lower bounds on
true peak, not memory acceptance or a demonstrated memory improvement.

Seeds are excluded. They do not constitute a paired cold-build distribution.
The older 4.910/5.977 s checkpoint used different run conditions and preceded
the Python startup repair; differences between those checkpoints must not be
attributed to directive caching. This paired comparison establishes only the
0.147 s self-host improvement. Reaching two seconds still requires reductions
of 55.8% self-host / 64.2% reference.

Next profile the cached source path to separate vocabulary/key construction,
private-cache lookup and fragment restoration from source reads/path work.
Select the next repair from those measurements, then revisit SDK/native
validation against PLAN.md's component budgets. Preserve fresh path binding,
original-read checks and content-based invalidation throughout.

Cold/edit behavior, true peak memory, final package and full release/host gates
remain required. Evidence lives in
`~/.cache/btrc/perf/directive-cache-2026-09-21/`; `product-make/results.json`
and `phase-summary.json` retain the comparison, with bootstrap evidence in
`bootstrap-1/` and `bootstrap-final/`. Drivers and raw test/build logs are
`build/plan-directive-*`. Earlier source-profile timings remain baseline
diagnostics, separate from this actual Make result.

#### Cached directive lookup profile

Five warm compiler invocations of a diagnostic generated-C derivative preserve
all generated outputs, SDK receipts and directive-cache entries. The seed is
excluded, source fingerprints stay unchanged, and nested exclusive counters
sum exactly to graph time in every run. This measures individual owners; it
does not replace the actual-Make KPI.

| Owner within source-graph resolution | Calls | Median inclusive time |
| --- | ---: | ---: |
| Source graph | 1 | 755.929 ms |
| Directive scanner | 444 | 278.477 ms |
| Vocabulary identity serialization | 444 | 101.680 ms |
| Directive cache load | 444 | 139.385 ms |
| Cache key construction | 444 | 29.967 ms |
| Private directory/lease open | 444 | 85.246 ms |
| Entry read and validation | 444 | 22.576 ms |
| Fragment restoration | 444 | 37.802 ms |
| Fragment scanning | 1,745 | 7.281 ms |
| Source reads | 1,307 | 233.466 ms |

Inclusive rows overlap. Source reads include hashing and path work; fragment
scanning is nested within restoration. The complete operative vocabulary is
serialized repeatedly even though it is unchanged after grammar construction.
The next candidate retains that identity within TokenVocabulary and invalidates
it before every keyword, operator or annotation mutation. It changes neither
the identity format nor cache admission and filesystem validation. Cache-open
lifetime changes are deferred: their measured 85 ms ceiling does not justify
weakening path/lease validation. SDK/native validation remains the larger
follow-up after this bounded owner-level repair.

Evidence: `directive-cache-2026-09-21/lookup-profile/` under the performance
cache, with generated-C instrumentation, strict C11/-O2 build, six raw runs,
input/output fingerprints and counters. Scripts are
`build/plan-directive-lookup-{instrument,measure}.py`. The expanded pre-change
scanner/vocabulary baseline passes 48 cases through both frontends in 22.59 s.
The first attempt passed 33 cases and stopped 15 fixture cases on a source input
identity change in the synced workspace; its log is retained, and the unchanged
retry passes all cases. No production memo speedup is claimed by this profile.

#### Vocabulary identity reuse

TokenVocabulary now retains its serialized identity until a keyword, operator
or annotation mutation invalidates it. The maps remain private, all mutation
methods invalidate before changing data, and serialization/key formats are
unchanged. This avoids rebuilding the same JSON tree per source without
changing cache admission, source reads, path checks or lock lifetimes.

The formatted source reaches a raw byte-identical self-host fixed point:
69.098 s first emission, 99.963 s strict Apple Clang C11/-O2 compilation and
69.107 s second emission. The resulting compiler passes **213 focused tests
without skips** in 82.99 s: directive-cache/scanner, vocabulary, artifact-cache,
interface boundary and compiler structure coverage. Mutation tests include
keyword/operator replacement, annotation changes, owner isolation and retained
identity strings after mutation/destruction. These counts overlap earlier
qualification; do not sum them as unique tests.

Five alternating actual-Make pairs measure **4.703 → 4.611 s self-host**, saving
**0.091 s / 1.9%**; the candidate is faster in all five pairs. Five unchanged
reference controls measure **5.567 s**. Both binaries use matching Apple Clang
builds and consume the same current source tree/helper/native plan. All 15 timed
runs hit compiler/native caches, retain output and SDK receipt bytes/metadata,
and perform zero compiles or links. All 17/39 preprocessing receipts hit,
native unit keys and debug maps remain valid, and all **1,350 input fingerprints**
remain unchanged. All 1,332 existing directive entries remain unchanged in every
warm run; this inventory includes earlier compiler namespaces. The harness
restores its wrapper exactly. Seeds and separate memory probes are excluded.

| Diagnostic phase | Paired baseline | Current |
| --- | ---: | ---: |
| Self-host source graph | 0.743 s | 0.643 s |
| Self-host SDK validation | 1.134 s | 1.134 s |
| Self-host artifact identity/load | 0.406 s | 0.415 s |
| Self-host native command | 1.606 s | 1.614 s |
| Self-host native receipt preparation | 1.195 s | 1.204 s |
| Reference native command (unchanged control) | — | 2.390 s |
| Reference native receipt preparation | — | 1.939 s |

Nested phase medians are not additive. Separate 50 ms process-tree RSS samples
are **304.9 → 274.9 MiB self-host / 551.4 MiB reference**; these are lower bounds,
not true peak-memory acceptance or a demonstrated memory reduction. Earlier
4.526/5.586 s medians came from another run; the gain claimed here is solely
against the paired 4.703 s baseline. Current two-second gaps are **2.611/3.567 s**.

Next profile native receipt preparation in both frontends, separating Python
setup, helper/driver work, receipt decoding, fresh filesystem validation and
blob consumption. Preserve correctness; prioritize this multi-second cost
before more small source-cache lifetime changes. Cold/edit, final package,
required-host and full final-tree gates remain open.

Evidence: `~/.cache/btrc/perf/vocabulary-identity-2026-09-21/` contains bootstrap
and actual-Make records, phase summaries, retention inventories and raw logs.
Drivers/test logs are `build/plan-vocabulary-identity-*`. Final compiler SHA-256:
`0c0263b1c1f456105870c08dc76f213db45e4d3076d1262ef0dc73f6beb0dda6`.

### Native receipt preparation profile and path-context candidate

Diagnostic timers through the real Make wrapper measured five warm runs per
frontend after excluded seeds. All ten retain compiler outputs, SDK receipts,
native preprocessing receipts and native unit keys, with 17/39 receipt hits,
zero compiles/links and 1,352 unchanged input fingerprints. Both wrappers are
restored. These are phase diagnostics, not replacement Make KPIs.

| Native preparation owner | Self-host | Reference |
| --- | ---: | ---: |
| Complete native build | 1.611 s | 2.405 s |
| Initial receipt preparation | 1.194 s | 1.954 s |
| Helper process/read | 0.946 s | 1.485 s |
| Concurrent driver expansion span | 0.217 s / 17 calls | 0.397 s / 39 calls |
| Response-blob reads, summed | 0.0026 s | 0.0057 s |

Expansion calls overlap; their summed durations are not elapsed build time.
The first diagnostic attempt added an environment variable and therefore
changed the correctly environment-bound receipt identities. It compiled fresh
units and is excluded. The corrected run passes its destination as an argument
through the actual Make wrapper, with no new child environment variable.

A diagnostic helper then isolated receipt parsing and filesystem verification.
Five warm samples per frontend, after private-cache seeds, preserve complete
response descriptors and checksummed blobs. Parsing takes about 0.137/0.294 s;
trace validation about 0.446/0.673 s. Within validation, directory/key work takes
0.116/0.245 s, complete-record comparisons 0.030/0.069 s, fresh observations
0.282/0.337 s, and record copying about 0.012 s in both. These nested times must
not be added to the parent phases. The self-host trace has 52,817 rows with
43,038 reused observations; reference has 115,143 rows with 105,254 reused.
Their receipts total 27.1/59.0 MB. Every path-bearing row uses an absolute path.

An explicit-O2 experiment was rejected before adoption: the effective baseline
compiler command already contains -O2 from Nix. No build flag changed. The
candidate instead omits current-directory key work only for absolute paths
whose recorded opening directory is also absolute or absent. Relative paths,
relative opening directories and ordered directory transitions stay bound to
the current directory; complete observation comparison and fresh validation
remain unchanged. The native package builds with strict warning gates.

Before that change, 87 cache/preprocessing tests pass; three extended directory
cases also pass, including an absolute file with a relative opening directory
that exists only in one working directory. The first broader candidate run
used the wrong C++ adapter provider and began an unnecessary compiler rebuild;
it was stopped after 195 passes and one missing-C++-header failure, and its log
is retained. The corrected run passes 242 checks but has 53 self-host fixture
setup errors: interface-only generic types are not registered by the compiler.

That prerequisite is reproduced by three minimal interface-only return,
parameter and nested-container signatures, while an unresolved generic
interface remains valid (three expected failures, one pass). The analyzer's
existing generic-instance discovery now visits interface signatures using their
unresolved type-parameter set. The first old-seed/repaired generation comparison
fails because newly discovered interface instances change declaration order;
the original failure and raw C are retained. Compiling the repaired output
(99.042 s, strict Apple Clang C11/-O2) and self-emitting again (67.121 s) gives
**raw byte-identical C**, with unchanged source inputs. The final compiler and
native helper pass **445 focused tests without skips** in 193.32 s, including
the previously failing codec fixture and all interface signature regressions.

Five alternating actual-Make pairs per frontend measure **4.388 → 4.248 s
self-host / 5.283 → 5.062 s reference**. The gain is **0.140 s (3.2%) /
0.221 s (4.2%)**, with the candidate faster in all ten pairs. Both variants use
the same freshly built compiler and native consumer; only the helper changes.
Separate object-cache namespaces retain each helper's receipts while preserving
the same generated and executable output paths. Seeds are excluded, including
the 343.049 s reference candidate rebuild; these are not cold-build KPI samples.

All 20 timed runs hit compiler caches and all 17/39 preprocessing receipts,
retain output/SDK receipt bytes and metadata, preserve native unit keys and
perform zero compiles/links. Debug maps remain valid. All **1,357 input
fingerprints** stay unchanged, and both harness wrappers are restored.

| Diagnostic phase | Baseline | Current |
| --- | ---: | ---: |
| Self-host source graph | 0.610 s | 0.609 s |
| Self-host SDK validation | 1.078 s | 1.008 s |
| Self-host artifact identity/load | 0.399 s | 0.398 s |
| Self-host native command | 1.528 s | 1.452 s |
| Self-host native receipt preparation | 1.138 s | 1.063 s |
| Reference native command | 2.281 s | 2.071 s |
| Reference native receipt preparation | 1.848 s | 1.639 s |

Nested phase medians are not additive. Separate 50 ms process-tree RSS sampling
is 302.9 → 305.2 MiB self-host / 551.3 → 551.2 MiB reference. These are lower
bounds on true peak; no memory reduction or memory acceptance is established.
Earlier 4.611/5.567 s results are from another checkpoint; this change's gain
is established only against the paired baselines above. Current gaps to two
seconds are **2.248/3.062 s**. Next address receipt decoding/materialization and
fresh observations, then remaining SDK and source costs. Full cold/edit,
final-package, required-host and final-tree qualification remains open.

Evidence: `~/.cache/btrc/perf/native-receipt-profile-2026-09-21/` retains the
excluded initial diagnostic, corrected `actual-make/`, helper/trace profiles
and effective build flags. `native-path-2026-09-21/` retains the candidate
package, prerequisite generation transition and final fixed point, plus
`product-make/results.json` and `phase-summary.json`. The final compiler SHA-256
is `a908c88226c396095257e391423b4655013e25ecf8e4de3c9fbdf91e3ed28772`.
Drivers/logs are
`build/plan-native-receipt-*`, `build/plan-native-path-*` and
`build/plan-interface-only-*`.


### Shared trace fragment read prototype, September 22

The next profile keeps production sources unchanged and instruments fresh
observation operations in an isolated native helper. After a private seed,
five warm runs per frontend retain response descriptors and verify all returned
blob bytes. Receipt parsing takes **0.133/0.283 s**; trace verification takes
0.319/0.417 s. Fresh opens account for about 0.110/0.111 s across 7,480/7,568
opens. Fetching CWD takes about 0.016 s; entering and restoring directories
together costs only 0.0074 s. Skipping directory semantics is therefore not the
next optimization. Buffer operations, including their nested opens and status
checks, take 0.155/0.210 s. These diagnostic medians overlap and are not Make KPIs.

A read-only inventory verifies the stored receipt checksums before examining
representation costs. The 17/39 receipts total 27.1/59.0 MB, including
24.5/52.9 MB of filesystem traces and 2.6/6.1 MB of input contracts. Their
52,817/115,143 rows contain just 9,763/9,851 distinct complete rows (about 5 MB).
Repeated status objects account for 8.1/17.5 MB but only about 0.6 MB of unique
status data. Inventory byte counts use compact JSON; they are not speedup claims.

The representation experiment retains every original row and its order.
Boundaries depend on each complete serialized row's digest, with a nominal
64-row interval and a 256-row maximum. This lets shared runs converge after
different prefixes. It yields 790/1,692 fragment references to 214/236 unique
fragments, totaling **6.46/6.84 MB** of unique trace data plus **53/113 KB** of
reference indexes. Alternative intervals of 16/32/128 rows are retained in the
experiment record; smaller intervals reduce bytes but increase file operations.

An isolated C++ reader then consumes these fragments through the existing
checked private-file reader and SHA-256 validation. Parsed immutable fragments
belong to the cache invocation, with a 64 MiB encoded-byte admission limit;
overflow fragments are temporary. Each expanded receipt also has a 64 MiB
limit. The verifier walks arrays in order with one pending-observation set for
the whole receipt, preserving the existing failed-group transaction boundary.
Production capture/storage remains inline: an offline experiment converter
rewrites only private seeded receipts. This is not the proposed shipping format.

Five alternating helper pairs per frontend measure **0.792 → 0.685 s self-host /
1.192 → 0.886 s reference**, saving **0.108 s (13.6%) / 0.306 s (25.7%)**.
All 20 timed runs hit every 17/39 receipt, verify identical preprocessed response
bytes across variants and retain cache file bytes/inodes/mtimes. The captured
input fingerprints remain unchanged. No production source or Make wrapper is
modified. These are helper component measurements; the actual-Make KPI remains
**4.248/5.062 s**, and cold publication and memory costs remain unmeasured.

Eight isolated probes pass: unchanged hit, corrupt fragment, missing fragment,
invalid reference, wrong JSON shape, failed filesystem observation, expanded
size ceiling and restored hit. These do not replace production tests for
concurrent publication, fragment-boundary CWD transitions, failed-group
isolation, migration, or native invalidation. The next implementation belongs
to `NativeHeaderCache` and `NativeTraceVerifier`; reuse existing storage owners,
version the format and preserve immutable publication semantics. Qualify the
writer's cold cost and complete actual-Make pairs before adopting a KPI claim.

Evidence: `~/.cache/btrc/perf/native-observation-2026-09-22/` contains
`receipt-inventory.json`, `fragment-experiment.json`, the instrumented helper
under `profile/` and the read prototype under `fragments/`, including raw logs,
paired results and probes. Drivers are `build/plan-native-observation-*`,
`build/plan-native-receipt-inventory.py`, `build/plan-native-trace-fragments.py`
and `build/plan-native-fragment-prototype-*`. Both diagnostic helpers are rooted
in the local Nix store. This records the read-only prototype checkpoint;
production qualification follows below.


### Production shared trace fragments, September 22

The fragment implementation now belongs to the existing `NativeHeaderCache`
and `NativeTraceVerifier`. V2 receipts refer to ordered, checksummed immutable
fragments; V1 inline receipts remain readable. Content-defined boundaries have
a nominal 64-row interval and a 256-row maximum. Checked private reads reject
wrong ownership, modes, links, types, sizes and unstable snapshots. Publication
repairs invalid fragments without modifying aliases, preserves valid fragment
inodes under concurrent writers, and synchronizes fragment data/names before
publishing the referring receipt. The receipt plus expanded fragments is
bounded by the existing 64 MiB ceiling. Parsed fragment retention is limited to
64 MiB of encoded data per invocation; overflow arrays remain temporary for
that validation. This is an encoded-data bound, not a bound on total heap RSS.

The verifier keeps one initial/final CWD and pending-observation transaction
across all fragments. It still compares complete records and obtains fresh
filesystem answers; parsing reuse does not itself authorize an observation.
The compiler sources and previously fixed-point-qualified `a908c882` binary
are unchanged for this native-helper change.

The baseline passes **89 tests**. Initial production cache/preprocessing coverage
passes 105. The first broader launcher mistakenly selects the old package;
it is stopped after 12 failures and 76 passes, and its log is retained. The
corrected launcher explicitly selects the new package and passes **463 tests
without skips** in 199.24 s. Eighteen new parametrized cases cover ordered trace
round trips, old receipts, malformed/missing/corrupt fragments, repair without
alias mutation, expansion ceilings, relative paths/opening directories across
fragment boundaries, retained-data overflow and concurrent inode preservation.
A two-FIFO-barrier test changes a file after the first fragment is checked but
before its group fails, proving those earlier observations cannot leak into the
next group. Touched Python lint/format and both repository whitespace checks pass.
Counts overlap earlier suites and must not be summed as unique coverage.

Five alternating cold-helper pairs per frontend use a new private cache each
time and include real preprocessing, serialization, synchronization and
publication. They measure **5.408 → 5.521 s self-host / 9.765 → 9.921 s reference**:
additional **0.113 s (2.1%) / 0.156 s (1.6%)**. All 20 runs capture every unit,
return identical preprocessed bytes across variants, and retain unchanged input
fingerprints. The current caches contain 214/236 unique fragments. This is
component cold evidence, not a cold product-build or OS-cold qualification.

Five alternating actual-Make pairs per frontend measure **4.249 → 4.180 s
self-host / 4.995 → 4.732 s reference**, saving **0.070 s (1.6%) / 0.263 s (5.3%)**.
The candidate wins all ten pairs. Both variants use the same compiler and native
consumer; only the helper differs. All 20 timed runs hit the compiler and all
17/39 preprocessing receipts, preserve output/SDK/native receipt and fragment
bytes/inodes/mtimes, retain unit keys, and perform zero compiles or links.
Debug maps pass, all **1,362 input fingerprints** stay unchanged, and both
harness wrappers are restored. Setup seeds and separate memory probes are
excluded; do not attribute differences from earlier checkpoints to this change.

| Diagnostic phase | Baseline | Current |
| --- | ---: | ---: |
| Self-host source graph | 0.606 s | 0.611 s |
| Self-host SDK validation | 1.020 s | 0.986 s |
| Self-host artifact identity/load | 0.400 s | 0.403 s |
| Self-host native command | 1.449 s | 1.346 s |
| Self-host native receipt preparation | 1.057 s | 0.955 s |
| Reference native command | 2.047 s | 1.802 s |
| Reference native receipt preparation | 1.618 s | 1.374 s |

Phase medians are diagnostic and not additive. Separate 50 ms process-tree RSS
samples are 291.3 → 288.1 MiB self-host / 551.3 → 551.0 MiB reference. These
sampling lower bounds establish neither true peak acceptance nor a memory
reduction. The remaining two-second gaps are **2.180/2.732 s**. Next profile
current SDK/runtime/provider preparation and native driver/receipt preparation
before selecting a further change; the inline-receipt profile is historical.
Full final-tree, cold/edit, final compiler package and required-host gates remain
open. This slice does not complete M6a.

Evidence: `~/.cache/btrc/perf/native-fragment-2026-09-22/` contains the package,
`cold-helper/results.json`, and `product-make/results.json`/`phase-summary.json`.
Drivers and failure/final logs are `build/plan-native-fragment-*`. The production
helper is `/nix/store/59q7479idh1jsgv41y5ckmn7nc4bqnh4-btrc-native-header-0`,
rooted as `native-fragment-current`; its source SHA-256 is
`aae8d225149bc94ece2b6dc7285552e2c088aef851fc3c7674e096badbf39329`.

### Native preparation owner profile, September 22

The production v2 fragment implementation is unchanged. An isolated diagnostic
helper and Python entry wrappers time the actual Make consumers, using the same
qualified self-host compiler. No profiling environment variable is added:
the helper writes to a compiled-in diagnostic destination outside its protocol.
An excluded seed establishes each frontend's diagnostic helper/cache identity,
then five warm runs per frontend prove full compiler and 17/39 native receipt
hits, zero compiles/links, retained output and SDK/native receipt/fragment
bytes/inodes/mtimes, retained native unit keys and unchanged recorded inputs.
All three temporary wrappers are restored. Seeds take 126.178/347.831 s; these
are setup costs, not product cold-build KPI measurements.

| Instrumented owner, median | Self-host | Reference |
| --- | ---: | ---: |
| SDK helper main wall | 0.383 s | 0.389 s |
| SDK preparation, all 16 groups | 0.036 s | 0.037 s |
| SDK cache lookup, including trace validation | 0.319 s | 0.320 s |
| SDK trace validation | 0.225 s | 0.224 s |
| SDK fresh filesystem observations | 0.190 s | 0.188 s |
| Native helper main wall | 0.664 s | 0.894 s |
| Native cache lookup, including trace validation | 0.419 s | 0.581 s |
| Native trace validation | 0.332 s | 0.440 s |
| Native fresh filesystem observations | 0.281 s | 0.343 s |
| Native compiler runtime observation | 0.095 s | 0.093 s |
| Native compiler runtime finishing | 0.065 s | 0.066 s |
| Parallel driver expansion span, 17/39 calls | 0.210 s | 0.389 s |
| Native receipt preparation, Python parent | 1.003 s | 1.413 s |

Timers are nested and overlap; do not add this table to predict build time.
The summed driver worker times are 1.252/2.945 s, whereas the elapsed spans
above reflect their concurrency. Helper main excludes loader/process startup.
Native cached blob consumption totals only 0.003/0.006 s in Python. SDK helper
runtime capture totals about 0.002 s, so optimizing it offers very little.

Reference native-import resolution is 0.750 s, including 0.480 s of session
preparation, 0.065 s of C++ include discovery, 0.066 s of semantic decoding
and 0.013 s of batch decoding. The outer source resolver is 1.509 s and
**includes** native-import resolution. These nested medians are not an additive
decomposition. Self-host caller internals were not instrumented; the earlier
qualified SDK phase of 0.986 s must not be attributed entirely to the helper,
nor can its difference from a separately instrumented helper run be treated as
an isolated caller measurement.

Instrumented Make medians are 4.278/4.991 s. They include profiling overhead
and do not replace the uninstrumented **4.180/4.732 s** KPI. This experiment
provides attribution, not a new speedup. No compiler/helper production change
or new acceptance-test result is claimed by this profiling slice.

The next bounded investigation is filesystem observation cost by operation,
alongside self-host caller timers for startup, response validation, decoding
and projection. Any sharing must preserve fresh content checks, negative
lookups, directory/opening contexts, complete row comparisons and failed-group
isolation. Delaying semantic projection until an artifact miss is conditional
on measured caller cost and proof that cache identity and cold-path diagnostics
remain equivalent. Small runtime/hash savings alone cannot close the remaining
2.180/2.732 s gap. M6a and the full final-tree/required-host gates remain open.

Evidence: `~/.cache/btrc/perf/native-preparation-2026-09-22/` contains diagnostic
`reader.cpp`, `package.nix`, `package.json`, and `actual-make/results.json` with
raw per-run C++/Python profiles and `owner-summary.json`. Reproduction drivers
are `build/plan-native-preparation-profile-{build,entry,make,summary}.py`.
The isolated helper is
`/nix/store/lgl4nljicsqxsxmvxvxrjc9libsj6kvz-btrc-native-preparation-profile-0`,
rooted as `native-preparation-profile`. Production source SHA-256 remains
`aae8d225149bc94ece2b6dc7285552e2c088aef851fc3c7674e096badbf39329`.

### SDK caller and filesystem operation profiles, September 22

Two isolated diagnostics refine the previous owner profile. Production sources
and the qualified Make KPIs remain unchanged at **4.180/4.732 s**.

The operation helper replays the actual native preparation requests against
private v2 caches, with an excluded seed and five warm samples per frontend.
Every warm response hits all 17/39 units, verifies all returned blob bytes and
retains response descriptors and cache bytes/inodes/mtimes. Recorded inputs
remain unchanged. Additional timers inside fresh observation show:

| Native observation owner | Self-host median | Reference median |
| --- | ---: | ---: |
| File opens, 7,480/7,568 calls | 0.113 s | 0.117 s |
| Content SHA-256, 1,973/1,995 calls | 0.102 s | 0.159 s |
| Buffer acquisition | 0.007 s | 0.007 s |
| Open-file status | 0.002 s | 0.002 s |
| Current directory reads | 0.017 s | 0.020 s |
| Enter/restore opening directory, combined | 0.008 s | 0.009 s |

These timers nest inside trace validation and do not add to prior phase
measurements. `NativeFileTrace::digest` already uses CommonCrypto on macOS;
the profile does not justify repeating that provider switch. File contents
must still be checked, and directory semantics remain required. The earlier
operation profile and its original reproduction files are preserved.

For self-host caller attribution, a diagnostic copy of the qualified emitted
compiler C wraps 28 existing owner functions with monotonic timers. Atomic
counters support the existing reader workers; timing is active only during
native-import resolution. No production source or qualified compiler binary is
modified. The first diagnostic C build fails because timer declarations were
inserted after some wrapped functions. Its source and error log are retained;
a corrected build places them before the earliest wrapped owner and passes
strict C11 compilation at the existing optimization/warning settings.

The complete BTRSmith compiler command runs with private output/cache paths:
one excluded 119.804 s seed, then five artifact hits. All warm runs retain the
emitted generation and SDK receipt/fragment bytes/inodes/mtimes. This omits the
native compile/link step and is not a Make KPI measurement.

| SDK caller owner | Self-host median | Calls |
| --- | ---: | ---: |
| Native declaration resolution | 1.033 s | 1 |
| SDK session preparation | 0.453 s | 1 |
| Header consumption, including batch decoding | 0.075 s | 41 |
| C++ include discovery | 0.075 s | 1 |
| Semantic response decoding | 0.246 s | 41 |
| Batch decoding | 0.059 s | 3 |
| Declaration import | 0.137 s | 1,013 |
| JSON parsing, nested in the owners above | 0.128 s | 61 |
| Cached blob consumption, summed worker time | 0.025 s | 32 |

Direct comparison with production C initially fails because the deliberately
private output directory changes generated `#line` filenames. The failure is
retained. Follow-up validation maps **only exact output filenames in those
line directives**: all remaining bytes match all 15 production C units.
`validation.json` retains directive counts and original/normalized/production
hashes, plus unchanged input checks. This establishes the scope of diagnostic
output equivalence; it is not a replacement for raw bootstrap equality.

The next implementation proposed at that checkpoint was an owned prepare/project
split in both importers (superseded by the user decision below):
read and validate native responses and their identity before artifact lookup,
then run existing decoding/projection on a miss. Roughly 0.38 s of self-host
semantic work is a candidate saving, not an achieved speedup; batch handling
and reference behavior must be measured independently. Preserve direct eager
APIs, identity coverage, cold diagnostics and bounded memory. Preparation must
not expose a later reader failure before an earlier binding's semantic error.
Any bounded eager fallback must consume each response once without changing
identity. A miss must reuse preparation instead of launching a duplicate SDK
session. Tests, fresh compiler qualification, cold cost and paired Make runs
are required before adopting the change. M6a remains open.

Evidence lives in `~/.cache/btrc/perf/native-operation-2026-09-22/` and
`~/.cache/btrc/perf/selfhost-sdk-profile-2026-09-22/qualified/`; failed diagnostic
compiler evidence remains in the latter's parent. Reproduction drivers are
`build/plan-native-operation-profile-*` and `build/plan-selfhost-sdk-profile-*`.
The operation helper is
`/nix/store/6dhj6y4xw53bgwwhjicwziamcy20bv69-btrc-native-operation-profile-0`,
rooted as `native-operation-profile`.

### Unchanged latency closed; edit and cold acceleration, September 22

The user closed unchanged-build latency at **≤5 s**. The qualified actual-Make
medians are **4.179815 s self-host / 4.732492 s reference**, and all ten current
samples are below 5 s (maxima **4.212551 / 4.793972 s**). Keep this as a regression
guard; the old 2 s median / 3 s p95 campaign is retired. Full-tree correctness
and required-host qualification remain open.

The partially implemented SDK prepare/project change is not adopted: its exact
nine-file patch is saved outside the tree at
`~/.cache/btrc/checkpoints/2026-09-22-m6a/deferred-native-projection-shelved.patch`
(SHA-256 `92e7bc7015629695cf9f7be9f73cf7d3818c894a3ad5d5cbc7f80590e6dafa52`).
Production files were restored from the index to preserve the qualified work.
Do not restart that experiment as the next optimization task.

The active assignment is **≥10× faster edit-to-executable and cold self-host
BTRSmith development builds**, within bucket 1. Compiler bootstrap remains a
separate metric. Fresh diagnostics use the actual product Make command, the
qualified compiler/helper and eight native jobs, on an isolated complete copy
of the tracked product. The original product is not edited. Detailed results
and the next implementation contracts follow below.

### Fresh actual-Make cold and live body-edit diagnostics, September 22

The qualified a908c882 self-host compiler and 59q native helper build an
isolated copy of all 830 tracked BTRSmith files. macOS Apple Silicon, dev
`-O0`, debug information, eight native jobs. Cold compiler/SDK/object/output
caches are empty; installed toolchains and packages are present, OS page cache
uncontrolled. Exact commands, environment, hardware and hashes are recorded in
`~/.cache/btrc/perf/edit-cold-2026-09-22/continued-results.json`.

| Scenario | Make wall | Compiler wall | Native wall | Compiled / reused | Links |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold | 134.608 s | 124.340 s | 9.304 s | 17 / 0 | 2 |
| edit-navigation | 126.747 s | 119.000 s | 7.308 s | 1 / 16 | 2 |
| edit-ui-live | 112.325 s | 107.080 s | 4.935 s | 1 / 16 | 2 |
| edit-audio-adjacent | 113.142 s | 106.980 s | 5.843 s | 1 / 16 | 2 |

This is one sample per scenario, not an acceptance distribution or an
optimization comparison. Each accepted edit changes an implementation literal,
one generated C unit and the executable while preserving signatures, layouts,
generic/call/effect shape and unrelated line counts. Navigation changes the
return label; UI changes the live library title; the audio-adjacent fixture
changes a background cancellation message. The original UI fixture edits an
unreachable toolbar method and fails the benchmark's changed-code assertion:
119.190 s compiler work, identical C, zero native compiles/links. That failure
is preserved in `results.json` and excluded from live edit results. Continuation
uses a verified live method. Original product, mirror sources and all recorded
compiler/tool inputs pass final hash checks.

The cold compiler's sequential phase marks total 114.496 s: analysis 21.570,
lowering 37.213, optimization 19.125, emission 27.750 and other marks 8.838.
Setjmp is 15.916 s **within** optimization; generic/declaration lowering are
15.416/20.740 s **within** lowering. Do not add nested detail again. Another
9.844 s lies outside phase marks but inside compiler wall; publication,
serialization and destruction need separate attribution. Native wall is
9.304 s; summed parallel scan/compile times are not additional elapsed time.
The emitted C inventory has 15 units / 182,535,171 bytes, plus two adapters.

The compiler still reruns whole-program analysis, lowering, optimization and
emission after each local edit despite reusing 16/17 native objects. That
supports M11 typed module/IR reuse as the main edit mechanism. Code inspection
also finds repeated count/render passes, all-program preambles and per-line
filename escaping in the emitter. These are M7 candidates, not established
savings. M7 starts with bounded owner attribution and the dominant emission
cut, then setjmp and lowering; M8a tests allocation reduction; M11 proves
stable dependencies, incremental typed work and bounded cold scheduling.

Initial design envelopes are 13 s cold (7 compiler + 5 native + 1 outer) and
10 s edit (4.5 compiler + 4.5 native + 1 outer). One tenth of the cold sample
is 13.461 s. These proposed budgets do not establish 10×; freeze repeated
baselines and acceptance distributions on each required host. Keep correctness,
debug behavior, reference parity, bootstrap, memory and runtime gates. Empty
cold caches cannot be replaced by hidden prebuilt product/stdlib artifacts.

`summary.json` records phase groups and validation; original and continuation
logs retain the rejected fixture. Reproduction drivers are
`build/plan-edit-cold-baseline.py`, `build/plan-edit-cold-continue.py` and
`build/plan-edit-cold-summary.py`. Source restoration runs even on failure.

### M7 debug filename reuse: implementation and correctness checkpoint, September 22

A diagnostic copy of the qualified compiler wraps 15 existing emitter/driver
owners with monotonic timers. One full BTRSmith compiler miss takes 110.071 s;
this instrumented compiler-only run is not a Make KPI. All 15 generated C units
match the qualified compiler after mapping only exact generated-output filenames
in `#line` directives. Recorded inputs remain unchanged. The first harness
attempt selected Make's `mkdir -p` line instead of the compiler command and
failed before compilation; that evidence is retained under
`emission-owner-2026-09-22/failed-command-selection/`.

| Owner, nested timings | Seconds | Calls |
| --- | ---: | ---: |
| Split emission | 24.632 | 1 |
| Function rendering, including count pass | 20.480 | 39,216 |
| Debug directive emission | 15.130 | 507,509 |
| Filename escaping, inside debug directives | **14.677** | **507,509** |
| Parameter formatting | 0.839 | 591,235 |
| Joining output | 0.706 | 17 |
| Generated-line reset fixup | 0.487 | 15 |
| Prologue line-vector splice | 0.426 | 17 |
| Artifact-cache storage | 0.181 | 1 |
| Output-generation publication | 0.281 | 1 |

These nested times must not be summed. The unmarked compiler residual is not
mostly artifact storage/publication; its remaining lifetime/cleanup attribution
is still open. The emitted debug inventory has **420 distinct encoded filenames,
51,845 bytes of encoded values**, across the 507,509 directives. This is a
static inventory, not a peak-memory measurement; keys and map overhead are extra.

Both emitters now retain escaped filenames by exact string value for one
emission, sharing them across counting and unit rendering. Each public emission
starts a fresh map. Escaping rules, line numbers, split boundaries, output text
and the pure reference escaping helper are unchanged. There is no raw-address
cache, filesystem observation cache or process-global retention.

Baseline coverage passes **224 tests / four Linux-only skips**. The expanded
final run with the fresh compiler passes **245 tests / the same four skips**,
covering split units, debug paths, artifact reuse, C++/Objective-C emission and
CLI flags. Two encoding-count regressions fail against the staged old emitter
and pass after the change. New end-to-end cases compile, link and execute split
output with quotes, backslashes, question marks and newlines in source/output
paths through both frontends. Initial test assumptions about the count pass's
old debug filename and an omitted self-host target were corrected; their failed
logs are retained. The first red-run invocation lacked PYTHONPATH; the corrected
isolated old-emitter run demonstrates both intended assertion failures.

The fresh self-host binary is
`3cf253ec3ea736fe0e68b9b21ff589c5920c2ea8ab1b9467682f41d3559e4eb0`.
Strict C11/O2 compilation passes, and its next self-emission is byte-identical
to the seed-generated compiler C. Bootstrap evidence lives at
`~/.cache/btrc/perf/emission-owner-2026-09-22/bootstrap/results.json`.
Production input hashes remain unchanged during that proof. Focused Ruff and
format checks pass. Full final-tree/required-host/memory gates remain open.

Next: two alternating baseline/current pairs of actual-Make cold and live
navigation-edit builds, with an unchanged control after each cold seed. Keep
separate empty compiler/SDK/object/output caches per round/variant and retain
all output hashes and native reuse counts. Do not claim an elapsed-time gain
from the owner profile or correctness checks alone. After measurement, move to
M7's next dominant setjmp/lowering work; unchanged latency remains closed at 5 s.

### M7 filename reuse: completed actual-Make comparison, September 22

Two alternating baseline/current rounds use the same isolated complete product,
dev `-O0` plus debug, eight native jobs and the qualified 59q helper. Each
round/variant has fresh compiler, SDK, object and executable caches for its cold
build, then one unchanged control and the same live navigation implementation
edit. Variant output-directory names have equal lengths. Installed dependencies
remain present; OS page cache is uncontrolled. These are two paired diagnostic
samples per scenario, **not** final five-cold/twenty-edit acceptance distributions.

| Scenario, two-sample medians | Baseline | Current | Saved |
| --- | ---: | ---: | ---: |
| Actual Make cold executable | 121.676 s | **105.035 s** | **16.641 s / 13.7%** |
| Actual Make navigation body edit | 115.059 s | **99.706 s** | **15.353 s / 13.3%** |
| Cold compiler command | 112.810 s | 96.200 s | 16.610 s |
| Edit compiler command | 108.895 s | 93.540 s | 15.355 s |
| Cold emission phase | 26.372 s | 9.994 s | 16.378 s |
| Edit emission phase | 26.505 s | 10.003 s | 16.502 s |
| Cold native stage | 8.272 s | 8.455 s | −0.183 s |
| Edit native stage | 5.835 s | 5.840 s | −0.006 s |
| Unchanged control | 4.029 s | 4.094 s | −0.065 s |

The individual cold pairs are **122.572 → 105.105** and
**120.781 → 104.965 s**. The edit pairs are **115.232 → 99.274** and
**114.887 → 100.138 s**. All four changed-build pairs improve. All unchanged
controls hit compiler/native caches and perform zero compiles/links; all remain
below the closed 5 s guard. No unchanged-build improvement is claimed.

Every cold run compiles all 17 units. Every edit changes one generated C unit,
compiles one native unit, reuses 16 and changes the executable. Cold/changed
builds retain the existing two-link receipt-admission protocol. Across both
rounds all 30 final C units match after mapping **only exact generated-output
filenames in `#line` directives**; no other normalization is applied. All
recorded compiler/tool/product inputs remain unchanged, the original product
is untouched, and the isolated source edit is restored. Output bytes for each
unchanged control match its cold seed. Metadata retention is covered by the
existing tests; this harness records content hashes, not inode/mtime equality.

Evidence: `~/.cache/btrc/perf/emission-builds-2026-09-22/results.json` and
`summary.json`, individual raw stdout/stderr and native reports. Drivers:
`build/plan-emission-builds.py` and `build/plan-emission-build-summary.py`.
The implementation, 245-test focused run and raw bootstrap fixed point are
recorded above. This supports retaining the cut, while M7's ≤55 s compiler
goal, the final ≥10× objectives, reference performance, aggregate memory and
full final-tree/required-host matrix remain open. Next is the existing M7
setjmp allocation work, beginning with measured null/leaf traversal and
empty/singleton copies rather than assuming full interning is necessary.

### M7 setjmp traversal and allocation diagnostic, September 22

One complete BTRSmith compiler miss with direct function-entry counters records
31,734,770 `Vector<SetjmpOrigin>` constructions. Of 20,591,611 expression
visits, 16,354,702 receive null. Literal/function-reference leaves account for
711,530 / 344,042 visits and each falls through fifteen absent child fields:
15,833,580 avoidable null visits. `copyOrigins` sees 3,653,551 empty, 909,036
singleton and 157 larger sources; `addOrigins` sees 10,478,465 empty, 2,764,243
singleton and 13,066 larger sources. There are 36,408 function-flow passes.

The counter compiler is a generated-C diagnostic derived from the qualified
3cf emission compiler, built at strict C11/O2. Its 96.758 s compiler-only wall
is instrumented and excludes native compilation/linking; it is not a new KPI.
All fifteen product C units match after mapping only exact generated-output
filenames in `#line`; recorded input hashes remain unchanged. Evidence is
`~/.cache/btrc/perf/setjmp-origin-2026-09-22/qualified/results.json`.
The initial diagnostic build used unqualified enum names and failed; its
source/logs are retained beside the corrected build.

The pre-change exception suite passes 136 tests without skips. The first
production cut skips child traversal for literals/function references and
stores only nonempty node-origin facts in both compilers. All consumers treat
absent facts as empty; write records retain their existing ordering and storage.
Returned mutable sets remain independent, and accumulated nonempty facts survive
empty revisits. No new shared mutable empty value or interning table is added.
The expanded exception suite passes **137 tests without skips** against the
fresh compiler. Strict C11/O2 compilation and a byte-identical self-host fixed
point pass; binary SHA-256 is
`de11dfaf474aa44ef92fe706970c6704b8df8bff3e6874e929ae205c952457ff`.
Bootstrap evidence lives in `setjmp-origin-2026-09-22/bootstrap/results.json`;
the test log is `build/plan-setjmp-origin-qualified.log`. Actual-product
measurement remains pending; do not infer a speedup from allocation counts alone.

The corresponding post-change counter run records **12,752,952 origin-vector
constructions**, down 18,981,818 (**59.8%**), and **521,122 null visits**, down
15,833,580 (**96.8%**). Expression visits fall to 4,758,031. Nonempty copy/add
counts, leaf counts, location visits, function-flow passes and loads match the
baseline exactly. The 3,148,238 allocations saved beyond skipped null visits
come from omitting empty node-origin storage. All fifteen C units remain
identical under the same narrow `#line` mapping and input hashes are unchanged.
Its instrumented compiler-only wall is 91.462 s; use the uninstrumented actual
Make comparison for elapsed-time claims. Evidence is
`setjmp-origin-2026-09-22/candidate-counts/results.json`.

### M7 setjmp cut: completed actual-Make comparison, September 22

Two alternating baseline/current rounds repeat the emission experiment's full
product, empty-cache cold dev build, unchanged control and live navigation edit.
The baseline is the qualified 3cf filename-reuse compiler; the candidate is the
qualified de11 setjmp compiler. Installed dependencies remain available and OS
page cache is uncontrolled. Both use dev O0/debug and eight native workers.
These are paired diagnostics, not final five-cold/twenty-edit distributions.

| Two-sample medians | Baseline | Candidate |
| --- | ---: | ---: |
| Actual Make cold executable | 104.836 s | **99.975 s** |
| Actual Make navigation edit | 99.341 s | **93.962 s** |
| Cold compiler wall | 95.880 s | 91.390 s |
| Edit compiler wall | 93.105 s | 87.830 s |
| Cold setjmp phase | 13.847 s | 10.252 s |
| Edit setjmp phase | 13.729 s | 10.208 s |
| Cold native stage | 8.326 s | 8.211 s |
| Edit native stage | 5.909 s | 5.806 s |
| Unchanged control | 4.002 s | 4.004 s |
| Cold compiler maximum RSS | 4,907,589,632 bytes | 4,514,693,120 bytes |
| Edit compiler maximum RSS | 4,911,398,912 bytes | 4,514,979,840 bytes |

Cold saves **4.861 s / 4.6%**, edit **5.379 s / 5.4%**. Both pairs improve:
cold 105.871 → 100.484 and 103.801 → 99.465 s; edit 100.097 → 93.775 and
98.585 → 94.150 s. `/usr/bin/time -l -p` measures each compiler process's
maximum resident set; the roughly 8% decrease is **not** aggregate process-tree
memory acceptance. There is no unchanged-build gain claim.

All four cold builds compile 17 units. All four edits compile one, reuse 16,
change exactly one generated unit and produce a changed executable. All four
controls hit the compiler cache and perform zero native compiles/links, below
5 s. All 30 final C units match after mapping only exact generated-output
filenames in `#line`. Compiler/tool/product hashes remain unchanged, the
original product is untouched, and isolated sources are restored. As in the
previous comparison, this harness verifies output hashes rather than inode/
mtime preservation. All cold/changed builds retain two-link receipt admission.

Evidence: `~/.cache/btrc/perf/setjmp-builds-2026-09-22/{results,summary}.json`
and raw logs/native reports. Drivers are `build/plan-setjmp-builds.py` and
`build/plan-setjmp-build-summary.py`. The allocation counter proof, 137-test
focused suite and fresh raw self-host fixed point are recorded above. Retain
the cut. Next is M7 generic/type and declaration lowering; full origin-set
interning remains conditional on residual cost evidence. M7's ≤55 s compiler
exit, final ≥10× build goals, reference performance, aggregate memory and
full final-tree/required-host qualification remain open.

### M7 type-owner profile, September 22

The fresh de11 compiler passes the generic/nullable/typedef baseline: **221 tests,
no skips**. One complete product miss with isolated generated-C wrappers records
5,053,758 generic-substitution calls, 933,211 AST allocations beneath that owner
and **2.535 s** of outermost recursive owner time. `lowerGeneric` accounts for
42,351 calls and **0.191 s**; `namedClass` for 294,767 calls and **0.623 s**.
`TypeShape.copyWithArguments` accounts for 772,712 calls / 1.728 s and
`TypeComposition.compose` for 641,951 / 1.523 s. These owners overlap and must
not be summed. All AST construction is 3,632,626 nodes / 6.858 s; each Node
is 768 bytes before separately allocated members. These totals are allocation
traffic, not live memory or a proposed speedup.

Substitution returns its original input 4,120,547 times. Of 668,984 compound
visits, 573,424 retain identical immediate child identities. That suggests a
reuse opportunity, but callers can mutate returned trees: the reference
`TypeSubstitution.resolve` explicitly copies cached parameter trees on read.
A shared mutable-result cache would violate that contract. Generic C-type
rendering alone is too small to justify a new caching subsystem.

The instrumented compiler-only wall is 103.623 s, excluding native build/link;
wrapper overhead and lost inlining affect it. All fifteen product C units match
after only exact generated-output line-filename mapping, and input hashes are
unchanged. Evidence: `~/.cache/btrc/perf/type-owner-2026-09-22/results.json`,
raw owner data, generated diagnostic source and strict-C11/O2 build log. This
narrows the next action to broader lowering, inference and AST/IR lifecycle
attribution before adopting a type cache. It does not change the measured
100.0 s cold / 94.0 s edit KPIs or close M7.

### M7 lowering-owner profile, September 22

A second bounded owner diagnostic narrows the unaccounted lowering work.
Outermost recursive owner times overlap across rows and must not be summed:

| Owner | Seconds | Calls | AST allocations beneath owner |
| --- | ---: | ---: | ---: |
| Generic-instance emission | 14.178 | 273 | 1,271,216 |
| Class emission | 17.032 | 1,289 | 876,501 |
| Method lowering | 14.889 | 9,052 | 795,960 |
| Body lowering | **28.363** | 18,897 | 2,109,925 |
| Expression lowering | 17.705 | 483,812 | 1,582,762 |
| Call ownership planning | 2.862 | 59,491 | 370,254 |
| Call-target resolution | 3.415 | 298,932 | 719,158 |
| Ordinary expression inference | 2.414 | 1,448,719 | 293,600 |
| Specialization inference | 4.477 | 4,713,663 | 486,567 |
| AST construction | 6.421 | 3,632,626 | 3,632,626 |
| AST destruction | 2.349 | 3,085,566 | 0 |
| IR-node construction | 1.557 | 3,023,266 | 0 |
| IR-node destruction | 0.431 | 827,678 | 0 |

IR nodes are 416 bytes before separate members. Body lowering creates
2,623,807 IR nodes. The constructor/destructor rows do not measure all ARC,
container or allocation costs; those operations also happen throughout owner
methods. They do rule out treating node construction alone as the entire
remaining compiler time. More call-target resolutions than ownership plans
suggest repeated work, but call-site attribution must establish which repeats
are redundant and which use different semantic state.

All fifteen product C units match after only exact generated-output line-file
mapping, and input hashes are unchanged. The instrumented compiler-only wall
is 94.042 s, not a KPI or a comparison against the previous instrumentation.
Evidence: `~/.cache/btrc/perf/lowering-owner-2026-09-22/results.json`, raw logs,
generated diagnostic C and strict-C11/O2 build. Together these profiles put the
next work in body/expression lowering, repeated call/inference work and their
state lifetime. Preserve mutable-result isolation and scope/flow validity;
neither type caching nor constructor allocation alone explains the whole gap.


### M7 scope-copy attribution, September 22

A targeted full-product diagnostic separates lexical type-map copying from
callable flow bookkeeping. Each row times the outermost recursion of that
owner; rows overlap and must not be summed.

| Owner | Seconds | Calls |
| --- | ---: | ---: |
| `TypeValidator.cloneTypes` | **6.561** | **91,506** |
| Callable flow snapshot | 0.396 | 551,700 |
| Callable flow restore | 0.162 | 442,009 |
| Callable flow evaluation | 0.515 | 233,267 |
| Callable ABI classification | 0.436 | 606,592 |
| Source-binding snapshot / restore | 0.033 / 0.044 | 70,133 / 89,268 |
| Borrowed-binding snapshot / restore | 0.009 / 0.008 | 51,072 / 51,410 |
| GPU-capacity snapshot / restore | 0.024 / 0.016 | 44,529 / 44,529 |
| Closure-escape checks | 2.901 | 118,656 |
| Call ownership planning | 2.903 | 59,491 |
| Call-target resolution | 3.475 | 298,932 |

All fifteen C units match after mapping only exact generated-output `#line`
filenames; input hashes remain unchanged. The 92.113 s instrumented wall is
not a new KPI. No allocation counters were enabled in this probe.
Evidence: `~/.cache/btrc/perf/flow-owner-2026-09-22/results.json`, raw profile,
strict-C11/O2 diagnostic build and compile logs. The baseline passed 945 tests
with no skips in 131.46 s using four workers and the qualified de11 compiler.
An earlier serial baseline was deliberately interrupted before restarting
with four workers; its partial log is not an additional passing suite.

The selected production cut replaces key-vector construction plus repeated
source lookups in `TypeValidator.cloneTypes` with `result.merge(source)`.
Both paths scan source occupied buckets in the same order and call `put` on a
fresh destination, preserving insertion order, value retention and independent
map mutation. This removes repeated copying machinery without sharing mutable
flow state. The reference analyzer uses parent-linked `Scope` objects, and its
block lowerer pushes scope dictionaries; this key-vector copy loop has no
direct counterpart there.
The candidate reaches a byte-identical self-hosting fixed point with strict
C11/O2, and the expanded suite passes **1,001 tests with zero skips** in
139.34 s. Bootstrap stages take 59.073 s (seed self-compile), 99.081 s (native
compile), and 58.910 s (candidate self-compile). These are qualification runs,
not paired bootstrap-speed evidence. Candidate binary SHA-256:
`43afc90301d875be153e7a725eb8fb0fc8b420f6d19ae76f9eac46c5c6183515`;
fixed-point C SHA-256:
`0f7a29cd38d7ece82907a92eea8c32036423debf2057c208488dc9697e395879`.
Evidence: `~/.cache/btrc/perf/scope-copy-2026-09-22/bootstrap/results.json`
and `build/plan-scope-copy-tests.log`.

Two alternating actual-Make baseline/candidate pairs now measure:

| Scenario | Previous compiler | Map-copy cut | Saving |
| --- | ---: | ---: | ---: |
| Cold dev executable | 100.803 s | **97.427 s** | **3.375 s / 3.35%** |
| Navigation body edit | 94.224 s | **92.095 s** | **2.129 s / 2.26%** |
| Cold compiler command | 91.865 s | 88.750 s | 3.115 s |
| Edit compiler command | 87.955 s | 85.885 s | 2.070 s |

Both pairs improve in each active scenario. Cold analysis decreases
19.846 → 18.343 s; lowering decreases 33.158 → 31.281 s. Compiler peak RSS
is effectively flat (cold 4,515,168,256 → 4,517,625,856 bytes); this is not
aggregate process-tree memory. Every cold run compiles 17 units, and every edit
compiles one, reuses sixteen, links and changes the executable. All thirty C-unit
comparisons match after only exact output-filename `#line` normalization.
Compiler/product inputs and restored source bytes pass their hash checks.
All four unchanged controls are below 5 s with no compilation or linking;
the candidate control median is 4.111 s.

Evidence: `~/.cache/btrc/perf/scope-copy-builds-2026-09-22/{results,summary}.json`,
raw Make/native reports, and `build/plan-scope-copy-builds.py` plus its summary
driver. This is a paired diagnostic comparison, not final 5-cold/20-edit or
required-host acceptance. M7's ≤55 s compiler command, the ≥10× end-to-end
goals, and the full final-tree matrix remain open.

Do not infer that every repeated call-target query can be reused: operand
lowering changes flow state. A no-explicit-argument shortcut is also invalid
because omitted defaults can contain callback values requiring validation.


Final formatting checks found four files needing only blank-line separators:
`frontend/NativeImports.btrc`, both portable native-digest facade/provider files,
and the native-digest test driver. After those spacing repairs, a fresh strict
C11/O2 bootstrap again reaches a raw byte-identical fixed point. Its executable
is **byte-identical to the measured 43afc903 compiler**, so the tested compiler
binary is unchanged. Comparing C across temporary build roots initially failed
on the sole absolute `CommonDigest.h` include path; exact normalization of that
one line, with identical header SHA-256, proves all remaining C bytes equal.
This normalization is separate from the raw within-root fixed-point check.
Evidence: `~/.cache/btrc/perf/scope-copy-final-2026-09-22/bootstrap/results.json`
and `format-equivalence.json` in its parent directory.

### September 22 quota checkpoint: unit-suite repair

The scope-copy optimization is saved in signed, pushed commit `9437a22`.
Implementation is paused at the user's request; resume with M7's remaining
analysis/lowering costs, then M8a and M11. No additional optimization or native
UI work belongs to this wrap-up.

The initial full unit run found 33 failures (7,606 passed, 49 skipped). The
repairs update the native macOS generated-C filename assertion, read FreeType's
binding from its GUI group manifest, refresh the strict-import inventory to
1,233 sources, and import `Library.IO` explicitly in three process fixtures
that call `fileno`. These preserve the existing behavior assertions.

The remaining failures were local verification setup: Apple C++ inherited a
Nix SDKROOT, and the temporary Python environment lacked the declared `build`
dependency. Clearing SDKROOT/DEVELOPER_DIR for the host run and installing the
declared packaging dependencies resolves them without compiler changes. All
296 tests across the seven affected modules pass with zero skips; all six
executions of the changed process fixtures pass through both compilers.
Generated-source checks, lint, Python/btrc formatting, 31 structure/naming
checks, and diff whitespace checks pass.

Evidence: `build/plan-wrap-retest.{log,json}`, `build/plan-wrap-corpus.log`,
and `build/plan-wrap-checks.json`. The full final-tree platform, GPU, extension
and C11 optimization matrix remains a separate release gate.
