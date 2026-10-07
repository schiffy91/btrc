# CX-STDLIB-03: preserve explicit Mac button alignment

Owned paths: `src/stdlib/GUI/MacOS/MacOSButton.btrc`,
`src/tests/native/gui/controls/macos/ButtonAlignment.btrc`, and the narrow
registration in `src/tests/python/test_native_gui_appkit.py`. This report records
the packet and its evidence.

Base: `87dd60d7`. Implement the accepted first-delivery repair from PLAN.md.
The original unpublished source is unavailable locally; reproduce the defect on
current source and reconstruct the minimal owner-layer change.

Acceptance: explicit alignment survives title/symbol changes, default alignment
remains correct, and the real AppKit fixture passes through both compilers and
required sanitizer variants. No native result is claimed by this claim commit.

## Reconstructed repair

Source inspection found that `setCentered` updates only the native control, while
`placeSymbol` overwrites that alignment after every title or symbol change.
Preserve the explicit setting in `MacOSButton`; use its existing automatic
titled-left/icon-only-center defaults only until an alignment is requested.
Image position and title hugging still follow the presence of a title.

The dedicated `ButtonAlignment.btrc` fixture uses actual AppKit property readback,
registered in the existing native GUI driver. It checks default plain/title and
symbol behavior; explicit left and center set before and after a symbol; empty
and nonempty title changes; symbol replacement; and changing an explicit setting.
Each control is closed. The probe only reads native state; it does not implement
the provider policy or use a mock.

## Qualification

Static checks passed: Ruff lint and Python formatting for the driver, Python AST
parsing, BTRC formatting for both BTRC files, and `git diff --check`. The first
BTRC formatting check requested the fixture's canonical one-line helper; the
formatter applied it and the subsequent check passed. Tools were already
realized Nix store binaries; no Nix realization or native build ran in this lane.

Native red/green execution is pending the main gate owner. Run from this clone
in the qualified Nix environment with the native header reader and a
source-matched self-host compiler:

```sh
python -m pytest -q src/tests/python/test_native_gui_appkit.py -k ButtonAlignment
```

Expected admission is four cases: reference/self-hosted, each plain/sanitized.
Run first at the fixture-only commit, then at the repair commit; retain the
failing assertion and final JUnit/logs with source and toolchain identities.
No executed failure or native pass is claimed yet. A source-level diagnosis and
passing static checks do not qualify the AppKit behavior.

## Pilot intervals (UTC, 2026-10-07)

- 16:18:21–16:21:30: baseline source inspection, implementation, fixture authoring
  and static checks, including formatting correction. Start-of-stage free space:
  80,319,000,576 bytes, above the 80 GB threshold.
- 16:21:30 onward: prepare handoff/report and local commits. Native qualification
  remains waiting for the existing serialized gate; no active gate time is
  attributable to this packet yet. Main owner records its eventual start/finish.

## Native verification, 2026-10-07

The main integrator ran the actual AppKit fixture on
Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0.

- Fixture-only integration `d248b742`: all four cases failed at the actual
  alignment assertion (reference/selfhost, plain/ASan+UBSan), 54.12 seconds.
- First repair `f320093c`: both compilers rejected the ternary's promoted integer
  result when assigned to bool. Four compile failures were retained; this was not
  a passing native run.
- Corrected integration `37a8ae67`: **4 passed, 136 deselected, zero skips**,
  52.80 seconds, including both compilers and both sanitizer configurations.

Command: `python3 -m pytest -q -rs src/tests/python/test_native_gui_appkit.py -k ButtonAlignment`.
The qualified Darwin Nix shell supplied Python; the self-host binary was the
previously built `a8d92cb8` compiler, SHA-256
`5d146acf85ee91345fd1833b6a5effa8151f618da334c1e1adf71de2076778b7`.
The integrator verified its production compiler/spec/runtime tree was unchanged.
The branch's provider, fixture and driver bytes match that passing integration.
This is focused source-matched provider evidence, not full branch or combined-tree
qualification. Hosted checks and final integration gates remain required.

Retained evidence: `~/.cache/btrc/plan-consolidation-2026-10-07/subagent-delivery/button-alignment/`
contains `red`, `green` (the rejected first repair) and `green-2` manifests,
JUnit, logs and scratch. Native work ran 16:25:25–16:26:21, 16:26:48–16:27:09
and 16:29:02–16:29:59 UTC respectively.
