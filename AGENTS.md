# btrc Compiler — Architecture & Development Rules

These rules are non-negotiable. Every contributor (human or AI) must follow them.
Read this ENTIRE file before writing any code.

## Second agent: Codex

OpenAI Codex builds in this repository beside Claude under D27 as amended by
D28 (CLAUDE.md). Codex's active queue is [CODEX.md](CODEX.md).
[`WORKSTREAMS.md`](WORKSTREAMS.md) §3 holds claims and protocol.

- **Applies to Codex:** everything here about architecture, the pipeline,
  parity, strict imports, naming, generated files, and the Hard Rules.
- **Does not apply:** "Host capacity and agent rules" (the Mac's locks, hubs,
  disk and load rules), MEMORY.md, and the Mac measurement rules. In a cloud
  container, export `BTRC_TEST_RUNNER=linux-devcontainer` and run every
  command through `nix develop --command` (WORKSTREAMS.md §3.11).
- **Branches:** one packet per `codex/…` branch, with a draft PR to `main`
  titled `[CX-…]` whose body starts with the packet's owned paths and follows
  `.github/PULL_REQUEST_TEMPLATE/codex-packet.md`. The draft PR is for CI only.
- **Never:** push `main` or `main-kn9jxh`, merge or close a PR, edit
  `docs/design/plan-reference.md`, claim Mac, device or account evidence, or
  treat a local `make test` as the gate (draft-PR CI is).
- **Paths Codex never edits** (put a `REQUEST(<target>)` block in the PR body
  instead, WORKSTREAMS.md §3.6):
  - `src/compiler/**`, `src/language/**`, `tools/compiler_codegen/**`;
  - generated files: the Python compiler's `generated.py` modules,
    `src/compiler/btrc/generated/**`, `src/stdlib/btrc.lock`,
    `src/stdlib/btrc.symbols`, `src/devex/lsp/catalog/generated.py`;
  - `src/runtime/**`, `tools/NativeHeaderReader.cpp`,
    `tools/JavaClassReader.c`, the boundary manifest;
  - `src/devex/**` and the compiler-import stdlib modules (WORKSTREAMS.md
    §3.4), unless the packet names the file;
  - `Makefile`, `flake.nix`, `flake.lock`, `nix/*`, `src/tests/conftest.py`,
    `src/tests/runner_capabilities.py`, `tools/native_plan.py`,
    `tools/budget_bench.py`, `.github/workflows/**` (and `ci/proposed/`),
    CLAUDE.md (and the PLAN.md pointer), and this file.
- **Integrator-owned data** (`btrc.toml` exports and native rows,
  expected-skip manifests, denominators, Makefile lines, `ci/tiers.toml`)
  changes only in a final `fragment: <what>` commit, and regenerated outputs
  only in a `derived: regenerate` commit, which Claude drops and regenerates
  (WORKSTREAMS.md §3.5).

---

## Multi-Session Warning

This project is too large for a single context window. You WILL run out of memory.

### Current state (2026-09-30)

Work happens directly on `main`. [`CLAUDE.md`](CLAUDE.md) is the sequential
43-stage roadmap for everything that remains, with every decision resolved
(it moved there from PLAN.md on 2026-10-06; PLAN.md is a pointer);
the previous plan is frozen verbatim in `docs/design/plan-reference.md` and
cited as `ref:N`. Never edit the frozen reference.

For a cross-repository handoff, read BTRSmith's MVP epic (schiffy91/btrsmith
issue #15, which replaced `GOAL.md`), `docs/HWW.md`, `docs/DD.md` and
`docs/NativePlatformPlan.md` after this file. The structure-first review was
done on 2026-09-14 and has drifted since; PLAN.md Stage 4 repeats it. Consumers
may continue against approved interfaces while compiler repairs land; do not
invent a second wrapper or ownership model.

The verification matrix last recorded green on `1cadaf4`: `make test` at
12,439 passed and 172 skipped, `make test-c11` at 8 × 1,934, and `make
bootstrap` reaching its byte-stable fixed point. Caveats when you read a green
run:

