# PLAN: compile performance

Goal: `make btrsmith-native` from ~10.5 minutes to under 3 minutes cold and
under a minute incremental, with the same two-compiler, bootstrap-verified
output the project has today. The measurements and the
reasoning behind the order are in
[`docs/design/compile-performance.md`](docs/design/compile-performance.md).

Ground rules for every milestone:

- Both compilers change together. Every step lands in `src/compiler/python`
  and `src/compiler/btrc` in the same commit, and BTRSmith's
  `application-frontend-check` (reference and self-hosted link plans
  identical, both binaries built) is part of the gate.
- "Byte-identical" below means each compiler against its own output before
  the change (the two compilers do not emit identical C today; the bootstrap
  fixed point is btrcc against btrcc). The check is `tools/perf` output of
  the corpus and BTRSmith before and after, `cmp`'d per compiler, with the
  three corpus programs that embed absolute include paths compared modulo
  that path.
- Gates that never regress: `make test`, `make bootstrap`, `make test-c11`,
  `make lint`, `make format-check`; in `../btrsmith`, `application-frontend-check`
  and `btrsmith-library-smoke` on both frontends.
- Every milestone records its own numbers in `docs/design/compile-performance.md`
  (the same `BTRCC_TIMING=1` phase table and `/usr/bin/env time -f "%e %M"`
  on BTRSmith), so the next milestone starts from measured, not remembered.
- No effort estimates. Order is by dependency and payoff only.

Baseline (2026-09-19, BTRSmith, x86_64 NixOS): btrcc 542 s / 5.2 GB, btrcpy
742 s / 2.5 GB, clang -O2 83 s, link 9 s. Phases: analyze 209 s, lower 248 s,
optimize 46 s, everything else 8 s.

---

## M0 — Measurement harness

Make the numbers reproducible before touching anything, so each later
milestone has a one-command before/after.

1. `make perf-btrsmith` (or `tools/perf/btrsmith.sh`): transpile BTRSmith
   with both compilers under `BTRCC_TIMING=1` and `/usr/bin/env time`,
   compile the emitted unit(s) with clang, print one table (phase seconds,
   peak RSS, C line count, function/struct/instance counts, clang seconds).
2. Add `BTRC_TIMING` to btrcpy with the same phase names as btrcc's
   `BtrccPhaseTimer`, so the two tables line up.
3. Add a `make perf-self` variant that compiles `BtrccMain.btrc` — the
   "same output size, 3× fewer classes" control that exposes superlinear
   behaviour.
4. Check the tables into `docs/design/compile-performance.md` as the baseline.

Exit: one command produces the table; the numbers above are reproduced.

---

## M1 — Remove the quadratic class walks

The single largest bucket (~40 % of btrcc, the `_is_subclass` storm in
btrcpy). Output must not change by a byte.

1. **Subclass index** in `Analyzed` (`src/compiler/btrc/analyzer/Models.btrc`)
   and its Python mirror (`analyzer/program.py` / `ir/lowering/ownership.py`):
   after declaration registration build `parent → children`,
   `class → ancestors`, `interface → implementors`, and the generic-instance
   equivalents. `isSubclass(sub, base)` becomes an ancestor-set lookup with no
   allocation; native (`objective-c`/`c`) classes keep their `nativeAncestors`
   path but through the same index.
2. **`CycleSemantics.appendRuntimeTypes` / `computeRuntimeTypeMayCycle`**
   (`analyzer/ownership/Cycles.btrc`, `ir/lowering/ownership.py`
   `_runtime_type_candidates` / `type_may_cycle`): iterate the descendants of
   the field's type from the index instead of `classTable.keys()`; keep the
   result order identical to today's (class-table insertion order) so the
   emitted visitor tables do not reorder.
3. **Memoise `runtimeTypeMayCycle` and `typeIsCyclable`** per runtime type
   name for the whole compile (today: 86,713 calls for 1,440 distinct
   answers).
4. Verify with the corpus and BTRSmith: `cmp` of the emitted C before and
   after on every corpus program and on BTRSmith, both frontends.

Exit: analyze + lower drop by ~200 s on BTRSmith; `perf-self` ratio to
BTRSmith falls from 8.5× toward the output-size ratio (~1×).

---

## M2 — Stop copying the environment per expression

Second bucket (~19 %). Output must not change by a byte.

1. `OwnershipOperandEnvironment` (`ir/lowering/ownership/Operands.btrc`) and
   `CallableBoundaryContext.variables()`: return a read-only view of the
   variable-type map; introduce a scope chain (`Scope { parent, bindings }`)
   where a nested block creates a child scope instead of `copyTypes`.
   Lookup walks outward. Same in `ir/lowering/session.py` `type_of` and
   `ownership.py`.
