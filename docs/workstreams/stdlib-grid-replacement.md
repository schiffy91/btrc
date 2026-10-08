# CX-STDLIB-04: preserve a grid cell on invalid replacement

Owner: Codex performance_review, assigned under PLAN D29 on 2026-10-08.
Branch: `codex/stdlib-grid-replacement`.
Base: `2202c0bd` on preserved `codex/qualify-linux-provider-repairs`.

Owned paths:

- `src/stdlib/GUI/Linux/LinuxGrid.btrc`
- `src/stdlib/GUI/Linux/LinuxView.btrc`: extract the existing LinuxViewNode child-attachment preconditions for validation before replacement mutates ownership.
- `src/tests/native/gui/layout/linux/LinuxGridReplacement.btrc`
- `src/tests/python/test_native_ui_grid_replacement.py`
- This report.

The existing 96-row Linux input/layout/scrollbar recipe and its source branch remain unchanged. This packet adds one real grid replacement journey across both frontends and plain/sanitized variants (four rows). It must preserve the old child's identity, attachment and rendered pixels after rejecting an already-parented replacement, then prove valid replacement, null clear and ownership cleanup. Closed-child and cycle rejection exercise the same precondition boundary.

Baseline source finding: LinuxGrid.setChild detaches and clears the old cell before LinuxViewNode.attachChild validates the replacement. MacOSGrid.setChild validates attachment before detaching. Capture a fixture-only red checkpoint before the production change; native red and green execution waits for the parent-owned Linux lane. No native test, build, guest or acceptance is claimed by this source-only claim.

Initial free space: 79,788,376 KiB (81.7 GB). G12 owns the native lane. Final provider, strict-import, fixture-discovery and native admission evidence remain pending; no PLAN, generated file or expected-skip fragment is changed here.
