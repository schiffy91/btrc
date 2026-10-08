# Public macOS Application composition

Integrator-assigned D29 continuation from clean904d2716, preserving the existing
qualified Window and foundation sources. Branch codex/ui2-macos-application.
Owned Application/Executor/RunLoop seams and original public host fixture/driver
are listed in WORKSTREAMS. TextField, Slider and Select implementations belong
to separate coordinated owners; no portable interface or context change is
part of this packet without coordination.

Actual b6/f75 original NativeApplicationHost reference baseline (session25358)
retains19 errors: Application3, TextField3, Slider6, Select7, plus the nullable
publisher fixture warning. Evidence application-baseline-result.json in
ui2-macos-foundations-b6a4fe3e-compiler-f75c737b; aggregatee7d442. No C/link/native
public Application acceptance has occurred. Preserve every original assertion.

One MacOSApplication lifecycle composes the existing MacOSWorkQueue,
MacOSPublisher, staged MacOSRunLoopSignal and explicit MacOSControlContext.
Constructor must leave a foreign host delegate unchanged. post/postAfter and
schedule share work accounting; internal run and external attachment share
bounded service and nonblocking shutdown. Native group quit remains separate.
Original internal-run native shell and public hosted behavior both require
paired plain/sanitized acceptance; component proofs do not substitute for them.

Source work begins while another agent owns the native attribution lane.
No test/compiler/AppKit process is authorized concurrently.
