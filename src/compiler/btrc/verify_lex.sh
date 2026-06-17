#!/usr/bin/env bash
# Stage-1 verification: the self-hosted btrc lexer's token output is byte-for-byte
# identical to the Python compiler's `--emit-tokens` across the corpus.
#
# Builds btrcc's lexer (btrcpy compiles lex_main.btrc -> C -> binary), then for
# every self-contained .btrc test file (no `import` / `#include "..."`, which the
# frontend would expand) diffs the two token streams.
set -u
cd "$(dirname "$0")/../../.." || exit 1   # repo root
BTRCPY="${BTRCPY:-python3 -m src.compiler.python.main}"
CC="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Building self-hosted lexer..."
$BTRCPY src/compiler/btrc/lex_main.btrc --no-cache -o "$work/lex.c" >/dev/null || { echo "transpile failed"; exit 1; }
$CC -std=c11 "$work/lex.c" -o "$work/btrclex" -lm -lpthread || { echo "C compile failed"; exit 1; }

total=0; match=0; fails=0
for f in $(find src/tests -name '*.btrc' | sort); do
  grep -qE '^[[:space:]]*import|#include "' "$f" && continue
  total=$((total + 1))
  "$work/btrclex" "$f" > "$work/a" 2>/dev/null
  $BTRCPY "$f" --emit-tokens --no-stdlib > "$work/b" 2>/dev/null
  if diff -q "$work/a" "$work/b" >/dev/null 2>&1; then
    match=$((match + 1))
  else
    fails=$((fails + 1)); echo "MISMATCH: $f"
  fi
done
echo "lexer parity: $match / $total byte-identical"
[ "$fails" -eq 0 ]
