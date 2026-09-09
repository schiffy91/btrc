# Compiler Structure

Status: **active architecture contract**.

This document records the ownership-driven destination shared by the Python
reference compiler, the self-hosted compiler, and developer tooling. The
normative inventory is exactly 82 production Python compiler files and 91
self-hosted `.btrc` files. File size is a review signal, not a boundary:
independent state, invariants, and change reasons justify a separate owner.

## Architectural invariants

1. `src/language/grammar.ebnf`, `src/language/ast.asdl`, and
   `src/language/hosted_abi.toml` remain shared sources of truth.
2. Both compilers retain lexer, parser, analyzer, structured IR lowering,
   optimizer, and C-emitter stages.
3. IR lowering produces structured nodes. Emitters only format those nodes.
4. Production behavior belongs to a meaningful stage or domain owner. Module
   scope is limited to constants, enums, value/schema declarations, generated
   data, and thin process entry points.
5. Package manifests contain imports only. Internal consumers import concrete
   owners; wildcard facades and forwarding compatibility modules are forbidden.
6. Mutable context objects carry run state, not catalogs or service objects.
   Collaborators receive narrow dependencies and never retain a composition root.
7. Ordinary and generic lowering use the same domain lowerers. Specialization
   supplies immutable substitutions and declaration views.
8. Strict imports are the default in APIs, CLIs, bootstrap, examples, and tests.
9. Generated C remains warning-free strict C11, and final compiler output,
   diagnostics, runtime metadata, and bootstrap results remain bit-perfect.

The dependency direction is:

```text
syntax -> lexer/parser -> frontend -> analyzer -> ir.lowering
                                              -> ir.optimizer -> backend
                                  \-> abi/runtime

application -> pipeline and stage composition
cli -> application boundary only
main -> application + cli + concrete artifact adapters
artifacts -> sibling persistence/storage owners only
devex -> public compiler/frontend APIs
```

Dependencies point inward or leftward, never back to a composition root or
later pipeline stage.

Application owns narrow cache, stdlib-archive, and self-host-bundle port
contracts plus explicit disabled library defaults. `main.py` is the concrete
process composition root: it injects `CompilerCache`,
`StdlibArtifactRepository`, `SelfhostBundleBuilder`, and the shared toolchain
fingerprint. Application and artifacts have no import edge in either
direction; concrete artifact owners satisfy the application ports
structurally.

## Object ownership

The Python `Compiler` owns one `CompilationPipeline`; the self-hosted
`Compiler` owns the corresponding `CompilerPipeline`. Each composes retained
stage owners:

```text
Compiler
  CompilationPipeline / CompilerPipeline
    FrontendStage
      SourceResolver -> ResolvedSource(text, provenance, dependency graph)
      Lexer
      Parser
    SemanticAnalyzer
    IRLowerer
    IROptimizer
    CEmitter
```

`CompilationPipeline` also owns `StdlibArchiveAdapter`, which performs all
compiler-stage transformation and partitioning for a stdlib archive. The
artifact repository receives and returns plain archive values and owns only
authentication, serialization, storage, and publication.

`LoweringSession` and `LoweringContext` contain only mutable facts, scopes,
counters, temporaries, and deferred plans for one run. Call, storage,
ownership, expression, and statement owners exchange narrow plans or callbacks
instead of retaining the lowerer composition root. Generic specialization
returns immutable substitutions and invokes the ordinary lowerers.

`CallableProvenance` belongs to exactly one emitted function body. It owns
callable types, managed-return ABI tags, lifted closure environments, lexical
scopes, and control-flow snapshots as one typed binding model. There is no
ambient fallback tracker or resettable global map.

`SourceMacroNamespace` owns the immutable macro-definition view for one
analysis run; the declaration owner alone applies effects to produce successor
namespaces.

## Exact Python destination

The Python compiler contains exactly 82 production `.py` files:

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
    realtime.py                  # RealtimeAnalyzer/fixed-point effect proof

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

## Exact self-hosted destination

The self-hosted compiler contains exactly 91 `.btrc` files: 85
compiler/generated files and six explicit developer-tool files. Only the
public compiler application object and thin process entry point remain at the
package root:

