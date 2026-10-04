# GTK4 / WebGPU feasibility: plain-C pre-spike

CX-UIA-12, recorded 2026-10-04 against main
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.

CPU readback can place WebGPU output inside GTK's layout, clipping and control
stacking on X11 and Wayland. The direct X11 child presents GPU frames but visibly
breaks clipping and covers the overlaid native button. A Wayland subsurface also
presents frames, but its relationship to GTK's clip and control stack is not
integrated or proven by a compositor capture. The pinned public wgpu-native C
API supplies no dmabuf export route. **No accelerated route is qualified for the
production provider by this experiment.**

This is plain C and **does not satisfy D23**, which requires a btrc-hosted window.
The CPU path is a non-final baseline. It is not a decision to replace the current
SDL provider or a claim that UI1/UI2 acceptance is complete.

## Reproducible source and evidence

The prototype is on `codex/cx-uia-12-spike`, commit
[`47f381f9`](https://github.com/schiffy91/btrc/tree/47f381f9/spikes/gtk4-webgpu).
That branch has no PR and must never merge. This findings branch carries only
this document. The prototype's README contains the build command and invocations;
its `evidence/` directory contains actual screenshots, AT-SPI trees, unsuppressed
sanitizer logs compressed as `probe.log.gz`, and source hashes.

The host was a Linux x86_64 cloud container, using the repository's private
D-Bus/headless-session helper, Xvfb for X11 and Weston with its pixman renderer
for Wayland. GPU rendering used software Vulkan. Pinned versions were GTK
4.22.4, wgpu-native 27.0.4.0, wayland-client 1.25.0, X11 1.8.13, GCC 15.2.0 and
Python 3.14.6. No flake, Nix definition, source provider or workflow was changed.
GTK 4.22 deprecates its public X11 backend APIs; the probe retains those build
warnings with `-Wno-error=deprecated-declarations`.

Check out the prototype branch and run from its root inside the pinned shell:

```bash
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 cpu 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland cpu 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 x11-child 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland wayland-subsurface 100 asan
```

All four recorded commands completed 100 cycles and 300 frames, then exited **1**
for the leak reports below. They are not green sanitizer tests. For a quick
functional run, replace `100 asan` with `1 plain`. Output goes to
`build/gtk4-spike/PROTOCOL/ROUTE-VARIANT`.

## The experiment and route results

Each cycle constructs a GtkApplicationWindow containing a GtkEntry, a
GtkOverlay with a native button above the GPU area, and a GtkScrolledWindow
holding a 1,000-row GtkListView. The GPU image/native surface is 128 × 128; its
GTK viewport is 96 × 96. This deliberately exposes clipping failures. A new
WebGPU instance, adapter, device and queue renders three blue frames each cycle;
window/device resources are then released.

| Route | X11 result | Wayland result | Frames in recorded 100-cycle run |
|---|---|---|---|
| CPU readback → GdkMemoryTexture → GtkPicture | Renders; GTK snapshot and composed capture show correct viewport clipping and visible overlay button | Renders; GTK snapshot shows correct viewport clipping and visible overlay button | 300 each |
| X11 child surface → WebGPU | Presents, but fails GTK clipping and overlay stacking | Not applicable: no X11 display/window | 300 X11; 0 Wayland |
| Wayland subsurface → WebGPU | Not applicable: no Wayland display/surface | Presents; GTK snapshot excludes external surface; composed overlap/clipping unverified | 0 X11; 300 Wayland |
| dmabuf → GdkDmabufTexture / GtkGraphicsOffload | Blocked at public WebGPU export API; GTK types available | Same blocker; GTK types available | 0 each |

The CPU probe copies an RGBA8 render target into a mapped staging buffer,
checks the returned blue/alpha bytes, copies them into GBytes and creates a
GdkMemoryTexture for GtkPicture. Each frame crosses GPU/CPU memory and involves
a copy. The recorded elapsed times (X11 59.98 s, Wayland 57.15 s for 100 cycles)
include initialization, destruction, artificial main-context waits and a
12-second accessibility hold. They are **not throughput or latency measurements**.

GTK4 does not supply the former GTK3 foreign-child embedding abstraction. The
X11 probe uses the public GDK display/XID accessors and XCreateSimpleWindow,
then passes that raw child to WGPUSurfaceSourceXlibWindow. It is outside GTK's
snapshot composition. The composed image below shows all 128 × 128 blue pixels
covering the native button and the beginning of the list beyond the viewport:

- [CPU baseline, correctly clipped](https://github.com/schiffy91/btrc/blob/47f381f9/spikes/gtk4-webgpu/evidence/x11/cpu-asan/x11-composed-cpu.png)
- [Native X11 child, clipping and overlap failure](https://github.com/schiffy91/btrc/blob/47f381f9/spikes/gtk4-webgpu/evidence/x11/x11-child-asan/x11-composed-x11-child.png)

The Wayland probe obtains the parent wl_surface from GdkWaylandSurface, creates
its own wl_surface/wl_subsurface, places it at the GPU widget's position and
passes it to WGPUSurfaceSourceWaylandSurface. Presentation succeeds, but the
probe does not translate GTK clip regions, reshape on scroll/resize, or integrate
native controls into the external surface's stacking order. A GTK snapshot
cannot prove compositor output because it excludes this external surface.
No Wayland composed screenshot was captured; actual overlap pixels remain
unverified. This route therefore fails the proof required for choosing it,
even though presentation itself works.

Both `gdk_dmabuf_texture_builder_get_type()` and
`gtk_graphics_offload_get_type()` resolve. Inspection of the pinned public
`webgpu.h` and `wgpu.h` found no dmabuf/external-memory texture export facility.
The probe stops there with `blocked-no-wgpu-c-export-api`; it does not pretend
to import a WebGPU frame or infer support from GTK's types. A private Rust/Vulkan
bridge would be additional design and ownership work, outside this spike.

Reproduce the two blocked and two opposite-protocol results:

```bash
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 dmabuf 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland dmabuf 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 wayland-subsurface 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland x11-child 1 plain
```

These API-only runs return 0 with an explicit blocked/not-applicable JSON result
and **zero frames**. Their process exit status is not evidence of a working GPU
route. Search the same pinned headers with:

```bash
nix develop --command bash -c 'rg -ni "dmabuf|dma_buf|external.memory|export.*texture" "$(pkg-config --variable=includedir wgpu-native)"'
```

An empty search is supporting inspection, not a general impossibility claim
about all WebGPU implementations or future APIs.

## Accessibility evidence

The CPU route runs a separate pyatspi client in the same private D-Bus session.
It finds the actual frame title, services AT-SPI cache updates and serializes
native accessible nodes. The application identifies itself as `Unnamed`, so
matching an invented application name would miss it.

- [X11 AT-SPI JSON](https://github.com/schiffy91/btrc/blob/47f381f9/spikes/gtk4-webgpu/evidence/x11/cpu-asan/atspi.json): 46 nodes, including text entry, button, list, 16 list items and image.
- [Wayland AT-SPI JSON](https://github.com/schiffy91/btrc/blob/47f381f9/spikes/gtk4-webgpu/evidence/wayland/cpu-asan/atspi.json): 56 nodes; extra window decoration nodes account for the difference.

Both capture processes returned 0 after checking entry/button/collection roles.
The capture deliberately limits each node to 16 children and the tree to 256
nodes, and marks truncation. It does not establish accessibility of all 1,000
rows, recycling behavior or a custom semantic tree inside GPU content.
GtkPicture exposes an image; production IGPUView semantics still need an explicit
accessibility contract. X11 emitted a dbind cache warning before successful
capture; the raw log is preserved.

## Lifetime and sanitizer findings

ASan and UBSan instrument the C probe; GTK, wgpu-native and other dependencies
are the pinned prebuilt libraries. LeakSanitizer is enabled without suppression.
No address violation or undefined-behavior report appeared in these runs, but
**all four sanitizer runs fail for leaks**:

| Protocol / route | Cycles | Frames | Directly tracked widgets left | Leak bytes | Leaked allocations | Exit |
|---|---:|---:|---:|---:|---:|---:|
| X11 CPU | 100 | 300 | 0 | 276,404 | 6,389 | 1 |
| X11 child | 100 | 300 | 0 | 276,404 | 6,389 | 1 |
| Wayland CPU | 100 | 300 | 0 | 306,594 | 7,245 | 1 |
| Wayland subsurface | 100 | 300 | 0 | 306,594 | 7,245 | 1 |
| X11 CPU baseline | 1 | 3 | 0 | 276,404 | 6,389 | 1 |
| Wayland CPU baseline | 1 | 3 | 0 | 297,047 | 7,144 | 1 |

Weak references count only directly constructed tracked widgets. They do not
cover every GTK internal object, row label, driver allocation or native proxy;
zero here must not be reported as leak freedom. The identical X11 one-/100-cycle
totals suggest substantial process-lifetime retention. Stacks include Fontconfig
and Pango, but their presence alone does not justify suppressing the reports.
Wayland's 100-cycle stack contains 9,600 bytes in 100 allocations through
`wl_proxy_marshal_flags` → `gdk_wayland_surface_constructed`; its total grows by
9,547 bytes and 101 allocations over the one-cycle baseline. Both CPU and
subsurface routes share that total. The exact cleanup cause remains unresolved.

Raw logs are in the prototype's `evidence/{x11,wayland}/` directories; read them
with `gzip -dc probe.log.gz`. The prototype README gives one-cycle reproduction
commands. Further attribution should isolate a minimal GTK-only lifecycle and
native-display shutdown before deciding whether these are toolkit defects,
process-global retention or missing probe cleanup. No leak-free claim is made.

## Requirements for a btrc-hosted provider

The next spike needs the approved GObject binding and callback contracts:

- Correct floating-reference sinking for widgets and transfer-full/borrowed
  handling for GtkStringList, GtkSingleSelection, factories, textures and GBytes.
  Getter results must follow their documented ownership; model/factory transfer
  into GtkListView must not be released a second time.
- Typed GObject signal connections for setup/bind/unbind/teardown and UI events,
  with CallbackScope rooting, explicit disconnect and an unregister barrier
  before the captured owner is released.
- GLib main-context dispatch owned by the host application, with publication,
  cancellation and fair work draining matching the approved UI2 executor.
  This polling C loop is an experiment, not the executor contract.
- Native GDK display/surface borrows whose lifetime cannot outlive the GTK
  window; WebGPU surfaces must release before destroying their native child.
  Resize, scale, clipping, input targeting and scroll updates need explicit
  integration and tests if an external-surface route is retained.
- Mapped-buffer callback lifetime, cancellation/device loss, texture ownership
  and queue completion must be modeled before asynchronous production rendering.
  The synchronous CPU copy here avoids proving those production lifetimes.
- Native AT-SPI roles plus custom GPU accessibility, stable list keys and
  recycling semantics; prove these through the btrc-hosted window, not C-only
  widget exposure.

CL-UIA-12 can use this evidence to reject the raw X11 embedding route as currently
implemented, keep CPU readback as a correctness comparison, and require an
explicit public export/composition mechanism for accelerated GTK rendering.
D23 still needs the btrc-hosted experiment, resolved lifetime findings and actual
Wayland compositor-level clipping/overlap evidence.
