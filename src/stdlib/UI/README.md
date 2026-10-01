# Library.UI

`Library.UI` is a declarative element tree with deterministic layout,
backend-neutral semantics, `UIEvent` messages and a proof raster. It holds no
platform handles and has no presentation host: no GPU painter, window or
native session consumes `UIFrame`. Applications build `UIElement` trees, call
`UIRenderer.layout(root, width, height)` for geometry, and own presentation
themselves (native controls and GPU views live in `Library.GUI`).

## Modules

`import Library.UI;` is an import-only facade over an acyclic module graph;
each module can also be imported alone:

| Module | Owns |
| --- | --- |
| `Text` | UTF-8 scalar boundaries (`UIText`) shared by every other module |
| `Semantics` | `UISemantics`, roles and states |
| `Element` | `UIElement`, values (`UIColor`, `UISelect`, ranges, events) and styles (`UIStyle`, `UIStyleSheet`) |
| `Typography` | `UITypography`, measurement, wrapping and the platform raster contract |
| `Render` | `UIRenderer`, layout, hit testing, `UIResolvedStyle` and the proof raster painter |
| `TextRaster` | `UITextRaster`, text runs as transparent `Image` rasters |

## Hosts and the test driver

A host synthesizes `UIEvent` values from its own input and applies them to its
application state; the next tree it publishes is the accepted state. The
`UIRenderer` interaction methods (`pointerPressed`, `pointerMoved`,
`textEntered`, `moveCaretLeft`, `undoText`, `focusNext`, `openTextMenu`,
`wheelBy`, ...) are a **deterministic test driver**: they turn synthetic input
into the same `UIEvent` messages and keep caret, selection, menu and scrollbar
state so tests can prove input contracts against the proof raster. They are
not bound to keys, a clipboard or a window by this package.

`render(root, width, height)` paints the proof raster, a portable RGBA `Image`
used as test evidence, not a production surface.

## Appearance

`UIStyleSheet` and per-element styles affect appearance only. Explicitly
transparent buttons stay transparent when idle. Hover and press add
subtle foreground-tinted overlays (6% and 12%), honoring the declared corner
radius. An explicit foreground controls the tint on custom dark/light materials;
otherwise the theme text color supplies it. Disabled controls do not highlight.
Transparent gradient stops retain their transparency.

Text inputs may own a decorative `leadingIcon(image, width, height, gap)`.
Logical dimensions are independent of raster resolution; `imageRevision`
invalidates cached pixels. The field retains one border, focus target and
editing identity, including clicks on the icon. Resolved left padding includes
the icon and gap so rendering, selection, caret positioning and text scrolling
agree. Icons too large for a resized field are hidden without overflowing it;
their source pixels participate in the ordinary renderer resource limits.

## Retained layout

`UIRenderer.layoutImmutable(root, width, height)` opts into retained subtree
measurements. The caller publishes immutable element trees: replace changed
branches rather than mutating previously published elements, descriptors, or
image geometry. Ordinary `layout` and `render` support mutable
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
report renderer work. These are node counts, not allocation counts or timings.


## Background materials

`background-image: linear-gradient(#RRGGBB[AA], #RRGGBB[AA])` paints a vertical
two-stop gradient over `background-color`. The proof raster interpolates premultiplied
colors, preserves rounded borders, and retains the original gradient coordinates
when clipped or scrolled. `background-image: none` explicitly clears it through
the normal cascade. Directions, extra stops, and image URLs are not supported.
Gradient values are immutable and safe to share with frozen resolved styles.
Buttons apply the same restrained hover/pressed tint to gradient stops as to
solid fills; styling does not change control layout, hit targets, or input routing.

## Semantic state

Attach `UISemantics` with `UIElement.semantics(...)`; element
`enabled`, `selected`, and `focusable` remain typed properties rather than CSS.
Roles are backend-neutral. Label, hint, and value are independently optional,
limited to 512 bytes, and validated as NUL-free UTF-8. Checked and pressed use
`UISemanticToggleState`; expanded uses
`UISemanticExpansionState`; live regions use
`UISemanticLiveMode`.

Disabled elements cannot be hit, focused, edited, adjusted, or activated.
`UIRenderer.activate(...)` is the accessibility activation boundary. Focus in
the test driver is renderer-owned:
inspect `UIResolvedSemantics.focused()` through a frame or layout box.
There is no declarative focused flag, and style declarations cannot alter
semantic values.

## Semantic ranges

`renderer.showVerticalScrollbar()` enables viewport-owned vertical scroll chrome
(off by default). `verticalScrollbar()` exposes its current track/thumb geometry.
The thumb represents full measured content, including virtual rows that have no
elements. Dragging retains its grab offset; track clicks page the viewport. Both
use the existing `UI_SCROLLED` path and virtual-grid metrics. Release,
focus loss, viewport resize, root replacement, or disabling the scrollbar cancels
capture. The proof raster paints it from the same geometry and theme colors;
select popups stay above it. No application-owned second scroll offset is needed.

Attach `UISemanticRange.horizontal(...)` or `.vertical(...)` with
`UIElement.semanticRange(...)`. Bounds, values, and steps are signed
64-bit integers so frame and sample positions remain exact. The descriptor is
controlled state: input events propose a clamped `rangeValue()`, and the next
application tree supplies the accepted value.

