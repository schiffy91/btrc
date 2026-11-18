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
| Linux, SDL provider | `probes/linux/SdlProbe.c` | Synthetic SDL events queued for the window |

A probe is a stand-in for a compositor's or a person's input, as the
provider's own automation helpers are. It never reaches into a provider.

## Running it

`src/tests/python/test_native_ui_conformance.py` builds the program through
both compilers, plain and sanitized, and runs each case in its own process:

```sh
tools/ui/headless-session.sh --x11 -- python3 -m pytest -q src/tests/python/test_native_ui_conformance.py
tools/ui/headless-session.sh --wayland -- python3 -m pytest -q src/tests/python/test_native_ui_conformance.py
```

A case prints `CASE <name> PASS`, or `CASE <name> FAIL <what it found>`.
`BTRC_CONFORMANCE_FONT` names a font file for the font face case; the driver
supplies one.

## Coverage

The driver holds `cases.toml` to the operation catalog
(`docs/design/native-ui-catalog/operations`): every operation is exercised by
exactly one case or named in the driver's `UNCOVERED` table with what stands
in the way. Today that table has four entries: the alert and the directory
picker, which are modal and need a probe that can answer them, and
`IApplication.pollClose`, which the facade never calls.

## Adding a case

Write a class implementing `IConformanceCase` (or `ILoopCase` when the case
must own `GUI.run`), add it to `Main.btrc`, and record it in `cases.toml` with
the operations it exercises. Give every window a title no other case uses:
the probe finds windows by title.
