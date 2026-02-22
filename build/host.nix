{ cfg, lib }:
let
  runtime = cfg.runtime;
  machine = cfg.machine;
in
''
  #!/usr/bin/env bash
  set -euo pipefail
  if ! ${runtime} info &>/dev/null; then
    echo "Starting ${runtime}..."
    ${runtime} machine start 2>/dev/null || {
      ${runtime} machine init --memory ${toString machine.memory} --cpus ${toString machine.cpus} --disk-size ${toString machine.disk}
      ${runtime} machine start
    }
  fi
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64) PLATFORM="linux/amd64" ;;
    arm64|aarch64) PLATFORM="linux/arm64" ;;
    *) echo "Unsupported: $ARCH" >&2; exit 1 ;;
  esac
  echo "Building ${cfg.name} devcontainer ($PLATFORM)..."
  ${runtime} build -f .devcontainer/Containerfile --platform "$PLATFORM" -t ${cfg.image} .
  ${runtime} image prune --force &>/dev/null || true
  ${runtime} volume prune --force &>/dev/null || true
'' + lib.optionalString cfg.share.claude ''
  # Mirror Claude credentials to ~/.claude/.credentials.json (Linux convention)
  if command -v security &>/dev/null; then
    mkdir -p "$HOME/${cfg.paths.claude}"
    security find-generic-password -s "Claude Code-credentials" -a "$USER" -w > "$HOME/${cfg.paths.claude}/.credentials.json" 2>/dev/null || true
  fi
''
