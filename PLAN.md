# PLAN: compile performance

Goal: `make btrsmith-native` from ~10.5 minutes to under 3 minutes cold and
under a minute incremental (M0–M7, done: 101 s cold, 98 s incremental), then
on to clang-class turnaround: btrcc under 10 s cold and an edit to one
module rebuilt in under 10 s (M8–M11), with the same two-compiler,
bootstrap-verified output the project has today. The measurements and the
reasoning are in [`docs/design/compile-performance.md`](docs/design/compile-performance.md).

This file is written to be picked up cold by another agent. Section 1 is
the state of the tree, section 2 the rules and the exact commands every
milestone uses, section 3 what landed (with file pointers), section 4 the
open milestones step by step, section 5 the order.

---

## 1. Handoff state (2026-09-20)

- **Everything is pushed.** btrc `main` = 0823f8c1 (M0–M7 and this plan;
  every gate green on that tree: `make test` 8608 passed, `make bootstrap`,
  `make test-c11` on gcc and clang -O0..-O3, `make lint`, `make format-check`).
  btrsmith `main` = 965db86: units, object cache and `BUILD=dev` in
  `make/Config.mk`, `make/Toolchain.mk`, `tools/LinkPlanParity.btrc`, and
  its btrc flake input repinned to 0823f8c1 (`nix build .` of btrsmith
  passed against that pin, 502 s including the store btrcc build).
- The user's own uncommitted edit to btrc `README.md` (a rewritten opening)
  is in the working tree. Leave it alone; never `git add -A`.
- Commit unsigned (`git -c commit.gpgsign=false commit`) unless the user's
  1Password session is available for signing; pushes need it too.
- Current numbers (BTRSmith, x86_64 NixOS, quiet machine):

  | | wall | phases |
  | --- | --- | --- |
  | btrcc | **76 s** (was 542 s) | lex+parse 2.7, analyze 12 (generics 3.1, validate 4.8, close-generics 1.9, realtime 2.1), lower 28 (l-generic-classes 12.3, l-declarations 14.8), optimize 16.5 (o-setjmp 12.0, o-dce 2.8), emit 2.8 |
  | btrcpy | **259 s** (was 742 s) | analyze 16, lower 140, optimize 57, emit 7 |
  | clang + link, 15 units | **~8 s** (was 85 s) | |
  | `make btrsmith-native` cold / edit one module | 101 s / 98 s | edit recompiles 1 of 15 units |

---

## 2. Ground rules and the commands

### Rules

- Both compilers change together: the reference compiler
  (`src/compiler/python`, "btrcpy") and the self-hosted one
  (`src/compiler/btrc`, "btrcc") land in the same commit, and BTRSmith's
  `application-frontend-check` (reference and self-hosted link plans
  identical, both binaries built) is part of the gate.
- "Byte-identical" means each compiler against **its own** output before the
  change. The two compilers do not emit identical C (957 of 960 corpus
  programs differ between them, by design); the bootstrap fixed point is
  btrcc against btrcc.
- Gates that never regress: `make test`, `make bootstrap`, `make test-c11`,
  `make lint`, `make format-check`; in `../btrsmith`,
  `application-frontend-check` and the library smoke on both frontends.
- Every milestone records its numbers in
  `docs/design/compile-performance.md` (the `BTRC_TIMING=1` phase line and
  wall time on BTRSmith) so the next milestone starts from measured, not
  remembered.
- No effort estimates. Order is by dependency and payoff only.

### Building the compilers

```sh
cd ~/Downloads/btrc
nix develop                     # dev shell: python, ruff, clang, gcc, pkg-config
make btrcc                      # bin/btrcc from dist/btrcc.c (btrcpy transpiles BtrccMain.btrc, cc -O2 compiles it; ~5 min)
export BTRC_HOME=$PWD/src       # both compilers find the stdlib here
python3 -m src.compiler.python.main --no-cache --strict-imports --target linux-x86_64 P.btrc -o P.c   # btrcpy
bin/btrcc --strict-imports --target linux-x86_64 P.btrc -o P.c                                          # btrcc
```

`make btrcc` runs `compiler-codegen-check` first (regenerate with
`make compiler-codegen-generate` after touching `src/runtime/c/*` or
`src/runtime/c/manifest.toml`; it rewrites
`src/compiler/python/runtime/generated.py` and
`src/compiler/btrc/generated/runtime/Catalog.btrc`, which are committed).

**Never run `make btrcc` while `make test` is running**: it replaces
`bin/btrcc` under the suite. **Never edit Python sources while `make test`
runs**: a mid-run import error produced 332 bogus failures once.
`make test` with `BTRC_TEST_BTRCC=$PWD/bin/btrcc` exported skips the
suite's own content-addressed btrcc build.

