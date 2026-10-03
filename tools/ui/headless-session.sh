#!/usr/bin/env bash
# Run a command inside a private headless GUI session on Linux:
#
#   tools/ui/headless-session.sh --x11 -- python -m pytest src/tests/python/test_native_linux_providers.py -k gui
#   tools/ui/headless-session.sh --wayland -- ./hello-gtk4
#
# The session is a D-Bus session bus (dbus-run-session) carrying the AT-SPI
# accessibility bus, plus one display server:
#
#   --x11      Xvfb on a free display number, started with -noreset: by
#              default Xvfb resets whenever its last client leaves, and a test
#              window that connects during that reset fails to open.
#   --wayland  weston's headless backend with the pixman renderer, on its own
#              socket, without a panel or an idle timeout.
#
# The command sees DISPLAY or WAYLAND_DISPLAY (never both), SDL_VIDEODRIVER and
# GDK_BACKEND pinned to that protocol so neither toolkit probes the other, and
# Mesa's software Vulkan driver (lavapipe) when the dev shell names it and the
# caller chose no Vulkan driver. When the command exits, everything the session
# started is stopped and its directory removed; the command's status is the
# script's. A server that fails to start has its log printed.
#
# The dev shell provides every tool (flake.nix): Xvfb, weston, dbus-run-session
# and BTRC_ATSPI_LIBEXEC. Without the AT-SPI launcher the session still runs,
# without an accessibility bus, and the native-atspi capability gate says why.
set -euo pipefail

readonly SCREEN_WIDTH=1280
readonly SCREEN_HEIGHT=1024
# Tenths of a second to wait for a server before giving up.
readonly START_TICKS=300

usage() {
  echo "usage: $0 --x11|--wayland -- <command> [args...]" >&2
  exit 2
}

fail() {
  echo "headless-session: $*" >&2
  exit 1
}

mode=""
while (($#)); do
  case "$1" in
    --x11 | --wayland)
      [[ -z "$mode" ]] || usage
      mode="${1#--}"
      shift
      ;;
    --)
      shift
      break
      ;;
    *) usage ;;
  esac
done
[[ -n "$mode" && $# -gt 0 ]] || usage
[[ "$(uname -s)" == Linux ]] || fail "headless GUI sessions are Linux-only"

# First pass: re-run this script on a private session bus. dbus-run-session
# stops that bus when the script exits. The marker is cleared at once, so a
# command that starts a nested session gets a bus of its own.
if [[ "${BTRC_HEADLESS_SESSION_STAGE:-}" != bus ]]; then
  command -v dbus-run-session >/dev/null || fail "dbus-run-session is not installed"
  # Nix's dbus looks for its configuration under /etc, which a container
  # lacks; use the session configuration installed beside the daemon.
  configuration=()
  if daemon="$(command -v dbus-daemon)"; then
    shipped="$(dirname "$(readlink -f "$daemon")")/../share/dbus-1/session.conf"
    [[ -f "$shipped" ]] && configuration=(--config-file="$shipped")
  fi
  BTRC_HEADLESS_SESSION_STAGE=bus exec dbus-run-session ${configuration[@]+"${configuration[@]}"} \
    -- bash "${BASH_SOURCE[0]}" "--$mode" -- "$@"
fi
unset BTRC_HEADLESS_SESSION_STAGE

session="$(mktemp -d "${TMPDIR:-/tmp}/btrc-headless.XXXXXX")"
pids=()
teardown() {
  local pid
  for pid in ${pids[@]+"${pids[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in ${pids[@]+"${pids[@]}"}; do
    wait "$pid" 2>/dev/null || true
  done
  rm -rf -- "$session"
}
trap teardown EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# weston and the AT-SPI launcher need a private, user-only runtime directory.
if [[ -z "${XDG_RUNTIME_DIR:-}" || ! -w "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="$session/runtime"
  mkdir -m 0700 "$XDG_RUNTIME_DIR"
fi

# Wait for `$1` (a predicate command) while process `$2` lives; print `$3` on failure.
await() {
  local predicate="$1" pid="$2" log="$3" tick
  for ((tick = 0; tick < START_TICKS; tick++)); do
    if eval "$predicate"; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
  [[ -f "$log" ]] && cat "$log" >&2
  return 1
}

# The accessibility bus. GTK and pyatspi find it through org.a11y.Bus on the
# session bus, and the registry daemon is activated on it on first use.
launcher="${BTRC_ATSPI_LIBEXEC:+$BTRC_ATSPI_LIBEXEC/at-spi-bus-launcher}"
if [[ -n "$launcher" && -x "$launcher" ]]; then
  "$launcher" --launch-immediately >"$session/atspi.log" 2>&1 &
  pids+=("$!")
  # NameHasOwner, unlike a call to the bus itself, never activates a second launcher.
  await 'dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus \
    org.freedesktop.DBus.NameHasOwner string:org.a11y.Bus 2>/dev/null | grep -q "boolean true"' \
    "$!" "$session/atspi.log" || fail "the AT-SPI bus did not start"
else
  echo "headless-session: no AT-SPI bus: BTRC_ATSPI_LIBEXEC does not name at-spi-bus-launcher" >&2
fi

case "$mode" in
  x11)
    command -v Xvfb >/dev/null || fail "Xvfb is not installed"
    # -displayfd picks a free display number and writes it once listening.
    Xvfb -displayfd 3 -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x24" -nolisten tcp -noreset \
      3>"$session/display" >"$session/xvfb.log" 2>&1 &
    pids+=("$!")
    await '[[ -s "$session/display" ]]' "$!" "$session/xvfb.log" || fail "Xvfb did not start"
    unset WAYLAND_DISPLAY
    export DISPLAY=":$(tr -d '[:space:]' <"$session/display")"
    export SDL_VIDEODRIVER=x11 GDK_BACKEND=x11
    ;;
  wayland)
    command -v weston >/dev/null || fail "weston is not installed"
    socket="btrc-wayland-$$"
    printf '%s\n' '[core]' 'idle-time=0' '[shell]' 'panel-position=none' 'locking=false' \
      '[input-method]' 'path=' >"$session/weston.ini"
    weston --backend=headless --renderer=pixman --width="$SCREEN_WIDTH" --height="$SCREEN_HEIGHT" \
      --socket="$socket" --config="$session/weston.ini" --log="$session/weston.log" \
      >"$session/weston.out" 2>&1 &
    pids+=("$!")
    await '[[ -S "$XDG_RUNTIME_DIR/$socket" ]]' "$!" "$session/weston.log" || fail "weston did not start"
    unset DISPLAY
    export WAYLAND_DISPLAY="$socket"
    export SDL_VIDEODRIVER=wayland GDK_BACKEND=wayland
    ;;
esac

if [[ -n "${BTRC_LAVAPIPE_ICD:-}" && -f "$BTRC_LAVAPIPE_ICD" && -z "${VK_DRIVER_FILES:-}${VK_ICD_FILENAMES:-}" ]]; then
  export VK_DRIVER_FILES="$BTRC_LAVAPIPE_ICD"
  export LD_LIBRARY_PATH="${BTRC_VULKAN_LOADER:+$BTRC_VULKAN_LOADER${LD_LIBRARY_PATH:+:}}${LD_LIBRARY_PATH:-}"
fi

status=0
"$@" || status=$?
exit "$status"
