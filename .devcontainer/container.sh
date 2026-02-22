#!/bin/bash
set -euo pipefail

# =============================================================================
# Devcontainer lifecycle script. Called by devcontainer.json:
#   postCreateCommand:  bash .devcontainer/container.sh setup
#   postStartCommand:   bash .devcontainer/container.sh start
#
# All project-specific configuration lives in .devcontainer/project.json.
# This script reads it via jq — no per-project edits needed here.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_JSON="${SCRIPT_DIR}/project.json"

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  PROJECT-SPECIFIC — reads from project.json                                │
# └─────────────────────────────────────────────────────────────────────────────┘

project_setup() {
    if [ ! -f "$PROJECT_JSON" ]; then
        echo "WARNING: project.json not found, skipping project setup"
        return
    fi

    # Run each setup command from project.json
    local count
    count=$(jq -r '.setupCommands | length' "$PROJECT_JSON")
    for ((i = 0; i < count; i++)); do
        local cmd
        cmd=$(jq -r ".setupCommands[$i]" "$PROJECT_JSON")
        echo "Running: $cmd"
        eval "$cmd"
    done

    # Build local extensions (npm install + package as .vsix)
    local ext_count
    ext_count=$(jq -r '.localExtensions | length // 0' "$PROJECT_JSON")
    for ((i = 0; i < ext_count; i++)); do
        local ext_path
        ext_path=$(jq -r ".localExtensions[$i]" "$PROJECT_JSON")
        local abs_path="/workspace/${ext_path}"
        if [ -d "$abs_path" ] && [ -f "$abs_path/package.json" ]; then
            echo "Building local extension: $ext_path"
            (cd "$abs_path" && npm install && npm run package)
        else
            echo "WARNING: local extension not found at $abs_path, skipping"
        fi
    done
}

project_firewall_domains() {
    # Return project-specific domains to whitelist (one per line).
    # Generic infra domains (npm, Anthropic, VS Code, GitHub) are in
    # FIREWALL_ALLOWED_DOMAINS in devcontainer.json — no need to repeat them.
    if [ ! -f "$PROJECT_JSON" ]; then
        return
    fi
    jq -r '.firewallDomains[]? // empty' "$PROJECT_JSON"
}

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  GENERIC — no changes needed per project below this line                   │
# └─────────────────────────────────────────────────────────────────────────────┘

# --- Lifecycle entry points ---------------------------------------------------

setup() {
    project_setup
}

start() {
    restore_credentials
    install_local_extensions
    init_firewall
}

# --- Local extension installer ------------------------------------------------

install_local_extensions() {
    # Install .vsix files built during setup. Runs during postStartCommand
    # when the VS Code CLI is available.
    if [ ! -f "$PROJECT_JSON" ]; then
        return
    fi

    local ext_count
    ext_count=$(jq -r '.localExtensions | length // 0' "$PROJECT_JSON")
    for ((i = 0; i < ext_count; i++)); do
        local ext_path
        ext_path=$(jq -r ".localExtensions[$i]" "$PROJECT_JSON")
        local abs_path="/workspace/${ext_path}"
        # Find any .vsix file in the extension directory
        local vsix
        vsix=$(find "$abs_path" -maxdepth 1 -name '*.vsix' -print -quit 2>/dev/null || true)
        if [ -n "$vsix" ]; then
            echo "Installing local extension: $vsix"
            code --install-extension "$vsix" --force 2>/dev/null || true
        fi
    done
}

# --- Credential helpers -------------------------------------------------------

restore_credentials() {
    # Claude Code
    cp /tmp/claude-host-creds/.credentials.json /home/node/.claude/.credentials.json 2>/dev/null || true
    chmod 600 /home/node/.claude/.credentials.json 2>/dev/null || true

    # GitHub CLI
    if [ -f /tmp/claude-host-creds/gh/hosts.yml ]; then
        mkdir -p /home/node/.config/gh 2>/dev/null || true
        cp /tmp/claude-host-creds/gh/hosts.yml /home/node/.config/gh/hosts.yml 2>/dev/null || true
        chmod 600 /home/node/.config/gh/hosts.yml 2>/dev/null || true
    fi

    # SSH agent (1Password) — host.sh bind-mounts the socket to a fixed path.
    # Write SSH_AUTH_SOCK into the shell profile so every terminal picks it up.
    if [ -S /run/host-ssh-agent.sock ]; then
        echo 'export SSH_AUTH_SOCK=/run/host-ssh-agent.sock' > /home/node/.ssh_agent_env
        # Also set for the current postStartCommand scope
        export SSH_AUTH_SOCK=/run/host-ssh-agent.sock
    else
        rm -f /home/node/.ssh_agent_env
    fi

    # Configure git to use SSH for GitHub (works with 1Password agent or any SSH key)
    git config --global url."git@github.com:".insteadOf "https://github.com/" 2>/dev/null || true
}

# --- Firewall -----------------------------------------------------------------

