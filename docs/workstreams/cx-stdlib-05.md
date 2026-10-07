# CX-STDLIB-05: bound the Linux scrollbar to its track

Owned paths:
- `src/stdlib/GUI/Linux/LinuxScrollView.btrc`
- `src/tests/native/gui/controls/linux/ScrollThumbBounds.btrc`
- `src/tests/python/test_native_ui_scroll_thumb.py`
- `docs/workstreams/cx-stdlib-05.md`

Packet: CX-STDLIB-05. Branch: `codex/stdlib-scroll-repair`.
Base: `06c3923a10671534d5fe16870c51ca87495297c1`.

PLAN's existing-interface repair and WORKSTREAMS' reservation assign this
provider and its dedicated regression independently of the grid writer.
UIA23, UIA27 and UIB31 wait for this repair. The live open-PR inventory had no
overlapping LinuxScrollView claim on 2026-10-08. Checked local/hub history has
no preserved ScrollView repair; this packet reconstructs the bounded fix from
current source. The prior Mac alignment branch remains intact.

The current thumb has a 24-point minimum even when its inset track is shorter.
Its travel can therefore become negative, painting outside the viewport and
reversing the offset-to-position geometry. This is a source finding, not an
executed reproduction. Native red/green remains required.

Acceptance: actual Linux SDL/WebGPU captures must keep the thumb within its
track at zero and maximum offsets, for zero/tiny/normal viewports and absent
overflow. Wheel scrolling must still move real content offsets; normal thumb
dragging through SDL must reach the document boundary. A track without travel
must not divide by zero or move the offset during dragging. Both frontends and
plain/ASan+UBSan variants must execute on Linux. The dedicated driver joins the
existing `test_native_ui_*.py` native gate glob. No shared interfaces, compiler,
runtime or workflow files are changed. The integrator's final fragment admits
the four Linux-only platform skips on Mac; it adds no Linux allowance.

Started 2026-10-08. Initial free space: 78,463,668 KiB reported by `df`.
Native Linux builds are pending the integrator's execution slot. Publication
waits for its CI slot. No executed Linux failure, fix qualification or final
integration is claimed.

The dedicated regression is committed before the provider edit so the integrator
can run it against the original provider. It compares real captured pixels with
the same non-overflowing viewport at heights 0, 2, 4, 8, 20, 28 and 100 points,
then drives normal thumb dragging and wheel scrolling through SDL. Direct
provider pointer calls cover a zero-length track and a thumb that fills its
track. Both compiler frontends and sanitizer variants are collected by the
normal native-GUI glob; their Linux execution is pending.

Read-only independent review also confirmed that a finite `1e308` document
extent overflows the original offset-position multiplication, and an overshoot
drag can overflow before offset clamping and incorrectly return to the top.
The same real fixture therefore covers visible thumb pixels at the maximum of
that extent and direct drag overshoot to both boundaries. This remains an
unexecuted regression, not a current native failure claim.

## Current implementation and proof queue

The provider caps the preferred thumb height to the available track. Thumb
position divides the bounded offset by its maximum before scaling by travel.
Dragging clamps the destination fraction to [0, 1] before multiplying by the
finite maximum offset; zero travel or zero maximum performs no division.
The native view's existing frame validation and content-size validation still
reject non-finite dimensions. No wheel handling or interface contract changes.

Independent source review found no remaining actionable blocker after the
finite-extent corrections. The integrator applied the shared three-file audit
repair as `c311170d` before preparing normal qualification. Ruff lint/format,
BTRC formatting and `git diff --check` pass; the fixture needed whitespace-only
formatting. Native fixture discovery and the strict-import audit pass all ten
selected checks. These checks do not execute the Linux provider.

On Mac, the real regression driver produces four skips for its existing
anchored Linux/native-reader guard. Before the manifest fragment all four were
unexpected; afterward the local Mac skip gate accepts exactly those four.
Independent manifest checks also confirm the hosted Mac rule's schema and
exact admission, rejection of unrelated reasons/nodes, and no Linux allowance.
This is local platform-skip admission, not hosted Mac or Linux execution.
Evidence is retained under `subagent-delivery/scroll-thumb/macos-admission/`
in the integrator's 2026-10-07 consolidation evidence directory. Both-frontends
native compilation and real Linux behavior remain unqualified.

Fixture-only source: `7c060d08` (earlier tiny-viewport fixture: `0b5c3ba6`).
The integrator must run that regression with the original provider, retain its
actual failure, then rerun the repaired provider under the same environment:

```sh
nix develop --command tools/ui/headless-session.sh --x11 -- \
  python3 -m pytest -q src/tests/python/test_native_ui_scroll_thumb.py
```

Use the qualified Linux native header reader, matching compiler and GPU SDK
environment; do not count four platform skips on macOS as validation. The same
driver is included in `make test-native-gui` and the Linux GUI shard through the
existing wildcard, with no Makefile change. Repeat the required Wayland row when
that runner is available and retain its distinct outcome. Hosted publication is
coordinated by the integrator under the shared CI cap. Final combined-tree gates
and main landing remain open.
