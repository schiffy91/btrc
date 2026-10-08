# UI2 macOS text field events

Packet: CX-UIA-22 text-field completion under PLAN D29.
Branch: `codex/ui2-macos-text-field`.
Base: `904d2716898c13915e59a5af9cc966339e9d12f6` (qualified provider b6).
Owner: performance_review; parent integrator owns final fragments and landing.

## Owned paths

- `src/stdlib/GUI/MacOS/MacOSTextField.btrc`
- `src/stdlib/GUI/MacOS/Text.h` and `Text.m` if native field-editor operations require a cohesive helper
- `src/tests/native/gui/ui2/probes/macos/NativeTextState.btrc`
- `src/tests/native/gui/ui2/probes/macos/TextProbe.btrc`, `TextProbe.h`, `TextProbe.m`
- `src/tests/python/test_native_ui_text_macos.py`
- `src/tests/native/gui/ui2/probes/macos/NativeApplicationHost.btrc` checked-local warning correction only, separate commit
- This report and this packet's WORKSTREAMS reservation

No portable interface, shared semantic context, Application/Executor, compiler,
generated output or production manifest change is claimed. Any needed native
metadata is a separately reviewed integrator fragment, never a hand-edited
generated catalog. The existing generic/token/audio branches remain preserved.

## Authentic starting evidence

The original public NativeApplicationHost fixture, provider b6 and current f75,
failed reference semantic projection in session25358 after 7.685 seconds.
Nineteen missing-method errors included this owner's onDraftChanged/onCommit/
onCancel; the other sixteen belong to Slider, Select and Application. One
separate fixture warning reports nullable publisher capture. SDK/probe setup
passed; no C compilation, linking or native application execution occurred.
Evidence: `ui2-macos-foundations-b6a4fe3e-compiler-f75c737b/application-baseline-result.json`,
SHA256 `e7d442a68ab6976824ae07249df95ac4c1189eb67ed65ac430c01e980c643296`.
The eight foundation native passes qualify their unchanged source only.

## Bounded implementation and proof

Keep AppKit as the editor/selection/composition/undo owner. Use the existing
generated stored delegate registration and CallbackScope cancellation barrier,
MacOSViewState routing, and ControlEventChannel immutable snapshots/reservations.
The text owner owns accepted baseline, interaction/sequence/model revision,
composition observation and reserved terminal tickets. Capture must contain
native-boundary failures through the existing context latch.

`text()` reads the live editor without validateEditing. Publishing the accepted
baseline is a true no-op even during dirty/composing edits. A changed model
cancels once at the old revision before establishing the new baseline. Return
and subsequent end-edit notifications cannot double commit. Escape first follows
composition cancellation; without composition it restores the accepted baseline.
Eligibility loss settles before native hide/disable/detach and preserves the
non-composing draft with one SYSTEM cancellation. Same-window moves preserve the
interaction; route rebind follows old-route settlement.

Preserve a fixture-only checkpoint before provider changes. Real native tests
must exercise field-editor input/marked text, selection/undo preservation on
no-op, dirty Return/blur deduplication, Escape, MODEL replacement, SYSTEM retained
draft cancellation, detach/reattach/move, queue ordering/pressure, scope cancellation
and entered-callback close. Programmatic field-editor composition is mechanism
evidence; owner IME evidence remains separate. Request early reference SDK
projection, then paired strict C/native plain+ASan/UBSan qualification on the
exact final source. No tests or native builds have run for this packet.

## Source checkpoint and pending qualification

Fixture-only checkpoint `c21f791f` uses actual NSTextView insertion, marked text,
Return, focus departure and native editor identity/selection/undo observations.
It has not yet been executed. The authentic application baseline remains the
three missing-method diagnostics above, not a claimed native red result.

The provider source adds the three typed channels, accepted-baseline no-op,
immutable queued payloads, native capture failure containment, model and
eligibility settlement, and separate native/semantic cancellation drain.
`Text.h`/`Text.m` forward AppKit's begin/change/end/command hooks through a typed
weak sink using the existing generated stored callback registration. This is an
actual NSTextField subclass: AppKit retains editing, selection and undo behavior.
The helper resolves the existing native projection's duplicate `control` selector
restriction without a compiler change. Changed model/eligibility settlement ends
the native editing session; unchanged accepted-model publication never touches it.

All domain channels retain effective-eligibility admission. Approved decisions
514–519 and reconciler139–145 override the older control draft115–118: accepted
commits can retire INELIGIBLE, and never become another cancellation. An active
interaction captures one SYSTEM cancellation with its old identity and retained
non-composing draft; a still-ineligible target or old-route retirement may dispose
that record INELIGIBLE. No generation restamping or observation-target exception
is introduced. A disable/reenable-before-service fixture inspects the captured
payload; a queued-commit-then-disable fixture checks the disposition instead.

The dedicated driver's `TEXT_PROVIDER_BINDINGS` is the exact proposed native
fragment, applied only to its copied test data root. Production manifest and
generated files remain unchanged. Final integration must apply the same binding
rows once and remove any redundant test-only application. The private queue is
exported only in that fixture's copied data root.

Formatting, Ruff and diff checks pass. Reference SDK projection is the next
required step; native helper compilation, plain/sanitized execution, capacity
overlap, Escape, route migration and entered-handler close still require actual
qualification. No full E01/IME/owner-session acceptance is claimed.
