#!/bin/bash
# The goal's gate matrix on one tree, sequentially, one log per target:
#
#   gates.sh <repo> <logdir>
#
# <logdir>/summary.txt records each target's exit code, duration and test
# counts. batch_gate.sh is the fuller D5 batch gate.
set -u
REPO=$1 LOG=$2
mkdir -p "$LOG"
cd "$REPO" || exit 2
echo "tree $(git rev-parse --short HEAD) $(git status --short | wc -l | tr -d ' ') dirty" > "$LOG/summary.txt"
for target in lint format-check test bootstrap test-c11; do
  start=$(date +%s)
  make "$target" > "$LOG/$target.log" 2>&1
  rc=$?
  counts=$(grep -E "[0-9]+ (passed|failed)" "$LOG/$target.log" | tail -1)
  if [ "$target" = test-c11 ]; then
    counts="$(grep -cE "^[0-9]+ passed" "$LOG/$target.log") runs: $(grep -E '^[0-9]+ (passed|failed)' "$LOG/$target.log" | tr '\n' ';')"
  fi
  echo "make $target exit=$rc ($(($(date +%s) - start))s) $counts" >> "$LOG/summary.txt"
done
echo DONE >> "$LOG/summary.txt"
