# BTRC GUI

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
a substitute for the still-unfinished package exports and application lifecycle.

`MacOSContainer` implements `IContainer` with real native children. `attach`
transfers subtree lifecycle responsibility; `detach` returns the same open child.
Closing an attached child is rejected before actions/editing are changed.
Parent close and ordinary scope cleanup close descendants despite surviving
aliases; detached children remain independent. Multiple parents, ancestor cycles
and reentrant mutations are rejected. A failed close remains unavailable and
reports its original error without retrying the child. Native attachment errors
roll back; an unsuccessful rollback leaves the container failed and retaining
the potentially attached child. Children do not strongly retain their parent.
This grouping primitive does not yet implement recursive row/grid measurement,
application shutdown or GPU composition.

`IWindow.attachRoot(view)` transfers a detached root to the window; replace it
explicitly with `detachRoot()` first. `root()` returns an alias, not another
lifecycle owner. The root fills the content area and AppKit resizes it with the
window. Detach restores the root's previous native autoresizing policy and
returns it open. Explicit window close and ordinary owner scope cleanup close
the root subtree, including controls held by aliases. Failed attachment rolls
back frame and resize policy; indeterminate detach/shutdown failure remains
unavailable without retrying native cleanup. Provider queries and attachment
reject reentrant tree mutation. Dimensions exclude native window chrome.

This proves programmatic window ownership, not native close-button or application-
quit routing: those still need checked native delegates and application shutdown.

Creation still uses the explicit macOS constructors. The target-selected `GUI`
factory, application ownership and checked action subscriptions remain
unfinished; these interfaces alone do not complete the portable GUI gate.

`Library.GUI.MacOS.MacOSTextField` owns a real AppKit
text field. `MacOSWindow` owns an AppKit window, title, content size and explicit
close; `AppKitText` copies strings at the SDK boundary. Raw native children outside
the managed root still require explicit child-before-window close. `MacOSApplication` owns
main-thread startup and bounded nonblocking event dispatch for a shared UI/GPU
loop; application shutdown/delegates and actual GPU embedding remain unfinished.
`MacOSScrollView` owns a native vertical viewport and document,
with overlay scrollers, top-relative logical-point offsets and resize clamping.
Native document children retain AppKit's unflipped coordinates; this is not yet
the portable recursive layout or recycled collection API. Native/GPU composition
is unfinished. Future Linux/Windows providers use sibling platform packages;
they are outside the current implementation scope.

`MacOSButton(title, actions)` creates an AppKit momentary button. After native
dispatch, consume `MacOSActionQueue.take()` and identify the sender with
`button.matches(sender)`. Close buttons before the queue; closing a button
cancels its pending activations. Keep application commands outside AppKit's
dispatch stack. This does not implement value-changing controls or delegates.
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
| `btrc_gui.h` / `btrc_gui.c` | Remaining blend/text/font-dispatch backend, borrowing a typed `BtrcGuiPixels` view selected through the package's native bindings. No pixel ownership or lifecycle API. |
| `Geometry.btrc` | Saturating integer geometry shared by immediate and declarative layout. |
| `GUI.btrc` | BTRC-owned `Surface` storage, resize, clear/fill, readback/PPM and immediate-mode widgets (`Color`, `GUIInput`, `Theme`, `GUI`, `GUIApp`). |
| `View.btrc` | Declarative UI: a `View` tree with flexbox-style layout, events-as-data (`GUIEvents`), and a one-call `UI.frame(...)`. |
| `btrc_gui_window.h` / `.c` | Legacy standalone native window backend (resizable GLFW/OpenGL window, GPU-texture present). It is retained for GUI compatibility tests and is not composable with `Library.App`. |
| `Window.btrc` | Legacy btrc bindings for that standalone backend (`GUIWindow`, incl. `width`/`height`/`fit`). |
| `btrc_gui_font.h` / `.c`, `Font.btrc` | Optional FreeType backend (`Font`) for scalable, anti-aliased, full-Unicode text. |

Not auto-included. Opt in with `import Library.GUI;` and build the remaining
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
#include "GUI/GUI.btrc"
#include "GUI/Window.btrc"

int main() {
    var win = GUIWindow("Hello", 480, 320);
    var ui = GUI(Surface(480, 320));
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
var ui = GUI(Surface(320, 200));
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
#include "GUI/GUI.btrc"
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
  #include "GUI/GUI.btrc"
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
