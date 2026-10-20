# UI2 acceptance fixtures

The mappings below describe source wiring. Focused results apply only to the
named revision and scenarios; full provider qualification remains pending.
Both frontends and plain/ASan+UBSan variants are required;
real input, injected input, host suspension and physical-device evidence retain
separate dispositions under `docs/design/ui-contracts/ui2-approved.md`.

`ControlEvents.btrc`, `Lifecycle.btrc` and
`UI2ExecutorChecks.publications` in `Executor.btrc` require `IUI2Probe`. No
provider implements that interface or calls these helpers on this revision.
Their assertions describe intended portable checks; their presence does not
establish execution. `FacadeHost.btrc` is also uncalled. The provider fixtures
below execute their own concrete equivalents, with the remaining gaps stated
explicitly. `UI2ExecutorChecks.hosted` does not require `IUI2Probe` and is called
by `UI2LinuxExecutor.btrc`.

## Shared owners

| Fixture | Driver and scope |
| --- | --- |
| `ControlEventQueue.btrc`, `ControlEventHeld.btrc`, `ControlEventCapture.btrc`, `ControlEventChannelCapture.btrc` | `src/tests/python/test_native_ui_control_queue.py`: queue ordering, held receipts, capture credits, typed channels and atomic route preflight |
| `SliderValue.btrc`, `SliderInteraction.btrc` | Same driver: validated double range, snapping, owning snapshots, preview/terminal identity, cancellation, model replacement and pressure |
| `Publisher.btrc`, `PublisherChecks.btrc` | Same driver: receipt identity, ordered replacement, retirement, cancellation, host exceptions and injected wake rejection; `PublisherChecks` is also called by the macOS publisher and Linux executor probes |
| `CompletionReadyRetry.btrc` | `src/tests/python/test_background_jobs_runtime.py::test_completion_ready_explicit_retry`: injected trylock failure, poll without retry and explicit retry to COMPLETE |
| `BackgroundCompletionReady.btrc` | `src/tests/python/test_background_jobs_runtime.py::test_completion_ready_subscription`: actual worker wake, cancellation, late subscription, partial drain and stale-token isolation |

Shared-owner passes cannot replace provider input, native resource or application
composition checks.

## Provider equivalents

macOS fixture stems below name files under `probes/macos/`; Linux stems name
files under `probes/linux/`. Drivers live in `src/tests/python/`. Native `.m` or
`.c` helpers beside a BTRC fixture supply its SDK calls and observations.

| Case / portable intent | macOS fixture and driver | Linux fixture and driver | Qualification still required |
| --- | --- | --- | --- |
| E01 text draft/commit/cancel (`UI2ControlChecks.text`) | `UI2MacOSTextField` via `test_native_ui2_macos_controls.py::test_macos_ui2_controls`; `UI2MacOSTextCapture` via `test_native_ui2_macos_text_capture.py::test_macos_ui2_text_capture` | Text lifecycle/composition-order checks in `UI2LinuxControls` via `test_native_ui_core_linux.py::test_linux_ui2_executor_and_lifecycle`; `UI2LinuxCapture` via `test_native_ui2_capture_linux.py::test_linux_capture_admission` | Actual IME/device and hosted active/key-window input evidence; Linux undo/IME/accessibility gaps remain carried |
| E02 keyed selection (`UI2ControlChecks.selection`) | `UI2MacOSSelect` via the macOS controls driver; `UI2MacOSSelectCapture` via `test_native_ui2_macos_select_capture.py::test_macos_select_capture` | Selection checks in `UI2LinuxControls` via the Linux core driver | Full popup journeys, Escape/native tracking and platform accessibility dispositions; callback injection is not physical interaction evidence |
| E03 slider preview/terminal (`UI2ControlChecks.slider`) | `UI2MacOSSlider` via the macOS controls driver, including SDK accessibility methods and provider-owned drag/key routes | `UI2LinuxSlider` via the Linux core driver | Full hosted interaction and assistive qualification; UI2 does not require native `NSSliderCell` tracking |
| E04 worker publication | `UI2MacOSSignal`, `UI2MacOSPublisher`, `UI2MacOSExecutor`, `UI2MacOSApplicationPublisher` via `test_native_ui_core_macos.py::test_macos_ui2_scoped_worker_signal` | `UI2LinuxExecutor` via the Linux core driver | Complete failure/destruction matrix and sustained fairness |
| E29 mutation (`UI2LifecycleChecks.mutation`) | `UI2MacOSContainer`, `UI2MacOSDetachFault`, `UI2MacOSViewOrder` via the macOS core driver | `UI2LinuxLifecycle` via the Linux core driver; `UI2LinuxCapture` via the capture driver | Full 100-cycle fault/resource qualification and focused-editor/pending-image combinations |
| E30 host suspension (`UI2ExecutorChecks.hosted`) | `UI2MacOSExecutor`, `UI2MacOSApplicationHost` via the macOS core driver | `UI2LinuxExecutor` calls the shared `hosted` helper through the Linux core driver | 100-cycle acceptance extension; injected host transitions do not establish OS suspension, wall-clock behavior or durable restoration |
| E31 teardown (`UI2LifecycleChecks.teardown`) | `UI2MacOSHostFailure`, `UI2MacOSButtonCloseFailure`, `UI2MacOSNativeSettlement`, executor and container probes via the macOS core driver | `UI2LinuxHostFailure`, `UI2LinuxLifecycle`, executor probes via the Linux core driver | Fatal off-executor final release and full 100-cycle resource assertions, as described below |
| E35 retained image (`UI2LifecycleChecks.retainedImage`) | `UI2MacOSImages` via `test_native_ui2_images.py` | `UI2LinuxImages` via the same driver | Complete image/rendering E-case; owner tests cover publication/close races, including a separate TSan variant |
| E39 eligibility and two-axis scroll (`UI2LifecycleChecks.scroll`) | `UI2MacOSViewState`, `UI2MacOSViewInput` via the macOS core driver; `UI2MacOSScroll` via `test_native_ui_scroll_macos.py` | `UI2LinuxLifecycle`, `UI2LinuxControls`, `UI2LinuxCapture` via their drivers above | Full native visibility/input and platform-specific scrolling journeys |
| E42 window state | `UI2MacOSWindow` via `test_native_ui_window_macos.py::test_macos_ui2_window`; `UI2MacOSViewState` via the core driver | `UI2LinuxLifecycle`, `UI2LinuxControls` via the Linux core driver | 100 hide/minimize/occlude/recreate cycles and presentation evidence |
| E46 reversible close (`UI2LifecycleChecks.closeTransaction`) | `UI2MacOSWindow` via the window driver; `UI2MacOSApplicationQuit` via the macOS core driver | `UI2LinuxWindowClose`, `UI2LinuxWindowQuit` via the Linux core driver | Full 100-cycle two-window/resource matrix and hosted dirty-dismissal journey |

