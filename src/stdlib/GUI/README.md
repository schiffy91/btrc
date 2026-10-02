# BTRC GUI

`import Library.GUI;` selects the native provider for the compilation target
through the `[[package.providers]]` entries in `btrc.toml`: `MacOS.GUIProvider`
(AppKit) for `macos` and `Linux.GUIProvider` (SDL3 windows drawn with WebGPU)
for `linux`. Any other target, Windows included, fails at compile time with a
missing-provider error. Call `GUI.initialize()`, create a window and controls
with `GUI.createWindow`, `GUI.createColumn`, `GUI.createRow`,
`GUI.createButton`, `GUI.createTextField` and the other `GUI.create*`
factories, attach them, then enter `GUI.run()`.

The facade returns portable `I*` interfaces. `IApplication` declares every
view factory, so providers agree on one contract. `GUI` owns capacity
validation, the single application slot (`ApplicationSlot`) and run/close; a
provider's private `GUIProvider` supplies only the application and the native
services (image handles, the directory picker, text rasterization and
capture). Both providers drain a closing subtree in `run()` for at most 10 s,
then throw `Native subtree shutdown did not complete`; on macOS the pending
owners stay retained so a later `GUI.close()` can finish them.

## Application and scheduling

`GUI.post(work)` schedules UI-thread work; `GUI.requestQuit()` stops admission.
`GUI.postAfter(delaySeconds, work)` schedules one cancellable delayed delivery
and returns an `ICallbackRegistration`. It shares the immediate-work capacity
(`GUI.initialize(workCapacity)`, default 256, 1 to 65536); overflow rejects
the new work without losing accepted work. Canceling its alias or closing the
application releases a waiting receiver without waiting for its deadline.
Delivery is never inline, errors propagate from `run()` after teardown, and
native views remain alive through the admitted call. Delay must be finite and
nonnegative. Delayed work may run late and is not a real-time or
display-synchronization API. Native GPU completion required for shutdown must
not use a domain callback that Quit intentionally abandons. Work must be posted
from the UI thread; worker-thread publication is a separate capability that
does not exist yet.

`run()` closes owned windows and detached views before returning or propagating
a work error. `GUI.close()` covers setup without loop entry and returns a
`CallbackCancellation`; `CALLBACK_CANCELLATION_PENDING` keeps the application owner. Enter `GUI.run()`
to drain that shutdown on the native executor. Closed aliases remain closed
after reinitialization. A work exception requests orderly quit and is rethrown
by `run()` after teardown.

`button.onAction(receiver, scope)` registers an `IButtonAction.invoke()` receiver
in a normal `CallbackScope` and returns an `ICallbackRegistration`. Keep that
scope with the independent component/application owner. Cancel before replacing
the receiver; scope cancellation and button close discard queued old clicks.
Model setters never synthesize actions. Native delivery is queued in click
order (a bounded `ActionMailbox`) and dispatched on the UI executor after
native event dispatch; callers do not poll an action queue.

Button and select typography is portable: bordered buttons and selects accept
fonts up to 20 points (`ButtonTypography.borderedMaximumSize()`,
`SelectTypography.maximumSize()`) and reject larger sizes instead of
overflowing the bezel; borderless buttons accept up to
`ButtonTypography.maximumSize()`, and cannot be re-bordered until their font
fits. `setBordered(false)` hides only the bezel; `setTransparent(true)` hides
all button drawing and is for hit targets, not labels.

[Native.btrc](../../../examples/gui/Native.btrc) is a portable application example:
edit a native text field, apply the window title through a queued button action,
then quit through the same application lifecycle. Its nested row/column layout
uses native intrinsic sizes, not manually assigned control frames.

## Views and layout

