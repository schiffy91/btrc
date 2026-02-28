#!/bin/bash
# Runs on the HOST (via initializeCommand) before every devcontainer start.
# Extracts credentials and stages the SSH agent socket for bind-mount.
#
# Supports macOS and Linux (NixOS) hosts. All operations are best-effort —
# missing tools or credentials are silently skipped.

CREDS_DIR="${HOME}/.claude-devcontainer"
mkdir -p "$CREDS_DIR"

# --- Podman housekeeping ---
# Prune unused images/containers to prevent the VM disk from filling up.
if command -v podman &>/dev/null; then
    podman system prune -a -f >/dev/null 2>&1 || true
fi

# --- Claude Code credentials ---
if [[ "$(uname)" == "Darwin" ]] && command -v security &>/dev/null; then
    # macOS: extract OAuth token from Keychain
    tmp="${CREDS_DIR}/.credentials.json.tmp"
    if security find-generic-password -s "Claude Code-credentials" -a "$USER" -w > "$tmp" 2>/dev/null; then
        mv "$tmp" "${CREDS_DIR}/.credentials.json"
        chmod 600 "${CREDS_DIR}/.credentials.json"
    else
        rm -f "$tmp"
    fi
else
    # Linux (e.g. NixOS): credentials are stored as a plain file
    if [ -f "${HOME}/.claude/.credentials.json" ]; then
        cp "${HOME}/.claude/.credentials.json" "${CREDS_DIR}/.credentials.json" 2>/dev/null || true
        chmod 600 "${CREDS_DIR}/.credentials.json" 2>/dev/null || true
    fi
fi

# --- GitHub CLI auth ---
# macOS gh stores tokens in the system Keychain; Linux gh stores them in
# ~/.config/gh/hosts.yml. Either way, `gh auth token` returns the live token.
# We build a portable hosts.yml the container can use directly.
if command -v gh &>/dev/null; then
    token=$(gh auth token -h github.com 2>/dev/null || true)
    user=$(gh api user --jq .login 2>/dev/null || true)
    if [ -n "$token" ]; then
        mkdir -p "${CREDS_DIR}/gh" 2>/dev/null || true
        cat > "${CREDS_DIR}/gh/hosts.yml" 2>/dev/null <<EOF
github.com:
    oauth_token: ${token}
    user: ${user:-}
    git_protocol: https
EOF
        chmod 600 "${CREDS_DIR}/gh/hosts.yml" 2>/dev/null || true
    fi
fi

# --- SSH agent (1Password) ---
# Detect the 1Password SSH agent socket and place a stable symlink that
# devcontainer.json can bind-mount into the container.
AGENT_DEST="${CREDS_DIR}/ssh-agent.sock"
rm -f "$AGENT_DEST" 2>/dev/null || true

SOCK=""
if [[ "$(uname)" == "Darwin" ]]; then
    candidate="${HOME}/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
    [ -S "$candidate" ] && SOCK="$candidate"
else
    candidate="${HOME}/.1password/agent.sock"
    [ -S "$candidate" ] && SOCK="$candidate"
fi
# Fallback: standard SSH agent
if [ -z "$SOCK" ] && [ -n "${SSH_AUTH_SOCK:-}" ] && [ -S "${SSH_AUTH_SOCK}" ]; then
    SOCK="${SSH_AUTH_SOCK}"
fi

if [ -n "$SOCK" ]; then
    ln -sf "$SOCK" "$AGENT_DEST"
else
    # Placeholder so the bind-mount doesn't fail when no agent is available.
    touch "$AGENT_DEST"
fi
