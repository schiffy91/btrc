# UI2 portable acceptance fixtures

These fixtures exercise the approved `ui2-approved.md` interface. They have no
platform provider implementation and establish no native pass by themselves.
CX-UIA-22/23 supply `IUI2Probe` using their real AppKit/SDL entry paths and admit
these checks through their native pytest drivers. Run both frontends, plain and
ASan/UBSan; label injected native input and host suspension as stand-in evidence.

| Fixture | Assertions | Required driver additions |
| --- | --- | --- |
| `ControlEvents.btrc` | E01 draft/commit/model replacement; E02 keyed duplicate/reorder; E03 preview/terminal/snap; E39 eligibility | Real composition/undo, popup and drag interruption, assistive paths, ordered receipts including ineligible disposition |
| `Lifecycle.btrc` | E29 stable move/stale revision; E31 alias teardown; E35 retained image/closed alias; E39 detach; E46 stale save/cancel/no-handler; two-axis scroll | Native mutation rollback/quarantine, resource/drain counts and fatal off-executor case; two-window native close/quit; native image publication/close race |
| `Executor.btrc` | E04/E40 ordered publication bursts 4095/4096/4097/8193; E30 cancel/defer/replace in injected host suspension | Real worker producer/publisher lifetime; native input/rendering fairness, bounded service gaps and close start; tracking/modal trials and declared monotonic clock |
| `FacadeHost.btrc` | Real-provider host cancellation clears the facade slot, permits reinitialization and rejects a duplicate host | AppKit/SDL host fixture drivers |
| `BackgroundCompletionReady.btrc` | Actual worker wake/owner cancellation barrier; late subscription; level readiness across partial drain; stale token isolation; close | Admitted by `test_background_jobs_runtime.py::test_completion_ready_subscription`, paired frontends and plain/sanitized builds |

`UI2Events` retains owning snapshots so assertions run after dispatch.
`IUI2Probe.drain()` advances bounded turns outside an application callback;
implementations must not start a nested loop. Platform drivers choose real native
stimuli, collect receipt traces and instrument resource lifetimes. They must not
replace a driver addition in this table with a declaration-only or mock pass.

E40 plain-build latency retains p95 ≤100 ms, class service gaps ≤250 ms and
close start ≤250 ms. Sanitized executions check counts/losses. These helpers
supply shared oracles; their portable subset does not close an entire E-case.
Linux undo, actual IME, accessibility, unavailable window-manager cases and other
carried gaps stay open under the approved record. The host fixture injects
suspension; it does not assert the OS suspended the process.