- The boundary manifest holds **311** records
  (`src/tests/fixtures/compiler_boundaries/manifest.toml`, checked by
  `test_boundary_manifest.py`).
  Some observed-behavior capabilities are skipped inside the nix shell as
  incompatible; PLAN.md Stage 2 records how many are checked there.
- The skips are missing tools and environment-gated providers — `naga`,
  `lldb`, `pkg-config`, `BTRC_NATIVE_PROVIDER_CC`/`CXX`, and platform-specific
  paths — not product defects. They are still coverage the run did not get, and
  a green result looks identical either way; PLAN.md Stage 2's skip ledger
  classifies every one.
- `stdlib/Daemon.btrc` used to fail under load with a daemon-stop deadline
  error. That was a stop race, not a deadline too tight for a saturated
  machine: `4c9af96` closed it (the record is read before its absence is
  judged) and added a deterministic deadline-path check. A second cause made
  the program take about 15 s in a container, right at the corpus runner's
  15 s run timeout: a stopped group's orphaned descendants stay zombies until
  init reaps them, and `kill -0` counts zombies, so every stop waited out the
  full `TERM` grace and then init's reaping (pid 1 in the cloud containers
  reaps late). The supervisor now treats a group whose members are all zombies
  as finished (`stage2/daemon-runtime`), and the program runs in under 6 s.
  A failure there now is a real defect, not load.

### Host capacity and agent rules

One Mac carries every gate, guest and agent: Apple M1 Max, 8P+2E, 64 GiB,
macOS 27.0. Record exactly that host provenance string in manifests and bench
JSON.

| Resident load | Memory |
| --- | --- |
| `make test` (8 xdist workers) | most of the machine; nothing heavy beside it |
| `make bootstrap` (431k-line TU at `-O2`) | memory risk; runs alone |
| podman `linux-ci` machine (`podman-machine-default`) | 24 GiB, 6 CPUs, 40 GB disk |
| Android emulator | about 4 GiB each |
| iOS simulator | about 2–3 GiB each |
| BTRSmith self-host compile at `--jobs 1` / cold dev aggregate | 3.0 / 4.8 GiB |

- **Gates** run from a clone outside Google Drive, one at a time, holding
  `~/.cache/btrc/locks/gate`. `make bootstrap` never runs beside the parallel
  suite, another build or a guest.
- **Load rules.** The daemon-deadline fix has landed (`4c9af96`), so at most
  one agent build runs beside `make test`, and none beside `make test-c11` or
  `make bootstrap`; other agents stay read-only while a gate runs. At most one guest beside
  a gate, none during bootstrap or a measurement.
- **Measurements** need the automated quiet check (PLAN.md standing
  approvals), every guest stopped, and a workspace under
  `~/.cache/btrc/bench.noindex/`. Agents never change system settings.
- **Locks** live in `~/.cache/btrc/locks/` (`gate`, `bench`, `linux-ci`,
  `guest`, `gui-capture`, `signing`, and the two-slot `btrcc-build`
  semaphore). Take them with `~/.cache/btrc/tools/withlock.sh <name> <cmd>`;
  macOS has `lockf`, not `flock`.
- **Hubs.** Agents clone from `~/.cache/btrc/hub.git` and
  `~/.cache/btrsmith/hub.git`, never from a Drive checkout or a worktree whose
  gitdir lives in Drive. At most 6 writer clones at a time, and at most 2
  BTRSmith clones; clean BTRSmith test outputs after each run.
- **Disk.** Check free space at the start of every stage: at least 80 GB to
  continue, 100 GB before PLAN.md Stage 23. Before every agent wave, prune
  `build/test-btrcc` to the newest 20 fingerprints plus any pinned by
  `BTRC_TEST_BTRCC`.

Do not claim completion until `make test`, `make bootstrap`, `make test-c11`,
lint, format, generated-source, extension, and repository-hygiene gates all pass
on the final tree. Do not treat the size of the checkpoint as accidental, and do
not discard its frozen boundary fixtures.

The test harness builds the self-hosted compiler once per source revision and
caches it under `build/test-btrcc/<fingerprint>/`; a change to any compiler
source, the stdlib, a shared spec, a runtime asset, or the C compiler version
invalidates it. Set `BTRC_TEST_BTRCC` to reuse a binary you built yourself.

