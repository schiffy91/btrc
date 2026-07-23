# Self-hosted btrc compiler

`btrcc` is the production self-hosted implementation of the same six-stage
pipeline as the Python reference compiler. It reads the shared grammar and AST
specifications, resolves the explicit dependency graph, enforces per-file
import visibility, analyzes the program, lowers it to structured IR, and emits
strict C11.

Because btrc has no dynamic downcasts, the self-hosted AST and IR use fat tagged
nodes: one node class per layer, a `kind` tag, and the union of fields needed by
all variants. The AST node source is generated from
[`src/language/ast.asdl`](../../language/ast.asdl); do not edit
[`ast/node.btrc`](ast/node.btrc) by hand.

## Pipeline modules

| Stage | Modules |
|---|---|
| Front end | `frontend_paths.btrc`, `frontend.btrc`, `btrcc_main.btrc` |
| Grammar and lexer | `ebnf.btrc`, `tokens.btrc`, `lexer.btrc` |
| Parser | `parser.btrc` |
| Analyzer | `ast_identity.btrc`, `analyzer.btrc` |
| IR generation | `ir_nodes.btrc`, `ir_top_nodes.btrc`, `irgen.btrc`, `setjmp_volatility.btrc` |
| GPU lowering | `gpu_ir_nodes.btrc`, `gpu_wgsl*.btrc`, `gpu_lowering.btrc`, `gpu_dispatch*.btrc`, `gpu_optimizer.btrc` |
| C emission | `emitter.btrc`, `gpu_emitter.btrc` |

The small `lex_main.btrc`, `parse_main.btrc`, and `frontend_main.btrc` programs
are stage-boundary verification drivers. `ast/asdl.btrc` and
`ast/gen_node.btrc` provide the dependency-free self-hosted ASDL generator.

Reachable top-level `@gpu` functions follow the same checked WGSL and structured
host-dispatch model as the Python compiler. Unsupported GPU syntax fails closed;
unreachable kernels and shader constants are removed by DCE. Pre-submit GPU
failures execute per-invocation C fallbacks, including array outputs. Failures
after a successful submission clean up and terminate without applying a
fallback to partially transferred data.

## Build and verify

The developer build resolves the repository data from `bin/btrcc`'s real path;
release bundles resolve `share/btrc` beside their `bin` directory. Neither mode
uses the current directory as an implicit data source.

```bash
make btrcc                  # native bin/btrcc
make test-selfhost          # lexer parity
make test-btrc-selfhost     # full shared corpus through btrcc
make bootstrap              # fixed-point self-hosting proof
```

`btrcc --stdlib-dir` prints the active standard-library directory. Set
`BTRC_HOME` to an alternate data root containing `language/grammar.ebnf` and
`stdlib/`; an invalid explicit override fails rather than falling back. The
cross-build targets emit relocatable `.tar.gz`/`.zip` archives and SHA-256
sidecars in `dist/`.

Strict imports are the default. `--strict-imports` explicitly reasserts that
mode; `--relaxed-imports` is the only legacy compatibility opt-out and enables
implicit cross-file visibility plus whole-stdlib composition.

Native-module output keeps its C header include. Compile it with the active
stdlib and relevant module directory on the include path, such as
`-I "$(btrcc --stdlib-dir)" -I "$(btrcc --stdlib-dir)/gui"`, then link the
module runtime described in that stdlib directory.

`btrcc` intentionally rejects package-style imports (`import dep` or
`import dep.module`) because the `btrc.toml`/lockfile resolver has not yet been
self-hosted. Use `btrcpy` for package projects. Local imports remain supported
when written as explicit paths such as `import ./dep.btrc` or a quoted path;
btrcc never falls back from a package name to a same-named file.

For parser-stage inspection:

```bash
python3 -m src.compiler.python.main \
  src/compiler/btrc/parse_main.btrc --no-cache -o /tmp/parse.c
cc -std=c11 -pedantic-errors /tmp/parse.c -lm -lpthread -o /tmp/btrcparse
/tmp/btrcparse program.btrc
```

## Parser diagnostics

`Parser.expect()` and generic-close handling record a sticky fatal diagnostic
with line/column and expected/actual token details. `parseProgram()` stops at
that boundary; `parse_main.btrc` and `btrcc_main.btrc` report the error and
return nonzero before analysis or IR generation. The built-driver regression
suite is `src/tests/btrc/test_parser_diagnostics.py`.
