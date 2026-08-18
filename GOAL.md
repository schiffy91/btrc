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
5. Establish the smallest relevant behavioral baseline before editing.

Before ending a session:

1. Leave the tree in a verified state or record the exact unfinished state.
2. Update the progress checklist and breadcrumbs in this file.
3. Commit coherent, working checkpoints frequently.
4. Never weaken an invariant or add a compatibility shim to save time.

This goal is not complete until the destination trees exist, obsolete paths are
gone, both compilers are behaviorally and byte-for-byte verified, the complete
test matrix passes, and the devex artifacts build successfully.

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

- The target architecture below has been reviewed and approved as the
  destination.
- No destination-tree migration has been implemented yet.
- The working tree contains a large uncommitted ownership/correctness slice
  from the preceding refactor. Preserve and migrate that work; do not discard
  it or mistake it for the finished architecture.
- The self-hosted compiler currently has 266 tracked `.btrc` files, 249 at the
  package root. Ninety-seven are under 100 lines. A lexical audit found roughly
  1,138 probable loose top-level behavior functions in 189 files.
- The Python compiler currently has 499 tracked production `.py` files,
  including 204 IR-lowering modules and 46 runtime-helper modules.
- Devex currently has 63 tracked production inputs, plus generated extension
  payloads living incorrectly beneath `src`.
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
cli/artifacts -> application boundary only
devex -> public compiler/frontend APIs, never compiler internals by facade
```

Dependencies may point inward or leftward in this diagram, never back toward a
composition root or a later pipeline stage.

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
    models.btrc                   # immutable options/results
    pipeline.btrc                 # CompilerPipeline

  syntax/
    grammar.btrc                  # GrammarInfo, EBNF parser
    tokens.btrc                   # Token and token vocabulary
    identity.btrc                 # AstIdentity, TypeIdentity
    types.btrc                    # TypeShape, callable signatures
    literals.btrc                 # source/C literal model

  generated/
    ast/
      node.btrc                   # ASDL-generated AST
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
    models.btrc                   # AnalyzedProgram, indexes, memo state
    declarations.btrc             # DeclarationRegistry
    types.btrc                    # SemanticTypeSystem
    expressions.btrc              # ExpressionTypeResolver
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
      statements.btrc             # StatementLowerer, IRStatementSequence
      control_flow.btrc            # ControlFlowLowerer
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

The 499 tracked Python compiler files collapse to exactly 80 production Python
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
    types.py                     # TypeSystem/TypeInference
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
    generated.py                 # generated immutable helper specs

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
markers, and deterministic emission order. The C files contain cohesive named
sections, not one file per helper.

The generator produces exactly these compiler/devex data files:

```text
src/compiler/python/runtime/generated.py
src/compiler/btrc/generated/runtime/catalog.btrc
src/compiler/python/syntax/ast/generated.py
src/compiler/btrc/generated/ast/node.btrc
src/compiler/btrc/generated/hosted_abi/tables.btrc
src/devex/lsp/catalog/generated.py
```

Generated modules contain data only. Stateful repositories and catalogs own
all querying, validation, indexing, and selection behavior.

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
- [ ] Introduce the shared hosted-ABI and runtime specifications.
- [ ] Generate both language-specific runtime catalogs and prove exact byte,
      dependency, header, and ordering parity.
- [ ] Collapse self-hosted cycle, process, thread, and try/catch runtime shards.
- [ ] Move the self-hosted flat root into the destination packages without
      compatibility shims.
- [ ] Replace self-hosted validation globals with the 11 validator owners.
- [ ] Replace `IRGen` service-location with `IRLowerer`, `LoweringContext`, and
      explicit domain lowerers.
- [ ] Consolidate the Python syntax, parser, frontend, analyzer, ABI, artifact,
      and backend packages.
- [ ] Unify ordinary and generic Python lowering and delete the generic emitter
      copy.
- [ ] Repackage the LSP around `BtrcLanguageServer`, `DocumentAnalyzer`,
      `SemanticResolver`, and feature providers.
- [ ] Repackage the debugger and VS Code extension; redirect generated output
      to `build/` and `dist/`.
- [ ] Delete every obsolete production path and update build, CI, docs,
      generators, source fingerprints, and structure tests.
- [ ] Establish frozen compiler outputs for tokens, AST, IR, optimized IR, C,
      diagnostics, and runtime helper specifications from the completed
      destination architecture.
- [ ] Complete all bit-perfect comparisons and the full verification matrix.
- [ ] Perform a final loose-function, import-cycle, package-root, generated-file,
      and source-output audit.

## Slice Rules

Every migration slice must:

1. Name the real owner and its state/invariants before moving behavior.
2. Move a complete dependency-connected domain, not a convenient line range.
3. Delete old files in the same slice; never leave temporary facades.
4. Preserve the exact runtime helper bytes, dependency vectors, header vectors,
   and deterministic order where applicable.
5. Add or strengthen structural tests so the old fragmentation cannot return.
6. Run focused behavior/parity tests before a broad suite.
7. Pass lint, formatting, and `git diff --check` before checkpointing.
8. Update this document's progress checklist and current-state breadcrumbs.

## Correctness and Completion Gates

For compiler-affecting structural changes, compare the frozen pre-refactor and
new compilers at each available boundary:

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
