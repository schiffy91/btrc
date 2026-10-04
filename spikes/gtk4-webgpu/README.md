# GTK4 / WebGPU plain-C pre-spike

Throwaway CX-UIA-12 evidence. Push this branch, open no PR, never merge it.
This does not satisfy D23, which requires a btrc-hosted window.
The separate findings packet owns `docs/design/linux-gtk4-feasibility.md`.

Use the repository's pinned development shell from its root:

```bash
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 cpu 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland cpu 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 x11-child 100 asan
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland wayland-subsurface 100 asan
```

All four recorded runs completed 100 window/device lifecycles and 300 frames,
then **returned 1 because LeakSanitizer reported leaks**. Do not suppress the
exit status or describe these as sanitizer passes. `owned_widgets_alive: 0`
counts only the directly tracked widgets, not every toolkit allocation.
ASan/UBSan instrument the probe; dependencies use the pinned prebuilt libraries.
The elapsed times include a 12-second accessibility hold and artificial pumping
waits, initialization and teardown; they are not frame-rate benchmarks.

Each command writes logs and images under `build/gtk4-spike/PROTOCOL/ROUTE-VARIANT`.
For a quick functional reproduction, use `1 plain` instead of `100 asan`.
For the API-only routes, run both protocols:

```bash
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 dmabuf 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland dmabuf 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh x11 wayland-subsurface 1 plain
nix develop --command bash spikes/gtk4-webgpu/run.sh wayland x11-child 1 plain
```

The dmabuf check reports available GTK types but zero frames: no public external
memory/dmabuf export was found in the pinned wgpu-native v27 C headers. It does
not attempt a private Rust/Vulkan bridge. Opposite-protocol native routes report
`protocol-not-applicable`, not a successful rendering test.

`evidence/` preserves the final unsuppressed sanitizer logs (`probe.log.gz`, read with `gzip -dc`), one-cycle CPU
baselines, actual AT-SPI JSON and snapshots. CPU readback renders blue pixels,
copies them into GdkMemoryTexture and participates in GTK clipping/overlay.
X11's composed capture shows the native child covering the overlay button and
extending beyond the 96-by-96 viewport. GTK snapshots exclude external native
surfaces; the Wayland native route has no composed screenshot, so its actual
compositor pixels are unverified. Neither native route participates in GTK's
snapshot clip or within-window control stacking.

AT-SPI captures have an explicit 16-child-per-node limit and 256-node budget.
They establish native entry/button/list exposure, not all 1,000 rows or custom
GPU accessibility. A transient dbind cache warning was emitted on X11; capture
still found the required roles and exited 0.

For a one-cycle sanitizer baseline, reuse the built CPU binary in its private
session (create OUTPUT first):

```bash
nix develop --command tools/ui/headless-session.sh --x11 -- build/gtk4-spike/x11/cpu-asan/Probe cpu 1 0 OUTPUT
nix develop --command tools/ui/headless-session.sh --wayland -- build/gtk4-spike/wayland/cpu-asan/Probe cpu 1 0 OUTPUT
```

No leak suppressions or production provider changes are included. X11 public
API deprecation warnings from GTK 4.22 remain visible in build logs.
