# Compiler Structure

Status: **active architecture contract**.

This document defines the target layout and migration order for both btrc
compilers. It replaces line-count-driven decomposition with ownership-driven
objects and packages.

## Why this refactor exists

The old hard file-size rule produced discoverability without encapsulation.
The ownership audit at commit `4c15ee1` (production sources only; generated
ASTs, tests, vendored code, and entry-point adapters excluded) found:

- the Python compiler and developer tooling have 569 source files, with 1,575
  loose behavior functions that still need owners;
- its analyzer is an 80-class mixin assembly with a 78-module strongly
  connected method graph;
- Python IR generation alone has 800 loose functions, 411 of which accept a
  mutable `gen`/`generator` service-locator;
- the self-hosted compiler has 260 production source files, with 1,282 loose
  behavior definitions that still need owners;
- 20 ambient mutable bindings remain: 13 in the LSP, four in Python IR
  contexts, two compiler metadata caches, and one dead self-hosted binding;
- the self-hosted core is still concentrated in very large parser, analyzer,
  and IR-generator files despite the surrounding microfile sprawl.

File count and line count are not design goals. A boundary is justified only
when it gives one owner a coherent responsibility and a small explicit API.

## Invariants

The refactor must preserve these architectural contracts:

1. Grammar and ASDL remain the language sources of truth.
2. Both compilers retain the lexer, parser, analyzer, structured IR lowering,
   optimizer, and C emitter stages.
3. IR lowering produces nodes, never assembled C text.
4. The Python and self-hosted implementations keep matching observable
   semantics and diagnostics.
5. Generated C remains warning-free strict C11.
6. Strict imports are the default. Textual `#include` joins files into one
   compilation unit; `import` creates a directed visibility dependency.

## Object model

`Compiler` owns one `CompilerPipeline`. The pipeline composes stage objects:

```text
Compiler
  CompilerPipeline
    SourceResolver -> ResolvedSource(text, provenance, dependency graph)
    Lexer
    Parser
    SemanticAnalyzer
    IRLowerer
    IROptimizer
    CEmitter
```

Each complex stage owns domain collaborators instead of inheriting a large
mixin lattice or calling free functions through a shared service-locator:

```text
SemanticAnalyzer
  AnalysisContext
  DeclarationRegistry
  TypeSystem
  ExpressionAnalyzer
  StatementAnalyzer
  OwnershipValidator
  GenericAnalyzer
  GpuValidator

IRLowerer
  LoweringContext
  DeclarationLowerer
  ExpressionLowerer
  CallLowerer
  OwnershipLowerer
  ControlFlowLowerer
  ExceptionLowerer
  GenericLowerer
  GpuLowerer
  ConcurrencyLowerer
```

Collaborators receive their context explicitly. They do not reach through an
unbounded generator/analyzer object for unrelated state. Domain classes may
be larger when their behavior is cohesive.

Production modules do not expose loose behavior functions. The narrow
exceptions are process entry points, generated declarations/tables, and pure
data/type declarations. A class must be a real owner; a one-method class used
only to imitate a namespace is not an acceptable conversion.

## Target tree

The two implementations intentionally share the same stage vocabulary.
Python-only distribution tooling stays outside the language pipeline.

