#!/usr/bin/env bash
# Run a gate on a desktop without letting it reach the session it is started
# from, which is how the native Linux runner is qualified
# (.github/ci/expected-skips/linux.json):
#
#   .github/ci/headless-gate.sh nix develop --command make NIX= test
#
# The command gets a fresh environment instead of the caller's:
#
#   * no DISPLAY or WAYLAND_DISPLAY, so the GUI suites skip instead of opening
#     windows on the desktop, and the real-desktop session check does not run;
#   * a private, empty XDG_RUNTIME_DIR: the session's own holds its Wayland,
#     PipeWire and D-Bus sockets, and a client with no WAYLAND_DISPLAY still
#     tries wayland-0 there. Its path is short because a socket path under it
#     must fit sun_path's 108 bytes;
#   * none of the caller's compiler variables. Started from inside another
#     Nix shell, a build inherits that shell's CPATH and compiles against its
#     headers while linking this repository's libraries.
#
# The directory is removed when the command ends, and the command's status
# is this script's.
set -euo pipefail

if (($# == 0)); then
  echo "usage: .github/ci/headless-gate.sh <command> [args...]" >&2
  exit 64
fi

user="$(id -un)"
runtime="$(mktemp -d /tmp/btrc-rt.XXXXXX)"
trap 'rm -rf "$runtime"' EXIT
path="/run/wrappers/bin:/run/current-system/sw/bin:$HOME/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/bin:/bin"

status=0
env -i HOME="$HOME" USER="$user" LOGNAME="$user" PATH="$path" TERM="${TERM:-dumb}" LANG=C.UTF-8 \
  XDG_RUNTIME_DIR="$runtime" "$@" || status=$?
exit "$status"
