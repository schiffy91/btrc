#!/usr/bin/env bash
# Build the gate spike into build/gtk4-gate (or the directory given).
# Run inside `nix develop --impure -f docs/design/native-ui-gtk4-gate/shell.nix`.
set -euo pipefail
source="$(cd "$(dirname "$0")" && pwd)"
out="${1:-build/gtk4-gate}"
mkdir -p "$out"
protocols=$(pkg-config --variable=pkgdatadir wayland-protocols)
wayland-scanner client-header "$protocols/stable/viewporter/viewporter.xml" "$out/viewporter-client-protocol.h"
wayland-scanner private-code "$protocols/stable/viewporter/viewporter.xml" "$out/viewporter-protocol.c"
cc -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter -I"$out" "$source/gate.c" "$out/viewporter-protocol.c" -o "$out/gate" \
  $(pkg-config --cflags --libs gtk4 gtk4-wayland webkitgtk-6.0 wayland-client wgpu-native)
