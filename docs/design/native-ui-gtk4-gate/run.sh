#!/usr/bin/env bash
# Run the built gate spike in a private headless Weston, print its frame
# timings and leave a screenshot in the output directory.
#   RENDERER=pixman  software everywhere (the default)
#   RENDERER=gl      Weston composites on the host's GPU and wgpu renders on it
#   GATE_FRAMES=N    frames to run (default 1860: one second of start-up, then 30)
set -uo pipefail
out="$(cd "${1:-build/gtk4-gate}" && pwd)"
renderer="${RENDERER:-pixman}"
cd "$out"
export XDG_RUNTIME_DIR="$out/runtime-$renderer"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
# The spike runs in its own process group, so its bus daemons end with it.
trap 'kill -- -$gate 2>/dev/null; kill $weston 2>/dev/null; wait 2>/dev/null; fusermount3 -u "$XDG_RUNTIME_DIR/doc" 2>/dev/null' EXIT
unset DISPLAY
printf '%s\n' '[shell]' 'panel-position=none' 'locking=false' '[core]' 'idle-time=0' > "$XDG_RUNTIME_DIR/weston.ini"
weston --backend=headless --renderer="$renderer" --fake-seat --width=1024 --height=768 --socket=gate-0 --debug \
  --config="$XDG_RUNTIME_DIR/weston.ini" --log="$out/weston-$renderer.log" >"weston-$renderer.out" 2>&1 &
weston=$!
for _ in $(seq 100); do [ -S "$XDG_RUNTIME_DIR/gate-0" ] && break; sleep 0.1; done
export WAYLAND_DISPLAY=gate-0 GDK_BACKEND=wayland WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1
if [ "$renderer" = pixman ]; then
  export VK_ICD_FILENAMES="${BTRC_LAVAPIPE_ICD:-}" VK_DRIVER_FILES="${BTRC_LAVAPIPE_ICD:-}" GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1
fi
GATE_HOLD=1 GATE_FRAMES="${GATE_FRAMES:-1860}" setsid dbus-run-session -- ./gate >"gate-$renderer.out" 2>"gate-$renderer.err" &
gate=$!
for _ in $(seq 900); do grep -q 'GATE measured=' "gate-$renderer.err" 2>/dev/null && break; kill -0 $gate 2>/dev/null || break; sleep 0.2; done
sleep 1
weston-screenshooter >"shot-$renderer.out" 2>&1
grep GATE "gate-$renderer.err"
