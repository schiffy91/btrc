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

### Three-call production correction

Fixture-only red candidate: `366da1cd`. Grid now calls `cell.arrange` and each
Stack orientation calls `child.arrange`, preserving geometry calculations and
existing hidden/closed checks. The real child's implementation owns recursive
layout and scroll clamping; no ScrollView behavior was duplicated or edited.

Ruff lint/format, BTRC syntax/format checks, `git diff --check`, and direct AST
inspection of literal fixture admission pass. Both new layout basenames occur
in the driver selected by the unchanged native-GUI glob. For the stacked input
fixture, `LinuxMetrics` is declared directly in the explicitly imported
`Library.GUI.Linux.LinuxContext`; `GUIProviderRoot` exports that provider module.
This resolves source ownership inspection, not paired native strict-import
qualification: no compiler/native builds or pytest runs have occurred here.

Scheduled qualification, after the parent allocates Linux capacity:

```sh
PYTEST_WORKERS=1 tools/linux-ci.sh test-native-gui \
  'BTRC_TEST_RUNNER=linux-devcontainer' \
  'PYTEST_ARGS=-q -rs -k linux_layout_resize --basetemp=build/linux-layout-proof/pytest --junitxml=build/linux-layout-proof/junit.xml'
```

Run the fixture-only and repaired source on the same qualified toolchain and
retain logs/generated units/executables before reusing basetemp. A real stale
offset/height assertion is the required red; compilation/setup failure is not.
All 12 repaired rows must pass without skips. The broader combined Linux input,
layout, scrollbar and existing-controls suite follows, then the normal final
gates. Expected-skip admission and evidence catalog promotion remain parent
obligations. No new performance or main-integration claim is made.