Pointer press captures the range until release or cancel. Press, move, release,
and cancel events carry a one-dimensional local `UIPointerSample`:
horizontal ranges use x/width and vertical ranges use y/height. A captured move
may report a coordinate below zero or beyond the extent.

`UIRenderer.wheelBy(x, y)` targets the range under the pointer. Positive
renderer-space movement increments and negative movement decrements; horizontal
ranges use x (falling back to y when x is zero), while vertical ranges use y
(falling back to x). A wheel outside a range retains ordinary viewport scroll.

`adjustRange` and `adjustFocusedRange` apply small, large, minimum and maximum
adjustments; a host maps its own keys or accessibility actions onto them.
Button clicks, text input, and ordinary scrolling retain their existing event
contracts.

## Select controls

Build a controlled select with `UIElement.select(id,
UISelect(options, selectedValue))`. Every `UISelectOption` has a
stable, non-empty `value`, a user-facing `label`, and an optional enabled flag.
Values are compared exactly; options must be unique, the selected value must
exist, and descriptors are bounded and UTF-8 validated.

Pointer activation or `activate` opens the renderer-owned menu;
`navigateFocusedSelect` moves across enabled options, `dismiss` closes it while
preserving focus, and `focusNext` closes it while moving focus. A committed change emits
`UI_SELECTION_CHANGED`; `UIEvent.value()` carries the stable
option value, never its presentation label. The application accepts that
proposal by supplying the selected value in its next tree. Resolved semantics
use the combo-box role, selected label as the default semantic value, and the
actual open/closed state.

## Style sheets and overrides

`UIResolvedStyle.from(element, sheet)` resolves, in order: the kind's
built-in defaults, the sheet's kind rule (`UIStyleSheet.kindRule(kind,
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
  rule limit; a kind outside `UIElementKind` is `UI_STYLE_INVALID_SELECTOR`.

`UIStyle.parse(css)` is the one declaration parser. `UIStyle.validate` reports
its first `UIStyleError`, and `UIResolvedStyle.apply(css)` applies its
validated declarations or throws that error's message without changing the
style, so `apply("color: red")` is an error rather than a bad read.

Rows accept `align-items: start | center | end` for children shorter than
the row; columns and grids ignore it. `UIColor.css()` prints
`#rrggbbaa`, the form every colour property accepts, so themes compose into
rules; `UIColor.fromRgba(...)`/`rgba()` bridge `Library.Image`, and
`UITheme.dark()`/`light()` are a matched pair that applications can
pick between at runtime.

`border-color` gives a filled panel or control a one-pixel inset rim without
changing layout; the theme panel supplies the fill if no background is set.
Focused text fields and open selects retain their accent rim. `marker-color`
overrides the select disclosure color independently of its label. Both accept
the same hex colors as `color`. Select disclosures use centered, round-capped
chevrons, not text glyphs; they reverse when expanded and use the muted theme
color when disabled.

Text fields draw a one-logical-pixel blinking caret, centered at font size
within the line box (clamped to its height). The test driver's
`openTextMenu` models Cut/Copy/Paste/Select All without losing an existing
selection under the pointer and edits through the same validated UTF-8
operations as `textEntered`/`backspace`; it reports the chosen command and
never touches a clipboard. `navigateTextMenu` selects enabled commands; an
outside press dismisses without activating content underneath. Focus loss,
scrolling, resizing and external value replacement dismiss the menu.

`padding` sets all four edges; `padding-top`, `padding-right`, `padding-bottom`,
and `padding-left` override individual edges in declaration order (0..4096px).
Use these insets instead of empty spacer elements. Layout, the proof raster,
and virtual-grid viewport calculations use the resolved edges. `padding()`
reports the last uniform declaration; read `paddingTop()`/`paddingRight()`/
`paddingBottom()`/`paddingLeft()` for effective values.

Image elements optionally accept `imageRegion(UIImageRegion(left, top, width, height))`, an immutable normalized source rectangle inside [0,1]. Passing null restores the full image. Sampling changes do not change layout, hit targets, source bytes or image revision. Element copies preserve the region independently of later setter calls. Invalid/nonfinite/empty/out-of-bounds rectangles are rejected.

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
A platform typography provider supplies its own line-break callback; the
deterministic proof font breaks at scalar cells and ASCII whitespace instead
of claiming linguistic shaping.

`UITypography.wrap` produces immutable `UITextLayout` lines with
their exact metrics and vertical positions. Layout boxes expose that same
layout to any painter; width changes invalidate retained measurements.
Only visible lines paint. The existing 4096-byte per-element and 4 MiB tree
metadata bounds include retained line data. Platform measurement providers
must supply their matching line-break callback when opting into wrapping.

Surfaces that draw their own images (rulers, meters, note charts) obtain
text through `UITextRaster.rasterize(typography, text, fontSize,
lineHeight, fontWeight, color, backingScale)`. The result is a transparent
`Image` in backing pixels: the platform's system font when the session's
`UITypography` carries a raster provider, the deterministic 5x7 glyph
painter otherwise, sized from `measure()` either way. Runs longer than 4096
bytes are cut at a scalar boundary; the empty run is `Image.empty()`.
`UITextRaster.blit(target, source, x, y)` composes with straight
alpha through `Image.compositeImage` and keeps the target's own transparency.
Callers supply the typography provider and backing scale explicitly. The
proof raster draws platform text the same way when the provider rasterizes.
