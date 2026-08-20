# BTRC Compiler Architecture Goal

This file is the persistent contract for the compiler and developer-experience
refactor. It is intentionally detailed enough to survive context compression
and handoff between sessions.

## Session Protocol

Before changing code for this goal:

1. Read `AGENTS.md` completely.
2. Read this file completely.
3. Inspect `git status` and preserve all existing goal work.
4. Inspect the progress checklist below.
5. Establish the smallest baseline permitted by the current phase: structural,
   generation, and loadability checks during foundation work; behavioral and
   parity checks after the architecture checkpoint.

Before ending a session:

1. Leave the tree in a verified state or record the exact unfinished state.
2. Update the progress checklist and breadcrumbs in this file.
3. Commit coherent, working checkpoints frequently.
4. Never weaken an invariant or add a compatibility shim to save time.

This goal is not complete until the destination trees exist, obsolete paths are
gone, both compilers are behaviorally and byte-for-byte verified, the complete
test matrix passes, and the devex artifacts build successfully.

## Active Handoff (2026-08-19)

### Repository state

- Continue from branch `codex/compiler-refactor-handoff`. The checkpoint is a
  single intentional architecture-and-correctness campaign; do not discard or
  split the large compiler, runtime, devex, test, golden, or frozen-boundary
  diff merely because it spans hundreds of files.
- The architecture destination, exact production inventories, runtime/hosted
  specifications, generated catalogs, compiler-boundary snapshot harness,
  portable Makefile boundary gate, LSP/debugger/VS Code ownership moves, and
  corpus golden completion are implemented.
- Correctness is still in the self-host hill-climb. The final serial self-host
  suite, `make test`, `make test-c11`, and the actual bootstrap fixed point have
  **not** passed on this final checkpoint. Do not mark this goal complete.
- All worker processes were stopped for this handoff. No build or test is
  intentionally running in the background.

### Last immutable self-host artifact

The latest current-tree strict artifact was generated before the handoff stop:

```text
C:      /tmp/btrc-current-joint-stage1.N37NYk/btrcc.c
SHA256: e03fdbd26f913fab61033299416329ab06f11347a4df8898037aea6346ad744d
binary: /tmp/btrc-current-joint-stage1.N37NYk/btrcc
SHA256: 3432ef09bb04eeebce72ad7e0bf09ba59895d557ad5363225a99dc6b8aa6f5d2
inputs: 99b1ae9626de6064cb0745072162e68c8cc4ac87a72d76308eb87278249c2a26
```

It was produced by a clean Python-to-C transpile (164.31 s) and strict C11
`-pedantic-errors -Wall -Wextra -Werror -O2` native build (80.14 s). The input
fingerprint was unchanged before and after the build. `/tmp` is not durable:
verify the hash before reuse and rebuild after any self-host production edit or
when the path is absent.

### Immediate next steps

1. **Fix Python VLA bound single evaluation.** The exact failing node is
   `src/tests/btrc/test_gpu_boundary.py::test_gpu_vla_capacity_does_not_replay_the_declared_bound[python]`.
   Python currently emits `int values[((size() > 0) ? size() : 1)]`, evaluating
   the effectful bound twice. The owner seam is
   `StatementLowerer.lower_declaration` ->
   `StorageLowerer.materialize_array_size`/`safe_array_size`. Preserve one
   logical bound value, materialize a typed local temp once for a runtime VLA,
   use its clamped physical extent for C storage, and record the unclamped
   logical extent in `CArrayBinding` for GPU/iteration consumers. Constant and
   static bounds must stay direct; initialized VLAs remain rejected. Re-audit
   the exact API shape before editing because the independent VLA audit was
   interrupted by this handoff.
2. **Rerun the optional/coalesce self-host regression.** The new node is
   `src/tests/btrc/test_semantic_validation.py::test_optional_generic_method_coalesce_keeps_result_and_cleanup_paths_separate`.
   The compiler output strict-builds and runs successfully. Its structural
   assertion was updated to recognize the intentional lazy false branch
   `: (__btrc_optional_result_N = scalarFallback())`; rerun the exact node with
   the artifact above to close the gate.
3. **Finish `test_gpu_boundary.py`.** After the VLA fix, rerun the full file
   against the Python compiler and the immutable self-host artifact. Sixty-one
   tests passed before the VLA node stopped the last run. The GPU helper-name
   assertions were deliberately rewritten around dispatch dataflow/order rather
   than unstable temp prefixes.
4. **Resume self-host discovery suffixes.** The private continuation manifests
   from this machine are under `/tmp/btrc-selfhost-continuations.RrvVIO/` if
   still present. They restart shard 1 at `test_generic_instance_closure.py`,
   shard 2 at `test_generic_array_assignment_contract.py`, and shard 3 at
   `test_helper_mirrors.py`. Several boundaries found after those restart
   points have already been fixed, so focused files should be rerun before
   continuing past the last stopped modules (`test_lexical_call_resolution_contract.py`,
   `test_gpu_boundary.py`, and `test_property_layout_contracts.py`). These
   shards are discovery only; they never replace the final serial run.
5. **Run one authoritative final matrix only after discovery is green:**
   portable and observed frozen boundaries, the full no-cache Python suite,
   both language corpora, complete non-bootstrap self-host suite from zero,
   strict GCC/Clang C11 matrix, LSP, debugger, extension packaging, lint,
   format, generated checks, `make test`, and finally `make bootstrap`.