init_firewall() {
    local domains="${FIREWALL_ALLOWED_DOMAINS:-}"
    local project_domains
    project_domains="$(project_firewall_domains 2>/dev/null || true)"
    if [ -n "$project_domains" ]; then
        domains="$domains $(echo "$project_domains" | tr '\n' ' ')"
    fi
    # The firewall needs root; re-invoke this script with sudo for that portion.
    # shellcheck disable=SC2086
    sudo bash "$0" _firewall $domains
}

_do_firewall() {
    local IFS=$'\n\t'
    local ALLOWED_DOMAINS=("$@")

    # 1. Extract Docker DNS info BEFORE any flushing
    local DOCKER_DNS_RULES
    DOCKER_DNS_RULES=$(iptables-save -t nat | grep "127\.0\.0\.11" || true)

    # Flush existing rules and delete existing ipsets
    iptables -F
    iptables -X
    iptables -t nat -F
    iptables -t nat -X
    iptables -t mangle -F
    iptables -t mangle -X
    ipset destroy allowed-domains 2>/dev/null || true

    # 2. Selectively restore ONLY internal Docker DNS resolution
    if [ -n "$DOCKER_DNS_RULES" ]; then
        echo "Restoring Docker DNS rules..."
        iptables -t nat -N DOCKER_OUTPUT 2>/dev/null || true
        iptables -t nat -N DOCKER_POSTROUTING 2>/dev/null || true
        echo "$DOCKER_DNS_RULES" | xargs -L 1 iptables -t nat
    else
        echo "No Docker DNS rules to restore"
    fi

    # Allow DNS, SSH, and localhost before any restrictions
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A INPUT -p udp --sport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 22 -j ACCEPT
    iptables -A INPUT -p tcp --sport 22 -m state --state ESTABLISHED -j ACCEPT
    iptables -A INPUT -i lo -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT

    # Create ipset with CIDR support
    ipset create allowed-domains hash:net

    # Fetch GitHub meta information and aggregate + add their IP ranges
    echo "Fetching GitHub IP ranges..."
    local gh_ranges
    gh_ranges=$(curl -s https://api.github.com/meta)
    if [ -z "$gh_ranges" ]; then
        echo "ERROR: Failed to fetch GitHub IP ranges"
        exit 1
    fi
    if ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null; then
        echo "ERROR: GitHub API response missing required fields"
        exit 1
    fi

    echo "Processing GitHub IPs..."
    local cidr
    while read -r cidr; do
        if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]]; then
            echo "ERROR: Invalid CIDR range from GitHub meta: $cidr"
            exit 1
        fi
        echo "Adding GitHub range $cidr"
        ipset add allowed-domains "$cidr"
    done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | aggregate -q)

    # Resolve and add allowed domains passed as arguments
    local domain ips ip
    for domain in "${ALLOWED_DOMAINS[@]}"; do
        [ -z "$domain" ] && continue
        echo "Resolving $domain..."
        ips=$(dig +noall +answer A "$domain" | awk '$4 == "A" {print $5}')
        if [ -z "$ips" ]; then
            echo "WARNING: Failed to resolve $domain (skipping)"
            continue
        fi
        while read -r ip; do
            if [[ ! "$ip" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
                echo "ERROR: Invalid IP from DNS for $domain: $ip"
                exit 1
            fi
            echo "Adding $ip for $domain"
            ipset add allowed-domains "$ip" 2>/dev/null || true
        done < <(echo "$ips")
    done

    # Host network
    local HOST_IP HOST_NETWORK
    HOST_IP=$(ip route | grep default | cut -d" " -f3)
    if [ -z "$HOST_IP" ]; then
        echo "ERROR: Failed to detect host IP"
        exit 1
    fi
    HOST_NETWORK=$(echo "$HOST_IP" | sed "s/\.[0-9]*$/.0\/24/")
    echo "Host network detected as: $HOST_NETWORK"

    iptables -A INPUT -s "$HOST_NETWORK" -j ACCEPT
    iptables -A OUTPUT -d "$HOST_NETWORK" -j ACCEPT

    # Default policies
    iptables -P INPUT DROP
    iptables -P FORWARD DROP
    iptables -P OUTPUT DROP

    # Allow established connections
    iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    # Allow only whitelisted destinations
    iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT

    # Reject everything else with immediate feedback
    iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

    # Verify
    echo "Firewall configuration complete — verifying..."
    if curl --connect-timeout 5 https://example.com >/dev/null 2>&1; then
        echo "ERROR: Firewall verification failed - was able to reach https://example.com"
        exit 1
    else
        echo "Firewall verification passed - unable to reach https://example.com as expected"
    fi
    if ! curl --connect-timeout 5 https://api.github.com/zen >/dev/null 2>&1; then
        echo "ERROR: Firewall verification failed - unable to reach https://api.github.com"
        exit 1
    else
        echo "Firewall verification passed - able to reach https://api.github.com as expected"
    fi
}

# --- Dispatcher ---------------------------------------------------------------

case "${1:-}" in
    setup)     setup ;;
    start)     start ;;
    _firewall) shift; _do_firewall "$@" ;;
    *)         echo "Usage: $0 {setup|start}" >&2; exit 1 ;;
esac
