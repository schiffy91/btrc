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
[`generated/ast/node.btrc`](generated/ast/node.btrc) by hand.

## Application and pipeline ownership

`btrcc_main.btrc` is only the process entry point. `compiler.btrc` owns the
production application object, `cli/driver.btrc` owns command-line and process
orchestration, and `pipeline/pipeline.btrc` owns ordered compilation.
`BtrccOptions` defaults to strict imports before any of those owners can observe
it.

The destination contains exactly 88 `.btrc` files: 82 compiler/generated files
and six explicit developer-tool files. `compiler.btrc` and
`btrcc_main.btrc` are the only `.btrc` files at this package root.

Each stage exposes one manifest. The manifests record dependency direction and
are the stable navigation surface; implementation leaves are not separate
public stages.

| Domain | Manifest or primary owner |
|---|---|
| Application and command | `compiler.btrc`, `cli/driver.btrc`, `pipeline/stage.btrc` |
| Front end and import visibility | `frontend/stage.btrc`, `frontend/resolver.btrc`, `frontend/visibility.btrc` |
| Grammar and lexer | `lexer/stage.btrc` |
| Parser | `parser/stage.btrc` |
| Semantic analysis | `analyzer/stage.btrc`, `analyzer/analyzer.btrc` |
| IR lowering | `ir/stage.btrc`, `ir/lowering/lowerer.btrc`, `ir/lowering/context.btrc` |
| IR optimization | `ir/optimization/optimizer.btrc`, `ir/optimization/cleanup.btrc` |
| C and WGSL emission | `ir/emitter.btrc`, `ir/gpu/wgsl.btrc` |

The exact owner packages are `cli/`, `pipeline/`, `syntax/`, `lexer/`,
`frontend/`, `parser/`, `analyzer/`, `analyzer/ownership/`,
`analyzer/validation/`, `ir/`, `ir/runtime/`, `ir/lowering/`,
`ir/lowering/ownership/`, `ir/gpu/`, `ir/optimization/`,
`ir/optimization/setjmp/`, `generated/`, and `tools/`. The complete 88-file
inventory is recorded in
[`docs/design/compiler-structure.md`](../../../docs/design/compiler-structure.md).

`ir/lowering/` contains the retained context/composition owners and the type,
declaration, generic, function, statement, control-flow, expression, call,
callable, assignment, aggregate, string, and concurrency lowerers. Its
`ownership/` package contains the six ownership lowerers. Ordinary and generic
paths use these same owners; specialization supplies views rather than a second
lowering stack.

The small `tools/lex_main.btrc`, `tools/parse_main.btrc`, and
`tools/frontend_main.btrc` programs are stage-boundary inspection drivers.
`tools/ast/schema.btrc` owns the native ASDL model and parser;
`tools/ast/dump_main.btrc` and `tools/ast/generate_main.btrc` retain the dump
and AST-generation commands.

Runtime C is shared with the Python compiler. `src/runtime/c/manifest.toml`
describes helper metadata and stable order for the pre-authored `core.c`,
`collections.c`, `cycles.c`, `mutex.c`, `process.c`, `strings.c`, `threads.c`,
`trycatch.c`, and `gpu.c` assets plus `btrc_rt.h`. Generated immutable rows live
in `generated/runtime/catalog.btrc`; handwritten lookup, selection, dependency,
and reference behavior lives in `ir/runtime/catalog.btrc` and
`ir/runtime/references.btrc`. Lowerers and emitters never assemble runtime C.

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

Structural audits — exact-tree and stale-path, generation and parse/import
checks, dependency/SCC and loose-behavior audits, and `git diff --check` — are
the first pass on a change. Behavior, parity, corpus, and bootstrap checks all
apply as well; the matrix below is the finish line.

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
  src/compiler/btrc/tools/parse_main.btrc --no-cache -o /tmp/parse.c
cc -std=c11 -pedantic-errors /tmp/parse.c -lm -lpthread -o /tmp/btrcparse
/tmp/btrcparse program.btrc
```

## Parser diagnostics

`Parser.expect()` and generic-close handling record a sticky fatal diagnostic
with line/column and expected/actual token details. `parseProgram()` stops at
that boundary; `tools/parse_main.btrc` and `btrcc_main.btrc` report the error and
return nonzero before analysis or IR generation. The built-driver regression
suite is `src/tests/btrc/test_parser_diagnostics.py`.