Before measuring a compile or changing the compiler for performance, read
"Measuring a compile" and "Performance changes already measured and rejected"
in [`docs/design/compile-performance.md`](docs/design/compile-performance.md):
which C compiler built the `btrcc` you measure, comparing on instructions
retired and peak memory, `BTRC_TIMING=1`, and the experiments not to retry
without new evidence.

Self-host binaries under `/tmp` are an ephemeral convenience, never a tracked
build product. Rebuild after any change to self-host production sources or to
the Python compiler that generates them.

**Before you start working:**
1. Read this file completely
2. Read MEMORY.md (in your auto-memory directory)
3. Check `git status` — this repository is synced across machines, so HEAD can
   move and foreign uncommitted files can appear mid-session
4. Establish a baseline before changing anything. The architecture migration is
   finished, so behavior, parity, and correctness suites all apply: run the
   gates that cover what you are about to touch, and know what was already
   failing before you start.

**Before context runs out:**
1. Commit working code frequently
2. Update MEMORY.md with what you accomplished and what's next
3. Leave clear breadcrumbs for the next session

**NEVER cut corners when context gets low.** If you're running low on context,
stop and save state. Do NOT start wrapping things in raw strings, skipping IR
nodes, or "temporarily" bypassing the architecture. The whole point is to do
this RIGHT.

---

## The Architecture

### Overview

The Python reference compiler and self-hosted btrc compiler follow the same
6-stage pipeline driven by formal specs.

```
SHARED SPECS (single source of truth):
  src/language/grammar.ebnf       keywords, operators, syntax rules
  src/language/ast.asdl                   AST node types (Zephyr ASDL)
  tools/compiler_codegen/asdl.py         ASDL schema parser + value model
  tools/compiler_codegen/ast.py          ASDL → Python + btrc AST catalogs

PIPELINE:
  source.btrc
       │
  [1. Lexer]        →  token stream        (grammar-driven from EBNF)
       │
  [2. Parser]       →  typed AST           (ASDL-generated node classes)
       │
  [3. Analyzer]     →  type-checked AST    (scopes, types, generic instances)
       │
  [4. IR Gen]       →  IR tree             (structured IR nodes — NOT text)
       │
  [5. Optimizer]    →  optimized IR tree   (typed reachability + normalization)
       │
  [6. C Emitter]    →  .c file             (simple tree walk, no lowering)
```

### Stage-by-Stage

#### Stage 1: Lexer
- Reads keywords + operators from `src/language/grammar.ebnf` via EBNF parser
- Builds keyword lookup table and operator trie at init time
- Tokenizes source into typed Token stream
- NO hardcoded keyword or operator lists anywhere in the codebase

#### Stage 2: Parser
- Hand-written recursive descent, guided by grammar rules
- Produces typed AST nodes generated from `src/language/ast.asdl`
- Handles disambiguation: generic `<` vs comparison, cast vs grouping,
  for-in vs C-for, tuple type vs paren group
- ASDL wrapper types: ElseBlock/ElseIf, ForInitVar/ForInitExpr,
  SizeofType/SizeofExprOp, MapEntry, FStringText/FStringExpr,
  LambdaBlock/LambdaExprBody, Capture, EnumValue, MethodSig

#### Stage 3: Analyzer
- Two-pass: register declarations, then analyze bodies
- Type inference for `var` declarations
- Generic instance collection (targets for monomorphization)
- Scope management, access control, inheritance validation
- Output: AnalyzedProgram with class_table, generic_instances, etc.

#### Stage 4: IR Gen (THE CORE)
- Walks typed AST + AnalyzedProgram → IRModule with structured IR nodes
- ALL lowering happens here and ONLY here:
  - ClassDecl → IRStructDef + method IRFunctionDefs
  - Generics → monomorphized copies per type combination
  - Methods → free functions with explicit self parameter
  - new/delete → malloc/free + constructor/destructor calls
  - for-in → C-style for with index variable
  - f-strings → snprintf sequences
  - Lambdas → static functions + capture structs
  - String/collection methods → runtime helper calls
  - Operator overloading → method calls
  - Static inheritance/member lowering and interface-contract validation
