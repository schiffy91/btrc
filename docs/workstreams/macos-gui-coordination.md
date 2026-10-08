# Main-based AppKit coordination qualification

Base: `49f136ec94bb46cf67dd9bf407df6e4b0d79332c`. Reviewed source donor: `ade99447cedef6cdbb5bccdf64180fc710627f56`.

This packet transplants only the ten Python test/harness deltas below onto main;
unrelated compiler-cache flags from the donor parent are excluded. No compiler,
stdlib/provider, native fixture, assertion, timeout or expected-skip change is included.
Current-source process and hosted native qualification are **pending**.

PR69 (`f01ec0ff9c025b56feacf28a304659f286d57f9c`) failed hosted native GUI
run 37738227455 / job 113182639729: 326 passed, 67 skipped and one selfhost
Portable sanitized WebGPU failure, SIGABRT in PortableGPUJourney_run. The old
artifacts retained JUnit but not Program.c. The generated assertion ordinal does
not identify its source predicate. The coordination defect is independently
reproduced below; it is not yet the demonstrated cause of that GPU failure.

Owned source paths:

- `src/tests/conftest.py`
- `src/tests/python/test_macos_gui_coordination.py`
- `src/tests/python/test_native_app_runtime.py`
- `src/tests/python/test_native_control_sizing_runtime.py`
- `src/tests/python/test_native_gui_appkit.py`
- `src/tests/python/test_native_objective_c_delegates.py`
- `src/tests/python/test_native_pointer_runtime.py`
- `src/tests/python/test_native_tray_runtime.py`
- `src/tests/python/test_native_ui_shell_macos.py`
- `src/tests/python/test_native_webgpu_imports.py`

## Historical evidence (not current qualification)

# macOS GUI worker coordination

Packet: macos-gui-coordination. Owner: Codex, integrator-assigned under D29.
Branch: `codex/macos-shell-lifecycle`, baseline `08d77b32`.
Owned paths: the exact reservation in WORKSTREAMS.md §3.3.2.

## Baseline and contract

`Makefile` defaults to eight pytest workers; `.github/workflows/macos.yml`
runs the focused native GUI gate with three. Neither groups GUI cases.
`src/tests/conftest.py` owns a POSIX advisory lock for compiler cache builds,
but does not coordinate AppKit execution. Separate workers can run shell,
AppKit controls, pointer/sizing, tray, WebGPU child and Objective-C delegate
programs while the shell's independent control requires actual active/key
state. This is a source-proven concurrency hole, not proof that contention
caused the retained activation-policy exception or loginwindow failures.

The existing outer `gui-capture` lease remains external. A distinct shared
checkout lease will serialize marked AppKit tests, including fixture setup and
teardown, without taking that outer lock again. Other tests remain parallel.
Waiting is bounded and reports the current holder. Exceptions and process death
release the kernel lock; stale text is never treated as ownership. Native GUI
assertions, deadlines, provider counters and skip admission remain unchanged.

The explicit execution inventory excludes compile-only ownership checks,
headless WebGPU, raster text and image decoding. Every known AppKit application,
window and tray execution is marked; the collection contract checks those cases.
Independent pytest processes will exercise exclusion, unmarked progress,
exception and process-death release. A separate contender exercises bounded
waiting and holder diagnostics. These are coordination tests, not GUI evidence.

## Historical local validation

Claim `2ec3774d` preceded source edits, at 2026-10-08 01:34:43 UTC.
The process baseline on unchanged conftest/driver owners failed because the
contender entered while the first marked process still held its journey; the
inventory guard also failed. Result: **2 failed, 3 passed in 1.98 s**.
Evidence: `~/.cache/btrc/plan-consolidation-2026-10-07/macos-gui-coordination/baseline.log`
and `baseline.xml`.

The repaired owner is the existing `_exclusive` context manager: optional
bounded nonblocking acquisition, holder PID/node metadata written only after
acquisition, and the original blocking default for compiler-cache users.
`_macos_gui_session` is an autouse function fixture that activates only for
`macos_gui` on Darwin. It uses
`.pytest_cache/d/macos-gui/execution.lock`; the cache root is shared by workers
and concurrent pytest processes in this checkout. It covers function fixture
setup, body and teardown. It does not create a second host-level GUI lock.
The 1800-second acquisition bound produces a failure with lock path and last
recorded holder, not a skip or permission request. Do not delete this cache
while tests run: removing an active advisory-lock file invalidates coordination.
Higher-scope fixtures in the marked modules only prepare exports/compiler data;
actual AppKit launches occur in their protected function bodies.

