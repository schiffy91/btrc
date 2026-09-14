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

1. Done 2026-09-13: fresh self-host compiler qualifies the switched CoreAudio
   realtime registration (28 cases) and the new unique C callback table
   (`resources.<record>.table`, 18 cases per frontend); vgmstream's
   handwritten adapter is deleted. Evidence is listed in
   `design/native-interop.md` and BTRSmith's
   `build/evidence/VgmstreamCallbackTable.md`.
2. Done 2026-09-13: pugixml's checked load-once owner. `language = "c++"`
   bindings project opaque unique owners, owner-bound views and copied
   strings through one generated `extern "C"` adapter unit in both compilers
   (`src/tests/python/test_native_cxx_owners.py`, 9 cases per frontend on
   fresh self-host compiler `8b49c232195c7d1caa6c5360751c4781`); BTRSmith's
   handwritten pugixml adapter is deleted.
3. Structure first (2026-09-13 evening, user direction): the stdlib is a closed
   root prelude plus group folders with same-named facades and `I`-prefixed
   platform contracts (`src/stdlib/README.md`); the BTRC-drawn toolkit is
   `Library.UI` (formerly `NativeUI`); each stdlib group gets its own
   `btrc.toml` and the root manifest depends on those packages (extend
   `with_stdlib`/`includeStdlib` in both compilers); then every other BTRC
   directory (tests, tools, examples, nix files, docs) is reviewed against the
   same standard. The exact order is BTRSmith's `docs/NativePlatformPlan.md`.
4. Re-run real consumers on the final tree, then delete any superseded bridge
   and its build wiring. Keep no silent legacy fallback.
5. Hand the resulting provider revisions to BTRSmith for product integration
   and its visual/physical-audio gates.

Compiler/runtime failures belong to the BTRC owner with a reproducer. Consumer
work may proceed against approved interfaces while a foundation fix is in
flight. Preserve unrelated shared-main edits, stage exact files, and run the
gates covering each change. A failed signer/push is reported, not bypassed.
