#!/usr/bin/env bash
# Run a command with a display and a GPU adapter where the host has neither,
# as GitHub's Linux runners do not:
#
#   tools/virtual-display.sh make NIX= test-shard-unit
#
# The dev shell names Mesa's software Vulkan driver (lavapipe) and the Vulkan
# loader that wgpu-native dlopens. The display is tools/ui/headless-session.sh
# in X11 mode: a private Xvfb started with -noreset, inside its own D-Bus
# session bus with the AT-SPI accessibility bus, and SDL and GDK pinned to X11
# so neither probes a missing Wayland compositor. BTRC_VIRTUAL_DISPLAY=wayland
# selects that script's weston session instead. A shell without the session's
# tools falls back to xvfb-run, which gives an X display alone. A
# session that already has a display keeps it and its own GPU driver. Where the
# tools are missing (macOS, a shell without them) the command runs without
# them, so the display and adapter tests skip exactly as they would without
# this wrapper.
set -euo pipefail

if [[ "$(uname -s)" != Linux || -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  exec "$@"
fi
if [[ -n "${BTRC_LAVAPIPE_ICD:-}" && -f "$BTRC_LAVAPIPE_ICD" && -z "${VK_DRIVER_FILES:-}${VK_ICD_FILENAMES:-}" ]]; then
  export VK_DRIVER_FILES="$BTRC_LAVAPIPE_ICD"
  export LD_LIBRARY_PATH="${BTRC_VULKAN_LOADER:+$BTRC_VULKAN_LOADER${LD_LIBRARY_PATH:+:}}${LD_LIBRARY_PATH:-}"
fi
session="${BTRC_VIRTUAL_DISPLAY:-x11}"
case "$session" in
  x11) server=Xvfb ;;
  wayland) server=weston ;;
  *)
    echo "virtual-display: BTRC_VIRTUAL_DISPLAY must be x11 or wayland, not $session" >&2
    exit 2
    ;;
esac
if command -v "$server" >/dev/null && command -v dbus-daemon >/dev/null; then
  exec "$(dirname "${BASH_SOURCE[0]}")/ui/headless-session.sh" "--$session" -- "$@"
fi
if ! command -v xvfb-run >/dev/null; then
  exec "$@"
fi
export SDL_VIDEODRIVER=x11
exec xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24 -nolisten tcp -noreset" "$@"
