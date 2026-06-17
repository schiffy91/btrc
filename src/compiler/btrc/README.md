# Self-hosted btrc compiler (in progress)

A faithful port of the Python compiler (`src/compiler/python/`) into btrc, built
stage by stage and verified **byte-identical** to the Python reference at each
stage boundary. See [docs/design/self-hosting.md](../../../docs/design/self-hosting.md).

## Status

| Stage | Module | Status |
|---|---|---|
| 0. EBNF | `ebnf.btrc` | ✅ byte-identical (keyword/operator/annotation token maps) |
| 1. Lexer | `tokens.btrc`, `lexer.btrc` | ✅ `--emit-tokens` byte-identical across 398/398 self-contained corpus files |
| AST | `ast_nodes.btrc` | generated (`make ast-generate-btrc`) |
| 2. Parser | — | not started |
| 3. Analyzer | — | not started |
| 4–6. IR/opt/emit | — | not started |

## Files

- `ast_nodes.btrc` — AST node types, generated from `src/language/ast/ast.asdl`
  by `asdl_btrc.py` (`make ast-generate-btrc`). Do not edit by hand.
- `tokens.btrc` — `Token` + `pyRepr` (Python-repr-compatible value quoting) +
  `chr` (char→string). Token type is the type-NAME string.
- `ebnf.btrc` — `GrammarInfo` + `parseGrammar` (manual scanning, no regex).
- `lexer.btrc` — the tokenizer (grammar-driven; longest-first operator match).
- `lex_main.btrc` — CLI driver: lex a file, print tokens (mirrors `--emit-tokens`).
- `verify_lex.sh` — Stage-1 regression: diff the btrc lexer against btrcpy across
  the corpus (`make test-selfhost`).

## Running

```bash
make test-selfhost                      # build + verify the lexer against btrcpy
btrcpy src/compiler/btrc/lex_main.btrc -o /tmp/lex.c && cc -std=c11 /tmp/lex.c -o /tmp/btrclex
/tmp/btrclex some_file.btrc             # print its token stream
```

## btrc gotchas learned (for future stages)

- `string.substring(start, COUNT)` takes a length, not an end index — every
  Python `s[a:b]` becomes `s.substring(a, b - a)`.
- char→string: `f"{c}"` (string `+` char concatenation is unsupported).
- String methods are instance (`s.length()`, `s.indexOf(x)`, `s.substring(a,n)`,
  `s.toUpper()`); char classification is static (`Strings.isDigit(c)`, `isAlpha`,
  `isAlnum`, `isSpace`). Whole-file read: `Path.readAll(path)`.
- Map: `{}` literal, `.put(k,v)`, `.get(k)` (aborts on missing — guard with
  `.has(k)`). Vector: `[]`, `.push(x)`, `.get(i)`, `.len`, `.sortBy(lambda)`.
- Lambdas need typed params: `(string a, string b) => ...`.
