#!/usr/bin/env bash
# Run from the repository root inside the pinned nix develop shell.
set -euo pipefail
protocol="${1:?x11 or wayland}"
route="${2:?cpu, x11-child, wayland-subsurface, or dmabuf}"
cycles="${3:-1}"
variant="${4:-plain}"
out="build/gtk4-spike/$protocol/$route-$variant"
mkdir -p "$out"
flags=()
if [[ "$variant" == asan ]]; then
  flags=(-fsanitize=address,undefined -fno-omit-frame-pointer)
elif [[ "$variant" != plain ]]; then
  exit 2
fi
# GTK4 4.22 deprecates the entire X11 backend. Keep its warnings visible:
# probing that still-supported API is intentional, not production policy.
cc -std=c11 -Wall -Wextra -Werror -Wno-error=deprecated-declarations -O1 -g \
  "${flags[@]}" spikes/gtk4-webgpu/Probe.c -o "$out/Probe" \
  $(pkg-config --cflags --libs gtk4 wgpu-native wayland-client x11) > "$out/build.log" 2>&1
tools/ui/headless-session.sh "--$protocol" -- bash -c '
  out=$1; route=$2; cycles=$3
  "$out/Probe" "$route" "$cycles" 12 "$out" > "$out/probe.log" 2>&1 &
  probe_pid=$!
  trap '\''kill "$probe_pid" 2>/dev/null || true'\'' EXIT
  if [[ "$route" == cpu ]]; then
    python3 spikes/gtk4-webgpu/Atspi.py "$out/atspi.json" > "$out/atspi.log" 2>&1 || atspi_status=$?
    printf "AT-SPI exit=%s\n" "${atspi_status:-0}" >> "$out/atspi.log"
  fi
  status=0
  wait "$probe_pid" || status=$?
  trap - EXIT
  if [[ "$status" == 0 ]]; then status=${atspi_status:-0}; fi
  exit "$status"
' _ "$out" "$route" "$cycles"