```text
src/compiler/python/
  __init__.py                 Compiler, CompilerOptions, CompilerResult
  compiler.py                 application object
  pipeline/
    pipeline.py               six-stage orchestration
    models.py                 immutable cross-stage results
  frontend/
    resolver.py               SourceResolver
    dependencies.py           SourceDependencyGraph + edge kinds
    visibility.py             ImportVisibilityChecker
    stdlib.py                 standard-library discovery/composition
    packages.py               package dependency resolution
  lexer/
  parser/
  analyzer/
    semantic_analyzer.py      SemanticAnalyzer composition root
    context.py
    model.py
    declarations/
      registry.py             declaration indexes + registration cascade
      top_level.py            values, structs, enums, and source macros
      inheritance.py          class metadata inheritance
    types/
    expressions/
    statements/
    ownership/
    generics/
    gpu/
  ir/
    __init__.py               IR stage API only
    model/
    lowering/
      context.py
      declarations/
      expressions/
      calls/
      ownership/
      control_flow/
      exceptions/
      generics/
      gpu/
      concurrency/
    optimization/
    emission/
    runtime/
  interop/
    hosted_abi/
    freestanding/
  artifacts/
    cache/
    stdlib/
    selfhost_bundle/
    publication/
  cli/

src/compiler/btrc/
  btrcc_main.btrc            thin process entry point only
  compiler.btrc              Compiler application object
  pipeline/
  frontend/
    stage.btrc               ordered public stage manifest
    resolver.btrc
    dependencies.btrc
    visibility.btrc
    stdlib.btrc
  lexer/
    stage.btrc
  parser/
    stage.btrc
  analyzer/
    stage.btrc
    context.btrc
    declarations/
    types/
    expressions/
    statements/
    ownership/
    generics/
    gpu/
  ir/
    stage.btrc
    model/
    lowering/
      declarations/
      expressions/
      calls/
      ownership/
      control_flow/
      exceptions/
      generics/
      gpu/
      concurrency/
    optimization/
    emission/
    runtime/
  generated/
    hosted_abi/
  tools/                     alternate diagnostic/developer entry points
```

Self-host directories improve ownership and navigation but do not create a
namespace: btrc imports are textual today. Public class names therefore remain
globally unique until the language gains namespaced modules. Every stage has a
single manifest that records its intentional dependency order; the root driver
imports stage manifests rather than hundreds of leaf files.

Python `__init__.py` files define small durable APIs only. Internal code imports
the concrete owner it uses. Wildcard exports and broad compatibility re-export
layers are prohibited.

## Migration order

Each step must leave the relevant tests green and may be committed separately.

1. **Governance and baseline**
   - remove the LOC cap and `__init__.py` ban;
   - record global-symbol, dependency, generated-output, and test baselines.
2. **Strict frontend contract**
   - introduce `ResolvedSource` and typed dependency-graph objects;
   - distinguish compilation-unit `#include` edges from directed `import`;
   - make strict visibility the default in both compilers;
   - retain only an explicit `--relaxed-imports` compatibility mode.
3. **Application and public stage APIs**
   - introduce `Compiler`, `CompilerPipeline`, options, and result objects;
   - reduce `main` functions to argument/process adapters;
   - update all internal callers rather than accumulating re-export shims.
4. **Python analyzer composition**
   - replace the 80-class MRO with domain collaborators over `AnalysisContext`;
   - consolidate strongly connected microfiles within each owner;
   - keep type, ownership, generic, and GPU policies independently testable.
5. **Python IR composition**
   - replace `fn(gen, ...)` helpers with lowerer methods over
     `LoweringContext`;
   - move IR model, lowering, optimization, emission, and runtime helpers to
     their owning packages;
   - eliminate module-global mutable compiler state.
6. **Self-host driver and stage manifests**
   - introduce the real `Compiler`/driver object;
   - move alternate entry points under `tools/`;
   - replace the root include wall with ordered stage manifests.
7. **Self-host analyzer and IR composition**
   - move top-level semantic and lowering behavior onto the same domain owners
     used by the Python architecture;
   - consolidate leaf fragments only when their state and change reasons are
     the same;
   - keep generated tables and C-runtime source declarations explicit.
8. **Close compatibility seams**
   - remove old import paths and temporary adapters;
   - verify no production behavioral free functions or mutable globals remain;
   - update this document and `AGENTS.md` to the final tree.

## Definition of done

- Both compilers expose one documented application API and six stage APIs.
- Analyzer and IR behavior use composition, not cross-module mixin/service-
  locator coupling.
- Production compiler behavior has an object owner; only the documented narrow
  exceptions remain at module/global scope.
- The self-host root contains only the production entry point, application
  composition root, stage directories, generated sources, and developer tools.
- Strict import checking is on for normal CLI, API, bootstrap, examples, and
  tests; relaxed behavior requires `--relaxed-imports`.
- Python/self-host AST, IR, diagnostics, generated C, runtime output, and
  bootstrap fixed-point gates pass.
