#!/usr/bin/env bash
# Run a command with a display and a GPU adapter where the host has neither,
# as GitHub's Linux runners do not:
#
#   tools/virtual-display.sh make NIX= test-shard-unit
#
# The dev shell names Mesa's software Vulkan driver (lavapipe) and the Vulkan
# loader that wgpu-native dlopens; xvfb-run starts a private X server, and SDL
# is pinned to X11 so it never probes a missing Wayland compositor. The server
# runs with -noreset: by default Xvfb resets whenever its last client leaves,
# and a test window that connects during that reset fails to open. A session
# that already has a display keeps it and its own GPU driver. Where the tools
# are missing (macOS, a shell without them) the command runs without them, so
# the display and adapter tests skip exactly as they would without this wrapper.
set -euo pipefail

if [[ "$(uname -s)" != Linux || -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  exec "$@"
fi
if [[ -n "${BTRC_LAVAPIPE_ICD:-}" && -f "$BTRC_LAVAPIPE_ICD" && -z "${VK_DRIVER_FILES:-}${VK_ICD_FILENAMES:-}" ]]; then
  export VK_DRIVER_FILES="$BTRC_LAVAPIPE_ICD"
  export LD_LIBRARY_PATH="${BTRC_VULKAN_LOADER:+$BTRC_VULKAN_LOADER${LD_LIBRARY_PATH:+:}}${LD_LIBRARY_PATH:-}"
fi
if ! command -v xvfb-run >/dev/null; then
  exec "$@"
fi
export SDL_VIDEODRIVER=x11
exec xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24 -nolisten tcp -noreset" "$@"
