# BTRC GUI

`import Library.GUI;` selects the native provider for the compilation target
through the `[[package.providers]]` entries in `btrc.toml`: `MacOS.GUIProvider`
(AppKit) for `macos`, and `Shim.GUIProvider` for `linux` (GTK4), `windows`
(Win32 and Common Controls 6, with WebView2 for the web view), `android`
(the system's views through JNI) and `ios` (UIKit, for iOS and iPadOS). The
shim provider is one portable implementation over a C contract that each of
its platforms implements once (see "The shim provider" below). Call
`GUI.initialize()`, create a window and controls
with `GUI.createWindow`, `GUI.createColumn`, `GUI.createRow`,
`GUI.createButton`, `GUI.createTextField` and the other `GUI.create*`
factories, attach them, then enter `GUI.run()`.

The facade returns portable `I*` interfaces. `IApplication` declares every
view factory, so providers agree on one contract. `GUI` owns capacity
validation, the single application slot (`ApplicationSlot`) and run/close; a
provider's private `GUIProvider` supplies only the application and the native
services (image handles, the directory picker, text rasterization and
capture). The providers drain a closing subtree in `run()` for at most 10 s,
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
(`MacOS/MacOSRunLoop.btrc`). A CoreFoundation source in the main run loop's
common modes coalesces wakeups for window cleanup and action delivery; it never
coalesces clicks. The source forwards to the existing scoped notification
adapter using a unique native name. Workers signal through an admission gate;
source teardown waits for admitted signal calls to return without blocking. Each delivery
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
Every other `MacOS.*` module and every `Linux.*` module is private to the
package; the Linux Tray talks to the StatusNotifierItem bus itself and needs no
GUI seam. The providers' own conformance fixtures, which assert native state
through their modules (AppKit readback on macOS; the provider's own event queue and a
stalled `ShimNodeView` on Linux), compile against a test data root whose copy
of this manifest re-exports them (`src/tests/gui_provider_root.py`); products
cannot. Inside the provider,
`MacOSButton(title, actions)` reports clicks through a
`MacOSActionQueue(capacity = 256)` (1 to 65536) that wraps the portable
`ActionMailbox` ring on the main thread and wakes the run loop: ordered, never
coalesced, overflow latched and reported by `take()` after native dispatch,
matched by `button.matches(action)`; close buttons before their queue. `MacOSScrollView` keeps AppKit's unflipped coordinates for native
document children while its public offsets count down from the top.

## The shim provider, and GTK4 on Linux

`Shim/GUIProvider` is selected for `linux` targets. Everything in `Shim/` is
portable BTRC: the application, the view tree and its layout, the windows'
frames and captures. It reaches the platform's toolkit through one C
contract (`Shim/Shim.h`, `ShimControls.h`, `ShimSurface.h`, `ShimWeb.h`),
which each platform implements once: GTK4 on Linux (`Linux/Gtk*.c`), Win32
on Windows (`Windows/Win32*.c`), Android's views through JNI
(`Android/Android*.c`), UIKit on iOS and iPadOS (`IOS/UIKit*.m`). On Linux its windows and controls are
GTK4's: a button is a `GtkButton`, a text field a `GtkEntry`, a select a
`GtkDropDown`, a slider a `GtkScale`, and they look, focus, type and speak to
assistive technology as GTK makes them. One provider runs on X11, Wayland and
the Deck's Gamescope session.

- The shim owns every GTK object (`GtkShim.c` windows and events,
  `GtkCanvas.c` the window's content, `GtkControls.c` the controls,
  `GtkSurface.c` the WebGPU surface, `GtkWeb.c` the web view). No GTK callback enters BTRC: a signal becomes an
  event in a bounded queue the shim owns, and `ShimApplication.run()` polls
  it, iterating GLib's main context between events. A control's event names
  the view that owns it, and the window routes it there.
- Layout stays portable. The window's content is one canvas that measures
  nothing and puts each control exactly where the view tree says; every
  control sits in a slot that clips it, so a scroll view clips its children
  like any other. A frame walks the tree and hands GTK the controls back to
  front. This happens at `show()` too, before the GPU device is ready, so
  what a person sees they can click.
- `IGPUView` content is drawn by the window's WebGPU device. On Wayland it
  goes to a subsurface below the window, and the canvas leaves a hole where
  each GPU view is. On X11 each frame is read back and handed to GTK as a
  picture drawn at the view's place in the order. Either way a control placed
  over a GPU view is over it, and one placed under is under.
- `GUI.capture` is the GPU frame read back with GTK's own rendering of the
  controls laid over it, so a capture is what the window shows, and the
  part of it that is the view asked for. A view another one overlaps has
  the other's pixels where they overlap, which macOS leaves out. It fails
  at once if the window's device is not ready rather than waiting on the UI
  thread; a program that captures straight after `show()` asks again until
  it is, and needs no turn of the loop for the controls to be in it.
- The optional [embedded-web package](../../../packages/embedded-web/README.md)
  supplies the WebKitGTK control. Call `EmbeddedWeb.install()` before the
  first `WebView.create()` or use `EmbeddedWeb.create()`. Existing clients keep
  the same `IWebView` bundle, message, and navigation APIs.
- Every provider and application entry point except `createImageHandle`
  requires the thread that called `GUI.initialize`.
- `IWindow.showAlert` is a GTK alert; `GUI.chooseDirectory` is GTK's folder
  dialog (the desktop portal's, where there is one), pumped like a modal.
- GTK is initialized once, by the first `GUI.initialize`, and stays
  initialized for the process.

On Windows the same provider runs over `Windows/Win32*.c`:

- A window is a top-level `HWND`; its drawn content is presented on a child
  window that fills the client area and lies below every control. A control
  is a child window above it (`Button`, `Edit`, `Static`, `ComboBox`,
  `msctls_trackbar32`, `msctls_progress32`, `ScrollBar`), so each is what
  UI Automation and the system's themes expect. Until a control is placed
  in a window it lives in a hidden window of the shim's own.
- A control's frame is its window's. The rectangle its ancestors clip it to,
  and the GPU views placed after it, are cut out of its window region, which
  is how a scroll view clips and how drawn content shows over a control
  placed before it.
- Common Controls 6 comes from an activation context (the manifest
  `shell32.dll` carries), so a program needs no manifest of its own.
- The web view is WebView2, the system's engine, reached through
  `WebView2Loader.dll`, which a program ships beside itself as it does
  `wgpu_native.dll`. Without the loader or the engine, `WebView.create()`
  throws and says which is missing.
- A slider, a select and a scroll bar show what the program gives them and
  never change it themselves: the shim reads the mouse and keys and reports
  what a person asked for.
- A fill or picture that is not opaque is drawn over the window's own
  colour: a child window has nothing behind it to blend with.

On Android the same provider runs over `Android/Android*.c`, which reaches
the system's own views through JNI (`Android/Java`, package `dev.btrc.shim`):

- The program is the shared library of an app whose one activity is
  `ShimActivity`. Its `main` runs on a thread of its own; every call of the
  contract does its work on the activity's UI thread and returns when it is
  done, and what a person does comes back as events the program polls. No
  callback enters BTRC.
- A window is one layer of the activity's frame, and the session gives it
  the whole of it: the last window shown is the one on the screen, and a
  window keeps the size it asked for only until it is first shown. A window
  is a whole number of points each way, since a point is rarely a whole
  number of pixels.
- A control is an `android.widget` view (`Button`, `TextView`, `EditText`,
  `SeekBar`, `ProgressBar`, `ImageView`; a select is a button that opens a
  list) in a slot that clips it to its ancestors and cuts out the GPU views
  placed after it. Drawn content is presented on a `SurfaceView` beneath
  the controls.
- A window's surface is made in one graphics API, Vulkan where the device
  has it and OpenGL ES where it does not: a native window is connected to
  the first API that makes a surface on it.
- The web view is `android.webkit.WebView`. Its engine fetches only over
  http and https, so the bundle's page lives at a host that resolves to
  nothing and whose every request the provider answers; the program is told
  of `app://bundle/` all the same.
- Escape in a text field is the field's, before the soft keyboard can take
  it to hide itself. Back is the window's close request.
- Dark or light is the theme controls are made in: one made before the
  appearance changed keeps the one it has. There is no folder to choose by
  path, so the directory picker reports that it is unavailable.
- An app has no pkg-config search path, so its build gives the compiler and
  the linker wgpu-native's directories and packs `libwgpu_native.so` and the
  shim's Java into the app (`tools/target_hosts/android/gui.py` does this
  for tests, with the SDK's own tools).

On iOS and iPadOS the same provider runs over `IOS/UIKit*.m`:

- UIKit owns the process. An app links with `-e _btrcUIKitMain`, which
  enters `UIApplicationMain` and never returns; the program's `main` runs on
  a thread of its own. Every call of the contract does its work on the main
  thread and returns when it is done, and what a person does comes back as
  events the program polls. No callback enters BTRC, and `GUI.run` is the
  program's own loop as it is everywhere else.
- A window is a `UIWindow` of the app's scene, and the scene gives it the
  whole of itself: the last window shown is the one on the screen, and a
  window keeps the size it asked for only until it is first shown. Its
  content is the safe area, a whole number of points each way, so nothing a
  program places lies under the status bar, the sensor housing or the home
  indicator. A rotation, a split view and a resized scene are the window's
  new size (`WINDOW_RESIZED`); the contract has no size class of its own.
- A control is UIKit's (`UIButton`, `UILabel`, `UITextField`, `UISlider`,
  `UIActivityIndicatorView`, `UIProgressView`, `UIImageView`; a select is a
  button that opens a list) in a slot that clips it to its ancestors and
  cuts out the GPU views placed after it. Drawn content is presented on the
  content view's own `CAMetalLayer`, beneath the controls, through
  wgpu-native's Metal backend.
- A text field keeps what is typed as typed: it does not capitalize,
  correct or substitute. A slider shows the value the program gives it and
  reports where a finger asks it to go.
- Keys are a hardware keyboard's, read before any view acts on them.
  Command-W is the window's close request; Escape in a text field is the
  field's. A pointer's hover and a wheel or trackpad's scrolling reach a
  view where the device has a pointer; a finger is a press, a drag and a
  release.
- The web view is `WKWebView`, with a scheme handler that serves the bundle
  at `app://bundle/` and a store that keeps nothing. A link a person taps
  to somewhere else is handed to the system, which opens it in Safari.
- Dark or light is one setting for the application, applied live. The
  system's folder picker lends a folder for as long as a program holds its
  security scope, not a directory to open by path, so the directory picker
  reports that it is unavailable.
- Where the system gives an app more than one scene (iPadOS), the program's
  windows live in one of them: the first to connect, or a second one the
  provider asks for when `BTRC_SHIM_SCENE=second` is in the environment.
  When the system takes that scene away, its windows are asked to close and
  move to another scene if one is connected.
- An app has no pkg-config search path, so its build gives the compiler and
  the linker wgpu-native's directories and links its static library
  (`tools/target_hosts/ios/gui.py` does this for tests, with Xcode's own
  tools, and packs the bundle a scene-based app needs). `BTRC_SHIM_OUTPUT`
  names a directory that receives what the program prints and its result.

The shared conformance suite (`src/tests/native/gui/conformance`) is the
regression: each case runs through both compilers on X11 and on Wayland with
real input (XTEST; a wlroots compositor's virtual pointer and keyboard) in a
private session from `tools/ui/headless-session.sh`. `LinuxGUIShutdown.btrc`
proves a subtree that never finishes closing fails `run()` after the drain
deadline, `LinuxEventBoundary.btrc` that a burst of input is delivered
losslessly in bounded turns, and `ShimPlacement.btrc` that controls are
placed at `show()`. Linux CI runs every shard in such a session with Mesa's
lavapipe Vulkan driver, so they run there as they do locally.

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
| `Shim/` | The provider for platforms whose toolkit is reached through a C contract: `GUIProvider`, `WebViewProvider`, `Shim*` views and application, and the contract's headers. |
| `Linux/` | The contract in GTK4: `GtkShim`, `GtkCanvas`, `GtkControls`, `GtkSurface`, `GtkWeb`. |
| `Android/` | The contract over Android's views through JNI: `AndroidShim` (windows, events, controls, text), `AndroidSurface`, `AndroidWeb`, and `Java`, package `dev.btrc.shim` (`ShimActivity`, `Shim`, `ShimWeb`, `Slot`), the Java an app compiles in. |
| `IOS/` | The contract in UIKit, for iOS and iPadOS: `UIKitShim` (the app's entry, scenes, windows, events, text), `UIKitControls` (UIKit's controls in clipping slots), `UIKitSurface` (the content's `CAMetalLayer`), `UIKitWeb` (`WKWebView`). |
| `Windows/` | The contract in Win32: `Win32Shim` (windows, events, text), `Win32Controls` (Common Controls 6 as child windows, placed and clipped by window regions), `Win32Surface`, `Win32Web` (WebView2). |

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

`.pcf` and gzip-compressed `.pcf.gz` files at their stored pixel size use BTRC's PCF reader. It preserves the fixed strike's native bearings, widths, bitmap row padding, bit order and default glyph. Bitmap-only TrueType files with a horizontal CBDT/CBLC color strike also use a first-party reader at the strike size. It decodes the embedded PNG into the existing grayscale coverage API. Mixed strike formats and unsupported sizes continue through the native FreeType provider.

Standalone, non-variable `.ttf`, `.woff` and `.woff2` files containing TrueType outlines and grid-fitting bytecode use BTRC's outline reader, hint interpreter and grayscale rasterizer. The web-font containers use the first-party zlib and Brotli decoders. The current reader accepts a single Unicode character map and axis-aligned hint programs. Fonts declaring general-vector instructions in their font or size programs use FreeType from the start. An unsupported glyph instruction switches the face to FreeType using its original font bytes, even after the source path changes. Fonts that require automatic hinting continue through FreeType at open.

`FreeType.load(path, pixelSize)` throws on a missing path, an unloadable face
or a nonpositive size instead of silently selecting the bitmap fallback. Face
metrics are copied at load. The native provider admits one `FT_Load_Char` at a
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
make -C examples/gui        # build the portable Native.btrc example
make -C examples/gui run    # build it and open its window
```

## Caveats

- Surfaces draw into CPU-owned offscreen pixels. Native window/control
  presentation belongs to the portable GUI factory and its selected provider.
- Drawing is rectangles, blending and text; it is intentionally minimal.