`IWindow`, `IView`, `IContainer`, `IStack`, `IGrid`, `IPanel`,
`IScrollView`, `IButton`, `ITextField`, `ILabel`, `ISelect`, `ISlider`,
`IImageView`, `IProgressIndicator`, `ILevelIndicator` and `IGPUView` are the
portable view contracts; they expose no SDK objects. Interface conversion
preserves the same owner: closing through a detached `IView` invalidates its
control aliases. `arrange(x, y, width, height)` uses logical points from the
parent's top-left and requires attachment first. Fitting sizes are native
minima, so a flexible text field may report zero minimum width. Visibility
denotes the control's own flag, not actual on-screen exposure.

`GUI.createRow(spacing)` and `GUI.createColumn(spacing)` return `IStack`.
Attach ordinary controls or nested stacks; the provider performs recursive
layout. Spacing defaults to eight logical points; `setPadding(top, right,
bottom, left)` sets nonnegative insets. `STACK_ALIGN_START`/`_CENTER`/`_END`
control cross-axis alignment. Native control sizes and reading order are
retained. Hidden children keep their space and parent; detach removes them
from layout. `layout()` flushes pending layout without rebuilding controls,
reading active editors, or replacing their undo state.
`GUI.createContainer()` remains the plain grouping primitive for explicit
placement. `GUI.createPanel(fill, radius)` is a filled container that can also
switch its descendants to a dark or light appearance.

`GUI.createGrid(columns, rows, columnSpacing, rowSpacing)` returns `IGrid`.
Set cells to detached child views; nested grids are ordinary children. Cells
own their attached subtrees: replacing or clearing a cell detaches its
previous view without closing it, allowing explicit reuse, and closing the
grid closes every occupied cell. A child must be detached before it moves to
another cell or container. Explicit row/column sizes return to content sizing
with `fitRow`/`fitColumn`; hidden rows and columns take no space.

Containers (`IContainer` and its stack, panel, scroll and grid forms) take
subtree lifecycle responsibility on `attach`; `detach` returns the same open
child. Closing an attached child through an alias is rejected. Parent close
and ordinary scope cleanup close descendants despite surviving aliases;
detached children remain independent. Multiple parents, ancestor cycles and
reentrant mutations are rejected. Children do not strongly retain their parent.

`IView.close()` starts shutdown once and reports completion. `pollClose()`
advances already-started cleanup without retrying failed native operations; it
reports `CALLBACK_CANCELLATION_NOT_REQUESTED` on a live view. Native controls complete immediately. A
container retains pending children, closes siblings independently, and removes
a child only after `CALLBACK_CANCELLATION_COMPLETE`. `isOpen() == false` means admission has
stopped, not that native cleanup finished. Dropping an unfinished subtree
owner is a diagnosed lifecycle error, not permission to free native borrowers.

`IWindow.attachRoot(view)` transfers a detached root to the window; replace it
explicitly with `detachRoot()` first. `root()` returns an alias, not another
lifecycle owner. The root fills the content area and resizes with the window.
Explicit window close and ordinary owner scope cleanup close the root subtree,
including controls held by aliases. Dimensions exclude native window chrome.
`isOpen()` and `isVisible()` remain safe after native or explicit close and
return false; operations needing a live native window still reject access.
The native close button closes an application-owned window's subtree from the
application loop, outside the native callback; consumers need not poll a
closing application-owned window themselves.

`IView.onPointer` and `onScroll` register synchronous, scoped native handlers;
return true to consume an event. A consumed press captures drag/release until
release, focus loss, detach, cancellation or close. Coordinates are view-local,
top-left logical points. `IWindow.onKey` routes keys before the focused control.

`GUI.chooseDirectory(request)` runs the provider's modal directory picker
(see `IDirectoryPicker.btrc`). `GUI.createImageHandle(pixels)` converts decoded
pixels to a native image on any thread, before or after `GUI.initialize`.

## GPU views and capture

`GUI.createGPUView(capture = false)` returns `IGPUView`, an ordinary native child
for `IContainer`/`IWindow`. The view owns its frame renderer and the
asynchronous programs and readbacks created through it. Call `poll()` from
scheduled UI work until it returns true, then `beginFrame(...)` refreshes
backing-pixel dimensions after layout and skips hidden/empty views.
`frameRenderer()` supplies the existing portable GPU drawing API. Create
programs with `view.createProgram(...)` and captures with `view.readback(...)`
so their pending native callbacks belong to this subtree. On macOS a frame is
capturable only when the view was created with `capture = true` or after
`requestCapture()`; Linux GPU views render offscreen and are always
capturable. Shutdown closes renderer aliases immediately, drains asynchronous
work, then releases the GPU resources; the application shutdown loop keeps
polling pending views, and product code must not spin on the UI thread.