- **Produces structured IR nodes** (IRIf, IRCall, IRFor, IRBinOp, etc.)
- **NEVER produces C text.** Runtime helpers are pre-authored as cohesive assets
  under `src/runtime/c/` and described by the shared runtime manifest; IR
  lowering selects generated catalog rows but never assembles helper source.

#### Stage 5: Optimizer
- Computes one structured function/global reachability graph
- Removes unreachable functions, globals, helpers, GPU kernels, externs,
  and typed C declarations with their transitive dependencies
- Installs required cycle boundaries, normalizes unused parameters, and
  rematerializes live runtime dependencies

#### Stage 6: C Emitter
- Simple recursive tree walk over IR nodes
- Each IR node type → formatted C text
- **NO lowering logic** — just formatting what IR Gen produced

---

## Shared Specs

### src/language/grammar.ebnf
- @lexical: the canonical keyword and longest-first operator tables
- @syntax: grammar rules (human-readable spec, not parser-generator input)
- EBNF parser extracts GrammarInfo: keyword set, operator list,
  keyword→token mapping, operator→token mapping

### src/language/ast.asdl (Zephyr ASDL)
- Typed sum and product node definitions for the complete source AST
- Sum types: decl, stmt, expr, class_member, if_else, for_init, etc.
- Product types: Program, ClassDecl, BinaryExpr, etc.
- attributes(int line, int col) on nodes that have source locations
- Field names ARE the API contract for analyzer, IR gen, LSP, and tests
- NEVER hand-edit syntax/ast/generated.py or generated/ast/Node.btrc — regenerate from ASDL

### Shared runtime and hosted ABI

- `src/runtime/c/manifest.toml` is the single runtime-helper manifest.
- The pre-authored runtime assets are `btrc_rt.h`, `core.c`, `collections.c`,
  `cycles.c`, `mutex.c`, `process.c`, `strings.c`, `threads.c`, `trycatch.c`,
  and `gpu.c` in `src/runtime/c/`.
- Runtime metadata is generated into
  `src/compiler/python/runtime/generated.py` and
  `src/compiler/btrc/generated/runtime/Catalog.btrc`; handwritten catalog,
  selection, reference, and materialization behavior remains with the retained
  runtime owners in each compiler.
- `src/language/hosted_abi.toml` generates
  `src/compiler/python/abi/generated.py` and
  `src/compiler/btrc/generated/hosted_abi/Tables.btrc`.
- `src/language/targets.toml` is the compilation-target spec (PLAN.md D21):
  the target rows, the predefined-macro table that `#if` evaluates, and the
  reserved and foreign macro name lists. `TargetManifest` in
  `tools/compiler_codegen/hosted_abi.py` validates it and renders it into the
  same two hosted-ABI modules (`TARGET_*` tables;
  `GeneratedHostedAbiData.targetRows()` and its siblings). Selection and
  classification belong to each compiler's conditional-environment owner.
- Generated modules contain data/schema declarations only, with one
  exception: the self-hosted `generated/ast/Node.btrc` also carries generated
  `name()`/`nameMut()` accessors for the lazily allocated list fields named in
  `_LAZY_LIST_FIELDS` (`tools/compiler_codegen/ast.py`, which rejects a name
  that is not an ASDL list field). Those accessors own only that storage's
  allocation and its shared-empty guard. Generated Python
  rows use immutable value types; generated btrc rows expose public fields
  required by the language and consumers treat them as read-only by
  convention. Generated modules never own lookup, validation, selection,
  canonical rendering, or source-assembly behavior.

---

### Naming

The shared specs (`ast.asdl`, `hosted_abi.toml`, `targets.toml`, `manifest.toml`) name every
field once, in snake_case. Each generator renders those names in the
convention of the language it emits: `generated.py` keeps snake_case, and the
`.btrc` catalogs are respelled camelCase. Handwritten source on either side
follows its own language, so a spec field `is_gpu` reaches the Python compiler
as `is_gpu` and the self-hosted compiler as `isGpu`.

This holds for **every** `.btrc` file, not just the compiler: the stdlib, the
corpus and the examples all spell what they own in camelCase, and
`src/tests/btrc/test_naming_convention_contract.py` checks each tracked source.

