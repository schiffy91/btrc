#!/bin/bash
# The D5 batch gate (PLAN.md): every check, sequentially, one log each.
#
#   batch_gate.sh <btrc-clone> <logdir> [base-ref] [btrsmith-clone] [--no-c11]
#
# Run it under the gate lock: withlock.sh gate batch_gate.sh ... Exit codes,
# durations and test counts go to <logdir>/summary.txt. The BTRSmith checks use
# that clone's flake with btrc overridden to <btrc-clone> (a diagnostic-only
# pin). test-c11 is rerun once when only the daemon wall-clock deadline failed.
set -u
C11=1
positional=()
for argument in "$@"; do
  if [ "$argument" = --no-c11 ]; then C11=0; else positional+=("$argument"); fi
done
if [ ${#positional[@]} -lt 2 ]; then
  echo "usage: batch_gate.sh <btrc-clone> <logdir> [base-ref] [btrsmith-clone] [--no-c11]" >&2
  exit 64
fi
REPO=${positional[0]} LOG=${positional[1]} BASE=${positional[2]:-origin/main} BSM=${positional[3]:-}
mkdir -p "$LOG"
cd "$REPO" || exit 2
S="$LOG/summary.txt"
echo "tree $(git rev-parse --short HEAD) base $(git rev-parse --short "$BASE") dirty=$(git status --porcelain | wc -l | tr -d ' ') start=$(date '+%F %T')" > "$S"
gate_start=$(date +%s)
failed=""
step() { # step <name> <command...>
  local name=$1 started counts rc
  shift
  started=$(date +%s)
  "$@" > "$LOG/$name.log" 2>&1
  rc=$?
  counts=$(grep -aE "[0-9]+ (passed|failed)" "$LOG/$name.log" | tail -1)
  if [ "$name" = test-c11 ]; then
    counts="$(grep -acE '^[0-9]+ passed' "$LOG/$name.log") configs passed; $(grep -aE '^[0-9]+ (passed|failed)' "$LOG/$name.log" | tr '\n' ';')"
  fi
  echo "$name exit=$rc $(($(date +%s) - started))s $counts" >> "$S"
  [ $rc -ne 0 ] && failed="$failed $name"
  return $rc
}
dev() { nix develop "$REPO" --command "$@"; }
step diff-check git diff --check "$BASE" HEAD
step lint dev make lint
step format-check dev make format-check
step generated-check dev make generated-check
step extension dev make extension
step test dev make test
step bootstrap dev make bootstrap
if [ $C11 = 1 ]; then
  step test-c11 dev make test-c11
  if [ $? -ne 0 ] && grep -aq 'daemon did not confirm termination before the deadline' "$LOG/test-c11.log" \
    && ! grep -aE '^FAILED' "$LOG/test-c11.log" | grep -vq 'Daemon'; then
    mv "$LOG/test-c11.log" "$LOG/test-c11.first.log"
    echo "test-c11 rerun: only the daemon deadline failed" >> "$S"
    failed="${failed/ test-c11/}"
    step test-c11 dev make test-c11
  fi
fi
if [ -n "$BSM" ]; then
  cd "$BSM" || exit 2
  override=(--override-input btrc "path:$REPO")
  step bsm-frontend-check nix develop . "${override[@]}" --command make application-frontend-check
  for frontend in reference selfhost; do
    step "bsm-library-smoke-$frontend" nix develop . "${override[@]}" --command make btrsmith-library-smoke BTRC_FRONTEND=$frontend
  done
  rm -rf build/tests
fi
echo "total $(($(date +%s) - gate_start))s result=$([ -z "$failed" ] && echo GREEN || echo "RED:$failed") end=$(date '+%F %T')" >> "$S"
[ -z "$failed" ]
