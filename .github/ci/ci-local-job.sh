#!/usr/bin/env bash
# Run one CI job's steps the way a hosted runner does: in a fresh clone of
# HEAD, each step under `bash -e` as GitHub runs a `run` step, with CI=true.
#
#   .github/ci/ci-local-job.sh [NAME=value ...] -- 'step' ['step' ...]
#
# .github/ci/local.json's commands call this; `python3 .github/ci/local.py
# jobs --write` derives them from the workflows' own steps, and
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
#
# One thing outlives the clone: the suite's self-hosted compilers and helper
# drivers. Each is keyed by everything it was built from, the C toolchain
# included (src/tests/selfhost_cache.py), so a job never has to rebuild one an
# earlier job built for the same tree. Their binaries are kept in
# <cache>/compilers, copied into the clone's build/test-btrcc before the first
# step and collected from it after the last, whether the job passed or not: an
# entry whose key does not match the tree is simply not used. The newest
# COMPILERS_KEPT compilers and DRIVERS_KEPT drivers stay.
set -euo pipefail

readonly COMPILERS_KEPT=4
readonly DRIVERS_KEPT=160

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
  echo "usage: .github/ci/ci-local-job.sh [NAME=value ...] -- 'step' ['step' ...]" >&2
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

compilers="$cache/compilers"
built="$work/workspace/build/test-btrcc"
# A copy, so the job's chmod and the container's user never reach the kept binaries.
copy() {
  cp --reflink=auto "$1" "$2" 2>/dev/null || cp "$1" "$2"
}
restore_compilers() {
  [[ -d "$compilers" ]] || return 0
  local kept
  while IFS= read -r kept; do
    mkdir -p "$built/$(dirname "$kept")"
    copy "$compilers/$kept" "$built/$kept"
  done < <(cd "$compilers" && find . -type f \( -name btrcc -o -name driver \) | sed 's|^\./||')
}
keep_compilers() {
  [[ -d "$built" ]] || return 0
  local binary staged
  while IFS= read -r binary; do
    [[ -e "$compilers/$binary" ]] && continue
    mkdir -p "$compilers/$(dirname "$binary")"
    # Published by rename: a job that is interrupted here leaves no partial binary to trust.
    staged="$compilers/$binary.$$"
    if copy "$built/$binary" "$staged" && chmod 0755 "$staged"; then
      mv "$staged" "$compilers/$binary"
    else
      rm -f "$staged"
    fi
  done < <(cd "$built" && find . -type f \( -name btrcc -o -name driver \) | sed 's|^\./||')
  [[ -d "$compilers" ]] || return 0
  prune "$compilers" "$COMPILERS_KEPT" btrcc
  prune "$compilers/drivers" "$DRIVERS_KEPT" driver
}
# prune <directory> <count> <binary>: keep the <count> newest entries that hold <binary>.
prune() {
  [[ -d "$1" ]] || return 0
  local entry index=0
  while IFS= read -r entry; do
    index=$((index + 1))
    if ((index > $2)); then rm -rf "${entry%/*}"; fi
  done < <(ls -t "$1"/*/"$3" 2>/dev/null)
}

restore_compilers
cd "$work/workspace"
export CI=true GITHUB_WORKSPACE="$PWD" GITHUB_SHA="$commit" RUNNER_TEMP="$work/temp"
for assignment in ${environment[@]+"${environment[@]}"}; do
  export "$assignment"
done

for step in "$@"; do
  echo "ci-local-job: ${step%%$'\n'*}" >&2
  if ! bash -e -c "$step"; then
    keep_compilers
    echo "ci-local-job: that step failed at ${commit:0:12}; its clone is kept at $work" >&2
    echo "ci-local-job: remove it with: $remove $work" >&2
    exit 1
  fi
done
keep_compilers
cd /
rm -rf "$work" 2>/dev/null || $remove "$work" || echo "ci-local-job: could not remove $work" >&2
