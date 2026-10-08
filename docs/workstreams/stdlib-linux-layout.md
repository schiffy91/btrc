# CX-STDLIB-02: recursive Linux Grid/Stack resize

Branch: `codex/stdlib-linux-layout`.
Exact stacked base: `42d5a7c161b8bc1d19408ff6571a4d6c523c3e04`
(`codex/stdlib-linux-event-repair`, preserved unchanged). Parent assigned this
packet under PLAN D29 on 2026-10-08. The base is itself unqualified native work;
this branch does not promote its input/visibility outcomes.

## Owned paths

- `src/stdlib/GUI/Linux/LinuxGrid.btrc`
- `src/stdlib/GUI/Linux/LinuxStack.btrc`
- `src/tests/native/gui/layout/linux/LinuxGridScrollResize.btrc`
- `src/tests/native/gui/layout/linux/LinuxStackScrollResize.btrc`
- `src/tests/python/test_native_ui_layout_resize.py`
- This report.

No ScrollView, input provider, portable contract, compiler, generated file,
PLAN, shared harness, workflow or admission-manifest change. The parent handles
admission fragments after source-matched evidence. CX-STDLIB-01's native
minimize/restore gap remains explicitly unqualified; this packet does not
change visibility.

## Planned proof

Preserve a fixture-only red candidate before changing provider code. Use real
Grid/Stack and ScrollView instances: parent layout must call the child's virtual
`arrange`, reaching the ScrollView's existing clamp. Both Stack orientations
contain a real Grid with a scroll child, proving nested dispatch without a
replacement layout implementation. Check the offset immediately after layout
(before painting can incidentally repair it), then actual GPU pixels.

Native runs/builds/guests are not authorized yet: parent owns qualification
scheduling. Historical combined `0f6f3448` source is unavailable; its old passing
counts are not evidence for this reconstruction. Source/format checks only.

### Fixture-only checkpoint

Both native fixtures use the real factory-created Grid/Stack/ScrollView and
four opaque 100-point color bands in a 400-point document. Initial height 80
and offset 320 show yellow; enlargement to 180 must clamp to 220 and show blue;
repeating that layout must be stable; enlargement to 440 removes overflow and
shows red; shrinking to 80 preserves offset zero, and scrolling to the end again
shows yellow. Each checks `scrollOffset`, node height and content translation
before capture, actual GPU pixels after capture, retained child identity and
completed subtree shutdown. Both Stack orientations contain the same real Grid,
so virtual dispatch is tested through two production layout owners.

The normal driver is `test_native_ui_layout_resize.py`: grid/row/column ×
Python/selfhost × plain/ASan+UBSan = 12 native rows. Reader/platform/display
guards precede expensive fixtures. Fixture-only source is not an executed red
result. Native/guest/build execution remains unstarted.