```text
src/compiler/btrc/
  README.md
  BtrccMain.btrc                 # thin main()
  Compiler.btrc                   # public Compiler application object

  cli/
    Driver.btrc                   # BtrccDriver, command line, paths, output

  pipeline/
    Stage.btrc                    # public package manifest
    Models.btrc                   # mutable options/results
    Pipeline.btrc                 # CompilerPipeline

  syntax/
    Grammar.btrc                  # GrammarInfo, EBNF parser
    Tokens.btrc                   # Token and token vocabulary
    Identity.btrc                 # AstIdentity, AstCanonicalRenderer, TypeIdentity
    Types.btrc                    # TypeShape, callable signatures
    Literals.btrc                 # source/C literal model

  generated/
    ast/
      Node.btrc                   # ASDL-generated Node data/schema only
    hosted_abi/
      README.md
      Tables.btrc                 # generated hosted ABI declarations
    runtime/
      Catalog.btrc                # generated runtime-helper specifications

  lexer/
    Stage.btrc                    # public package manifest
    Lexer.btrc                    # Lexer and owned literal scanner

  frontend/
    Stage.btrc                    # public package manifest
    Models.btrc                   # source/dependency value types
    Packages.btrc                 # recursive packages, locks, native plans
    SourceIo.btrc                # bounded UTF-8 filesystem owner
    Stdlib.btrc                   # FeStdlibRepository
    Resolver.btrc                 # FeFrontendResolver
    Visibility.btrc               # ImportVisibilityChecker

  parser/
    Stage.btrc                    # public package manifest
    Parser.btrc                   # complete stateful Parser
    SourceMacros.btrc            # SourceMacroDefinition

  analyzer/
    Stage.btrc                    # public package manifest
    Analyzer.btrc                 # SemanticAnalyzer composition root
    Models.btrc                   # AnalyzedProgram and semantic indexes
    Declarations.btrc             # DeclarationRegistry
    Types.btrc                    # SemanticTypeSystem
    Expressions.btrc              # ExpressionTypeResolver/private memo state
    Generics.btrc                 # GenericSpecializer
    Operators.btrc                # NumericSemantics, OperatorSemantics
    HostedAbi.btrc               # HostedAbiRepository/provenance
    SourceMacros.btrc            # SourceMacroNamespace
    Gpu.btrc                      # GPU semantic owners
    Realtime.btrc                 # transitive realtime-effect proof

    ownership/
      Values.btrc                 # ManagedValueSemantics
      Cycles.btrc                 # CycleSemantics

    validation/
      Validator.btrc              # SemanticValidator composition
      Types.btrc                  # TypeValidator
      Constants.btrc              # ConstantValidator
      Names.btrc                  # NameValidator
      Storage.btrc                # StorageValidator
      Ownership.btrc              # OwnershipValidator
      Borrows.btrc                # BorrowValidator
      Calls.btrc                  # CallValidator
      Expressions.btrc            # ExpressionValidator
      ControlFlow.btrc           # ControlFlowValidator
      Declarations.btrc           # DeclarationValidator

  ir/
    Stage.btrc                    # public IR package manifest
    Model.btrc                    # complete structured IR model
    Emitter.btrc                  # CEmitter only

    runtime/
      Catalog.btrc                # RuntimeHelperCatalog/registry
      References.btrc             # RuntimeReferenceCollector

    lowering/
      Context.btrc                # LoweringContext
      Lowerer.btrc                # IRLowerer composition root
      Types.btrc                  # CTypeLowerer
      Declarations.btrc           # DeclarationLowerer
      Generics.btrc               # specialization planning only
      Functions.btrc              # FunctionLowerer
      Statements.btrc             # StatementLowerer
      ControlFlow.btrc            # IRStatementSequence, ControlFlowLowerer
      Expressions.btrc             # ExpressionLowerer
      Calls.btrc                   # CallLowerer, CallTargetResolver
      Callables.btrc               # CallableValueLowerer
      CallableFlow.btrc           # CallableFlowState
      Assignments.btrc             # AssignmentLowerer
      Aggregates.btrc              # AggregateValueLowerer
      Strings.btrc                 # StringLowerer
      Concurrency.btrc             # ConcurrencyLowerer

      ownership/
        Semantics.btrc             # lowering ownership classification
        Operands.btrc              # OwnershipOperandPlanner
        Calls.btrc                 # CallOwnershipLowerer
        Lifetime.btrc              # ManagedLifetimeLowerer
        ManagedTypes.btrc         # ManagedTypeLowerer
        CycleBoundaries.btrc      # CycleBoundaryLowerer

    gpu/
      Wgsl.btrc                    # GpuWgslEmitter
      Pipeline.btrc                # GPU lowering/dispatch/optimization

    optimization/
      Optimizer.btrc               # IROptimizer and reachability
      Cleanup.btrc                 # CleanupSlotValidator
      Realtime.btrc                # structured-IR realtime backstop
      setjmp/
        Analysis.btrc              # SetjmpEffectAnalysis
        Safety.btrc                # SetjmpSafetyPlanner

  tools/
    FrontendMain.btrc             # frontend inspection executable
    LexMain.btrc                  # lexer inspection executable
    ParseMain.btrc                # parser inspection executable
    ast/
      Schema.btrc                  # ASDL schema model
      DumpMain.btrc               # ASDL dump executable
      GenerateMain.btrc           # AST generator executable
```

