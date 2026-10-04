# Android Views native-shell design note

**Status:** CX-UIA-13, docs-only proposal for `ui-1-android-shell`; no APK build,
emulator run or physical-device result. Baseline `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
Implementation belongs to [CX-UIA-17](../../workstreams/codex.md#cx-uia-17).
Its real shell is needed for CL-UIA-22's UI2/UI3 re-check.

The reviewed [foreign ownership design](../native-interop-ownership.md), JNI
steps 4 and 7, is authoritative. The
[target contract](../platform-target-contract.md) supplies Stage 24 target
identity, ABI and sysroot rules. Both documents describe planned implementation;
neither makes the JNI/Activity shell available at this baseline.

## Provider, Java host and main loop

The provider directory is `src/stdlib/GUI/Android/`. Reuse the Stage 29
application/Activity lifecycle owner (CX-P2-41) and its main executor. The small
Java Activity host in `tools/android/shell/` owns Android entry points and view
attachment, not product policy, persistence or a second btrc object registry.
Views are the proposed route for this shell; replacing them with GameActivity
needs the assigned feasibility decision rather than an implicit shortcut.

Android owns Activity entry and the main Looper. A Handler/main-loop wakeup
dispatches bounded work through the UI2 executor, with generation and scope
cancellation checks. Never cache a `JNIEnv*` in a provider, worker or queued
event; Java's VM owner retrieves the environment on the actual calling thread.
Never start a second blocking GUI.run loop from `onCreate`, and never use
periodic polling to substitute for worker publication.

Every Activity instance has an independent generation. Recreation cancels
delivery into its old views, drains native/Java peers and reconstructs from
durable values. Saved state cannot retain Activity, View, Surface or callback
pointers. Process death may skip onDestroy entirely; restoration cannot depend
on terminal callbacks. Back, transient dismissal and dirty navigation use the
approved lifecycle transaction; `finish()` is not an unconditional dirty-close
handler. Activity visibility, interaction eligibility and GPU surface existence
remain separate states.

## Native views and surface composition

| Portable owner | Native route | Required shell assertion |
| --- | --- | --- |
| IWindow/scene | Activity content/root ViewGroup | Correct owner through pause/resume, recreation, keyboard insets and close |
| ITextField / IButton | EditText / Button | InputConnection composition distinct from hardware KeyEvent; setters do not dispatch user actions |
| Scrolling/collection boundary | Scroll container with RecyclerView where collection identity is needed | Stable ids, viewport clipping and actual scroll geometry; no claim that UI6 virtualization is already complete |
| IGPUView | SurfaceView with ANativeWindow/Vulkan WebGPU surface | Native controls overlap correctly; surface lifetime and input remain aligned |

SurfaceHolder callbacks create/change/destroy a surface generation independent
of the Activity generation. Retain/release the ANativeWindow through the shared
GPU owner (CX-P2-44); release the old WebGPU surface and leases on destruction,
then attach a new generation when available. A stale frame or callback cannot
use the previous ANativeWindow. Surface loss must not replace active editors or
shut down shared audio.

SurfaceView composition has its own layer/z-order behavior. Prove native
overlays, clipping while scrolling, resize and hit testing on the emulator;
do not infer them from the View hierarchy alone. Any route change needed for
correct clipping becomes a reviewed GPU/provider change. UI9 supplies full
Choreographer pacing, surface recovery and memory-pressure proof later.

Normalize dp/density, WindowInsets and IME occlusion into portable logical
geometry. A layout refresh preserves the native editor and its composing spans.
Java strings cross through the checked UTF-16/real-UTF-8 route, including NUL
and supplementary characters; modified UTF-8 and key-to-text reconstruction
are not accepted substitutes.

## Checked JNI and lifecycle ownership

| Need | Native ownership design step | Rule for this shell |
| --- | --- | --- |
| Java calls, fields, object/string results and worker attachment | Step 4 (CL-P2-09) | Signature-selected calls, per-call local frames, immediate exception checks; promote escaping objects to owned global references |
| Java-to-btrc callbacks and main Looper affinity | Step 7 (CL-P2-24) | RegisterNatives checked entries, application ClassLoader, `executor = main`; exception translation cannot unwind through JNI |
| Retained Java peer to btrc receiver | Step 7 / shared R3 | One external ARC claim and entry pin; explicit peer close on its executor, CallbackScope cancellation and drain |
| Weak Activity references and recreation | Step 7 | JavaWeak promotion on use plus generation checks; a cleared reference produces a typed unavailable result, not stale dereference |
| Surface ownership | Stage 29 GPU owner | ANativeWindow lease tied to surface generation; no local JNI reference stored after its adapter frame |

The Activity-facing provider and Java peer may form a foreign-held cycle;
explicit cancellation must break it before releasing the old Activity. A Java
Cleaner reports a leaked peer and must not release btrc ARC from its thread.
Only btrc-attached threads detach, after ARC cleanup; Java-owned entry threads
remain attached. Application classes resolve through the registered ClassLoader
or JNI_OnLoad cache, not FindClass from an arbitrary attached worker.

Construction, callback and teardown failures keep the same checked ownership
model: unwind acquired globals/local frames, expose failed or pending cleanup,
and retain only the state required to finish it. Cancel from inside a callback
must not free its receiver before the outermost entry returns. Never add a
parallel raw-jlong receiver table as an escape hatch around generated holders.

## Target rows, host and accessibility evidence

Use `android-aarch64` and `android-x86_64` with the NDK sysroot and API 29 floor
from the target contract. The target OS remains Android even though its triple
contains linux. Provider filters must select Android exclusively, and cache
identity includes ABI, API and sysroot. A Linux x86_64 shared library is not an
Android x86_64 result.

`docs/design/native-ui-catalog/hosts.toml` is absent at this baseline.
CX-UIA-06 (`ui-0-host-matrix`) will declare the CI KVM emulator and the owner's
Mac emulator, separately for each frontend/evidence class. CI provision comes
from `tooling-android-ci-emulator` (CX-P1-05), then Stage 25
`platforms-p1-host-android` (CX-P1-09, `host-android.yml` provider-suite).
The current cloud container is not an emulator evidence host. Use
`nix develop .#platforms` for local build tooling; the hosted lane installs the
exact SDK/NDK/JDK revisions from the repository's pinned toolchain contract.

