#!/usr/bin/env bash
# Run a make target the way the Linux CI job runs it: inside the devcontainer
# image, with NIX= so make uses the container's own toolchain.
#
#   tools/linux-ci.sh                  # the CI test job
#   tools/linux-ci.sh lint format-check
#
# Two things differ from `podman run -v "$PWD:/workspace"`:
#
#   * build/ subdirectories and dist/ may be symlinks into a cache outside
#     the workspace, because this repository can live in synced storage and
#     build products should not be synced. Those links dangle inside the
#     container, and mkdir -p will not follow a dangling link, so each link
#     target is created inside a container-private directory and bind-mounted
#     at its own path.
#   * That directory is private on purpose. build/stdlib holds host objects,
#     and a Linux build must not link against them.
#   * Bytecode is written outside the tree. The host and the container can run
#     the same Python version -- both reach 3.14 through nix -- so the
#     container would load __pycache__ files the host wrote, whose recorded
#     filenames are host paths it cannot read. Everything that inspects a
#     source, including the self-host fingerprint, then fails at import.
#
# Both budgets are larger than CI's because this runs in a VM: the self-hosted
# compiler is rebuilt from scratch against a cold cache, and the corpus's
# heaviest program does not finish inside the default run budget at -O0.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
private="${BTRC_LINUX_BUILD:-${XDG_CACHE_HOME:-$HOME/.cache}/btrc/linux-ci}"
image="${BTRC_LINUX_IMAGE:-btrc-devcontainer:latest}"
cd "$repo"

if ! podman image exists "$image"; then
  echo "$image is missing; run: make devcontainer" >&2
  exit 1
fi

mounts=(-v "$repo:/workspace")
declare -a roots=()
while IFS= read -r link; do
  target="$(readlink "$link")"
  [[ "$target" == /* ]] || continue
  root="$(dirname "$target")"
  slot="$private/$(printf '%s' "$root" | tr '/' '_')"
  mkdir -p "$slot/$(basename "$target")"
  for seen in ${roots[@]+"${roots[@]}"}; do
    [[ "$seen" == "$root" ]] && continue 2
  done
  roots+=("$root")
  mounts+=(-v "$slot:$root")
done < <(find build dist -maxdepth 1 -type l 2>/dev/null)

exec podman run --rm --init "${mounts[@]}" \
  -e PYTHONPYCACHEPREFIX=/tmp/btrc-pycache "$image" \
  make NIX= "PYTEST_WORKERS=${PYTEST_WORKERS:-4}" \
  "BTRC_TEST_TRANSPILE_TIMEOUT=${BTRC_TEST_TRANSPILE_TIMEOUT:-1800}" \
  "BTRC_TEST_RUN_TIMEOUT=${BTRC_TEST_RUN_TIMEOUT:-60}" \
  "${@:-gpu-required test}"
