# Linux shell probe

`ShellProbe.c` drives the shared shell journey on the Linux provider with
real input: XTEST on X11, and on Wayland a wlroots compositor's virtual
pointer and keyboard (the conformance suite's `ShimProbe`, `X11Input` and
`WaylandInput`). It runs only in a private session from
`tools/ui/headless-session.sh`, never on a desktop someone is using. Its
accessibility report says `not observed`: the controls are GTK widgets with
GTK's own accessible objects, and the journey does not read them.

`EventBoundary.c` is the observer of the burst fixture
(`../../../linux/LinuxEventBoundary.btrc`). It queues events in the
provider's own queue through the shim's private seams (`btrcGtkPush`,
`btrcGtkQueued`, `btrcGtkQueueFlush`, `btrcGtkQueueFilter`) and wraps
`btrcShimPollEvent`, `wgpuSurfacePresent` and `btrcShimWindowShowPicture` at
link time, delegating each call unchanged. Only the provider dequeues.
