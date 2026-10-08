# CX-UIA-22: approved UI2 macOS provider

Packet: CX-UIA-22. Branch: `codex/ui2-macos-provider`.
Owner: Codex under the integrator's D29 assignment.
Base: `db269d6cbd9ede0c4f3e06406bdc17cb14928248`.
Exact owned provider/probe/driver paths are reserved in WORKSTREAMS.md §3.3.2.

The approved `ui2-approved.md` record governs the 53 operations, common-mode
source/timers, bounded worker publication, control events, revisions, cancellable
close and lifetime rules. No redesign, portable interface changes or compiler
work belongs to this packet. UI2 lands atomically with the Linux provider and
portable interface; incomplete providers are not shippable stubs.

## Recovered dependencies

Reused original source commits a809416b, 55b2dc52 and d44fad90 as 058dba01,
b29c2099 and 6fc9fc54. The only cherry-pick conflict restored the absent
CX-UIA-21 report. All portable interfaces/facade, BackgroundJobExecutor,
BackgroundJobs README, native fault fixtures, portable UI2 fixtures and
BackgroundJobs driver compare byte-identical with preserved ca4782e1.
This includes sticky cancellation and explicit native retry, qualified by the
prior 26 paired/sanitized BackgroundJobs cases, as recorded in its report.
No previous qualification is claimed for new provider behavior.
The ca4782 catalog amendment remains integration-owned and is not duplicated
here. Binding data will be an explicit final fragment; generated output is
reserved for the integrator. Current button-alignment and lifecycle repairs
come from the db269d6c base and must remain intact.

## Source baseline and proof plan

Current MacOSRunLoopSignal wakes via main-thread-only NSNotificationQueue in
default mode. MacOSApplication posts one performBlock per work item and uses
default-mode timers. They cannot implement approved worker-safe common-mode
publication. MacOSTextField.text calls validateEditing, so a getter can affect
editing; setText compares live draft rather than accepted baseline. Existing
providers lack the frozen UI2 methods. These are inspected source gaps, not
executed native red results.

Add meaningful fixture-only checkpoints using real provider entry paths before
each implementation owner. Native acceptance requires both frontends, plain and
ASan/UBSan, portable shared oracles plus real macOS probes, actual active/key
context for keyboard rows, zero-owned cleanup and unchanged approved E40 limits.
The observed loginwindow foreground currently prevents local GUI qualification.
No unlock, permission or system-settings change is requested.

Inspection/recovery began 2026-10-08 at approximately 01:44 UTC. Source/static
work proceeds while Linux owns the native lane; no compiler/native/GUI execution
has run for this packet. Execution and wait intervals will be recorded when the
integrator allocates qualification. Implementation and all new evidence pending.

## Fixture-only worker wake checkpoint

`RunLoopWake.btrc` uses the existing MacOSRunLoopSignal API from a real spawned
worker, then enters the real default or tracking CF run-loop mode with no polling
timer. It requires one UI-thread callback in each mode and no callback after
scope cancellation. The probe installs no source or common-mode membership on
the provider's behalf. The dedicated native driver selects both frontends and
plain/sanitized builds through existing fixtures, records stdout/stderr and uses
the common AppKit execution marker. Ruff and canonical BTRC formatting passed.
This checkpoint is deliberately before provider edits. Native red has **not**
run: the Linux qualification owns the lane. The expected baseline failure is
current wake() rejecting the worker thread; execution must confirm it when the
integrator grants a slot. No native or E04 pass is claimed.

The driver was renamed to `test_native_ui_core_macos.py` after verifying the
canonical `test_native_ui_*.py` discovery at Makefile:344. This is a fixture-only
follow-up to e968c459, whose original red candidate remains retained. The
`macos_gui` marker is present; the integrator owns adding the final execution
function inventory at atomic landing. No Makefile exception is needed.

A second fixture-only checkpoint adds `RunLoopDeadline.btrc`: one monotonic
deadline must wake each real native mode, never early or inline; replacement,
disarming and close must suppress superseded callbacks. It shares the actual
native driver and probe. This extends the internal signal with the deadline
contract the provider needs, without adding portable operations. The old owner
has no deadline API, so semantic compilation is expected to fail until the
implementation and native binding fragment are present. Native red is pending.

## Shared private semantic dependency

The integrator assigned `GUI/ControlEventQueue.btrc` to the Linux/shared owner.
Its exact cd5530af bytes are reused here without modification. It supplies typed
channels, reserved terminal tickets, ordered replacement barriers, retirement
and channel migration between a detached queue and window queues. The macOS
provider owns native capture, wake, budgets and lifecycle admission only. This
dependency has source/static review only; generic instantiation and behavior
remain unqualified until the shared fixtures execute.
