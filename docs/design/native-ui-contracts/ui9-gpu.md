# UI9 GPU and scheduling pre-draft

Status: draft under D27, not approved

Packet: **CX-UIB-05**. Source baseline:
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.
This is a proposal for N47–N49 and their UI5/UI8/UI10 consumers. It changes no
interface or provider and records no native execution. Final contracts require
the UI2/UI3 landing, all five UI1 shells, D23, CL-UIA-22 and CL-UIB-02 review.
The companion [runtime-probes](runtime-probes.md) defines measurement boundaries;
the limits below retain [native-ui-parity](../native-ui-parity.md) E12/E32/E36/
E37/E38/E42/E43 and its numeric acceptance table.

## Source gaps and retained ownership

| Existing source | Observation at the baseline | Required change in the implementation packet |
|---|---|---|
| [IGPUView](../../../src/stdlib/GUI/IGPUView.btrc) | Poll/error, borrowed renderer, preparation/readback ownership and asynchronous close exist. Display-paced invalidation and recoverable presentation events do not. | Extend these owners, without a second GPU runtime or borrowed renderer outliving its view. |
| [IApplication](../../../src/stdlib/GUI/IApplication.btrc) | `postAfter` is delayed UI work, with capacity and cancellation. | Keep timers separate from display cadence. |
| [LinuxWindow](../../../src/stdlib/GUI/Linux/LinuxWindow.btrc) | `needsFrame` uses stored `_visible`; hide/minimized event branches do not update that eligibility. `isVisible` checks the hidden flag but not the whole exposure/drawable state. Unavailable rendering throws after more than 120 attempts. | Observe exposure and retry by elapsed monotonic time, rather than frame count or exception-driven application shutdown. |
| [Linux GUIProvider](../../../src/stdlib/GUI/Linux/GUIProvider.btrc), [GUICaptureLayer](../../../src/stdlib/GUI/GUICaptureLayer.btrc) | Capture validates layer provider and ancestry, but ignores layer pixels and captures the owning window. The shared comment explicitly permits Linux to wait; `LinuxWindow.render(true)` polls readback with 1 ms sleeps for up to 5 s. | Review the existing exception away: validate full subtree/frame/layer scope and separate asynchronous preparation from bounded composition. |
| [LinuxPainter](../../../src/stdlib/GUI/Linux/LinuxPainter.btrc) | Images are cached by identity; eviction runs every 64 frames for entries unused more than 240 frames. There is no aggregate byte admission here. | Byte reservations, retirement accounting and trim independent of repaint. |
| [LinuxFonts](../../../src/stdlib/GUI/Linux/LinuxFonts.btrc), [LinuxSystemText](../../../src/stdlib/GUI/Linux/LinuxSystemText.btrc) | Measurement sums scalar glyph advances; missing glyphs fall back to `?`. | Qualified shaped runs shared by measurement and rasterization, with fallback and cluster identity. |

Existing view ownership and UI2 close/drain remain authoritative. A scene/window
owns its display subscription; a GPU view owns programs/readbacks it creates;
shared devices name every dependent window. A window-local failure is not
permission to close unrelated native editors. IView's exposure/lifecycle shape
stays with its designated writer chain.

## Proposed scheduling surface

The proposed **IDisplayScheduler** belongs to the existing application's native
loop integration. It holds one pending invalidation revision per target plus
an optional scoped animation subscription. It does not run a periodic timer
when there is no work. These names are proposed operation ids, not new frozen
catalog entries or compilable interfaces:

```btrc
// IDisplayScheduler
void invalidate(IGPUView view, long long contentRevision);
ICallbackRegistration onFrame(IGPUView view, IDisplayFrameHandler handler, CallbackScope owner);
DisplayState state(IGPUView view);
// IGPUView, extending its existing close/poll ownership
PresentationState presentationState();
ICallbackRegistration onPresentationChanged(IPresentationHandler handler, CallbackScope owner);
PresentationRequest retryPresentation();
```

The scheduler requests the next display opportunity only while exposed drawable
work or a declared animation needs it. Repeated invalidation replaces the
pending desired revision; native input/final semantic events are not replaceable
frames. At a tick, reconcile readiness/generation, acquire at most one frame
for that target, render the current model, then present. If model state advances
during work, retain the newer invalidation for the next eligible tick.