Final focused pure result: **7 passed in 4.58 s** (`corrected-3.log/xml`).
The process cases exercise actual kernel locking through separate pytest
interpreters, setup/teardown exclusion, ordinary-worker progress, non-Darwin
concurrency, exception/process-death release and a real 0.2-second contender
timeout with holder diagnostics. On POSIX the fixture owner's platform view is
explicitly set to Darwin for this test; the Python interpreter/platform itself
is unchanged. Windows exercises its unchanged non-Darwin passthrough.
The inventory audit collects actual parameterized test items from the eight
marked modules and checks every case belonging to the 15 known execution
functions. No compiler or native fixture is executed by collection.

Existing harness-selection checks also passed: **15 passed in 0.06 s**
(`harness-selection.log/xml`). Ruff lint, formatting and `git diff --check` passed. Pure validation used the
qualified Python 3.14.6 environment; before execution, available space was
81.70 GB. Source/validation work completed at approximately 01:40 UTC; native
work waited for the G12 lane throughout, and none ran in this packet.
At that local checkpoint, native GUI was blocked by the observed loginwindow context. That proof was
coordination evidence only: it does not resolve the original activation-policy
exception or qualify the lifecycle changes on an unlocked/hosted desktop.
No GUI launch, compiler build, guest, hosted dispatch or assertion/skip change
was made during that initial local packet.


## Main-based hosted qualification, 2026-10-08

Source `13e147edf4ec2dc921ee1a6bb5f3baff5f1a9520` isolates the AppKit
coordination changes on main `49f136ec94bb46cf67dd9bf407df6e4b0d79332c`.
Diagnostic child `6b845c2991eaf1559de97575691705150632e1d4` adds only
its immutable qualification recipe. [Run 37745915293](https://github.com/schiffy91/btrc/actions/runs/37745915293)
completed successfully.

- The unchanged main baseline with the new tests has the two required
  coordination/inventory assertion failures, with no errors or skips. The
  repaired owner passes all seven coordination cases.
- Original `make NIX= PYTEST_WORKERS=3 BTRC_TEST_TRANSPILE_TIMEOUT=600
  BTRC_TEST_RUN_TIMEOUT=60 test-native-gui` passes: 327 passed, 67 expected
  skips, zero failures/errors. The exact 394 collected identities executed.
- All eight native GPU pixel cases pass, including the self-hosted portable
  sanitized case that failed in the earlier plan-only run. This is not proof
  of the historical failure's cause.
- The original enforced skip gate passes. It records 65 skipped rows covered
  by another runner and two explicitly uncovered Linux-native-reader rows;
  none is presented as macOS execution.
- Two independent reviews verify all 4,374 production-source files against
  their Git blob IDs, bytes and modes, unchanged source/tool inventories,
  original commands, and the three diagnostic input hashes.

Artifact `11538891327` is 174,524,129 bytes with SHA-256
`07e0cabe6f83b4b854b1391dd578b26b4a1b1493a87858b097a97a9d55e365f9`.
The complete ZIP and bounded receipts remain in
`~/.cache/btrc/plan-consolidation-2026-10-07/macos-gui-lease-main49-hosted/`.
The 31 retained generated Program.c units are diagnostic evidence, not tracked
build outputs. This result qualifies the affected AppKit gate; final combined
PR gates, main integration and the full product roadmap remain separate.


## Follow-up fixture isolation

The later Linux baseline diagnostic exposed pytest configuration discovery in
nested archived trees: child pytest loaded the ancestor candidate's pythonpath
and imported its fixture owner while the outer test belonged to the baseline.
A real process reproduction records both imported paths and reproduces the
incorrect baseline pass. The shared test pattern now pins the intended pytest
configuration and cache and verifies the imported owner's absolute path and
SHA-256. Exclusion waits for actual contention on the intended kernel lock or
body entry, so process setup is not treated as proof of lock acquisition.
The seven Mac coordination cases retain their original assertions; safe process
group cleanup also reaps a completed leader before checking its descendants.
The production AppKit lease and native test bodies remain exactly those from
`13e147ed`. This fixture follow-up does not relabel the earlier native run as
execution of new test source. Its focused result and combined PR CI are recorded
with the new candidate.
