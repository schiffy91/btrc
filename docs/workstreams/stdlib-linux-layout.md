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
