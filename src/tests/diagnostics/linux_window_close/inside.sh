#!/bin/bash
set -euo pipefail
cd /workspace
export GITHUB_WORKSPACE=/workspace PYTHONDONTWRITEBYTECODE=1 BTRC_TEST_RUNNER=linux-devcontainer
unset BTRC_TEST_BTRCC BTRC_HOME BTRC_TIMING BTRC_CFLAGS PYTEST_ADDOPTS PYTEST_ARGS MAKEFLAGS
export GIT_CONFIG_COUNT=3
export GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=/workspace/compiler
export GIT_CONFIG_KEY_1=safe.directory GIT_CONFIG_VALUE_1=/workspace/provider
export GIT_CONFIG_KEY_2=safe.directory GIT_CONFIG_VALUE_2=/workspace
packet=/workspace/provider/src/tests/diagnostics/linux_window_close
finish() {
  code=$?
  trap - EXIT
  set +e
  python3 "$packet/run-stage.py" --seconds 120 --label closure -- python3 "$packet/qualify.py" close > evidence/closure.stdout 2> evidence/closure.stderr
  closed=$?
  if [ "$code" -ne 0 ] || [ "$closed" -ne 0 ]; then exit 1; fi
  exit 0
}
trap finish EXIT
python3 "$packet/run-stage.py" --seconds 120 --label inputs -- python3 "$packet/qualify.py" start > evidence/inputs.stdout 2> evidence/inputs.stderr
python3 "$packet/run-stage.py" --seconds 2400 --label compiler_build -- make -C compiler -j1 NIX= btrcc > evidence/compiler-build.stdout 2> evidence/compiler-build.stderr
python3 "$packet/run-stage.py" --seconds 120 --label compiler_receipt -- python3 "$packet/qualify.py" build > evidence/compiler-receipt.stdout 2> evidence/compiler-receipt.stderr
export BTRC_TEST_BTRCC=/workspace/compiler/bin/btrcc
for role in B C; do
  set +e
  (cd "$role" && python3 "$packet/run-stage.py" --seconds 2400 --label "${role}_native" -- /workspace/compiler/tools/ui/headless-session.sh --x11 -- python3 -m pytest -c "/workspace/$role/pyproject.toml" --rootdir="/workspace/$role" -o "cache_dir=/workspace/evidence/$role-cache" -n 0 -q src/tests/python/test_native_ui_core_linux.py -k UI2LinuxWindowClose --basetemp="/workspace/evidence/$role-tmp" --junitxml="/workspace/evidence/$role.xml") > "evidence/$role.stdout" 2> "evidence/$role.stderr"
  status=$?
  set -e
  printf '%s\n' "$status" > "evidence/$role.status"
  expected=0
  if [ "$role" = B ]; then expected=1; fi
  test "$status" -eq "$expected"
  python3 "$packet/run-stage.py" --seconds 120 --label "${role}_classify" -- python3 "$packet/qualify.py" classify "$role" > "evidence/$role-classify.stdout" 2> "evidence/$role-classify.stderr"
done