6. Remove only ignored caches/build products after all gates pass. Do not remove
   committed boundary fixtures or newly added exact stdout/stderr goldens.

Suggested first commands:

```bash
export BTRC_TEST_BTRCC=/tmp/btrc-current-joint-stage1.N37NYk/btrcc
shasum -a 256 "$BTRC_TEST_BTRCC"

PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  'src/tests/btrc/test_gpu_boundary.py::test_gpu_vla_capacity_does_not_replay_the_declared_bound[python]'

PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  src/tests/btrc/test_semantic_validation.py::test_optional_generic_method_coalesce_keeps_result_and_cleanup_paths_separate

PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  src/tests/btrc/test_gpu_boundary.py
```

### Verified evidence to preserve

- Frozen boundary harness: 301 records, 69 intentional accepted deltas, 34
  current parity equalities; the portable Makefile gate previously checked 277
  records and skipped only four explicitly observed host-dependent GPU cases.
- Earlier full Python checkpoint: 3270 passed, 26 skipped; earlier Python
  language corpus checkpoint: 930 passed, 3 skipped. These predate the latest
  fixes and therefore must be rerun; they are breadcrumbs, not final proof.
- Latest focused slices include: immediate captured-lambda 4/4 plus 96 adjacent;
  generated-symbol boundaries 56/56; array/GPU capacity 35/35; managed property
  lifetime exact nodes green; 500-term binary inference/validation in 17.17 s
  under the unchanged 30 s contract; GPU output receiver 4/4 plus strict
  GCC/Clang and sanitizer coverage; optional Python focused 7/7 and architecture
  67/67.
- The last static snapshot before the latest correctness batch passed lint,
  format, generated checks, diff checks, lock validation, and portable boundary
  verification. Rerun every static gate on the committed handoff tree.

## Objective

Refactor the Python reference compiler, the self-hosted BTRC compiler, the LSP,
the debugger, and the VS Code extension into cohesive packages built around
real object owners. Eliminate flat namespaces, dangling behavior functions,
partial-class source fragments, duplicate ordinary/generic lowering stacks,
compatibility facades, and source-controlled build output.

Correctness is non-negotiable:

- The six-stage compiler architecture remains lexer, parser, analyzer, IR
  lowering, optimizer, and emitter.
- IR lowering produces structured IR only.
- Runtime helper sources remain pre-authored rather than assembled by the
  emitter.
- The grammar and ASDL schema remain the syntax sources of truth.
- Strict imports remain the default.
- Successful outputs and diagnostics remain bit-identical unless a separately
  documented correctness fix intentionally changes them.
- Both compilers must stay in parity and the self-hosting fixed point must hold.

## Current Baseline

Status recorded on 2026-08-18:

- The architecture-foundation baseline is pinned at commit
  `fce26b8502feb4019784b18cdee27028ec4e3d15`. Correctness hill-climb changes
  compare against that immutable revision.
- The target architecture below has been reviewed and approved as the
  destination.
- The shared runtime foundation is implemented: one validated manifest, nine
  cohesive pre-authored C assets, data-only generated catalogs, and retained
  catalog/selection/reference owners in both compilers.
- The shared hosted-ABI foundation is implemented: one validated TOML schema,
  data-only generated Python and btrc tables, retained query/provenance owners
  in both compilers, and no compatibility layer for the deleted ABI shards.
- The 46 Python `ir/helpers` modules, `ir/gen/helpers.py`, the old runtime
  dependency module, and four root freestanding modules are deleted.
- Thirty-four self-hosted cycle/process/thread/string/IR-runtime shard files
  are deleted. Runtime source visibility now comes only from generated runtime
  metadata; analyzer code no longer imports an IR-stage catalog.
- The self-hosted syntax, lexer, and parser foundations now live under
  `syntax/`, `lexer/`, and `parser/`. Every analyzer/IR consumer uses the new
  identity, type-shape, callable-signature, and literal owners directly; the
  deleted global APIs have no production references or compatibility layer.
- The self-hosted application root now contains only `Compiler`; command-line
  parsing, secure runtime-path resolution, checked output, and process
  orchestration are retained together by `cli/driver.btrc`. The former driver,
  path, and output fragments are deleted.
- The self-hosted frontend now has exactly the six destination files. Source
  models, bounded UTF-8/path I/O, stdlib discovery, dependency resolution, and
  import visibility have distinct retained owners; the former five root
  fragments and parser-to-frontend dependency are deleted.
- The self-hosted generated AST now lives under `generated/ast/`; the native
  ASDL schema, dump, and generation tools live under `tools/ast/`, and the
  lexer, parser, and frontend inspection entry points live under `tools/`.
  `AstCanonicalRenderer` in `syntax/identity.btrc` retains canonical rendering
  behind one public `render` method and private recursive formatting helpers;
  generated `Node` owns schema/data fields and initialization only. Each
  executable has a retained command owner behind a thin `main()`, and the
  former `ast/` and package-root paths are deleted without facades. The former
  standalone AST-verification script and lexer-verification shell program are
  also deleted; canonical AST encoding and raw-byte lexer comparison now belong to
  `tools.compiler_codegen.verification.CompilerBoundaryVerifier` and are
  exposed by the unified tool entry point.
- The Python grammar, token vocabulary, lexer, and parser foundations now live
  under `syntax/`, `lexer/`, and `parser/`. Literal scanning is retained by
  `LiteralScanner`, one stateful `Parser` owns all recursive-descent behavior,
  and the former root modules and parser fragments are deleted without facades.
