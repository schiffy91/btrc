#!/bin/bash
# The owner's one command for a Mac session (WORKSTREAMS.md §3.12):
#
#   tools/runbook/run.sh <preset> [<preset> ...] [options]     e.g.  tools/runbook/run.sh stage5
#   tools/runbook/run.sh stage5 --list                         what would run, and what already finished
#   tools/runbook/run.sh stage5 --rehearsal --stand-in --dry-run   rehearse anywhere, measuring nothing
#
# Run it from a clone of ~/.cache/btrc/hub.git outside Google Drive. It enters
# this checkout's pinned dev shell (GC-rooted at ~/.cache/btrc/gcroots/runbook,
# so a later run needs no download) and runs `python3 -m tools.runbook`.
# Rerunning the same command resumes from the last finished cell; README.md
# describes every preset and option.
set -u
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cd "$repo" || exit 2
case $repo in
  *"Google Drive"* | *GoogleDrive* | *CloudStorage*)
    echo "runbook: $repo is inside Google Drive; run from a clone of ~/.cache/btrc/hub.git (AGENTS.md 'Hubs')." >&2
    exit 2
    ;;
esac
if [ -n "${IN_NIX_SHELL:-}" ]; then
  exec python3 -m tools.runbook "$@"
fi
if ! command -v nix > /dev/null 2>&1; then
  echo "runbook: nix is not on PATH; open a shell where \`nix develop\` works and rerun." >&2
  exit 2
fi
profiles=${BTRC_BENCH_HOME:-$HOME/.cache/btrc}/gcroots
mkdir -p "$profiles"
nix develop "$repo" --profile "$profiles/runbook" --command python3 -m tools.runbook "$@"
status=$?
if [ $status -ne 0 ] && [ $status -ne 1 ] && [ $status -ne 130 ]; then
  echo "runbook: exited $status before finishing; the message above names the problem. Rerun the same command after fixing it." >&2
fi
exit $status
