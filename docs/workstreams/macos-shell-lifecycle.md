# macOS shell lifecycle repair

Packet: macos-shell-lifecycle. Branch: `codex/macos-shell-lifecycle`.
Base: `dff538ef502f4a074c3019f677220810e4061225`.

Reserved diagnostic/repair paths:
- `src/stdlib/GUI/MacOS/MacOSApplication.btrc`
- `src/stdlib/GUI/MacOS/MacOSTextField.btrc`
- `src/tests/native/gui/shell/probes/macos/ShellProbe.m`
- `src/tests/native/gui/shell/probes/macos/AppKitControl.m`
- `src/tests/python/native_ui_shell_fixtures.py`
- `src/tests/python/test_native_ui_shell_macos.py`
- `docs/workstreams/macos-shell-lifecycle.md`

The integrator assigns this bounded repair under PLAN D29. The previous signed
native-link packet remains intact on its own branch at `e2090c51`; no source
from it is included here. Publication and final combined gates remain with the
integrator. No unrelated provider or compiler paths are owned.

Baseline: the completed full dff gate reports 17,855 passes, 168 skips and three
failures, all from the real macOS shell. Evidence lives under
`~/.cache/btrc/plan-consolidation-2026-10-07/combined-dff538ef/`; failure text and
the retained native executables/scratch are authoritative.

- Plain selfhost completes 90 successful teardowns, then throws
  `Cannot enable native application activation`. The line 203 failure is the
  subprocess exit check, not the later `dirty-close=missing` marker assertion.
- Sanitized selfhost fails at its first teardown with one provider-created
  `NSTextField` still alive.
- Sanitized Python completes 100 cycles and 100 GPU frames, then fails during
  fresh-process restore 97 with the same retained provider text field.
- Both field failures also retain AppKit's Swift-hosted text-field view and
  `AppKit.NSSimpleLabel`, beyond the usual seven private field-editor views.
  These are observations, not an allowance. All four independent one-cycle
  AX/wheel diagnostic combinations pass in each failed case.

Investigation starts read-only while the integrator restores 80 GB disk
headroom. Initial hypotheses: repeated application launch versus singleton
lifetime; delayed AppKit text-field teardown versus an actual owned reference.
Neither is yet a proven cause. No assertion, skip, survivor allowance, deadline
or provider policy is changed by this claim.

Host: Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0.