Foreign names are the exception, because their spelling is the contract, and
the test reads them from three places rather than a list that could drift:

- `src/language/hosted_abi.toml` covers `size_t` and its neighbours.
- The repository's own `.c`, `.h` and `.m` sources cover what btrc links
  against — a stdlib shim, a native fixture, an example package. Respelling
  only the btrc side of one of those strands the C definition, so a third
  check looks for that fingerprint: an `extern` the C sources do not spell,
  whose snake_case form they do.
- Members of system structures are listed in the test itself. btrc emits
  `entry->d_name` straight through to C, so unlike every other foreign name
  there is no declaration in the tree to read it from.

**Every `.btrc` file name is PascalCase**, with no underscore and no leading
lowercase letter, because the file is named for what it declares. That holds
in the stdlib (`Array.btrc`, `HTTPClient.btrc`), in the self-hosted compiler
(`ControlFlow.btrc`, `Analyzer.btrc`), in the corpus (`CastFollowedByUnary.btrc`)
and in the examples. A stdlib module's import name is its stem, so
`Array.btrc` is `import Library.Array;`, and `expected/<Stem>.stdout` is the golden
output for `<Stem>.btrc`.

The corpus runner discovers a file whose name begins with a capital. A
source that another corpus source includes or imports by path is a fixture,
not a program: `include_fixtures()` derives that set from the references
themselves. The benchmark directory -- whose programs `tools/bench` times
instead -- is listed in `NON_CORPUS_DIRECTORIES`. Both live in
`src/tests/corpus_files.py`.

Stdlib package directories are PascalCase too: `Audio/MacOS`, `GUI/MacOS`,
`GPU`, and `BackgroundJobs`. Imports use their exact spelling, for example
`import Library.Audio.RealtimeAudio;`. Capitalize acronyms in stdlib module
and type names: `MacOS`, `GUI`, `GPU`, `UI`, `HTTP`, `JSON`, `IO`, and `CLI`.
C symbols and SDK names retain their external spelling. Every stdlib directory
is PascalCase. The Windows POSIX header overlays are not stdlib: they live in
`src/runtime/windows/` (`sys/`, `arpa/`, `netinet/`), whose lowercase include
paths are external API.

---

## Python Compiler (src/compiler/python/)

### Cohesion and Object Design

Module boundaries follow ownership and cohesion, not line counts. File size is
a review signal, never a hard limit and never sufficient reason to split a
module. Keep a cohesive implementation together until it contains genuinely
independent responsibilities with stable APIs.

Production compiler behavior belongs to the class that owns its stage or
domain. Do not add loose module-level behavior functions. Prefer instance
methods when behavior depends on compiler state and class methods for stateless
operations owned by a real domain type. Classes must represent meaningful
owners, not one-function pseudo-namespaces. Module-level constants, generated
tables, type declarations, and thin process entry points are allowed.

`__init__.py` files are allowed when they define a small, intentional package
API. Do not create wildcard re-export layers or package facades that conceal
dependency direction. Internal code should still import the concrete owner it
depends on.

### Import Discipline

Strict imports are the language and compiler default. A source file must import
the top-level symbols it references. Any relaxed compatibility mode must be an
explicitly named opt-out; it may never silently become the default. The Python
compiler, self-hosted compiler, bootstrap, examples, and test corpus must all
prove the strict-import path.

### File Structure

The exact 88-file production inventory, with each file's owner, is normative
in [`docs/design/compiler-structure.md`](docs/design/compiler-structure.md);
`src/tests/python/test_python_compiler_structure.py` checks it against the tree.

Compiler tests live in `src/tests/python/`; generated language/runtime fixtures
and their golden output live alongside the topic-organized corpus in
`src/tests/`.

---

## btrc Compiler (src/compiler/btrc/)

The self-hosted compiler implements the same six-stage pipeline with fat tagged
AST and IR nodes. Its destination contains exactly 97 `.btrc` files: 94
compiler/generated files (including the three `cli/` host entries) and three
stage-inspection tool files. Only
`Compiler.btrc` and the thin `BtrccMain.btrc` process entry point remain at the
package root. The owned packages are:

