# `std.app`

`std.app` is the process-global application/event-loop owner. It creates at
most one native window and emits ordered, bounded pointer, scroll, key, text,
logical resize, framebuffer resize, DPI, and close-request events.

`AppPointerEvent.clickCount` preserves the native click sequence on macOS;
movement has count zero. It is captured inside the OS callback before queueing,
so delayed dispatch does not change double-click recognition. macOS owns the
user's timing/spatial preference. Platforms without a click-count provider
currently report one for button events; native multi-click support there is
unfinished. Synthetic events can supply the optional constructor argument.
`std.NativeUiApp` forwards the count to shared text fields: double-click
selects a word, dragging extends by whole words, and triple-click selects the
line. Shift-click retains anchor-based selection.

`window.setTitlebarStyle(APP_TITLEBAR_OVERLAY)` extends content behind the
native title bar on macOS, preserving the native window buttons and logical
viewport dimensions. Reserve the top-left header area for those controls.
Call it before creating a surface; it returns an optional `AppError` for
unsupported platforms, invalid styles, closed windows, wrong-thread calls, or
an existing surface. `APP_TITLEBAR_STANDARD` restores the conventional frame.
Unconfigured windows remain standard; unsupported platforms are not made
borderless or given imitation window buttons.

The native window never crosses the public BTRC API. `ApplicationWindow`
creates one generation-checked `AppSurfaceAttachment`; a GPU or UI renderer
may attach to that capability through its private native boundary. A second
surface owner, two simultaneous GPU attachments, a stale generation, and an
attachment after window close are typed failures.

Ownership is structural:

```text
GPU/UI child -> AppSurfaceAttachment -> ApplicationWindow -> Application
```

Close children before their parents. Early parent close calls return
`APP_ERROR_RESOURCE_BUSY`; destructors retain the same ownership chain so ARC
cannot tear down the window or GLFW while a renderer still uses the surface.
The native order is in-flight frame and render resources, surface
unconfiguration, queue/device/adapter and the GPU surface handle, application
surface lease, native window, then GLFW.
The GPU owner is itself represented by a monotonic integer capability, so a
closed GPU identity cannot alias a later native allocation.

GPU attachment, resource creation/update, draw recording, frame acquisition,
presentation, and close all return typed outcomes. Resource factories publish
an identity and teardown receipt only with `GPU_RESOURCE_READY`; every failure
leaves both outputs zero. An opaque backend creation failure remains the honest
`GPU_RESOURCE_CREATION_FAILED` state rather than being guessed to be shader
validation or allocation failure. Invalid/stale resources, invalid descriptors,
wrong-thread access, device loss, missing active frames, and backend draw
failure remain distinct public states.

Managed owner constructors are private. Each native owner creation returns a
second, private one-time receipt alongside its public operation capability;
close and finalizer entry points require the exact pair. Publishing a
capability therefore does not confer teardown authority, and a copied,
guessed, stale, or wrong-generation receipt cannot close the canonical live
window, surface, GPU, shader, pipeline, or uniform owner.

The GLFW implementation requires calls on the creating thread and enforces the
macOS main-thread requirement. Headless tests use the same BTRC API with a
deterministic runtime implementation; passing those tests is not evidence that
a display, adapter, or presentation path is available.

Application, window, surface, GPU, and render-resource objects are
thread-affine. Explicit close operations still return typed wrong-thread
rejections before touching native state. If ARC drops the last strong
reference on a worker, its destructor instead records an idempotent finalizer
request in the native owner; it never performs GLFW/WebGPU teardown there.
The owner drains render resources, GPU, surface, window, and application in
that order at the next owner operation, before a replacement `Application`
checks the singleton, or from the owner-thread exit handler. Stale capability
requests cannot target a reopened resource. If a process calls `exit` from a
non-owner worker, native window teardown is intentionally left to the OS
rather than violating GLFW's thread contract.
