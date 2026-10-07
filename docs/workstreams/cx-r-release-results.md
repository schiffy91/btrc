# CX-R-RELEASE-RESULTS: identify release-check failures

Owned paths: `tools/runbook/engine.py`,
`tools/runbook/presets/stage4-requal.toml`, `tools/runbook/README.md`,
`src/tests/python/test_runbook_engine.py`, and this report.

Branch: `codex/btrsmith-release-results`. Base: `ba6c221d`.
The integrator reserved these paths on 2026-10-07; publication waits for its
available CI slot. No compiler, product or baseline allowance changes belong here.

The release-check reader currently treats unittest's aggregate
`FAILED (failures=2)` as a test named `(failures=2)`. Identify actual unittest
failure headers and pytest node IDs instead. Resolve unittest `__main__` only
against an observed Python test-script command; unknown provenance fails closed.
Compilation, linking, infrastructure and otherwise unclassified failures remain
separate and block qualification even when every named test is allowed.

Acceptance: deterministic tests reproduce the wrong summary identity, verify
stable class/method identities and script provenance, preserve pytest/custom
formats, and reject mixed test/build failures and unknown failures. The real
historical release log is diagnostic input only: its additional build failures
prevent it from qualifying as a test-only allowance. No source TSV may substitute
for release-check results, and this packet creates no baseline allowance file.

Started 2026-10-07 at 16:50:53 UTC. Initial free space: 83,268,829,184 bytes.
Only lightweight pure Python tests are authorized in this lane; native execution
and full combined qualification stay with the integrator.
