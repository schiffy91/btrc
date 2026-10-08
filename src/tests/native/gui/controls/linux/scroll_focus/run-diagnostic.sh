#!/bin/bash
set -euo pipefail
cd /workspace
export PYTHONDONTWRITEBYTECODE=1
export BTRC_TEST_RUNNER=linux-devcontainer
unset MAKEFLAGS PYTEST_ADDOPTS BTRC_TIMING
export BTRC_TEST_BTRCC=/workspace/donor/B/bin/btrcc
export ALSA_CONFIG_PATH=/workspace/nix/asound.conf
printf '%s  %s\n' "$EXPECTED_BASELINE_BTRCC_SHA256" "$BTRC_TEST_BTRCC" | sha256sum -c -
test "$(uname -s)-$(uname -m)" = Linux-x86_64
test -n "$BTRC_NATIVE_HEADER_READER"
test -x "$BTRC_TEST_BTRCC"
cc --version > evidence/cc-version.txt
sha256sum "$(command -v cc)" "$BTRC_NATIVE_HEADER_READER" > evidence/native-tools.sha256
python3 --version > evidence/python-version.txt
fixture=src/tests/python/test_native_ui_scroll_focus_diagnostic.py
shell=src/tests/python/test_native_ui_shell_linux.py
failed=0
for stage in controlled isolated concurrent; do
  args=(-q -vv -ra -x --basetemp="evidence/$stage/pytest" --junitxml="evidence/$stage/junit.xml" -o cache_dir=/workspace/evidence/cache)
  nodes=()
  if [ "$stage" = controlled ]; then
    expected=1
    nodes+=("$fixture::test_scroll_focus_diagnostic[focus-loss-plain-python]")
  else
    expected=8
    # Do not stop after an original failure: retain each positive row and the
    # later concurrent evidence. No individual failure is accepted as a pass.
    args=(-q -vv -ra --basetemp="evidence/$stage/pytest" --junitxml="evidence/$stage/junit.xml" -o cache_dir=/workspace/evidence/cache)
    for mode in original trace; do
      for sanitizer in plain sanitized; do
        for frontend in python selfhost; do
          nodes+=("$fixture::test_scroll_focus_diagnostic[$mode-$sanitizer-$frontend]")
        done
      done
    done
    if [ "$stage" = concurrent ]; then
      expected=12
      args+=(-n4 --dist=loadgroup)
      nodes+=("$shell::test_linux_native_shell")
    fi
  fi
  mkdir -p "evidence/$stage"
  set +e
  timeout --kill-after=10s 2400s tools/ui/headless-session.sh --x11 -- \
    python3 -m pytest "${args[@]}" "${nodes[@]}" \
    > "evidence/$stage/stdout.log" 2> "evidence/$stage/stderr.log"
  status=$?
  set -e
  printf '%s\n' "$status" > "evidence/$stage/status"
  printf 'X11_DIAGNOSTIC_STAGE stage=%s exit=%s\n' "$stage" "$status"
  if [ "$status" -ne 0 ]; then
    # Preserve actual failures in the job log even if artifact transport fails.
    tail -n 180 "evidence/$stage/stdout.log" || printf 'Unable to read retained stdout for %s\n' "$stage"
    tail -n 80 "evidence/$stage/stderr.log" || printf 'Unable to read retained stderr for %s\n' "$stage"
  fi
  test "$status" -le 1
  python3 - "$stage" "$expected" <<'PY'
import json,sys,xml.etree.ElementTree as ET
from pathlib import Path
stage,expected=sys.argv[1:]
root=Path('evidence')/stage
cases=list(ET.parse(root/'junit.xml').iter('testcase'))
assert len(cases)==int(expected),(stage,len(cases),expected)
assert not any(c.find('skipped') is not None or c.find('error') is not None for c in cases), 'Missing capability or setup errors do not qualify'
result={'stage':stage,'native_window_overlap': 'unproven' if stage=='concurrent' else 'not-applicable', 'interpretation': 'scheduling-attempt-only' if stage=='concurrent' else 'bounded-fixture-observation', 'cases':[{'name':c.attrib,'failed':c.find('failure') is not None} for c in cases]}
(root/'classification.json').write_text(json.dumps(result,indent=2)+'\n')
print('X11_DIAGNOSTIC_CLASSIFICATION '+json.dumps(result,sort_keys=True))
PY
  if [ "$status" -ne 0 ]; then failed=1; fi
  # An invalid controlled negative cannot establish the causal mechanism.
  if [ "$stage" = controlled ]; then test "$status" -eq 0; fi
done
sha256sum --check evidence/source-inputs.sha256 > evidence/source-after.log
printf '%s  %s\n' "$EXPECTED_BASELINE_BTRCC_SHA256" "$BTRC_TEST_BTRCC" | sha256sum -c - > evidence/compiler-after.log
exit "$failed"
