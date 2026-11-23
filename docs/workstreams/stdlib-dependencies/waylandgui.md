# Linux GUI on native Wayland

Implement the portable GUI shim on a native Wayland compositor. Ordinary windows,
controls and software rendering use the Wayland protocol over the compositor's
socket. A GPU window may use libwayland-client for the objects wgpu-native must
pass to the driver. Keep existing X11 compatibility where it is inexpensive.
A new X11 backend is outside this workstream.

## Existing contracts

Read the four headers in `src/stdlib/GUI/Shim`, the GTK implementations in
`src/stdlib/GUI/Linux`, the Windows shim, the GUI package manifest, the Linux UI
conformance suite and `tools/ui/headless-session.sh`. Establish a native Wayland
baseline with the existing provider for input, window lifecycle, controls, pixels,
GPU views, accessibility, clipboard, dialogs and WebKit integration. Record the
public behavior of each before switching its provider.

## Work and qualification

1. Implement registry discovery, interface version negotiation and object
   lifetimes. Use the system's Wayland socket, bounded wire messages and Unix
   descriptor passing. Implement xdg-shell configure/acknowledge, window
   state, input seats, scaling, frame callbacks, shared-memory buffers and
   release notifications. Integrate wakeups from other threads with the event
   loop. Exercise disconnect and teardown.
2. Preserve the layout, drawing, clipping, focus, editing and input behavior of
   every shim control, including text selection, preedit, popups, clipboard,
   scroll, pointer and keyboard navigation. Account for keyboard layouts and
   compose input. Wayland leaves some operations, including global window
   placement, to the compositor. Record any public capability gap for the owner.
3. For GPU presentation, give the driver a real wl_display and wl_surface
   from the same libwayland-client connection. A surface from a separate
   connection cannot be adopted by the driver. Verify the lifecycle when a
   caller adds a GPU view to an existing window, with input, scale, focus and
   sibling controls intact. Trace runtime loads in both a software-only app
   and a GPU app. Scope the display-library allowance to GPU presentation.
4. Retain AT-SPI roles, states, editable text, actions and focus events through
   the first-party D-Bus client. Keep portal folder selection, message boxes,
   tooltips and first-party text rasterization. Move Linux WebKit integration
   to its optional package with a working embedded-view migration.
5. Run `tools/ui/headless-session.sh --wayland -- …` and verify DISPLAY is
   unset in the application. Use compositor-native input and capture for the
   Linux UI conformance cases and provider tests. Prove the same public calls
   through both compilers. Exercise 100 create/destroy cycles and run the
   provider under ASan and UBSan. Record unavailable compositor protocols.
6. With GTK and the removed development packages absent, check ELF imports with
   `tools.qualification.dependencies` and trace runtime loads for each rendering
   mode. Remove the bundled viewporter code and retire each pending requirement
   when its replacement passes. Record remaining X11 behavior and any
   migration that existing X11-only clients need.
