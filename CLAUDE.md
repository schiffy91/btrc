# btrc Compiler — Architecture & Development Rules

These rules are non-negotiable. Every contributor (human or AI) must follow them.
Read this ENTIRE file before writing any code.

---

## Multi-Session Warning

This project is too large for a single context window. You WILL run out of memory.

**Before you start working:**
1. Read this file completely
2. Read MEMORY.md (in your auto-memory directory)
3. Check git status to see what's been done
4. Check the todo list
5. Run `make test` to see what passes and what's broken

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
  src/compiler/python/ast/asdl_python.py  ASDL → Python dataclasses
  src/compiler/python/ast/gen_btrc_ast.py ASDL → btrc fat tagged nodes

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
  [5. Optimizer]    →  optimized IR tree   (dead helper elimination)
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
- **NEVER produces C text.** Runtime helpers are pre-authored in
  `ir/helpers/`; IR generation may reference them, but does not assemble them.

#### Stage 5: Optimizer
- Walks IR tree, collects runtime helper references
- Removes unused helpers from IRModule.helper_decls
- Resolves transitive category dependencies

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
- NEVER hand-edit ast_nodes.py or ast/node.btrc — regenerate from ASDL

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

```
src/compiler/python/
  __init__.py                   durable Compiler/Options/Result API
  compiler.py                   application object + compiled-C cache policy
  main.py                       thin process entry point
  pipeline/
    models.py                   immutable options + cross-stage results
    pipeline.py                 ordered six-stage orchestration
  frontend/
    dependencies.py             ResolvedSource + typed dependency graph
    resolver.py                 package/import/include/stdlib resolution
    stdlib.py                   stdlib discovery, composition, symbol ownership
    parser.py                   lex/parse modes + AST provenance
    visibility.py               per-file strict-import validation
  cli/
    compiler_cli.py             arguments, diagnostics, and user-facing file I/O

  ebnf.py                       EBNF grammar parser → GrammarInfo
  tokens.py                     Token + TokenType enum
  lexer.py                      grammar-driven tokenizer
  lexer_literals.py             number/string literal parsing
  ast_nodes.py                  GENERATED from src/language/ast.asdl
  cache_io.py                   atomic JSON/text cache writes
  cache_keys.py                 cache paths + toolchain fingerprints
  disk_cache.py                 on-disk compiled-C cache
  stdlib_ast_cache.py           schema-validated JSON stdlib AST cache

  parser/                        recursive descent parser (mixin-based)
    parser.py                    assembles Parser from mixins
    core.py                      ParserBase class, state, token helpers
    types.py                     type expression + param parsing
    declarations.py              class, struct, enum decls
    decl_simple.py               function, typedef, extern decls
    statements.py                var decls, assignments
    control_flow.py              if, for, while, switch, try/catch
    expressions.py               precedence climbing
    postfix.py                   member access, subscript, call chains
    primary.py                   atoms: literals, new, sizeof, cast, fstring
    lambdas.py                   verbose + arrow lambda parsing

  analyzer/                      semantic analysis (composition migration)
    semantic_analyzer.py         durable SemanticAnalyzer composition root
    core.py                      remaining orchestration + analysis context
    core_models.py               semantic result, declaration, and symbol models
    declarations/                owned pass-one declaration registration
      registry.py                declaration indexes + registration cascade
      top_level.py               values, structs, enums, and source macros
      inheritance.py             dependency-ordered class metadata inheritance
    statements.py                statement analysis
    expressions.py               expression analysis + type inference
    type_inference.py            var type deduction
    type_utils.py                type compatibility, formatting
    functions.py                 function/method analysis
    validation.py                access control, inheritance checks
    gpu.py                       @gpu function validation

  ir/                            IR pipeline
    nodes.py                     IR node dataclass definitions
    optimizer.py                 dead helper elimination
    emitter.py                   IR → C text (simple tree walk)
    emitter_exprs.py             expression emission mixin
    emitter_gpu.py               GPU kernel + dispatch emission mixin

    gen/                         IR generation (AST → IR lowering)
      generator.py               main class + generate_ir() entry point
      classes.py                 class/struct lowering
      class_members.py           field/method/property lowering
      enums.py                   enum lowering (simple + rich)
      statements.py              statement lowering
      control_flow.py            if/while/for/switch/try lowering
      expressions.py             expression lowering
      operators.py               operator overloading → method calls
      calls.py                   function/method call lowering
      functions.py               function def lowering
      methods.py                 method → free function lowering
      fields.py                  field initialization
      fstrings.py                f-string → snprintf lowering
      collections.py             collection method expansion
      iterations.py              for-in → C-style for lowering
      lambdas.py                 lambda lifting + capture structs
      types.py                   type-related IR generation
      helpers.py                 runtime helper registration
      arc.py                     ARC reference counting lowering
      threads.py                 spawn/Thread/Mutex lowering
      variables.py               variable declaration lowering
      gpu.py                     @gpu kernel IR generation
      gpu_wgsl.py                btrc AST → WGSL text
      generics/                  monomorphization
        core.py                  generic infrastructure
        user.py                  user-defined generic classes
        user_emitter.py          generic class expression emitter
        user_emitter_stmts.py    generic class statement emitter
        user_methods.py          generic class method lowering

    helpers/                     runtime helper C source text
      registry.py                aggregates all helpers into HELPERS dict
      core.py                    helper infrastructure
      alloc.py                   safe alloc wrappers
      divmod.py                  division/modulo safety
      string_pool.py             string tracking pool
      strings.py                 string operation helpers
      strings_ops.py             string manipulation (replace, split, etc.)
      strings_query.py           string queries (contains, indexOf, etc.)
      strings_convert.py         string conversions (toUpper, toLower, etc.)
      math.py                    math helpers
      trycatch.py                setjmp/longjmp infrastructure
      hash.py                    hash functions for Map/Set
      collections.py             generic collection function templates
      cycles.py                  ARC cycle detection helpers
      threads.py                 threading helpers (pthread wrappers)

```

Compiler tests live in `src/tests/python/`; generated language/runtime fixtures
and their golden output live alongside the topic-organized corpus in
`src/tests/`.

---

## btrc Compiler (src/compiler/btrc/)

The self-hosted compiler implements the same six-stage pipeline with fat tagged
AST and IR nodes. `btrcc_main.btrc` is the production driver; the unified
language runner executes the corpus through both compilers, and the bootstrap
suite proves a byte-stable self-hosting fixed point.

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
make stubs-generate       Regenerate built-in type stubs
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
