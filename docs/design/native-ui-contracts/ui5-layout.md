# UI5 layout, environment and scene state

**Pre-draft — CX-UIB-02, `ui-5-contract-layout`.** This is input to CX-UIB-12,
not an API or approval to edit IView/IWindow/App. The UI2/UI3 writer chain must
land first; Claude freezes the resulting Stage 34 contract in CL-UIB-02 against
the five real shells and CL-UIA-22. All five platform mappings below are proposals.
No provider execution, screen-reader result or performance measurement is claimed.
The paired [accessibility pre-draft](ui8-accessibility.md) covers N41–N43.

## Source audit and family coverage

Read against `f4317455de1e567d4d6290139e5ba28fbada7d0c`:

| Family | Current source and missing behavior | Proposed acceptance |
|---|---|---|
| N23 | [IView](../../../src/stdlib/GUI/IView.btrc) has unconstrained fittingWidth/fittingHeight and logical-point arrange. | Width-dependent measurement, min/preferred/max and baselines; E26. |
| N24 | [IStack](../../../src/stdlib/GUI/IStack.btrc) keeps space for hidden children; [IGrid](../../../src/stdlib/GUI/IGrid.btrc) exposes explicit track sizes, fitting and hidden rows/columns. | Coherent nested layout, grow/shrink, stable children and distinct collapse; E26/E29/E39. |
| N25 | [IWindow](../../../src/stdlib/GUI/IWindow.btrc) exposes content size and visibility, not safe-area, keyboard or exposure facts. | Snapshot of viewport/occlusion/scale with explicit unknowns; E18/E27/E42. |
| N31 | No shared native tabs/navigation contract in these interfaces. | Keyed destinations, Back/history and transactional departure; E16/E18/E46/E47. |
| N32 | No shared split-pane/toolbar contract in these interfaces. | Bounded panes, collapse and reachable overflow with compact adaptation; E18/E26/E46. |
| N44 | [UI/Typography](../../../src/stdlib/UI/Typography.btrc) deliberately measures one cell per Unicode scalar for deterministic proof rasters. Native shaping belongs to GUI. | Native shaping, locale/reading direction and localization revisions; E20/E26. |
| N45 | [MacOSLabel.setCentered](../../../src/stdlib/GUI/MacOS/MacOSLabel.btrc) maps false to physical left alignment. | Semantic leading/trailing, text scale, contrast and role colors; E15/E20/E26. |
| N46 | The current portable view/window interfaces expose no reduced-motion, transparency or haptic preference observations. | Observe preferences and supply nonanimated/nonhaptic feedback; E20. |

The authoritative meanings and fixture budgets are in
[native-ui-parity](../native-ui-parity.md). The P/C/M planning cells do not prove
these proposed behaviors. N41–N43 consume the geometry, visibility and focus facts
below through the paired document; no second geometry model belongs to the bridge.

## Proposed operation inventory

These names are candidate catalog ids, not btrc signatures. New declarations need
an approved amendment; do not append to the frozen UI0 denominator.

| Candidate operation ids | Values and invariant |
|---|---|
| IView.measure | Constraints and environment revision → result with min/preferred/max extent, optional first/last baseline and overflow disposition. |
| IView.setLayoutParticipation | Visible/hidden/collapsed participation using the approved UI2 interaction state; no implicit close or reparent. |
| IView.invalidateMeasurement | Reason/revision invalidates cached size once; no callback loop from unchanged inputs. |
| IStack.setDistribution, IStack.setChildFlex | Axis packing plus per-child grow/shrink/basis; cross-axis baseline/leading/trailing alignment. |
| IGrid.setColumnRule, IGrid.setRowRule | Fixed/content/fractional track rule with min/max and bounded span handling. Existing setChild/childAt identity is preserved. |
| IWindow.viewport, IWindow.onViewportChanged | Immutable viewport/safe-area/keyboard/scale/direction snapshot and scoped observation. |
| IWindow.environment, IWindow.onEnvironmentChanged | Immutable typography/appearance/motion/locale facts with revision and scoped observation. |
| INavigation.setDestinations, INavigation.requestDestination, INavigation.onDestinationChanged | Stable keys, one departure transaction, committed route observation. |
| ISplitPane.setPanes, ISplitPane.setDivider, ISplitPane.onDividerCommitted | Stable panes, bounded sizes and user commit; compact collapse preserves child identity. |
| IToolbar.setItems | Stable command keys, priority and reachable overflow; one command owner. |
| ISceneRestoration.checkpoint, ISceneRestoration.restore | Versioned bounded metadata through the product persistence owner; no native-object serialization. |

Where UI2/UI3 approves an equivalent operation, reuse its id and value type rather
than adding the spelling above. Scope registrations use CallbackScope and
ICallbackRegistration. Setters cause no user command; notifications report state
changes after native mutation settles. Native decision hooks remain synchronous.

