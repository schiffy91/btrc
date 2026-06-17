# Self-Hosted btrc Compiler

The goal: a btrc compiler written in btrc (`src/compiler/btrc/`) that is a
faithful port of the Python compiler (`src/compiler/python/`), follows the same
6-stage pipeline, and produces **byte-identical output for every input** —
ultimately compiling its own source (bootstrap).

## The invariant that drives everything

For every input program, `btrcc` must produce exactly what `btrcpy` produces:

```
btrcc --emit-tokens  f.btrc  ==  btrcpy --emit-tokens  f.btrc
btrcc --emit-ast     f.btrc  ==  btrcpy --emit-ast     f.btrc
btrcc --emit-ir      f.btrc  ==  btrcpy --emit-ir      f.btrc
btrcc                f.btrc  ==  btrcpy                f.btrc      (the C output)
```

These `--emit-*` flags are the **stage boundaries** and the **verification
points**. We build the pipeline bottom-up and diff each stage against the Python
reference before starting the next. The diff harness is kept as regression
coverage (engineering-decomposition: prove each atom, then each cascade
boundary, against the real reference).

## Toolchain / bootstrap

`btrcc` is itself btrc source, so until it can compile itself it is built by the
Python compiler:

```
src/compiler/btrc/*.btrc  ──btrcpy──▶  btrcc.c  ──cc──▶  btrcc   (the binary)
```

Bootstrap milestone (the end): `btrcc` compiles `src/compiler/btrc/*.btrc` and
the resulting binary is identical to the btrcpy-built one (fixed point).

## Stages (atoms) and their contracts

Same shapes as the Python compiler; ASDL field names are the API contract.

| Stage | btrc module(s) | Input → Output | Verified by |
|---|---|---|---|
| 0. EBNF | `ebnf.btrc` | grammar.ebnf → GrammarInfo (keywords, operators, token maps) | feeds lexer |
| 1. Lexer | `tokens.btrc`, `lexer.btrc` | source + GrammarInfo → Token[] | `--emit-tokens` |
| 2. Parser | `parser/*.btrc` | Token[] → AST (`ast_nodes.btrc`) | `--emit-ast` |
| 3. Analyzer | `analyzer/*.btrc` | AST → AnalyzedProgram | errors + downstream |
| 4. IR Gen | `ir/gen/*.btrc` | AST + Analyzed → IRModule | `--emit-ir` |
| 5. Optimizer | `ir/optimizer.btrc` | IRModule → IRModule | `--emit-optimized-ir` |
| 6. Emitter | `ir/emitter.btrc` | IRModule → C text | default output |

`ast_nodes.btrc` is generated from `src/language/ast/ast.asdl` by
`src/language/ast/asdl_btrc.py` (`make ast-generate-btrc`) — the same single
source of truth the Python AST is generated from.

## AST representation: fat tagged node (not a class hierarchy)

btrc does not (yet) support dynamic dispatch through a base-typed reference,
base→subclass downcasting, or interface-typed variables — a method called on a
`Base` reference always runs `Base`'s method, even when it holds a subclass.
So the Python compiler's polymorphic AST (isinstance/override traversal) cannot
be ported directly. The self-hosted AST is instead **one fat `Node` struct**
with a `kind` (NodeKind) tag and the union of all fields, dispatched via
`if (n.kind == NK_X)`. Every field is reachable on every node, so no downcast is
needed. This is the C-idiomatic AST and is byte-output-neutral (the AST is
internal; only the emitted C must match the Python compiler). `asdl_btrc.py`
generates this fat-node form. (The underlying language gap is tracked as a
btrc issue; fixing dynamic dispatch would later allow a more faithful port.)

## Canonical AST dump

`--emit-ast` is Python `pprint` (not reproducible). For parser verification both
compilers emit a stable indented S-expression instead: `--emit-ast-canon`
(Python: `src/compiler/python/ast_canon.py`, generic via reflection; btrc:
generated from ast.asdl per node kind so the field order/format match exactly).

## Verification harness

`src/compiler/btrc/verify.sh <emit-flag>` compiles `btrcc`, then for every
`.btrc` in the corpus runs both compilers with the flag and diffs. A stage is
"done" when its flag diffs clean across the whole corpus.

## Notable porting decisions / risks

- **`--emit-tokens` format.** Python prints `repr(token)` =
  `Token(TYPE, 'value', line:col)` using Python's `repr()` for the value (single
  quotes, switching to double quotes when the value contains a `'`, with escape
  rules). `tokens.btrc` reproduces this with a small `py_repr(string)` helper.
  (The *real* invariant is byte-identical C; `--emit-tokens` parity is the
  stage-1 aid.)
- **No regex.** `ebnf.py` uses `re` for brace-block extraction and token
  scanning; the btrc port uses manual character scanning (the EBNF block
  extractor is already a hand-written scanner — mirror it).
- **No hardcoded keyword/operator lists** (CLAUDE rule) — the btrc lexer parses
  `grammar.ebnf` at startup just like the Python one. Keyword/operator → token
  mapping is derived (`_op_to_token_name`, `kw.upper()`), not tabulated.
- **char type.** btrc has `char`; `s[i]` yields a char and `Strings.isDigit/
  isAlpha/isSpace/isAlnum(char)` classify. The port works in chars, not slices.
- **State machines as classes.** Lexer/Parser are stateful classes (pos, line,
  col) — direct translation of the Python classes.

## Phased plan

1. **Stage 1 (in progress):** tokens + EBNF + lexer; `--emit-tokens` parity.
2. **Stage 2:** recursive-descent parser over `ast_nodes.btrc`; `--emit-ast` parity.
3. **Stage 3:** analyzer (scopes, types, generic instances).
4. **Stages 4–6:** IR gen, optimizer, emitter; `--emit-ir` then byte-identical C.
5. **Bootstrap:** `btrcc` compiles its own source; verify fixed point.

Each phase lands only when its verification flag diffs clean across the corpus.