### Measuring

```sh
BTRC_TIMING=1 bin/btrcc ... 2>&1 >/dev/null | grep 'btrcc timing:'      # phase and sub-phase marks (a-*, l-*, o-*)
BTRC_TIMING=1 python3 -m src.compiler.python.main ... 2>&1 | grep 'btrcpy timing:'
python3 -m tools.perf ../btrsmith/src/BTRSmith.btrc --json build/perf/btrsmith.json   # both compilers + C compile table
nix develop ../btrsmith -c make NIX= perf-btrsmith                                    # same, from BTRSmith's dev shell (its packages)
```

BTRSmith needs its packages' headers: run btrcc/btrcpy on it inside
`nix develop ~/Downloads/btrsmith` (which puts pkg-config paths and the
native header reader in the environment), or export that shell's
`PKG_CONFIG_PATH`. Phase marks are added with `BtrccPhaseTimer.mark("name")`
(`src/compiler/btrc/frontend/Timing.btrc`) and `self._timed(profile, "name", start)`
in `src/compiler/python/application/pipeline.py`.

gprof works on btrcc: `cc -std=c11 -O2 -pg -w dist/btrcc.c -o btrcc-pg -lm -lpthread`,
run it on BTRSmith, `gprof -b -p btrcc-pg gmon.out` (flat) and `-q` (graph).
Self time under `-pg` is dominated by the ARC runtime; read the **call
counts** and the call graph's inclusive column, not the self column. For
btrcpy use `python3 -m cProfile -o out.prof -m src.compiler.python.main ...`.

### Byte-identity gate

Emit the whole corpus with a compiler into a directory, once before and
once after, and `cmp` every file:

```sh
python3 - <<'EOF' > programs.txt
import sys; sys.path.insert(0, '.')
from src.tests.corpus_files import language_test_files
for p in language_test_files('src/tests'): print(p if p.startswith('src/tests/') else 'src/tests/' + p)
EOF
mkdir -p out/after
while read f; do rel=${f#src/tests/}; dst=out/after/${rel%.btrc}.c; mkdir -p "$(dirname "$dst")"
  bin/btrcc --strict-imports --target linux-x86_64 "$f" -o "$dst" 2>/dev/null || echo "FAIL $f"; done < programs.txt
for f in $(cd out/before && find . -name '*.c'); do cmp -s out/before/$f out/after/$f || echo "DIFF $f"; done
```

Three programs embed absolute include paths
(`basics/InteropCEnumBaseType`, `basics/InteropUnionBaseType`,
`imports/ImportCSourceFile`): compare them modulo the checkout path. For
BTRSmith, `cmp` the single-unit output (no `--emit-units`). Milestones
that change the emitted shape (M4–M6, M11) are gated by the corpus
goldens (`make test`) instead.

### Frozen compiler boundaries

`src/tests/fixtures/compiler_boundaries/manifest.toml` freezes IR dumps,
generated C and the runtime catalog. After an intentional change:

1. `python3 -m tools.compiler_codegen.main boundary-capture` writes
   candidates to `build/verification/compiler-boundaries/candidate/records/<id>.bin`.
2. For every record whose capability is `portable` and whose candidate
   sha256 differs from its `accepted_sha256` (or `baseline_sha256`), copy
   the candidate to `artifacts/accepted/<id>.bin` and set
   `accepted_path`, `accepted_sha256`, `reason`, `regressions` on the
   record by editing the TOML (no tool does this). **Never** accept records
   of `observed` capabilities (`*.behavior-gcc`, `*.behavior-clang`): they
   are recorded on macOS and skipped on Linux.
3. `python3 -m tools.compiler_codegen.main boundary-check`.
4. A new runtime helper needs a new `helper.<name>` channel on
   `shared.runtime-metadata` and a record whose baseline file contains
   `null`; `src/tests/python/test_boundary_manifest.py` hardcodes the
   record count (309).

### BTRSmith

```sh
cd ~/Downloads/btrsmith && nix develop            # its dev shell has the pinned store btrcc/btrcpy
make btrsmith-native                              # reference frontend, units, object cache (build/objects)
make BTRC_FRONTEND=selfhost btrsmith-native       # btrcc
make BUILD=dev btrsmith-native                    # --debug (#line into .btrc), -O0 -g
make macos-btrsmith-library-smoke                 # runs on Linux despite the name; prints PASS lines
make -f make/Product.mk application-frontend-check
```

