# UI2 Linux provider

Packet CX-UIA-23, assigned under PLAN D29. Branch
`codex/ui2-linux-provider`; source-only base `bd8b5904320e8f1e2d7e16f994e8c68977351f31`
combines preserved grid/input/layout/scroll source `47e64e21`, reviewed integration
`db269d6c`, and approved interface `ca4782e1`. The old qualification archives and
branch refs remain unchanged. This branch is an atomic UI2 landing dependency,
not an independently shippable provider/interface release.

## Owned paths

- `src/stdlib/GUI/Linux/{LinuxApplication,LinuxWindow,LinuxTextField,LinuxSelect,LinuxSlider,LinuxScrollView,LinuxImageView,LinuxView,LinuxActionQueue,LinuxContext,LinuxContainer,LinuxStack,LinuxPanel,LinuxButton,LinuxPublisher}.btrc`
- `src/stdlib/GUI/Linux/SDL.h`
- `src/tests/native/gui/ui2/probes/linux/{UI2LinuxProbe,UI2LinuxExecutor,UI2LinuxControls,UI2LinuxLifecycle}.btrc`
- `src/tests/native/gui/ui2/probes/linux/{UI2LinuxProbe.h,UI2LinuxProbe.c}`
- `src/tests/python/test_native_ui2_linux.py`
- this report

SDL symbol/export rows are an integrator fragment; no portable interface,
catalog, generated output, Mac provider or frozen evidence is edited here.
LinuxPublisher owns only this provider's bounded plain-data worker ingress;
LinuxContext carries its existing shared provider services. The approved
interface and ui2-approved.md govern; no second portable ownership model.

## Qualification state

Claim precedes implementation. Existing Linux 96-row repair and four Grid04
rows are being qualified from immutable archives by another agent. No UI2
native run, compiler build, guest, latency measurement or acceptance is claimed.
Before source work the host had 81.44 GB available. Native tests wait for the
parent's exclusive lane. The fixture-only checkpoint must precede production.

Required evidence includes real worker wake with the SDL waiter parked without
a polling timer, failed SDL wake, bounded class rotation and deadline dispatch,
host suspension stand-ins, revisioned reversible close, control draft/terminal
events with SDL composition, ownership-preserving mutation and retained image
presentation. Both frontends, plain/sanitized, X11/Wayland, original E40 counts
and the separate ten-minute load remain acceptance requirements. Linux undo,
physical IME, headless minimize/cover/scale evidence remain explicitly outside
the corresponding stand-in claims. Both complete desktop providers and the
interface must integrate atomically before product use.
