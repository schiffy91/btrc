# BTRC GUI

`import Library.GUI;` selects the native provider for the compilation target.
Call `GUI.initialize()`, create a window and controls with `GUI.createWindow`,
`GUI.createColumn`, `GUI.createRow`, `GUI.createButton` and `GUI.createTextField`, attach them,
then enter `GUI.run()`. Only macOS is implemented; other targets fail explicitly.
The factory returns portable interfaces and its application owner is package-private.
`GUI.post(work)` schedules UI-thread work; `GUI.requestQuit()` stops admission.
`GUI.postAfter(delaySeconds, work)` schedules one cancellable delayed delivery
and returns an `ICallbackRegistration`. It shares the immediate-work capacity;
overflow rejects new work. Canceling its alias or closing the application
releases a waiting receiver without waiting for its deadline. Delivery is never
inline, errors propagate from `run()` after teardown, and native views remain
alive through the admitted call. Delay must be finite and nonnegative.
On macOS this uses a checked `NSTimer` stored-block binding in the default
run-loop mode. It may run late during tracking/modal work and is not a real-time
or display-synchronization API. Native GPU completion required for shutdown
must not use a domain callback that Quit intentionally abandons.
`run()` closes owned windows and detached views before returning or propagating
a work error. `GUI.close()` covers setup without loop entry and returns a
`CallbackCancellation`; `Pending` keeps the application owner. Enter `GUI.run()`
to drain that shutdown on the native executor. Closed aliases remain closed
after reinitialization.
`button.onAction(receiver, scope)` registers an `IButtonAction.invoke()` receiver
in a normal `CallbackScope` and returns an `ICallbackRegistration`. Keep that
scope with the independent component/application owner. Cancel before replacing
the receiver; scope cancellation and button close discard queued old clicks.
Model setters never synthesize actions. Native delivery is queued automatically
on the UI executor; callers do not poll an action queue. GPU composition and the
remaining core qualification are unfinished. Legacy provider modules stay public until their
consumers migrate.

[Native.btrc](../../../examples/gui/Native.btrc) is a portable application example:
edit a native text field, apply the window title through a queued button action,
then quit through the same application lifecycle. Its nested row/column layout
uses native intrinsic sizes, not manually assigned control frames.

`GUI.createRow(spacing)` and `GUI.createColumn(spacing)` return `IStack`.
Attach ordinary controls or nested stacks; AppKit performs recursive layout.
Spacing defaults to eight logical points; `setPadding(top, right, bottom, left)`
sets nonnegative insets. `StackAlignment.Start/Center/End` controls cross-axis
alignment. Native control sizes and reading order are retained. Hidden children
keep their space and parent; detach removes them from layout and restores their
previous Auto Layout policy. `layout()` flushes pending native layout without
rebuilding controls, reading active editors, or replacing their undo state.
`GUI.createContainer()` remains the plain grouping primitive for explicit placement.
Grid/overlay and GPU layout integration are still pending.

The native-control API is being implemented for macOS. Portable controls and
recursive layout belong at this package root; AppKit providers and SDK headers
belong under `MacOS/`. `IWindow`, `IView`, `IContainer`, `IButton` and `ITextField` are portable interfaces
implemented by the existing native window, view, button and text-field owners. They
expose no SDK objects. Interface conversion preserves the same owner: closing
through a detached `IView` invalidates its control aliases. `arrange(x, y, width, height)`
uses logical points from the parent's top-left and requires attachment first;
native parent flipping and bounds origins stay inside the provider. Fitting
sizes are native minima, so a flexible text field may report zero minimum width.
Visibility denotes the control's own flag, not actual on-screen exposure.

The provider's `IMacOSView` interface lives with `MacOSView`. A checked
`(IMacOSView?)view` query projects the existing native owner for composition;
an incompatible implementation returns null. Portable signatures still expose
no SDK objects. This is a provider integration boundary, not a product API or
a substitute for the portable API. Existing provider modules remain exported
for migration; the new factory's `GUIProvider` module is private, including
named references through transitive imports.

