# Portable muted speaker symbol

The Player speaker state needs `speaker.slash.fill`. Linux currently rejects this
name, while its `speaker.wave.2.fill` rendering exists. The only button providers
at5be are LinuxButton (fixed LinuxSymbols vocabulary) and MacOSButton (native
NSImage system-symbol lookup). No other provider implementation is changed.

Append the muted name at index18, preserving every existing index0–17. The
existing speaker-body geometry is shared; the muted branch draws a diagonal
slash in place of sound arcs. The portable IButton vocabulary includes the name.

The existing LinuxGUIControls fixture retains its original assertions and adds
same-button, same-size composed captures: both symbols must draw pixels, differ,
and restore the exact audible pixels after a round trip. Fitting size stays
constant, setters emit no action, disabled activation is rejected, and a real
queued SDL pointer click on the muted control delivers exactly one action. The
existing test_linux_gui_controls owner retains both frontends and both sanitizer
rows with its original180-second timeout. No new skip or driver is introduced.

This is source preparation only. Native compilation, capture assertions and
actual behavior remain unqualified. It does not prove BTRSmith mute/persistence,
macOS SF Symbol availability, physical input or a full GUI acceptance.
