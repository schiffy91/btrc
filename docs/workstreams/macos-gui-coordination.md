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

## Status

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
Native GUI remains blocked by the observed loginwindow context. This proof is
coordination evidence only: it does not resolve the original activation-policy
exception or qualify the lifecycle changes on an unlocked/hosted desktop.
No GUI launch, compiler build, guest, hosted dispatch or assertion/skip change
was made. The existing focused hosted native-GUI lane can qualify the eventual
reviewed tree when the integrator's two-wave CI cap allows it.

Independent read-only review of source `ade99447` by the performance-review
agent found no actionable blocker in the lock lifecycle, existing compiler-lock
behavior, marked execution inventory, collection audit or process regressions.
The reviewer ran no tests/builds. Native GUI and full-matrix qualification remain
pending; this review does not upgrade the pure coordination proof to GUI evidence.
