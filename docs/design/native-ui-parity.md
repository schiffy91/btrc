# Native UI: inventory, contracts and qualification

Status: proposed/open; API inventory refreshed 2026-09-21. This is part of [PLAN.md](../../PLAN.md),
alongside the [platform roadmap](platform-parity.md). It extends UI planning to
**macOS, Linux, Windows, iOS/iPadOS and Android**. It does not claim that current
providers or proposed budgets have passed live qualification.

Audit revisions: btrc `4e5c98239868e805586524b4ee06424bf4556130`; BTRSmith
remote `main` `5549c261`, inspected without modifying its older local checkout.
The inventory below identifies 60 capability families. They are planning units,
not 60 implemented widgets or an exhaustive count of SDK methods. UI0 expands
them into operation-level acceptance cases with a stable denominator.

## Review checkpoint

UI implementation is **bucket 4**, queued behind compiler performance,
C compatibility and platform foundations under
[PLAN.md's sequential execution order](../../PLAN.md#execution-order-five-buckets).
This inventory does not authorize early UI work. Once bucket 4 begins, start
with native-shell feasibility and an editor-and-focus slice using the existing
GUI owners, before expanding controls. The dependency order below applies
within that bucket; it is not a parallel workstream beside optimization.

| Decision for review | Recommendation | Evidence required before expanding the work |
| --- | --- | --- |
| First portable behavior | Extend the existing text/select/range owners with scoped events; keep native editing state with the control. | E01–E07: exactly one command per commit, no setter-generated actions, preserved composition/selection/undo and correct editor shortcut precedence through both frontends. |
| Provider choice | Extend AppKit; evaluate the Linux/Windows/mobile routes in section 1 with the same shell fixture. | UI1: real editor, button, scrolling content and GPU child; native input, accessible tree and 100 teardown cycles. Record an interop blocker before committing to a toolkit migration. |
| Reusable collections | Preserve BTRSmith's stable-key album pool while defining the shared data/selection/recycling contract. | UI6: 100,000 rows with bounded owners, stable scroll/focus and offscreen accessibility realization; no allocation of one native view per record. |
| Product migration | Search/filters → Settings → browse/import → Player → mobile restoration, with accessibility in every slice. | Each slice preserves its actual user journey and meets its named input, lifecycle and performance gates. A migrated screen is not evidence for an unimplemented provider. |
| Core versus extended scope | Keep N01–N50 core and N51–N60 explicitly open; promote an extended capability when an existing product journey needs it. | UI10 requires every core journey; UI11 retains printing, rich editing, WebView and other extended work without blocking the first usable Library screen unnecessarily. |
| Definition of parity | Track implementation and qualification separately for every provider and frontend. | 300 classified family/platform cells plus the initial 470 case-result slots; missing implementations, failed tests, unavailable runners and reviewed OS adaptations remain separately visible. |

The source matrix makes the scale of the gap explicit:

| Platform | Partial native/provider foundation | Custom control foundation | Missing families | Live qualification |
| --- | --- | --- | --- | --- |
| macOS | 33 | 0 | 27 | Open |
| Linux | 15 | 15 | 30 | Open |
| Windows | 0 | 0 | 60 | Open |
| iOS/iPadOS | 0 | 0 | 60 | Open |
| Android | 0 | 0 | 60 | Open |

These counts summarize the P/C/M matrix below, not a percentage complete:
**27 families are missing on all five platforms**. A partial foundation can
still need substantial API and behavior work. Prioritize input, ownership,
layout and accessibility together; adding factories alone will not close these
families. UI0 must break each family into operations before estimating effort.

Review the provider feasibility evidence after UI1 and the shared event/focus
contracts after UI2/UI3. Numeric budgets in section 5 are proposed acceptance
goals, not estimates of current performance. The inventory is ready for design
review; UI0's operation catalog and all implementation milestones remain open.

## 1. Destination and evidence

Ordinary application controls should be platform controls, with native text
editing, focus, accessibility, menus and interaction conventions. Product code
owns application state and commands; stdlib providers own native objects and
their lifetimes. Custom GPU content remains appropriate for tablature, the
note highway, meters and other musical visualization. It must participate in
the same focus, command, accessibility and lifecycle contracts as its neighbors.

Parity means equivalent tasks and semantics, with idiomatic presentations:
a desktop menu can become a mobile action menu, and a desktop split view can
become a navigation stack. Pixel-identical chrome is not the objective. Neither
painted lookalikes nor successful screenshot capture prove native behavior.

### What the tree currently provides

| Evidence | Current implementation and specific gap |
| --- | --- |
| `src/stdlib/GUI/GUI.btrc`, `IApplication.btrc`, `IView.btrc`, `IWindow.btrc` | A portable factory, native owner interfaces, scoped callbacks, queued work, delayed work and close/drain contracts already exist. Extend these owners; do not introduce a second GUI runtime. Portable scene, focus, command, accessibility and general lifecycle observation remain incomplete. |
| `GUI/ITextField.btrc`, `ISlider.btrc`, `ISelect.btrc` | Text/value/index getters and setters exist. No portable text-edit/commit, slider-change or selection-change subscriptions. A text editor cannot be integrated properly by repeatedly sampling its string. `ISelect` exposes labels/indices rather than stable option identities. |
| `GUI/IStack.btrc`, `IGrid.btrc`, `IScrollView.btrc` | Rows, columns, grids and clipped scrolling exist. There is no general native recycled collection/table/tree API. Scroll offset is a vertical scalar; portable scroll-position notifications, anchor restoration and two-axis programmatic navigation need contracts. |
| `GUI/MacOS/MacOSTextField.btrc` and other MacOS owners | Actual AppKit controls. The text field delegates editing to AppKit and preserves unchanged text. This is valuable implementation, but does not prove all IME, undo, assistive-technology or mixed native/GPU journeys. |
| `GUI/Linux/LinuxApplication.btrc`, `LinuxPainter.btrc`, `LinuxTextField.btrc` | SDL windows with WebGPU-painted controls. The text field implements caret, selection and clipboard itself; movement uses UTF-8 scalar boundaries, which do not establish grapheme-cluster editing. The SDL adapter flattens committed `SDL_EVENT_TEXT_INPUT`, without a corresponding text-editing/preedit payload branch. Treat full IME composition and native-widget semantics as gaps. |
| `GUI/IGPUView.btrc`, `Capture.btrc`, provider GPU/capture owners | Embedded GPU rendering and capture have implementations. Preserve them and qualify clipping, occlusion, resize, focus and accessibility when adding toolkits; a readback image is not a screen-reader tree. |
| `src/stdlib/UI/UI.btrc`, `Render.btrc`, `Semantics.btrc`, `Typography.btrc` | A separate custom renderer already has retained trees, semantics, focus, text editing, adjustable ranges, selects and virtual grids. Reuse suitable semantic values and action boundaries. No OS accessibility bridge was found in the audited GUI/UI sources; internal activation and semantic metadata alone do not establish one. |
| `src/stdlib/App/App.btrc` | Keyboard, pointer and scroll value contracts exist, including cancellation and scroll phases. Touch identity, multi-touch, pen data, keyboard insets and mobile scene facts need explicit extensions. |
| BTRSmith `src/application/adapters/{ApplicationView,PlayerScreen,SettingsScreen}.btrc` | Real native controls already compose Library, Settings and Player. Preserve their persistent editor owners. Search/select/slider sampling and manual geometry expose stdlib event/layout gaps; `ApplicationView.present` currently rejects widths below 480, a concrete mobile-layout blocker. |
| BTRSmith `src/frontend/library/AlbumGrid.btrc` | A product-owned recycled pool and binding counters already exist. Extract a reusable collection contract only after preserving stable identities, scroll anchors and bounded binding behavior; do not replace it with one native view per album. |
| `src/tests/native/gui/`, `src/tests/python/test_native_linux_providers.py`, native GUI/interop tests | Existing fixtures cover controls, input, containers, sizing, work, capture and GPU surfaces through both frontends in applicable hosts. These are starting evidence, not a complete keyboard/IME/accessibility/device matrix. No live suite was rerun for this document. |

Some GUI README passages still describe native/GPU composition as future work
despite current GPU/capture owners. UI0 reconciles documentation with source and
tests, distinguishing implemented, tested, unavailable and planned behavior.

### Additional source audit: behavior behind the interfaces

The September 20 follow-up reviewed the current working-tree implementations,
not just interface names. These findings refine the existing N01–N60 families;
they do not increase the family count or establish a runtime test result.

| Source owner | Observed behavior | Work to include in the milestone |
| --- | --- | --- |
| `GUI/Linux/LinuxWindow.btrc::deliverKey` | An open overlay receives keys first, then window subscriptions, then the focused control. A window subscriber can consume an editor shortcut before the editor sees it. | UI3: specify preflight interception versus ordinary product commands; prove editor precedence and modal command scope. Preserve intentional low-level event consumption while keeping playback commands out of text entry. |
| `GUI/Linux/LinuxButton.btrc`, `LinuxSlider.btrc`, `LinuxScrollView.btrc` | Their `key` methods return false. `LinuxSlider.focus` does no work. Existing pointer interaction does not supply these controls' keyboard interaction. | UI3/UI4/UI6: test default button activation, focus indication, arrow/page/home/end range changes and keyboard scrolling through real focus traversal. Treat these as explicit Linux gaps during provider migration. |
| `GUI/Linux/LinuxTextField.btrc::key` | Implements navigation, deletion, select-all and clipboard shortcuts, but this handler has no undo/redo branch. Committed text enters through `textInput`. | UI3: prove undo transaction grouping, redo invalidation, native composition and grapheme-safe boundaries. Do not count the existing ASCII edit fixture as complete editor qualification. |
| `GUI/Linux/LinuxDirectoryPicker.btrc`, `GUI/MacOS/MacOSDirectoryPicker.btrc` | Linux pumps events in a loop until the dialog answers; macOS calls `runModal`. The shared result represents a selected directory as a string path. | UI7/P3: replace the synchronous call with parent-owned asynchronous completion and a resource capability that can represent non-path mobile selections. Exercise parent close and permission revocation without nested dispatch assumptions. |
| `GUI/MacOS/MacOSButton.btrc`, `MacOSSelect.btrc`, GUI README | Bordered button/select font sizes above 20 pt are explicitly unsupported. | UI4/UI5: define native large-text adaptation and remeasure controls; prove the largest supported accessibility size without throwing, clipping, silently capping text, or replacing ordinary controls with painted substitutes. |
| `GUI/IWindow.btrc`, `IApplication.btrc` | Window title/size/visibility and application quit/work exist; the public interfaces do not expose close veto, scene restoration, external open requests or active-document command targeting. | UI1/UI3/UI7: distinguish application, scene, window and document lifetime. Route file/URL activation and menu commands to the intended document, including when a second window closes. |
| `UI/Semantics.btrc`, `GUI/IView.btrc` | Semantic values include roles, labels and state, while the native view interface exposes no shared semantic attachment or automation ID. | UI8/UI10: specify stable node identity, label/error relations, bounds and action delivery across the native/custom boundary; reuse semantic values without requiring native widgets to join the custom render tree. |
| `src/tests/native/gui/linux/LinuxGUIControls.btrc` | Sends synthetic SDL pointer/key/committed-text events, checks an ASCII edit, pointer-driven slider/select/scroll and composed capture. | UI10: retain this regression, then add actual toolkit/IME and assistive-technology evidence. Distinguish event injection, native automation and physical input in each result; none substitutes for the others. |

The next implementation recommendation is scoped events plus an editor/focus
vertical slice, followed by forms and virtual collections. Large-text rejection,
command precedence and modal reentrancy should have failing behavioral fixtures
before their APIs change. Native-control defaults are useful baseline behavior,
but application labels, relations and custom content still need explicit
accessibility integration; GTK documents that distinction in its
[accessibility contract](https://docs.gtk.org/gtk4/section-accessibility.html).

### Further contract gaps found in the source inventory

These are additional planning requirements within N01–N60, not new capability
families or claims of reproduced runtime failures. They make the scope of a
usable native toolkit more precise before provider implementation starts.

| Audited boundary | Concrete limitation | Recommendation and acceptance case |
| --- | --- | --- |
| `App/App.btrc::AppKeyCode`, `GUI/Linux/LinuxWindow.btrc::keyCode` | The public key enum has unknown plus 24 named values, with only eight letter keys; no Page Up/Down, function-key or complete shortcut vocabulary. The Linux mapping mixes logical symbols and physical scancodes into that one enum. | UI3/N07: distinguish physical key identity, layout-dependent key meaning, command binding and committed text. Preserve unknown events and native handling. Add remapping/discovery without adding one enum member for each product shortcut. E25. |
| `GUI/IView.btrc`, `IStack.btrc`, `Linux/LinuxStack.btrc` | `fittingWidth()` and `fittingHeight()` take no constraints. Linux stacks query those independent sizes when arranging children. There is no shared height-for-width, baseline or grow/shrink request. | UI5/N23–N24: define constrained measurement and invalidation, then qualify wrapping labels, dynamic errors and native editors together. Preserve existing hidden-child space behavior until an explicit collapsed mode is available. E26. |
| `GUI/MacOS/MacOSLabel.btrc::setCentered` | Turning centering off explicitly selects left alignment. The portable label API has no leading/trailing alignment choice. | UI5/N14/N44: add semantic alignment that follows reading direction, while retaining an explicit physical alignment when needed. Qualify mixed-direction text and label/control baselines. E26. |
| `GUI/IView.btrc`, `IWindow.btrc`, `App/App.btrc` | Pointer coordinates are documented as local logical points; surface metrics exist, but the shared view/window APIs offer no view-to-window/screen conversion, anchor rect or display-change subscription. | UI3/UI5/UI7/N08/N25/N34: one provider-owned coordinate contract must serve hit testing, popover placement and accessibility bounds through nested scrolling and fractional scale. E27. |
| `UI/Semantics.btrc::UISemantics` | Roles and scalar states exist, but this value owner has no relation references, accessible text ranges, table coordinates or action-pattern contract. Labels, hints and values are each validated at a 512-byte limit. | UI8/N41–N42: reuse these values, then supply native relations and semantic operations through the appropriate owner. Keep full editor/document text separate from bounded labels; specify recoverable over-limit behavior instead of silently dropping the accessible node. E28. |
| `GUI/IContainer.btrc`, `IView.btrc` | Attach/detach ownership is explicit; there is no ordered move or batch-update contract. A future data diff needs a defined outcome when one native mutation fails. | UI2/UI6/N03/N27: preserve surviving identities and either commit an update coherently or report a consistent partial/rolled-back state. Do not promise atomic native toolkit behavior that a provider cannot deliver. E29. |
| `GUI/IApplication.btrc`, `MacOS/MacOSApplication.btrc`, `Linux/LinuxApplication.btrc` | Delayed work is owned and cancellable, with native timer versus tick-deadline implementations. The shared API does not specify scene-suspension policy or cross-clock event timing. | UI1/UI2/UI9/N01/N04/N48: classify work as cancel, defer or replace on suspension; define monotonic timing and do not replay stale animation work after resume. E30/E32. |
| `GUI/MacOS/MacOSStack.btrc::__del__`, application and view close/drain contracts | Native destruction can require the UI executor; some destructors fail fatally if asynchronous cleanup has not completed. Ordinary reference release alone is not a general asynchronous disposal protocol. | UI2/N03–N04: audit every native owner for explicit shutdown, final release, callback failure and partial-construction cleanup. Keep the existing drain contract and prove the caller can complete it during application shutdown. E31. |
| `GUI/Linux/LinuxSelect.btrc::key`, `menuHeight`, `paintOverlay`, `scroll` | Keyboard handling returns false while the menu is closed. Popup height includes every option; painting visits every option; wheel input is consumed without changing a scroll position. Placement only chooses above or below. | UI3/UI4/UI7/N19/N34: qualify keyboard opening, viewport-bounded popups, reachable offscreen options and search/type-ahead. A three-item pointer fixture cannot establish a usable large selector. E33. |
| `GUI/ISelect.btrc`, both provider `setItems` implementations | A nonempty option list requires a selected index; there is no explicit unselected/loading state. Replacing items rebuilds their presentation and enabled state; Linux also closes the popup. | UI2/UI4/N05/N19/N22: define stable-key refresh, unavailable selection and loading/error/empty outcomes together. Preserve disabled-item policy and active interaction, or report an explicit cancellation when continuity is impossible. E02/E33. |
| `GUI/ISlider.btrc`, `MacOS/MacOSSlider.btrc`, `Linux/LinuxSlider.btrc` | The public API can change only the value, not minimum/maximum/step. Both constructors reject more than 1,000 intervals; the public value is a `double`. | UI2/UI4/N05/N18: define coherent range/value updates, degenerate ranges and precision without replacing the focused control. Separate logical steps from visible tick marks and retain exact product timeline coordinates outside any normalized native projection. E34. |
| `GUI/IImageHandle.btrc`, `MacOS/MacOSImageView.btrc`, `Linux/LinuxImageView.btrc` | The shared comment says views keep their own reference. macOS assigns the native image to the view; Linux retains the mutable handle and skips painting after that handle is explicitly closed. Releasing a caller's reference and calling `close()` are distinct operations with an unclear portable outcome. | UI2/UI4/N03/N20: specify whether publication retains an independent presentation resource or observes handle invalidation. Recommend independent retained presentation, consistent with the existing interface intent; test two views sharing one image, explicit close, replacement and detach. E35. |
| `GUI/Linux/LinuxPainter.btrc::imageTexture`, `evictImages`, `beginFrame` | Uploaded images are cached by identity. Eviction runs every 64 rendered frames for entries unused for more than 240 frames; this owner has no aggregate image-byte limit. A per-image pixel limit and a bounded cell pool do not bound retained decoded/native/GPU artwork or ensure eviction after rendering stops. | UI6/UI9/N20/N27/N48/N49: add byte-accounted admission and eviction tied to ownership and memory pressure, without creating repaint work to advance a cache clock. Bound decoded, in-flight and uploaded resources together. E36. |
| `GUI/Linux/LinuxFonts.btrc::advance`, `LinuxPainter.btrc::text`, `LinuxSystemText.btrc::raster` | Measurement and drawing walk Unicode scalars, retrieve individual glyphs and sum advances. Font resolution chooses regular/bold sans faces; missing glyph handling falls back to a question mark. These paths do not implement shaping runs, contextual joining, bidi layout or a per-run font fallback chain despite the system-text file's shaping description. | UI5/UI9/N44/N49: use native text layout for controls and a qualified shaping/layout owner for retained custom GPU text. Share shaped advances, cluster mapping and ink bounds between measurement and drawing; audit raster/atlas overflow separately. E37. |
| `GUI/Capture.btrc`, both `GUIProvider.btrc::capture` implementations and `MacOSComposedCapture.btrc` | The shared layer contract says composition never waits for GPU work on the UI thread. macOS captures the requested view and validates descendant, duplicate and backing-size constraints on supplied layers. Linux finds the owning window, ignores the supplied layers and renders the whole window; it can poll GPU readiness with 1 ms sleeps for up to 5 s. | UI9/UI10/N47/N49/N50: define subtree scope, completed-frame identity, layer validation and readiness outcomes before treating provider captures as interchangeable visual evidence. Separate asynchronous preparation from bounded composition; keep native interaction and accessibility checks independent. E38. |
| `GUI/IView.btrc`, `Linux/LinuxView.btrc::setVisible`, `LinuxWindow.btrc::locateIn`, `deliverKey`, `settle` | Visibility is explicitly the view's own flag. Linux changes that flag and invalidates paint; identity lookup traverses hidden ancestors, and focus settlement checks presence rather than effective visibility. Keyboard/text and captured-pointer routing use that lookup. The shared API has no subtree interaction-state contract. | UI2/UI3/UI5/UI8/N05/N06/N08/N24/N41: separate local visibility, inherited eligibility, layout participation and actual exposure. Define focus, composition, pointer cancellation, popup dismissal and semantic-tree changes when an ancestor becomes unavailable. Add a behavioral regression before claiming a live failure. E39. |
| `GUI/Linux/LinuxApplication.btrc::pumpEvents`, `runWork`, `runDelayed`, `GUI/Linux/SDL.h::btrcSdlPollEvent` | The event loop dispatches at most 4,096 events, but polls the next event at the end of each iteration. At the limit it can remove event 4,097 without dispatching or retaining it. Immediate work drains a whole captured batch, and delayed work scans the live list; admission capacity alone does not establish fair scheduling between input, work and rendering. | UI2/UI3/UI9/N04/N05/N08/N48: preserve every dequeued event across yields, bound each scheduling turn, and specify fair progress for native input, completions, timers, presentation and shutdown. Add boundary and sustained-load fixtures, including release/commit/close events at the batch edge. E40. |
| `GUI/IScrollView.btrc`, `Linux/LinuxScrollView.btrc::scroll`, `Linux/LinuxWindow.btrc::deliverScroll`, `Linux/SDL.h` | The shared offset is vertical only. Linux consumes a wheel event whenever the document overflows, even when clamping prevents motion; horizontal deltas do not move this viewport. Linux delivery always reports `precise=false` and no gesture/momentum phase. Floating-point wheel deltas alone do not establish pixel units or native momentum support. | UI3/UI6/N08/N09/N26: define axis, unit, gesture ownership and boundary handoff, including remaining motion after a child partially consumes it. Preserve native scrolling and expose unavailable phase information honestly. E41. |
| `GUI/IWindow.btrc`, `Linux/LinuxWindow.btrc::dispatch`, `needsFrame`, `isVisible` | Window-hidden/minimized events return without updating `_visible`; frame eligibility uses that stored flag. The public interface exposes visibility/focus queries but no exposure state or transition subscription. Requested visibility, minimized state, occlusion and a usable drawable are not one fact. | UI1/UI5/UI9/N01/N02/N25/N48: separate requested visibility from observed exposure and drawable availability. Suspend unnecessary presentation, preserve pending invalidation and restore one current frame; explicitly represent unknown occlusion. E42. |
| `GUI/IGPUView.btrc`, `Linux/LinuxWindow.btrc::pollDevice`, `render`, `Linux/LinuxApplication.btrc::run` | GPU polling/error reporting exists. Linux window rendering counts unavailable frames and throws after more than 120 attempts; the application loop closes on an escaping error. The shared GUI API does not define retry timing, recovery ownership or a presentation-failure event. | UI1/UI2/UI9/N02/N04/N47/N48: classify transient surface unavailability, device loss and terminal failure, with bounded retries and a scoped recoverable outcome. A failure in musical GPU content must not require discarding the native editor or healthy windows. E43. |
| `GUI/Linux/LinuxTextField.btrc::copySelection`, `key`, `paste`, `App/App.btrc::AppClipboardText` | Copy ignores the clipboard write result; cut then deletes the selection unconditionally. Paste checks for a null pointer but does not distinguish an empty error result before replacing the selection. The shared clipboard result value exists, but these editor paths do not use it. | UI3/UI7/N10/N37/N40: treat cut and paste as fallible editing transactions. A failed write must not delete text; a failed read must not become an empty replacement. Preserve native editor ownership and expose a recoverable outcome. E44. |
| `GUI/ITextField.btrc`, `Linux/LinuxTextField.btrc::paste`, `replaceSelection`, `offsetAt`, `MacOS/AppKitText.btrc` | No shared input-size or normalization policy is declared. Linux copies a complete clipboard string before validation, rebuilds the text on replacement, and repeatedly measures prefixes for pointer-to-caret lookup. Programmatic Linux text assignment checks null but does not perform the UTF-8 check used by its input path; AppKit conversion rejects invalid UTF-8. | UI3/UI4/UI7/N10/N15/N16/N37: define validation, explicit limits and native range conversion at the editor boundary. Measure long-text behavior, preserve drafts on rejection and avoid adding a second text engine. E45. |

These are source-level contract findings; no live rendering failure was
reproduced during this inventory. In particular, handle invalidation needs a
portable contract decision and a regression before changing either provider.
Keep native object release, GPU retirement and application references distinct.

The event-loss finding follows from the loop's control flow and the wrapper's
call to `SDL_PollEvent` with a non-null destination: that call removes an event
from the queue. It has not yet been reproduced in a running provider fixture.
[SDL event dequeue contract](https://wiki.libsdl.org/SDL3/SDL_PollEvent).

For the proposed GTK provider, evaluate Pango's paragraph layout and logical
index/visual-position mapping for custom text as well as native labels. This
is a recommendation to reuse a native text owner, not to write another shaper
or assume that changing the widget provider repairs existing GPU text.
[Pango layout and position mapping](https://docs.gtk.org/Pango/class.Layout.html).

For large selections, prefer a native model-backed control with a bounded popup
and search where appropriate. GTK's dropdown already exposes a list model,
item factories and optional popup search; this supports the proposed Linux
direction but does not qualify BTRC's bindings or establish equivalent behavior
on the other providers. [GTK dropdown](https://docs.gtk.org/gtk4/class.DropDown.html).

The constrained-measurement recommendation maps to actual toolkit concepts:
GTK measurement accepts a constraint on the opposite axis and returns minimum,
natural and baseline sizes. This is evidence for the contract shape, not a
decision to expose GTK types in portable APIs.
[GTK measurement](https://docs.gtk.org/gtk4/method.Widget.measure.html).
Android likewise distinguishes hardware key callbacks from software-keyboard
editing; portable shortcut events must not become the text-input protocol.
[Android keyboard actions](https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/commands).
Windows accessibility requires supported operations as well as descriptive
properties, which makes action/range/selection contracts part of UI8.
[UI Automation control patterns](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview).

### Existing public API inventory

The current `src/stdlib/GUI/I*.btrc` surface contains **19 interface files,
24 interfaces and 135 directly declared methods**, including five callback/work
interfaces. Inherited methods are counted once at their declaring interface.
`GUI.btrc` adds **27 factory/service methods**. These are source counts at the
audit revision, not 162 independent behaviors or passing tests. Helper value
types, other exported GUI modules, `App`, `UI` and product callers remain part
of UI0's broader operation inventory.

| Existing owner (under `src/stdlib/GUI/`) | Declared methods | Work needed beyond the current contract |
| --- | ---: | --- |
| `IApplication` | 8 | Scene/lifecycle observation, suspend/restoration and an explicit worker-completion wakeup path. `post` and `postAfter` currently require the UI thread. |
| `IWindow` | 18 | Close veto, resize/scale/activation events, scene association, restored placement and typed asynchronous modal results. |
| `IView` | 10 | Focus, automation identity, semantics, layout invalidation, hit-test/coordinate contracts and executor-safe final release. |
| `IContainer` | 4 | Ordered insertion/move and batched subtree mutation while retaining the existing detach/attach ownership contract. |
| `IStack` | 6 | Grow/shrink, baseline alignment, width-dependent measurement and explicit collapsed state; hidden children currently retain space. |
| `IGrid` | 12 | Constraint-based sizing and spanning where needed; this fixed-cell container is not a virtual data grid. |
| `IScrollView` | 3 | Two-axis positions/events, visible rect, scroll anchors and nested-scroll policy; current offset is vertical. |
| `IButton` | 16 | Default/cancel/link roles, command binding and accessible descriptions; preserve the existing scoped action subscription. |
| `ITextField` | 6 | Draft/commit/cancel events, input purpose, secure/read-only modes, selection and native composition continuity. |
| `ISelect` | 10 | Stable option keys, change/commit events, grouped options and explicit popup behavior. |
| `ISlider` | 6 | Preview/commit events, range/step updates, accessibility value text and keyboard policy. |
| `ILabel` | 6 | Label/control association, selectable content, truncation policy, semantic text styles and baseline metrics. |
| `IImageView` | 2 | Fit/fill/alignment, semantic/decorative state and scale-aware asset presentation. |
| `IImageHandle` | 4 | Preserve owned decoded-image reuse; qualify native resource release and async handoff on every provider. |
| `IPanel` | 4 | Semantic materials/colors, resettable appearance and high-contrast behavior. |
| `IProgressIndicator` | 2 | Determinate fraction, accessible status and cancellation; currently exposes running state only. |
| `ILevelIndicator` | 2 | Range/unit semantics, threshold updates and announcement throttling. |
| `IDirectoryPicker` | 1 | Async parent-owned selection and scoped resources; open/save/multi-select require additional contracts. |
| `IGPUView` | 10 | Display-paced invalidation, device/surface recovery, overlays and accessible virtual children; preserve asynchronous close/drain. |
| Five work/input/action interfaces | 5 total | Extend typed event payloads and delivery rules; keep synchronous native decisions distinct from queued product commands. |

The five helper interfaces are `IApplicationWork`, `IButtonAction`,
`IViewPointerHandler`, `IViewScrollHandler` and `IWindowKeyHandler`. Method counts
are reproducible from interface bodies in those 19 files, excluding comments,
helper classes and inherited declarations. Updating an API requires refreshing
its row and linking the affected behavioral cases, not preserving this count.

The [individual API checklist](native-ui-api-inventory.md) now lists all **162
current interface/facade declarations** by stable owner/method ID, with source
links, inheritance and starting family/milestone/case mappings. Qualification
requires **1,620 operation mapping slots** (162 × 5 providers × 2 frontends)
for this surface, with concrete-receiver checks for inherited behavior. These
slots overlap the 470 behavioral case-result slots; they are not additional
independent tests. This closes enumeration of the current interface/facade
surface only. Exact assertion mappings, other exported values/modules, product
callers and runtime evidence still keep UI0 open. The checklist also identifies
nine contract increments to implement before expanding the widget set.

### Provider baseline and recommended direction

| Platform | Audited provider state | Proposed route and proof required |
| --- | --- | --- |
| macOS | AppKit controls and GPU child surface implemented; portable contracts incomplete | Extend existing AppKit owners. Prove field-editor continuity, menu/responder routing, accessibility and multi-window behavior. |
| Linux | SDL/WebGPU window and painted controls implemented | Evaluate GTK4 as the native-widget provider first. Prove toolkit controls, IME, accessibility and embedded WebGPU on both Wayland and X11 before migration. Keep the current path working until equivalent product evidence exists. |
| Windows | No `Library.GUI` provider found | Follow W2's Win32/common-control route first, with checked COM where required. Prove Unicode editing, per-monitor DPI, UI Automation and GPU child composition. Record modern theme/control limitations; evaluate WinUI only if the required interaction cannot be delivered acceptably. |
| iOS/iPadOS | No GUI provider or mobile app lifecycle implementation found | UIKit controls, view controllers/scenes and a native GPU host through existing checked Objective-C ownership. Prove touch, keyboard/IME, safe areas, adaptive navigation and VoiceOver. |
| Android | No GUI provider or Activity/JNI implementation found | Standard Activity and native Views through A1's checked JNI boundary. Prove EditText/IME, list recycling, Back, TalkBack and GPU surface composition. This is a BTRC integration recommendation, not a claim that Views are Android's preferred framework for every new app. |

GTK has native accessibility and input contracts; this does **not** establish
that its GPU interoperability fits our pinned WebGPU runtime. UI1 must prove
that separately without assuming a GL widget accepts a WebGPU surface.
[GTK accessibility](https://docs.gtk.org/gtk4/section-accessibility.html),
[GTK input handling](https://docs.gtk.org/gtk4/input-handling.html).

Use native controls' existing accessibility where possible and add bridges for
custom content. UIKit provides accessible controls; Windows UI Automation uses
provider patterns (or automation peers with WinUI); Android custom views need
nodes/actions/events and may need virtual children. These are different native
bindings behind shared semantics, not a single platform-neutral renderer.
[UIKit accessibility](https://developer.apple.com/documentation/uikit/accessibility-for-uikit),
[Windows automation peers](https://learn.microsoft.com/en-us/windows/apps/design/accessibility/custom-automation-peers),
[Android custom-view accessibility](https://developer.android.com/guide/topics/ui/accessibility/views/custom-views).

For the proposed Win32 route, use the native UI Automation provider model;
WinUI automation peers apply only if that framework is selected.
[Win32 UI Automation providers](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-providersoverview).

### Platform readiness at the audited revision

This source-level matrix separates a shared API gap from a missing platform
provider. **Partial** means code exists but the complete contract and live
qualification remain open. **Custom** means the current implementation draws
the control itself. **Missing** means no implementation of the requested
portable native capability was found. None of these cells means qualified.
The provider declarations in `src/stdlib/GUI/btrc.toml` select only macOS and
Linux; the three new providers also require the platform-roadmap prerequisites.

| Native capability | macOS | Linux | Windows | iOS/iPadOS | Android |
| --- | --- | --- | --- | --- | --- |
| Application/window owner and event loop | Partial | Partial | Missing | Missing | Missing |
| Native buttons, labels, fields, selects and sliders | Partial | Custom | Missing | Missing | Missing |
| Shared edit/change/commit subscriptions for fields/selects/sliders | Missing | Missing | Missing | Missing | Missing |
| Native stack/grid/scroll container integration | Partial | Custom | Missing | Missing | Missing |
| Native virtual list/table/tree contracts | Missing | Missing | Missing | Missing | Missing |
| Shared focus scopes and command routing | Partial | Partial/custom | Missing | Missing | Missing |
| Complete asynchronous picker and resource-access contract | Partial | Partial | Missing | Missing | Missing |
| Shared semantics bridged to OS accessibility, including GPU children | Missing | Missing | Missing | Missing | Missing |
| Embedded GPU surface and composed capture | Partial | Partial | Missing | Missing | Missing |
| Adaptive mobile scene/navigation/inset contracts | Missing | Missing | Missing | Missing | Missing |

The accessibility row concerns the common semantics bridge, not whether an
individual AppKit control already exposes native accessibility. Likewise,
existing GPU support outside `Library.GUI` does not supply a Windows or mobile
GUI surface owner. The full source inventory below retains these distinctions; UI0 still needs
the operation-level catalog and execution evidence.

### Complete family-by-platform source inventory

This is the initial **60 × 5 = 300-cell source inventory**. Read each N-ID
with its contract and milestone in section 2. **P** means a provider implements
a relevant subset, with shared API work and qualification outstanding. **C**
means related behavior is implemented by custom controls in that provider;
native-widget parity remains open. **M** means no provider implementation of
that portable family was found in the audited surface. These classifications
are neither pass counts nor estimates of remaining effort.

The scope includes `Library.GUI` and the adjacent `Library.Tray` service.
Internal custom `Library.UI` semantics and BTRSmith-specific widgets remain
reuse candidates described below; they do not supply a missing native provider.
For N10/N37/N40/N42/N43, macOS **P** credits the existing native editor/control
foundation, not a verified shared editing or accessibility contract. N41 remains
missing because native control defaults do not provide a custom-content bridge.
Windows/mobile **M** means the BTRC integration is absent, not that the OS lacks
the capability. A documented platform adaptation is decided per operation later.

| Family | macOS | Linux | Windows | iOS/iPadOS | Android | Milestone |
| --- | --- | --- | --- | --- | --- | --- |
| N01 — App/scene lifecycle | P | P | M | M | M | UI1 |
| N02 — Window management | P | P | M | M | M | UI1 |
| N03 — View ownership and mutation | P | P | M | M | M | UI2 |
| N04 — UI executor and work | P | P | M | M | M | UI2 |
| N05 — Control events and state | P | P | M | M | M | UI2 |
| N06 — Focus and traversal | P | C | M | M | M | UI3 |
| N07 — Commands and shortcuts | P | P | M | M | M | UI3 |
| N08 — Pointer and capture | P | P | M | M | M | UI3 |
| N09 — Touch, pen and gestures | M | M | M | M | M | UI3 |
| N10 — IME and editing transactions | P | C | M | M | M | UI3 |
| N11 — Buttons and links | P | C | M | M | M | UI4 |
| N12 — Checkbox, radio and switch | M | M | M | M | M | UI4 |
| N13 — Segmented control | M | M | M | M | M | UI4 |
| N14 — Labels and read-only text | P | C | M | M | M | UI4 |
| N15 — Text/search/password fields | P | C | M | M | M | UI4 |
| N16 — Multiline plain-text editor | M | M | M | M | M | UI4 |
| N17 — Numeric entry/stepper | M | M | M | M | M | UI4 |
| N18 — Slider and adjustable range | P | C | M | M | M | UI4 |
| N19 — Select/combo box | P | C | M | M | M | UI4 |
| N20 — Images and symbols | P | P | M | M | M | UI4 |
| N21 — Progress and meters | P | C | M | M | M | UI4 |
| N22 — Forms and validation | M | M | M | M | M | UI4 |
| N23 — Intrinsic and constrained layout | P | C | M | M | M | UI5 |
| N24 — Stack/grid/container semantics | P | C | M | M | M | UI5 |
| N25 — Adaptive viewport | M | M | M | M | M | UI5 |
| N26 — Scrolling | P | C | M | M | M | UI6 |
| N27 — Virtual list/collection | M | M | M | M | M | UI6 |
| N28 — Table/data grid | M | M | M | M | M | UI6 |
| N29 — Tree/outline | M | M | M | M | M | UI6 |
| N30 — Selection models | M | M | M | M | M | UI6 |
| N31 — Tabs and navigation | M | M | M | M | M | UI5 |
| N32 — Split panes and toolbars | M | M | M | M | M | UI5 |
| N33 — Menus and context menus | M | M | M | M | M | UI7 |
| N34 — Popovers, tooltips and transient UI | P | C | M | M | M | UI7 |
| N35 — Alerts, sheets and dialogs | P | P | M | M | M | UI7 |
| N36 — Open/save/folder pickers | P | P | M | M | M | UI7 |
| N37 — Clipboard and edit commands | P | C | M | M | M | UI7 |
| N38 — Drag/drop and transfer | M | M | M | M | M | UI7 |
| N39 — Open/share/reveal | M | M | M | M | M | UI7 |
| N40 — Undo/redo and document state | P | M | M | M | M | UI7 |
| N41 — Native accessibility bridge | M | M | M | M | M | UI8 |
| N42 — Accessible collection/text/range behavior | P | M | M | M | M | UI8 |
| N43 — Assistive input and focus | P | M | M | M | M | UI8 |
| N44 — Typography and localization | P | C | M | M | M | UI5 |
| N45 — Appearance and text scaling | P | C | M | M | M | UI5 |
| N46 — Motion, transparency and haptics | M | M | M | M | M | UI5 |
| N47 — GPU/native composition | P | P | M | M | M | UI9 |
| N48 — Frame/invalidation scheduling | P | P | M | M | M | UI9 |
| N49 — Assets and rendering fidelity | P | P | M | M | M | UI9 |
| N50 — Inspection, testing and diagnostics | P | P | M | M | M | UI10 |
| N51 — Date/time/calendar picker | M | M | M | M | M | UI11 |
| N52 — Color/font picker | M | M | M | M | M | UI11 |
| N53 — Rich text and attributed content | M | M | M | M | M | UI11 |
| N54 — Web content view | M | M | M | M | M | UI11 |
| N55 — Print and document preview | M | M | M | M | M | UI11 |
| N56 — Notifications, badges and tray/status item | P | P | M | M | M | UI11 |
| N57 — Media/system transport UI | M | M | M | M | M | UI11 |
| N58 — Advanced data editing | M | M | M | M | M | UI11 |
| N59 — Specialized document surfaces | M | M | M | M | M | UI11 |
| N60 — Help, services and platform extensions | M | M | M | M | M | UI11 |

The source anchors for existing cells are the provider and interface audit
above: application/window/view owners for N01–N08; the named controls for
N10–N26; tooltip/alert/picker/editor owners for N34–N40; native controls and
text/theme owners for N42–N45; GPU/capture/native fixtures for N47–N50; and
`Tray/{MacOS,Linux}/TrayProvider.btrc` for N56. Missing rows identify contracts
to add, rather than inviting a duplicate owner for neighboring functionality.
Reclassify individual operations as they are implemented and tested; a whole
family must not become “passed” because its simplest control works.

#### Existing tray integration to preserve

`Tray/Tray.btrc` already defines tray models, checked items, show/pump/run/close,
and two native providers. The macOS owner uses AppKit status items and menus;
the Linux owner implements StatusNotifierItem and DBusMenu. N56 is therefore
partial. This does not supply application/context menus (N33), notifications,
badges or Windows/mobile service providers.

The current `TrayItem.command` and `stateCommand` are shell strings. Both
providers execute those commands synchronously in their dispatch paths. Extend
the command/ownership contracts from UI2/UI3 to support typed in-process
application actions and state updates; retain shell execution as an explicit
consumer choice. Qualify how tray pumping joins the application's event loop,
which owner may stop that loop, and how outstanding work drains on close.

UI11's N56 exit evidence must include **100 create/update/activate/close cycles**,
**exactly one application command per accepted activation**, **0 late actions
after close**, and **0 leaked owned registrations/connections**. Inject a slow
explicit external command and verify it runs off the UI executor under owned
cancellation, preserving the existing **≤100 ms p95** semantic-command delivery
goal. Exercise missing/restarted Linux tray hosts with an explicit availability
outcome. Native notifications/badges need their own permission, activation and
revocation cases; a working tray must not count as their implementation.

## 2. Capability inventory

**P** = partial portable contract or implementation; **M** = missing portable
native contract in the audited GUI surface; **C** = related custom-renderer
behavior exists but is not a portable native control. These are source-audit
states, not pass/fail results. Provider defaults can supply some behavior even
when the portable API cannot configure or observe it. All rows still require
new providers on Windows/iOS/Android; macOS and Linux need the listed contract
work plus provider-specific qualification.

Rows N01–N50 form the proposed core native UI scope. N51–N60 remain explicit
extended toolkit milestones; they need not block BTRSmith unless an existing
journey requires them. Do not silently remove them from a claim of full toolkit
coverage. An OS-restricted desktop service needs a documented mobile adaptation,
not a fabricated empty-success implementation.

### Application, ownership and input

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N01 | App/scene lifecycle — P | Startup, activation, suspend/resume, memory pressure, recreation and durable restoration; OS-owned mobile event loop. | UI1 |
| N02 | Window management — P | Close request/veto, resize/move/scale/visibility events, fullscreen, multi-window/scenes, modal parent and restored placement. | UI1 |
| N03 | View ownership and mutation — P | Preserve detach/attach/close/drain; define reparenting, child ordering and atomic update boundaries; no orphan native children. | UI2 |
| N04 | UI executor and work — P | Cancellable queued/delayed delivery, bounded worker-completion wakeup, explicit overload behavior, reentrancy and failure propagation; separate frame scheduling from timers. Existing `post` is UI-thread-only. | UI2 |
| N05 | Control events and state — P | Typed edit/change/commit/cancel subscriptions; programmatic setters do not emit user actions; coalesce continuous changes without dropping final commits. | UI2 |
| N06 | Focus and traversal — P/C | Focus query/request, tab order, scopes, restoration, focus-visible state, hidden/disabled removal and native/GPU traversal. | UI3 |
| N07 | Commands and shortcuts — P/C | Stable commands with enabled/checked state; responder routing, platform modifiers, key equivalents, editing precedence and discoverability. | UI3 |
| N08 | Pointer and capture — P | Mouse buttons, hover/cursor, trackpad precision, coordinate conversion, capture loss and cancellation on detach/close. | UI3 |
| N09 | Touch, pen and gestures — M | Contact identity, gesture arbitration, long press, pinch, pen metadata where available; accessible alternatives and cancellation. | UI3 |
| N10 | IME and editing transactions — P/C | Native composition/preedit/commit/cancel, dead keys, selection ranges, undo/redo grouping; no refresh replacing the active editor. | UI3 |

### Controls, forms and content

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N11 | Buttons and links — P | Default/cancel roles, accessible icon-only actions, toggle state, link activation and native keyboard semantics. | UI4 |
| N12 | Checkbox, radio and switch — M | Boolean/tri-state values, mutually exclusive groups, labels and change events; choose native desktop/mobile presentation. | UI4 |
| N13 | Segmented control — M | Stable item IDs, exclusive/multiple selection as supported, keyboard and compact overflow behavior. | UI4 |
| N14 | Labels and read-only text — P | Alignment, wrapping, truncation, selectable text, associated control labels and accessible descriptions. | UI4 |
| N15 | Text/search/password fields — P | Search/clear/submit, read-only/secure modes, native input purpose/autofill policy, selection and events; protect secure contents from diagnostics. | UI4 |
| N16 | Multiline plain-text editor — M/C | Wrapping/scrolling, selection, native IME/undo, clipboard, limits and accessible text ranges. | UI4 |
| N17 | Numeric entry/stepper — M | Typed value/range/step, locale parsing, intermediate invalid drafts, commit and validation; preserve editing text. | UI4 |
| N18 | Slider and adjustable range — P/C | Continuous preview versus commit, keyboard steps, units, precision and accessible min/max/value; preserve 64-bit timeline coordinates. | UI4 |
| N19 | Select/combo box — P/C | Stable keys, disabled/grouped options, type-ahead, optional editable combo, change/commit, popup focus and selection preservation on updates. | UI4 |
| N20 | Images and symbols — P | Fit/fill/alignment, scale variants, semantic icons, tint, alt text/decorative state, async decode cancellation and bounded cache. | UI4 |
| N21 | Progress and meters — P | Determinate/indeterminate progress, status text and cancellation; meter units/ranges and announcement throttling. Current progress interface is running state only. | UI4 |
| N22 | Forms and validation — M | Label/control/error relationships, dirty drafts, validation on edit/commit, pending work, first-error focus and save/cancel. | UI4 |

### Layout, collections and navigation

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N23 | Intrinsic and constrained layout — P | Width-dependent measurement, min/preferred/max, grow/shrink, baseline alignment, invalidation and bounded relayout. | UI5 |
| N24 | Stack/grid/container semantics — P | Padding/gaps/alignment, hidden versus collapsed, clipping/z-order, attach/detach and nested dynamic content without editor replacement. | UI5 |
| N25 | Adaptive viewport — M/P | Safe areas, keyboard occlusion, logical units, rotation, split screen, compact/wide navigation and mobile widths below 480. | UI5 |
| N26 | Scrolling — P | Two-axis positions, notifications, scroll-to-item/rect, momentum, nested scroll ownership, visible range and stable anchors. | UI6 |
| N27 | Virtual list/collection — M/C | Stable keyed data source, reusable cells, async loading/cancellation, selection, focus, empty/error states and bounded native owners. | UI6 |
| N28 | Table/data grid — M | Virtual rows, typed columns, headers, sort/filter, column sizing, row actions and editable cells; mobile detail adaptation. | UI6 |
| N29 | Tree/outline — M | Lazy expansion, hierarchy announcements, stable selection, keyboard navigation and unloaded-node failure/retry. | UI6 |
| N30 | Selection models — M/C | Single/multi/range selection, anchor and active item independent of recycled view; stable identity through sort/filter/delete. | UI6 |
| N31 | Tabs and navigation — M | Native tab/sidebar/stack navigation, history/back, dirty-screen dismissal and per-destination restoration. | UI5 |
| N32 | Split panes and toolbars — M | Resizable desktop panes, sidebar collapse, toolbar overflow and compact mobile equivalents. | UI5 |

### Presentation and OS services

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N33 | Menus and context menus — M/C | Main/window/context menus backed by shared commands; checked/radio items, submenus, key equivalents and native invocation. | UI7 |
| N34 | Popovers, tooltips and transient UI — P/C | Anchor ownership, screen-edge placement, outside-dismiss, keyboard escape, focus return, accessibility and parent-close cancellation. | UI7 |
| N35 | Alerts, sheets and dialogs — P | Typed buttons/results, default/cancel/destructive roles, nonblocking completion, validation, modal focus scope and nested-request policy. | UI7 |
| N36 | Open/save/folder pickers — P | Async single/multiple selection, filters, save/overwrite, scoped resources/content URIs and distinguish cancel/error/revocation. Existing directory chooser is only a subset. | UI7 |
| N37 | Clipboard and edit commands — P/C | Text plus typed data where supported; cut/copy/paste/select-all routed to focused owner, native lifetime and explicit denial/unavailable outcome. | UI7 |
| N38 | Drag/drop and transfer — M | Internal/external typed payloads, copy/move intent, lazy file data, hit feedback, cancellation and keyboard/touch alternatives. | UI7 |
| N39 | Open/share/reveal — M | OS open URL/document, share sheet and reveal where available, capability results and scoped resource lifetime. | UI7 |
| N40 | Undo/redo and document state — P/C | Native editor undo stays with editor; shared command undo owns product mutations, dirty state and close/save decisions without double dispatch. | UI7 |

### Accessibility, visual adaptation and custom surfaces

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N41 | Native accessibility bridge — M/C | Native roles/names/values/states/relations/actions, stable identity, screen bounds, notifications and inspectable custom GPU children. | UI8 |
| N42 | Accessible collection/text/range behavior — P/C | Virtual item realization, reading order, text selection, adjustable timelines, busy/live status and modal isolation; no duplicate native/custom nodes. | UI8 |
| N43 | Assistive input and focus — P/C | Screen-reader, keyboard-only, switch and voice-control journeys; visible focus, gesture alternatives and no focus traps. | UI8 |
| N44 | Typography and localization — P | Native shaping/fallback, grapheme/word boundaries, bidi/RTL, locale formats, translated expansion and font-metric invalidation. | UI5 |
| N45 | Appearance and text scaling — P | System/light/dark, high contrast, semantic colors, disabled/selected/focused state, increased text size and contrast-safe custom content. | UI5 |
| N46 | Motion, transparency and haptics — M/P | Observe reduced motion/transparency; nonanimated alternatives, meaningful opt-in haptics and no color/motion-only feedback. | UI5 |
| N47 | GPU/native composition — P | Clipping/z-order, overlay controls, occlusion, hit testing, resize/DPI, surface loss/recreate and coordinated presentation. | UI9 |
| N48 | Frame/invalidation scheduling — P | Display-paced animation only when needed; idle windows do no application relayout/repaint work; bounded work during scroll/audio. | UI9 |
| N49 | Assets and rendering fidelity — P | Scale-aware images/icons, color/alpha consistency, font packaging, cache invalidation and native/GPU screenshot composition. | UI9 |
| N50 | Inspection, testing and diagnostics — P | Stable automation IDs, layout/focus/owner diagnostics, accessibility inspection and real native input/device tests through both compilers. | UI10 |

### Extended toolkit scope, retained as open work

| ID | Capability / state | Required contract and acceptance | Milestone |
| --- | --- | --- | --- |
| N51 | Date/time/calendar picker — M | Locale/calendar/timezone policy, ranges and accessible native selection. | UI11 |
| N52 | Color/font picker — M | Native dialogs where available, typed color/font results, preview/cancel and capability adaptation. | UI11 |
| N53 | Rich text and attributed content — M | Native spans/links/attachments, editing/selection, copy/paste, accessibility and bounded document resources. | UI11 |
| N54 | Web content view — M | Native engine owner, navigation policy, script-message ownership, load/error/cancel and accessible focus traversal; no renderer replacement for ordinary controls. | UI11 |
| N55 | Print and document preview — M | Native print/preview flow, pagination/export, cancellation and mobile share/print adaptation. | UI11 |
| N56 | Notifications, badges and tray/status item — P | Preserve existing macOS/Linux `Library.Tray` providers; add typed app-command integration, notification permission/action routing, badges and lifecycle qualification. Tray has no compulsory mobile equivalent. | UI11 |
| N57 | Media/system transport UI — M | Now-playing metadata/actions and lock-screen/system media integration sharing product commands. Promote earlier if P5 inventory requires it. | UI11 |
| N58 | Advanced data editing — M | Reorderable sections, drag handles, inline cell editors, hierarchical tables and accessibility-preserving identity. | UI11 |
| N59 | Specialized document surfaces — M/C | Reusable accessible diagram/chart/timeline host contracts with navigation/zoom; retain BTRSmith's existing custom musical renderers. | UI11 |
| N60 | Help, services and platform extensions — M | Context help, native services and narrowly typed provider capabilities; explicit unsupported results and owned lifetimes. Shared SDK availability/update resilience is a core UI1/UI10 prerequisite, not deferred with these extensions. | UI11 |

## 3. Contracts before implementation

Keep cohesive interface owners rather than adding a universal widget with
dozens of unrelated optional fields. Reuse `CallbackScope`, registrations,
native import schemas, generated adapters and existing close/drain behavior.
The proposed contracts must work through both compilers. Compiler gaps belong
in shared specs and the correct pipeline owners, never emitter string patches.

1. **State and events:** each control owns its native interaction state.
   Product updates change its model without replacing focus, selection or IME
   state. User edit, commit and cancellation are distinct. An event carries
   stable identity and sufficient typed state to avoid querying a detached
   native object later. Prevent feedback loops and duplicate commands.
2. **Dispatch and lifetime:** synchronous event consumption remains necessary
   for pointer/key propagation; queued semantic actions use explicit ordering.
   Define whether each subscription is synchronous or queued. Test cancel in
   callback, close with queued work, handler failure, overflow and detach/
   reattach. Never block the audio callback on UI work or dispatch UI from it.
   `GUI.post` is not currently a worker-safe dispatcher. Connect the existing
   `BackgroundJobExecutor` completion ownership to a bounded native-loop wakeup,
   with generation checks and shutdown draining. Define a rejection/backpressure
   outcome for ordered commands and coalescing only for replaceable state.
   Test a producer racing teardown; do not solve wakeup with permanent polling
   or silently relax UI-thread checks on current owners.
3. **Text ownership:** native editors own composition and undo; application
   validation sees drafts and committed values separately. Keep native range
   units private or convert them explicitly to the public UTF-8 contract.
   A byte or scalar offset is not a grapheme boundary. Empty, non-BMP, combining
   and RTL strings must survive round trips without splitting text.
4. **Focus and commands:** one command path serves menu, key, touch, automation
   and accessibility actions. Text editing gets first chance at its shortcuts;
   playback keys must not consume space while typing. Focus and selection
   remain meaningful when collection cells are recycled or a dialog closes.
5. **Layout:** measure in logical coordinates, distinguish available-size
   constraints from intrinsic size, and invalidate on content/font/scale/theme
   changes. Define visibility versus layout participation explicitly; preserve
   existing hidden-child behavior until consumers migrate. No relayout loops.
6. **Collections:** data identity is separate from cell identity. Cancellation
   and generation checks prevent stale artwork/data from binding to a reused
   cell. Item models own selection and edits; view pools own presentation.
   Accessibility may request realization without allocating the whole list.
7. **Accessibility:** common semantic values feed native objects and virtual
   GPU children. Reuse `UISemantics` where it fits; extend its ownership and
   notifications rather than maintaining two unrelated trees. Native controls
   should not appear twice. Screen readers receive useful transport/range
   state, not one announcement per rendered frame or musical note.
8. **Async services:** dialogs, pickers, transfers and external actions have
   complete/cancel/error outcomes and owned lifetimes. Parent close, scene loss
   and permission revocation resolve pending work exactly once. Migrate the
   synchronous picker boundary without nested event-loop assumptions.
9. **Platform adaptation:** common semantics do not require every platform to
   expose every window style or service. Typed capabilities describe genuine
   restrictions. UI views must not leak HWND, Objective-C or JNI handles into
   product models. Explicit provider projections alias existing owners.
10. **Design resources:** product branding belongs in named semantic roles for
    color, typography, spacing and icons; providers resolve native defaults and
    invalidate affected views when appearance or text size changes. Separate
    application artwork from OS symbols. Localization needs resource keys,
    plural/argument formatting, bidirectional isolation and accessible labels,
    not only translated visible strings. Audit existing `UI/Typography` and
    GUI font/image owners before defining additional types. These are N20 and
    N44–N49 work, including packaging in P4/P7; avoid a second styling engine.
11. **Scene and document identity:** the application owns native activation;
    each scene/window owns focus, navigation and pending presentation. Product
    documents own durable edits and shared command state. Opening a second
    window must not duplicate audio engines or transfer another window's modal
    result. External open/share requests need queued, validated delivery before
    or after scene creation, with explicit duplicate and recovery behavior.
12. **Input privacy and presentation:** secure text, autofill, spellchecking,
    capitalization and IME action are explicit editor policies. Preserve native
    password accessibility behavior without copying secrets into semantic value
    strings, logs or test captures. Software keyboard visibility and insets are
    layout facts; switching hardware keyboards must not fabricate a commit or
    discard a draft. These extend N10/N15/N25 rather than a separate input stack.
13. **Effective interaction state:** preserve `isVisible()` as the local flag;
    define separately whether a view can currently receive input through its
    ancestors and modal scope. Hiding, disabling, collapsing, detaching and
    ordinary viewport clipping have distinct outcomes. Specify a subtree
    disable policy without overwriting each child's own enabled preference.
    Losing eligibility must settle capture, hover, popups, focus and active
    composition under an explicit commit/cancel policy. Restoring eligibility
    must not replay an old gesture or steal focus. Hidden subtrees leave the
    accessible presentation; disabled controls retain the appropriate native
    discoverability and unavailable state. Offscreen virtual collection items
    retain their accessible realization contract. Command availability is
    rechecked when queued actions run.

GTK separately exposes inherited visibility and sensitivity, which supports
this distinction; inherited visibility itself does not establish unobscured
screen exposure. Keep those concepts distinct in every provider rather than
mapping all of them onto `IView.isVisible()`.
[GTK effective visibility](https://docs.gtk.org/gtk4/method.Widget.is_visible.html),
[GTK effective sensitivity](https://docs.gtk.org/gtk4/method.Widget.is_sensitive.html).

Android input purpose and IME actions are native editor configuration, not
application key-event emulation.
[Android input-method configuration](https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/style).

### Binding and OS-update prerequisites

These apply to the core native UI, alongside P1's platform binding work:

- **GTK:** represent GObject ownership, floating-reference adoption, signal
  registration/disconnection and callback return values in the existing checked
  binding model. Widget creation alone does not qualify ownership on teardown.
  [GObject reference adoption](https://docs.gtk.org/gobject/method.Object.ref_sink.html).
- **Windows:** qualify HWND destruction, message reentrancy, COM reference
  ownership/apartment requirements and UI Automation callbacks for the selected
  provider. Preserve native synchronous results without queuing them as actions.
- **Apple:** extend the existing checked Objective-C delegate/block ownership
  for app/scene, text and accessibility callbacks. Record deployment minimum,
  build SDK and runtime API availability separately. The audited
  `src/language/native_abi.asdl` has no complete availability model; a newer
  header's declaration does not establish that an older OS can load the app.
- **Android:** qualify Java/Kotlin shell ownership, JNI local/global references,
  thread attachment, exceptions and callbacks after Activity destruction.
  A `JNIEnv` belongs to its thread; do not cache it as a shared GUI handle.
  Keep this in the common checked native boundary and a small platform shell.
  [Android JNI guidance](https://developer.android.com/ndk/guides/jni-tips).

Use public SDKs and native defaults. Optional APIs need provider-owned capability
checks plus correct load/link behavior on the declared minimum version. Preserve
unknown native result/enum values as diagnostic data rather than treating them
as success. Keep application screens free of OS-version branches. Windows OS
API availability and separately shipped UI framework versions are distinct.
[Windows version adaptation](https://learn.microsoft.com/en-us/windows/apps/develop/testing/version-adaptive-code).

UI1 records these binding risks; UI10 proves the same built artifact on minimum
and current supported OS versions, then rebuilds unchanged product source with
the newer supported SDK/toolkit. Exercise unavailable APIs, font/theme/scale
changes and teardown. Native chrome may change with OS releases; preserve
interaction, layout and product-art requirements without freezing old widget
pixels. Ordinary OS updates should require no product source changes, but this
is not a promise of maintenance-free providers or no future rebuilds.

## 4. Milestones and dependency order

Every milestone below is open. Progress is per platform and capability, with
implementation and qualification tracked separately. A finished macOS slice
does not complete the five-platform milestone.

### UI0 — Freeze the inventory and executable acceptance catalog

Expand every family into public operations, native defaults, expected
adaptations and negative cases. Record provider, source owner, test, required
hardware/OS, frontend and result. Inventory BTRSmith's actual runtime callers,
not just legacy render projections. Reconcile GUI/UI documentation and record
the selected support floors from P0.

Exit: **60/60 families classified on 5 platforms (300 planning cells)**, plus
an operation-level denominator covering 100% of current public GUI APIs and
product UI journeys. No unclassified or silently excluded cases. Source-only,
implemented-unverified, passed, adapted, OS-restricted and missing stay distinct.
This audit supplies all 300 source classifications, not a completed test
report. UI0 remains open for operation-level coverage, ownership/test mapping
and documentation reconciliation.
Seed the catalog with the public-interface inventory above. Each operation case
records its N-ID, declaring owner, provider implementation, native default or
adaptation, regression fixture, compiler frontend and observed result. Record
both missing implementation and unavailable test evidence when both apply;
an unavailable runner must not turn a missing provider into an unverified one.

### UI1 — Prove each native shell and toolkit boundary

Dependencies: UI0; P1 and the relevant W1/I1/A1 host/binding prerequisites for
new platforms. Build the same small fixture containing a native text field,
button, scrolling collection and embedded GPU region. Prove input, focus,
resize, accessibility inspection and teardown before implementing all widgets.
For Linux, qualify GTK4/WebGPU interop on Wayland and X11, including overlapping
native controls and clipping. Do not count a CPU readback loop as the final
interactive rendering path. If this fails, record the blocker and compare an
alternative toolkit before choosing a migration, without duplicating product
policy. For Windows, prove common-control theming and COM/UI Automation needs.

Exit: fixture executes through **both frontends on all 5 platforms**, with real
native controls and 100 open/close cycles; E46/E47 must also qualify close
requests and fresh-process restoration as their dependent owners land. No lost callbacks, stale handles or
hidden toolkit/ABI blocker. Partial platform slices can unlock later work.

### UI2 — Complete shared events and ownership

Dependencies: UI1 for the provider under test. Deliver N03–N05 first: text,
selection, range, scroll and lifecycle observation with scoped registrations.
Prove event ordering and programmatic-set suppression. Migrate BTRSmith search,
filters, settings and transport values from polling to subscriptions; retain
timers only for actual timed product work. Keep existing native editor owners.

Exit: one user commit causes **exactly one product command**; unchanged state
causes zero artificial actions; all cancellation/reentrancy/close cases pass
through both frontends. Record idle polling removed at real callers.
Worker completions wake an idle native loop without periodic polling; queue
saturation and completion-after-close have explicit outcomes, with zero stale
view mutation or leaked retained payloads.
Admission limits and dispatch limits are separate: E40 must prove lossless
batch boundaries and progress for input, rendering and close while work is
continuously replenished. Never drop a final input event to yield the executor.

### First operation-level acceptance backlog

These are proposed regression cases, not tests that have passed. They make
UI1–UI3 reviewable before expanding the widget surface. Keep the behavioral
case shared; execute it through each provider and both compiler frontends.
Start from `src/tests/native/gui/`, the AppKit runtime tests and Linux provider
tests; extend their real native fixtures rather than introducing a mock UI
runtime. Each case records input mechanism, observed events/state and teardown
evidence, with physical IME and assistive-input evidence where automation
cannot exercise the relevant path.

| Case / family | Contract owner to extend | Required observable result |
| --- | --- | --- |
| E01 — Text draft/commit/cancel, N05/N10 | `ITextField`, native editor/delegate | Type, compose, commit and cancel; a commit produces exactly one semantic command. Republishing unchanged text preserves selection, composition and undo. |
| E02 — Stable selection, N05/N19 | `ISelect`, keyed option model | Reorder duplicate-label options while open; selection follows its key. Removing the selected key has an explicit outcome. Setters emit zero user actions. |
| E03 — Range interaction, N05/N18 | `ISlider`, scoped event owner | A drag emits previews and one final commit; capture loss has a defined cancellation outcome. A queued final commit is never discarded by preview coalescing. |
| E04 — Worker delivery, N04 | `IApplication`, background completion owner | Wake a sleeping native loop, cancel delivery and race window destruction; no polling dependency, stale mutation or retained payload after drain. |
| E05 — Focus restoration, N06 | `IView`, window focus scope | Tab/Shift-Tab across native and GPU controls; detach the focused view and close a modal; focus moves to a valid visible owner without a trap. |
| E06 — Command precedence, N07 | `IWindow`, shared command owner | Space and editing shortcuts operate on the focused editor; the equivalent menu/button/accessibility action invokes the product command once when appropriate. |
| E07 — Text boundaries, N10/N44 | Native editor, explicit range conversion | Combining marks, emoji sequences, non-BMP text and RTL survive selection, deletion, undo and model refresh; test actual IME preedit and commit separately. |
| E08 — Close and restoration, N01/N02 | Application/scene and window owners | A dirty document can veto dismissal; explicit discard closes once. OS-forced termination does not depend on a veto or final callback; prior durable state restores. |
| E09 — Scroll identity, N26/N30 | `IScrollView`, collection model | Insert/sort/filter during scrolling; preserve the identified anchor and focused item, or apply the documented fallback when either is deleted. |
| E10 — Async service lifetime, N35/N36 | Dialog/picker owner, scoped resource | Cancel, deny, revoke and destroy the parent; resolve once and release resources. An absent filesystem path must not turn a valid mobile resource into failure. |
| E11 — Accessible native/GPU boundary, N41/N42 | Shared semantics and provider bridge | Inspect the OS tree and operate it with the screen reader; native controls occur once, virtual GPU children retain identity and bounds after scroll/scale. |
| E12 — Toolkit/GPU interop, N47/N48 | Native surface and display scheduler | Overlay controls, resize, hide, suspend and recreate the surface; correct clipping/input and recovered rendering, with no static redraw loop. |

First checkpoint: **12/12 cases specified**, each assigned to a source owner
and platform fixture; UI1 proves the native boundary, then UI2/UI3 close their
applicable cases. E08–E12 also feed UI6–UI9 and remain open until those full
contracts pass. Do not call these twelve cases exhaustive coverage or let their
completion replace the broader input, lifecycle and 60-family requirements.

### Additional acceptance cases for platform completeness

E13–E24 expand the backlog to **24 specified cases**. Each remains open. These
cases deliberately cover behavior that a widget construction or screenshot
test misses; they supplement the operation inventory rather than replacing it.

| Case / families | Owner and milestone | Required observable result |
| --- | --- | --- |
| E13 — Keyboard-only controls, N06/N11/N18/N26 | Focus/command owner and control providers; UI3/UI4/UI6 | Traverse a form without pointing; activate its button, adjust its range and scroll its content. Disabled/hidden controls do not trap focus; supported keys change state once and preserve visible focus. |
| E14 — Native undo transactions, N10/N16/N40 | Native editor and document command owner; UI3/UI7 | Type, compose, paste, undo and redo across model refreshes. Editor undo does not undo an unrelated product command; a new edit invalidates only the relevant redo history. |
| E15 — Accessibility text scaling, N14/N23/N45 | Measurement and native control owners; UI4/UI5 | Increase text size during editing, including beyond the current 20 pt button/select limit. Controls remeasure, actions remain reachable and focus/selection survive; no exception or silent font-size clamp. |
| E16 — Independent windows/scenes, N01/N02/N07 | Application, scene and command owners; UI1/UI3 | Open two windows or supported scenes, edit in both, change activation and close one with pending work. Commands and completions reach the intended owner; surviving state and the shared product service remain valid. Record a single-scene adaptation where required. |
| E17 — External open and restoration, N01/N39/N40 | Activation router and document owner; UI1/UI7 | Deliver a file/URL at cold start, while running and during recreation. Validate its resource, route it once under the documented duplicate policy, and preserve unsaved state when access fails. |
| E18 — Keyboard occlusion and Back, N09/N25/N31 | Scene insets, navigation and editor owners; UI3/UI5 | Show the software keyboard, rotate/resize and attach a hardware keyboard. Keep focused content and submit/cancel reachable. Back first follows the platform's active transient/editor/navigation rules; cancellation preserves the draft. |
| E19 — Secure and specialized editing, N10/N15/N17 | Editor configuration and form validation; UI3/UI4 | Exercise password/search/numeric purposes, native submit actions and autofill where supported. Invalid numeric drafts remain editable; password contents do not enter diagnostics or custom semantic values. |
| E20 — Live environment changes, N20/N44–N46/N49 | Resource, appearance and layout owners; UI5/UI9 | Change theme/contrast/text size/locale and move between display scales. Native and GPU content update coherently; localized labels and bidi layout remain correct without replacing active editors. |
| E21 — Accessible virtual collection, N27–N30/N42 | Collection data source and accessibility bridge; UI6/UI8 | Ask the screen reader to reach an unrealized item, then sort/filter/delete it. Identity and announced position stay correct; realization respects the cell budget and has a defined deletion fallback. |
| E22 — Drag/drop cancellation, N08/N38 | Transfer session and scoped resource owner; UI3/UI7 | Drag internally and from another app, cancel or close the destination mid-transfer, and retry. Ownership/move intent is explicit, partial data is recoverable and each transfer completes once; keyboard/touch alternatives remain usable. |
| E23 — Nested presentation and command state, N07/N33–N35 | Command and presentation owners; UI3/UI7 | Open a menu/popover while work completes, disable its command, then invoke or dismiss it. Revalidate availability at invocation, prevent stale actions, enforce modal scope and return focus after dismissal. |
| E24 — Queue pressure and stale cell data, N04/N20/N27/N48 | UI executor, image and collection owners; UI2/UI6/UI9 | Saturate the declared work capacity while recycling cells and closing a scene. Reject or coalesce according to contract, retain final commits, discard obsolete image generations and release every retained payload after drain. |

### Foundation acceptance cases discovered during the inventory

E25–E32 bring the initial catalog to **32 specified cases**. All eight are open
and extend existing families. A single case contains several operations; UI0
still needs operation-level fixtures and the complete platform catalog.

| Case / families | Owner and milestone | Required observable result |
| --- | --- | --- |
| E25 — Shortcut and key identity, N06/N07/N10 | App event values, provider key mapping and command router; UI3 | Test all alphabetic shortcut keys, Page Up/Down and F1–F12 where delivered by the OS, plus remapped/non-US layouts and unknown keys. Physical bindings retain position; semantic bindings follow the declared layout policy. OS-reserved keys pass through, text comes from the editor, and each invocation dispatches at most once. |
| E26 — Constrained measurement and direction, N14/N22–N24/N44 | View measurement, labels, stacks and form layout; UI4/UI5 | Resize a form containing wrapped labels, an editor and validation text through 320/480/1024 logical-unit widths at 100/150/200% text size in LTR and RTL. Baselines and leading/trailing alignment remain correct, no required text/action clips, and unchanged measurement inputs cause no repeated layout work after settling. |
| E27 — Coordinate and anchor continuity, N08/N25/N34/N41/N47 | View geometry, popup owner and accessibility bounds; UI3/UI5/UI7/UI8 | Scroll nested containers and move a window across 100/150/200% displays while an anchored popup and GPU child are visible. Screen/view conversions round-trip within one device pixel; input and accessible bounds identify the displayed target. Moving/removing the anchor repositions or dismisses according to contract. |
| E28 — Accessible operations and text limits, N16/N28/N29/N41/N42 | Semantic values, native accessibility bridge and editor/collection owners; UI6/UI8 | Invoke, toggle, select, expand and adjust through the OS accessibility API. Query text selection and table/tree position without reconstructing them from a label string. Exercise Unicode labels at 511/512/513 bytes and editor content longer than 512 bytes; declared limits produce an explicit outcome, preserve the control and never truncate inside a character. |
| E29 — Failed and reordered tree updates, N03/N24/N27/N30 | Container mutation and keyed collection owners; UI2/UI6 | Insert/move/remove while an editor is focused and an image load is pending. Inject failure at each native mutation boundary; the resulting tree matches the documented commit/rollback policy, retained aliases agree with ownership, and retry creates no duplicate children or stale selection. |
| E30 — Suspension and deadline semantics, N01/N04/N48 | Scene lifecycle, work scheduler and display clock; UI1/UI2/UI9 | Suspend with an edit, delayed action and animation pending, change wall-clock time, then resume or recreate. Durable state survives; canceled work stays canceled, replaceable updates coalesce and expired animation frames do not replay as a backlog. Product/audio clocks remain distinct from UI timers. |
| E31 — Failure and final-release ownership, N03/N04/N50 | Provider native owners, callback boundary and close/drain protocol; UI2/UI10 | Inject construction, callback and teardown failures, including close during callback and attempted final release away from the UI executor. Follow the declared error policy, finish or explicitly report pending cleanup, and verify zero orphan handles, registrations, double release or callbacks to destroyed owners. |
| E32 — Comparable latency evidence, N04/N48/N50 | Input instrumentation, scheduler and presentation observer; UI9/UI10 | Record input receipt, command delivery, model update and actual presentation using a documented monotonic clock mapping. Report unavailable native timestamps explicitly; handler duration alone cannot satisfy the input-to-visible budget. Collect at least 100 actions with cold and warm asset states identified. |

### Selector and range completeness

E33–E34 bring the initial catalog to **34 specified cases**. These remain open
within the existing 60 families; they are required control behavior, not optional
extended widgets.

| Case / families | Owner and milestone | Required observable result |
| --- | --- | --- |
| E33 — Large and changing option lists, N05/N19/N22/N34 | Keyed selection, native popup and form owners; UI2/UI3/UI4/UI7 | Exercise 0, 1, 100 and 10,000 options at 320/480/1024 logical-unit widths, including long/duplicate labels and all-disabled options. Open without a pointer, reach the final enabled item through native scrolling/search, cancel and restore focus. Place the control at each viewport edge at 100/200% text size; popup content remains reachable. Refresh while open, preserve key/disabled state or explicitly cancel, and distinguish no selection, loading, empty and failure. Setters dispatch zero user commits; acceptance dispatches exactly one. |
| E34 — Changing ranges and exact values, N05/N18/N42 | Adjustable value model, slider providers and product timeline adapter; UI2/UI4/UI8 | Change duration/range/step while focused and during a drag; define clamp, reject or cancel behavior and apply range/value coherently without replacing the owner. Exercise zero-length and reversed ranges, nonfinite input, 999/1,000/1,001 logical intervals, negative/fractional values and exact timeline values around 2^53. Keep 64-bit product values exact through keyboard/accessibility increments and no-op refresh; any pointer quantization has a documented bound. Visible ticks need not equal logical steps. One accepted interaction produces one commit; canceled interaction produces no stale commit. |

Use the existing 100-sample latency budget for large selector operations and
100 range/refresh/cancellation cycles for these cases. Report popup realization
and update work at each list size; apply UI6's cell budget to provider-owned
recycled presentation. Toolkit-internal allocations must be measured separately,
not assumed bounded because the public API accepts a data model.

### Images, bounded resources and shaped text

E35–E37 bring the initial catalog to **37 specified cases**. They extend the
existing families and apply to custom musical surfaces as well as ordinary
native controls; migrating Linux widgets must not leave these paths unaudited.

| Case / families | Owner and milestone | Required observable result |
| --- | --- | --- |
| E35 — Published image lifetime, N03/N20 | `IImageHandle`, both image-view owners and future providers; UI2/UI4 | Publish one handle to two views, release the caller's reference, then separately exercise explicit handle close, replacement, clearing and view teardown in each order. Under the recommended retained-presentation contract, already-published images remain valid until their views replace or clear them; new publication of a closed handle fails explicitly. Run 100 cycles, including worker creation and UI-thread publication, with zero blank/stale images, use-after-free or leaked native resources after drain. |
| E36 — Artwork budget and idle eviction, N20/N27/N48/N49 | Image loading/ownership, collection and provider cache owners; UI6/UI9 | Traverse the 1,000-album catalog with fixed 256/512-pixel thumbnail variants and oversized-source fixtures; account for decoded, staging, native and GPU allocations, in-flight work and retired uploads. Stay within the byte and concurrency budgets below. Stop scrolling and stop rendering, then request cache trim or simulate memory pressure through the real provider path: evict eligible resources without repainting, preserve currently displayed images and recover on demand. Cancel/recycle/close during upload for 100 cycles with no stale publication. |
| E37 — Shaping, fallback and text bounds, N10/N44/N49 | Native text layout, `TextRun`, measurement and GPU raster/atlas owners; UI5/UI9 | Freeze strings covering Latin ligatures/kerning, combining marks, Arabic joining, mixed Hebrew/Latin/numerals, Devanagari, Thai, CJK, Korean and emoji/ZWJ with named fonts/fallbacks. Match the platform layout's cluster order and advances; measured and drawn ink bounds agree within one backing pixel. Exercise wrapping, ellipsis, selection/hit mapping where exposed, scale/text-size changes, missing fonts and raster/atlas capacity. No silent glyph omission or question-mark substitution when a qualified fallback font contains the glyph. Unsupported glyphs and resource limits have explicit recoverable outcomes. |

E37 supplements E07's editing checks: a string can round-trip unchanged while
its glyph order, joining or visual caret positions remain incorrect. Compare
with the same platform's native layout and pinned fonts, not pixel-identical
screenshots across operating systems. Run all named text cases at 100/150/200%
display scale and the existing accessibility text-size matrix. Keep the current
4096-pixel system-text raster bound and 512-pixel glyph-staging bound visible in
boundary tests until a qualified replacement policy is chosen.

### Capture scope and trustworthy visual evidence

E38 brings the initial catalog to **38 specified cases** within the existing
60 families. This is a source-observed contract mismatch, not a newly reproduced
runtime failure. Capture is part of the toolkit's testing surface and needs the
same portability discipline as visible controls.

| Case / families | Owner and milestone | Required observable result |
| --- | --- | --- |
| E38 — Subtree capture and GPU readiness, N47/N49/N50 | `GUI.capture`, capture-layer values, provider capture and GPU readback owners; UI9/UI10 | Capture one of two sibling panels, including a nested GPU child: output contains only the requested subtree at its backing scale, with correct clipping and native overlays. Reject foreign, duplicate, detached and incorrectly sized layers consistently. Associate supplied readbacks with a declared frame/size generation; resize or device loss produces an explicit stale/not-ready/cancelled outcome. Preparation never sleeps or waits for GPU completion on the UI executor. Close during preparation resolves once, releases retained pixels/owners and leaves the view tree intact. |

Exercise root and nested captures at **100/150/200% scale**, ready/not-ready/lost
GPU states, and **100 capture/resize/cancel/close cycles** through both frontends.
Record output dimensions, input frame identity, capture duration and temporary
bytes; charge captures to the existing product memory budget. Keep explicit
pixel/byte admission limits before allocations. A live presented frame and a
composed offscreen snapshot are different evidence: label each result so an
offscreen image cannot satisfy E32's actual input-to-presentation measurement.
If a provider can compose from its own completed window frame, it must still
honor subtree scope and the declared frame contract; silently ignoring supplied
layer data is not an equivalent implementation.

### Effective visibility and interaction transitions

This extends existing focus and ownership work to changes that keep the view
attached. The current source paths establish a missing portable contract;
runtime behavior, including native toolkit defaults, still needs qualification.

| Case / families | Contract owner / milestone | Required result through each frontend |
| --- | --- | --- |
| E39 — Hidden or disabled subtrees, N05/N06/N08/N24/N41 | View state, focus/capture, presentation and accessibility owners; UI2/UI3/UI5/UI8 | Hide a focused editor's ancestor during composition, hide a captured slider before release, and disable a form while a popup or queued action is pending. Settle each interaction exactly once under the declared commit/cancel policy; no later input mutates an ineligible target. Move focus to a valid owner and dismiss unavailable anchors. Restore the subtree without replaying input, stealing focus or losing each child's enabled preference. Native accessibility distinguishes hidden, disabled and offscreen realizable content. |

Run **100 hide/show/disable/restore cycles** with both direct and ancestor
changes, including changes from inside callbacks. Record composition policy,
focus destination and cancellation/commit counts. Require **0 stale commits,
0 duplicate completions and 0 trapped focus paths**. Include a clipped but
otherwise eligible control as a negative control: clipping alone must not be
treated as document closure or destruction. Preserve the existing hidden-child
layout behavior until consumers explicitly adopt a collapsed state.

### Lossless event batches and fair scheduling

| Case / families | Contract owner / milestone | Required result through each frontend |
| --- | --- | --- |
| E40 — Event batches under sustained load, N04/N05/N08/N48 | Application event pump, native event adapter, queued/delayed work and presentation owners; UI2/UI3/UI9 | Queue identifiable events around the provider's dispatch limit, then continuously replenish input and short work while rendering two windows or independently updating regions. Every dequeued non-coalescible event is delivered once or explicitly canceled by its lifetime policy. Final releases, text commits and close requests survive batch boundaries; pending timers, worker completions and other windows continue to progress. Self-posting immediate/delayed work cannot monopolize a turn. |

For the current Linux limit, exercise **4,095 / 4,096 / 4,097 / 8,193 events**,
placing a release, committed-text event and close request at the boundary in
separate trials. Record enqueue success so OS queue rejection is distinguished
from provider loss. Repeat **100 bursts** with **0 unexplained losses,
duplicates or reordered ordered events**. If the dispatch limit changes, retain
these regressions and add limit−1/limit/limit+1/two-limits+1 cases. Event
coalescing is allowed only for declared replaceable state; record its policy
and preserve final values and terminal events. Do not require unrelated native
event classes to share a global order the OS does not provide.

Run a separate **10-minute sustained-load** fixture with bounded, nonblocking
handlers, recording producer rate, admitted/rejected work, queue depth, handler
duration and longest service gap per work class. Target **p95 ≤100 ms** from
admission to delivery for short semantic commands and **≤250 ms maximum**
service gap for runnable input/completion/timer/presentation classes under the
declared load. A close request must begin shutdown within **250 ms**; asynchronous
resource drain keeps its separate lifetime contract. Future-deadline timers,
hidden-window presentation and intentionally canceled work are not runnable.
Measure presentation against the existing frame budgets as well. These are
proposed controlled-load goals, not a promise to preempt an arbitrary blocking
application callback. Report overloaded and blocking-handler trials separately;
explicit rejection cannot be counted as successful delivery. Preserve the
30-minute BTRSmith audio/UI soak as the product gate.

### Nested scrolling and gesture ownership

| Case / families | Contract owner / milestone | Required result through each frontend |
| --- | --- | --- |
| E41 — Scroll units, axes and boundary handoff, N08/N09/N26 | Native event adapter, view input and scroll/collection owners; UI3/UI6 | Nest vertical and horizontal viewports around a GPU timeline. Exercise each boundary, diagonal input, partial consumption, direction reversal, momentum, popup interception and detach during a gesture. Route remaining motion under a documented platform policy without duplicating it or trapping the outer viewport. Programmatic scroll-to-item and accessibility scrolling use the same stable content coordinates. |

Qualify **100 gestures per input class**: detented wheel, precision trackpad,
touch pan and keyboard/accessibility scroll, where each is supported. Include
fractional deltas, a zero-range child, content shrink during scrolling, RTL and
100/150/200% scale. For a deterministic fixture with overscroll disabled, target
**≤1 logical unit final-position error** against the declared unit conversion,
**0 duplicated deltas**, and **0 stranded end/cancel transitions**. Native
elastic overscroll and fling curves keep platform behavior; do not require
identical physical trajectories across platforms. Record missing native phase
information rather than synthesizing false precision. Retain UI6's frame and
recycling budgets during the interaction.

Android's nested-scroll protocol explicitly distinguishes consumed and
unconsumed motion; use that as a provider mapping, without exposing Android
interfaces in the portable API. SDL's wheel payload supplies floating-point
axes and direction, which alone does not promise pixel deltas or phase events.
[Android nested scrolling](https://developer.android.com/reference/androidx/core/widget/NestedScrollView),
[SDL wheel payload](https://wiki.libsdl.org/SDL3/SDL_MouseWheelEvent).

### Window exposure and presentation failure

| Case / families | Contract owner / milestone | Required result through each frontend |
| --- | --- | --- |
| E42 — Exposure and drawable transitions, N01/N02/N25/N48 | Application/scene, window state and presentation scheduler; UI1/UI5/UI9 | Minimize, hide, cover, restore, move between displays and temporarily lose the drawable while updates arrive. Distinguish user-requested visibility, observed exposure, application activity and drawable availability. Retain the latest model/invalidation without replaying obsolete frames; background audio/completions follow their own lifecycle policies. Unknown compositor occlusion remains unknown. |
| E43 — Recoverable presentation failure, N02/N04/N47/N48 | GPU device/surface, GUI host and application error owner; UI1/UI2/UI9 | Force transient acquisition failure, device loss, failed recreation and close during retry. Cancel work tied to the retired GPU generation, preserve native editors and product state, and recreate only affected resources. Report a persistent error through native UI with retry/close actions. Unrelated healthy windows continue handling commands; shared-device failures name their actual affected scope. |

Run E42 for **100 exposure/restore cycles**, including two windows and an
animated GPU child. After settling a known non-presentable window, require
**0 application presentation attempts over 60 seconds**; this excludes explicit
offscreen capture and genuinely required background work, which are recorded
separately. Restore the latest frame within **100 ms p95** after the provider
reports a usable drawable, measured separately from device initialization.
Keep editor selection, scroll anchor and pending semantic actions; no focus
steal or input replay. Where occlusion cannot be observed, report that coverage
limit and still qualify hide/minimize/drawable-loss behavior. AppKit exposes
occlusion separately from window visibility; the shared model must retain that
distinction rather than assuming every provider can detect complete coverage.
[AppKit window state](https://developer.apple.com/documentation/appkit/nswindow).

Run E43 for **100 fail/recover/close cycles** using fault injection at the real
provider boundary, followed by native device/surface recreation trials. Proposed
retry ceiling: **10 attempts per second**, with an explicit failure outcome
within **5 seconds** of continuous retryable failure; waiting for a hidden or
zero-size surface is an exposure state, not a failed attempt. Never sleep on
the UI thread. Once replacement resources are ready, present current content
within **1 second** in the controlled fixture. Require **0 stale-generation
callbacks**, **0 unintended healthy-window closes**, and **0 leaked owned GPU
resources** after drain, retaining the existing ≤5% settled-memory-growth gate.
Do not count the application's exception-driven shutdown as successful recovery.
If the provider cannot recover a particular device failure, a responsive native
error/close flow is required and the recovery limitation stays explicit.

### Clipboard transactions and bounded editing

These cases refine N10/N15/N16/N37/N40 without adding capability families.
The Linux source findings above are not live failure reproductions. SDL's
clipboard write returns a success flag; its read can return an empty allocated
string on failure, including allocation failure. Checking only for null is
insufficient evidence of a successful read.
[SDL clipboard write](https://wiki.libsdl.org/SDL3/SDL_SetClipboardText),
[SDL clipboard read](https://wiki.libsdl.org/SDL3/SDL_GetClipboardText).

| Case / families | Contract owner / milestone | Required result through each frontend |
| --- | --- | --- |
| E44 — Failed clipboard operations preserve edits, N10/N37/N40 | Native editor, focused edit-command routing and clipboard outcome; UI3/UI7 | Inject write failure during cut and read failure during paste at the actual provider boundary. Preserve text, selection, composition and undo history on failure; distinguish empty content, unavailable format, denied access and backend error where the OS exposes them. Successful cut/paste creates exactly one edit transaction. A delayed transfer cannot mutate a closed editor or a newly focused recipient. |
| E45 — Text admission and long-edit behavior, N10/N15/N16/N37 | Native editor configuration, string/range conversion and transfer admission; UI3/UI4/UI7 | Exercise construction, setters, typing, composition, paste and drop against the same declared text policy. Reject invalid or oversized input with a recoverable outcome and no partial draft mutation. Keep native UTF-16/code-point ranges distinct from BTRC byte offsets; test combining sequences, non-BMP characters and reversed selections. Measure pointer placement, selection and replacement at the declared maximum. |

For E44, run **100 success/failure/retry cycles per supported operation**, with
**0 lost selections**, **0 mutations on failure**, **0 duplicate undo entries**
and **0 late deliveries after close**. A successful edit has one undo group;
programmatic setters retain their separate contract. Do not claim durable
clipboard delivery: acceptance means the platform accepted the transfer, and
another application may subsequently replace clipboard contents. Reuse native
edit commands where possible; a portable result type must not route ordinary
native editing through a competing application text buffer.

For E45, use configurable fixture limits of **64 KiB for a single-line field**
and **1 MiB for a multiline editor**, testing **L−1, L and L+1 UTF-8 bytes** as
well as empty text and multibyte characters crossing the boundary. These are
qualification fixture configurations, not mandatory global limits for every
product field or a ceiling for future document editors. Declare byte limits
separately from user-visible character counts. Reject the entire over-limit
edit by default; never silently truncate a grapheme or alter an IME commit.
Specify line-ending normalization before evaluating the resulting content.
An explicit model replacement during composition needs a cancel/defer outcome,
not an accidental partial commit.

At each admitted fixture size, collect **at least 100 pointer/selection/edit
samples** with the existing **p95 ≤100 ms** response goal; include validation,
conversion and layout in the timing. Record peak allocation and native storage
alongside the existing working-set budget. Admit size before making avoidable
BTRC copies; if an OS API allocates the full transfer first, report that boundary
and qualify oversized-input refusal without claiming a preallocation bound.
Keep failures inspectable without including secure-field contents in logs,
automation snapshots or restoration records; reuse E19's secure-input checks.

### Dismissal transactions and durable scene restoration

The source audit makes the close gap concrete: `MacOSWindowEvents.windowShouldClose`
in `GUI/MacOS/MacOSWindow.btrc` always returns true; Linux's
`LinuxApplication.renderWindows` closes a window when `closeRequested()` is
set. `IWindow` exposes final close/drain but no portable request/decision hook.
`IApplication` likewise has no scene restoration record or activation-delivery
contract. These are missing shared capabilities, not proof that an OS lacks
restoration. E46/E47 refine E08/E16–E18 within existing families.

| Case / families | Contract owner and milestone | Required observable result |
| --- | --- | --- |
| E46 — Dirty dismissal and navigation cancellation, N01/N02/N07/N31/N35/N40 | Application/scene, window close request, navigation and document command owners; UI1/UI3/UI5/UI7 | Request window close, app quit, Back, tab departure or interactive navigation while a form is dirty. Exercise Save/Discard/Cancel, failed save, repeated requests, save completion after a new edit, and parent loss. Coalesce repeated requests for the same pending decision. Close only after the intended document revision is saved or explicitly discarded; cancellation preserves the draft, route, focus and scroll anchor. |
| E47 — Versioned scene restoration, N01/N02/N25/N30/N31/N40 | Scene restoration value/codec, product persistence and activation router; UI1/UI5/UI10 | Recreate from a checkpoint in a fresh process with no native objects retained. Restore destination, stable selection/scroll identity and eligible drafts. Exercise old/current/unknown schema, truncated data, a deleted item, revoked resource access, changed display topology and external activation during restore. Recover to an operable screen with an explicit fallback; never replay Save, import, playback or another side-effecting command merely because state was restored. |

For E46, model request, pending decision, pending save and resolved outcome
explicitly. Keep the native synchronous close answer separate from asynchronous
Save/Discard/Cancel presentation; resume an authorized close without prompting
recursively. An interactive Back preview must not mutate durable state before
commit, and cancellation must not pop the route. Use Android's native Back
integration rather than treating it as an ordinary key binding.
[Android predictive Back integration](https://developer.android.com/guide/navigation/custom-back/predictive-back-gesture).

Qualify **100 dismissal/commit/cancel cycles per applicable entry path**, with
**0 lost drafts, duplicate saves, stale-revision closes or wrong-window results**.
Use two documents/windows where supported; an app-wide quit that is canceled
must leave remaining windows usable. Pending save/prompt work must preserve
E40's responsiveness budget. Forced OS termination cannot wait for consent:
restore only previously checkpointed state and report that durability boundary.

For E47, keep small versioned scene descriptors separate from durable product
records and large drafts. Persist stable IDs, route parameters and policy-approved
view state; never serialize native handles, callbacks, pending service operations,
passwords or the entire catalog. Validate size/version/identity before creating
views. Checkpoint through an atomic persistence owner, and define migration,
corruption fallback and user-dismissal policy. Android's saved-state mechanism
has different lifetime and size constraints from durable local storage; it is
not itself a document save acknowledgement.
[Android state persistence guidance](https://developer.android.com/topic/libraries/architecture/saving-states).

Run **100 fresh-process restore cycles** per supported configuration, distributing
fault injection across checkpoint writes and recreation boundaries. Require
**0 corruption of acknowledged durable product saves, 0 replayed side effects,
and 0 cross-scene state swaps**. Freeze a **64 KiB per-scene metadata fixture
budget**, with explicit overflow and separate storage for large drafts; this is
a proposed application budget, not an OS limit. Measure at least **20 launches**:
restore the interactive pre-indexed Library within the existing **p95 ≤3 s desktop /
≤4 s mobile** launch budget. Include one previous-schema upgrade and missing-item
fallback. Process-kill tests must use the platform's actual recreation path;
constructing a second view in the same process does not prove recovery.

For each of E01–E47, record all **5 provider × 2 frontend combinations** as passed,
failed, missing, unverified or reviewed adaptation: **470 case-result slots**
before expanding OS versions and devices. This is a reporting denominator,
not 470 successful tests and not permission to mark every absent backend N/A.
Run E16–E18 and E22–E24 for **100 transition/cancellation cycles** per applicable
configuration with zero wrong-owner delivery, duplicate completion or stale
mutation. Freeze the exact sequence and queue capacity in the fixture so the
count is reproducible. Also run E29–E31 for **100 mutation/suspend/cleanup cycles**
with fault positions and timer policies recorded. These repetitions reuse the
resource-lifetime budget; they are not additional capability-family counts.
Physical IME, screen-reader and installed-app evidence
remain separately required by section 6.

### UI3 — Focus, commands, keyboard, text and touch

Dependencies: UI2. Deliver N06–N10 with a real text-input fixture and mixed
native/GPU focus traversal. Test IME composition while product state refreshes,
native undo, non-US layouts, touch cancellation and shortcut precedence.

Exit: complete the input matrix in section 6 on each platform; **zero** lost or
duplicated commits, broken grapheme deletions, focus traps or playback commands
triggered by ordinary field editing. Platform-specific text ranges stay correct.

### UI4 — Complete native controls and forms

Dependencies: UI2/UI3; implement layout and accessibility alongside controls.
Deliver N11–N22, with accessible labels, native state transitions and draft/
commit validation. Replace product workarounds only after equivalent real-input
tests pass. Portable stable-key selection must survive device lists changing
while audio Settings is open.

Exit: **12/12 control families** implemented and qualified per platform, with
enabled/disabled, empty/invalid, keyboard/touch and callback-lifetime cases.
Search, audio forms, volume/speed and instrument selectors use the common APIs.

### UI5 — Adaptive layout, navigation and visual preferences

Dependencies: UI2, iterated with UI4. Deliver N23–N25, N31–N32 and N44–N46.
Remove BTRSmith's desktop minimum-width assumptions; define compact Library,
Settings and Player layouts with keyboard-safe navigation. Preserve native
control metrics and persistent editing while relaying out. E46/E47 define
transactional departure and versioned restoration across navigation changes.

Exit: layout matrix passes with **zero clipped essential actions or overlapping
editors**, RTL, text scaling, high contrast and reduced motion. Resize/rotate
and theme changes preserve state, focus and scroll anchors over 100 cycles.

### UI6 — Native virtual collections, tables and trees

Dependencies: UI3/UI5; accessibility developed with UI8. Deliver N26–N30 with
stable keyed data and bounded cell ownership. Use BTRSmith AlbumGrid and its
window caches as the concrete consumer, preserving its existing pooling gains.
Include sorting/filtering during selection, stale async results, offscreen
focus and assistive requests for unrealized items. E41 qualifies nested scrolling,
axis/unit conversion and boundary handoff alongside collection performance.

Exit: **100,000-row toolkit stress fixture** and the shared BTRSmith catalog
meet section 5 budgets; list/table/tree operations do not instantiate every row.
Publish cell counts, binds and memory alongside frame timing.

### UI7 — Menus, dialogs and desktop/mobile services

Dependencies: UI2/UI3; P3 storage/capability contracts for resource pickers.
Deliver N33–N40, sharing commands with controls. Define desktop menus/sheets
and mobile action/navigation equivalents. Test cancellation, nested requests,
external resource failures, clipboard ownership and parent destruction. E44
adds failed cut/paste transaction preservation; E45 adds consistent text admission
and long-edit qualification across input paths.

Exit: **8/8 families** qualified on applicable platforms, with reviewed
adaptations recorded for the others; no blocking picker loop or duplicate
completion in BTRSmith import, Settings or unsaved-edit flows.

### UI8 — OS accessibility and assistive journeys

Dependencies: UI2/UI3; add each bridge during UI1 and extend it with UI4–UI7,
not as a final retrofit. Deliver N41–N43 using AppKit accessibility, GTK's
accessibility backend, Windows UI Automation, UIKit accessibility and Android
nodes/actions. Include virtual GPU content and recycled collection identity.

Exit: **100% of core actionable controls** have correct names, roles, states,
actions and focus behavior; all core product journeys pass keyboard-only and
the platform screen reader. Verify VoiceOver on Mac/iPhone/iPad, Orca on Linux,
Narrator on Windows and TalkBack on Android. Exercise native switch/voice input
where supported and document failures. A semantic snapshot alone is insufficient.

### UI9 — GPU composition, scheduling and resource budgets

Dependencies: UI1/UI2/UI5; integrate UI8's custom-content bridge. Deliver
N47–N49, preserving the pinned GPU runtime. Prove occlusion, overlays, scale,
surface/device loss, suspension, capture and restoration. E42/E43 add observed
exposure, bounded recovery and preservation of the native shell during failures.
GUI delayed work is not a display clock. Separate static UI invalidation from
musical animation.

Exit: frame/idle/memory budgets pass while audio plays, including mixed native
controls over GPU content; no application full-window repaint on static idle,
unbounded uploads or per-frame accessibility notifications.

### UI10 — Product migration and five-platform release evidence

Dependencies: UI1–UI9 and applicable platform/package prerequisites. Deliver
N50 and qualify the actual installed BTRSmith entrypoint. Finish Library,
import/scan/errors, search/filter, album details, Settings and device changes,
Player transport, looping/practice, custom views and persistence. Preserve
product-specific visual and physical audio gates; UI automation cannot replace
them. Full platform release depends on this milestone, but early W2/I1/A1
shell slices can proceed before it, avoiding a dependency cycle.

Exit: **50/50 core families** have passed or reviewed genuine OS adaptations;
**zero missing core journeys**, zero blocker accessibility/input defects, all
numeric goals met on the named matrix. Publish captures, accessibility trees,
native input results, resource traces, both-frontends results and unavailable
coverage. Integrate repeatable provider tests into existing harnesses.
Include the minimum/current OS and SDK-update evidence described in section 3.

### Product slices within UI2–UI10

Ship bounded journeys through the common contracts, with provider and consumer
changes verified together. These slices do not replace the full 60-family scope.

| Order | BTRSmith slice | Acceptance that exposes the underlying gap |
| --- | --- | --- |
| 1 | Library search and filters | IME text commits once; refresh preserves composition/selection; stable filter IDs survive option changes; no per-frame text/select sampling. |
| 2 | Settings and device changes | Native validation preserves invalid drafts; device refresh does not reset an active editor; Save/Back work by keyboard, touch and screen reader; cancel restores focus. |
| 3 | Library browse and import | Native scrolling, bounded album cells, asynchronous picker/import/cancel, progress and accessible empty/error states; back navigation restores the scroll anchor. |
| 4 | Player controls with GPU content | Scrub preview/commit, volume/speed/select changes and shortcuts share commands; typing space does not start playback; overlays clip correctly and accessible transport stays usable. |
| 5 | Mobile adaptation and release | Library/Settings/Player survive rotation, keyboard occlusion, backgrounding and recreation; installed-app journeys pass on every target and both frontends. |

Address `ApplicationView.present`'s current **480–4096 width / 240–4096 height**
admission limits during UI5; the lower bound blocks small phones and the upper
bound also needs a deliberate large-display policy. Derive supported layout
limits from platform viewport/resource constraints and test overflow explicitly.
Avoid removing validation without replacing its original resource bounds.

### UI11 — Extended toolkit completeness

Dependencies: UI2–UI9 as relevant. Deliver N51–N60 as cohesive capabilities,
promoting anything used by an existing product journey into UI10 prerequisites.
Do not make a WebView, rich editor or printing engine a prerequisite for the
first Library screen. Each family still needs native ownership, accessibility,
failure/cancellation behavior and five-platform applicability evidence.

Exit: **10/10 extended families** dispositioned and qualified where supported;
the final report retains every missing or OS-restricted operation. A complete
core UI milestone is not a claim of complete extended toolkit coverage.

## 5. Numeric goals

These are proposed acceptance budgets, not current measurements. Use the
platform roadmap's named hardware classes and **10,000-song / 1,000-album**
catalog; stricter existing BTRSmith budgets prevail. The large toolkit fixture
contains 100,000 stable records without requiring 100,000 media files.

| Metric | Proposed exit goal |
| --- | --- |
| Inventory / coverage | 300 classified family/platform cells; 100% operation and journey classification; no hidden skipped evidence |
| User action to visible response | p95 ≤100 ms, excluding explicitly pending I/O; report input/debounce/dispatch/render components separately |
| Executor progress under declared sustained load (E40) | Short semantic-command admission-to-delivery p95 ≤100 ms; runnable work-class maximum service gap ≤250 ms; close starts within 250 ms; 0 unexplained event losses at dispatch boundaries |
| Library search/filter | p95 ≤100 ms after separately reported debounce on the shared catalog |
| Scroll/resize/Player presentation at 60 Hz | p95 ≤16.7 ms, p99 ≤33.3 ms over 10 minutes; report missed presents and longest stall |
| Reference 120 Hz device | Report 8.3 ms frame-budget misses separately; 60 Hz qualification is not a claim of 120 Hz parity |
| Virtual collection realization | Native cell owners ≤3 × maximum visible capacity of the viewport for the run, plus ≤2 explicitly pinned editor/focus cells; publish counts after shrinking the viewport |
| Steady collection rebinding | No offscreen full-data traversal per frame; unchanged presentation performs 0 cell rebinds; bind work bounded by entering/changed visible rows |
| Static idle, no caret blink/animation/work pending | 0 application-requested layout/paint passes after settling; mean application CPU ≤1% of one core over 60 s, measured separately with and without assistive technology |
| Scroll integrity (E41) | 100 gestures per supported input class; ≤1 logical unit deterministic final-position error; 0 duplicated motion or stranded terminal events |
| Exposure transitions (E42) | 100 cycles; 0 presentation attempts over 60 s when settled and known non-presentable; restored current frame p95 ≤100 ms after drawable readiness |
| Presentation recovery (E43) | 100 cycles; ≤10 retries/s and explicit failure within 5 s of continuous retryable failure; current frame within 1 s after resources become ready; 0 unintended healthy-window closes |
| Resource lifetime | 100 open/close/reparent/modal/recreate cycles per family; 0 leaked owned handles/registrations; settled memory growth ≤5% after warmup |
| Product steady working set | ≤512 MiB desktop / ≤384 MiB mobile, native/GPU resources reported separately and included in the aggregate as defined in P6 |
| Catalog artwork residency | ≤128 MiB desktop / ≤64 MiB mobile across decoded, staging, native and GPU image allocations, including in-flight work; a subset of the product working-set budget, not an extra allowance |
| Artwork admission and trimming | ≤2 simultaneous thumbnail decode/conversion jobs; reserve bytes before allocation, downsample to the displayed size, and cancel obsolete generations. Release all eligible unreferenced cache entries within 1 s of an explicit trim request in a quiescent fixture, with 0 application repaint passes requested solely for eviction |
| Cold pre-indexed Library | p95 ≤3 s desktop / ≤4 s mobile over 20 launches; retain P6's launch definition |
| Clipboard failure integrity (E44) | 100 success/failure/retry cycles per supported operation; 0 text/selection loss, failed-operation mutation or late delivery |
| Text admission and long edits (E45) | 64 KiB single-line / 1 MiB multiline fixture limits; L−1/L/L+1 boundaries; at least 100 admitted-size interaction samples, p95 ≤100 ms |
| Dismissal integrity (E46) | 100 cycles per applicable entry path; 0 lost drafts, duplicate saves, stale-revision closes or wrong-window results |
| Scene restoration (E47) | 100 fresh-process cycles; 0 acknowledged-save corruption, replayed side effects or cross-scene swaps; 64 KiB metadata fixture budget; 20 launches within the existing cold Library budget |
| Editing integrity | 100% named input cases pass; 0 duplicate/lost commit events; unchanged model refresh preserves selection, composition and undo |
| Accessibility | 100% core actionable controls named and operable; 100% core journeys via keyboard and platform screen reader; 0 inaccessible modal exits |
| UI activity during audio | 30-minute controlled scroll/search/dialog/playback soak with 0 app-induced xruns; retain P6 callback and physical-latency gates |

Artwork accounting counts distinct allocations once, even when two views alias
one image, and counts separate CPU/native/GPU copies separately. Include pending
GPU retirement until the resource is actually reusable. Record toolkit-private
residency or an explicit measurement limitation rather than equating a dropped
BTRC reference with recovered memory. Required visible images take precedence
over speculative prefetch; when their requested resolution cannot fit, choose
a documented lower-resolution presentation instead of exceeding the budget.

Report distributions and failures, not a single fastest screenshot. Use at
least 100 action samples, 20 launches, 10 minutes of frame data and the specified
lifecycle counts. Distinguish event-handler CPU from end-to-end presentation
latency. Exclude fixture generation from interaction timing but include actual
model projection, binding and native work. Record OS/toolkit/font/backend,
device, thermal/power mode, scale, build mode and frontend. Missing measurement
stays open; do not silently loosen a budget for a provider.

## 6. Verification matrix and review checkpoints

- **Input:** Tab/Shift-Tab, arrows/Home/End/Page keys, default/cancel, menu
  equivalents, non-US keyboard, dead keys, Japanese and Chinese IMEs, Korean
  composition, combining accents, emoji/ZWJ, Arabic/Hebrew bidi, cut/paste,
  native undo/redo, selection while refreshing, touch and pointer cancellation.
  Test both virtual keyboard and attached keyboard on mobile. Verify password
  and numeric input purpose without treating keyboard choice as validation.
- **Layout:** phone portrait/landscape starting at 320 logical units wide,
  tablet/split screen, desktop resizing and multiple monitors at 100/150/200%
  scale. Test 100/150/200% text scaling where configurable and the largest
  supported accessibility text category on mobile, LTR/RTL, long translated
  strings, dark/light/high contrast and reduced motion. Essential actions must
  remain reachable; overflow may use native scrolling/navigation.
- **Native automation:** invoke real native controls and deliver real keyboard,
  pointer, IME and accessibility actions. Programmatic `activate()` and golden
  images supplement these tests. Inspect OS accessibility trees and native
  widget identities. Virtual displays are useful Linux CI coverage but must
  be accompanied by real Wayland/X11 desktop and assistive-input sessions.
- **Platforms:** macOS AppKit; Linux Wayland and X11; Windows x64 and ARM64;
  physical iPhone and iPad plus simulator; two physical Android vendors plus
  emulator. Pin exact minimum/current OS/toolkit versions under P0. Verify
  installed artifacts, not only binaries run inside the checkout.
- **Failure and stress:** data changes during editing/scrolling, popup during
  teardown, callback cancellation within callback, queue saturation, stale
  artwork response, denied/revoked picker resources, mobile process death,
  keyboard appearance during rotation, display/scale changes and GPU loss.
- **Compiler and regression gates:** run each applicable provider fixture with
  both compilers, ownership diagnostics and supported sanitizers. Preserve the
  existing language/corpus/bootstrap/C11/generated-source/lint/format/extension
  and repository-hygiene gates for implementation changes. Platform skips and
  unavailable physical/assistive checks remain visible outstanding evidence.

Recommended sequence: UI0 → UI1 vertical slices → UI2/UI3 foundations, then
UI4/UI5/UI6/UI7 in usable product increments with UI8 accessibility and UI9 GPU
qualification throughout → UI10 installed-product gate → UI11 remaining
toolkit breadth. Execute this sequence only when bucket 4 becomes active under
PLAN.md. Technical independence from compiler representation changes does not
override the user's sequential delivery order. Review toolkit feasibility after
UI1 and API/event contracts after UI2 before expanding controls and providers.
