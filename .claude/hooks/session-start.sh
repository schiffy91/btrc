#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Every gate in this repository is defined by the Nix flake: the Makefile
# prefixes each target with `nix develop --command`, and the dev shell pins the
# C toolchain, Python, wgpu-native, the native header reader and its sysroot.
# A web session container has none of that, so anything run outside the shell
# (a distro clang, a distro python3) drifts from CI. This hook installs Nix and
# warms the dev shell, so `make lint`, `make test-unit`, `make bootstrap` and
# the rest behave exactly as they do in CI and in a local `nix develop`.
#
# Idempotent and non-interactive. Runs only in the remote environment; a local
# checkout is expected to already have Nix.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

NIX_PROFILE_BIN=/nix/var/nix/profiles/default/bin

if [ ! -x "$NIX_PROFILE_BIN/nix" ]; then
  echo "session-start: installing Nix"
  installer="$(mktemp -d)/nix-installer.sh"
  curl -sSfL --proto '=https' --tlsv1.2 https://install.determinate.systems/nix -o "$installer"
  # No init system in the container, so no daemon: the store is driven
  # directly (NIX_REMOTE=local below). The build sandbox stays enabled.
  sh "$installer" install linux --no-confirm --init none \
    --extra-conf "experimental-features = nix-command flakes"
fi

export PATH="$NIX_PROFILE_BIN:$PATH"
export NIX_REMOTE=local

# Persist for the rest of the session: every later shell sees nix on PATH and
# talks to the store without a daemon.
{
  echo "export PATH=\"$NIX_PROFILE_BIN:\$PATH\""
  echo "export NIX_REMOTE=local"
} >> "$CLAUDE_ENV_FILE"

# Pull the pinned toolchain now so the first `make` is not a cold download,
# and so the cached container state carries it.
echo "session-start: warming the flake dev shell"
cd "$CLAUDE_PROJECT_DIR"
nix develop --command true

# bin/btrcpy is the reference-compiler wrapper the docs and examples use.
nix develop --command make build

echo "session-start: ready"
