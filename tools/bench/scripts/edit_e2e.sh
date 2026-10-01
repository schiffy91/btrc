#!/bin/bash
# End-to-end BTRSmith dev rebuilds with a given btrcc and btrc tree (native
# builder, stdlib): cold, two private function-body edits and a no-op. Each
# rebuild is compile (--module-units --debug, default workers) + native plan
# (-O0, -g, object cache, 8 jobs) + link, as budget_bench's dev builds are:
#
#   edit_e2e.sh <btrcc> <tag>
#
# The quick four-build check behind the 2026-09-24 evidence
# (~/.cache/btrc/perf/e2e-2026-09-24); budget_bench's edit scenarios are the
# sampled, verified measurement. BTRC_REPO, BSM_WORKSPACE and BTRC_TARGET as
# in instr.sh; evidence goes to ~/.cache/btrc/perf/e2e-<tag>/.
set -u
here=$(cd "$(dirname "$0")" && pwd)
if [ -z "${BSM_ENV_ACTIVE:-}" ]; then exec "$here/bsm_env.sh" "$0" "$@"; fi
BTRCC=$1 TAG=$2
CACHE=${BTRC_BENCH_HOME:-$HOME/.cache/btrc}
R=${BTRC_REPO:-$(cd "$here/../../.." && pwd)}
W=$CACHE/perf/e2e-$TAG
rm -rf "$W"
mkdir -p "$W/out" "$W/cache" "$W/objects"
cp -R "${BSM_WORKSPACE:-$CACHE/bsm-measure}" "$W/ws"
cd "$W/ws" || exit 2
now() { python3 -c "import time; print(time.time())"; }
build() {
  local tag=$1 t0 t1 t2 rc1 rc2
  t0=$(now)
  BTRC_TIMING=1 BTRC_HOME="$R/src" BTRC_CACHE_DIR="$W/cache" "$BTRCC" --strict-imports \
    --target "${BTRC_TARGET:-macos-arm64}" --debug --emit-link-plan "$W/out/p.json" --emit-units "$W/out/p" \
    --module-units src/BTRSmith.btrc -o "$W/out/p.c" > /dev/null 2> "$W/$tag.timing"
  rc1=$?
  t1=$(now)
  PYTHONPATH="$R" python3 -m tools.native_plan --plan "$W/out/p.json" --generated-c "$W/out/p.c" \
    --output "$W/out/BTRSmith" --cc clang --cxx clang++ --jobs 8 --debug-info --optimization 0 \
    --object-cache "$W/objects" --report-json "$W/$tag.native.json" > "$W/$tag.native.log" 2>&1
  rc2=$?
  t2=$(now)
  python3 "$here/e2e_report.py" "$tag" "$rc1" "$rc2" "$t0" "$t1" "$t2" "$W/$tag.native.json"
}
edit() {
  python3 - src/frontend/visualization/instrument/InstrumentCamera.btrc "$1" "$2" << 'PY'
import sys
from pathlib import Path

path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text()
assert old in text, "edit anchor missing"
path.write_text(text.replace(old, new, 1))
PY
}
build cold
edit "double offset = self.value - self.target;" "double offset = (self.value - self.target) * 1.0;"
build edit
edit "double offset = (self.value - self.target) * 1.0;" "double offset = (self.value - self.target) * 2.0;"
build edit2
build noop