`GUI.capture(root, layers)` returns an image of a view subtree with each
`GUICaptureLayer`'s completed GPU readback composed in. It does not depend on
capturing an unlocked desktop. The Linux window already composites its GPU
children, so there the layers are only validated (see the Linux provider).

## macOS provider

AppKit providers and SDK headers live under `MacOS/`. Each GPU view owns its
own surface, device and frame renderer. Stacks and grids use AppKit layout
(`NSStackView`, `NSGridView`); detaching a stack child restores its previous
Auto Layout policy, and detaching a window root restores its previous
autoresizing policy. Failed attachment rolls back frame and resize policy;
indeterminate detach/shutdown failure remains unavailable without retrying
native cleanup. A failed container close remains unavailable and reports its
original error without retrying the child; native attachment errors roll back,
and an unsuccessful rollback leaves the container failed and retaining the
potentially attached child.

`MacOSApplication.run()` enters the real AppKit loop; `requestQuit()` requests
exit without tearing down controls inside the calling native callback. Native
application Quit uses the same request through a generated delegate. Owned
subtrees close before the loop stops; final application subscriptions drain
after loop return. A wake event is posted because AppKit observes `stop:` after
dispatching an event, not merely after running a timer. A pre-run request skips
loop entry only when no work remains to drain. The owner cannot be restarted
after closing. New windows are rejected as soon as Quit is requested, before
loop exit. Reentrant run/close and a second concurrent application owner are
rejected; failed construction cancels its unpublished subscription.

Posted work runs through an actual `NSRunLoop` one-shot block; completed
callback states are pruned on submission and delivery uses no polling timer.
Quit stops admission and skips queued domain work, but keeps native
completion callbacks alive until they return. Closing with pending work is
rejected: enter `run()` to drain it. Work may retain the application until
completion. `postAfter` uses a checked `NSTimer` stored-block binding in the
default run-loop mode, so it may run late during tracking/modal work.

The native close button is observed through a checked `NSWindow` delegate. For
application-created windows it marks the window closed immediately and signals
the run loop; closed windows are cleaned up before queued commands, cancelling
their stale button actions. Application `close()` cancels window subscriptions
and closes their trees; one failure does not skip siblings or retry an
indeterminate native close. The callback receiver contains only close state
and the wake signal, not a strong reference back to the window owner.

Button actions wake the loop through `MacOSRunLoopSignal`
(`MacOS/MacOSRunLoop.btrc`), which posts a notification with its own sender
identity on AppKit's default notification queue, coalescing only wakeups for
window cleanup and action delivery; it never coalesces clicks. Each delivery
batch is bounded by its starting size; remaining clicks schedule another
run-loop pass. Cancellation invalidates queued generations. Overflow is a
persistent error even if cancelled entries are subsequently pruned. Handler
failure requests quit and is rethrown after normal application teardown. The
application owns the wake subscription outside its receiver graph; ordinary
callback scopes own user subscriptions. Action delivery uses no polling timer,
raw receiver pointer or second reference-counting system.