Use UiAutomator/AccessibilityNodeInfo against the fixture package, recording
role/class, stable ids, text labels (without password/draft secrets), bounds,
enabled/focus state and actual click/edit actions. Tree dumps are accessibility
structure evidence, not TalkBack evidence. Physical input, vendor-specific
behavior and physical-device GPU performance remain unavailable under D8 and
`tooling-android-physical-devices`.

Run APKs built from each frontend on the required API rows. Exercise 100
Activity-recreation cycles and separate fresh-process death/restore trials:
focus/edit, native button, scroll, GPU resize/loss, pending completion, close
during callback and old-generation delivery. Assert zero stale Activity/View
references, globals and registered peers after drain, with CheckJNI clean logs.
Record surface-generation leases separately. A successful APK launch does not
prove either stale-reference cleanup or process-death restoration.

Artifacts include API/ABI/page size, emulator/host provenance, target and source
revision, frontend, input mechanism, accessibility dump, event/lifetime trace
and native/GPU composition capture. The 16 KiB-page arm64 lane belongs to the
Mac emulator/device plan (MAC-P1-03); an ordinary x86_64 CI emulator must not be
reported as that lane. Minimum/current-API or page-size gaps stay explicit.

## Dependency checklist and requests

| Required before CX-UIA-17 | PLAN item / packet |
| --- | --- |
| Target/ABI/NDK identity, exclusive provider selection and safe caches | `platforms-p1-target-spec` (CL-P1-06), `platforms-p1-hosted-abi-targets`, `platforms-p1-native-import-targets`, `platforms-p1-native-plan-toolchain`, `platforms-p1-provider-filters` (CL-P1-14), `platforms-p1-cache-identity` (CL-P1-15) |
| Build tools, emulator and test executor | `tooling-android-sdk-ndk` (CL-P1-02, MAC-P1-03), `tooling-android-ci-emulator` (CX-P1-05), `platforms-p1-host-android` (CX-P1-09) |
| Checked JNI in both directions | `platforms-a1-checked-jni` (CL-P2-09 then CL-P2-24) |
| Activity and main executor | `platforms-a1-activity-lifecycle` (CX-P2-41), lifecycle-shape review CL-P2-22 under that item |
| WebGPU SurfaceView route | `platforms-a2-gpu` (CX-P2-44), shared `tooling-cross-gpu-deps` archives; packaging alignment is `platforms-a2-packaging-16k` |
| Shared fixture and approved interface | `ui-1-shell-fixture` (CX-UIA-09), `ui-2-contract-review` / `ui-3-contract-input` for landed contracts |

CL-P2-09/24 are the request owners for missing checked JNI operations, native
entry lifetimes or main-Looper release support. CL-P1-14/15 own provider/cache
gaps. These are known assigned prerequisites, not new compiler defect claims;
file a minimal targeted REQUEST if implementation finds another need. The
notes unblock planning and review only, not the gated provider implementation.