To use a locally built compiler instead of the pinned one, pass
`BTRCC=$HOME/Downloads/btrc/bin/btrcc BTRC=$HOME/Downloads/btrc/bin/btrcc`
(selfhost) or a small wrapper that runs
`python3 -m src.compiler.python.main` with `PYTHONPATH=$HOME/Downloads/btrc`
(reference), plus `NATIVE_PLAN="python3 -m tools.native_plan"` from the btrc
checkout, with `BTRC_HOME=$HOME/Downloads/btrc/src` exported; keep the
BTRSmith dev shell's `PKG_CONFIG_PATH`. Knobs: `BTRC_UNITS=` (one unit),
`BTRC_UNIT_LINES` (unit size, default 40000), `BTRC_OBJECT_CACHE=`
(disable), `BUILD=dev|release`.

---

## 3. What landed (M0–M7)

### M0 — Measurement harness (b27a1acb)

`tools/perf.py` (`make perf-btrsmith`, `make perf-self`), `BTRC_TIMING=1`
phase timing in both compilers with the same phase names, baseline tables
in the design doc. Test: `src/tests/python/test_perf_tool.py`.

### M1–M3 — Algorithmic cuts (154093de, b1c9816a, 4ae64cda)

- Subclass/ancestor index in `Analyzed`
  (`src/compiler/btrc/analyzer/Models.btrc`: `ancestorsOf`, `subclassesOf`,
  `refreshInheritanceIndex`); `CycleSemantics` iterates `subclassesOf`.
  Python mirror in `ir/lowering/ownership.py` (`_ancestors`, `_subclasses_of`).
- Environments shared instead of copied per expression
  (`ir/lowering/ownership/Operands.btrc` `variables()`/`typeArguments()`;
  `generics.py` `TypeSubstitution` caches decoded tables and hands out
  copies on read — a9b4d215).
- Native-declaration indexes, DCE membership sets, setjmp fixed point
  driven by "consulted" summaries (`ir/optimization/setjmp/Analysis.btrc`,
  `exceptions.py`), iterative IR walker in `ir/nodes.py`.
- The compiler `keep`s its analysis and IR graphs at exit
  (`pipeline/Pipeline.btrc`, `analyzer/Analyzer.btrc`): releasing them
  cost 200 s of ARC reverse-edge proofs.

### M4 — Translation units (62d69404, reworked in 598bc161)

`--emit-units PREFIX` in both compilers writes `PREFIX.unit-<k>.c`; the
link plan is schema 3 with `emitted-units`; `btrc-native-plan --jobs`
compiles units in parallel. Every unit carries the prologue, types,
helpers and prototypes; functions and globals lose `static`; the primary
unit defines globals and kernels, secondaries declare them. Runtime
file-scope state stays written as plain `static` in `src/runtime/c/*.c`
(the stdlib archive parses that text to derive its `extern` header); the
unit emitters reshape it per unit through
`src/compiler/python/backend/runtime_state.py` and
`src/compiler/btrc/ir/RuntimeState.btrc` (primary drops `static`, others
declare `extern`). Emitters: `c_emitter.py` `emit_units`/`_emit_unit`,
`ir/Emitter.btrc` `emitUnits`/`emitUnit`. Tests:
`src/tests/python/test_emitted_units.py`, `test_native_plan_builder.py`.

### M5 — Source mapping and dev builds (d7f24d73, f7000dcd)

btrcc `--debug` lowers `IRK_LINE_MARKER` statements
(`ir/lowering/Statements.btrc` `lowerStmtInto`) and the emitter stamps
`#line` before every content line of a function body
(`ir/Emitter.btrc` `emitLineDirective`, `fixGeneratedLineResets`);
`-o PATH` (options may follow the input); `btrc-native-plan --debug-info`;
BTRSmith `BUILD=dev`. Tests: `src/tests/btrc/test_cli_arguments.py`,
`test_emitted_units.py::test_debug_split_units_map_lines_and_run`.

### M6 — Incremental rebuilds (1d285e55)

Every lowered function records its `.btrc` module (`IRFunction.sourceFile`,
`IRFunctionDef.source_file`, stamped by
`LoweringContext.stampFunctionSources` per top-level declaration and per
generic instantiation, and by `TranslationUnit._stamping_sources`);
`--emit-units` packs consecutive same-module runs to the line target
(`Emitter.unitStarts`, `CEmitter._unit_starts`), so an edit changes one
unit. `btrc-native-plan --object-cache DIR` (`tools/native_plan.py`
`_ObjectCache`) keys objects on compiler identity, flags and source bytes.
Per-module parse caching was dropped for cause: the front end is 3 s of 76.

Open items, small, to ride along with M7/M8:

- **Trim the per-unit prologue.** Every unit carries the whole program's
  struct definitions, prototypes and helpers (~50k of a unit's ~95k
  lines). Emit per unit only what its functions reference (walk the unit's
  bodies for names); clang time per unit halves and the object cache hits
  more often.