`pipeline/Models.btrc` contains mutable option and result transports for one
compilation. Analyzer indexes and shared semantic records belong to
`analyzer/Models.btrc`, while expression-type memo state belongs privately to
`ExpressionTypeResolver` in `analyzer/Expressions.btrc`.
`IRStatementSequence` is a control-flow plan and therefore belongs to
`ir/lowering/ControlFlow.btrc`. `AstCanonicalRenderer` in handwritten
`syntax/Identity.btrc` owns canonical AST formatting; the parse inspection
tool calls that owner, and generated `Node` owns no formatting behavior.
The unified generator check structurally verifies that the handwritten
renderer covers every ASDL constructor and field.

Self-host directories improve ownership and navigation but do not create a
language namespace. Public class names therefore remain globally unique, and
each stage manifest records an intentional import order without owning behavior.

## Shared specifications and runtime

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

`src/runtime/c/manifest.toml` owns helper names, dependencies, headers,
realtime-effect summaries, feature flags, source markers, and deterministic catalog order. Its nine
cohesive pre-authored C assets are `core.c`, `collections.c`, `cycles.c`,
`mutex.c`, `process.c`, `strings.c`, `threads.c`, `trycatch.c`, and `gpu.c`,
with the shared `btrc_rt.h` header. Compilers select and materialize these
assets; lowerers and emitters never assemble helper source.

`src/language/hosted_abi.toml` owns hosted signatures, lifetime and realtime effects, names,
platform subsets, runtime-adopting metadata, and provenance markers. Generated
Python rows use immutable value types. Generated btrc rows expose public fields
required by the language and consumers treat them as read-only by convention.
All generated modules contain data/schema declarations only; retained
repositories own indexing and queries.

The unified generator produces exactly these data files:

```text
src/compiler/python/runtime/generated.py
src/compiler/btrc/generated/runtime/Catalog.btrc
src/compiler/python/syntax/ast/generated.py
src/compiler/btrc/generated/ast/Node.btrc
src/compiler/python/abi/generated.py
src/compiler/btrc/generated/hosted_abi/Tables.btrc
src/devex/lsp/catalog/generated.py
```

## Exact developer-experience destination

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

Build payloads live only under `build/devex/vscode/`, and the packaged VSIX
lives at `dist/btrc.vsix`. Source directories never contain compiled output,
bundled payloads, dependency installs, Python bytecode, or test caches.

## Architecture-first verification

During the ownership migration, each slice proves the destination shape with
exact-tree and stale-path audits, generated-source checks, AST/parse/import
checks, dependency/SCC and loose-behavior audits, and `git diff --check`.
Behavior, parity, bootstrap, compiler-corpus, and broad correctness suites are
deferred until the destination tree is mechanically complete.

After that structural boundary is stable, verification hill-climbs through
focused behavior and parity checks, then the full corpus, strict GCC/Clang C11
matrix, generated-source verification, bootstrap fixed point, LSP/debugger
suites, extension packaging, lint, and format checks. No failure may be
dismissed as pre-existing.

## Definition of done

- The exact trees above exist and obsolete paths are absent.
- Both compilers expose one application API and six explicit stage owners.
- Analyzer and IR behavior use composition rather than mixins or service
  location; production behavior has a real owner.
- Runtime and hosted-ABI data come only from their shared specifications.
- Python/self-host tokens, AST, IR, optimized IR, diagnostics, emitted C,
  runtime metadata, runtime behavior, and bootstrap output satisfy the
  bit-perfect completion gates.
