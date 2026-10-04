# Win32 native-shell design note

**Status:** CX-UIA-13, docs-only proposal for `ui-1-windows-shell`; no native
implementation or execution evidence. Baseline `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
The provider packet is [CX-UIA-15](../../workstreams/codex.md#cx-uia-15).
Review this note in the UI1 feasibility/parity review and reconcile the UI2/UI3
surface through CL-UIA-22 when the real shell exists.

The [foreign interop ownership design](../native-interop-ownership.md) is the
reviewed Stage 27 design, not a claim that its steps are implemented. Its
R1/R2/R3 relationships, checked executors, callback entry pins and cancellation
rules govern this provider. The [target contract](../platform-target-contract.md)
is the Stage 24 design; use its implemented generated target rows when available.

## Provider and host boundary

Create `src/stdlib/GUI/Windows/` only after the assigned prerequisites land.
Keep the portable `GUI/I*.btrc` interfaces and GUI facade unchanged in that
packet; consume approved UI2/UI3 contracts or their reviewed typed-unsupported
outcomes. Win32 is the proposed shell route, not a decision to introduce WinUI
or a second widget abstraction.

The application owns one UI thread and its Win32 message loop. Wait through
`MsgWaitForMultipleObjectsEx` for the worker wake signal and message input,
then service bounded batches of messages/work, timers and presentation. Use
the appropriate wake mask/flags so previously observed queued input is not
stranded. Never empty the native queue into a fixed array that silently drops
the remainder. WM_QUIT is a terminal loop result, not a window command to lose
between batches. This implements D24's host-owned-loop model using the UI2
executor contract rather than a self-reposting polling task.

WndProc makes synchronous OS decisions, snapshots owned event data and queues
semantic delivery after dispatch. WM_CLOSE enters the approved close-request
transaction; it does not immediately destroy a dirty owner. DestroyWindow and
WM_NCDESTROY end native lifetime after close admission and callback drain.
Multiple HWNDs retain independent owner generations; one window closing must
not quit shared services while another survives (E16).

## Native content and GPU child

| Portable owner | Proposed native route | Shell proof |
| --- | --- | --- |
| IWindow | Top-level HWND, per-monitor DPI awareness v2 established before creating windows | Move/resize/scale, activation and independent close; logical-to-device bounds recorded |
| ITextField / IButton | Unicode EDIT/BUTTON controls with a ComCtl32 v6 activation context/manifest | Native focus and editing; one queued button action; setter-generated notifications suppressed |
| IScrollView | Owned viewport/content HWND hierarchy with two-axis offsets | Child clipping and input coordinates after scroll and DPI changes |
| IGPUView | Child HWND passed to the Windows WebGPU surface provider | Presented frame plus native editor/button overlap, hit testing and clipping |

The activation context belongs to the application construction owner and stays
valid through native control creation; failure unwinds it without publishing a
partial GUI owner. EDIT text remains native UTF-16 until copied/transcoded at
the checked boundary. IME composition is not reconstructed from key presses.
GPU availability and device/surface errors use the shared GPU owner; this
provider never adds private runtime calls to force a successful frame.

Child-HWND z-order/clipping, focus across native/GPU children and resize
reconfiguration require actual proof. A blank surface or screenshot without
input/accessibility assertions does not close UI1. Minimized/occluded/drawable
states stay distinct; WM_PAINT or a timer is not proof of physical presentation.

## Ownership and interop map

| Need | Existing design step and rule | Dependency |
| --- | --- | --- |
| WndProc/subclass entry and stored context | Step 2, checked callback-holder machinery and pinned entries. HWND is not a COM object or a copied vtable. Bind its context/terminal destruction explicitly; never cast an unowned btrc pointer into window user data. | `platforms-interop-function-table-calls` (CL-P2-06) |
| UI Automation client and future provider interfaces | Step 5, COM claims, checked lpVtbl dispatch, QueryInterface identity, HRESULT translation and apartment-bound release | `platforms-w1-win32-com-imports` (CL-P2-10) |
| Callback disposal during native dispatch | Shared R3 pin until outermost return; CallbackScope closes admission before unregister/drain. Late entries cannot reach a closed receiver. | Same Stage 27 function-table/COM items; E31 |
| GPU child and ABI | Checked native window borrow only while its surface lives; release surface before terminal HWND destruction | `tooling-cross-gpu-deps` (CX-P2-25, CL-P2-29) |

Destroy UI handles on their creating UI thread. CallbackScope cancellation is
explicit and independent of the receiver, since a native-held cycle is not
collectible. Do not block that thread waiting for its own callback. Construction
failure reverses ownership acquisition; pending drain remains observable.

## Targets, hosts and evidence

The target-contract rows are `windows-x86_64` (GNU, LLP64),
`windows-aarch64` (GNU, LLP64) and `windows-aarch64-msvc` for the GPU ABI route
that needs it. Linux cross-compilation uses the row's `zig_target` with pinned
zig 0.16. A GNU object/archive and an MSVC GPU archive cannot be assumed ABI/CRT
compatible; Stage 28 supplies the reviewed link route and digest per slice.
Cross-compilation alone proves no HWND, input or UI Automation behavior.

`docs/design/native-ui-catalog/hosts.toml` is absent at this baseline. Its owner,
CX-UIA-06 (`ui-0-host-matrix`), must supply the planned Windows x64 hosted row
and Windows ARM64 row (runner availability unverified), per frontend and
evidence class. Do not invent an existing host id. The Stage 25
`platforms-p1-host-windows` lane (CX-P1-07, `host-windows.yml` provider-suite)
runs this shell; a green scope-only `windows.yml` is not shell evidence.

Use a separate UI Automation probe process, scoped to the fixture HWND/PID,
through COM `IUIAutomation`. Record control type/name, native focus, enabled
state, bounds and Invoke/Value behavior without editor secrets. Keep apartment
claims and any event sinks on their declared executor; do not introduce a
free-threaded sink beyond the reviewed COM design. If the hosted session cannot
provide UIA or interactive input, report that evidence unavailable instead of
falling back to a mock tree. Narrator and physical display/input are unavailable
under D8 until their `tooling-windows-physical` owner packet.

Run both frontends with the shared `ui-1-shell-fixture`: 100 create/show/edit/
scroll/resize/close cycles, native/GPU composition, tree assertions and close
inside a callback. Track fixture HWNDs and `GetGuiResources` GDI/USER counts
against a warmed baseline; process-wide counts alone cannot identify ownership.
Require zero retained fixture handles/registrations after drain and explain
any process-global cache delta. Upload event trace, UIA tree, image, adapter
metadata and resource counters with run id, target and frontend. Timing on a
hosted display remains stand-in evidence.

## Dependency checklist and requests

| Required before CX-UIA-15 | PLAN item / packet |
| --- | --- |
| Target identity, ABI, SDK selection and safe provider imports | `platforms-p1-target-spec` (CL-P1-06), `platforms-p1-hosted-abi-targets`, `platforms-p1-native-import-targets`, `platforms-p1-native-plan-toolchain`, `platforms-p1-provider-filters` (CL-P1-14), `platforms-p1-cache-identity` (CL-P1-15); Stage 24 exit |
| Executable Windows provider-test host | `platforms-p1-host-windows` (CX-P1-07); ARM64 tooling is `tooling-windows-ci-arm64-llvm` (CX-P1-03) |
| Checked native callbacks and UIA | `platforms-interop-function-table-calls` (CL-P2-06), `platforms-w1-win32-com-imports` (CL-P2-10) |
| WebGPU archives and compatible link route | `tooling-cross-gpu-deps` (CX-P2-25, CL-P2-29), `platforms-w1-toolchain-abi-route` |
| Shared fixture and approved portable contracts | `ui-1-shell-fixture` (CX-UIA-09); `ui-2-contract-review` / `ui-3-contract-input` for whichever surface has landed |

Requested capabilities are already assigned, not newly discovered compiler
bugs: CL-P2-06 must provide the checked callback/entry-lifetime route; CL-P2-10
must provide UIA's COM shape and apartment cleanup; CL-P1-14/15 must prevent
foreign-provider imports/cache reuse. If a minimal real-shell repro shows a
gap, file the targeted REQUEST before adding any wrapper or unsafe bypass.
Feasibility review remains pending; this note does not claim all dependencies
are met or that the Win32 shell runs today.
