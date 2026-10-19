# Linux Window close transactions

Packet: CX-UIA-23 Window close. Base44a6f04a, branch codex/ui2-linux-window-close.
Integrator assigned this bounded continuation under D29; previous Linux writer
confirmed the source clean and idle. The original branch remains preserved.

Owned paths are the four existing Linux provider owners LinuxWindow,
LinuxContext, LinuxApplication and GUIProvider; the dedicated native Window
close fixture/probe, its existing driver row, this report and the claim.
No portable contract, compiler, generated catalog, production manifest or full
UI2 redesign is part of this packet. Native application quit grouping remains
separate; no partial full-provider qualification is claimed.

Baseline source observation: LinuxWindow exposes state/onStateChanged but lacks
requestClose/onCloseRequested and transaction ownership. Its application render
path force-closes a native request flag. Approved ui2-approved.md:640-677 requires
repeat identity, cancellation, revision/attempt authority and single-use close.
The implementation will use the existing context, semantic terminal reservation
and CallbackScope; it will preserve native window/editor state on cancellation.

The Mac b6 implementation and eight actual f75 native passes provide the sibling
behavior, not Linux evidence. Native SDL baseline and paired/sanitized acceptance
must execute on a real Linux runner before any passing implementation claim.
Source preparation waits for the allocated native/guest lane; hosted waves are
currently occupied. No VM, compiler, native program or test has run for this packet.

## Source checkpoints and pending acceptance

Claim335f0f43 precedes fixture-only a058e53f. Independent source review found
no blocker in that fixture. Its real SDL close event must reach the ordinary
window dispatcher; delivery must remain queued. The original assertions cover
independent windows, repeated identity, stale revision/attempt rejection,
failed-save retry, cancellation preserving root/text, terminal reservation
under ordinary queue pressure, entered-callback close drain, rejected scope
admission and a shared cross-window modal guard. Native quit grouping is not
covered by this component.

The production draft reuses the existing LinuxWindow, LinuxContext,
ControlEventQueue and CallbackScope owners. A native close flag counts as
pending semantic work; its service admits a reserved terminal record, and the
application no longer bypasses that decision by force-closing the window in
its render phase. Forced close resolves an existing transaction OWNER_LOST.
The receiver's finally-only cleanup balances the shared modal guard on both
normal and throwing callbacks under the language's existing exception rules.

Static preparation at 2026-10-08 11:19 UTC: canonical BTRC formatter, Ruff on
the changed driver and git diff --check passed. No compiler projection, C
compilation, test process or SDL execution has run. Source-only work proceeded
while the serialized native lane and hosted waves belonged to other packets.

The next Linux acceptance must execute a058e53f as the baseline, retain its
actual failure, then use the repaired source with identical fixture, current authenticated
compiler and Linux SDK/image. Run the dedicated driver with
`-k UI2LinuxWindowClose` through the existing headless session, both frontends
and both plain/sanitized rows. Preserve generated C, native plans, stdout,
stderr, exact test identity/count, source/tool hashes and process closure.
Do not count a skip as native acceptance. The integrator must compose the
current Linux GUI lease/known-driver admission before the normal full GUI gate;
this source base predates that separately qualified coordination packet.

Independent bounded production source review found no blocker in the four-file
Window/context/application/modal-routing delta. Compilation and native acceptance
remain pending. Qualification composition also needs the inherited text slice's
`SDL_ClearComposition` binding: existing LinuxTextField.btrc calls it, but this
base's SDL symbol list does not expose it. Keep that exact native dependency in
both baseline and candidate composition; do not remove the retained-draft oracle.
The manifest remains integrator-owned and untouched by this implementation.

Final native fragment exposes only two already-used SDL declarations:
`SDL_ClearComposition` is `bool(SDL_Window*)`, main-thread-only since SDL3.2;
`SDL_EVENT_TEXT_EDITING` is the existing SDL_EventType composition event used
by LinuxWindow dispatch. Both are selected from the existing SDL.h binding,
with no guessed prototypes/values or generated changes. Official declarations:
https://wiki.libsdl.org/SDL3/SDL_ClearComposition and
https://wiki.libsdl.org/SDL3/SDL_EventType . The earlier no-manifest-change status
describes production checkpoint53e4bfaa; this integrator-authorized final fragment
must be applied identically to fixture baseline and candidate qualification.