- **No-op rebuilds.** `make` re-runs the transpile whenever a source is
  touched (94 s for "no change"). Key the generated C and plan on the
  closure's content hash (btrcpy's output cache in
  `application/compiler.py` already computes it) and make BTRSmith's rules
  depend on the hash rather than mtimes.
- **The reference compiler.** btrcpy is at 259 s and nothing targets it;
  profile `optimize` (its setjmp planner) and lowering with cProfile after
  each btrcc cut and port the same shape.

### M7 — Profile-driven cuts (9f7d7328, 5d9562be; in progress)

Parallel lowering is off the table as the plan first stated it: every ARC
retain and release takes the global spinlock `__btrc_arc_lock_mutation`
(`src/runtime/c/cycles.c`), so threads inside btrcc would serialise on it,
and `Analyzed`'s lazily filled caches are not thread-safe. M9 and M10 are
the way around both.

Landed, all byte-identical: cleanup-adapter name index
(`ir/optimization/Cleanup.btrc`), `TypeIdentity.utf8Hex` through a
`StringBuilder` (`syntax/Identity.btrc`), memoised setjmp body scans
(`setjmp/Safety.btrc` `bodyContainsSetjmp`), copy-on-write alias states
and one shared empty origin set (`setjmp/Analysis.btrc` `shareSlot`,
`ownOrigins`, `noOrigins`), `CallableBoundaryContext.variables()` returns
the live table (`ir/lowering/Callables.btrc`). Sub-phase marks `l-*` and
`o-*` in `Lowerer.btrc`, `Optimizer.btrc`, `Pipeline.btrc`.

---

## 4. Open milestones

### M7 (remainder) — finish the profile-driven cuts

Target: btrcc under 55 s on BTRSmith, byte-identical. Measure each step
with `BTRC_TIMING=1` on BTRSmith and the corpus `cmp`.

1. **Intern origin sets in the setjmp flow** (`o-setjmp` 12 s).
   `SetjmpPointerFlowResult` (`src/compiler/btrc/ir/optimization/setjmp/Analysis.btrc`)
   allocates ~35 M `Vector<SetjmpOrigin>` per compile: `flowExpression`
   returns a fresh vector per expression, `copyOrigins` is called 7.6 M
   times, `addOrigins` 16 M. Make an origin set an immutable value:
   a canonical sorted `Vector<SetjmpOrigin>` interned in a per-function
   table keyed by the joined `storage.identity/depth/sourceExposed`
   triples, so `copyOrigins` is a reference copy, `addOrigins` builds the
   union once and interns it, and `flowSameOrigins` is a pointer compare.
   `SetjmpAliasSlot.origins` then never needs copying (drop `owned`).
   Mirror in `src/compiler/python/ir/lowering/exceptions.py` (its sets are
   `frozenset`s already; the cost there is the per-node dict churn —
   cProfile it first). Gate: corpus `cmp`, BTRSmith `cmp`, `make test`.
2. **Generic instantiation allocation** (`l-generic-classes` 12 s).
   `SemanticTypeSystem.resolveGenericType` and
   `TypeShape.copyWithArguments` (`src/compiler/btrc/analyzer/Types.btrc`,
   `syntax/Identity.btrc`) create ~1.6 M type nodes per compile;
   `SemanticTypeSystem.namedClass` another 1.15 M. Memoise substitution
   per (type identity, type-map identity) within one instantiation
   (`DeclarationLowerer.emitGenericInstance`, `ir/lowering/Declarations.btrc`),
   return the input when no parameter is reached (the M1 shape in
   `resolveTypedefType`), and audit `namedClass` callers for mutation
   before sharing its result.
3. **Declaration lowering** (`l-declarations` 15 s). Re-profile after 1–2.
   Inclusive-time candidates from the last graph:
   `CallTargetResolver.resolve` (300k calls, 4.7 s), `resolveField`
   (219k), `CallableValueSemantics.expressionAbi` (620k, 4.8 s),
   `CallableFlowState.applyEvaluation` (240k, 4.8 s),
   `CycleSemantics.reaches` (2.2k calls at 1.8 ms each — memoise per
   (type, target) or precompute reachability once per class graph).
4. Port each cut to btrcpy where the same shape exists; record the numbers.

### M8 — Per-kind AST and IR nodes

Target: btrcc under 30 s on BTRSmith, peak RSS under 1.5 GB, node
allocations down at least 3× (gprof call counts of `Node_init`,
`IRNode_init`, `__btrc_cycle_grow_slots`). Byte-identical at every commit.

Why: `Node` (`src/compiler/btrc/generated/ast/Node.btrc`, generated from
the AST schema under `tools/compiler_codegen/`) is one 103-field struct
whose constructor allocates several empty vectors and maps; 3.8 M are
built per BTRSmith compile, plus 2.9 M `IRNode`s of the same shape
(`ir/Model.btrc`). Most of the runtime's allocation, reverse-edge and
deferred-release work in the profile is those fields.

