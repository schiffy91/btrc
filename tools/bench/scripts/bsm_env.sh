#!/bin/bash
# Run a command inside BTRSmith's dev shell with the measurement environment.
#
#   bsm_env.sh '<shell command>'      one argument: evaluated by bash
#   bsm_env.sh <program> [args...]    several: executed as given
#
# Inside, PKG_CONFIG_PATH names BTRSmith's packages and BTRC_NATIVE_HEADER_READER,
# BTRC_NATIVE_TARGET and BTRC_NATIVE_SYSROOT name the native header reader, and
# BSM_ENV_ACTIVE=1 lets a script re-execute itself here exactly once.
#
#   BTRC_BENCH_HOME      measurement root (default ~/.cache/btrc)
#   BTRSMITH_DEV_SHELL   flake or saved profile for `nix develop`
#                        (default $BTRC_BENCH_HOME/gcroots/btrsmith-dev)
#   BSM_PKG_CONFIG_PATH  file holding the PKG_CONFIG_PATH to measure with (default
#                        $BTRC_BENCH_HOME/measure/bsm-pkg-config-path.txt; the
#                        shell's own when the file is absent)
#   READER               native header reader (default: the one the September
#                        2026 baselines used; pass the btrc tree's own reader,
#                        e.g. from its dev shell, when its protocol changed)
#   BTRC_NATIVE_TARGET   reader target (default arm64-apple-macosx14.0.0)
#   BTRC_NATIVE_SYSROOT  reader SDK (default the dev shell's SDKROOT)
set -u
CACHE=${BTRC_BENCH_HOME:-$HOME/.cache/btrc}
export BSM_PKG_CONFIG_PATH=${BSM_PKG_CONFIG_PATH:-$CACHE/measure/bsm-pkg-config-path.txt}
export READER=${READER:-/nix/store/59q7479idh1jsgv41y5ckmn7nc4bqnh4-btrc-native-header-0/bin/btrc-native-header}
nix develop "${BTRSMITH_DEV_SHELL:-$CACHE/gcroots/btrsmith-dev}" --command bash -c '
if [ -f "$BSM_PKG_CONFIG_PATH" ]; then PKG_CONFIG_PATH="$(cat "$BSM_PKG_CONFIG_PATH")"; export PKG_CONFIG_PATH; fi
export BTRC_NATIVE_HEADER_READER="$READER"
export BTRC_NATIVE_TARGET="${BTRC_NATIVE_TARGET:-arm64-apple-macosx14.0.0}"
export BTRC_NATIVE_SYSROOT="${BTRC_NATIVE_SYSROOT:-${SDKROOT:-}}"
export BSM_ENV_ACTIVE=1
if [ $# -eq 1 ]; then eval "$1"; else exec "$@"; fi' _ "$@" 2>&1 \
  | grep --line-buffered -v "^warning: \(Git tree\|ignoring\)\|copying path\|fetched\|unpacking"
exit "${PIPESTATUS[0]}"
