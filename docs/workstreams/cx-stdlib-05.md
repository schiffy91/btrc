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
runtime, manifests, skip allowances or workflow files are changed.

Started 2026-10-08. Initial free space: 78,463,668 KiB reported by `df`.
Native builds and all tests are
paused while the integrator owns the shared gate. Publication waits for its CI
slot. No executed failure, fix qualification or final integration is claimed.

The dedicated regression is committed before the provider edit so the integrator
can run it against the original provider. It compares real captured pixels with
the same non-overflowing viewport at heights 0, 2, 4, 8, 20, 28 and 100 points,
then drives normal thumb dragging and wheel scrolling through SDL. Direct
provider pointer calls cover a zero-length track and a thumb that fills its
track. Both compiler frontends and sanitizer variants are collected by the
normal native-GUI glob; their Linux execution is pending.
