# btrc Compiler — Architecture & Development Rules

These rules are non-negotiable. Every contributor (human or AI) must follow them.
Read this ENTIRE file before writing any code.

---

## Multi-Session Warning

This project is too large for a single context window. You WILL run out of memory.

### Current state (2026-08-21)

Work happens directly on `main`; every prior campaign branch was merged and
deleted. The architecture migration is finished; what follows records the state
a change has to preserve.

The architecture destination and frozen-boundary infrastructure are complete.
The frontend resource-ceiling removal, the Python VLA bound single-evaluation
fix, and the empty managed slot defect have landed with their regressions.

The verification matrix runs: `make test` at 7,274 passed and 20 skipped, and
`make bootstrap` reaching its byte-stable fixed point. Two caveats matter when
you read a green run:

- The boundary gate checks **301** records outside the nix shell but **277**
  inside it, because four observed-behavior capabilities are skipped there as
  incompatible. Twenty-four records go unchecked under that toolchain.
- The twenty skips are missing tools — `naga`, `lldb`, `pkg-config`, and
  platform-specific paths — not product defects. They are still coverage the
  run did not get, and a green result looks identical either way.
- `stdlib/test_stdlib_daemon.btrc` asserts a wall-clock daemon-stop deadline,
  so it can fail on a saturated machine and pass on a quiet one.

Do not claim completion until `make test`, `make bootstrap`, `make test-c11`,
lint, format, generated-source, extension, and repository-hygiene gates all pass
on the final tree. Do not treat the size of the checkpoint as accidental, and do
not discard its frozen boundary fixtures.

The test harness builds the self-hosted compiler once per source revision and
caches it under `build/test-btrcc/<fingerprint>/`; a change to any compiler
source, the stdlib, a shared spec, a runtime asset, or the C compiler version
invalidates it. Set `BTRC_TEST_BTRCC` to reuse a binary you built yourself.
### Performance changes already measured and rejected

Each of these was implemented or prototyped, measured, and abandoned. Do not
retry them without new evidence:

- **Bounding the substring scan.** `__btrc_substring` measures the whole string
  to clamp, so lexing is quadratic — `Lexer_readIdentifier` slices the entire
  source once per token, and `strlen` was 60% of a self-compile profile.
  Scanning only `start + len` measured **415s against a 278s baseline**: it
  traded a SIMD `strlen` for a byte-at-a-time loop.
- **A pointer-keyed string-length cache.** Memory-unsafe. Cache `(buf, 900)`
  for a `char[1024]`, let the frame return, and a later `char[16]` at that
  stack address yields a 900-byte read from a 16-byte buffer.
- **Consolidating the thread-locals.** `_tlv_get_addr` was 45% of profile
  samples, but a build with `_Thread_local` stripped was not faster.
  Leaf-sample share is not speedup.
- **`-ftls-model=local-exec`.** Identical timings; Darwin resolves
  thread-locals through its own TLV descriptors, not the ELF models that flag
  selects.
- **`-O1` for the bootstrap's C compiles.** `-O1` is 392s against `-O2`'s 430s;
  the cliff is `-O0`→`-O1`. Dropping to `-O0` would also retire
  `-Wmaybe-uninitialized`, which only fires at `-O2`.
- **Running the gate's three verifications concurrently.** Reverted:
  `test_memory_intensive_bootstrap_runs_after_the_parallel_suite` encodes the
  sequencing, and its reason is in its name — the bootstrap compiles a
  431k-line translation unit at `-O2`, which is a memory risk beside eight
  pytest workers.

What did work: emitting the generated ABI and runtime-catalog tables as many
small methods rather than one constructor (a single 114,073-line C function was
~90% of the cost of compiling the compiler; `-O2` went 429.8s → 52.5s), and
sharing one cached compiler across test modules instead of rebuilding it per
xdist worker.

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
- NEVER hand-edit syntax/ast/generated.py or generated/ast/node.btrc — regenerate from ASDL

