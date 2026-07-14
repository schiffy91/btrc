# Self-hosted compiler

The repository has two implementations of one language pipeline:

- `src/compiler/python/` is the reference implementation and bootstrap compiler.
- `src/compiler/btrc/` is the self-hosted implementation used by `btrcc`.

Both consume `src/language/grammar.ebnf` and `src/language/ast.asdl`, then run
lexer, parser, analyzer, IR generation, optimization, and C emission. Language
tests share the same source fixtures and golden runtime output.

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
| Grammar/lexer | `ebnf.btrc`, `tokens.btrc`, `lexer.btrc` | token stream |
| Parser | `parser.btrc` | fat tagged `Node` AST |
| Analyzer | `ast_identity.btrc`, `analyzer.btrc` | symbol/type/generic metadata |
| IR generation | `ir_nodes.btrc`, `irgen.btrc` | structured fat tagged IR |
| C emission | `emitter.btrc` | strict C11 text |

The front end in `frontend.btrc` composes imports and the standard library.
`btrcc_main.btrc` is the production driver. The small lexer, parser, and
front-end drivers exist for stage-boundary testing.

## Fat tagged nodes

btrc does not provide the Python implementation's dynamic `isinstance`-style
AST traversal. Its generated AST therefore uses one `Node` class with a `kind`
tag and the union of fields needed by every ASDL variant. The IR follows the
same representation. Dispatch is explicit and lowering remains isolated in IR
generation; the emitter only formats structured IR.

`src/compiler/btrc/ast/node.btrc` is generated from
`src/language/ast.asdl` by `src/compiler/python/ast/gen_btrc_ast.py`.
`make ast-generate-btrc` regenerates and validates it. Never edit the generated
node file directly.

## Verification

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
