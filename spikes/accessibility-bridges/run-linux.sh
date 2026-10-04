#!/usr/bin/env bash
set -euo pipefail
# Run in the pinned nix develop shell from the repository root.
frontend="${1:?reference or selfhost}"
out="build/accessibility-spike/$frontend"
mkdir -p "$out"
case "$frontend" in
  reference) compiler=(python3 -m src.compiler.python.main) ;;
  selfhost) compiler=("${2:?path to current-main btrcc}") ;;
  *) exit 2 ;;
esac
"${compiler[@]}" --no-cache spikes/accessibility-bridges/linux/src/Main.btrc -o "$out/Program.c" > "$out/compile.log" 2>&1
cc -std=c11 -pedantic-errors -Wall -Wextra -Werror -O2 "$out/Program.c" -o "$out/Program" \
  $(pkg-config --cflags --libs dbus-1) -lm -lpthread > "$out/link.log" 2>&1
tools/ui/headless-session.sh --x11 -- python3 spikes/accessibility-bridges/linux/capture.py \
  "$out/Program" "$out/tree.json" > "$out/capture.log" 2>&1
cat "$out/capture.log"
