#!/bin/bash
# Run tools.budget_bench from a btrc tree outside Google Drive, in BTRSmith's
# dev shell (bsm_env.sh):
#
#   bench.sh <btrc-tree> <btrcc> <out> [budget_bench options...]
#
# <btrcc> may be "" with --frontend reference. The measured workspace is
# BSM_WORKSPACE (default ~/.cache/btrc/bsm-measure), which the harness copies;
# keep <out> under ~/.cache/btrc/bench.noindex/ (AGENTS.md "Measurements").
set -u
here=$(cd "$(dirname "$0")" && pwd)
TREE=$1 BTRCC=$2 OUT=$3
shift 3
WORKSPACE=${BSM_WORKSPACE:-${BTRC_BENCH_HOME:-$HOME/.cache/btrc}/bsm-measure}
cd "$TREE" || exit 2
arguments=(--workspace "$WORKSPACE" --out "$OUT")
if [ -n "$BTRCC" ]; then arguments=(--btrcc "$BTRCC" "${arguments[@]}"); fi
PYTHONDONTWRITEBYTECODE=1 exec "$here/bsm_env.sh" python3 -m tools.budget_bench "${arguments[@]}" "$@"
