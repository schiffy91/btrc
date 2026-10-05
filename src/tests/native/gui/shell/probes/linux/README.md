# Linux shell diagnostics

`ShellProbe.c` injects and observes native input for the portable shell fixture.
The SDL controls are drawn views; its accessibility report explicitly says
`no bridge`. Zero native handles counts SDL windows, not every allocation in
SDL, the compositor or the graphics driver.

## Clipboard requestor lifetime

`ClipboardRequestor.c` forces an X11 clipboard lifetime race without BTRC or a
provider implementation. SDL owns the clipboard. A second X11 connection sends
a `TARGETS` conversion request, then destroys the requesting window before SDL
pumps its queued request. `XSync` on the second connection orders request and
destruction before owner dispatch; there is no timing-based sleep.

```sh
mkdir -p build/ui-shell
cc -std=c11 -Wall -Wextra -Werror -O2 \
  src/tests/native/gui/shell/probes/linux/ClipboardRequestor.c \
  $(pkg-config --cflags --libs sdl3 x11) -o build/ui-shell/ClipboardRequestor
tools/ui/headless-session.sh --x11 -- build/ui-shell/ClipboardRequestor 0
tools/ui/headless-session.sh --x11 -- build/ui-shell/ClipboardRequestor 1
```

Run through the pinned Nix shell. The live-requestor control exits 0. With SDL
3.4.10, the destroyed-requestor case exits 1 with `BadWindow`, opcode 18
(`X_ChangeProperty`), naming the destroyed requestor. A ten-second alarm bounds
setup and dispatch. SDL's clipboard handler changes the requestor property and
synchronizes without handling that peer's lifetime ending. The dependency owner
must repair that path without globally swallowing unrelated X errors.

This matches the signature of the concurrent `LinuxGUIControls` clipboard test
failure and supplies a deterministic interleaving. It does not retroactively
prove the call stack of the earlier CI failure; that log retained only the X11
error. No provider race is waived by this narrower reproduction.

## Pending Wayland dispatch

`LibdecorPending.c` isolates a dependency failure seen while showing a restored
shell on Weston headless. It creates a libdecor context, queues a Wayland sync
reply without dispatching it, then calls `libdecor_dispatch(-1)`. A three-second
watchdog distinguishes failure to deliver the callback from delivery followed
by a blocked dispatcher. It does not patch libdecor, suppress decorations or
change the shell's timeouts.

From the repository root, build using the pinned libdecor and Wayland development
headers:

```sh
mkdir -p build/ui-shell
cc -std=c11 -Wall -Wextra -Werror -O2 \
  src/tests/native/gui/shell/probes/linux/LibdecorPending.c \
  $(pkg-config --cflags --libs libdecor-0 wayland-client) -o build/ui-shell/LibdecorPending
tools/ui/headless-session.sh --wayland -- build/ui-shell/LibdecorPending -1
tools/ui/headless-session.sh --wayland -- build/ui-shell/LibdecorPending 0
```

Run these commands through the repository's Nix development shell. If that
shell lacks libdecor development headers, obtain the same pinned source and
headers through Nix; do not substitute a different libdecor release.
At base `72592d36`, the following fallback was tested with the shell's existing
libdecor 0.2.5 runtime:

```sh
nix build --no-link /nix/store/zm0hkyn0aimcam5my4r9pg7imxm15y7m-source.drv^out
cc -std=c11 -Wall -Wextra -Werror -O2 \
  $(pkg-config --cflags wayland-client) \
  -I/nix/store/f670s14b96k4m134g108zm079mxx3zly-source/src \
  src/tests/native/gui/shell/probes/linux/LibdecorPending.c \
  /nix/store/9l5rmzfwgh07dainwwkcsg3i25i45kvm-libdecor-0.2.5/lib/libdecor-0.so.0 \
  $(pkg-config --libs wayland-client) -o build/ui-shell/LibdecorPending
```

These store paths identify the tested dependency, not a replacement package
pin. Re-resolve matching source and runtime paths if the repository pin changes.

The `-1` call reproduces the SDL window-show wait. Its failure exits 1 after
printing `sync callback delivered` and `FAIL: callback delivered; libdecor
dispatch still blocked`. Exit 2 denotes setup or callback-delivery failure.
The `0` call is a diagnostic control, not a proposed production workaround.

In libdecor 0.2.5, GTK's `libdecor_plugin_gtk_dispatch` dispatches pending events
in its prepare-read loop and then polls unconditionally with the caller's
timeout. SDL 3.4.10 calls it with -1 while waiting for the initial configure.
When the configure callback is already pending, the dispatcher can complete
that callback and wait forever for an unrelated new event before returning.
The dependency owner must repair this and rerun the unchanged shell gate.

## Event-batch boundary

The intentionally failing `LinuxEventBoundary.btrc` fixture and its driver live
only on `codex/cx-uia-11-e40-repro`, under D24. They must not merge until the
provider fix lands. The reproduction submits 4,095, 4,096, 4,097 and 8,193 events
and checks ordinary keys, a release, committed text and a close request in
separate trials. It does not qualify sustained-load responsiveness or fairness.

In a checkout of that reproduction branch, run:

```sh
BTRC_TEST_RUNNER=linux-devcontainer nix develop --command \
  tools/ui/headless-session.sh --x11 -- \
  python3 -m pytest src/tests/python/test_native_ui_shell_linux.py \
  -k event_boundary -q -ra
```

Both frontends are selected by the fixture. A boundary failure is an assertion
failure with an `E40` line reporting submitted events, delivery counts, queue
depth and the first mismatched key ordinal. It is never an expected-failure
marker or a skipped test. The close row permits cancellation of an ordered
suffix after closure, while requiring all keys preceding the close request.
