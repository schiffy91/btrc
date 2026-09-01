# BTRC formatter

`btrc-format` is the syntax-validated BTRC style checker and writer. It parses
each input with the compiler frontend, formats through a lossless token/trivia
model, then proves the result preserves compiler tokens and comment contents.

```bash
# From this checkout.
nix develop -c btrc-format check src tests
nix develop -c btrc-format check --diff app.btrc
nix develop -c btrc-format write app.btrc

# From a pinned flake input.
nix run github:schiffy91/btrc#btrc-format -- check app.btrc
```

Directories are searched recursively for `.btrc` files in stable path order.
Check mode returns `0` when clean, `1` when files would change, and `2` for
usage, parse, read, or write failures. Write mode replaces changed files
atomically and preserves their permission bits.

## Default style

- Tabs; four columns are used only when tabs must be measured.
- Unlimited line width.
- Function/method signatures and control conditions occupy one physical line.
- Ordinary calls, assignments, returns, and expression statements occupy one
  physical line. Explicitly multiline collection/table literals retain their
  structural layout unless `--single-line-data` is set.
- An opening parenthesis stays with its construct. An explicitly multiline
  construct puts its closing parenthesis on its own line.
- Trivial bodies are compact, for example
  `public int getNumber() { return 0; }`.
- Consecutive functions have one blank line. Consecutive fields and both class
  edges have none.
- Imports form two stable groups: `std` imports first, then user BTRC imports
  and compatibility `#include` directives. Relative order within each group is
  retained, groups have one blank line between them, and entries within a group
  have none. C extern declarations are ordinary declarations, not imports.

## Overrides

Every default is a command-line option and applies identically in `check` and
`write` modes:

```text
--indent-style tabs|spaces
--indent-width N
--line-width N                         # 0 means unlimited
--[no-]single-line-signatures
--[no-]single-line-conditions
--[no-]single-line-statements
--[no-]single-line-data
--opening-paren same-line|next-line
--multiline-closing-paren own-line|same-line
--[no-]compact-trivial-functions
--blank-lines-between-functions N
--blank-lines-between-fields N
--blank-lines-after-class-opening N
--blank-lines-before-class-closing N
--blank-lines-between-import-groups N
--blank-lines-within-import-groups N
```

`--line-width` wraps signatures at parameter commas and conditions at top-level
boolean operators. An indivisible token may exceed the requested width. A line
comment inside a construct prevents that construct from being joined, because
joining would change which source the comment owns.