`MacOSContainer` implements `IContainer` with real native children. `attach`
transfers subtree lifecycle responsibility; `detach` returns the same open child.
Closing an attached child is rejected before actions/editing are changed.
Parent close and ordinary scope cleanup close descendants despite surviving
aliases; detached children remain independent. Multiple parents, ancestor cycles
and reentrant mutations are rejected. A failed close remains unavailable and
reports its original error without retrying the child. Native attachment errors
roll back; an unsuccessful rollback leaves the container failed and retaining
the potentially attached child. Children do not strongly retain their parent.
This primitive only groups explicitly placed children; use `IStack` for recursive
row/column layout. Grid layout and GPU composition remain pending migrations.

`IView.close()` starts shutdown once and reports completion. `pollClose()` advances
already-started cleanup without retrying failed native operations; it reports
`NotRequested` on a live view. Native controls complete immediately. A container
retains pending children and its native backing, closes siblings independently,
and removes a child only after `Complete`. `isOpen() == false` means admission
has stopped, not that native cleanup finished. Dropping an unfinished subtree
owner is a diagnosed lifecycle error, not permission to free native borrowers.

`IWindow.attachRoot(view)` transfers a detached root to the window; replace it
explicitly with `detachRoot()` first. `root()` returns an alias, not another
lifecycle owner. The root fills the content area and AppKit resizes it with the
window. Detach restores the root's previous native autoresizing policy and
returns it open. Explicit window close and ordinary owner scope cleanup close
the root subtree, including controls held by aliases. Failed attachment rolls
back frame and resize policy; indeterminate detach/shutdown failure remains
unavailable without retrying native cleanup. Provider queries and attachment
reject reentrant tree mutation. Dimensions exclude native window chrome.
`isOpen()` and `isVisible()` remain safe after native or explicit close and
return false; operations needing a live native window still reject access.

The native close button is observed through a checked NSWindow delegate.
For application-created windows it marks the window closed immediately and signals the native run loop; application
dispatch subsequently closes the owned subtree outside the callback, without
waiting for application quit or a manually pumped event. Closed windows are
cleaned up before queued commands, cancelling their stale button actions.
`MacOSApplication.createWindow()` returns
an `IWindow` and retains lifecycle responsibility. Application `close()` cancels
window subscriptions and closes their trees; one failure does not skip siblings
or retry an indeterminate native close. The callback receiver contains only
close state and the wake signal, not a strong reference back to the window owner.

`IApplication` is the portable application lifecycle. `MacOSApplication.run()`
enters the real AppKit loop; `requestQuit()` requests exit without tearing down
controls inside the calling native callback. Native application Quit uses the
same request through a generated delegate. Owned subtrees close before the loop
stops; final application subscriptions drain after loop return. A wake event is
posted because AppKit observes `stop:`
after dispatching an event, not merely after running a timer. A pre-run request
skips loop entry only when no work remains to drain. The owner cannot be restarted
after closing. New windows are rejected as soon as Quit is requested, before
loop exit. Reentrant run/close and a second concurrent application owner are
rejected; failed construction cancels its unpublished subscription.

`IApplication.post(work)` accepts an `IApplicationWork` on the UI thread and
invokes `run()` later through an actual `NSRunLoop` one-shot block. Capacity
includes queued and currently executing work (default 256, configurable on the
provider). Exhaustion rejects the new submission without losing accepted work.
Completed callback states are pruned on submission; work delivery uses no polling timer.
Quit stops admission and skips queued domain work, but keeps native completion
callbacks alive until they return. Closing with pending work is rejected: enter
`run()` to drain it. Work may retain the application until completion. A work
exception requests orderly quit and is rethrown by `run()` after teardown.
Worker-thread publication remains unfinished.

Factory button actions retain their order in a bounded ring. The private
`MacOSRunLoopSignal` uses AppKit's default notification queue and a private sender
identity to coalesce only wakeups for window cleanup and action delivery;
it never coalesces clicks. Each delivery batch is bounded by its starting size;
remaining clicks schedule another run-loop pass. Cancellation invalidates
queued generations. Overflow is a persistent error even if cancelled entries
are subsequently pruned. Handler failure requests quit and is rethrown after
normal application teardown. The application owns the wake subscription outside
its receiver graph; ordinary callback scopes own user subscriptions. Action delivery
uses no polling timer, raw receiver pointer or second reference-counting system.