A display callback may only publish a preallocated tick marker with timestamp
and generation. It does not allocate, block, call product handlers or reenter
the UI executor. The UI2 loop fairly arbitrates input, work, timers, frames and
terminal cleanup. `postAfter` remains for deadlines and debounce; audio sample
position remains the product/audio clock. No clock is simulated by counting
rendered frames, and suspension never replays an animation backlog.

## Exposure and presentation failure

Use UI2's separate requested visibility, native visibility/minimization,
activation, application/scene activity, exposure (`exposed`, `notExposed`,
`unknown`) and drawable readiness. Unknown compositor occlusion is not false
visibility and not failure. Hide/minimize/zero-size/known non-presentable state
suppresses presentation while retaining latest model/invalidation. Explicit
offscreen capture and required background work are separately attributed.

| State/outcome | Owner behavior |
|---|---|
| WaitingForExposure | No retry-failure count; wait for an exposure/size/activity transition. Keep current invalidation. |
| WaitingForDrawable | Unavailable surface that is expected from lifecycle/size remains an observed readiness state. Never spin to discover readiness. |
| RetryableFailure | Unexpected transient acquisition/presentation failure schedules bounded delayed retry. Preserve editors/model and report cause. |
| DeviceLost | Retire the device generation; cancel dependent GPU work/readbacks; coordinate every window sharing that device. Rebuild only affected resources. |
| Recreating | Native controls remain responsive; new GPU work is explicitly deferred/rejected until replacement resources exist. |
| TerminalFailure | Present an accessible native error with retry/close actions; stop automatic retries. Preserve unaffected windows and drafts. |
| Closing/Closed | Cancel frame admission and retire callbacks; drain GPU/native ownership on the required executor. No retry can reopen the generation. |

The continuous retry interval starts at the first unexpected retryable failure
and resets only after successful presentation or explicit user retry. Limit to
**at most 10 attempts per second**, with **at least 100 ms** between attempts,
and report terminal failure within **5 s** of continuous failure. No sleeping
on the UI thread. A hidden wait is not a failed attempt; a provider may not
relabel an unexpected failure as hidden to avoid the deadline. Native lifecycle
notifications wake a waiting target; repeated stale timer callbacks are canceled
by generation. Once replacement resources are ready, present current content
within **1 s** in the controlled fixture.

E42 restores the current frame within **100 ms p95** after drawable readiness,
measured separately from device initialization. E43 requires **0 stale-generation
callbacks**, **0 unintended healthy-window closes**, **0 leaked owned GPU
resources** after drain and **≤5%** settled growth after warmup. Failed recovery
stays a failure even if the application exits cleanly.

## Display-clock and native-surface mappings

Every row is a feasibility proposal. API availability and timestamp semantics
must be checked against the final deployment floors; naming an API is not proof
that its WebGPU integration works.

| Platform | Display signal | Surface, clock and lifecycle adaptation |
|---|---|---|
| macOS | CVDisplayLink or the supported AppKit CADisplayLink integration at the selected deployment floor | Display callback posts a bounded marker; AppKit work remains on main. Track display migration, backing scale, occlusion and per-view/shared device ownership. CV host timestamps require explicit conversion to the process monotonic clock. |
| Linux | GTK4 frame clock if D23 chooses GTK4; SDL/native display integration otherwise | GTK frame time and SDL performance timestamps are different domains. Prove Wayland frame/presentation feedback and X11 presentation observation where available. SDL timers are not proof of compositor presentation or reliable occlusion. |
| Windows | DXGI frame-latency waitable swapchain where available | Wait off the UI thread or integrate a message-aware readiness wait; never block native input dispatch. Correlate QPC/presentation evidence and record missing feedback in the chosen WebGPU surface path. Handle DPI/display changes. |
| iOS / iPadOS | CADisplayLink on the scene's main run loop | Track variable cadence, preferred frame range, scene activity and drawable lifecycle. Two iPad scenes have separate owner generations; no device-wide pause based on one scene's exposure. |
| Android | Choreographer frame callback | Bound JNI/UI-loop publication, record frame time versus actual present feedback, and cancel on Activity/surface generation changes. Refresh-rate changes do not alter audio time. |