If native modal work is active, Quit first stops that modal with the SDK abort
response so its caller can return. Views remain alive until callbacks drain;
the directory picker reports abort as cancellation. This uses AppKit's
[modal stop operation](https://developer.apple.com/documentation/appkit/nsapplication/stopmodal%28%29?language=objc),
not a nested polling pump. Asynchronous sheets and arbitrary nested-modal stacks
still need lifecycle integration and qualification.

`GUI.run()` enters AppKit's own run loop, the only native event dispatch; there
is no embedded pump. Applications use the target-selected factory and native
scheduling described above. GPU subtree shutdown, worker publication and broader
dialog handling still prevent full GUI qualification.

Pending window/subtree closure uses one application-owned native timer, armed
only while cleanup needs progress. It is independent of canceled domain work
and does not keep polling while idle. Closing one window retains its unfinished
tree without closing other windows; Quit also drains detached roots.

Composed capture (`MacOSComposedCapture`) inserts temporary native image views
for the GPU layers only during the synchronous snapshot. Successful and failed
captures remove them before returning, so a capture never leaves a frozen
image obscuring later GPU frames. Native regression tests check the child
hierarchy as well as rendered pixels. Capture over an opaque native background
so dark-mode controls can composite their title and bezel correctly.

The provider's `IMacOSView` interface lives with `MacOSView`. A checked
`(IMacOSView?)view` query projects the existing native owner for composition;
an incompatible implementation returns null. This is a provider integration
boundary, not a product API. The factory's `GUIProvider` and `ApplicationSlot`
modules are private, including named references through transitive imports.

Export policy: consumers import `Library.GUI` and the portable `I*` contracts,
never a platform module. Two provider modules stay exported on purpose as the
AppKit seam for `Library.Tray`: `MacOS.AppKitText` and `MacOS.MacOSRunLoop`.
Every other `MacOS.*` module is private to the package; the `Linux.*` exports
remain until the Linux fixtures move to the factory. The provider's own
conformance fixtures, which assert AppKit state through its modules, compile
against a test data root whose copy of this manifest re-exports them
(`src/tests/gui_provider_root.py`); products cannot. Inside the provider,
`MacOSButton(title, actions)` reports clicks through a
`MacOSActionQueue(capacity = 256)` (1 to 65536) that wraps the portable
`ActionMailbox` ring on the main thread and wakes the run loop: ordered, never
coalesced, overflow latched and reported by `take()` after native dispatch,
matched by `button.matches(action)`; close buttons before their queue. `MacOSScrollView` keeps AppKit's unflipped coordinates for native
document children while its public offsets count down from the top.

## Linux provider

`Linux/GUIProvider` is selected for `linux` targets. There is no single native
toolkit to inherit, so the provider draws every control itself: each `IWindow`
is one SDL3 window whose whole content is a WebGPU surface, the view tree is
composed over one `LinuxViewNode` per control, and `LinuxPainter` records
rounded rectangles, rings, glyph runs, images and clips into one vertex
stream that replays inside the window's render pass. Text comes from the
fontconfig `sans-serif` match rendered through FreeType at the window's
backing scale, so measurement and drawing agree at fractional scales.

- `LinuxApplication.run()` pumps SDL events, delivers posted and delayed
  work, dispatches queued button actions in click order, and renders every
  window whose own invalidation revision moved. Blinking carets and spinners ask
  the host for a wake instead of redrawing continuously.
- Pointer input is routed by hit-testing the tree: subscriptions along the
  path see the event first, leaf to root, then the controls' own behavior. A
  consumed press captures its drag and release. Keyboard input goes to
  window `onKey` handlers, then the focused control; SDL text input reaches
  the focused text field, which owns caret, selection and clipboard editing.
- `IGPUView` renders into a `GPUOffscreenTarget` on the window's device and
  is composited by the window frame; `poll()` asks the window to advance its
  device request, so a child polled before the first loop turn still becomes
  ready. `GUI.capture` paints the whole window into an offscreen target and
  reads it back, so a window captures before it is shown and presentation is
  never reconfigured. It fails at once if the window's device is not ready
  yet rather than waiting on the UI thread, and it checks that every layer
  names a GPU view inside the capture root; the layer pixels are unused
  because the frame already composes every GPU child.
- Every provider and application entry point except `createImageHandle`
  requires SDL's main thread, the one that called `GUI.initialize`.
- `ISelect` opens a window overlay that receives pointer and keyboard input
  first; `IWindow.showAlert` is SDL's message box; `GUI.chooseDirectory` is
  the desktop folder dialog (portal or zenity) pumped like a modal.
- The manifest binds SDL and fontconfig functions directly. `SDL.h` keeps
  only what the typed importer cannot express: flattening the `SDL_Event`
  union, the folder dialog's cross-thread transaction, and `btrcSdlPush*`
  synthetic input so automation and the native tests drive windows through
  SDL's own queue.
- SDL is initialized once, by the first `GUI.initialize`, and stays
  initialized for the process: a later `GUI.initialize` reuses it, the main
  thread SDL reports stays fixed, and an abandoned folder dialog's callback
  may still run after close. Process exit reclaims it; `SDL_Quit` is not
  bound.

`src/tests/native/gui/linux/LinuxGUIControls.btrc` is the live regression:
clicks, typing, clipboard paste, a select choice, a slider drag, wheel
scrolling, subscription capture, worker-made image handles, contract errors
and readback pixel checks on a real window. `LinuxGUIShutdown.btrc` proves a
subtree that never finishes closing fails `run()` after the drain deadline.
Linux CI runs every shard under `tools/virtual-display.sh`, which starts Xvfb
with Mesa's lavapipe Vulkan driver, so both run there as they do locally.

## Raster surfaces

The rest of this file covers the offscreen raster surface. `Surface` owns its
pixel buffer, resizing, fills, bitmap text, blending and readback in BTRC.
Optional FreeType loading uses checked SDK owners and copied glyph snapshots.
Native windows and product controls use `Library.GUI`; painted widget
trees use `Library.UI`. The legacy immediate-mode widgets (`RasterGUI`,
`GUIApp`, `Theme`, `GUIInput`, `Color`) and the declarative `View` tree were
removed: they duplicated `Library.UI` and `Library.Image` inside the
OS-native group.

Raster is opt-in: import it with `import Library.GUI.Raster;`; no native
raster archive or header is needed. `Surface.opened()` reports invalid
dimensions or backing-allocation failure. Failed resize preserves the old
image; successful resize preserves overlapping pixels and clears newly exposed
pixels. `pixels()` is a synchronous borrow, invalidated by resize or owner
destruction; there is no opaque `Surface.handle` or native surface destructor.

## Layout

| File | Role |
|------|------|
| `GUI.btrc` | The `GUI` facade: application slot, view factories, scheduling, directory picker, text rasterization and capture. |
| `ApplicationSlot.btrc` | Package-private single application owner the facade publishes and clears. |
| `IApplication.btrc` | `IApplication` lifecycle and view-factory contract, `IApplicationWork`. |
| `IWindow.btrc`, `IView.btrc` | Window and view contracts, pointer/scroll/key handler interfaces. |
| `IContainer.btrc`, `IStack.btrc`, `IGrid.btrc`, `IPanel.btrc`, `IScrollView.btrc` | Container contracts: plain grouping, rows/columns, grids, filled panels, vertical scrolling. |
| `IButton.btrc`, `ITextField.btrc`, `ILabel.btrc`, `ISelect.btrc`, `ISlider.btrc` | Control contracts, with the portable `ButtonTypography` and `SelectTypography` limits. |
| `IImageView.btrc`, `IImageHandle.btrc` | Image presentation and worker-safe native image handles. |
| `IProgressIndicator.btrc`, `ILevelIndicator.btrc` | Indicator contracts. |
| `IGPUView.btrc` | WebGPU child view contract. |
| `IDirectoryPicker.btrc` | Directory-picker request/outcome values and contract. |
| `GUICaptureLayer.btrc` | `GUICaptureLayer`: completed GPU readback pixels for `GUI.capture`. |
| `TextRun.btrc` | `TextRun` and `TextRasterization`: one shaped line rasterized by the provider's system text. |
| `ActionMailbox.btrc` | Bounded, ordered click storage both providers deliver button actions from. |
| `GUIInt.btrc` | Saturating integer geometry for raster measurement. |
| `Raster.btrc` | BTRC-owned `Surface` storage, resize, clear/fill/blend, bitmap and scalable text, readback/PPM. Colors are `Library.Image` `RGBA` values. |
| `Font.btrc` / `IFontFace.btrc` | Managed per-surface selection, the `IFontFace` contract and owned glyph/metric snapshots; scalable rasterization lives in `Raster.btrc`. |
| `FreeType.btrc` / `FreeType/FreeTypeFace.btrc` | Optional `FreeType.load` factory and the private FreeType face (unique SDK owners, admitted glyph snapshots). |
| `MacOS/` | AppKit provider: `GUIProvider`, `MacOS*` views and application, run-loop signal, composed capture, SDK headers. |
| `Linux/` | SDL3/WebGPU provider: `GUIProvider`, `Linux*` views and application, painter, fonts, SDL and surface bindings. |

## Quick start

Render to an offscreen buffer, inspect pixels or save a PPM:

```btrc
import Library.Image;
import Library.GUI.Raster;

var surface = Surface(320, 200);
surface.clear(RGBA(250, 248, 245));
surface.text(16, 16, "rendered offscreen", RGBA(43, 38, 34), 2);
surface.savePpm("out.ppm");
```

## Fonts (UTF-8 + scalable)

Raster text is UTF-8 throughout: `Surface.text` and `Surface.textWidth` decode
codepoints, including replacement characters for malformed input. Bitmap text
uses the bundled 8×8 cells; scalable text uses owned glyph snapshots.

Two backends:

- **Bitmap (default, zero-dependency).** A bundled 8×8 font (5×7 glyphs in an
  8×8 cell) covering digits, A–Z and common punctuation; lowercase maps to
  uppercase and non-ASCII codepoints render as a box.
- **Scalable (explicit, owned).** `Font(face)` accepts an `IFontFace` whose
  metrics and glyphs are immutable owned snapshots. Select the font separately
  on each surface; its measurement follows that selection:

  ```btrc
  import Library.GUI.Raster;
  import Library.GUI.Font;

  // face is an IFontFace supplied by the font provider.
  var font = new Font(face);
  surface.setFont(font);
  surface.text(10, 10, "Música", RGBA(255, 255, 255), 1);
  surface.setFont(null); // explicitly restore this surface's bitmap font
  ```

  The surface retains its selection after the caller's local font goes out of
  scope. Draw and measurement retain their own local snapshot. Selection and
  pixel mutation belong to the surface's synchronous owner; this is not a
  concurrent drawing API. Missing glyphs are skipped, never silently replaced
  by another font. `Font.use()` and global `Font.useBitmap()` are removed:
  selection is explicit, independent between surfaces, and unaffected by
  loading or destroying another font. Native GUI controls use system fonts and
  are not affected by raster font selection.

Optional loading is separate from the SDK-free raster domain:

```btrc
import Library.GUI.FreeType;

surface.setFont(FreeType.load("/path/to/font.ttf", 18));
```

`FreeType.load(path, pixelSize)` throws on a missing path, an unloadable face
or a nonpositive size instead of silently selecting the bitmap fallback. Face
metrics are copied at load. Each glyph call admits one `FT_Load_Char` at a
time per face (an overlapping call throws) and copies the glyph, including its
signed-pitch bitmap, into owned storage before the next load can reuse
FreeType's glyph slot; each bitmap has an explicit 64 MiB allocation limit.
The face owns the FreeType library and face handles privately and releases the
face before the library. `FreeType/FreeTypeFace.btrc` records the full
ownership and snapshot contract. Allocation fault injection and overlapping
native-thread admission are not qualified. `FontSnapshotConformance.btrc`
and `GUIFontConformance.btrc` in `src/tests/native/gui/` cover the snapshot
domain and the real loader.

## Dynamic resizing

`Surface.resize(w, h)` changes the owned pixel buffer dimensions; callers
redraw at the new size.

## Build

```
make -C examples/gui   # build + run the FontSmoke example
```

## Caveats

- Surfaces draw into CPU-owned offscreen pixels. Native window/control
  presentation belongs to the portable GUI factory and its selected provider.
- Drawing is rectangles, blending and text; it is intentionally minimal.