1. **Schema.** Extend the AST schema (`tools/compiler_codegen/ast.py`,
   `asdl.py`; Python side `src/compiler/python/syntax/ast/generated.py`)
   with the field set each kind uses; generate a base node (`kind`, `line`,
   `col`, identity) and one struct per kind. Child vectors are created on
   first use; a kind that has no `args` has no `args` field.
2. **Accessors.** Generate typed accessors so passes keep compiling during
   the migration: `node.args()` returns the kind's vector or one shared
   empty vector; `node.child(FIELD)` for the generic walkers. Replace the
   hand-written child enumerations (`containsSetjmp`,
   `globalInitializerHasEffects`, `collectGlobalRefs`, the `_TRAVERSAL_FIELDS`
   table in `ir/nodes.py`) with a generated per-kind child table.
3. **Migrate pass by pass**, both compilers, `cmp` after each pass: lexer
   and parser, analyzer, lowering, optimisation, emitter. The boundary
   fixtures (`surface.*`, `managed.*` IR dumps) change when the IR dump
   format changes — re-accept them once, deliberately.
4. **IR nodes** the same way once the AST is done.
5. Re-measure RSS and allocation counts; update the design doc.

### M11 — Separate compilation (the dev loop)

Target: editing one BTRSmith module and rebuilding takes under 10 s
(summary reads, one module lowered, one unit compiled, link); a cold dev
build is no slower than today; release output is unchanged. Gate: corpus
stdout goldens in both modes, bootstrap in release mode, BTRSmith suite in
both modes.

Why: after M6 an edit costs a whole transpile because analysis, generic
instantiation, DCE and cycle analysis are whole-program. clang is fast on
an edit because it never recompiles the world. The stdlib archive
(`--build-stdlib` / `--stdlib`, `src/compiler/python/application/pipeline.py`
`StdlibArchiveAdapter`, `artifacts/archive.py`, `artifacts/stdlib.py`:
one C unit plus a header with `extern` shared state, consumed by later
compiles) is already a working instance of the design for one module.

1. **Module interface summaries.** For each module (a `.btrc` file with
   its `btrc.toml` package context) the front end writes a summary
   (`<module>.btrci`, JSON, keyed by the module's content hash and the
   summary hashes of its imports): exported declarations with fully
   resolved types, class layouts and hierarchies, method ABIs and call
   contracts, native-import contracts, and the ownership facts other
   modules need (which runtime types may cycle, which methods release or
   capture, realtime effects). Analysis of a module consumes summaries,
   never the sources of its imports. Start from what `Analyzed`
   (`analyzer/Models.btrc`, `analyzer/program.py`) already holds per
   declaration; the resolver's `FeDependencyGraph` /
   `SourceDependencyGraph` gives the import order.
2. **Program facts as a link-time pass.** The facts that are truly
   whole-program — runtime-type may-cycle (`CycleSemantics`), the set of
   reachable runtime helpers (`RuntimeReferenceCollector`), the generic
   instantiation set, DCE roots — are computed by merging summaries
   (cheap: no bodies) into a program summary that every per-module lowering
   reads. Cycle analysis over summaries needs the field types of every
   class, which the summaries carry.
3. **One C unit per module.** Each module lowers to its own C file against
   a generated program header (types, prototypes, runtime helper
   prototypes, shared runtime state as `runtime_state.py` /
   `RuntimeState.btrc` already shape it); runtime helpers are defined once
   in a runtime unit. The symbol ABI is today's deterministic mangling
   (`TypeIdentity`); nothing in a module's C may depend on another
   module's bodies. The unit partition of M6 becomes "one module, one
   unit" in this mode.
4. **Generics.** An instantiation is lowered in the module that first
   needs it and recorded in the program summary; emit it with weak linkage
   (`__attribute__((weak))` on ELF and Mach-O, `__declspec(selectany)` on
   MSVC) so another module may emit the same one and the linker folds
   them. If weak symbols cause any drift, use the deterministic
   alternative: the program summary assigns each instantiation to exactly
   one owning module, and the driver re-lowers that module when the set
   changes.
5. **Whole-program passes in dev mode.** DCE becomes per-module plus a
   program-level unreachable list from the summaries (less aggressive than
   today; acceptable for dev builds). Release builds keep the whole-program
   path until the corpus shows separate-mode output behaves identically
   under the stdout goldens; then decide whether release moves too.
6. **Build driver.** `btrcc --module PATH --summary-dir DIR` (and the
   same in btrcpy) analyses one module against summaries and emits its
   unit and updated summary; `btrc-build` (a Python tool next to
   `tools/native_plan.py`, also callable from make) walks the dependency
   graph, re-analyses and re-lowers only modules whose sources or imported
   summaries changed, then links through the M6 object cache. BTRSmith's
   `BUILD=dev` uses it; `application-frontend-check` runs in both modes.