- Python ASDL processing and dual-language AST generation now belong to the
  retained owners in `tools/compiler_codegen/{asdl,ast}.py`; the generated
  Python model and `AstJsonCodec` live in the exact `syntax/ast/` package. The
  former generator package, root AST modules, and standalone generated-file
  checker are deleted, and the unified generator owns both output artifacts.
- The Python application boundary now has exactly the twelve destination files
  under `application/`, `cli/`, and `frontend/`, plus the two public package
  entry files. `CompilationPipeline` owns stage ordering, frontend resolution
  is split between its retained source/import/package owners, and the former
  root compiler, package, pipeline, and command modules are deleted without
  facades. Frontend and artifacts never import application or one another;
  CLI imports only application owners; application owns narrow structural
  cache/archive/bundle ports; and `main.py` is the sole concrete composition
  point for persistent artifact adapters.
- The Python analyzer now has exactly the sixteen destination files. One
  `SemanticAnalyzer` wires the session/result, declaration, type, aggregate,
  expression, call, statement, flow, storage, ownership, generic, GPU, macro,
  and generated-symbol owners; the former 60-way inheritance braid, 96
  analyzer fragments, and 21 analyzer-owned root semantic modules are deleted
  without facades or module-level behavior.
- Python's top-level IR package now has exactly `__init__.py`, `nodes.py`,
  `verifier.py`, and `optimizer.py`. The model has no dependency on later
  stages, `IRVerifier` owns fail-closed schema/cleanup/derived-order checks,
  and `IROptimizer` owns planning and mutation. `CEmitter` depends only on the
  IR model and verifier; `WgslEmitter` additionally consumes the structured GPU
  shader plan and the earlier syntax/analyzer type-value owners needed to
  render it. The former IR-schema, provenance, walk, reachability,
  declaration-order, topology, completion, and parameter fragments are gone.
- Python's former 198-file `ir/gen/` implementation and all 49 generic-emitter
  copies are deleted. The exact twenty-file `ir/lowering/` destination is
  physically present and ordinary/generic paths share its domain owners. Its
  exact import and retained-owner graphs are acyclic; broad
  `lowerer`/`generator` arguments, legacy `_gen` reach-through, callback bags,
  late binders, dynamic state fallbacks, and service-location seams are zero.
- Python artifact handling now has exactly six modules under `artifacts/` plus
  the thin `cli/bundle.py` command. Archive codecs, caches, publication,
  standard-library archives, and self-host bundles each have retained owners;
  the former root utilities and nested micro-packages are deleted without
  import facades.
- The 64 self-hosted semantic-validation fragments and two adjacent helper
  fragments are deleted. The complete validation domain now consists of the
  eleven retained owners under `analyzer/validation/`; validation run state no
  longer carries semantic services.
- The debugger has been repackaged around protocol, toolchain, LLDB, value
  presentation, and bootstrap owners. Its former flat modules are deleted and
  its tests live under `src/tests/debug/`.
- The LSP now consists of the exact 22-file destination package. Its document,
  resolution, workspace, catalog, protocol, and feature owners form an acyclic
  dependency graph; `BtrcLanguageServer` retains all mutable server state, the
  old compatibility modules are deleted, and tests live under `src/tests/lsp/`.
  Builtin-catalog scanning and rendering are owned by the unified compiler
  generator rather than LSP-local generator fragments.
- The VS Code extension now lives only under `src/devex/vscode/` with retained
  application, launcher, session, process, runtime-probe, and bundler owners.
  The former `ext/` tree and all source-local payloads are deleted; staging and
  compiled output live under `build/devex/vscode/`, with VSIX output reserved
  for `dist/btrc.vsix`.
- Native GPU and GUI object/archive output now lives under
  `build/stdlib/{gpu,gui}`. The former `src/stdlib/*/build` directories,
  package metadata snapshots, `.DS_Store` files, and other source-local native
  artifacts were removed; build and packaging consumers use the repository
  build root.
- Self-hosted source-macro namespace policy and the managed-value/cycle semantic
  owners now live under `analyzer/`; `CycleSemantics` is injected explicitly and
  the misleading `CycleMetadata` API and former package-root paths are deleted.
  `NumericSemantics` and `OperatorSemantics` now share the single analyzer-owned
  `operators.btrc` module that defines their common type/operator domain.
- The remainder of the self-hosted analyzer now has the exact destination tree.
  `SemanticAnalyzer` composes `DeclarationRegistry`, `SemanticTypeSystem`,
  `ExpressionTypeResolver`, and `GenericSpecializer` over semantic value state;
  IR lowering receives those narrow collaborators directly and never retains
  the analyzer composition root. The 21 absorbed root semantic fragments are
  deleted without facades or loose behavior.
- Self-hosted C formatting now lives in `ir/emitter.btrc`; `CEmitter.emit()` is
  its only behavioral API, formatting state/helpers are private, and lowering
  no longer reaches into an emitter-level whitespace global.
- Python backend formatting now lives in the exact three-file `backend/`
  package. One retained `CEmitter` owns translation-unit, archive, debug,
  declaration, statement, expression, preprocessor, and embedded-shader C
  formatting; one retained `WgslEmitter` owns complete kernel assembly, typed
  statement/expression rendering, checked operations, bindings, and type
  mappings. The former emitter mixins and GPU-WGSL shards are deleted without
  facades or loose behavior functions.
