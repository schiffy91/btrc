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

## Independent native diagnosis and bounded probe repair

The public-AppKit restore diagnostic reproduced the exact retained field
without BTRC runtime/provider or GPU code: the same `NSTextField` remained alive
after the original drain at 0.221910 s, remained alive at 0.292799 s, then
disappeared at 0.314785 s. This demonstrates deferred toolkit teardown beyond
the probe's fixed ten turns; it does not prove an application-owned reference
leak. Commands, source snapshots/hashes and pointer/time observations are retained
in `macos-shell-lifecycle/diagnostic-1` beside the baseline evidence.

The repair keeps the original ten turns, then continues only while provider
weak references remain, within a two-second monotonic deadline. Every original
zero-provider-survivor and callback-registration assertion remains. Private
classes still use the independent native control's observed allowance. Each
drain records turns, elapsed seconds, exact deadline and owned count. A new
independent negative control deliberately retains the real field across the
deadline, requires exactly one survivor, releases its reference, then requires
zero. The driver requires the deliberate failure exit and preserves its output,
including on timeout. No production text-field change is justified by this
evidence. Both independent reviewers found no blocker; the approved lifecycle
contract allows platform-deferred deallocation within a bounded native drain
(`docs/design/ui-contracts/ui2-approved.md`, native teardown contract).

Activation remains a distinct open defect. A native-only control calling
activation/finishLaunching for 100 successive cycles passed, so repeated launch
as the cause is unproven. The first focused repair run reproduced activation
failure in plain selfhost after 45 zero-survivor cycles, compared with 90 in the
full gate; this is not being dismissed as a pre-existing/transient failure.
The reference plain variant passed all 100 cycles and 100 restores. Its real
negative control retained one field for 2.000446 s, then released to zero after
0.209455 s. Focused run 79113 ended with 39 passes and two failures in
513.31 s. Both reference variants passed all 100 cycles and 100 restores.
Sanitized selfhost also completed all cycles/restores with zero provider and
registration survivors, but the unchanged class comparison failed because
`NSTextInsertionIndicator` was absent from its independent control. This remains
a failure, separate from activation. No final qualification is claimed.

The queued quiet compiler measurement takes the native lane immediately after
focused run 79113. No new native launches occur until the integrator releases
that measurement barrier. A forwarding-only activation trace is prepared under
`/private/tmp/btrc-audit-repair/macos-shell-lifecycle/ActivationTrace.m`, but has
not been compiled or executed. Provider source remains unchanged.


## Control-context investigation

Raw focused-1 timelines show that sanitized selfhost was active/key during 22
cycles, while its native control was inactive/nonkey during all 100 cycles.
`NSTextInsertionIndicator` survived in 21 shell cycles (2–21 and 72), one
instance each with different pointers; it never appeared in that control.
Both drains took approximately 0.205–0.209 s with zero provider survivors.
These observations support a missing equivalent active/key control journey;
they do not establish a provider leak or authorize a new class allowance.
Both production `MacOSWindow.show()` and the existing native control use
`makeKeyAndOrderFront`; neither explicitly activates the app. The production
application wrapper repeats `finishLaunching`, unlike the ordinary control.
Generated Objective-C adapters for both frontends are byte-identical; no
activation ABI defect was identified in independent read-only review.

The quiet memory attempt then refused without collecting samples. The integrator
released the native lane for a forwarding-only activation trace on the retained
selfhost executable and an independently activated/key native-control diagnostic.
Diagnostic-2 preserves its sources, commands, executable hash and raw observations;
its result is pending. These diagnostics do not change provider behavior, class
allowances, growth bounds or the original shell assertions.

Diagnostic-2 completed: both traced retained plain-selfhost runs passed 100
cycles (40.303 s and 39.909 s). Each used one stable application pointer;
initial policy was Prohibited (2), setting Regular (0) succeeded, and later
observed policies remained Regular. The actual failing policy/setter values
remain unknown. These isolated successful traces do not repair the intermittent
activation failure seen after the preceding reference test/restore workload.