### M9 — Arena allocation for compiler-lifetime data

Target: btrcc 10–15 s on BTRSmith cold; `__btrc_arc_lock_mutation`,
`__btrc_reverse_add` and `__btrc_cycle_grow_slots` gone from the top
twenty of the compiler's profile; corpus byte-identical (the generated
code's shape does not change).

Why: everything the compiler builds lives until the process exits; M1–M3
already `keep` the big graphs to skip a 200 s teardown. Refcounting,
reverse edges and the mutation lock buy nothing for that data, and the
lock is what forbids threads (M10).

1. **Language feature.** Add region allocation to btrc: an `Arena` value
   and allocation of a class instance in an arena, whose objects are
   neither refcounted nor cycle-collected and are released with the arena.
   Analyzer rules (both analyzers, `analyzer/validation/*.btrc` and
   `python/analyzer/*.py`): arena objects may reference each other and
   ordinary ARC objects; an ARC-owned field may reference an arena object
   only while the arena is alive. The first version allows only
   process-lifetime arenas (never released), which makes that rule
   trivially true and is all the compiler needs. Spec it in
   `src/language/`, add corpus programs and diagnostics tests.
2. **Runtime.** `src/runtime/c/cycles.c`: arena allocation is a bump
   allocator; `__btrc_arc_retain`/`release`/`retain_edge`/`release_edge`
   recognise an arena object from its header and return without taking
   the lock or touching reverse edges. Generated code does not change.
3. **Compiler adoption.** Tokens, AST, analysis tables and IR go into one
   compiler arena (the pipeline creates it; `keep` becomes unnecessary);
   the emitter's string building stays ARC.
4. **Gates.** `-fsanitize=address,undefined` builds of btrcc over the
   corpus and BTRSmith; the runtime boundary fixtures re-accepted once;
   `make test`, `bootstrap`, `test-c11`.

### M10 — Parallel analysis and lowering

Target: btrcc 3–5 s on BTRSmith on this machine (16 cores); parity with
clang -O0 per line of input; output byte-identical to the sequential run.

Possible once M9 removes the lock from the compiler's hot path and M8
makes per-thread node graphs cheap.

1. **Freeze the shared tables.** After analysis every lazily filled cache
   in `Analyzed` (inheritance index, native indexes, `runtimeTypeMayCycle`
   memo, typedef resolution memo, expression-type memos) is either filled
   eagerly or made thread-local; `Analyzed.freeze()` asserts no further
   mutation (debug builds trap on a write after freeze).
2. **Per-function work items.** `FunctionLowerer.lowerBody`, per-function
   validation (`DeclarationValidator.validateCallableBody`) and the setjmp
   flow run over a thread pool (`spawn`/`Thread<T>`) with a per-thread
   arena and a temporary-name state seeded per function so names do not
   depend on scheduling; results are appended in original order.
   `BTRC_JOBS=1` keeps the sequential path.
3. **Determinism gate.** Two runs `cmp` equal on the corpus and BTRSmith;
   `-fsanitize=thread` build of btrcc over the corpus; the same shape in
   btrcpy with `multiprocessing` only if profiling shows it pays (pickling
   the analysed program may cost more than it saves).

---

## 6. C compatibility track (independent of the performance milestones)

### Why, and how much

btrc does not need C source inside `.btrc` files to use C: `#include "x.h"`
pulls native declarations through the header reader, a `.c` file compiles
and links through the package link plan (`src/tests/imports/ImportCSourceFile.btrc`),
and every Linux provider (SDL, ALSA, FreeType, WebGPU) is imported that way.
So the gaps below never block building software. They matter for two
reasons: the README's "C, but better" reads as "C is a subset", and the
first C habits a newcomer types (`int main(void)`, a braceless `if`,
`int a, b;`) fail today; and C programmers write btrc with the same habits.
The goal of this track is therefore **ordinary C11 parses as btrc, and the
things btrc refuses are refused on purpose and documented**, not "rename
`.c` to `.btrc` and it compiles".

### What the probe found (2026-09-20, btrcpy, 100 one-construct programs)

Method: one tiny C11 program per construct, compiled with
`python3 -m src.compiler.python.main --no-cache --strict-imports --target linux-x86_64 P.btrc -o P.c`,
then `cc -std=c11 P.c && ./a.out`; a construct "passes" when the binary
exits 0. Regenerate the battery from the table below when adding to it;
each program should end up as a corpus case (see C5).