- The thirteen self-hosted setjmp fragments are deleted. Pointer provenance,
  call effects, and fixed-point summaries belong to `SetjmpEffectAnalysis`;
  capture, mutation, volatility, qualifier, and control-flow policy belong to
  `SetjmpSafetyPlanner`, under the two-file `ir/optimization/setjmp/` package.
- The self-hosted GPU fragments are deleted. Analyzer-owned builtin and type
  policy belongs to `GpuSemantics`, WGSL rendering belongs to
  `GpuWgslEmitter`, and registration, dispatch, fallback planning, and GPU-only
  reachability belong to `GpuPipeline`; none retains or accepts `IRGen`.
- The typed cleanup-registration invariant owner now lives beside the other IR
  optimization checks in `ir/optimization/cleanup.btrc`; its former root path
  is deleted without a forwarding include.
- The self-hosted structured IR schema now lives only in `ir/model.btrc`.
  `IRNode` and `IRPreprocessorDecl` own their typed constructors, GPU
  translation-unit records are part of the same schema, and the former
  `cleanup_ir.btrc`, `ir_nodes.btrc`, and `ir_top_nodes.btrc` files and loose
  factory functions are gone.
- Self-hosted whole-module reachability and unused-parameter normalization now
  belong to one retained `IROptimizer` in `ir/optimization/optimizer.btrc`;
  GPU reachability is delegated to `GpuPipeline`, and the former global and
  parameter-reachability fragments are deleted.
- The self-hosted compiler now has the exact 88-file destination tree. Raw IR
  construction stops at `IRLowerer`; `CompilerPipeline` invokes the injected
  `HostedAbiRepository`, setjmp/cleanup validation, `IROptimizer`, runtime
  materialization, and `CEmitter` as distinct later stages. `CallTargetResolver`
  centralizes call identity and signatures; `StatementLowerer` owns recursive
  statement traversal; `CallableValueLowerer` owns lifted callable values;
  `OwnershipOperandPlanner` owns operand order; and each emitted body receives
  a fresh `CallableFlowState`. GPU statements cross a typed
  plan/operands/result boundary rather than reaching through expressions.
- This revision is the architecture-foundation checkpoint. Exact destination
  inventories, generated sources, import and retained-owner DAGs, owner-call
  resolution, test collection, build/config parsing, and source-output hygiene
  are structurally green. Correctness, parity, bootstrap, strict-C, and broad
  behavior verification intentionally begin after this checkpoint rather than
  being inferred from structural success.
- The final structural audit covers 81 Python compiler modules, 88 self-hosted
  compiler units, 22 LSP modules, 12 debugger modules, 16 VS Code production
  inputs, 3 language specs, 11 runtime-C inputs, and 8 code-generation modules.
  It resolves every compiler import, parses every self-host unit and all 1,081
  BTRC test/corpus sources, collects 6,927 tests without import errors, and
  leaves no source-local bytecode, cache, native, build, temporary, or dangling
  worktree artifacts.
- At goal start, the self-hosted compiler had 266 tracked `.btrc` files, 249 at
  the package root. Ninety-seven were under 100 lines, and a lexical audit found
  roughly 1,138 probable loose top-level behavior functions in 189 files.
- At goal start, the Python compiler had 499 tracked production `.py` files,
  including 204 IR-lowering modules and 46 runtime-helper modules.
- At goal start, devex had 63 tracked production inputs, plus generated
  extension payloads living incorrectly beneath `src`.
- A subsequent canonical `make test` attempt reached 37 percent with 2,701
  passing and 10 skipped tests before being intentionally stopped. Per the
  user's direction, the destination foundations now take priority over
  repairing or proving the transitional architecture. Broad correctness
  testing is deferred to the final hill-climb phase; structural, generation,
  syntax, and import checks may still be used while constructing foundations.
- Do not rely on temporary `/tmp` compiler binaries or Nix profiles as durable
  state across sessions.

## Non-Negotiable Structural Rules

1. No production behavior at module scope. Module-level constants, enums,
   frozen value records, generated tables, and thin `main()` functions are the
   only exceptions.
2. No pseudo-namespace classes containing unrelated static methods.
3. No partial classes assembled through textual `.btrc` includes.
4. No compatibility facades, wildcard re-exports, forwarding files, `utils`,
   or generic `helpers` modules.
5. Every implementation file contains a complete owner or a tightly coupled
   group of domain value types.
6. Package manifests contain imports only and expose a small intentional API.
7. Only public APIs, generated data, documentation, and thin executable entry
   points may live at package roots.
8. Ordinary and generic lowering use the same lowerers. There is no second
   generic compiler.
9. Runtime C and hosted ABI declarations have shared sources of truth and are
   generated into language-specific representations.
10. File size is never a reason to split a cohesive owner. Independent state,
    invariants, or change reasons are.
11. Old paths are removed atomically. Do not leave import shims after a move.
12. Internal code imports the concrete owner it needs; package APIs must not
    conceal dependency direction.
13. State/context objects may carry mutable compilation state, but may not
    become service locators.
14. Collaborators receive narrow, explicit dependencies and may not retain a
    composition root such as `IRGen` or `SemanticAnalyzer`.
15. Generated files contain data/schema declarations only. Hand-written
    behavior lives in retained owners.

## Dependency Direction

