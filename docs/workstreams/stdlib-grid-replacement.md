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

## Source checkpoint

Claim commit: `611711da`. Fixture-only checkpoint: `36b47db5`; it retains the old detach-before-validation provider. The expected first failure is the old cell identity assertion after rejecting an already-parented replacement. This is a preserved red source checkpoint, not an executed red result.

The repair extracts the existing open/parent/cycle checks into `LinuxViewNode.validateChild`. Both ordinary attachment and grid replacement call that same owner. Grid validates before detach; no field, queue, ordering, rendering or public interface contract changes. This prevents invalid-argument replacement from discarding the cell. It does not claim transactional rollback for arbitrary failures occurring after attachment starts.

The fixture checks cell identity and the actual node child list before capture, then reads back exact red/green/black pixels through the real LinuxWindow GPU renderer. It also checks the donor's child identity, closed-child rejection, same-child no-op, successful detachment rather than destruction, null clear, detached-grid self-cycle rejection and final ownership cleanup. Existing platform/native-reader/display guards run before provider fixtures.

Performed: canonical BTRC formatter write/check for the fixture and check for both provider sources; Ruff lint/format on the dedicated driver; `git diff --check`. Native compilation and execution, strict-import/fixture-discovery audits, independent review and catalog/skip admission are pending. The G12 boundary capture owns the native lane.

Scheduled Linux selector (both frontends and plain/sanitized = four rows):

```sh
python3 -m pytest -q src/tests/python/test_native_ui_grid_replacement.py --compilers=both
```

Use the parent's existing native-reader/GPU-capable X11 session and source-matched compilers. Run the fixture-only checkpoint to establish real red, then the repair checkpoint to establish green. Add four rows to the preserved 96-row provider recipe only after review; do not change the existing 96-row evidence or claim it covers this packet. Mac skips need their own actual-node admission fragment if this new driver is collected there.
