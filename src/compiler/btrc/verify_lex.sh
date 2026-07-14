#!/usr/bin/env bash
# Stage-1 verification: the self-hosted btrc lexer's token output is byte-for-byte
# identical to the Python compiler's `--emit-tokens` across the corpus.
#
# Builds btrcc's lexer (btrcpy compiles lex_main.btrc -> C -> binary), then for
# every self-contained .btrc test file (no imports or btrc-source includes,
# which the frontend would expand) diffs the two token streams.
set -euo pipefail
cd "$(dirname "$0")/../../.." || exit 1   # repo root
split_command() {
  python3 -c 'import shlex, sys
for arg in shlex.split(sys.argv[1]):
    sys.stdout.buffer.write(arg.encode() + b"\0")' "$1"
}
mapfile -d '' -t btrcpy_cmd < <(
  split_command "${BTRCPY:-python3 -m src.compiler.python.main}"
)
mapfile -d '' -t cc_cmd < <(split_command "${CC:-cc}")
if [ "${#btrcpy_cmd[@]}" -eq 0 ] || [ "${#cc_cmd[@]}" -eq 0 ]; then
  echo "BTRCPY and CC must name non-empty commands" >&2
  exit 2
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Building self-hosted lexer..."
"${btrcpy_cmd[@]}" src/compiler/btrc/lex_main.btrc --no-cache \
  -o "$work/lex.c" >/dev/null
"${cc_cmd[@]}" -std=c11 "$work/lex.c" -o "$work/btrclex" -lm -lpthread

total=0; match=0; fails=0
while IFS= read -r f; do
  if grep -qE '^[[:space:]]*import|^[[:space:]]*#include[[:space:]]*("[^"]*\.btrc"|<[^>]*\.btrc>)' "$f"; then
    continue
  fi
  total=$((total + 1))
  if ! "$work/btrclex" "$f" > "$work/a" 2>"$work/selfhost.err"; then
    fails=$((fails + 1))
    echo "SELFHOST LEXER FAILED: $f"
    sed 's/^/  /' "$work/selfhost.err"
    continue
  fi
  if ! "${btrcpy_cmd[@]}" "$f" --emit-tokens --no-stdlib \
      > "$work/b" 2>"$work/python.err"; then
    fails=$((fails + 1))
    echo "PYTHON LEXER FAILED: $f"
    sed 's/^/  /' "$work/python.err"
    continue
  fi
  if diff -q "$work/a" "$work/b" >/dev/null 2>&1; then
    match=$((match + 1))
  else
    fails=$((fails + 1)); echo "MISMATCH: $f"
  fi
done < <(find src/tests -name '*.btrc' -print | LC_ALL=C sort)
echo "lexer parity: $match / $total byte-identical"
[ "$fails" -eq 0 ]
