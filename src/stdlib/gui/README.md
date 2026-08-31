# btrc GUI

A simple, dependency-light way to build native UIs in btrc. The design follows
btrc's spirit: a thin portable C shim does the pixel work, all widget/layout
logic lives in btrc, and it's threaded by default.

## Layout

| File | Role |
|------|------|
| `btrc_gui.h` / `btrc_gui.c` | Portable software framebuffer (`Surface`): clear, fill/blend rect, UTF-8 bitmap-font text, in-place resize, pixel readback, PPM dump, pluggable font backend. **No display required** — runs and is testable headlessly. |
| `geometry.btrc` | Saturating integer geometry shared by immediate and declarative layout. |
| `gui.btrc` | btrc bindings + immediate-mode widgets (`Color`, `Surface`, `GuiInput`, `Theme`, `Gui`, `GuiApp`). |
| `view.btrc` | Declarative UI: a `View` tree with flexbox-style layout, events-as-data (`GuiEvents`), and a one-call `Ui.frame(...)`. |
| `btrc_gui_window.h` / `.c` | Legacy standalone native window backend (resizable GLFW/OpenGL window, GPU-texture present). It is retained for GUI compatibility tests and is not composable with `std.app`. |
| `window.btrc` | Legacy btrc bindings for that standalone backend (`GuiWindow`, incl. `width`/`height`/`fit`). |
| `btrc_gui_font.h` / `.c`, `font.btrc` | Optional FreeType backend (`Font`) for scalable, anti-aliased, full-Unicode text. |

Not auto-included (it's in a subfolder and needs a compiled shim). Opt in with
`#include "gui/gui.btrc"` and build with `make gui`.

## Quick start (immediate-mode)

`GuiWindow` below is the legacy standalone presenter. New application code
should own its window through `std.app`; `std.ui` has not yet been migrated to
consume the unified `std.app`/`std.gpu` surface.

```btrc
#include "gui/gui.btrc"
#include "gui/window.btrc"

int main() {
    var win = GuiWindow("Hello", 480, 320);
    var ui = Gui(Surface(480, 320));
    while (win.isOpen()) {
        win.poll(ui.input);
        ui.beginFrame();
        ui.heading("btrc GUI");
        if (ui.button("Click me")) { print("clicked"); }
        win.present(ui.surface);
    }
    win.close();
    return 0;
}
```

Headless (no window — render to a buffer, inspect pixels or save a PPM):

```btrc
var ui = Gui(Surface(320, 200));
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

For richer layouts, `view.btrc` adds a declarative layer: describe the UI as a
tree of `View`s and frame it in one call. Layout is flexbox-style (rows/columns
with `padding`, `gap`, and `grow`); interactions come back as data keyed by a
stable `id` (Elm-style — no closures).

```btrc
#include "gui/gui.btrc"
#include "gui/view.btrc"

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

GuiEvents e = Ui.frame(surface, input, theme, ui());  // measure → layout → render
if (e.wasClicked("save")) { /* ... */ }
```

`Ui.frame` measures the tree, lays it out to the surface bounds, renders it, and
returns a `GuiEvents` you query by id (`wasClicked`, `wasToggled`). Builders:
`column`, `row`, `box`, `text`, `button`, `checkbox`, `spacer`; fluent setters:
`pad`, `withGap`, `grows`, `bgColor`, `fgColor`, `scaleText`, `sized`, `child`,
`kids`.

## Threaded by default

`GuiApp` bundles a `Surface`, a `Gui`, and a thread-safe `alive` flag. The
loop runs on a background thread via `spawn`; coordinate with `Mutex`:

```btrc
var app = GuiApp(640, 400);
Thread<int> t = spawn(() => {
    while (app.running()) {
        app.ui.beginFrame();
        if (app.ui.button("Quit")) { app.stop(); }
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
- **FreeType (optional, scalable).** `font.btrc` adds a `Font` that loads a
  TTF/OTF and renders anti-aliased, full-Unicode glyphs at any pixel size.
  Loading a font installs it as the active backend, so **all** text — both
  immediate-mode and declarative — switches over with no other code changes:

  ```btrc
  #include "gui/gui.btrc"
  #include "gui/font.btrc"

  Font f = Font("/path/DejaVuSans.ttf", 18);
  if (f.ok()) { f.use(); }     // every subsequent draw uses it
  // Font.useBitmap();         // restore the built-in font
  ```

  The core renderer stays dependency-free: the FreeType module plugs in through
  a function-pointer hook (`btrc_gui_install_font_backend`), and `make gui`
  builds it only when FreeType headers are present.

## Dynamic resizing

The window is resizable. `Surface.resize(w, h)` reallocates the pixel buffer in
place, and `GuiWindow` exposes the live framebuffer size (`width()`, `height()`)
plus `fit(surface)` to match a surface to the window each frame — the
declarative layout then reflows to the new bounds automatically:

```btrc
while (win.isOpen()) {
    win.poll(input);
    win.fit(surface);                          // track window size
    GuiEvents e = Ui.frame(surface, input, theme, ui());
    win.present(surface);
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
  (the software renderer and `GuiApp` thread test run anywhere, headless).
- GLFW requires window creation + event polling on the **main thread on macOS**,
  so drive the windowed loop from `main()` there; the threaded runner is for the
  offscreen surface or Linux.
- The legacy `GuiWindow` backend owns GLFW and an OpenGL window independently.
  Its header and `std.app` now reject a mixed translation unit at compile time;
  `std.app` is the sole GLFW owner for the unified application/GPU path. The
  headless software `Surface` remains safe and deliberately separate until
  `std.ui` consumes that path.
- Drawing is opaque-rect + bitmap text; it's intentionally minimal, not a
  full retained-mode toolkit.