## Constrained measurement and layout

All geometry uses content-local logical points from the top left, as IView does
today. Constraints explicitly distinguish finite bounds from an unbounded axis;
NaN, negative minima or min greater than max return invalid before native change.
A measurement result has finite nonnegative min/preferred extents, optional
unbounded maxima, and `min ≤ preferred ≤ max` on each axis. Baselines are optional
logical offsets within the reported extent; missing baselines are not zero.

Measure in two steps: resolve the available inline width, then ask the native
text/control provider for height at that width. The same font/locale/wrapping
configuration must measure and paint. Preserve the native editor, selection and
composition across remeasurement. A narrow container cannot make an indivisible
control fit by silently clipping required actions: return overflow and let its
owner choose wrap, scroll or the compact presentation. Never shrink below a
control's minimum to hide overflow.

Grow distributes extra space among nonzero grow weights up to maxima. Shrink
reduces each eligible preferred size toward its minimum according to declared
weights; remaining deficit reports overflow. Zero weights mean fixed preference,
not a zero-size child. Stable tie-breaking uses child order and accumulates
rounding residuals at device-pixel conversion so nested layout does not drift.
Baselines align only participating children with a baseline; others use the
specified fallback cross alignment. Padding/gaps use logical leading/trailing
and block-start/end; physical left/right are explicit opt-ins.

Stacks measure in axis order, subtract padding/gaps once, preserve ordered child
identity and distribute only within their axis. Grids resolve fixed tracks,
content minima, then bounded fractional remainder; spans contribute constraints
without measuring the same child as an independent object. Hidden retains space
but is not interactive or exposed as visible accessibility content; collapsed
has no layout space. Neither destroys its child. Empty/collapsed tracks have an
explicit gap policy (proposed: no gap attributable solely to collapsed tracks).

Clipping, z-order and traversal order remain separate. Moving a view changes its
parent transactionally under the approved container contract; failure never
leaves it owned by two containers. A batch publishes one consistent measured/
arranged tree or its declared rollback result (E29). Measurement is side-effect
free with respect to product commands. Cache keys include content revision,
constraints, provider/font metrics, text scale, locale/direction and style
revision. Settled unchanged inputs cause zero repeat layout work. Detect and
report a bounded nonconverging layout cycle instead of spinning the UI executor.

## Viewport, environment and adaptive navigation

A viewport snapshot includes logical content bounds, device scale, safe-area
insets, keyboard occlusion region, layout direction, size class and scene id.
Keyboard coverage is a region, not always a bottom inset (floating iPad keyboards
and split displays matter). Distinguish reported zero from unknown. Safe area
and keyboard overlap are unioned geometrically, not subtracted twice. Exposure,
requested visibility, activation and drawable availability follow UI2/E42 and
are not collapsed into a single boolean. Geometry and accessible screen bounds
share the same transform snapshot; round trips must be within one device pixel.

Navigation stores stable destination keys plus parameters, not widget indices.
Tab/Back/swipe/close requests enter the same E46 departure transaction. While a
Save/Discard/Cancel decision is pending, coalesce repeats for that destination;
failed save or a new document revision keeps the draft and route. A committed
transition changes the destination once and restores focus/scroll by identity.
Predictive Back previews can be cancelled without committing navigation. Modal,
editor and transient dismissal precedence belongs to UI3, not a second router.

Split panes obey minimum sizes and expose a keyboard/accessibility divider action.
Below the combined minimum, collapse to navigation with a visible route back;
never leave an unreachable offscreen pane. A toolbar uses the same command keys
in its overflow menu, with native platform placement; disabled/hidden states
revalidate at invocation. A large display can show panes concurrently without
forking document state. Resizing, rotating or moving to another display keeps
native editors and pending departure transactions attached to their owner.

Typography audit: UITypography limits its deterministic wrap/raster text to
4,096 bytes, uses scalar-cell metrics and caches up to 512 measurements. Its
left/center/right enums are physical. These are existing proof-renderer bounds,
not a native shaping specification or justification to copy its glyph model.
Native text needs shaping, fallback, grapheme/word boundaries and bidi-aware
measurement. Localization keys resolve with locale and parameter revisions;
never translate an already translated display string or persist it as identity.
Reading direction affects leading/trailing, while authored physical media
coordinates remain explicit. Font/theme/locale changes invalidate measurement
without replacing active editors or losing selection.

Environment observations include system/light/dark appearance, semantic roles
for foreground/background/accent/error/selection, contrast, text scale, reduced
motion and reduced transparency. Resolve state colors in the provider and expose
facts for custom GPU content. Increased text size is not silently capped at the
existing macOS button/select 20-point restriction. Reduced motion replaces
nonessential animation with an immediate state transition; progress and errors
retain text/shape feedback. Haptics are meaningful, opt-in and availability-
reported; no required action relies on vibration or color alone.