```text
syntax -> lexer/parser -> frontend -> analyzer -> ir.lowering
                                              -> ir.optimizer -> backend
                                  \-> abi/runtime

application -> pipeline and stage composition
cli -> application boundary only
main -> application + cli + concrete artifact adapters
artifacts -> sibling persistence/storage owners only
devex -> public compiler/frontend APIs, never compiler internals by facade
```

Dependencies may point inward or leftward in this diagram, never back toward a
composition root or a later pipeline stage.

Application owns the narrow cache, stdlib-archive, and self-host-bundle port
contracts. The library defaults are explicit disabled adapters; `main.py` is
the concrete process composition root that injects `CompilerCache`,
`StdlibArtifactRepository`, `SelfhostBundleBuilder`, and their shared
toolchain fingerprint. Application and artifacts do not import each other:
the concrete artifact owners satisfy the application ports structurally.

## Destination: Self-Hosted Compiler

The destination contains exactly 88 `.btrc` files: 82 compiler/generated files
and six explicit developer-tool files. Only the public compiler API and process
entry point remain at the root.

```text
src/compiler/btrc/
  README.md
  btrcc_main.btrc                 # thin main()
  compiler.btrc                   # public Compiler application object

  cli/
    driver.btrc                   # BtrccDriver, command line, paths, output

  pipeline/
    stage.btrc                    # public package manifest
    models.btrc                   # mutable options/results
    pipeline.btrc                 # CompilerPipeline

  syntax/
    grammar.btrc                  # GrammarInfo, EBNF parser
    tokens.btrc                   # Token and token vocabulary
    identity.btrc                 # AstIdentity, AstCanonicalRenderer, TypeIdentity
    types.btrc                    # TypeShape, callable signatures
    literals.btrc                 # source/C literal model

  generated/
    ast/
      node.btrc                   # ASDL-generated Node data/schema only
    hosted_abi/
      README.md
      tables.btrc                 # generated hosted ABI declarations
    runtime/
      catalog.btrc                # generated runtime-helper specifications

  lexer/
    stage.btrc                    # public package manifest
    lexer.btrc                    # Lexer and owned literal scanner

  frontend/
    stage.btrc                    # public package manifest
    models.btrc                   # source/dependency value types
    source_io.btrc                # bounded UTF-8 filesystem owner
    stdlib.btrc                   # FeStdlibRepository
    resolver.btrc                 # FeFrontendResolver
    visibility.btrc               # ImportVisibilityChecker

  parser/
    stage.btrc                    # public package manifest
    parser.btrc                   # complete stateful Parser
    source_macros.btrc            # SourceMacroDefinition

  analyzer/
    stage.btrc                    # public package manifest
    analyzer.btrc                 # SemanticAnalyzer composition root
    models.btrc                   # AnalyzedProgram and semantic indexes
    declarations.btrc             # DeclarationRegistry
    types.btrc                    # SemanticTypeSystem
    expressions.btrc              # ExpressionTypeResolver/private memo state
    generics.btrc                 # GenericSpecializer
    operators.btrc                # NumericSemantics, OperatorSemantics
    hosted_abi.btrc               # HostedAbiRepository/provenance
    source_macros.btrc            # SourceMacroNamespace
    gpu.btrc                      # GPU semantic owners

    ownership/
      values.btrc                 # ManagedValueSemantics
      cycles.btrc                 # CycleSemantics

    validation/
      validator.btrc              # SemanticValidator composition
      types.btrc                  # TypeValidator
      constants.btrc              # ConstantValidator
      names.btrc                  # NameValidator
      storage.btrc                # StorageValidator
      ownership.btrc              # OwnershipValidator
      borrows.btrc                # BorrowValidator
      calls.btrc                  # CallValidator
      expressions.btrc            # ExpressionValidator
      control_flow.btrc           # ControlFlowValidator
      declarations.btrc           # DeclarationValidator

  ir/
    stage.btrc                    # public IR package manifest
    model.btrc                    # complete structured IR model
    emitter.btrc                  # CEmitter only

    runtime/
      catalog.btrc                # RuntimeHelperCatalog/registry
      references.btrc             # RuntimeReferenceCollector

    lowering/
      context.btrc                # LoweringContext
      lowerer.btrc                # IRLowerer composition root
      types.btrc                  # CTypeLowerer
      declarations.btrc           # DeclarationLowerer
      generics.btrc               # specialization planning only
      functions.btrc              # FunctionLowerer
      statements.btrc             # recursive StatementLowerer
      control_flow.btrc           # plans, IRStatementSequence, ControlFlowLowerer
      expressions.btrc             # ExpressionLowerer
      calls.btrc                   # CallLowerer, CallTargetResolver
      callables.btrc               # CallableValueLowerer
      callable_flow.btrc           # CallableFlowState
      assignments.btrc             # AssignmentLowerer
      aggregates.btrc              # AggregateValueLowerer
      strings.btrc                 # StringLowerer
      concurrency.btrc             # ConcurrencyLowerer

      ownership/
        semantics.btrc             # lowering ownership classification
        operands.btrc              # OwnershipOperandPlanner
        calls.btrc                 # CallOwnershipLowerer
        lifetime.btrc              # ManagedLifetimeLowerer
        managed_types.btrc         # ManagedTypeLowerer
        cycle_boundaries.btrc      # CycleBoundaryLowerer

    gpu/
      wgsl.btrc                    # GpuWgslEmitter
      pipeline.btrc                # GPU lowering/dispatch/optimization

    optimization/
      optimizer.btrc               # IROptimizer and reachability
      cleanup.btrc                 # CleanupSlotValidator
      setjmp/
        analysis.btrc              # SetjmpEffectAnalysis
        safety.btrc                # SetjmpSafetyPlanner

  tools/
    frontend_main.btrc             # frontend inspection executable
    lex_main.btrc                  # lexer inspection executable
    parse_main.btrc                # parser inspection executable
    ast/
      schema.btrc                  # ASDL schema model
      dump_main.btrc               # ASDL dump executable
      generate_main.btrc           # AST generator executable
```