Clock conversion records units, origin, sampled offset/drift and uncertainty.
If native input or actual presentation timestamp is unavailable, mark that
endpoint unavailable and report a separately named proxy; handler duration,
queue submission, screenshot readback and frame ticks cannot satisfy E32's
actual input-to-visible budget. Do not subtract unrelated clocks or clamp
negative differences to zero. Preserve raw timestamps for reanalysis.

## Asynchronous subtree capture (E38)

The proposed **ICaptureRequest** retains root identity, owner generation,
content/frame revision, target backing size/scale and validated layers. Its
states are preparing/ready/stale/canceled/failed. It uses existing scoped
completion/cancellation machinery; no parallel callback lifetime model.

```btrc
// Proposed capture owner; exact factory belongs to the reconciler.
ICaptureRequest prepareCapture(IView root, CaptureSpec spec, CallbackScope owner);
// ICaptureRequest
CaptureState state();
CaptureResult takeResult();
CallbackCancellation cancel();
CallbackCancellation pollCompletion();
```

Validate before allocating/submitting: root open and attached, correct provider,
every GPU layer a unique descendant of that root, valid pixel dimensions and
scale, completed readback tied to the expected device/frame generation, and
checked pixel/byte limits. Sibling/foreign/duplicate/detached layers and stale
size/frame identities have distinct failure reasons. A root capture includes
only its subtree with correct clipping, native overlays and backing scale.
Already composed window pixels may be cropped only when all declared frame,
layer and scope constraints remain provable; silently ignoring supplied data
is not equivalence.

GPU preparation runs asynchronously; `takeResult` is bounded and returns
not-ready if incomplete. UI code never polls in a sleep loop or waits on a GPU
fence. Resize/device loss marks old results stale and releases their reservations
after actual GPU retirement. Close/cancel resolves once and leaves surviving
view ownership intact. Retain the existing default **16,777,216-pixel** readback
admission where applicable until a reviewed replacement; checked row pitch and
all staging copies are charged to an explicit byte budget. A provider's larger
internal capture allowance is not a portable API promise.

## Artwork residency and idle trim (E36)

Propose one **ArtworkBudget** owner across decode, conversion, upload and native
presentation caches. A per-image pixel limit and a bounded cell count are not
aggregate memory limits. Reserve bytes before every allocation; a reservation
accounts for decoded, staging, native/GPU copies and in-flight/retiring resources.
Count one allocation once even if several views alias it; count distinct copies
separately. Toolkit-private residency has a measurement or an explicit unknown
bound, not zero. Visible images remain pinned under UI2 retained presentation.

```btrc
ArtworkAdmission reserveArtwork(ArtworkRequest request);
ArtworkUsage artworkUsage();
ICallbackRegistration trimArtwork(IArtworkTrimHandler handler, CallbackScope owner);
```

Budget **≤128 MiB desktop / ≤64 MiB mobile**, inside the overall product working
set, with **≤2 simultaneous thumbnail decode/conversion jobs**. Prefer visible
work over prefetch; downsample to the displayed size. If a visible request
cannot fit, choose a documented smaller variant or return admission failure;
never exceed the ceiling. Cancel obsolete generations before publication and
keep retirement bytes charged until reusable. GPU completion can free a
reservation independently of semantic callback delivery.

Eviction is driven by ownership, trim request or memory pressure, not the
number of painted frames. In a quiescent fixture release all eligible unused
entries within **1 s** of explicit trim with **0 application repaint passes**
requested solely to advance eviction. Referenced presentations and unavoidable
GPU retirement are reported separately from eligible unused cache entries.
E36 traverses the **1,000-album** catalog using **256/512-pixel** thumbnail
variants and oversized-source cases; cancel/recycle/close during upload for
**100 cycles**, with zero stale publication and bytes returning after drain.

## Shaped custom text (E37)