Passes today: pointers, pointer-to-pointer, pointer arithmetic (`p = p + 2`),
arrays and decay, casts including `void*`, `static` functions and locals,
`extern`, globals with initialisers, enums with values, function-like
macros, `_Generic`, `do`/`while`, `switch` with fallthrough, nested struct
initialisers, literal suffixes (`LL`, `UL`, `f`), hex, octal, escapes,
`volatile`, `printf`, prototypes with named parameters,
`int main(int argc, char** argv)`, assignment in a condition, `if (i)` on an int.

| # | Construct | Symptom today | Class |
| --- | --- | --- | --- |
| 1 | `int f(void)`; unnamed prototype parameters `int f(int);` | "Expected parameter name" | parser gap |
| 2 | braceless bodies after `if`/`else`/`for`/`while` | "Expected LBRACE" | parser gap |
| 3 | multiple declarators `int a = 1, b = 2;`, `int x, y;` in structs | "Expected SEMICOLON, got COMMA" | parser gap |
| 4 | `char s[] = "abc"`, `char s[4] = "abc"` | "requires an array initializer" | parser gap |
| 5 | adjacent string literals `"a" "b"` | parse error | lexer gap |
| 6 | empty statement `;` (`for (...);`) | "Expected LBRACE" | parser gap |
| 7 | function-pointer declarators `int (*f)(int)`, `typedef int (*Op)(int,int)`, arrays of them, as parameters | parse error; btrc spells these `CFunction<...>` | parser gap (sugar) |
| 8 | `typedef struct { } T;`, `typedef struct P { } P;`, anonymous struct/union members | "Expected struct name" / "Expected typedef alias" | parser gap |
| 9 | `union U { };` as a declaration | only `union IDENT` as an interop base type (grammar line 30) | parser gap with an ownership rule |
| 10 | designated initialisers `{.b = 2}`, `{[2] = 7}`; compound literals `(struct S){5}` | "Unexpected token" | parser + IR gap |
| 11 | `goto` / labels | no syntax by design (grammar line 27) | parser + lowering rule |
| 12 | bitfields `unsigned a:3` | "Expected SEMICOLON, got COLON" | struct model gap |
| 13 | flexible array member `int d[];` | rejected | struct model gap |
| 14 | variadic definitions `int f(int n, ...)`, `va_list` | "Expected parameter name, got DOT" | parser + intrinsics |
| 15 | `inline`, `restrict`, `register`, `auto`, `_Noreturn`, `_Thread_local`, `_Alignas`, `_Static_assert` | "Expected name" | keyword pass-through |
| 16 | `long double` literal `1.5L`, `wchar_t`, `L'x'` | "Invalid numeric literal" / parse error | lexer + type gap |
| 17 | multi-dimensional arrays `int m[2][3]` | explicit diagnostic: needs an AST/IR representation per dimension | known gap |
| 18 | `#if`/`#else`/`#ifndef`/`#if 0` | directives pass through; the analyzer sees every branch ("Duplicate definition", "unsupported directive") | preprocessor gap |
| 19 | comma operator `(1, 2)` | parsed as a tuple literal | **conflict**: tuples |
| 20 | identifiers named `in`, `string`, `keep`, `self`, `class`, `interface`, `spawn`, `new`, `var`, `null`, `true`, `false` | keywords | **conflict**: reserved words |
| 21 | `strlen(s) == 2` (`size_t` vs `int`) | "mixes ABI-dependent integer type" | **on purpose**: strict integer mixing |
| 22 | `_Bool b = 1`; `return a();` in a void function | type errors | **on purpose** |
| 23 | VLAs `int v[n]` | parse error | **won't do**: conflicts with the array-size model |
| 24 | `_Atomic`, `_Complex` | rejected | **deferred**: need type-system entries |

### C1 — The ergonomic set (rows 1–7)

Pure grammar additions with a direct lowering and no semantic cost; this
is what makes the README claim true at first contact.

1. `(void)` as an empty parameter list; unnamed parameters in prototypes
   and in function-pointer types.
2. A single statement as the body of `if`, `else`, `for`, `while`; lower
   with braces. `;` as an empty statement.
3. Multiple declarators per declaration, locals and struct fields,
   expanded in the parser into separate declarations (initialisers stay
   attached to their own declarator).
4. String literal as the initialiser of a `char` array, sized or not;
   adjacent string literal concatenation in the lexer.
5. C function-pointer declarator syntax parsed into the existing
   `CFunction` type (`src/language/grammar.ebnf` `function_pointer` rules,
   `TypeIdentity`), including `typedef` and arrays of pointers.

Files: `src/language/grammar.ebnf` (the spec; change it first),
`src/compiler/python/parser/parser.py`, `src/compiler/btrc/parser/Parser.btrc`,
`src/compiler/python/lexer/`, `src/compiler/btrc/lexer/`. Any new AST node
goes through `src/language/ast.asdl` and `make compiler-codegen-generate`.

