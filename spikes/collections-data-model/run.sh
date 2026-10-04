#!/usr/bin/env bash
set -euo pipefail
frontend="${1:?reference or selfhost}"
out="build/collections-spike/$frontend"
mkdir -p "$out"
case "$frontend" in
  reference) compiler=(python3 -m src.compiler.python.main) ;;
  selfhost) compiler=("${2:?current main btrcc}") ;;
  *) exit 2 ;;
esac
"${compiler[@]}" --no-cache spikes/collections-data-model/Collections.btrc -o "$out/Program.c" > "$out/compile.log" 2>&1
cc -std=c11 -pedantic-errors -Wall -Wextra -Werror -O1 -g \
  -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer \
  "$out/Program.c" -o "$out/Program" -lm -lpthread > "$out/link.log" 2>&1
ASAN_OPTIONS=detect_leaks=1 "$out/Program" > "$out/run.log" 2>&1
cat "$out/run.log"
