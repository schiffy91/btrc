#!/bin/sh
# Build this host's share of ci/targets.nix, sign it, and add it to a flat-file Nix
# binary cache that other machines can substitute from over HTTP. No account anywhere.
#
# This is the compiler, so this cache is what spares every consumer from building
# btrcpy, btrcc and btrc-native-plan before it can build anything of its own.
#
#   publish.sh [--all] [--dir DIR] [--key FILE] [ATTR...]
#
# --all uses ci/targets.nix `local` instead of only this system's CI attrs.
# The secret key is generated on first use and never leaves this machine; keep a copy.
set -eu

root=$(cd "$(dirname "$0")/../.." && pwd -P)
targets="$root/ci/targets.nix"
dir="${BTRC_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/nix-cache}"  # shared with the other repositories on this host
key="${BTRC_CACHE_KEY:-${XDG_CONFIG_HOME:-$HOME/.config}/nix/btrc-cache-1.key}"
list=""
all=0

while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1 ;;
    --dir) dir="$2"; shift ;;
    --key) key="$2"; shift ;;
    -*) printf 'publish.sh: unknown option %s\n' "$1" >&2; exit 64 ;;
    *) list="$list $1" ;;
  esac
  shift
done

evaluate() { nix eval --raw --file "$targets" --apply "$1"; }
name=$(evaluate 'c: c.cache.name')
system=$(nix eval --raw --impure --expr 'builtins.currentSystem')

if [ -z "$list" ]; then
  if [ "$all" = 1 ]; then
    list=$(evaluate 'c: builtins.concatStringsSep " " c.local')
  else
    list=$(evaluate "c: let m = builtins.filter (s: s.system == \"$system\") c.systems; in if m == [] then \"\" else builtins.concatStringsSep \" \" (builtins.head m).attrs")
  fi
fi
[ -n "$list" ] || { printf 'publish.sh: ci/targets.nix names nothing for %s\n' "$system" >&2; exit 1; }

if [ ! -f "$key" ]; then
  mkdir -p "$(dirname "$key")"
  ( umask 077; nix key generate-secret --key-name "$name" > "$key" )
  printf 'publish.sh: generated %s — keep a copy; its public half is\n  %s\n' "$key" "$(nix key convert-secret-to-public < "$key")" >&2
fi
public=$(nix key convert-secret-to-public < "$key")
declared=$(evaluate 'c: c.cache.publicKey')
[ "$public" = "$declared" ] || printf 'publish.sh: this key is %s but ci/targets.nix declares %s\n' "$public" "$declared" >&2

mkdir -p "$dir"
for attr in $list; do
  printf 'publish.sh: %s#%s\n' "$system" "$attr" >&2
  out=$(nix build --no-link --print-out-paths "$root#$attr")
  nix store sign --key-file "$key" --recursive $out
  nix copy --to "file://$dir?compression=zstd" $out
done

printf '\npublish.sh: %s holds %s paths. Serve it (make cache-serve) and on every other machine:\n' "$dir" "$(ls "$dir" | grep -c '\.narinfo$' || true)" >&2
printf '  nix.settings.extra-substituters = [ "http://%s.local:8080" ];\n  nix.settings.extra-trusted-public-keys = [ "%s" ];\n' "$(hostname)" "$public" >&2