### C2 — Declarations (rows 8–10, 12–13)

1. Anonymous struct and union members; `typedef struct { } T` and
   `typedef struct P { } P` (synthesize the tag; both analyzers key structs
   by name).
2. `union` declarations for plain C members. Rule: a union member may not
   be ARC-managed (class, `string`, collection) — the runtime cannot know
   which member is live; the analyzer rejects it with a diagnostic, in
   both compilers.
3. Designated initialisers and compound literals: an initialiser node with
   field/index designators, lowered to the same C.
4. Bitfields: a field width on the struct model (`ast.asdl` field decl,
   layout in `analyzer/Storage`), lowered verbatim; native typed bindings
   keep rejecting bitfield structs (they cannot be addressed).
5. Flexible array members: last field only, `sizeof` excluded, no
   by-value copies of the struct.

### C3 — Control flow and calls (rows 11, 14–16)

1. `goto` and labels. btrc scopes carry ARC releases and cleanup slots, so
   the lowering must reject a jump that enters a scope past an owned
   variable's initialiser or leaves a `try` frame; jumps within one scope
   or outward past releases (emitting the releases) are allowed. Both
   compilers, same diagnostics.
2. Variadic definitions: `...` as the last parameter, `va_list`,
   `va_start`, `va_arg`, `va_end` as opaque intrinsics in
   `src/language/intrinsic_effects.toml`; realtime analysis treats them
   as non-allocating.
3. Keyword pass-through: `inline`, `restrict`, `register`, `auto`,
   `_Noreturn`, `_Thread_local`, `_Alignas`, `_Static_assert` parsed as
   declaration attributes and emitted verbatim (`_Thread_local` globals
   need the unit emitters' `extern` shaping from M4).
4. `long double` literals with `L`, `wchar_t` and `L'x'`/`L"x"` literals.

### C4 — Preprocessor conditionals (row 18)

Directives are passed through to C today, so the analyzer sees every
branch. Evaluate `#if`/`#ifdef`/`#ifndef`/`#elif`/`#else`/`#endif` in the
front end over object-like `#define`s in the closure plus the target's
predefined macros (`__linux__`, `__APPLE__`, `__x86_64__`, from
`src/language/hosted_abi.toml`'s target table), drop the dead branches
before parsing, and keep emitting the live branch's directives so the C
compiler agrees. `#if` on a macro the front end cannot evaluate (a system
header's) stays an error with a diagnostic naming the macro.

### C5 — Spec, corpus and the documented refusals (rows 19–24)

1. A `src/tests/c11/` corpus directory: one program per row of the table,
   each printing `PASS: <construct>` with a golden
   (`src/tests/generate_expected.py`), run through both compilers by the
   existing runner; rows 19–24 as diagnostics tests asserting the exact
   message.
2. A section in `src/language/grammar.ebnf`'s preamble and in
   `docs/known-language-gaps.md`: "C that btrc rejects on purpose" —
   the comma operator outside `for` headers (tuple literals win; support
   it only in `for` init/update), the reserved-word list, strict integer
   mixing, int-to-bool assignment, returning a void expression, VLAs,
   `_Atomic` and `_Complex` (deferred), with the reason for each.
3. README wording: "C's syntax and semantics where they are safe, the rest
   reachable through `#include`", linking to that section.

### Order and gates

C1 → C5 (corpus and docs first, so every later step has its goldens) →
C4 → C2 → C3. The track is independent of M7–M11 except that **C1–C3
add AST nodes and M8 changes the node schema**: land the C-track parser
work either before M8 starts or after it lands, never interleaved. Every
step: both compilers in one commit, `make test`, `make bootstrap`,
`make test-c11`, and the boundary fixtures for `surface.python.tokens`/
`surface.python.ast` re-accepted once per grammar change (section 2).

---

## 5. Order of operations, one line

M0 measure → M1 subclass index → M2 scope chains → M3 remaining scans and
allocation → M4 multi-unit emission and parallel clang → M5 `#line` and
dev builds → M6 stable units and the object cache → **M7 profile-driven
cuts (finish) → M8 per-kind nodes → M11 separate compilation → M9 arenas →
M10 parallel lowering.**

M11 comes before M9 and M10 because it changes what an edit costs, which
matters more than what a cold build costs, and it depends on neither; M9
and M10 then shrink both. M6's open items ride along with M7 and M8 as
they are measured. M1–M3 and M7–M10 are byte-identical-output changes
gated by `cmp`; M4–M6 and M11 change the emitted shape and are gated by
the corpus goldens, bootstrap and the BTRSmith suite. Each milestone ends
with the table in `docs/design/compile-performance.md` updated.
