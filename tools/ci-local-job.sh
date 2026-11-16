#!/usr/bin/env bash
# Run one CI job's steps the way a hosted runner does: in a fresh clone of
# HEAD, each step under `bash -e` as GitHub runs a `run` step, with CI=true.
#
#   tools/ci-local-job.sh [NAME=value ...] -- 'step' ['step' ...]
#
# ci/local.json's commands call this; `python3 -m tools.qualification
# local-jobs --write` derives them from the workflows' own steps, and
# `ci-local run` records a pass for the commit when this exits 0.
#
# The clone is what makes it CI's job rather than this checkout's:
#
#   * The ignored files a checkout gathers (build/, a stale cache, an image
#     context full of old evidence) are absent, as on a runner.
#   * The devcontainer's user is not this one. Its job makes the tree
#     world-writable and leaves files only `podman unshare` can remove; that
#     happens to the clone, never to the checkout.
#   * A git worktree's .git is a pointer the container cannot follow.
#
# GITHUB_WORKSPACE, GITHUB_SHA and RUNNER_TEMP are set as a runner sets them.
# A clone whose steps all pass is removed. A failing one is kept and named,
# with the command that removes it.
set -euo pipefail

environment=()
while (($#)) && [[ "$1" != -- ]]; do
  if ! [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
    echo "ci-local-job: expected NAME=value or --, not: $1" >&2
    exit 64
  fi
  environment+=("$1")
  shift
done
if (($# < 2)); then
  echo "usage: tools/ci-local-job.sh [NAME=value ...] -- 'step' ['step' ...]" >&2
  exit 64
fi
shift

root="$(git rev-parse --show-toplevel)"
commit="$(git -C "$root" rev-parse HEAD)"
cache="${BTRC_CI_LOCAL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/btrc/ci-local}"
mkdir -p "$cache"
work="$(mktemp -d "$cache/${commit:0:12}.XXXXXX")"
# What the container's user wrote belongs to a subordinate uid, which only
# podman's user namespace may remove.
remove="rm -rf"
if [[ "$(uname -s)" == Linux ]] && command -v podman >/dev/null 2>&1; then
  remove="podman unshare rm -rf"
fi

# Copied objects, not hard links: the job's chmod must not reach this repository's own.
git clone --quiet --no-hardlinks --no-checkout "$root" "$work/workspace"
git -C "$work/workspace" checkout --quiet --detach "$commit"
mkdir "$work/temp"
cd "$work/workspace"
export CI=true GITHUB_WORKSPACE="$PWD" GITHUB_SHA="$commit" RUNNER_TEMP="$work/temp"
for assignment in ${environment[@]+"${environment[@]}"}; do
  export "$assignment"
done

for step in "$@"; do
  echo "ci-local-job: ${step%%$'\n'*}" >&2
  if ! bash -e -c "$step"; then
    echo "ci-local-job: that step failed at ${commit:0:12}; its clone is kept at $work" >&2
    echo "ci-local-job: remove it with: $remove $work" >&2
    exit 1
  fi
done
cd /
rm -rf "$work" 2>/dev/null || $remove "$work" || echo "ci-local-job: could not remove $work" >&2
