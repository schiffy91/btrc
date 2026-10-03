#!/usr/bin/env bash
# Run a command inside a private headless GUI session on Linux:
#
#   tools/ui/headless-session.sh --x11 -- python -m pytest src/tests/python/test_native_linux_providers.py -k gui
#   tools/ui/headless-session.sh --wayland -- ./hello-gtk4
#
# The session is a private D-Bus session bus carrying the AT-SPI accessibility
# bus, plus one display server:
#
#   --x11      Xvfb on a free display number, started with -noreset: by
#              default Xvfb resets whenever its last client leaves, and a test
#              window that connects during that reset fails to open.
#   --wayland  weston's headless backend with the pixman renderer, on its own
#              socket, without a panel or an idle timeout. Its fake seat gives
#              clients a keyboard and pointer: without a seat there is no
#              Wayland clipboard, so a text field's copy and paste do nothing.
#
# The command sees DISPLAY or WAYLAND_DISPLAY (never both), SDL_VIDEODRIVER and
# GDK_BACKEND pinned to that protocol so neither toolkit probes the other, and
# Mesa's software Vulkan driver (lavapipe) when the dev shell names it and the
# caller chose no Vulkan driver. Its XDG_RUNTIME_DIR is the session's own: the
# AT-SPI bus always binds <runtime>/at-spi/bus, so two sessions sharing one
# directory would replace, and on exit delete, each other's socket.
#
# This script is the session's only owner, rather than a child of
# dbus-run-session, so a TERM sent to the PID its caller holds reaches it: it
# passes TERM (and INT) to the command, then stops the servers and the bus and
# removes the session's directory. The command's status is the script's.
# tools/virtual-display.sh sources it, so it must always end in exit. A
# server that fails to start has its log printed.
#
# The dev shell provides every tool (flake.nix): dbus-daemon, Xvfb, weston and
# BTRC_ATSPI_LIBEXEC. Without a working AT-SPI launcher the session still runs,
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
command -v dbus-daemon >/dev/null || fail "dbus-daemon is not installed"

session="$(mktemp -d "${TMPDIR:-/tmp}/btrc-headless.XXXXXX")"
# Started processes, stopped in reverse order: the command, the display, the
# accessibility bus and last the session bus they all talk to.
pids=()
command_pid=""
teardown() {
  local index
  [[ -z "$command_pid" ]] || kill -TERM "$command_pid" 2>/dev/null || true
  for ((index = ${#pids[@]} - 1; index >= 0; index--)); do
    kill "${pids[index]}" 2>/dev/null || true
    wait "${pids[index]}" 2>/dev/null || true
  done
  rm -rf -- "$session"
}
trap teardown EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

export XDG_RUNTIME_DIR="$session/runtime"
mkdir -m 0700 "$XDG_RUNTIME_DIR"

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

# The session bus. Nix's dbus looks for its configuration under /etc, which a
# container lacks, so use the session configuration installed beside the daemon.
configuration=(--session)
shipped="$(dirname "$(readlink -f "$(command -v dbus-daemon)")")/../share/dbus-1/session.conf"
[[ -f "$shipped" ]] && configuration=(--config-file="$shipped")
dbus-daemon "${configuration[@]}" --nofork --nopidfile --print-address=3 \
  3>"$session/bus" >"$session/dbus.log" 2>&1 &
pids+=("$!")
await '[[ -s "$session/bus" ]]' "$!" "$session/dbus.log" || fail "the session bus did not start"
DBUS_SESSION_BUS_ADDRESS="$(head -n 1 "$session/bus")"
export DBUS_SESSION_BUS_ADDRESS

# The accessibility bus. GTK and pyatspi find it through org.a11y.Bus on the
# session bus, and the registry daemon is activated on it on first use.
launcher="${BTRC_ATSPI_LIBEXEC:+$BTRC_ATSPI_LIBEXEC/at-spi-bus-launcher}"
if [[ -n "$launcher" && -x "$launcher" ]]; then
  "$launcher" --launch-immediately >"$session/atspi.log" 2>&1 &
  pids+=("$!")
  # NameHasOwner, unlike a call to the bus itself, never activates a second launcher.
  if ! await 'dbus-send --session --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus \
    org.freedesktop.DBus.NameHasOwner string:org.a11y.Bus 2>/dev/null | grep -q "boolean true"' \
    "$!" "$session/atspi.log"; then
    echo "headless-session: the AT-SPI bus did not start; continuing without it" >&2
  fi
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
    weston --backend=headless --renderer=pixman --fake-seat --width="$SCREEN_WIDTH" --height="$SCREEN_HEIGHT" \
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

# The command runs in the background so a signal interrupts `wait` and is passed
# on at once. Without job control bash would give it /dev/null as its input and
# make it ignore INT, so it reads the caller's input explicitly and an INT
# reaches it as TERM.
exec 3<&0
"$@" <&3 3<&- &
command_pid=$!
exec 3<&-
trap 'kill -TERM "$command_pid" 2>/dev/null || true' TERM INT
status=0
while :; do
  wait "$command_pid" && status=0 || status=$?
  kill -0 "$command_pid" 2>/dev/null || break
done
command_pid=""
exit "$status"
