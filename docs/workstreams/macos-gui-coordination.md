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

Claimed before implementation. Native GUI remains blocked by the observed
loginwindow context. Pure-process baseline and corrected proof pending; no GUI
launch, compiler build or hosted dispatch is part of this step.
