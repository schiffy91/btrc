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

## M6 — Per-module front end and cache

The front end stops concatenating the closure into one string; the
resolver already has the dependency graph (`FeDependencyGraph`), it just
throws it away after building the string.

1. **Per-module parse**: lex and parse each source identity separately into
   its own declaration list, keyed by `(source identity, content hash)`.
   Line numbers become `(file, line)` everywhere they are `(concatenated
   line)` today — diagnostics, `#line`, `userLines`, `stdlibLineCount`.
   The program AST is the concatenation of the per-module declaration
   lists in the same order as today, so analysis sees the same input.
2. **Cache the parsed modules** in the existing cache directory
   (`~/.cache/btrc`, `artifacts/cache.py` and its btrc mirror), keyed by
   content hash + grammar + toolchain fingerprint. Unchanged modules are
   loaded from cache, so `lex`/`parse` are paid only for edited files.
3. **Cache analysis per module** where analysis is local (declaration
   registration, member tables, visibility, per-function validation for
   functions whose types are all resolved within the closure that did not
   change). Whole-program passes (instantiation, DCE, cycle analysis,
   lowering) still run; after M1–M3 they are the cheap part.
4. **Per-unit reuse** with M4: a unit whose emitted text is unchanged is
   not recompiled (content-hash the unit, keep the object in the build
   directory).
5. Turn the cache on by default in the Makefiles (drop `--no-cache`); keep
   `--no-cache` for the goldens and CI's clean-tree runs.

Exit: editing one BTRSmith adapter and rebuilding takes under a minute;
each BTRSmith check target re-transpiles the app in about a minute; a
cold build is unchanged from M4.

---

## M7 — Parallel lowering and a slimmer AST

Only if M6 leaves lowering as the bottleneck, and in this order.

1. **Parallel lowering**: after analysis the shared tables are read-only;
   `FunctionLowerer.lowerBody` runs over a thread pool with per-thread
   temporaries, results appended in the original order. Needs the ARC
   runtime's thread-confinement rules written down and a sanitizer run
   (`-fsanitize=thread`) on the compiler itself.
2. **Per-kind AST nodes**: replace the one 103-field `Node` with a base
   node plus per-kind structs generated from the same schema (`generated/ast`).
   Memory ~3× down, allocation ~3× faster. Every pass in both compilers is
   touched, which is why it is last.

Exit: btrcc under 1 minute on BTRSmith cold; peak RSS under 2 GB.

---

## Order of operations, one line

M0 measure → M1 subclass index → M2 scope chains → M3 remaining scans and
allocation (re-profile until flat) → M4 multi-unit emission and parallel
clang → M5 `#line` and dev builds → M6 per-module front end and cache →
M7 parallel lowering, slimmer nodes.

M1–M3 are byte-identical-output changes gated by `cmp`; M4 onwards change
the emitted shape and are gated by the corpus, bootstrap and the BTRSmith
suite. Each milestone ends with the table in
`docs/design/compile-performance.md` updated.
