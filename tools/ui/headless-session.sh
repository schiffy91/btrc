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
#   --wayland  labwc, a wlroots compositor, on its headless backend with the
#              pixman renderer. A test can send real input in it: it offers
#              the virtual pointer, virtual keyboard and foreign-toplevel
#              protocols. It centres each new window. Its Xwayland starts
#              only when an X client connects, and the command is given no
#              DISPLAY.
#
# The command sees DISPLAY or WAYLAND_DISPLAY (never both), GDK_BACKEND pinned
# to that protocol so GTK does not probe the other,
# BTRC_UI_SESSION naming the mode and BTRC_UI_PRIVATE_SESSION=1, which tells a
# test that the display's one pointer and keyboard are its own to drive, and
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
# The dev shell provides every tool (flake.nix): dbus-daemon, Xvfb, labwc and
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
  local status=$? index log
  [[ -z "$command_pid" ]] || kill -TERM "$command_pid" 2>/dev/null || true
  for ((index = ${#pids[@]} - 1; index >= 0; index--)); do
    kill "${pids[index]}" 2>/dev/null || true
    wait "${pids[index]}" 2>/dev/null || true
  done
  # A compositor may abort after readiness. Keep its diagnostic before removing
  # the private session, including when the client reports only a broken pipe.
  if ((status != 0)); then
    for log in "$session"/*.log "$session"/*.out; do
      [[ -f "$log" ]] || continue
      printf 'headless-session: %s (last 200 lines)\n' "${log##*/}" >&2
      tail -n 200 "$log" >&2 || true
    done
  fi
  # A desktop portal the session bus activated mounts its document store at
  # <runtime>/doc and unmounts it as it exits with the bus. A mount point
  # cannot be removed, so wait for that, and detach it if it never happens.
  for ((index = 0; index < 50; index++)); do
    grep -qsF " $XDG_RUNTIME_DIR/doc " /proc/mounts || break
    sleep 0.1
  done
  if grep -qsF " $XDG_RUNTIME_DIR/doc " /proc/mounts; then
    fusermount3 -u -z "$XDG_RUNTIME_DIR/doc" 2>/dev/null || fusermount -u -z "$XDG_RUNTIME_DIR/doc" 2>/dev/null || true
  fi
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
    export GDK_BACKEND=x11
    ;;
  wayland)
    command -v labwc >/dev/null || fail "labwc is not installed"
    mkdir "$session/labwc"
    printf '%s\n' '<?xml version="1.0"?>' '<labwc_config>' \
      '  <placement><policy>center</policy></placement>' '</labwc_config>' >"$session/labwc/rc.xml"
    # labwc names its own socket: the first free wayland-N in the session's
    # private runtime directory, which holds no other.
    unset DISPLAY WAYLAND_DISPLAY
    WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 \
      WLR_HEADLESS_OUTPUTS=1 \
      labwc -C "$session/labwc" >"$session/labwc.log" 2>&1 &
    pids+=("$!")
    await '[[ -S "$XDG_RUNTIME_DIR/wayland-0" ]]' "$!" "$session/labwc.log" || fail "labwc did not start"
    export WAYLAND_DISPLAY=wayland-0
    export GDK_BACKEND=wayland
    # A headless output is 1280x720 until it is told otherwise, and a window
    # taller than its screen is cut to it.
    command -v wlr-randr >/dev/null || fail "wlr-randr is not installed"
    wlr-randr --output HEADLESS-1 --custom-mode "${SCREEN_WIDTH}x${SCREEN_HEIGHT}" >"$session/output.log" 2>&1 ||
      fail "the Wayland output could not be set to ${SCREEN_WIDTH}x${SCREEN_HEIGHT}: $(cat "$session/output.log")"
    ;;
esac
export BTRC_UI_SESSION="$mode" BTRC_UI_PRIVATE_SESSION=1

# The session's fonts are the dev shell's one family, not the machine's: a
# container has none, and a desktop's own differ from the next one's.
if [[ -n "${BTRC_FONTS_CONFIG:-}" && -f "$BTRC_FONTS_CONFIG" ]]; then
  export FONTCONFIG_FILE="$BTRC_FONTS_CONFIG"
fi
# GTK's file chooser aborts without its settings schema; the dev shell names GTK's own.
if [[ -n "${BTRC_GSETTINGS_SCHEMAS:-}" && -d "$BTRC_GSETTINGS_SCHEMAS" ]]; then
  export GSETTINGS_SCHEMA_DIR="$BTRC_GSETTINGS_SCHEMAS"
fi

if [[ -n "${BTRC_LAVAPIPE_ICD:-}" && -f "$BTRC_LAVAPIPE_ICD" && -z "${VK_DRIVER_FILES:-}${VK_ICD_FILENAMES:-}" ]]; then
  export VK_DRIVER_FILES="$BTRC_LAVAPIPE_ICD"
  export LD_LIBRARY_PATH="${BTRC_VULKAN_LOADER:+$BTRC_VULKAN_LOADER${LD_LIBRARY_PATH:+:}}${LD_LIBRARY_PATH:-}"
  if [[ -n "${BTRC_MESA_EGL:-}" && -f "$BTRC_MESA_EGL" && -z "${__EGL_VENDOR_LIBRARY_FILENAMES:-}" ]]; then
    export __EGL_VENDOR_LIBRARY_FILENAMES="$BTRC_MESA_EGL"
  fi
fi
if [[ "$mode" == wayland && -n "${BTRC_WAYLAND_CLIENT_LIB:-}" && -d "$BTRC_WAYLAND_CLIENT_LIB" ]]; then
  export LD_LIBRARY_PATH="${BTRC_WAYLAND_CLIENT_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
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