2. The analyzer's `ExpressionValidator.copyTypes` (`analyzer/Expressions.btrc`
   lines ~971–1074, `analyzer/expressions.py`) → the same scope chain.
3. `ExpressionLowerer.resolvedExpressionType` (762 k calls): memoise per
   `(node, scope)` where the scope object is stable; drop the memo when the
   scope is popped.
4. `cmp` gate as in M1.

Exit: `copyTypes` disappears from the top 40 of the profile; lower drops
by ~80 s.

---

## M3 — The remaining linear scans and allocation churn

Everything else in the profile that is a data-structure choice, not an
algorithm. Output must not change by a byte.

1. **Native declaration index**: `Analyzed.nativeGlobalReturnsOwned`,
   `nativeGlobalReadOnly`, `nativeClassLanguage` callers → `Map<string, …>`
   built once from `nativeDeclarations` (btrcpy: the matching lookups in
   `analyzer/program.py`).
2. **DCE membership**: `IROptimizer.containsName` and the `removed` vectors
   → `Map<string, bool>` (btrcpy `ir/optimizer.py`: sets).
3. **Setjmp analysis** (`ir/optimization/setjmp/*.btrc`,
   `ir/lowering/exceptions.py`): memoise `contains_setjmp` / pointer-flow
   per function; skip functions with no `try`, no callable boundary and no
   volatile-relevant locals up front.
4. **`Node` allocation** (`src/compiler/btrc/generated/ast/Node.btrc`,
   generated from the AST schema): allocate the 21 child vectors lazily
   (null until first push, readers treat null as empty). Regenerate the
   codec; the Python `Node` dataclasses use default factories only where a
   field is written.
5. **Pointer-keyed memo maps**: replace `AstIdentity.key(node)` (string of
   the address, 68 sites) with an identity-keyed `Map<Node, …>`; btrcpy
   already keys by object identity.
6. **btrcpy only**: stop round-tripping resolved types through JSON
   (`ir/lowering/generics.py` `_thaw` / `syntax/ast/codec.py`); keep frozen
   type trees as interned tuples with an identity cache. Also the tuple-type
   collection in `translation_unit.py` `_collect_ast_tuple_types` (4 M AST
   walks) → one walk with a memo per declaration.
7. Re-profile (gprof for btrcc, cProfile for btrcpy) and fix whatever is now
   above 3 %; stop when the top of the flat profile is lexing/parsing-shaped
   work or the ARC runtime on data the compiler genuinely has to touch.

Exit: btrcc ≤ 150 s and ≤ 3.5 GB on BTRSmith; btrcpy ≤ 250 s.

---

## M4 — Multiple translation units

The clang minutes become seconds, and per-unit recompilation becomes
possible. This milestone changes the emitted shape, so the proof is the
corpus and the full BTRSmith check suite on both frontends, not `cmp`.

1. **Origin tracking**: give `IRFunction`, `IRStructDef`, `IRGlobalDecl` and
   generic instances an `origin` (package name) populated in lowering from
   the source stamps `stampProgramSources` already puts on declarations.
   Runtime helpers and each generic instantiation get the origin of the
   first demander; the runtime prelude gets `btrc_runtime`.
2. **Emitter** (`ir/Emitter.btrc`, `ir/lowering/translation_unit.py`): emit
   one header (`<name>.h`: prelude, enums, typedefs, struct definitions,
   function pointer typedefs, prototypes for every non-`static` function,
   `extern` globals) and one `.c` per origin. Anything referenced from
   another unit loses `static`; anything referenced only within its unit
   keeps it. Deterministic unit order and content.
3. **Link plan schema 3**: the plan lists the emitted units (reusing the
   existing `units` / `generated-units` shape) so `tools/native_plan.py`
   compiles them in parallel (`-j` = cores) and links once. `--emit-link-plan`
   callers (btrc `Makefile`, BTRSmith `make/Config.mk`, the nix packages)
   move from "one generated C file" to "a generated directory".
4. **Single-file mode stays** (`--single-unit`) for the corpus runner, the
   bootstrap fixed point and anyone who wants one file; it must be byte
   identical to today.
5. Optional `-flto` switch in the native plan for release builds; measure
   whether it matters for BTRSmith's frame time before turning it on.

Exit: BTRSmith compiles as ~20 units; clang wall ≤ 20 s on this host;
`make bootstrap` still reaches its fixed point through single-unit mode;
every BTRSmith check passes on both frontends.

