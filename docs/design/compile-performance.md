# Compile performance: where the time goes and what to do about it

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

## Harness (M0)

`python3 -m tools.perf <program.btrc>` (Makefile: `perf-btrsmith`, `perf-self`)
runs both compilers under `BTRC_TIMING=1` in a fresh measuring process,
reports wall, CPU, peak RSS and the phase split, counts the emitted C, and
times the C compiler at each requested level with the link plan's flags.
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
the link plan (schema 3, `emitted-units`) counts them and `btrc-native-plan`
compiles them in parallel (`--jobs`, default: CPU count). Every unit carries
the prologue, helpers, types and prototypes; the primary defines globals and
kernels, the secondaries declare them; functions and globals lose internal
linkage so units can reference each other. The runtime's file-scope state is
declared through `BTRC_RT_STATE`, which the primary defines once and the
secondaries see as `extern` — the only runtime change the split needed.

| | units | C compile + link |
| --- | --- | --- |
| BTRSmith, btrcpy output | 16 secondaries | **8.6 s** (84.9 s with `--jobs 1`) |
| BTRSmith, btrcc output | 14 secondaries | **7.8 s** |

The whole corpus splits, links and runs with its goldens through both
compilers (the three GPU programs need the GPU runtime library the corpus
runner links separately), and the split BTRSmith passes its library smoke
from either compiler's units.

## Raw data

`/tmp/claude-1000/prof/`: `btrcc-timing.txt`, `gprof-flat.txt`,
`gprof-graph.txt`, `btrcpy-pstats.txt`, `clang-time-report.txt`.
