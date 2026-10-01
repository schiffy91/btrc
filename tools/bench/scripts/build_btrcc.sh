#!/bin/bash
# Build a clang -O2 btrcc from a btrc working tree, inside that tree's dev
# shell (which supplies the native header reader the macOS entry needs):
#
#   build_btrcc.sh <out-binary> [entry]
#
#   BTRC_REPO       the tree (default: the repository holding this script)
#   BTRC_DEV_SHELL  flake or saved profile for `nix develop` (default BTRC_REPO)
#   BTRCC_CC        the C compiler (default Apple's /usr/bin/clang: Nix's cc on
#                   macOS is gcc, whose emulated TLS slows btrcc ~20%; CLAUDE.md)
#
# Writes <out>.c, <out>.build.log and <out>. Building btrcc takes the two-slot
# semaphore: withlock.sh btrcc-build build_btrcc.sh ...
set -u
here=$(cd "$(dirname "$0")" && pwd)
R=${BTRC_REPO:-$(cd "$here/../../.." && pwd)}
OUT=$1 ENTRY=${2:-src/compiler/btrc/cli/MacOSMain.btrc}
case $OUT in /*) ;; *) OUT=$PWD/$OUT ;; esac
CC_FOR_BTRCC=${BTRCC_CC:-$([ -x /usr/bin/clang ] && echo /usr/bin/clang || echo clang)}
cd "$R" || exit 2
nix develop "${BTRC_DEV_SHELL:-$R}" --command bash -c '
export PYTHONDONTWRITEBYTECODE=1 BTRC_HOME="$PWD/src"
uv run python -m src.compiler.python.main "$2" --strict-imports --no-cache -o "$1.c" > "$1.build.log" 2>&1 \
  && "$3" -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 "$1.c" -o "$1" >> "$1.build.log" 2>&1 \
  && echo "BUILD OK $1 ($3)" || { echo "BUILD FAIL"; grep -v "^warning\|^ *-->\|^ *|\|^ *[0-9]* |" "$1.build.log" | tail -30; exit 1; }' \
  _ "$OUT" "$ENTRY" "$CC_FOR_BTRCC" 2>&1 | grep -v "^warning: \(Git tree\|ignoring\)"
exit "${PIPESTATUS[0]}"