The acceptance extension repeats 100 fresh cycles for macOS container,
executor, application-host, window and application-quit scenarios, and Linux
lifecycle, executor, window-close and window-quit scenarios. At `77043828`,
all 28 macOS variants passed: those five scenarios plus open and closed
worker-final-release probes, each through both frontends, plain and sanitized.
The application-host scenario repeats the public CANCEL/DEFER/REPLACE journey.
These focused results do not establish physical input or complete E-case
acceptance. Linux extension qualification remains pending.

### Final release and native resources

`UI2MacOSFinalRelease` and `UI2MacOSClosedRelease` use the macOS core driver.
Both require process failure with the approved diagnostic
`Callback scope destruction requires its creating thread`
(`docs/design/ui-contracts/ui2-approved.md:827`;
`docs/design/ui-contracts/reviews/ui2/parity.md:233–237`). Cancellation does not
remove that affinity: a component retaining a fully cancelled scope still
aborts when its final reference is released on a worker. The positive control
closes, drains and releases the owner on the UI thread.

`UI2LinuxFinalRelease` uses
`test_native_ui_core_linux.py::test_linux_ui2_final_release_requires_executor`.
An open real `LinuxApplication` must abort with
`Native application destroyed before subtree cleanup completed` when its last
reference is released by a worker. A closed application without a callback
scope may be released there. `UI2LinuxAffineRelease`, through
`test_linux_ui2_callback_scope_release_requires_executor` in the same driver,
separately checks the callback-scope rule. A caught destructor exception does
not satisfy a required fatal outcome.

`UI2LinuxResourceLifetime`, through
`test_native_ui2_linux_resource_lifetime.py::test_linux_ui2_native_resource_lifetime`,
observes executable-origin SDL and WebGPU claims over 100 fresh windows. Each
cycle renders text, labels, images and buttons and creates both lazy cursors.
All 19 resource classes must have positive acquisitions, balanced creates plus
retains versus releases, and zero live claims at window COMPLETE, while closed
aliases remain retained and before application close or `SDL_Quit`. The driver
requires 1,900 ordered records for each frontend/sanitizer variant. Backend
internal references are outside this census. Runtime qualification is pending.

## E40 boundary, load and tracking

`test_native_ui2_macos_e40.py` runs the macOS boundary, 600-second load and
popup/provider-owned slider/live-resize/sheet trials in desktop and attached-host
modes. Its compile-only cases do not execute those trials. Runtime qualification
requires the explicit hosted opt-in and must not run as visible local GUI work.

`test_native_ui2_fairness_linux.py` runs Linux repeated boundary bursts and the
600-second workload; `test_native_ui_linux_spike.py` retains the focused input
boundary and repair regressions. The old UI1 4097th-event loss remains historical
reproduction evidence. Neither the uncalled portable publication helper nor a
source compile establishes that the current E40 matrix passes.

E40 requires 100 bursts per size/final disposition, exact receipt accounting and
real native progress during the applicable tracking intervals. Plain builds
retain command p95 ≤100 ms, class service gaps ≤250 ms and close start ≤250 ms;
sanitized builds retain the specified count/loss checks and latency exemption.
Accepted semantic commands and native input progress are separate records.

The macOS signal probe uses default and added common run-loop modes, tests idle
worker wake and 100 worker/close races. The publisher probe delivers 4,097 ordered
publications and tests 100 producer/cancellation races. These cover source and
publisher ownership; they do not substitute for the E40 workload or actual
AppKit tracking trials.
