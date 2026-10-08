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

## Results

The initial 14 regression cases produced 11 failures and three passes before the
repair. In particular, the observed unittest excerpt yielded `(failures=2)`
instead of the two class/method identities. Four later adversarial cases also
failed before their fixes: parameter IDs containing spaces, diagnostics inside a
unittest traceback, a separate collection error, and a same-depth Make failure.

The initial implementation's focused module run passed **79 tests in 19.24
seconds**; independent review then found two additional defects, recorded below.

```sh
python3 -m pytest -q -o addopts= src/tests/python/test_runbook_engine.py
```

It covers the parser and an actual fake-hub run proving that even an allowance
containing every test ID cannot permit a link failure or advance the fake
BTRSmith upstream. Existing retry, checkpoint, subset and push tests remain
green. Ruff lint/format and `git diff --check` pass. The Python runtime is the
already-realized qualified `35r726j0hx21698i9p7ry53l1afprc84` Nix environment;
no environment realization, compiler build, native GUI or benchmark ran.

A read-only replay of the retained Stage 2 release log (SHA-256
`772c88a371df315cf69b2d9f6b67927f45b1b753b28fe7efa1fe07af7eaed3b5`)
identified two real unittest failures and still rejected qualification. It
recorded 38 non-test/unclassified diagnostic lines: one infrastructure, one
compile, eight link and 28 unclassified records. These are diagnostic records,
not 38 independent root causes; nested Make propagation can repeat a failure.
Private product logs and identities are not copied into this public repository.
No baseline allowance was created or changed, and the Stage 4 preset continues
using the repaired default reader without a new result format.

## Independent-review corrections

Review found that a retry intersected its named failures with an earlier
incomplete command. A linker failure plus allowed test A, followed by a complete
run with new test B, could erase B and incorrectly allow the push. The regression
reproduced that push into the isolated fake upstream. Attempts now retain their
raw results and log paths in `attempt_history`; only eligible complete attempts
participate in the intersection. A single eligible attempt retains every named
failure. The corrected end-to-end regression proves that B remains new, the
subset fails and the fake upstream does not advance, while the first attempt's
link diagnostic remains in the checkpoint.

Review also found that ` - ` inside a pytest parameter ID was truncated as a
message delimiter, allowing distinct tests to collide. The default reader now
recognizes delimiters only outside balanced brackets; ambiguous bracket syntax
fails closed. Before these corrections, the focused cases produced **three
failures and one pass**. Afterward those four cases passed; additional malformed
identity cases also pass. The complete module now passes **85 tests in 33.87
seconds**, with Ruff lint/format and `git diff --check` passing. These are pure
Python tests using the same already-realized runtime; no native build ran.

## Timing and remaining work

Implementation and review ran between 16:50:53 and 17:10:14 UTC, with a read-only
pause while the integrator held the UI2 native gate. These are elapsed interval
endpoints, not a claim that the whole interval was active implementation. This
packet ran no gate or native build. Review corrections and their final checks
finished at 17:19:35 UTC after the initial 17:10:14 checkpoint; the final pure
Python suite took 33.87 s. Final review, publication under the CI cap and combined qualification
remain with the integrator. The actual Stage 4 pin/release requalification is
still open; repairing its result reader does not qualify the product.
