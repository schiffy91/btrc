# Self-hosted compiler

The repository has two implementations of one language pipeline:

- `src/compiler/python/` is the reference implementation and bootstrap compiler.
- `src/compiler/btrc/` is the self-hosted implementation used by `btrcc`.

Both consume `src/language/grammar.ebnf` and `src/language/ast.asdl`, then run
lexer, parser, analyzer, IR generation, optimization, and C emission. Language
tests share the same source fixtures and golden runtime output.

The self-hosted destination is an exact 90-file `.btrc` inventory: 84
compiler/generated files and six explicit developer-tool files. At the package
root, `compiler.btrc` is the public application object and `btrcc_main.btrc` is
the only production process entry point. The file-by-file inventory is recorded
in [Compiler Structure](compiler-structure.md).

## Bootstrap contract

The Python compiler creates stage 1, which then builds two self-hosted stages:

```text
btrcpy(btrcc source) -> btrcc1
btrcc1(btrcc source) -> btrcc2
btrcc2(btrcc source) -> btrcc3.c
```

`src/tests/btrc/test_bootstrap.py` requires `btrcc2.c == btrcc3.c` byte for
byte. This fixed point proves that the self-built compiler reproduces itself;
the same suite also compiles and runs a representative program with the
self-built binary.

## Stage contracts

| Stage | Self-host modules | Output |
|---|---|---|
| Grammar/lexer | `syntax/grammar.btrc`, `syntax/tokens.btrc`, `lexer/lexer.btrc` | token stream |
| Parser | `parser/parser.btrc` | fat tagged `Node` AST |
| Analyzer | `analyzer/stage.btrc`, `analyzer/analyzer.btrc` | symbol/type/generic metadata |
| IR generation | `ir/model.btrc`, `ir/lowering/lowerer.btrc` | structured fat tagged IR |
| Optimization | `ir/optimization/optimizer.btrc` | reachable, normalized IR |
| C emission | `ir/emitter.btrc` | strict C11 text |

The frontend package composes imports and the standard library through
`frontend/resolver.btrc`, with source I/O, stdlib, and visibility retained by
their sibling owners.
`btrcc_main.btrc` is the thin production entry point; `cli/driver.btrc` owns
the command. The small lexer, parser, and front-end drivers under `tools/`
exist for stage-boundary inspection.

The package ownership is exact:

- `pipeline/` contains the imports-only stage manifest, immutable models, and
  `CompilerPipeline`.
- `syntax/`, `lexer/`, `frontend/`, and `parser/` own the complete front end;
  parser source-macro definitions remain with the parser.
- `analyzer/` owns semantic composition, declarations, types, expressions,
  generics, operators, hosted ABI, source macros, and GPU policy;
  `analyzer/ownership/` owns managed values and cycles, while
  `analyzer/validation/` contains one validator composition owner and ten
  focused domain validators.
- `ir/` owns the imports-only stage manifest, complete structured model, and
  `CEmitter`; `ir/runtime/` owns catalog selection and reference collection.
- `ir/lowering/` contains `LoweringContext`, `IRLowerer`, and the type,
  declaration, generic, function, statement, control-flow, expression, call,
  callable, assignment, aggregate, string, and concurrency lowerers. Its
  `ownership/` package contains the six ownership-specific lowerers.
- `ir/gpu/` owns WGSL rendering and GPU pipeline planning;
  `ir/optimization/` owns reachability/normalization, cleanup validation, and
  the two setjmp analysis/safety owners.
- `generated/` contains data-only AST, hosted-ABI, and runtime catalogs.
  `tools/` contains five developer entry points plus the ASDL schema owner.

Stage manifests contain imports only. Concrete leaves own behavior, and public
class names remain globally unique because directories do not create btrc
namespaces.

## Fat tagged nodes

btrc does not provide the Python implementation's dynamic `isinstance`-style
AST traversal. Its generated AST therefore uses one `Node` class with a `kind`
tag and the union of fields needed by every ASDL variant. The IR follows the
same representation. Dispatch is explicit and lowering remains isolated in IR
generation; the emitter only formats structured IR.

`src/compiler/btrc/generated/ast/node.btrc` is generated from
`src/language/ast.asdl` by `tools/compiler_codegen/ast.py`.
`make ast-generate-btrc` regenerates and validates it. Never edit the generated
node file directly.

## Shared runtime contract

`src/runtime/c/manifest.toml` describes helper names, dependencies, headers,
features, source markers, and deterministic order for the shared pre-authored
runtime assets: `core.c`, `collections.c`, `cycles.c`, `mutex.c`, `process.c`,
`strings.c`, `threads.c`, `trycatch.c`, `gpu.c`, and `btrc_rt.h`.
`src/compiler/btrc/generated/runtime/catalog.btrc` contains immutable generated
rows; `ir/runtime/catalog.btrc` and `ir/runtime/references.btrc` retain query,
selection, dependency, and reference behavior. Lowering and C emission do not
assemble runtime source.

## Verification

Structural audits come first on any change: exact-tree and stale-path,
generated-source checks, parse/import and dependency/SCC checks, loose-behavior
audits, and `git diff --check`. Corpus, parity, bootstrap, and broad correctness
runs all apply too — the mandatory final matrix is:

```bash
make test-selfhost          # lexer parity
make test-btrc-selfhost     # shared language corpus through btrcc
make bootstrap              # self-hosted fixed point
make test-c11               # GCC/Clang optimization matrix, warnings as errors
```

The unified runner is `src/tests/runner.py`; `--compilers=python,btrc` selects
both implementations. Compiler failure is always a failure—there is no legacy
runner that converts unsupported self-host cases into skips.

## Parser diagnostics

The self-host parser records the first failed token expectation with its
line/column and expected/actual token, then unwinds to `parseProgram()` without
process termination in token helpers. Both parser-stage and production drivers
report the diagnostic, return nonzero, and stop before analysis or IR
generation. `src/tests/btrc/test_parser_diagnostics.py` exercises the built
drivers on invalid and valid source.