An independent native control using cooperative `activate` failed its existing
15 s deadline before obtaining active/key context. Diagnostic-3 used public
`activateIgnoringOtherApps:YES` and `makeKeyAndOrderFront`: six cycles completed
with one `NSTextInsertionIndicator` and zero provider survivors each, before
active/key context was lost and the unchanged deadline failed. Diagnostic-4
repeated the public activation/key request only while actual context was absent,
within that same deadline: all 100 sanitized native-only cycles passed in
40.698 s, with all 300 recorded Tab-context observations active/key, zero owned
survivors, and eight private objects per cycle including exactly one indicator.
No BTRC runtime/provider/GPU was linked. This establishes the missing equivalent
control journey without a named-class exception or changed growth bound.

The native lane was released after diagnostic-4. The bounded fixture correction
will retain and require those native context observations; it does not claim
production keyboard/GPU accessibility gaps resolved. Native rerun of the final
source, and diagnosis of the distinct intermittent activation failure, remain
open. Original failed artifacts are retained.

The prepared source correction makes the native control converge on actual
active/key state before editing and observation, under its original 15 s journey
deadline, and preserves all 100 × 3 actual context observations in evidence.
The summary now requires those observations before using native private-class
counts; six negative cases cover missing/partial/inactive/nonkey/nonboolean
context. The class allowance and first-observed multiplicity checks are
unchanged. These source changes and pure regressions are not yet executed:
the integrator reserved the next lane for a quiet measurement.

A private `qualify-with-trace.py` is prepared to run the entire focused module
in its original serial order, retaining the preceding reference's 100 restores.
Only NativeShell subprocesses in its scratch receive the forwarding trace;
compiler/tool processes and the independent control are unaffected. It retains
source/binary hashes, commands, raw output and unchanged test assertions. This
instrumented run is diagnostic, not final native qualification. It has not run.

Pure regression qualification ran after the first quiet preflight stopped:
`context-regressions-1` retains the exact `summarize_macos_shell` body from
`git show dff538ef` composed with the unchanged six new cases and fixture.
All six failed with `DID NOT RAISE` against that prior owner (1.11 s); all six
passed against the correction (0.32 s), with 41 other cases deselected in each
run. Source snapshots/hashes, commands, logs and XML are retained. Session 54647
ended successfully and all test execution stopped for the quiet restart.
Root's independent static review found no blocker in the four code/test files
or the trace runner. Final native execution remains pending.

## Full suite-context trace and uninstrumented result

The reviewed repair was committed as `c0e4d48a` after Ruff lint/format and diff
checks. `focused-trace-1` passed all 47 tests in 651.09 s on that clean source,
using unchanged production compiler SHA `85c4029079568b3a73fbd6853148d5b1e8038a05224e6e75c4ccd3768511e1c3`.
All 420 traced NativeShell subprocesses exited zero. No captured policy became
non-Regular after launch and no setter returned false. The longest zero-owner
drain was 0.230768 s; all four deliberately held fields remained visible through
the 2 s deadline and disappeared only after release. End HEAD/status were
verified. This trace did not reproduce or repair the activation exception.

`focused-2` then ran the same source without injection: 44 passed and three
failed in 395.44 s. Every BTRC main journey completed 100 cycles/100 frames with
zero owned survivors. Plain selfhost and both sanitized variants failed in the
independent control before cycle 1: active=0, key=0, policy=Regular, after the
unchanged 15 s deadline. Those cases did not reach their restore loops. Plain
reference completed its full checks. The original provider activation exception
did not recur. The successful traced and failed uninstrumented plain-selfhost
controls are byte-identical (`18e82d2268711b634725492175452932c4e2eaf4c7376ffc7edccbd2d6a9d772`)
and were never injected; their preceding shell journeys were both inactive/keyless
throughout. The actual failed evidence remains retained, not classified green.

Diagnostic-5 placed that exact control binary in a conventional temporary app
bundle and launched it with public `open -n -W`, retaining stdout/stderr. It also
failed the same focus guard before cycle 1. `open` returned zero, which is only
its launch status and is explicitly not reported as the application's status.
A public metadata-only probe then reported frontmost pid 455,
`com.apple.loginwindow`, active=true, on-console=true, login-done=true.
Foreground ownership by loginwindow prevents the required visible active/key
journey in this host state. No user content, credentials, Accessibility prompts
or settings were accessed or changed. Further GUI launches stopped; the native
lane was released. Final uninstrumented qualification requires an active user
desktop, and the original intermittent policy/setter failure remains a separate
open diagnosis. No deadline, skip, class allowance or growth check was weakened.
