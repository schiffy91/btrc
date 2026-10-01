#!/usr/bin/env bash
# Run a make target the way the Linux CI job runs it: inside the devcontainer
# image, with NIX= so make uses the container's own toolchain.
#
#   tools/linux-ci.sh                  # the CI test job
#   tools/linux-ci.sh lint format-check
#
# As in CI, tools/virtual-display.sh gives the container an X display and
# Mesa's software Vulkan driver, so the GUI and GPU adapter tests run.
#
# Three things differ from `podman run -v "$PWD:/workspace"`:
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
# The measurement path runs here too. A host without BTRSmith rehearses the
# budget harness on its generated stand-in (no receipts on Linux: the object
# cache validates by dependency scan and every build relinks):
#
#   tools/linux-ci.sh btrcc && tools/linux-ci.sh perf-budget \
#     'BUDGET_BENCH_OPTIONS=--btrcc /workspace/bin/btrcc --stand-in' \
#     'BUDGET_BENCH_ARGS=--scenarios cold,release,edit,instance-edit,interface-edit,noop,touch,memory,workers'
#
# Both budgets are set explicitly, as CI sets them. The run budget matches
# CI's 60 s, which the corpus's heaviest program needs at -O0. Only the
# transpile budget exceeds CI's 600 s: this runs in a VM, where the self-hosted
# compiler is rebuilt from scratch against a cold cache.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
private="${BTRC_LINUX_BUILD:-${XDG_CACHE_HOME:-$HOME/.cache}/btrc/linux-ci}"
image="${BTRC_LINUX_IMAGE:-btrc-devcontainer:latest}"
cd "$repo"

# With no arguments, run the Makefile's LINUX_CI_TARGETS default: the CI test
# job. Each target is its own argument; make would read one quoted string as a
# single target name.
if (($# == 0)); then
  set -- gpu-required test
fi

if ! podman image exists "$image"; then
  echo "$image is missing; run: make devcontainer" >&2
  exit 1
fi

mounts=(-v "$repo:/workspace")
declare -a roots=()
while IFS= read -r link; do
  target="$(readlink "$link")"
  [[ "$target" == /* ]] || continue
  # A link into the Nix store names a host build output, not a build
  # directory; shadowing /nix/store inside the container empties its toolchain.
  [[ "$target" == /nix/store/* ]] && continue
  root="$(dirname "$target")"
  slot="$private/$(printf '%s' "$root" | tr '/' '_')"
  mkdir -p "$slot/$(basename "$target")"
  for seen in ${roots[@]+"${roots[@]}"}; do
    [[ "$seen" == "$root" ]] && continue 2
  done
  roots+=("$root")
  mounts+=(-v "$slot:$root")
done < <(find build dist -maxdepth 1 -type l 2>/dev/null)

# Default the worker count to the VM's CPUs (CI's runner has four); `podman
# machine set --cpus N --memory M` resizes the VM, restarting it.
workers="${PYTEST_WORKERS:-$(podman info --format '{{.Host.CPUs}}' 2>/dev/null || echo 4)}"

exec podman run --rm --init "${mounts[@]}" \
  -e PYTHONPYCACHEPREFIX=/tmp/btrc-pycache "$image" \
  tools/virtual-display.sh make NIX= "PYTEST_WORKERS=$workers" \
  "BTRC_TEST_TRANSPILE_TIMEOUT=${BTRC_TEST_TRANSPILE_TIMEOUT:-1800}" \
  "BTRC_TEST_RUN_TIMEOUT=${BTRC_TEST_RUN_TIMEOUT:-60}" \
  "$@"