```text
cli/                              BtrccDriver and Windows/macOS host entry points
pipeline/                         stage manifest, mutable options/results, CompilerPipeline, ModuleUnitCompiler
syntax/                           grammar, tokens, identity/canonical rendering, types, literals
generated/ast/                    ASDL-generated Node data/schema plus lazy list accessors
generated/hosted_abi/             generated ABI data
generated/native_abi/             ASDL-generated native-header semantic data
generated/runtime/                generated runtime catalog data
lexer/                            stage manifest and Lexer
frontend/                         stage, models, source I/O, stdlib, resolver, visibility, native reader
parser/                           stage, Parser, SourceMacroDefinition
analyzer/                         semantic composition and domain owners
analyzer/ownership/               managed-value and cycle semantics
analyzer/validation/              validator plus ten focused validators
ir/                               stage manifest, structured model, CEmitter
ir/runtime/                       runtime catalog and reference collector
ir/lowering/                      context, composition, and domain lowerers
ir/lowering/ownership/            six ownership lowerers
ir/gpu/                           WGSL emitter and GPU pipeline
ir/optimization/                  optimizer, cleanup, and realtime validation
ir/optimization/setjmp/           effect analysis and safety planning
tools/                            lexer, parser and frontend inspection entry points
```

`pipeline/Models.btrc` contains the mutable options and result transports for
one compilation. Analyzer indexes and shared semantic records belong to
`analyzer/Models.btrc`; expression-type memo state belongs privately to
`ExpressionTypeResolver` in `analyzer/Expressions.btrc`.
`IRStatementSequence` belongs to `ir/lowering/ControlFlow.btrc`.
`AstCanonicalRenderer` in `syntax/Identity.btrc` owns canonical AST formatting,
and the parse inspection tool calls that owner; generated `Node` data owns no
formatting behavior. The unified generator check structurally verifies that
the handwritten renderer covers every ASDL constructor and field.

The exact 97-file inventory is normative in
`docs/design/compiler-structure.md`. Stage manifests contain imports only;
implementation behavior belongs to the concrete owner. The unified language
runner executes the corpus through both compilers, and the bootstrap suite
proves a byte-stable self-hosting fixed point.

Host capabilities are composed at the process entry point. `BtrccMain.btrc`
supplies the bounded Unix SDK-reader process; `cli/WindowsMain.btrc` uses the
same driver and pipeline without SDK scanning, until a real Windows process
provider exists. Native semantics depend only on `FeNativeHeaderReader`, not
on Unix process APIs. The explicit `cli/MacOSMain.btrc` entry additionally
composes the SDK-backed artifact digest provider; it is a host-composition
file only, and the six stage owners are unchanged. The portable Unix entry
remains usable without SDK hashing, including cross releases.
Build and bootstrap the entry point for the compiler's
host, not for the target of an arbitrary program it later compiles.

## Verification

The architecture destination is established, so every gate applies to claimed
behavior. Structural checks
still matter — exact-tree and stale-path audits, generated-source checks,
AST/parse/import checks, dependency/SCC and loose-behavior audits, and
`git diff --check` — but they are a first pass, not a substitute for behavior,
parity, corpus, and bootstrap runs. Run the gates covering what you touched,
and finish on the full matrix below.

---

## Testing Strategy

### CLI Flags

| Flag | Output |
|---|---|
| `--emit-tokens` | Token stream (one per line) |
| `--emit-ast` | Canonical AST dump |
| `--emit-ir` | IR tree dump (after IR gen, before optimizer) |
| `--emit-optimized-ir` | IR tree dump (after optimizer) |
| (default) | C source file |

### Test Categories

#### 1. Python Unit Tests (per-stage)
```
src/tests/python/
  test_lexer.py           tokenize snippets → check tokens
  test_parser.py          parse snippets → check AST structure
  test_analyzer.py        analyze snippets → check types/errors
```

