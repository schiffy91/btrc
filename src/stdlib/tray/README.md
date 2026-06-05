# btrc native system tray

A **real** OS-native status item — a clickable menu-bar icon (macOS) or
notification-area / Wayland indicator (Linux) with a native drop-down menu.
Selecting an item runs that item's shell command through the existing
`Command` / `UnixShell` stdlib.

Dependency-free in btrc's spirit: a thin native C shim does the OS work, all
policy lives in btrc, and it uses **only system frameworks** — no third-party
tray libraries.

## Layout

| File | Role |
|------|------|
| `btrc_tray.h` | Cross-platform C ABI for the tray runtime (opaque `void*` handle). |
| `btrc_tray_macos.m` | macOS backend: drives `NSStatusBar` / `NSStatusItem` / `NSMenu` via Cocoa. Linked with `-framework Cocoa` (system framework). |
| `btrc_tray_linux.c` | Linux backend: implements the `org.kde.StatusNotifierItem` + `com.canonical.dbusmenu` specs over D-Bus (the de-facto Wayland/freedesktop systray). Uses only base `libdbus-1`. |
| `tray.btrc` | btrc binding: `SystemTray` + `TraySignal`. Reuses the portable `Tray`/`TrayItem` data model from `ui.btrc`. |

Not auto-included (it needs a compiled native shim). Opt in with
`#include "tray/tray.btrc"`.

## Quick start

```btrc
#include "tray/tray.btrc"

int main() {
    SystemTray("App")
        .icon("/path/icon.png")                 // falls back to the title text
        .tip("My app")
        .item("Open", "open https://example.com")
        .item("Quit", TraySignal.quit())        // "__quit__" stops the loop
        .run();                                  // show + pump until quit
    return 0;
}
```

The portable `Tray` model in `ui.btrc` is unchanged and fully backward
compatible; `SystemTray` is the native renderer (the way `GuiWindow` renders a
`Surface`). You can also adopt an existing model with
`SystemTray.fromTray(tray)`.

### API

`SystemTray(title)` — fluent builder mirroring `Tray`:

- `.icon(path)` / `.tip(text)` / `.item(label, command)` / `.add(TrayItem)`
- `.show()` → `bool` — realize the native item; `false` on a headless host
- `.pump(timeoutMs)` → `bool` — pump the native loop once (`0` poll, `<0` block);
  runs any activated item's command via `UnixShell`; returns `false` once it
  should quit
- `.run()` — `show()` then block pumping until quit
- `.available()` / `.realized` — native-item state
- `.quit()` — request the loop to stop

`TraySignal.quit()` is the sentinel command (`"__quit__"`) that stops `run()`.

### How activation runs a command

When the user selects a menu item, the native shim records that item's
`command` string. The btrc loop (`pump`) takes it via the C ABI and runs it
through the existing stdlib:

```btrc
self.shell.run(command, stdout=CommandOutput.stream(), logFailure=false);   // UnixShell
```

so command execution, quoting, and process handling all reuse `Command` /
`UnixShell` — the tray shim never shells out itself.

## Build flags / frameworks

The shim is compiled and linked next to your transpiled program.

**macOS** (tested on this host):

```sh
btrcpy app.btrc -o app.c
cc -std=c11 -fobjc-arc -Isrc/stdlib/tray \
   app.c src/stdlib/tray/btrc_tray_macos.m \
   -framework Cocoa -lm -lpthread -o app
```

`-framework Cocoa` is a **system** framework (allowed); there are no other
dependencies.

**Linux** (Wayland/X11, any SNI host — GNOME AppIndicator, KDE/Plasma, Waybar, …):

```sh
btrcpy app.btrc -o app.c
cc -std=c11 -Isrc/stdlib/tray \
   app.c src/stdlib/tray/btrc_tray_linux.c \
   $(pkg-config --cflags --libs dbus-1) -lm -lpthread -o app
```

`libdbus-1` is a base system component (the reference D-Bus library), not a
third-party tray dependency. The Nix devshell provides `dbus.dev` +
`pkg-config` on Linux.

`examples/tray/Makefile` selects the right shim + flags per OS automatically
(`make` in that folder).

## GPU rendering

The tray icon and its drop-down menu are **drawn natively by the OS**, and the
OS composites them on the GPU through the platform window server — Quartz /
Core Animation (Metal) on macOS, the Wayland compositor (or X11 + the GPU) on
Linux. There is no software framebuffer in the tray path and nothing for btrc
to rasterize: routing tray drawing "through wgpu/Metal" would mean
reimplementing the system menu, which defeats the point of a *native* tray.

For **custom window content** (the `gui/` module), pixels drawn into a
`Surface` are uploaded to a GPU texture and composited with hardware by the
window backend (`btrc_gui_window.c`: `glTexImage2D` + a textured fullscreen
quad, bilinear-filtered) — i.e. present/scale is already GPU-accelerated. The
`gpu/` module (wgpu/Metal) is the path for fully GPU-rendered window content.

## Platform status

| | macOS | Linux |
|---|---|---|
| Backend | Cocoa `NSStatusBar`/`NSStatusItem`/`NSMenu` | `StatusNotifierItem` + `dbusmenu` over D-Bus |
| Icon + menu | ✅ native | ✅ native (SNI host required) |
| Activation → command (`UnixShell`) | ✅ tested (real click round-trip) | ✅ tested (dbusmenu `Event` path) |
| Realized + verified on this host | ✅ end-to-end | compiles + links + unit-verified logic; live registration needs a Linux session |

On a host with no GUI session / no D-Bus, `show()` returns `false` so callers
degrade cleanly (the example prints a notice and exits).
