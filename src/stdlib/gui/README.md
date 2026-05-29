# btrc GUI

A simple, dependency-light way to build native UIs in btrc. The design follows
btrc's spirit: a thin portable C shim does the pixel work, all widget/layout
logic lives in btrc, and it's threaded by default.

## Layout

| File | Role |
|------|------|
| `btrc_gui.h` / `btrc_gui.c` | Portable software framebuffer (`Surface`): clear, fill/blend rect, 8×8 bitmap-font text, pixel readback, PPM dump. **No display required** — runs and is testable headlessly. |
| `gui.btrc` | btrc bindings + immediate-mode widgets (`Color`, `Surface`, `GuiInput`, `Theme`, `Gui`, `GuiApp`). |
| `btrc_gui_window.h` / `.c` | Optional native window backend (GLFW + GL blit). |
| `window.btrc` | btrc bindings for the window backend (`GuiWindow`). |

Not auto-included (it's in a subfolder and needs a compiled shim). Opt in with
`#include "gui/gui.btrc"` and build with `make gui`.

## Quick start (immediate-mode)

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

## Font

The bundled 8×8 font is authored bit-by-bit (5×7 glyphs in an 8×8 cell) and
covers digits, A–Z and common punctuation; lowercase maps to uppercase and
unknown characters render as a box.

## Build

```
make gui            # software renderer (always) + window backend (if GLFW present)
make examples-gui   # build + run the headless example/test
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
- Drawing is opaque-rect + bitmap text; it's intentionally minimal, not a
  full retained-mode toolkit.
