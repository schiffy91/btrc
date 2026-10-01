#!/bin/bash
# Serialize heavy work on this Mac through the shared locks (AGENTS.md "Locks").
#
#   withlock.sh <name> <command...>        hold $BTRC_LOCK_DIR/<name> (macOS lockf)
#   withlock.sh btrcc-build <command...>   a counting semaphore of two slots,
#                                          btrcc-build.1 and btrcc-build.2
#
# BTRC_LOCK_DIR defaults to ~/.cache/btrc/locks, where gate, bench, linux-ci,
# guest, gui-capture and signing live. An unknown name is refused rather than
# created, so a typo cannot bypass a lock.
set -u
dir=${BTRC_LOCK_DIR:-$HOME/.cache/btrc/locks}
name=$1
shift
if [ "$name" = btrcc-build ]; then
  while :; do
    for slot in 1 2; do
      /usr/bin/lockf -s -k -t 0 "$dir/btrcc-build.$slot" "$@" && exit 0
      rc=$?
      [ $rc -ne 75 ] && exit $rc # 75 = EX_TEMPFAIL: this slot is busy
    done
    sleep 5
  done
fi
[ -e "$dir/$name" ] || {
  echo "unknown lock $name" >&2
  exit 64
}
exec /usr/bin/lockf -s -k "$dir/$name" "$@"
