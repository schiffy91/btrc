# btrc Compiler — Architecture & Development Rules

These rules are non-negotiable. Every contributor (human or AI) must follow them.
Read this ENTIRE file before writing any code.

---

## Multi-Session Warning

This project is too large for a single context window. You WILL run out of memory.

**Before you start working:**
1. Read this file completely
2. Read `/home/node/.claude/projects/-workspace/memory/MEMORY.md`
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

The Python compiler follows a 6-stage pipeline driven by formal specs.
A self-hosted btrc compiler (same pipeline) is planned but not yet implemented.

```
SHARED SPECS (single source of truth):
  src/language/grammar.ebnf       keywords, operators, syntax rules
  src/language/ast/ast.asdl       AST node types (Zephyr ASDL)
  src/language/ast/asdl_python.py ASDL → Python dataclasses
  src/language/ast/asdl_btrc.py   ASDL → btrc classes

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
- Produces typed AST nodes generated from `src/language/ast/ast.asdl`
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
  - Vtable setup for inheritance/interfaces
- **Produces structured IR nodes** (IRIf, IRCall, IRFor, IRBinOp, etc.)
- **NEVER produces C text** (exception: IRRawC for setjmp boilerplate only)

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
- @lexical: @keywords (57 keywords), @operators (48 operators sorted longest-first)
- @syntax: grammar rules (human-readable spec, not parser-generator input)
- EBNF parser extracts GrammarInfo: keyword set, operator list,
  keyword→token mapping, operator→token mapping

### src/language/ast/ast.asdl (Zephyr ASDL)
- ~50 AST node types with typed fields
- Sum types: decl, stmt, expr, class_member, if_else, for_init, etc.
- Product types: Program, ClassDecl, BinaryExpr, etc.
- attributes(int line, int col) on nodes that have source locations
- Field names ARE the API contract for analyzer, IR gen, LSP, and tests
- NEVER hand-edit ast_nodes.py or ast_nodes.btrc — regenerate from ASDL

---

## Python Compiler (src/compiler/python/)

### File Size Rule

**~200 lines per file, max 300.** If a file exceeds this, decompose it into
a package with sub-modules. No `__init__.py` files — use explicit module paths
(e.g., `from .parser.parser import Parser` not `from .parser import Parser`).

### File Structure

```
src/compiler/python/
  ebnf.py                       EBNF grammar parser → GrammarInfo
  tokens.py                     Token + TokenType enum
  lexer.py                      grammar-driven tokenizer
  lexer_literals.py             number/string literal parsing
  ast_nodes.py                  GENERATED from src/language/ast/ast.asdl
  main.py                       pipeline entry point + CLI

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

  analyzer/                      semantic analysis (mixin-based)
    analyzer.py                  assembles Analyzer from mixins
    core.py                      data structures (ClassInfo, Scope, SymbolInfo)
    registration.py              pass 1: register declarations
    statements.py                statement analysis
    expressions.py               expression analysis + type inference
    type_inference.py            var type deduction
    type_utils.py                type compatibility, formatting
    functions.py                 function/method analysis
    validation.py                access control, inheritance checks

  ir/                            IR pipeline
    nodes.py                     IR node dataclass definitions
    optimizer.py                 dead helper elimination
    emitter.py                   IR → C text (simple tree walk)

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
      generics/                  monomorphization
        core.py                  generic infrastructure
        lists.py                 List<T> specialization
        maps.py                  Map<K,V> specialization
        sets.py                  Set<T> specialization
        user.py                  user-defined generic classes

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

  tests/
    test_lexer.py                tokenize snippets → check tokens
    test_parser.py               parse snippets → check AST structure
    test_analyzer.py             analyze snippets → check types/errors
```

---

## btrc Compiler (src/compiler/btrc/) — NOT YET IMPLEMENTED

The self-hosted compiler is planned but does not exist yet. When implemented,
it will be a faithful port of the Python compiler in btrc, following the same
6-stage pipeline and producing identical output for every input.

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

#### 1. Python Unit Tests (per-stage, ~467 tests)
```
src/compiler/python/tests/
  test_lexer.py           tokenize snippets → check tokens
  test_parser.py          parse snippets → check AST structure
  test_analyzer.py        analyze snippets → check types/errors
```

#### 2. Language Tests (280 .btrc files, organized by topic)
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
  stdlib/                  Math, DateTime, Random
  algorithms/              quicksort, BST, hash table, linked list (pure C)

Each subdirectory has:
  test_*.btrc              test files (compile → gcc → run → assert PASS)
  expected/                golden .stdout files for output comparison
```

### Makefile Targets
```
make build          Create bin/btrcpy wrapper script
make test           Python unit tests + 280 btrc language tests
make test-btrc      Just the 280 btrc language tests
make lint           Lint with ruff
make format         Format with ruff
make clean          Remove build artifacts
```

---

## Hard Rules (Summary)

1. **IR Gen produces structured IR nodes, NEVER raw C text.**
2. **No monolithic codegen.** IR gen + optimizer + emitter is the ONLY path.
3. **Grammar is the single source of truth.** No hardcoded keywords/operators.
4. **AST types come from ASDL.** Never hand-edit generated files.
5. **Files ~200 lines max.** Decompose into packages.
6. **All 747 tests must pass.** No "pre-existing failures."
7. **Don't cut corners when context runs low.** Save state and stop.
