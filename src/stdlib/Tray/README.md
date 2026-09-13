# Native tray

`import Library.Tray.Tray;` provides `SystemTray`, backed by a private macOS
provider selected for the compilation target. Linux and Windows providers are
not implemented; those targets fail explicitly during provider selection.

```btrc
SystemTray("App").item("Open", "open https://example.com")
	.item("Quit", TraySignal.quit()).run();
```

The provider imports AppKit SDK declarations. Generated adapters own native
ARC and target/action subscriptions through `CallbackScope`; no handwritten
tray bridge or manual native handle is linked. Build with the compiler's native
link plan. Native objects and their destruction require the main thread.

`show()` creates the status item, menu, enabled states, checkmarks, tooltip and
optional template icon. Native initialization failure throws. `run()` uses the
AppKit application loop; `pump(timeoutMs)` remains available for an existing
manual host. An initialized application's activation policy is preserved.
`quit()` stops a standalone tray loop without stopping an existing GUI loop;
`close()` unregisters callbacks and removes the status item, and is idempotent.

Menu actions queue up to 256 ordered commands. A shared native run-loop signal
delivers them after menu tracking; overflow is an explicit terminal error.
Check-item probes refresh after command execution. Shell commands and probes
execute synchronously, so callers must keep them bounded.
