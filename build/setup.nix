{ cfg, lib }:
{
  hostSh = ''
    #!/usr/bin/env bash
    set -euo pipefail
    ARCH=$(uname -m)
    case "$ARCH" in
      x86_64) PLATFORM="linux/amd64" ;;
      arm64|aarch64) PLATFORM="linux/arm64" ;;
      *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
    esac
    echo "Building ${cfg.name} devcontainer ($PLATFORM)..."
    ${cfg.runtime} build -f .devcontainer/Containerfile \
      --platform "$PLATFORM" \
      -t ${cfg.name}-devcontainer:latest .
    D="$HOME/.devcontainer-credentials"
    rm -rf "$D" && mkdir -p "$D"
  '' + lib.optionalString cfg.share.ssh ''
    mkdir -p "$D/.ssh"
    cp "$HOME"/.ssh/id_* "$HOME/.ssh/config" "$D/.ssh/" 2>/dev/null || true
  '' + lib.optionalString cfg.share.git ''
    cp "$HOME/.gitconfig" "$D/.gitconfig" 2>/dev/null || true
  '' + lib.optionalString cfg.share.gh ''
    if command -v gh &>/dev/null && gh auth token -h github.com &>/dev/null; then
      mkdir -p "$D/.config/gh"
      printf 'github.com:\n  oauth_token: %s\n  user: %s\n  git_protocol: https\n' \
        "$(gh auth token -h github.com)" "$(gh api user --jq .login)" \
        > "$D/.config/gh/hosts.yml"
    fi
  '' + lib.optionalString cfg.share.claude ''
    if command -v security &>/dev/null; then
      mkdir -p "$D/.claude"
      security find-generic-password -s "Claude Code-credentials" -a "$USER" -w \
        > "$D/.claude/.credentials.json" 2>/dev/null || true
    fi
  '';

  containerSh = ''
    #!/usr/bin/env bash
    set -euo pipefail
    SRC="$CREDENTIALS_DIR"
  '' + lib.optionalString cfg.share.ssh ''
    [ -d "$SRC/.ssh" ] && {
      cp -r "$SRC/.ssh" "$HOME/.ssh"
      chmod 700 "$HOME/.ssh"
      chmod 600 "$HOME/.ssh/"* 2>/dev/null || true
      chmod 644 "$HOME/.ssh/"*.pub "$HOME/.ssh/config" 2>/dev/null || true
    }
  '' + lib.optionalString cfg.share.git ''
    [ -f "$SRC/.gitconfig" ] && cp "$SRC/.gitconfig" "$HOME/.gitconfig"
  '' + lib.optionalString cfg.share.gh ''
    [ -f "$SRC/.config/gh/hosts.yml" ] && {
      mkdir -p "$HOME/.config/gh"
      cp "$SRC/.config/gh/hosts.yml" "$HOME/.config/gh/hosts.yml"
    }
  '' + lib.optionalString cfg.share.claude ''
    [ -f "$SRC/.claude/.credentials.json" ] && {
      mkdir -p "$HOME/.claude"
      cp "$SRC/.claude/.credentials.json" "$HOME/.claude/.credentials.json"
      chmod 600 "$HOME/.claude/.credentials.json"
    }
  '' + "true\n";
}