### Shared runtime and hosted ABI

- `src/runtime/c/manifest.toml` is the single runtime-helper manifest.
- The pre-authored runtime assets are `btrc_rt.h`, `core.c`, `collections.c`,
  `cycles.c`, `mutex.c`, `process.c`, `strings.c`, `threads.c`, `trycatch.c`,
  and `gpu.c` in `src/runtime/c/`.
- Runtime metadata is generated into
  `src/compiler/python/runtime/generated.py` and
  `src/compiler/btrc/generated/runtime/catalog.btrc`; handwritten catalog,
  selection, reference, and materialization behavior remains with the retained
  runtime owners in each compiler.
- `src/language/hosted_abi.toml` generates
  `src/compiler/python/abi/generated.py` and
  `src/compiler/btrc/generated/hosted_abi/tables.btrc`.
- Generated modules contain data/schema declarations only. Generated Python
  rows use immutable value types; generated btrc rows expose public fields
  required by the language and consumers treat them as read-only by
  convention. Generated modules never own lookup, validation, selection,
  canonical rendering, or source-assembly behavior.

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

The destination contains exactly 82 production Python files:

```text
src/compiler/python/
  __init__.py                     Compiler/Options/Result API only
  main.py                         thin process entry point

  application/
    __init__.py
    compiler.py                   Compiler
    pipeline.py                   CompilationPipeline
    results.py                    immutable cross-stage results

  cli/
    __init__.py
    compiler.py                   CompilerCommand
    bundle.py                     BundleCommand

  frontend/
    __init__.py
    stage.py                      frontend composition
    sources.py                    SourceResolver/dependency graph
    imports.py                    ImportResolver/visibility
    packages.py                   PackageUniverse/GitDependencyCache

  syntax/
    __init__.py
    grammar.py                    GrammarRepository, EbnfGrammarParser
    tokens.py                     Token, TokenKind, TokenVocabulary
    ast/
      __init__.py
      generated.py                generated ASDL dataclasses
      codec.py                    AstJsonCodec

  lexer/
    __init__.py
    lexer.py                      Lexer and LiteralScanner

  parser/
    __init__.py
    parser.py                     complete stateful Parser

  analyzer/
    __init__.py
    analyzer.py                   SemanticAnalyzer composition root
    program.py                    AnalyzedProgram/scopes/indexes
    declarations.py              DeclarationRegistry
    types.py                      TypeSystem
    aggregates.py                 AggregateAnalyzer
    expressions.py                ExpressionAnalyzer
    calls.py                      CallAnalyzer/callable flow
    statements.py                 StatementAnalyzer
    flow.py                       ControlFlowAnalyzer
    storage.py                    StorageModel
    ownership.py                  OwnershipAnalyzer
    generics.py                   GenericAnalyzer
    gpu.py                        GpuAnalyzer
    macros.py                     SourceMacroAnalyzer/Namespace
    generated_symbols.py          GeneratedSymbolRegistry
    realtime.py                   RealtimeAnalyzer/fixed-point effect proof

  abi/
    __init__.py
    generated.py                  generated hosted-ABI data
    declarations.py               hosted ABI value declarations
    hosted.py                     HostedAbiRepository
    freestanding.py               FreestandingRuntime

  ir/
    __init__.py
    nodes.py                      complete typed IR model/IRModule
    verifier.py                   IRVerifier
    optimizer.py                  IROptimizer

    lowering/
      __init__.py
      lowerer.py                   IRLowerer composition root
      session.py                   LoweringSession/scopes/temporaries
      translation_unit.py          TranslationUnitLowerer
      declarations.py              DeclarationLowerer
      classes.py                   ClassLowerer
      functions.py                 FunctionLowerer
      types.py                     CTypeLowerer
      expressions.py               ExpressionLowerer
      calls.py                     CallLowerer
      storage.py                   StorageLowerer
      ownership.py                 OwnershipLowerer
      statements.py                StatementLowerer
      control_flow.py              ControlFlowLowerer
      collections.py               CollectionLowerer
      iteration.py                 IterationLowerer
      exceptions.py                ExceptionLowerer/setjmp analysis
      concurrency.py               ConcurrencyLowerer
      generics.py                   GenericSpecializer only
      gpu.py                        GpuLowerer

  backend/
    __init__.py
    c_emitter.py                  CEmitter
    wgsl_emitter.py               WgslEmitter

  runtime/
    __init__.py
    catalog.py                    RuntimeHelperCatalog
    generated.py                  generated runtime-helper data

  artifacts/
    __init__.py
    archive.py                    ArchiveCodec/validation
    cache.py                      CompilerCache
    publication.py                ArtifactPublisher
    stdlib.py                     StdlibArtifactRepository
    selfhost.py                   SelfhostBundleBuilder
```