---

## M5 — Developer build mode and source mapping

1. **`#line` directives** in emitted C under `--debug`, now in both
   compilers: btrcc gains the `IRK_LINE_MARKER` statement that btrcpy already
   lowered, stamped by the emitter from the line map `sourceFileForLine` /
   `sourceLineFor` maintain; synthesized code resets to the generated file
   (each unit names itself). The directives stay opt-in: release output is
   unchanged byte for byte, and anyone diffing C by hand sees no noise.
   btrcc also gains `-o PATH` so the reset directives can name the file.
2. **`BUILD=dev`** in BTRSmith's `make/Config.mk`: `--debug` on the
   transpile and `btrc-native-plan --optimization 0 --debug-info` (`-g`) on
   every link; assert messages, sanitizer reports and gdb frames name
   `AlbumGrid.btrc:97`.
3. Check that the smokes pass under `BUILD=dev` (they exercise the same
   binaries, just unoptimised).

Exit: a dev rebuild of BTRSmith after M3+M4 is transpile + a few seconds of
clang; a crash under gdb shows btrc source locations.

---

## M6 — Incremental rebuilds

Re-measured after M1–M5, the front end (resolve, lex, parse, visibility)
is 3 s of btrcc's 58 s on BTRSmith and 13 s of btrcpy's 225 s, so a
per-module parse cache would buy at most 5 %; and no per-function analysis
or lowering cache is possible while instantiation, DCE, ownership and cycle
analysis are whole-program. The milestone therefore targets the part of an
edit-rebuild that *can* be skipped, the C compiler:

1. **Stable unit partition**: every `IRFunction` records the `.btrc`
   module it was lowered from (stamped per top-level declaration and per
   generic instantiation; synthesized helpers join the preceding run), and
   `--emit-units` packs consecutive same-module runs to the line target
   instead of cutting balanced slices. Editing one module changes that
   module's unit and leaves the other units byte-identical.
2. **Object cache**: `btrc-native-plan --object-cache DIR` keys each
   compile on compiler identity, flags and source text and copies a cached
   object instead of compiling; entries untouched for two weeks are pruned.
   BTRSmith links with `BTRC_OBJECT_CACHE=build/objects` by default.
3. The whole-program C cache (`--no-cache` in the Makefiles) stays off for
   builds: it can only hit when nothing in the closure changed, which make
   already skips. `--no-cache` remains for the goldens and CI's clean-tree
   runs.

Exit (measured, BTRSmith, btrcc): cold 101 s; one-line edit in one module
→ 1 of 15 units recompiled, 98 s, of which the transpile is ~90 s. The
rebuild is now the transpile; M7 works on that.

---

## M7 — Lowering and optimisation time

Parallel lowering is off the table as written: the ARC runtime takes one
global spinlock on every retain and release (`__btrc_arc_lock_mutation`),
so threads inside the compiler would serialise on it, and the analyzer's
lazily filled caches are not thread-safe. Per-kind AST nodes remain the
last, largest lever. The profile-driven single-thread work continues with
`BTRC_TIMING=1` sub-phase marks (`l-*` in lowering, `o-*` in
optimisation) so each cut is measured against the phase it targets.

Done so far (every step byte-identical on the corpus and BTRSmith):
cleanup-adapter index, `utf8Hex` through a builder, memoised setjmp body
scans, copy-on-write alias states and shared empty origin sets in the
setjmp flow, the boundary context's variable table shared instead of
snapshotted per query. btrcc on BTRSmith: 85 s → 76 s.

Where the time is now (btrcc, BTRSmith): lower 28 s (generic class
instances 12 s, declarations 15 s), setjmp safety planner 12 s, analyze
12 s, DCE 2.8 s, emit 2.8 s. The setjmp planner allocates ~35 M origin
vectors per compile (one per expression flow result); interning origin
sets or returning them by reference is the next cut, then per-kind nodes.

Exit: btrcc under 1 minute on BTRSmith cold; peak RSS under 2 GB.

---

## Order of operations, one line

M0 measure → M1 subclass index → M2 scope chains → M3 remaining scans and
allocation (re-profile until flat) → M4 multi-unit emission and parallel
clang → M5 `#line` and dev builds → M6 stable units and the object cache →
M7 profile-driven lowering work, slimmer nodes.

M1–M3 are byte-identical-output changes gated by `cmp`; M4 onwards change
the emitted shape and are gated by the corpus, bootstrap and the BTRSmith
suite. Each milestone ends with the table in
`docs/design/compile-performance.md` updated.
