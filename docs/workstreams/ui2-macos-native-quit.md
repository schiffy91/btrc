# Native application quit across windows

D29 integrator-authorized continuation from Application report commit
`683571b2bdd04ca6a286dc7a94a7a9a9403684f4`, on preserved packet branch
`codex/ui2-macos-native-quit`. This checkpoint records contract and test design
only. No executable provider, fixture, compiler or native source changes have
been made, and no new native result is claimed.

## Baseline and intended behavior

The original rich attached-host Application fixture passes all four current-f75
plain/sanitized frontend cells. Aggregate
`b9c1d2dc59beae175500f2674cb14937412cdbbbbf4853c25b985042af9c742f`
and the previous failures remain in the Application packet report. Standalone
run and native group quit were explicitly excluded from that proof.

Current `MacOSApplication.applicationShouldTerminate` calls irreversible
`requestQuit` immediately. `MacOSWindow.requestClose` always creates an
uncoordinated transaction, although the existing transaction already supports
holding AUTHORIZED when coordinated. These are source findings, not a newly
executed native baseline. The new baseline must reach actual `[NSApp terminate:]`
with two live dirty windows and classify the resulting missing-decision/early
shutdown predicate; projection/setup failure is not that native RED.

The desired native-quit path retains all windows and normal ingress until every
window has authorized its current owner-reported revision. One cancellation
leaves the live windows and their drafts usable, including clean windows. Direct
`requestQuit` and forced teardown remain irreversible. Saved data can remain
saved after group cancellation; pending discard never destroys a draft early.

## Recorded contract clarification

The integrator approved the D29 clarification in `ui2-approved.md`, lifecycle
review decision 1, following the document-owner revision authority and native
group rules. The existing `decide` API serves held coordinated AUTHORIZED:
nonstale CANCEL cancels the group, strictly newer SAVE revokes authority and
starts a fresh attempt, and strictly newer DISCARD authorizes that revision.
Unchanged SAVE/DISCARD remains a programmer error; no automatic re-prompt is
introduced. Stale revisions/attempts and resolved-transaction rules remain.
The document owner must report newer revisions before returning to the UI
executor. The provider cannot discover unreported document edits from widgets.

New windows and handler changes invalidate the affected group snapshot. A
cancelled handler cancels the group. No-handler windows are held, which is the
explicit group exception to ordinary `requestClose` without a handler.
Before irreversible commit, membership, handler/transaction identity and
reported revisions are revalidated without intervening callbacks or event
pumping. Retained group references protect this segment from user destructors.

## Existing owner boundaries

- Application owns native quit readiness, group membership and the decision to
  enter irreversible shutdown. Native callback capture only coalesces readiness
  and returns `NSTerminateCancel`; decision delivery uses the existing executor.
- Window owns its registration and existing close transaction, including the
  document revision, save attempt, held authorization and terminal retirement.
  Provider-private begin/validate/consume/cancel helpers may expose those facts
  to Application; they do not create a second transaction or public API.
- Existing context guards, semantic channels, terminal reservations and wake
  owner remain authoritative. No global dispatch during cancellation, nested
  event pump, receiver invocation inside native capture, or parallel queue.
- Repeated native requests reuse a pending group. An already-pending window
  transaction must be reconciled by identity without duplicate prompt or save.
  A failed admission cannot leave partially published group responsibility.
- Group commit validates before any native teardown. Consuming authority changes
  owned transaction state only; retain window, transaction and registration/
  receiver references through irreversible ingress sealing. Releasing the last
  user handler reference could execute a destructor, so that release belongs
  after sealing. No callback or destructor may change membership/revision in
  the validate-to-commit segment. Native teardown follows the existing close
  owner and may report failure; it cannot roll back destroyed windows.
- Cancellation retires group transactions without sealing normal work or
  publishers. Direct quit or host-forced owner loss invalidates pending group
  authority and retains the existing teardown semantics.

## Original lifecycle scenarios retained

The existing `NativeApplication` driver has these 12 subprocess scenarios, each
with its original 30-second outer bound. Setup must be reconciled with UI2;
the behavioral responsibilities are retained rather than waived.

