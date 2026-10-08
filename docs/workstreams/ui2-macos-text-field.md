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
exact final source. Native execution has not run for this packet; source
projections are recorded below.

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

Formatting, Ruff and diff checks pass. Native helper compilation,
plain/sanitized execution, capacity
overlap, Escape, route migration and entered-handler close still require actual
qualification. No full E01/IME/owner-session acceptance is claimed.

The first actual reference SDK projection at d4564a49 stopped after4.803s with
three missing native method projections (subclass setBezelStyle/abortEditing,
NSTextField superview) and four nullable field-after-call warnings. The typed
stored delegate binding itself was accepted. Receipt SHA256
`b81520b12b2c103a2d00433b7fbb1618d56dd8a883e31dfc8f54ad288d9171a0`
is retained under `ui2-macos-text-d4564a49-compiler-f75c737b`; no C/link/native
stage ran. All four process groups were absent/reaped and final inputs unchanged.

The forward correction uses existing explicit NSTextField/NSView projections
and checked owning ticket/channel locals. Public native mutation also goes
through the existing MacOSView quarantine admission, while private retained
field access remains available for composition settlement and close. A separate
fixture checkpoint checks rejected mutation and successful close on that boundary.
No compiler nullability rule, binding assertion or native test assertion changed.

The corrected c4720eab source passes the same reference SDK projection on f75
with zero diagnostics in 8.634 seconds. The exact receipt SHA256 is
`fa6e33ac60837ae96d80bed71b7420297ff168205752b25af17d5779b8f22554`,
retained under `ui2-macos-text-c4720eab-compiler-f75c737b/results/textProjection1/`
with generated C and native plan. All four commands returned and reaped zero,
their process groups were absent afterward, and final source/tool inputs were
unchanged. This is semantic and SDK projection proof only; no C compilation,
link, native execution or physical IME acceptance is claimed. The original failed
d456 projection remains preserved.

The first paired native attempt on c472 passed both compiler projections without
diagnostics (reference 8.899s, selfhost 3.540s). Original strict C checks passed
the emitted program and RunLoop.m, then rejected Text.m's `__weak` ivar because
handwritten native sources use MRC. Receipt
`caba365a0c08994fc8fc16f13a3327b27d768b2e4b9f183bcc60ba073a8512d0`
is retained in `ui2-macos-text-c4720eab-native-compiler-f75c737b`; no link/native
stage ran. All stage inputs remained unchanged and owned groups were absent.

The source remedy stores the same generated scoped sink in an owned NSHashTable
using public NSPointerFunctionsWeakMemory plus pointer identity. The table does
not own the sink; captures pin the selected weak object through the surrounding
autorelease pool. Native deallocation releases the table. The existing AppKit
autoreleased field factory remains unchanged. The test probe now balances its
MRC-owned host/editor/text snapshots, and the fixture relies on the provider's
AppKit framework row instead of declaring it twice. No compiler flags, callback
API, semantic assertions or production native manifest changed. These repairs
require a fresh paired native attempt before any runtime claim.
