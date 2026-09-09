# Native UI input contracts

`std.native_ui` keeps rendering and input portable without exposing platform
handles. `NativeUiStyleSheet` and per-element styles affect appearance only.

The native GPU compositor antialiases rounded rectangle corners at framebuffer
scale and multiplies coverage by the source alpha. Radius-zero fills keep their
aligned rectangular edges; corner smoothing does not change layout or hit bounds.

Explicitly transparent buttons stay transparent when idle. Hover and press add
subtle foreground-tinted overlays (6% and 12%), honoring the declared corner
radius. An explicit foreground controls the tint on custom dark/light materials;
otherwise the theme text color supplies it. Disabled controls do not highlight.
Transparent gradient stops retain their transparency.

## Retained layout

`NativeUiRenderer.layoutImmutable(root, width, height)` and
`NativeUiAppSession.prepareImmutable(root)` opt into retained subtree
measurements. The caller publishes immutable element trees: replace changed
branches rather than mutating previously published elements, descriptors, or
image geometry. Ordinary `layout`, `render`, and `prepare` support mutable
trees and discard retained measurements.

`element.copy().replaceChild(index, child)` creates a separate container with
one changed child; other children remain shared. `replaceChild` mutates its
receiver and uses the same bounds checks as `childAt`. Never call it directly
on an element already published through the immutable path.

Reuse requires the same element, available width, tree depth, and stylesheet
revision. Stylesheet edits invalidate automatically. Only the current tree is
retained, within the normal 4096-element bound; reused branches still participate
in duplicate-ID and aggregate metadata/image limits. Retained frames share
frozen resolved styles instead of cloning them for every box. Read properties
through accessors such as `padding()` and `background()`. Frozen color reads
return detached values; `apply(css)` rejects edits to a frozen style. To edit a
box's style, assign `box.style = box.style.copy()` first. Ordinary mutable
layouts still receive independent editable styles. Freezing also detaches any
previously exposed colors, so old references cannot change a shared template.

`measuredNodeCount()`, `reusedNodeCount()`, and `retainedMeasurementCount()`
report renderer work; preparation outcomes expose `measuredNodes` and
`reusedNodes`. These are node counts, not allocation counts or GPU timings.
`prepareCurrent()` still repaints already published geometry without layout.

## Background materials

`background-image: linear-gradient(#RRGGBB[AA], #RRGGBB[AA])` paints a vertical
two-stop gradient over `background-color`. Both renderers interpolate premultiplied
colors, preserve rounded borders, and retain the original gradient coordinates
when clipped or scrolled. `background-image: none` explicitly clears it through
the normal cascade. Directions, extra stops, and image URLs are not supported.
Gradient values are immutable and safe to share with frozen resolved styles.
Buttons apply the same restrained hover/pressed tint to gradient stops as to
solid fills; styling does not change control layout, hit targets, or input routing.

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

`renderer.showVerticalScrollbar()` enables viewport-owned vertical scroll chrome
(off by default). `verticalScrollbar()` exposes its current track/thumb geometry.
The thumb represents full measured content, including virtual rows that have no
elements. Dragging retains its grab offset; track clicks page the viewport. Both
use the existing `NATIVE_UI_SCROLLED` path and virtual-grid metrics. Release,
focus loss, viewport resize, root replacement, or disabling the scrollbar cancels
capture. The software and native GPU painters share geometry and theme colors;
select popups stay above it. No application-owned second scroll offset is needed.

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

`border-color` gives a filled panel or control a one-pixel inset rim without
changing layout; the theme panel supplies the fill if no background is set.
Focused text fields and open selects retain their accent rim. `marker-color`
overrides the select disclosure color independently of its label. Both accept
the same hex colors as `color` and apply to software and GPU presentation.
Select disclosures use centered, round-capped chevrons, not text glyphs; they
reverse when expanded and use the muted theme color when disabled. Software
and GPU rendering share their logical geometry, with antialiased edges and no
icon texture allocation.

`padding` sets all four edges; `padding-top`, `padding-right`, `padding-bottom`,
and `padding-left` override individual edges in declaration order (0..4096px).
Use these insets instead of empty spacer elements. Layout, software/GPU drawing,
and virtual-grid viewport calculations use the resolved edges. `padding()`
reports the last uniform declaration; read `paddingTop()`/`paddingRight()`/
`paddingBottom()`/`paddingLeft()` for effective values.

Image elements optionally accept `imageRegion(NativeUiImageRegion(left, top, width, height))`, an immutable normalized source rectangle inside [0,1]. Passing null restores the full image. Sampling changes do not change layout, hit targets, source bytes or image revision; GPU placements retain their own crop while sharing the cached texture. Element copies preserve the region independently of later setter calls. Invalid/nonfinite/empty/out-of-bounds rectangles are rejected.

`width: fit` keeps text, images, and buttons without flowing children at their
intrinsic content width plus padding, bounded by available space. Rows reserve
that width before sharing remaining space among flexible children. Container
fit sizing is not supported; it is rejected rather than silently stretched.

## Floating elements

`element.floating(x, y)` positions an element relative to its parent's outer
origin, outside row/column/grid flow. It contributes neither size nor gaps to
the parent. Its own children lay out normally. Floating children paint after
flowing siblings in declaration order; nested subtrees stay together, and hit
testing uses the reverse paint order. Decorative children do not intercept
their parent's control actions. Overflow clips at the viewport, not at the
parent, allowing popovers and shadows. Offsets are bounded to +/-65536 pixels;
the root cannot float. Virtual-grid item counts exclude floating decorations.

## Text rasters for painters

Text elements can opt into `text-wrap: wrap`; the default is `nowrap`, and
buttons/inputs/selects remain single-line. Explicit line breaks are retained;
spaces at a soft break are not painted. Long words and paths break to fit.
macOS uses CoreText line and composed-character boundaries; a cluster wider
than the available space remains intact. The deterministic proof font breaks
at scalar cells and ASCII whitespace instead of claiming linguistic shaping.

`NativeUiTypography.wrap` produces immutable `NativeUiTextLayout` lines with
their exact metrics and vertical positions. Layout boxes expose that same
layout to both painters; width changes invalidate retained measurements.
Only visible lines paint. The existing 4096-byte per-element and 4 MiB tree
metadata bounds include retained line data. Platform measurement providers
must supply their matching line-break callback when opting into wrapping.

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
