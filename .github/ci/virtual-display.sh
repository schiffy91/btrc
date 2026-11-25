#!/usr/bin/env bash
# Run a command with a display and a GPU adapter where the host has neither,
# as GitHub's Linux runners do not:
#
#   .github/ci/virtual-display.sh make NIX= test-shard-unit
#
# The dev shell names Mesa's software Vulkan driver (lavapipe), the Vulkan
# loader that wgpu-native dlopens, and Mesa's EGL: wgpu-native probes OpenGL
# too, and a host GPU vendor's EGL can abort on a display it does not drive.
# The display is .github/ci/headless-session.sh
# in Wayland mode: a private labwc headless compositor inside its own D-Bus
# session bus with the AT-SPI accessibility bus. BTRC_VIRTUAL_DISPLAY=x11
# selects that script's Xvfb session instead. A shell without the session's
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
  if [[ -n "${BTRC_MESA_EGL:-}" && -f "$BTRC_MESA_EGL" && -z "${__EGL_VENDOR_LIBRARY_FILENAMES:-}" ]]; then
    export __EGL_VENDOR_LIBRARY_FILENAMES="$BTRC_MESA_EGL"
  fi
fi
session="${BTRC_VIRTUAL_DISPLAY:-wayland}"
if [[ "$session" == wayland && -n "${BTRC_WAYLAND_CLIENT_LIB:-}" && -d "$BTRC_WAYLAND_CLIENT_LIB" ]]; then
  export LD_LIBRARY_PATH="${BTRC_WAYLAND_CLIENT_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
case "$session" in
  x11) server=Xvfb ;;
  wayland) server=labwc ;;
  *)
    echo "virtual-display: BTRC_VIRTUAL_DISPLAY must be x11 or wayland, not $session" >&2
    exit 2
    ;;
esac
if command -v "$server" >/dev/null && command -v dbus-daemon >/dev/null; then
  # Sourced, not executed: in the devcontainer every new bash re-reads the dev
  # shell through BASH_ENV, which nests one more nix-shell.* directory into
  # TMPDIR. One more level pushes the corpus's unix-socket paths under TMPDIR
  # past sun_path's 108 bytes. The script exits with the command's status.
  # shellcheck source=headless-session.sh
  source "$(dirname "${BASH_SOURCE[0]}")/headless-session.sh" "--$session" -- "$@"
fi
if ! command -v xvfb-run >/dev/null; then
  exec "$@"
fi
export GDK_BACKEND=x11
exec xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24 -nolisten tcp -noreset" "$@"