Compiler tests live in `src/tests/python/`; generated language/runtime fixtures
and their golden output live alongside the topic-organized corpus in
`src/tests/`.

---

## btrc Compiler (src/compiler/btrc/)

The self-hosted compiler implements the same six-stage pipeline with fat tagged
AST and IR nodes. Its destination contains exactly 91 `.btrc` files: 85
compiler/generated files and six explicit developer-tool files. Only
`compiler.btrc` and the thin `btrcc_main.btrc` process entry point remain at the
package root. The owned packages are:

```text
cli/                              BtrccDriver
pipeline/                         stage manifest, mutable options/results, CompilerPipeline
syntax/                           grammar, tokens, identity/canonical rendering, types, literals
generated/ast/                    ASDL-generated Node data/schema only
generated/hosted_abi/             generated ABI data
generated/runtime/                generated runtime catalog data
lexer/                            stage manifest and Lexer
frontend/                         stage, models, source I/O, stdlib, resolver, visibility
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
tools/                            five entry points plus the ASDL schema owner
```

`pipeline/models.btrc` contains the mutable options and result transports for
one compilation. Analyzer indexes and shared semantic records belong to
`analyzer/models.btrc`; expression-type memo state belongs privately to
`ExpressionTypeResolver` in `analyzer/expressions.btrc`.
`IRStatementSequence` belongs to `ir/lowering/control_flow.btrc`.
`AstCanonicalRenderer` in `syntax/identity.btrc` owns canonical AST formatting,
and the parse inspection tool calls that owner; generated `Node` data owns no
formatting behavior. The unified generator check structurally verifies that
the handwritten renderer covers every ASDL constructor and field.

The exact 91-file inventory is normative in
`docs/design/compiler-structure.md`. Stage manifests contain imports only;
implementation behavior belongs to the concrete owner. The unified language
runner executes the corpus through both compilers, and the bootstrap suite
proves a byte-stable self-hosting fixed point.

## Verification

The architecture migration is finished, so every gate applies. Structural checks
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
  stdlib/                  Math, DateTime, Random
  algorithms/              quicksort, BST, hash table, linked list (pure C)

Each subdirectory has:
  test_*.btrc              test files (compile → gcc → run → assert PASS)
  expected/                golden .stdout files for output comparison
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
make lint                 Run ruff linter
make format               Format with ruff
make format-check         Check formatting without modifying files
make test-generate-goldens  Regenerate golden .stdout files
make compiler-codegen-generate
                          Regenerate compiler and devex data from shared specs
make extension            Package VSCode extension (.vsix)
make extension-install    Install VSCode extension (dev)
make examples             Build and run examples
make gpu                  Install WebGPU + GLFW and build GPU runtime
make examples-game        Build the 3D engine game
make examples-triangle    Build the GPU triangle example
make examples-sgd         Build the GPU SGD example
make examples-todo        Build the todo example
make devcontainer         Generate .devcontainer/ and build image
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
