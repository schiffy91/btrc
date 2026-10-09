#!/bin/bash
# Instructions retired and peak footprint of one cold single-process BTRSmith
# module-unit compile (macOS /usr/bin/time -l), the noise-free comparison
# docs/design/compile-performance.md "Measuring a compile" asks for:
#
#   instr.sh <btrcc> <tag>
#
#   BTRC_REPO      the tree whose stdlib the binary is paired with
#                  (default: the repository holding this script)
#   BSM_WORKSPACE  the BTRSmith copy (default ~/.cache/btrc/bsm-measure); it is
#                  compiled in place but never edited
#   BTRC_TARGET    default macos-arm64
#
# Evidence goes to ~/.cache/btrc/perf/instr-<tag>/. budget_bench's memory
# scenario records the same counters inside a full run.
set -u
here=$(cd "$(dirname "$0")" && pwd)
if [ -z "${BSM_ENV_ACTIVE:-}" ]; then exec "$here/bsm_env.sh" "$0" "$@"; fi
BTRCC=$1 TAG=$2
CACHE=${BTRC_BENCH_HOME:-$HOME/.cache/btrc}
R=${BTRC_REPO:-$(cd "$here/../../.." && pwd)}
O=$CACHE/perf/instr-$TAG
rm -rf "$O"
mkdir -p "$O/cache" "$O/out"
cd "${BSM_WORKSPACE:-$CACHE/bsm-measure}" || exit 2
BTRC_HOME="$R/src" BTRC_CACHE_DIR="$O/cache" /usr/bin/time -l "$BTRCC" --strict-imports \
  --target "${BTRC_TARGET:-macos-arm64}" --debug --emit-link-plan "$O/out/p.json" --emit-units "$O/out/p" \
  --module-units --jobs 1 src/BTRSmith.btrc -o "$O/out/p.c" > /dev/null 2> "$O/time.txt"
echo -n "rc=$? "
printf '%-10s instructions=%s peak-footprint=%s real=%s\n' "$TAG" \
  "$(awk '/instructions retired/ {print $1}' "$O/time.txt")" \
  "$(awk '/peak memory footprint/ {print $1}' "$O/time.txt")" \
  "$(awk '/ real / {print $1}' "$O/time.txt")"
