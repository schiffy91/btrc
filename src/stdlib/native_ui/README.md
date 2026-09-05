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

## Select controls

Build a controlled select with `NativeUiElement.select(id,
NativeUiSelect(options, selectedValue))`. Every `NativeUiSelectOption` has a
stable, non-empty `value`, a user-facing `label`, and an optional enabled flag.
Values are compared exactly; options must be unique, the selected value must
exist, and descriptors are bounded and UTF-8 validated.

Pointer or Enter/Space activation opens the renderer-owned menu. Arrow keys
move across enabled options, Escape closes the menu while preserving focus,
and Tab closes it while moving focus. A committed change emits
`NATIVE_UI_SELECTION_CHANGED`; `NativeUiEvent.value()` carries the stable
option value, never its presentation label. The application accepts that
proposal by supplying the selected value in its next tree. Resolved semantics
use the combo-box role, selected label as the default semantic value, and the
actual open/closed state.

## Style sheets and overrides

`NativeUiResolvedStyle.from(element, sheet)` resolves, in order: the kind's
built-in defaults, the sheet's kind rule (`NativeUiStyleSheet.kindRule(kind,
css)`), the element's class rule, then its inline style. Later declarations
win per property, so an application can start from a library's sheet and
adjust it without knowing every rule:

- `copy()` returns an independent sheet; the original never changes.
- `extend(className, css)` merges declarations into an existing class rule
  (the new declarations follow, so they win) and creates the rule when it is
  absent. `rule(...)` on a class that already has a rule stays an error, so
  a typo never silently doubles a selector.
- `kindRule(kind, css)` styles every element of one kind, for example every
  button's radius. Kind rules count toward the 64 KiB budget but not the 256
  rule limit.

Rows accept `align-items: start | center | end` for children shorter than
the row; columns and grids ignore it. `NativeUiColor.css()` prints
`#rrggbbaa`, the form every colour property accepts, so themes compose into
rules; `NativeUiColor.fromRgba(...)`/`rgba()` bridge `std.image`, and
`NativeUiTheme.dark()`/`light()` are a matched pair that applications can
pick between at runtime.

## Text rasters for painters

Surfaces that draw their own images (rulers, meters, note charts) obtain
text through `NativeUiTextRaster.rasterize(typography, text, fontSize,
lineHeight, fontWeight, color, backingScale)`. The result is a transparent
`Image` in backing pixels: the platform's system font when the session's
`NativeUiTypography` carries a raster provider, the deterministic 5x7 glyph
painter otherwise, sized from `measure()` either way. Runs longer than 4096
bytes are cut at a scalar boundary; the empty run is `Image.empty()`.
`NativeUiTextRaster.blit(target, source, x, y)` composes with straight
alpha and keeps the target's own transparency. `NativeUiAppSession` exposes
`typography()` and `backingScale()` so painters use the same provider and
scale as the frame compositor.