#### 2. Language Tests (organized by topic)
```
src/tests/
  runner.py                test runner (pytest parametrized)
  generate_expected.py     regenerate golden files

  corpus_files.py          which .btrc files are runnable programs
  conftest.py              --compilers option + shared fixtures

  basics/                  types, vars, print, nullable, casting, sizeof, etc.
  control_flow/            if/for/while/switch/try-catch, range, includes
  classes/                 classes, inheritance, interfaces, abstract, operators
  collections/             Vector, Map, Set, Array, indexing, iteration
  strings/                 string methods, fstrings, zfill, conversions
  functions/               default params, lambdas, forward decl, recursion
  generics/                user generics, Result<T,E>
  enums/                   simple enums, rich enums, toString
  tuples/                  tuple creation, access, multi-element
  memory/                  ARC: keep/release, cycle detection, auto-release
  threads/                 spawn, Thread<T>, Mutex<T>, ARC captures
  gpu/                     @gpu kernels, WGSL generation, dispatch
  stdlib/                  stdlib modules and packages
  algorithms/              quicksort, BST, hash table, linked list (pure C)
  imports/                 strict imports, directory imports, C sources
  c_compat/                C11 constructs btrc accepts unchanged

Each corpus directory has:
  <Name>.btrc              PascalCase programs (compile → C11 → run → assert PASS)
  expected/                golden <Name>.stdout (and .stderr) files

Not corpus (corpus_files.NON_CORPUS_DIRECTORIES):
  native/                  native-provider programs and C harnesses, each with
                           a dedicated pytest driver that supplies its ABI units
  benchmarks/              programs tools/bench compiles, runs and times
  python/ btrc/            per-compiler pytest suites
  formatter/               formatter tests and fixtures
```

### Makefile Targets
```
make build                Create bin/btrcpy wrapper script
make test                 Run unit, LSP, debugger, and both compiler corpora
make test-unit            Run Python reference-compiler unit tests
make test-lsp             Run editor/LSP tests
make test-debug           Run debugger/DAP tests
make test-btrc            Run the corpus through the Python compiler
make test-btrc-selfhost   Run the corpus through btrcc plus self-host tests
make bootstrap            Prove the self-hosted compiler's fixed point
make test-c11             Strict C11: gcc + clang at -O0 through -O3
make lint                 Run generated-policy checks and the ruff linter
make format               Format Python (ruff) and BTRC (btrc-format) sources
make format-check         Check both formattings without modifying files
make format-btrc-check    Check only the BTRC formatting
make test-generate-goldens  Regenerate golden .stdout files
make compiler-codegen-generate
                          Regenerate compiler and devex data from shared specs
make extension            Package VSCode extension (.vsix)
make extension-install    Install VSCode extension (dev)
make examples             Build and run examples
make gpu                  Build the headless @gpu compute runtime (skips if WebGPU is missing)
make gpu-required         Fail unless that runtime built
make examples-game        Build the 3D engine game
make examples-triangle    Build the GPU triangle example
make examples-sgd         Build the GPU SGD example
make examples-todo        Build the todo example
make examples-gui         Build the portable native GUI example
make examples-native-package TARGET=linux-x64
                          Build the recursive native package from its plan
make devcontainer         Generate .devcontainer/ and build image
make linux-ci             Run LINUX_CI_TARGETS in that container, as Linux CI does
make clean                Remove build artifacts
```

Run `make help` for the canonical, complete target list.

---

## Hard Rules (Summary)

1. **IR Gen produces structured IR nodes, NEVER raw C text.**
2. **No monolithic codegen.** IR gen + optimizer + emitter is the ONLY path.
3. **Grammar is the single source of truth.** No hardcoded keywords/operators.
4. **AST types come from ASDL.** Never hand-edit generated files.
5. **Cohesion before size.** Split and consolidate only at real ownership boundaries.
6. **All tests must pass.** No "pre-existing failures."
7. **Generated C must be strict C11.** No compiler-specific extensions.
8. **Strict imports are the default.** Relaxation is explicit and compatibility-only.
9. **No loose compiler behavior.** Stage/domain classes own executable logic.
10. **Don't cut corners when context runs low.** Save state and stop.
11. **Each language keeps its own spelling.** btrc names the things it owns in
    camelCase (PascalCase types); the Python compiler stays snake_case. Shared
    specs are written once in snake_case and rendered per language. Only hosted
    C ABI names keep their C spelling.
