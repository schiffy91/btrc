# Native UI input contracts

`std.native_ui` keeps rendering and input portable without exposing platform
handles. `NativeUiStyleSheet` and per-element styles affect appearance only.

## Semantic state

Attach `NativeUiSemantics` with `NativeUiElement.semantics(...)`; element
`enabled`, `selected`, and `focusable` remain typed properties rather than CSS.
Roles are backend-neutral. Label, hint, and value are independently optional,
limited to 512 bytes, and validated as NUL-free UTF-8. Checked and pressed use
`NativeUiSemanticToggleState`; expanded uses
`NativeUiSemanticExpansionState`; live regions use
`NativeUiSemanticLiveMode`.

Disabled elements cannot be hit, focused, edited, adjusted, or activated.
`NativeUiRenderer.activate(...)` is the accessibility activation boundary, and
Enter/Space use it for the focused control. Actual focus is renderer-owned:
inspect `NativeUiResolvedSemantics.focused()` through a frame or layout box.
There is no declarative focused flag, and style declarations cannot alter
semantic values.

## Semantic ranges

Attach `NativeUiSemanticRange.horizontal(...)` or `.vertical(...)` with
`NativeUiElement.semanticRange(...)`. Bounds, values, and steps are signed
64-bit integers so frame and sample positions remain exact. The descriptor is
controlled state: input events propose a clamped `rangeValue()`, and the next
application tree supplies the accepted value.

Pointer press captures the range until release or cancel. Press, move, release,
and cancel events carry a one-dimensional local `NativeUiPointerSample`:
horizontal ranges use x/width and vertical ranges use y/height. A captured move
may report a coordinate below zero or beyond the extent.

`NativeUiRenderer.wheelBy(x, y)` targets the range under the pointer. Positive
renderer-space movement increments and negative movement decrements; horizontal
ranges use x (falling back to y when x is zero), while vertical ranges use y
(falling back to x). A wheel outside a range retains ordinary viewport scroll.

Focused ranges use axis arrows for small adjustments, Shift+arrow for large
adjustments, and Control/Command+arrow for minimum or maximum. Accessibility
adapters can call `adjustRange` directly with the same semantic adjustment.
Button clicks, text input, and ordinary scrolling retain their existing event
contracts.
