# UIKit native-shell design note, including iPadOS

**Status:** CX-UIA-13, docs-only proposal for `ui-1-ios-shell`; no UIKit build,
simulator run or device evidence. Baseline `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
Implementation belongs to [CX-UIA-16](../../workstreams/codex.md#cx-uia-16).
Review against the real shell before CL-UIA-22 confirms UI2/UI3 feasibility.

Use the reviewed [native ownership design](../native-interop-ownership.md),
especially Objective-C steps 3 and 6, and the
[Stage 24 target contract](../platform-target-contract.md). They are design
authorities, not evidence their planned compiler features already exist.

## One provider, OS-owned entry

D24 names the directory `src/stdlib/GUI/IOS/`. iOS and iPadOS share it and
`App/IOS`; there is one `ios` ledger family. Reuse Stage 29's application/scene
lifecycle owner (CX-P2-36), not a second UIApplication or product-state store.

`UIApplicationMain` owns the process loop. A process-scoped instantiated app
delegate supplies application services; an instance-scoped scene delegate
owns each scene session/window and its generation. The GUI layer attaches to
that host. It must not call a second `GUI.run` loop from a scene callback or
emulate synchronous exit by polling. Worker publication wakes the main run
loop through the approved executor, and semantic receivers run there after
native callbacks return. Any GUI.run compatibility entry is decided in UI2;
it cannot silently turn an already-running UIKit app into a nested loop.

Scene disconnect terminates that scene delegate's checked holder. Reconnection
creates a fresh instance/generation using durable value state; it must not
resurrect the terminated native object. The application delegate's declared
process root is separate from per-scene leak counts. Suspension may prevent
further callbacks; persist restorable state before it is needed and never
depend on a final Save/close callback after process termination.

## Controls, geometry and the GPU child

| Portable owner | Native route | Required shell assertion |
| --- | --- | --- |
| IWindow/scene | UIWindow owned by the specific UIWindowScene | Input/completions reach the right scene; closing one leaves the other valid |
| ITextField / IButton | UITextField / UIButton with checked delegate/target-action bindings | Native selection/composition, exactly one semantic action, no setter actions |
| IScrollView | UIScrollView and a bounded document container | Safe-area/inset-aware scrolling; native/GPU coordinates stay aligned |
| IGPUView | Checked UIView subclass whose layerClass is CAMetalLayer | WebGPU frame beneath overlapping native controls, clipping and hit testing |

Step 6 generates the UIView subclass and enforces required super calls and
designated initialization; the GUI provider must not inject an unchecked
Objective-C class implementation. Retain the layer through the GPU surface
owner and update its pixel extent/scale from layout. No drawable means defer
presentation while retaining latest model state, not destroy the editor or
spin a timer. Stage 29's GPU owner (CX-P2-39) owns device/simulator Metal and
surface recovery. UI9 later supplies full display pacing and recovery proof.

Native editor storage and UTF-16 ranges stay on UIKit's side until copied to
owned portable values. UI3 owns composition/key precedence and input conversion;
UI2 draft/change/commit/cancel semantics cannot be inferred from raw touch-up
alone. Scene deactivation, occlusion and interaction ineligibility are distinct.
The shell reports observed state; it does not infer that every hidden view has
lost its draft or that suspension shuts down shared audio services.

## Checked ownership map

| Need | Ownership design step | Required capability |
| --- | --- | --- |
| Protocol conformance, weak/assign delegates, target/action and main-thread checks | Step 3 | Reader-derived protocol/property facts; CallbackScope owns a retained token/holder, clears delegate slot before releasing it |
| UIApplication/scene delegates instantiated by class name | Step 6 | `lifetime = instantiated`, process/instance scope, declared terminal callback, one external ARC claim per holder |
| CAMetalLayer-hosting UIView | Step 6 | Checked superclass/overrides, layerClass, layoutSubviews and required super sends |
| Release during a callback or on an SDK thread | Shared R3 pin and main release executor | Keep receiver/holder alive through callback return; marshal final claim release to main; no custom ARC path |

Cancellation is explicit: close admission, unregister/clear native slots, drain
admitted callbacks, release scene-owned views/surfaces on main. An independently
owned scope breaks foreign-held cycles; a receiver destructor is insufficient.
Construction failure unwinds unpublished controls and bindings. A late callback
from a terminated scene cannot target a new scene with a recycled native address.

## iPadOS requirements within the ios lane

Declare `UIDeviceFamily [1,2]` in the test-host application's Info.plist; do not
create a separate iPad provider or silently run only an iPhone destination.
UIWindowScene/scene-session support is a capability of the host app and OS
configuration, not an assumption that all UIKit applications permit two scenes.

| iPad dimension | Scenario and affected ios slots |
| --- | --- |
| Independent scenes | E16/N01/N02/N07: edit two scenes, switch activation, close one with pending work; check owner identity and surviving service state. If only one scene is configured, record the explicit adaptation rather than a pass for two scenes. |
| Size classes, Split View and Stage Manager | E20/E26/E27/E42: resize across compact/regular and split layouts, move/resize GPU/native children and inspect safe areas and coordinate conversions. Record OS/model availability; a simulator without Stage Manager cannot establish that path. |
| Software and hardware keyboards | E01/E07/E18/E25: IME preedit, Done/Return, key-command precedence, keyboard occlusion and disconnect/reconnect; keep the focused draft/actions reachable. |
| Pointer and trackpad | E03/E05/E22/E27/E39: hover, capture/drag interruption, focus, scroll and native/GPU hit testing. Touch-only automation does not prove pointer behavior. |
| Restoration and dismissal | E17/E30/E46/E47: scene reconnection and fresh-process checkpoint restore, dirty departure and external activation; no replayed side-effecting commands. |

All these records use `platform = ios` with distinct
`provenance.device_class` for iPhone versus iPad and exact destination/model/OS
metadata. A case requiring both classes is not qualified by one destination.
This expands evidence for existing slots, not the frozen family denominator.
Full adaptive layout, accessibility and restoration remain UI5/UI8/UI10 work;
the shell fixture establishes their native boundary only.

## Targets, hosts and probes

Use the target rows `ios-aarch64` (`iphoneos`, deployment floor 17.0) and
`ios-aarch64-simulator` (`iphonesimulator`, floor 17.0). Their environment, SDK
identity and cache keys differ even on the same arm64 host. Do not use a macOS
artifact for simulator proof or infer target identity from `uname`. Stage 24's
filters must prevent UIKit imports in desktop/Linux builds.

`docs/design/native-ui-catalog/hosts.toml` does not yet exist at this baseline.
CX-UIA-06 (`ui-0-host-matrix`) supplies separate iPhone/iPad simulator rows for
the same ios family, per frontend/evidence class. Planned hosts are the owner's
Mac after `tooling-ios-simulator-runtimes` (MAC-P1-02), and the GitHub macOS
simulator stand-in via Stage 25 `platforms-p1-host-ios` (CX-P1-04 spike then
CX-P1-08, `host-ios.yml` provider-suite). A normal macos.yml scope job is not an
iOS run. Xcode 27's ability to install an iOS 17 runtime remains an explicit
host-spike question; absence must not be relabelled a successful minimum-OS run.

Probe through XCUITest against native UIAccessibility: stable identifiers,
labels/traits, editable values, enabled/focus state and native/GPU bounds.
Tree inspection and an automation tap do not prove VoiceOver or hardware IME.
Record those separately; physical devices remain awaiting hardware under D8
and `tooling-ios-physical-devices`.

The future shell suite runs each frontend on both destination classes and
performs 100 scene connect/disconnect cycles, including close from a callback,
pending worker delivery and GPU resize. Count per-scene native owners, callback
registrations, surface leases and stale-generation deliveries; the declared
process root is explicit and unchanged. Upload accessibility snapshots, event
trace, frame/composition capture and final lifetime counts. No leak-free result
is inferred merely from an app that stays alive.

## Dependency checklist and requests

| Required before CX-UIA-16 | PLAN item / packet |
| --- | --- |
| Target/ABI/SDK and safe provider selection/cache | `platforms-p1-target-spec` (CL-P1-06), `platforms-p1-hosted-abi-targets`, `platforms-p1-native-import-targets`, `platforms-p1-native-plan-toolchain`, `platforms-p1-provider-filters` (CL-P1-14), `platforms-p1-cache-identity` (CL-P1-15) |
| Simulator runtime and executable host | `tooling-ios-simulator-runtimes` (MAC-P1-02), `platforms-p1-host-ios` (CX-P1-04/08) |
| UIKit protocols and instantiated classes | `platforms-i1-objc-protocol-adapters` (CL-P2-21; steps 3 and 6) |
| Shared lifecycle and main executor | `platforms-i1-app-lifecycle` (CX-P2-36), lifecycle-shape review CL-P2-22 under that item |
| Layer-backed WebGPU | `platforms-i2-gpu` (CX-P2-39), shared archives under `tooling-cross-gpu-deps` |
| Shared fixture and approved interface | `ui-1-shell-fixture` (CX-UIA-09), `ui-2-contract-review` / `ui-3-contract-input` for landed contracts |

CL-P2-21 is the targeted request owner if a class-name-created delegate or
UIView override lacks a checked lifetime route; CL-P1-14/15 own target/filter
gaps. These are assigned prerequisites, not reproduced compiler defects. No
private UIKit bridge is authorized as a workaround. Feasibility/parity review,
real shell results and new-platform contract reconciliation remain pending.
