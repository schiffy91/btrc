# GUI conformance suite

One portable BTRC program that holds every GUI provider to the same contract.
It uses the public facade only (`import Library.GUI;` and the exported
interfaces), so it runs unchanged on every platform a provider exists for, and
it finds what a white-box test cannot: a type the package forgot to export, an
operation a provider answers differently.

| File | Holds |
| --- | --- |
| `Main.btrc` | The cases, in order; `conformance --list` names them and `conformance NAME` runs one |
| `Suite.btrc` | The runner: a fresh application per case, driven one bounded turn at a time through the host attachment, never `GUI.run` |
| `Probe.btrc`, `probes/` | Input a person gives a window, by its title: the one thing the suite cannot do through the facade |
| `Picture.btrc` | The suite's eyes: `GUI.capture`, and a flat colour's bounding box in it. Views have no frame getter, so geometry is checked the way a person sees it |
| `cases.toml` | Every case and the catalog operations it exercises |
| the rest | The cases, grouped by what they hold to account |

## The probe

`probes/ConformanceProbe.h` is the whole interface: move, press, release,
wheel, key, text and the window manager's close, each queued for the window
with a given title and delivered by the application's next turns. Each
platform implements it once, in C, beside the suite:

| Platform | Source | How input arrives |
| --- | --- | --- |
| Linux, Windows, Android (the shim provider) | `probes/shim/ConformanceProbe.c`, `ShimProbe.c` | Real input: XTEST on X11 (`probes/linux/X11Input.c`), a wlroots compositor's virtual pointer and keyboard on Wayland (`probes/linux/WaylandInput.c`), `SendInput` on Windows (`probes/windows/Win32Input.c`), the system's event injection on Android (`probes/android/AndroidInput.c` and `probes/android/java`) |

The probe is the input itself: it moves the session's one pointer and types
on its one keyboard, so it runs only where `BTRC_UI_PRIVATE_SESSION=1` says
the session was made for tests (`tools/ui/headless-session.sh` sets it; on a
dedicated test host it is set by hand). Two things the display server will not tell an
input tool it asks the provider's shim, through hooks that deliver nothing:
where the pointer is in a window's content, which is how it finds that
content on the screen, and whether what it sent has arrived.

## Running it

`src/tests/python/test_native_ui_conformance.py` builds the program through
both compilers, plain and sanitized, and runs each case in its own process:

```sh
tools/ui/headless-session.sh --x11 -- python3 -m pytest -q src/tests/python/test_native_ui_conformance.py
tools/ui/headless-session.sh --wlroots -- python3 -m pytest -q src/tests/python/test_native_ui_conformance.py
tools/ui/headless-session.sh --wayland -- python3 -m pytest -q src/tests/python/test_native_ui_conformance.py
```

On Android the suite is an app.
`src/tests/python/test_native_ui_conformance_android.py` builds it for the
device's ABI through both compilers, installs it on the emulator
`BTRC_ANDROID_SERIAL` names (or boots one from `BTRC_ANDROID_AVD_STATE`),
and runs each case as its own process, started with `am instrument`: the
system lets a program send input to its own windows only under
instrumentation, which lends it the test host's right to. A press is a
finger's, as it is on a phone; a move with nothing down and a wheel are a
mouse's.

A case prints `CASE <name> PASS`, or `CASE <name> FAIL <what it found>`.
`BTRC_CONFORMANCE_FONT` names a font file for the font face case, and
`BTRC_CONFORMANCE_WEB` the directory bundle (`web/`) for the web view's; the
driver supplies both. A case with `needs` in `cases.toml` applies to the
providers that have what it names: the web view's cases need `web`, the
alert's and the folder chooser's `modal`, and the wheel's `wheel`, a pointer
device a phone does not have.

## Coverage

The driver holds `cases.toml` to the operation catalog
(`docs/design/native-ui-catalog/operations`): every operation is exercised by
exactly one case, or named in the file's `[uncovered]` table with what stands
in the way. That table is empty. `python3 -m tools.qualification.ui_conformance
record` writes what the cases prove into the catalog: each operation's case is
its regression on Linux, Windows and Android.

An alert and the folder chooser run a loop of their own, so the program that
opened one cannot press its keys. `probes/shim/ModalProbe.h` starts a helper
thread that presses Escape, with the same real input as the rest of the
probe, to whatever window is in front, until the modal has returned
(`Modals/ShimCases.btrc`; the cases need `modal`). Android has no folder to
choose by path: its case holds the chooser to saying so.
`IApplication.pollClose` is the application's own to call: `app.run` quits
while a GPU view's work is in flight, so the loop has to poll the close to
its end before `run` returns.

## Adding a case

Write a class implementing `IConformanceCase` (or `ILoopCase` when the case
must own `GUI.run`), add it to `Main.btrc`, and record it in `cases.toml` with
the operations it exercises. Give every window a title no other case uses:
the probe finds windows by title.