Propose **ITextLayout** as the owner of immutable shaped **TextRun** data:
resolved font/fallback runs, glyph positions, logical advances, cluster-to-source
mapping, bidi levels, line/ink bounds, wrapping and ellipsis. Measurement,
painting and any exposed hit/selection mapping consume the same shaped result.
Native controls retain their native text layout; this owner serves retained
custom GPU content, not a replacement editor.

```btrc
TextLayoutResult shapeText(TextLayoutRequest request);
TextHit hitTest(TextRun run, double x, double y);
TextRasterResult rasterizeRun(TextRun run, TextRasterBudget budget);
```

macOS/iOS evaluate Core Text/native text layout; GTK4 evaluates Pango; SDL-custom
needs a qualified shaping/bidi/fallback stack; Windows evaluates DirectWrite;
Android evaluates native text layout through its checked binding. These are
platform mappings to review, not dependency additions in this packet. Missing
font/glyph, unsupported script and resource exhaustion return recoverable
outcomes. A qualified fallback containing a glyph must not be replaced silently
by `?`; glyph/atlas overflow must not omit characters.

Freeze named fonts/fallbacks and strings for ligatures/kerning, combining marks,
Arabic, mixed Hebrew/Latin/numerals, Devanagari, Thai, CJK, Korean and emoji/ZWJ.
Compare cluster order and advances against the same platform's native layout;
measurement and drawn ink agree within **one backing pixel**. Run at
**100/150/200% display scale** and the accessibility text-size matrix. Retain
visible boundary tests around the current **4096-pixel system-text raster** and
**512-pixel glyph-staging** bounds until reviewed policy replaces them. These
are resource bounds, not permission to truncate a valid string. Do not require
pixel-identical glyphs across operating systems.

## Required acceptance before implementation can qualify

| Case | Sequence and numeric limits |
|---|---|
| E12 | Native overlays and GPU child: clip/input correctness through resize/hide/suspend/recreate, **100 lifecycle cycles**, zero leaked owners, zero static application relayout/repaint after settling. Native semantic boundary remains separately inspected. |
| E32 | **≥100 actions**, cold/warm assets identified; input receipt → command delivery → model update → actual presentation. Visible response p95 **≤100 ms**, debounce separately reported; missing native endpoints stay unavailable. Frame run **10 min at 60 Hz**, p95 **≤16.7 ms**, p99 **≤33.3 ms**, missed presents and longest stall reported; report 120 Hz **8.3 ms** misses separately. |
| E36 | **1,000 albums**, **256/512 px** variants; **128/64 MiB** desktop/mobile total artwork, **≤2** concurrent jobs, **100** cancellation cycles. Explicit trim releases eligible cache within **1 s**, with **0** eviction-only repaints. |
| E37 | Named script/font corpus at **100/150/200%** scale; cluster/fallback correctness and ink/measurement agreement within **1 backing pixel**. Exercise **4096 px** raster and **512 px** glyph bounds with explicit recoverable overflow. |
| E38 | Root and nested subtree captures at **100/150/200%** scale; **100** capture/resize/cancel/close cycles; ready/not-ready/lost GPU states and invalid layer scope. Zero UI-thread GPU waits, stale accepted results or retained resources after drain. Charge all bytes before allocation. |
| E42 | **100** exposure/restore cycles with two windows and animated child. When settled and known non-presentable, **0** presentation attempts over **60 s**; current restored frame p95 **≤100 ms** after drawable readiness. |
| E43 | **100** fail/recover/close cycles; **≤10 retries/s**, explicit failure within **5 s**, current frame within **1 s** after resources ready. **0** stale callbacks, healthy-window closes or owned GPU leaks; **≤5%** settled memory growth. |

Static idle additionally requires **≤1% of one core over 60 s**, measured with
and without assistive technology, with no caret blink/animation/work pending.
All families retain the **512/384 MiB** desktop/mobile product working-set
ceiling. Run through both frontends and the actual provider; Linux X11/Wayland
and iPhone/iPad evidence are distinguished. Timing from hosted or simulated
devices is diagnostic unless the qualification policy admits that runner.

Review must settle display/native timestamp availability, exposure uncertainty,
shared-device failure scope, capture compatibility, toolkit-private memory
accounting and font/shaper dependencies. Any runtime/interop/analyzer change is
a REQUEST from the implementing packet; no such change is made here.