If native modal work is active, Quit first stops that modal with the SDK abort
response so its caller can return. Views remain alive until callbacks drain;
the directory picker reports abort as cancellation. This uses AppKit's
[modal stop operation](https://developer.apple.com/documentation/appkit/nsapplication/stopmodal%28%29?language=objc),
not a nested polling pump. Asynchronous sheets and arbitrary nested-modal stacks
still need lifecycle integration and qualification.

Bounded embedded dispatch remains for existing hosts and is prohibited while
the native loop is running. New portable applications use the target-selected
factory and native scheduling described above. GPU subtree shutdown, worker
publication and broader dialog handling still prevent full GUI qualification.

Pending window/subtree closure uses one application-owned native timer, armed
only while cleanup needs progress. It is independent of canceled domain work
and does not keep polling while idle. Closing one window retains its unfinished
tree without closing other windows; Quit also drains detached roots. The timer
uses the existing checked stored-block binding and callback scope. This is the
shutdown foundation for GPU hosting, not a completed portable GPU view or a
display-synchronization API.
Programmatic `window.close()` wakes the same application owner as the native
close button, including from ordinary posted work. Consumers need not poll a
closing application-owned window themselves; direct standalone window owners
still carry their own completion responsibility.

Composed capture uses temporary native image views only during the synchronous
snapshot. Successful and failed captures remove them before returning; a capture
must not leave a frozen image obscuring subsequent GPU frames. Native regression
tests check the child hierarchy as well as rendered pixels. This uses view-backed
capture and renderer readback, independent of desktop visibility or screen lock.

`Library.GUI.MacOS.MacOSTextField` owns a real AppKit
text field. `MacOSWindow` owns an AppKit window, title, content size and explicit
close; `AppKitText` copies strings at the SDK boundary. Raw native children outside
the managed root still require explicit child-before-window close. `MacOSApplication` owns
main-thread startup and bounded nonblocking event dispatch for a shared UI/GPU
loop. Its native run/quit/delegate path is implemented above; actual GPU embedding remains unfinished.
`MacOSScrollView` owns a native vertical viewport and document,
with overlay scrollers, top-relative logical-point offsets and resize clamping.
Native document children retain AppKit's unflipped coordinates; this is not yet
the portable recursive layout or recycled collection API. Native/GPU composition
is unfinished. Future Linux/Windows providers use sibling platform packages;
they are outside the current implementation scope.

`MacOSButton(title, actions)` creates an AppKit momentary button. After native
dispatch, consume `MacOSActionQueue.take()` and identify the opaque BTRC action with
`button.matches(action)`. No native sender or selector is exposed. A checked
target/action binding delivers into preallocated ordered storage; queued entries
carry a generation so rebinding cancels old activations without changing order.
Close buttons before the queue. Dropping a queue also cancels its subscriptions:
their independent scopes are not retained by native callback receivers.

`MacOSActionQueue(capacity = 256)` accepts capacities from 1 to 65536. Ordered
clicks are never coalesced. Exhaustion latches an error reported by `take()` after
native dispatch and stops further admission; close the controls and queue rather
than continuing with a silently incomplete command stream. This is not a realtime
queue or a value-changing control's coalescing policy. Keep application commands
outside AppKit's dispatch stack; standalone-loop scheduling still needs integration.
Capture over an opaque native background so dark-mode controls can composite
their title and bezel correctly.

`MacOSLabel` defaults to one line with native tail ellipsis. `setWrapping(true)`
enables word wrapping; `setWrapping(false)` restores the single-line layout.
Neither mode truncates the stored text returned by `text()`.

`MacOSSelect` owns an AppKit popup and menu. Replace its titles and selected
index together with `setItems`; duplicate labels keep distinct indices. Items
may be disabled individually. Read `selectedIndex()` after native dispatch;
this is current selection state, not an ordered history of value changes.
`setFont(size)` uses the system font without replacing the native popup/menu.

`MacOSGrid(columns, rows, columnSpacing, rowSpacing)` is a native recursive
layout container. Set cells to unattached child views; nested grids are ordinary
children. AppKit supplies intrinsic sizing and aligned cell bounds. Explicit
row/column sizes can be returned to content sizing with `fitRow`/`fitColumn`.
Replacing or clearing a cell detaches its previous view, allowing explicit reuse;
attached children and hierarchy cycles are rejected before calling AppKit.
`close()` clears cells but does not close borrowed child owners. This provider
does not yet constitute the portable declarative layout API.

The APIs documented below are the **legacy custom-painted GUI**, not native OS
widgets. Existing `View.btrc` and `Window.btrc` are legacy implementations, not
the proposed native API. `Surface` owns its pixel buffer, resizing, fills and
readback in BTRC. Raster text/blending, FreeType and the legacy window provider
remain migration work. Do not build new product controls on this toolkit.

## Layout

| File | Role |
|------|------|
| `btrc_gui.h` / `btrc_gui.c` | Remaining optional font dispatch, borrowing a typed `BtrcGuiPixels` view and synchronous BTRC blend callback. Bitmap text, metrics and blending belong to `Raster.btrc`; no native pixel ownership API. |
| `Geometry.btrc` | Saturating integer geometry shared by immediate and declarative layout. |
| `Raster.btrc` | BTRC-owned `Surface` storage, resize, clear/fill, readback/PPM and legacy immediate-mode widgets (`Color`, `GUIInput`, `Theme`, `RasterGUI`, `GUIApp`). |
| `View.btrc` | Declarative UI: a `View` tree with flexbox-style layout, events-as-data (`GUIEvents`), and a one-call `UI.frame(...)`. |
| `btrc_gui_window.h` / `.c` | Legacy standalone native window backend (resizable GLFW/OpenGL window, GPU-texture present). It is retained for GUI compatibility tests and is not composable with `Library.App`. |
| `Window.btrc` | Legacy btrc bindings for that standalone backend (`GUIWindow`, incl. `width`/`height`/`fit`). |
| `btrc_gui_font.h` / `.c`, `Font.btrc` | Optional FreeType backend (`Font`) for scalable, anti-aliased, full-Unicode text. |

Not auto-included. Opt in with `import Library.GUI.Raster;` and build the remaining
native backend with `make gui`. `Surface.opened()` reports invalid dimensions
or backing-allocation failure. Failed resize preserves the old image; successful
resize preserves overlapping pixels and clears newly exposed pixels.
`pixels()` is a synchronous borrow, invalidated by resize or owner destruction;
there is no opaque `Surface.handle` or native surface destructor.

## Quick start (immediate-mode)

`GUIWindow` below is the legacy standalone presenter. New application code
should own its window through `Library.App`; `Library.UI` has not yet been migrated to
consume the unified `Library.App`/`Library.GPU` surface.

```btrc
#include "GUI/Raster.btrc"
#include "GUI/Window.btrc"

int main() {
    var win = GUIWindow("Hello", 480, 320);
    var ui = RasterGUI(Surface(480, 320));
    while (win.isOpen()) {
        Windows.poll(ui.input);
        ui.beginFrame();
        ui.heading("btrc GUI");
        if (ui.button("Click me")) { print("clicked"); }
        Windows.present(ui.surface);
    }
    Windows.close();
    return 0;
}
```

Headless (no window — render to a buffer, inspect pixels or save a PPM):

```btrc
var ui = RasterGUI(Surface(320, 200));
ui.beginFrame();
ui.label("rendered offscreen");
ui.surface.savePpm("out.ppm");
```

## Widgets

`label`, `heading`, `button` → `bool` (clicked), `checkbox(text, value)` → `bool`,
`slider(value, max)` → `int`, `panel`, `spacer`. Widgets lay out top-to-bottom;
each returns the interaction for the current frame. Style via `Theme` (light by
default; `Theme.dark()` provided).

## Declarative UI (View tree)

For richer layouts, `View.btrc` adds a declarative layer: describe the UI as a
tree of `View`s and frame it in one call. Layout is flexbox-style (rows/columns
with `padding`, `gap`, and `grow`); interactions come back as data keyed by a
stable `id` (Elm-style — no closures).

```btrc
#include "GUI/Raster.btrc"
#include "GUI/View.btrc"

View ui() {
    return View.column().pad(16).withGap(8).kids([
        View.text("Notes — héllo"),            // UTF-8 throughout
        View.button("Save", "save"),
        View.spacer(),                          // grows to fill
        View.row().withGap(8).kids([
            View.button("Quit", "quit"),
        ]),
    ]);
}

GUIEvents e = UI.frame(surface, input, theme, ui());  // measure → layout → render
if (e.wasClicked("save")) { /* ... */ }
```

`UI.frame` measures the tree, lays it out to the surface bounds, renders it, and
returns a `GUIEvents` you query by id (`wasClicked`, `wasToggled`). Builders:
`column`, `row`, `box`, `text`, `button`, `checkbox`, `spacer`; fluent setters:
`pad`, `withGap`, `grows`, `bgColor`, `fgColor`, `scaleText`, `sized`, `child`,
`kids`.

## Threaded by default

`GUIApp` bundles a `Surface`, a `GUI`, and a thread-safe `alive` flag. The
loop runs on a background thread via `spawn`; coordinate with `Mutex`:

```btrc
var app = GUIApp(640, 400);
Thread<int> t = spawn(() => {
    while (app.running()) {
        App.ui.beginFrame();
        if (app.ui.button("Quit")) { App.stop(); }
        // present via a window, or read pixels in a test
    }
    return 0;
});
t.join();
```

## Fonts (UTF-8 + scalable)

Text is **UTF-8 throughout** — `draw_text` and `text_width` decode codepoints,
so multi-byte characters measure and render as single glyphs.

Two backends:

- **Bitmap (default, zero-dependency).** A bundled 8×8 font (5×7 glyphs in an
  8×8 cell) covering digits, A–Z and common punctuation; lowercase maps to
  uppercase and non-ASCII codepoints render as a box.
- **FreeType (optional, scalable).** `Font.btrc` adds a `Font` that loads a
  TTF/OTF and renders anti-aliased, full-Unicode glyphs at any pixel size.
  Loading a font installs it as the active backend, so **all** text — both
  immediate-mode and declarative — switches over with no other code changes:

  ```btrc
  #include "GUI/Raster.btrc"
  #include "GUI/Font.btrc"

  Font f = Font("/path/DejaVuSans.ttf", 18);
  if (f.ok()) { f.use(); }     // every subsequent draw uses it
  // Font.useBitmap();         // restore the built-in font
  ```

  The core renderer stays dependency-free: the FreeType module plugs in through
  a function-pointer hook (`btrc_gui_install_font_backend`), and `make gui`
  builds it only when FreeType headers are present.

## Dynamic resizing

The window is resizable. `Surface.resize(w, h)` reallocates the pixel buffer in
place, and `GUIWindow` exposes the live framebuffer size (`width()`, `height()`)
plus `fit(surface)` to match a surface to the window each frame — the
declarative layout then reflows to the new bounds automatically:

```btrc
while (win.isOpen()) {
    Windows.poll(input);
    Windows.fit(surface);                          // track window size
    GUIEvents e = UI.frame(surface, input, theme, ui());
    Windows.present(surface);
}
```

## Build

```
make gui            # software renderer (always) + window backend (if GLFW)
                    #   + FreeType font backend (if FreeType present)
make examples-gui   # build + run the headless examples/tests (demo, declarative, font)
```

## Caveats

- Rendering split: widgets are rasterized on the CPU into the `Surface`; the
  window backend then **uploads that surface to a GPU texture and composites it
  with hardware** (textured quad, bilinear-filtered) — so present/scale is
  GPU-accelerated. (Per-primitive GPU rendering could later build on the `gpu`
  module.)
- The window backend needs GLFW + an OpenGL context and a **display** to run
  (the software renderer and `GUIApp` thread test run anywhere, headless).
- GLFW requires window creation + event polling on the **main thread on macOS**,
  so drive the windowed loop from `main()` there; the threaded runner is for the
  offscreen surface or Linux.
- The legacy `GUIWindow` backend owns GLFW and an OpenGL window independently.
  Its header and `Library.App` now reject a mixed translation unit at compile time;
  `Library.App` is the sole GLFW owner for the unified application/GPU path. The
  headless software `Surface` remains safe and deliberately separate until
  `Library.UI` consumes that path.
- Drawing is opaque-rect + bitmap text; it's intentionally minimal, not a
  full retained-mode toolkit.