### Required Self-Hosted Consolidations

- All 18 `cycle_runtime_*` files disappear. Their exact C bodies and dependency
  metadata come from the shared runtime package.
- `CycleRuntimeSourceCatalog` and `CycleRuntimeDependencyCatalog` disappear.
- The 64 `semantic_validation_*` fragments become the 11 stateful validators
  shown above.
- The 13 `setjmp_*` fragments become `analysis.btrc` and `safety.btrc`.
- The 17 `gpu_*` files become analyzer GPU semantics plus the two IR GPU owners.
- The five `process_runtime*` files and six `thread_runtime*` files cease being
  compiler-source fragments.
- `irgen.btrc` is dismantled into `IRLowerer`, `LoweringContext`, and the
  explicit lowerers above.
- `fe_debug.btrc` and `fe_debug2.btrc` are deleted.
- `verify_ast.py` and `verify_lex.sh` move into the shared verification tool.
- No `.btrc` source is textually included inside a class body.

The exact current cycle-runtime files removed are:

```text
cycle_runtime_abandon.btrc
cycle_runtime_abandon_queue.btrc
cycle_runtime_boundaries.btrc
cycle_runtime_collector_prefix.btrc
cycle_runtime_collector_suffix.btrc
cycle_runtime_dependencies.btrc
cycle_runtime_dependencies_lifecycle.btrc
cycle_runtime_dependencies_state.btrc
cycle_runtime_drain.btrc
cycle_runtime_helpers.btrc
cycle_runtime_incoming.btrc
cycle_runtime_lifecycle.btrc
cycle_runtime_lock.btrc
cycle_runtime_release.btrc
cycle_runtime_retain.btrc
cycle_runtime_snapshot.btrc
cycle_runtime_sources.btrc
cycle_runtime_state.btrc
```

## Destination: Python Compiler

The 499 tracked Python compiler files collapse to exactly 81 production Python
files.

```text
src/compiler/python/
  __init__.py                     # Compiler/Options/Result API only
  main.py                         # thin process entry point

  application/
    __init__.py
    compiler.py                   # Compiler
    pipeline.py                   # CompilationPipeline
    results.py                    # immutable cross-stage results

  cli/
    __init__.py
    compiler.py                   # CompilerCommand
    bundle.py                     # BundleCommand

  syntax/
    __init__.py
    grammar.py                    # GrammarRepository, EbnfGrammarParser
    tokens.py                     # Token, TokenKind, TokenVocabulary
    ast/
      __init__.py
      generated.py                # generated ASDL dataclasses
      codec.py                    # AstJsonCodec

  lexer/
    __init__.py
    lexer.py                      # Lexer and LiteralScanner

  parser/
    __init__.py
    parser.py                     # complete stateful Parser

  frontend/
    __init__.py
    stage.py                      # frontend composition
    sources.py                    # SourceResolver/dependency graph
    imports.py                    # ImportResolver/visibility
    packages.py                   # PackageUniverse/GitDependencyCache

  analyzer/
    __init__.py
    analyzer.py                   # SemanticAnalyzer composition root
    program.py                    # AnalyzedProgram/scopes/indexes
    declarations.py              # DeclarationRegistry
    types.py                     # TypeSystem
    aggregates.py                # AggregateAnalyzer
    expressions.py               # ExpressionAnalyzer
    calls.py                     # CallAnalyzer/callable flow
    statements.py                # StatementAnalyzer
    flow.py                      # ControlFlowAnalyzer
    storage.py                   # StorageModel
    ownership.py                 # OwnershipAnalyzer
    generics.py                  # GenericAnalyzer
    gpu.py                       # GpuAnalyzer
    macros.py                    # SourceMacroAnalyzer/Namespace
    generated_symbols.py         # GeneratedSymbolRegistry

  abi/
    __init__.py
    generated.py                  # generated hosted-ABI data
    declarations.py              # hosted ABI value declarations
    hosted.py                    # HostedAbiRepository
    freestanding.py              # FreestandingRuntime

  ir/
    __init__.py
    nodes.py                     # complete typed IR model/IRModule
    verifier.py                  # IRVerifier
    optimizer.py                 # IROptimizer

    lowering/
      __init__.py
      lowerer.py                 # IRLowerer composition root
      session.py                 # LoweringSession/scopes/temporaries
      translation_unit.py        # TranslationUnitLowerer
      declarations.py            # DeclarationLowerer
      classes.py                 # ClassLowerer
      functions.py               # FunctionLowerer
      types.py                   # CTypeLowerer
      expressions.py             # ExpressionLowerer
      calls.py                   # CallLowerer
      storage.py                 # StorageLowerer
      ownership.py               # OwnershipLowerer
      statements.py              # StatementLowerer
      control_flow.py            # ControlFlowLowerer
      collections.py             # CollectionLowerer
      iteration.py               # IterationLowerer
      exceptions.py              # ExceptionLowerer/setjmp analysis
      concurrency.py             # ConcurrencyLowerer
      generics.py                # GenericSpecializer only
      gpu.py                     # GpuLowerer

  backend/
    __init__.py
    c_emitter.py                 # CEmitter
    wgsl_emitter.py              # WgslEmitter

  runtime/
    __init__.py
    catalog.py                   # RuntimeHelperCatalog
    generated.py                 # generated runtime-helper data

  artifacts/
    __init__.py
    archive.py                   # ArchiveCodec/validation
    cache.py                     # CompilerCache
    publication.py               # ArtifactPublisher
    stdlib.py                    # StdlibArtifactRepository
    selfhost.py                  # SelfhostBundleBuilder
```

