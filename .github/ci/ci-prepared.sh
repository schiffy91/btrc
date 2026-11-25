#!/usr/bin/env bash
# What one CI run builds once and every Linux job of that run then takes: the
# devcontainer image and the suite's self-hosted compilers.
#
#   .github/ci/ci-prepared.sh save <directory>      # the prepare job, after `make devcontainer` and `make btrcc-test`
#   .github/ci/ci-prepared.sh restore <directory>   # every other Linux job, where it used to run `make devcontainer`
#
# save writes two archives into <directory>, which the job uploads:
#
#   devcontainer.tar.gz   `podman save` of the image
#   test-btrcc.tar.gz     the compiler and driver binaries under build/test-btrcc
#
# restore loads the image when its archive is there and builds it with `make
# devcontainer` when it is not, which is what a local job in a fresh clone
# does (.github/ci/ci-local-job.sh; that script keeps compilers between clones
# itself). It then unpacks the compilers into build/test-btrcc. A compiler is
# used only when its key matches the tree and the toolchain that would build
# it (src/tests/selfhost_cache.py), so an archive from another commit costs a
# rebuild and can never supply a wrong compiler.
set -euo pipefail

image="${BTRC_LINUX_IMAGE:-btrc-devcontainer:latest}"
if (($# != 2)) || [[ "$1" != save && "$1" != restore ]]; then
  echo "usage: .github/ci/ci-prepared.sh save|restore <directory>" >&2
  exit 64
fi
action="$1"
directory="$2"
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

case "$action" in
  save)
    mkdir -p "$directory" build/test-btrcc
    podman save "$image" | gzip -1 > "$directory/devcontainer.tar.gz"
    # Binaries only: beside each compiler lies 90 MB of generated C that no later job reads.
    (cd build && find test-btrcc -type f \( -name btrcc -o -name driver \) -print0 | tar --null -T - -cf -) |
      gzip -1 > "$directory/test-btrcc.tar.gz"
    ;;
  restore)
    if [[ -f "$directory/devcontainer.tar.gz" ]]; then
      gzip -dc "$directory/devcontainer.tar.gz" | podman load
    else
      make devcontainer
    fi
    if [[ -f "$directory/test-btrcc.tar.gz" ]]; then
      mkdir -p build
      gzip -dc "$directory/test-btrcc.tar.gz" | tar -C build -xf -
    fi
    ;;
esac
