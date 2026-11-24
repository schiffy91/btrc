# Legacy X11 D-Bus session activation on Linux

Standalone `Library.DBus` connects to the session bus through
`DBUS_SESSION_BUS_ADDRESS`, `$XDG_RUNTIME_DIR/bus`, and
`~/.dbus/session-bus/<machine-id>-<display>` without launching `dbus-launch`.

This optional package restores `dbus-launch --autolaunch=<machine-id> --binary-syntax --close-stderr`
activation for legacy X11 sessions that have no reachable address, runtime
socket or saved session file. It needs no `libdbus` library or D-Bus
development headers at build or link time.

## Link the package into an application

Add a relative path to the package in the application's `btrc.toml`:

```toml
[dependencies]
dbusX11 = { path = "packages/dbus-x11-launch" }
```

Import `dbusX11.DBusX11Launch` and call `DBusX11Launch.install()` before
`DBusConnection.session()` or `DBusConnection.open("autolaunch:")`.
`DBusX11Launch.available()` reports whether `dbus-launch` is executable on
`PATH`. On targets other than Linux, `install()` is a no-op and `available()`
returns `false`.

## Preload the adapter for an existing binary

Existing standalone Linux binaries built with `Library.DBus` can enable the
same fallback at launch time without recompiling. Build the shared object from
a BTRC checkout:

```sh
cc -O2 -std=c11 -fPIC -shared -I src/stdlib/DBus/X11Autolaunch \
  packages/dbus-x11-launch/Linux/Backend.c \
  -Wl,-soname,libbtrc-dbus-x11-launch.so.1 -o libbtrc-dbus-x11-launch.so.1
```

Then launch the binary with `LD_PRELOAD`:

```sh
LD_PRELOAD=/opt/my-app/lib/libbtrc-dbus-x11-launch.so.1 /opt/my-app/bin/my-app
```

Preloading requires a dynamic ELF loader that honors `LD_PRELOAD`. For
statically linked or secure-execution binaries, link the package directly into
the executable. At run time, the target X11 system needs an installed
`dbus-launch` helper on `PATH`.