### Required Python Consolidations

- All 14 parser mixin files become one `Parser`.
- The analyzer's roughly 101 files become 15 retained collaborators rather
  than a large inheritance braid.
- The 204 IR-generation files collapse into the 19 lowering owners plus
  composition and session modules.
- All 49 generic-emitter files disappear. `GenericSpecializer` supplies type
  substitutions to the ordinary lowerers.
- The 46 Python runtime-helper source modules disappear.
- The hosted-ABI fragments become a shared declaration source and three ABI
  owners.
- All emitter mixins become one `CEmitter`.
- Root archive, publication, cache, package, ABI, and bundle files move into
  their named packages.
- No module-level executable compiler behavior remains.

Generic specialization must produce a `TypeSubstitution` and specialized
declaration view, then invoke the same `ClassLowerer`, `StatementLowerer`,
`ExpressionLowerer`, `CallLowerer`, `StorageLowerer`, and `OwnershipLowerer`
used by ordinary code. `_UserGenericEmitter` and its domain copies are deleted.

## Destination: Shared Specifications and Runtime

```text
src/language/
  grammar.ebnf
  ast.asdl
  hosted_abi.toml

src/runtime/c/
  manifest.toml
  btrc_rt.h
  core.c
  collections.c
  cycles.c
  mutex.c
  process.c
  strings.c
  threads.c
  trycatch.c
  gpu.c

tools/compiler_codegen/
  __init__.py
  main.py
  asdl.py
  ast.py
  builtins.py
  hosted_abi.py
  runtime.py
  verification.py
```

`manifest.toml` owns helper names, dependencies, headers, feature flags, source
markers, and a dense deterministic order for each compiler catalog. Python
retains dependency-first DFS materialization; self-hosting retains dependency
closure followed by its catalog order. The C files contain cohesive named
sections, not one file per helper.

`hosted_abi.toml` owns exact function signatures and effects, complete owned
and native name sets, macros, objects, types, typedefs, platform subsets,
runtime-adopting metadata, and provenance markers. The generator validates the
set relationships and runtime references before emitting data rows; each
compiler retains indexing, alias recognition, source stamping, and ownership
queries in its handwritten ABI repository.

The generator produces exactly these compiler/devex data files:

```text
src/compiler/python/runtime/generated.py
src/compiler/btrc/generated/runtime/catalog.btrc
src/compiler/python/syntax/ast/generated.py
src/compiler/btrc/generated/ast/node.btrc
src/compiler/python/abi/generated.py
src/compiler/btrc/generated/hosted_abi/tables.btrc
src/devex/lsp/catalog/generated.py
```

Generated modules contain data/schema declarations only. Generated Python rows
use immutable value types; generated btrc rows expose public fields required by
the language and consumers treat them as read-only by convention. Stateful
repositories and catalogs own all querying, validation, indexing, and
selection behavior. `AstCanonicalRenderer` in handwritten
`syntax/identity.btrc` owns canonical AST formatting; generated `Node` owns no
formatting behavior. The unified generator check structurally verifies that
the handwritten renderer covers every ASDL constructor and field.

## Destination: Developer Experience

```text
src/devex/
  __init__.py

  lsp/
    __init__.py
    __main__.py

    protocol/
      __init__.py
      server.py                   # BtrcLanguageServer

    analysis/
      __init__.py
      document.py                 # DocumentAnalysis/Analyzer/Text
      resolution.py               # SemanticResolver/LexicalScopeIndex

    catalog/
      __init__.py
      builtins.py                 # BuiltinCatalog
      generated.py                # generated builtin data only

    workspace/
      __init__.py
      units.py                    # FileUnit/dependency model
      cache.py                    # Workspace/Unit/Package caches
      workspace.py                # Workspace composition owner

    features/
      __init__.py
      completion.py               # CompletionProvider
      signature_help.py           # SignatureHelpProvider
      navigation.py               # NavigationProvider/indexes
      hover.py                    # HoverProvider
      semantic_tokens.py          # SemanticTokenProvider
      symbols.py                  # SymbolProvider
      code_actions.py             # CodeActionProvider

  debug/
    __init__.py
    __main__.py

    protocol/
      __init__.py
      adapter.py                  # BtrcDebugAdapter/ProcessEventLoop
      transport.py                # DapReader/DapWriter

    toolchain/
      __init__.py
      build.py                    # LaunchConfig/ProgramBuilder/Artifact

    backend/
      __init__.py
      lldb.py                     # LldbSession/LLDB translations
      values.py                   # BtrcValuePresenter

    runtime/
      __init__.py
      bootstrap.py                # LldbBootstrap

  vscode/
    .vscodeignore
    package.json
    package-lock.json
    tsconfig.json

    assets/
      btrc.png

    config/
      language.json
      grammar.json

    src/
      extension.ts               # thin activate/deactivate entry point

      application/
        controller.ts            # ExtensionController

      language_server/
        launcher.ts              # LanguageServerLaunchResolver
        session.ts               # LanguageServerSession

      debugger/
        launcher.ts              # DebugLaunchResolver/provider/factory

      runtime/
        process.ts               # HostRuntime/ProcessTree
        python.ts                # PythonRuntimeProbe

    packaging/
      bundle.py                  # ExtensionBundler
      prepare.js                 # thin packaging entry point
```

