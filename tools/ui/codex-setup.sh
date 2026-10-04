#!/usr/bin/env bash
# Run from any directory after the environment has installed Nix (WORKSTREAMS §3.11).
set -euo pipefail

platforms=false
case "${1:-}" in
  '') ;;
  --platforms) platforms=true; shift ;;
  --help|-h)
    echo 'Usage: tools/ui/codex-setup.sh [--platforms]'
    echo 'Requires Nix on PATH; BTRC_CODEX_GCROOTS and BTRC_CODEX_RC_FILE override writable destinations.'
    exit 0 ;;
  *) echo "codex setup: unknown argument: $1" >&2; exit 2 ;;
esac
if (( $# )); then
  echo 'codex setup: expected at most --platforms' >&2
  exit 2
fi

# Keep a configured rootless wrapper and the platform Git credential proxy intact.
if ! command -v nix >/dev/null 2>&1; then
  if [[ -x /nix/var/nix/profiles/default/bin/nix ]]; then
    export PATH="/nix/var/nix/profiles/default/bin:$PATH"
  else
    echo 'codex setup: Nix is missing; install it during network-enabled environment setup (WORKSTREAMS §3.11), then retry.' >&2
    exit 1
  fi
fi
nix_command=(nix --extra-experimental-features 'nix-command flakes')
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd -- "$repo"
export BTRC_TEST_RUNNER=linux-devcontainer
roots=${BTRC_CODEX_GCROOTS:-${XDG_CACHE_HOME:-$HOME/.cache}/btrc/gcroots}
rc_file=${BTRC_CODEX_RC_FILE:-$HOME/.bashrc}
mkdir -p -- "$roots" "$(dirname -- "$rc_file")"
roots=$(cd -- "$roots" && pwd -P)

# Nix only advances the profile when the realized shell changes.
"${nix_command[@]}" develop --no-write-lock-file --profile "$roots/dev" --command true
"${nix_command[@]}" develop --no-write-lock-file --command bash -euo pipefail -c '
  version=$(gcc -dumpfullversion)
  case "$version" in 15.2|15.2.*) ;; *) echo "codex setup: expected GCC 15.2, got $version" >&2; exit 1;; esac
  command -v Xvfb >/dev/null || { echo "codex setup: Xvfb is missing" >&2; exit 1; }
  test -x "${BTRC_NATIVE_HEADER_READER:-}" || { echo "codex setup: native header reader is missing" >&2; exit 1; }
  printf "codex setup: GCC %s; Xvfb and native header reader available\n" "$version"
'
"${nix_command[@]}" build --no-write-lock-file .#btrc-native-header --out-link "$roots/native-header"
"${nix_command[@]}" develop --no-write-lock-file --command make NIX= build btrcc
if "$platforms"; then
  "${nix_command[@]}" develop .#platforms --no-write-lock-file --profile "$roots/platforms" --command true
fi

# Append a fixed line, never shell-evaluate a caller-supplied path or overwrite an rc.
runner_line='export BTRC_TEST_RUNNER=linux-devcontainer'
if [[ ! -e "$rc_file" ]] || ! grep -Fqx -- "$runner_line" "$rc_file"; then
  printf '\n%s\n' "$runner_line" >> "$rc_file"
fi

# Persist only a supplied setup secret, over stdin, and only if stored auth fails.
# Never run gh auth setup-git: it replaces the cloud platform's credential proxy.
if [[ -n "${GH_TOKEN:-}" ]]; then
  if ! env -u GH_TOKEN -u GITHUB_TOKEN "${nix_command[@]}" develop --no-write-lock-file --command gh auth status --hostname github.com >/dev/null 2>&1; then
    printf '%s' "$GH_TOKEN" | env -u GH_TOKEN -u GITHUB_TOKEN "${nix_command[@]}" develop --no-write-lock-file --command gh auth login --hostname github.com --with-token
  fi
fi
echo 'codex setup: ready'
