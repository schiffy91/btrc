# Native tray

`import Library.Tray.Tray;` provides `SystemTray`, backed by a private provider
selected for the compilation target: AppKit on macOS, StatusNotifierItem over
D-Bus on Linux. Windows has no provider and fails explicitly during provider
selection.

```btrc
SystemTray("App").item("Open", "open https://example.com")
	.item("Quit", TraySignal.quit()).run();
```

`show()` creates the status item, menu, enabled states, checkmarks, tooltip and
optional icon. Native initialization failure throws. `run()` blocks until a
`TraySignal.quit()` item is activated or `quit()` is called; `pump(timeoutMs)`
remains available for an existing manual host. `close()` removes the item and
is idempotent. Shell commands and check-item probes execute synchronously, so
callers must keep them bounded.

## macOS provider

`MacOS/TrayProvider.btrc` imports AppKit SDK declarations. Generated adapters
own native ARC and target/action subscriptions through `CallbackScope`; no
handwritten tray bridge or manual native handle is linked. Build with the
compiler's native link plan. Native objects and their destruction require the
main thread. `run()` uses the AppKit application loop; an initialized
application's activation policy is preserved, and `quit()` stops a standalone
tray loop without stopping an existing GUI loop.

Menu actions queue up to 256 ordered commands. A shared native run-loop signal
delivers them after menu tracking; overflow is an explicit terminal error.
Check-item probes refresh after command execution.

## Linux provider

`Linux/TrayProvider.btrc` speaks the KDE StatusNotifierItem spec
(`org.kde.StatusNotifierItem`) plus Canonical's `com.canonical.dbusmenu`, which
Plasma, GNOME's AppIndicator extension and the wlroots bars consume. It binds
libdbus-1 through a typed native import on `Linux/DBus.h`; that header only
adapts what the importer cannot lower faithfully: `DBusError` (bitfields)
stays C-side behind call adapters, and the by-address basic marshalling
(`dbus_message_iter_append_basic` / `get_basic`) becomes by-value helpers.
`[[native.pkg-config]]` names `dbus-1` for the header read and the link.

The provider owns a private session-bus connection named
`org.kde.StatusNotifierItem-<pid>-<connection serial>` and pumps it by pull:
`pump()` reads the socket, pops every queued method call and answers it itself,
so no native callback or object-path vtable is involved and activations run on
the caller's thread after their reply has left. Every unhandled method call
gets an `UnknownMethod` error reply rather than a silent timeout. Check items
are probed when the menu is realized, on every `AboutToShow`, and after each
activation; a changed mark bumps the dbusmenu revision and emits
`LayoutUpdated`. The item re-registers when `org.kde.StatusNotifierWatcher`
changes owner, so a restarted host (kded/plasmashell crash recovery) shows it
again. `show()` throws when there is no session bus or no watcher.
