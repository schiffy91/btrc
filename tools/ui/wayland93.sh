#!/usr/bin/env bash
# Branch-only hosted diagnostic; never part of an integrated gate.
set -euo pipefail
# The container's initial Bash has already loaded its pinned dev environment.
# Do not reload it in nested shells and replace explicit reader/debugger paths.
unset BASH_ENV PYTEST_ADDOPTS BTRC_TEST_BTRCC
test "$(uname -m)" = x86_64
export BTRC_WAYLAND93_OUTPUT="$PWD/build/wayland93/evidence"
mkdir -p build/wayland93
mkdir "$BTRC_WAYLAND93_OUTPUT"
trap 'chmod -R a+rX build/wayland93 build/ui-shell 2>/dev/null || true' EXIT
gdb_store=$(nix build --no-link --print-out-paths --impure --expr \
  '(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.x86_64-linux.gdb')
export BTRC_WAYLAND93_GDB="$gdb_store/bin/gdb"
reader_store=$(nix build --no-link --print-out-paths .#btrc-native-header)
export BTRC_NATIVE_HEADER_READER="$reader_store/bin/btrc-native-header"
test -x "$BTRC_WAYLAND93_GDB"
test -x "$BTRC_NATIVE_HEADER_READER"
export BTRC_WAYLAND93_DIAGNOSTIC=1 BTRC_UI_SHELL_CYCLES=100
export BTRC_TEST_RUNNER=linux-devcontainer BTRC_TEST_TRANSPILE_TIMEOUT=600
export BTRC_VIRTUAL_DISPLAY=wayland PYTHONPYCACHEPREFIX=/tmp/btrc-pycache
make NIX= gpu-required
bash tools/virtual-display.sh python3 -m tools.ui.wayland93
