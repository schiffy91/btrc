# BTRC handoff

**Checkpoint:** 2026-09-13, work is on `main`.

Read [`AGENTS.md`](../AGENTS.md) completely first. For product context, read
the sibling repository's [`docs/Handoff.md`](../../btrsmith/docs/Handoff.md)
and `GOAL.md`. The native contract is specified here and in
[`design/native-interop.md`](design/native-interop.md) plus
[`../src/language/package-manifest.md`](../src/language/package-manifest.md).

## Current state

The typed C/Objective-C/C++ import model, generated ABI adapters, ownership
primitives, native GUI/GPU surfaces, callback scopes, and realtime checks are
landed incrementally. Native-provider migration and final self-host
qualification are not complete. macOS providers are the active target;
Linux/Windows are future provider boundaries.

## Next sequence

1. Rebuild the next self-host compiler and qualify the switched CoreAudio
   provider and YAML guarded snapshots with optimized and sanitizer matrices.
2. Implement the vgmstream memory-stream callback-table owner and pugixml's
   checked load-once document factory using the existing contracts.
3. Re-run real consumers, then delete each superseded bridge and its build
   wiring. Keep no silent legacy fallback.
4. Hand the resulting provider revisions to BTRSmith for product integration
   and its visual/physical-audio gates.

Compiler/runtime failures belong to the BTRC owner with a reproducer. Consumer
work may proceed against approved interfaces while a foundation fix is in
flight. Preserve unrelated shared-main edits, stage exact files, and run the
gates covering each change. A failed signer/push is reported, not bypassed.