### Required Devex Consolidations

- `utils.py`, `server_state.py`, and the LSP compatibility/import cycle
  disappear.
- Completion's three modules become one provider.
- Definition, occurrences, highlights, references, and reference finders become
  one navigation owner.
- Signature context, items, and help become one provider.
- Workspace and unit caches become retained cache objects.
- All ambient mutable LSP state moves onto `BtrcLanguageServer`.
- Debug adapter mixins and translation globals move onto their adapter/session
  owners.
- `src/devex/ext` becomes `src/devex/vscode`.
- `requirements.txt` and the duplicate extension `LICENSE` disappear.
- The bundled debugger uses package imports and launches with
  `python -m src.devex.debug`.

Build payloads live outside source control:

```text
build/devex/vscode/
dist/btrc.vsix
```

`node_modules`, `out`, bundled server/debugger payloads, VSIX output,
`__pycache__`, and pytest caches must not exist beneath `src`.

## Migration Order

- [x] Freeze and approve the destination architecture.
- [x] Introduce the shared runtime specification and cohesive C assets.
- [x] Generate both language-specific runtime catalogs and prove exact byte,
      dependency, header, and ordering parity.
- [x] Introduce the shared hosted-ABI specification and generated repositories.
- [x] Delete the Python runtime-helper module shards and route consumers through
      `RuntimeHelperCatalog`, `RuntimeHelperSelection`, and
      `FreestandingRuntime`.
- [x] Collapse self-hosted cycle, process, thread, and try/catch runtime shards.
- [x] Move the self-hosted flat root into the destination packages without
      compatibility shims.
- [x] Replace self-hosted validation globals with the 11 validator owners.
- [x] Replace `IRGen` service-location with `IRLowerer`, `LoweringContext`, and
      explicit domain lowerers.
- [x] Consolidate the Python syntax, parser, frontend, analyzer, ABI, artifact,
      and backend packages.
- [x] Unify ordinary and generic Python lowering and delete the generic emitter
      copy.
- [x] Repackage the LSP around `BtrcLanguageServer`, `DocumentAnalyzer`,
      `SemanticResolver`, and feature providers.
- [x] Repackage the debugger around retained protocol, toolchain, backend, and
      bootstrap owners.
- [x] Repackage the VS Code extension and redirect generated output to
      `build/` and `dist/`.
- [x] Delete every obsolete production path and update build, CI, docs,
      generators, source fingerprints, and structure tests.
- [x] Establish frozen compiler outputs for tokens, AST, IR, optimized IR, C,
      diagnostics, and runtime helper specifications from the completed
      destination architecture.
- [ ] Complete all bit-perfect comparisons and the full verification matrix.
- [x] Perform a final loose-function, import-cycle, package-root, generated-file,
      and source-output audit.

## Slice Rules

Every migration slice must:

1. Name the real owner and its state/invariants before moving behavior.
2. Move a complete dependency-connected domain, not a convenient line range.
3. Delete old files in the same slice; never leave temporary facades.
4. Preserve the exact runtime helper bytes, dependency vectors, header vectors,
   and each compiler's deterministic materialization order where applicable.
5. During the current architecture-first phase, record structural invariants
   in this contract and use generation, import, parse/transpile, and
   `git diff --check` checks only. Do not spend time repairing transitional
   correctness failures or running behavior/parity suites.
6. After the destination tree is complete, add the structural regression
   checks and hill-climb through focused behavior/parity tests before the broad
   suite and bit-perfect gates.
7. Keep generated sources fresh and the changed architecture mechanically
   loadable before checkpointing; final lint/format enforcement belongs to the
   hill-climb phase.
8. Update this document's progress checklist and current-state breadcrumbs.

## Correctness and Completion Gates

After the destination architecture checkpoint is committed and pinned as the
baseline revision, compare that frozen compiler and each correctness-hill-climb
revision at every available boundary:

- token stream
- canonical AST
- raw structured IR
- optimized structured IR
- emitted C bytes
- diagnostics and exit status
- runtime helper source bytes
- runtime helper dependency/header/order metadata
- GCC and Clang runtime behavior
- Python compiler versus self-hosted compiler

The final tree must pass:

```text
make test
make bootstrap
make test-c11
make lint
make format-check
make extension
```

It must additionally pass:

- generated-source verification
- strict-import corpus through both compilers
- bootstrap fixed-point byte comparison
- runtime helper manifest/catalog parity
- LSP unit and stdio end-to-end tests
- debugger/DAP tests
- VS Code extension unit, packaging, manifest, and asset tests
- a repository audit proving there are no obsolete paths, compatibility shims,
  partial-class includes, unauthorized root files, or module-level production
  behavior functions

No failure may be labeled pre-existing. The goal remains incomplete until the
entire matrix is green.
