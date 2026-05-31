# Design: Precompiled standard library

Status: **proposed** (not yet implemented)

## Problem

Every btrc compile processes the *entire* standard library, even for a one-line
program. The auto-included stdlib (~25 modules, ~4k lines) is lexed, parsed,
analyzed, lowered to IR, optimized, and emitted on every build. Measured with
`make bench` on a trivial program, two phases dominate and are **near-constant
across all programs**, because they are paid on the stdlib regardless of what the
user code touches:

```
phase       trivial program    notes
parse       ~185 ms            re-parses the whole stdlib
optimize    ~115 ms            dead-function elimination over the whole stdlib
```

The user-visible symptom is fixed latency on the inner edit→compile loop: editing
one line of a small program still pays the full stdlib cost.

## What already exists (and why it is not enough)

The compiler has three caches, each removing one slice of repeated work:

1. **`disk_cache.py`** — caches the *final C output* keyed by a hash of the
   fully-resolved source (stdlib + user) plus a compiler version stamp. An
   *unchanged* program recompiles in <1 ms. **Limitation:** any edit to user
   code changes the hash and misses entirely.

2. **`cache.py: get_stdlib_source_cached`** — in-process cache of the stdlib
   *source string*, keyed by the set of user-defined class names (which
   determines skip-if-redefined). Removes re-reading stdlib files.

3. **`main.py: _cached_stdlib_decls`** — on-disk pickle of the stdlib *parsed AST
   declarations*, keyed by the stdlib source hash. Removes re-lexing/re-parsing
   the stdlib on the CLI path.

So after an edit to user code, the compiler still pays, every time:

- **analyze** the combined program (stdlib bodies + user bodies), and
- **ir-gen + optimize** the combined program.

These are the phases this design targets.

## Why this is hard (the monomorphization constraint)

A naive "compile the stdlib once to a `.o`, link it" plan breaks on **generics**.
btrc monomorphizes generic types per use: `List<int>` is only emitted if some
reachable code instantiates it, and the concrete C family
(`btrc_List_int_push`, …) is generated during IR-gen of the *whole program*. A
precompiled stdlib object cannot contain `List<int>` unless it knew, ahead of
time, that this user would need exactly that instantiation.

Therefore the stdlib splits into two parts:

- **Monomorphic core** — non-generic classes and free functions whose C output
  is identical for every program: `Strings`, `Math`, `Process`/`UnixShell`,
  `FileSystem`/`Path`, `DateTime`, `Random`, `Json`, `Toml`, `Http*`, `Ui*`,
  most of `error.btrc`, etc. **This part is precompilable.**
- **Generic templates** — `Vector<T>`, `List<T>`, `Map<K,V>`, `Set<T>`,
  `Result<T,E>`, and any user generics. **This part must stay per-program**,
  because the set of instantiations is program-specific.

## Proposed approach: split translation units + cached analyzed core

Compile the monomorphic core *once* into a reusable artifact, and reference it
from the per-program translation unit.

### Artifacts (built once, cached under `.btrc-cache/stdlib/<fingerprint>/`)

- `libbtrcstd.h` — declarations (struct typedefs, function prototypes, the
  runtime-helper prototypes the core uses) for every symbol in the monomorphic
  core.
- `libbtrcstd.c` / `libbtrcstd.o` — definitions of the monomorphic core plus the
  runtime helpers it references.
- `core.analyzed` — a pickled `AnalyzedProgram` slice for the core: its
  `class_table`, function signatures, and `node_types` for *signatures only*
  (not bodies). This lets the analyzer resolve `Strings.trim(...)` in user code
  without re-analyzing the body of `Strings.trim`.

The `<fingerprint>` folds in the compiler version stamp (as `disk_cache` already
does) and the core stdlib source hash, so any change to the compiler or the
stdlib rebuilds the artifact automatically.

### Per-program compile (the fast path)

1. Resolve includes/imports as today. Determine which stdlib classes the user
   redefines (existing `_CLASS_NAME_RE` logic) — if the user redefines a *core*
   class, fall back to the current whole-program path (rare; correctness first).
2. Lex + parse only the user code (stdlib AST already cached, step unchanged).
3. **Analyze** with the core's `class_table`/signatures preloaded as *extern*
   symbols (from `core.analyzed`). The analyzer treats core functions as declared
   but bodyless — it type-checks calls without walking core bodies. Generic
   templates are still analyzed per-program (they are not in the core).
4. **IR-gen** the user code + the generic instantiations it requires. Core
   functions are emitted as `extern` prototypes (via `#include "libbtrcstd.h"`),
   not redefined. Generic families are emitted as today.
5. **optimize** runs DCE over only the per-program functions (user code + its
   monomorphized generics). The core is already minimal and lives in the prebuilt
   object; its intra-core DCE was done once at artifact-build time.
6. **emit** a small `.c` that `#include`s `libbtrcstd.h`.
7. The driver compiles the user `.c` and links `libbtrcstd.o`.

### Correctness invariants (must hold; gate with tests)

- **Skip-if-redefined still wins.** If the user defines a class named like a core
  class, the core artifact for that class must not be used; fall back to
  whole-program compilation. A test must cover a user `class Strings { ... }`.
- **Identical output semantics.** For every existing language test, the
  split-compilation output must produce the same program behavior (same golden
  stdout). The full language test suite is the acceptance gate; it must stay
  green with the precompiled path enabled.
- **Runtime helpers are not double-defined.** Helpers used only by the core live
  in `libbtrcstd.o`; helpers used by user/generic code are emitted per-program.
  Helpers used by both must be `extern` in user TUs (declared in the header), or
  duplicated as `static` in each TU. Pick one and verify the linker outcome under
  `-std=c11 -pedantic-errors` on both gcc and clang.
- **ARC across the boundary.** A core function returning a managed object (e.g.
  `Strings.copy` returns an owned `char*`; class-returning factories return owned
  pointers) must keep the same ownership contract. The cycle collector's
  per-class `*_visit`/`*_destroy` for core classes live in the core object and
  are referenced by name from user scope-release code — verify the linker
  resolves them. This interacts with the reachability DCE in `ir/optimizer.py`:
  a core destructor referenced only from user code must not be eliminated from
  the core object, so the artifact build keeps all public core destructors.

### Opt-in / rollout

Add `--precompiled-stdlib` (off by default initially), plus
`btrcpy build-stdlib` to (re)build the artifact. Once the language suite passes
with it on, flip the default and keep `--no-precompiled-stdlib` as an escape
hatch. The existing whole-program path stays as the fallback for redefinition
and for `--debug` (which needs exact source positions over the combined text).

## Expected payoff

The monomorphic core is the bulk of stdlib lines, so moving its analyze/ir-gen/
emit out of the per-program path should remove most of the constant parse/
optimize cost an edit currently pays — the inner loop drops toward "user code
only" time. Measure with `make bench` before/after; the `funcs_before→after`
column already isolates how much of each program is core vs. per-program.

## Why it is deferred

This is separate compilation: it touches the analyzer (extern symbol tables),
IR-gen (extern vs. defined emission), the helper system (cross-TU helper
ownership), ARC (cross-TU destructor references), and the driver (link step). It
must not regress any language test or the ARC memory semantics. It is a
multi-step change that deserves its own focused effort with the full suite as a
gate — not a corner cut. This document is the plan of record for that effort.