| Scenario | Retained oracle |
| --- | --- |
| native | Actual NSApplication termination; native callback returns before owned subtree teardown; receiver destruction counted. |
| portable | Direct requestQuit seals admission and defers subtree teardown until callback unwind. |
| before-run | Quit seals creation; all pending child ownership eventually drains; late run rejects. |
| scheduled | Exactly 2048 admitted work deliveries and corresponding destructions. |
| cancelled-work | Capacity four rejects the fifth work item; rejected and abandoned receivers release exactly once; no abandoned delivery. |
| failed-work | Nonempty work error survives orderly teardown and reaches the caller. |
| native-pending | Two additional queued work items are abandoned without delivery and released exactly once after actual native quit. |
| empty-failure | Empty-string work error remains failure rather than being mistaken for success. |
| modal-native | Actual nested modal loop aborts on native quit; parent/child stay retained until outer callback returns. |
| modal-portable | Same real modal/retention boundary through direct requestQuit. |
| scope-exit | Surviving child alias is closed and native delegate ownership is released. |
| stuck-subtree | Bounded pending-shutdown diagnostic retains owners, then explicit completion/retry closes them. |

Keep terminal root-null/native live-view counts, callback-scope completion,
idempotent quit/close and late run/creation rejection. Preserve actual native
objects and original counts; do not substitute a fake application/window.

Five explicit setup/contract migrations are necessary before that old fixture
can qualify this source:

1. Constructor leaves the native delegate untouched. Move occupied-slot
   rejection to supported scoped run admission; assert the foreign delegate is
   unchanged and rejected admission leaves the application open.
2. Removed production `IAppKitDelayedWork` is not restored for test convenience.
   Ordinary turns use `IApplicationWork`; a test-owned typed timer receiver and
   existing scoped native callback binding preserve the actual modal-timer
   trial. No private callback is invoked directly.
3. Probe views and roots share the application's context. Use application
   factories and the existing native view owner's context for native-count
   probes. The stuck-view test forwards the current interface to that same
   owner; it does not introduce another runtime ownership model.
4. Close from an entered callback reports PENDING rather than the old throw
   expectation, and no owned resource may be released before unwind. The
   now-qualified attached-host callback cases are retained as regressions.
5. Current run rejects after requestQuit has sealed admission. Before-run and
   cancelled-work retain admission/release/teardown assertions through explicit
   close/pollClose; they must not require entering a loop on a closing owner.
   This deliberate lifecycle change is recorded rather than hidden by deleting
   those scenarios. Legitimate PENDING remains bounded, not accepted as success.

## Native proof sequence

The first new fixture calls actual `[NSApp terminate:]` through the native
binding/probe while the provider-internal host runs. It must prove native entry
before classifying an expected baseline failure. Capture source and native
predicate identity; do not accept a generic abort or missing success marker.

1. Two dirty windows: first holds DISCARD authorization; second CANCELS. Both
   drafts/roots remain open; queued normal work and publisher delivery survive.
   A repeated terminate reuses the same pending transactions and save attempts.
2. Saving and stale completion: a newer owner-reported revision during SAVE
   makes the older completion stale; a new explicit attempt is required. A
   failed save returns to decision; retry gets a fresh positive attempt.
3. Held authorization revision change: while another window waits, report a
   newer revision via SAVE or DISCARD and prove the older authority cannot
   close it. Nonstale CANCEL works while held; unchanged SAVE/DISCARD throws
   without another prompt; lower revisions and wrong attempts remain stale.
4. Membership/handler changes: a new window is included before commit, a newly
   dirty clean window loses its no-handler readiness, and cancelled handler
   cancels the group. A clean window must not close before a dirty peer cancels.
5. All authorized: final revalidation consumes each authorization once and only
   then seals ingress/closes. Late completions cannot revive the transaction.
   A handler finalizer attempting application mutation observes already-sealed
   ingress; it must not run within validation/consumption. Retained references
   and source ordering complement the real native assertion.
6. Preserve direct requestQuit as irreversible, and host-forced owner loss as
   non-vetoable. No claim that failed teardown restores destroyed native state.

Initial fixture-only native RED must precede production acceptance. If the
standalone path fails setup first, retain that result and repair its actual
owner separately; do not relabel it as group-quit evidence. Candidate proof
requires original bounds/strict flags, both compiler frontends and plain/
ASan+UBSan execution, followed by the unchanged attached-host four-cell
regression. Foreground-dependent Select/Range/Scroll controls remain separate;
no activation, timeout or assertion workaround is part of this packet.
