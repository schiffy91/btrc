#!/bin/bash
# One cold module-unit compile of the BTRSmith copy, for native_build.py,
# cmp_units.py and other studies of the emitted units:
#
#   gen_units.sh <btrcc> <outdir> [jobs]
#
# Writes <outdir>/out/p.c, p.unit-*.c and p.json, and <outdir>/timing.txt.
# BTRC_REPO, BSM_WORKSPACE and BTRC_TARGET as in instr.sh.
set -u
here=$(cd "$(dirname "$0")" && pwd)
if [ -z "${BSM_ENV_ACTIVE:-}" ]; then exec "$here/bsm_env.sh" "$0" "$@"; fi
BTRCC=$1 O=$2 JOBS=${3:-4}
case $O in /*) ;; *) O=$PWD/$O ;; esac
CACHE=${BTRC_BENCH_HOME:-$HOME/.cache/btrc}
R=${BTRC_REPO:-$(cd "$here/../../.." && pwd)}
rm -rf "$O"
mkdir -p "$O/cache" "$O/out"
cd "${BSM_WORKSPACE:-$CACHE/bsm-measure}" || exit 2
start=$(python3 -c "import time; print(time.time())")
BTRC_TIMING=1 BTRC_HOME="$R/src" BTRC_CACHE_DIR="$O/cache" "$BTRCC" --strict-imports \
  --target "${BTRC_TARGET:-macos-arm64}" --debug --emit-link-plan "$O/out/p.json" --emit-units "$O/out/p" \
  --module-units --jobs "$JOBS" src/BTRSmith.btrc -o "$O/out/p.c" > /dev/null 2> "$O/timing.txt"
rc=$?
echo "compile rc=$rc wall=$(python3 -c "import time; print(round(time.time() - $start, 2))")s"
exit $rc