## Versioned restoration and departure

Propose a `btrc.scene/1` value containing schema version, stable scene/document id,
destination key/parameters, stable selection and scroll-anchor identities, and
references to separately checkpointed eligible drafts. A codec validates UTF-8,
types, bounds, version and identity before constructing views. The fixture
metadata budget is **64 KiB (65,536 encoded bytes) per scene**, including envelope
and strings: 65,535 and 65,536 are admitted, 65,537 reports overflow with the
previous checkpoint preserved. It is an application budget, not an OS limit.
Large drafts live in durable product storage, not an oversized scene descriptor.

Checkpoint via the atomic persistence owner: prepare, validate, durable replace,
then acknowledge. This draft does not invent filesystem durability semantics.
Never serialize native handles, callbacks, pending saves/imports/playback,
passwords or resource credentials. Store opaque stable references and revalidate
access on restore. Restoring state never replays a side-effecting command.

Support current schema and one explicit previous-schema migration. Unknown
versions, malformed/truncated data, deleted items and revoked resources yield a
reported operable fallback; preserve the source record for recovery according to
product policy. Display topology changes clamp geometry to a usable viewport.
External activation during restore follows one router and duplicate policy,
without cross-scene swaps. User-dismissed scenes are not resurrected just because
a checkpoint exists. Forced OS termination can restore only previously
checkpointed state; no final callback or successful save is promised.

## Five-platform mapping and requests

| Family | Layout/environment/navigation mapping to qualify |
|---|---|
| macOS | AppKit intrinsic measurement, native stack/grid and split/toolbar owners; NSWindow content and screen-scale facts, native text/font metrics, NSAppearance and accessibility preference changes. Tab/window departure uses the shared transaction. |
| Linux | SDL currently draws custom controls; native semantics require explicit shaping and desktop preference sources. If D23 chooses GTK4, use GTK measurement/layout, direction and settings. Qualify X11 and Wayland independently; compositor occlusion may remain unknown. |
| Windows | Per-monitor DPI and client bounds, native control measurement, high-contrast/system settings and accessible split/toolbar adaptation; never assume fixed 96-DPI geometry. UIA uses the resulting transforms. |
| iOS/iPadOS | UIKit safe-area and keyboard layout facts, dynamic type, size classes and scene state. One ios family includes iPhone plus iPad split view/Stage Manager, floating keyboard and external display scenarios with device_class provenance. |
| Android | WindowInsets/IME regions, configuration/locale/font-scale changes and platform navigation/Back callbacks. Activity recreation restores stable state; framework saved state alone is not a durable document-save acknowledgement. |

Interop follows [native-interop-ownership](../native-interop-ownership.md): Apple
steps 3/6 and **CL-UIB-09**, Windows COM step 5 and **CL-UIB-10**, Android JNI
steps 4/7 and **CL-UIB-11**, Linux GObject step 8 or verified D-Bus export and
**CL-UIB-12**. The accessibility document spells out the expected REQUEST blocks.
Stage 24/25 hosts, Stage 29 bindings, D23 and five-shell CL-UIA-22 review remain
prerequisites; a C/Objective-C/Java prototype alone is not a btrc provider proof.

## Proposed acceptance evidence

- **E26/E39, N23/N24/N44:** wrapped label/editor/validation form at 320/480/1024
  logical widths, 100/150/200% text size and LTR/RTL; baseline alignment,
  grow/shrink, hidden/collapsed and bounded invalidation with no editor loss.
- **E18/E27/E42, N25/N31/N32:** keyboard show/hide, floating keyboard, rotation,
  display-scale moves, split/compact navigation and toolbar overflow; focused
  content/actions remain reachable and transforms round-trip within one pixel.
- **E15/E20, N44–N46:** live text scale/locale/theme/contrast/motion changes;
  remeasure once per changed revision, no stale GPU colors or clipped actions.
- **E46:** 100 cycles per applicable departure entry, including failed/stale
  saves and parent loss; zero lost drafts, duplicate saves, stale-revision closes
  or wrong-window results, with UI executor responsiveness preserved.
- **E47:** 100 fresh-process restores with write/recreation fault injection;
  zero acknowledged-save corruption, replayed commands or cross-scene swaps.
  Cover prior/current/unknown schema and metadata boundaries. Measure 20 launches
  against the existing pre-indexed Library p95 ≤3 s desktop / ≤4 s mobile budget.

Execute applicable cases through reference/selfhost and each provider; record
missing/unverified/adapted outcomes honestly. iPad shares ios slots with device
provenance. No tests, operation rows or denominator changes accompany this draft.
