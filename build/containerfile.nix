{ cfg, lib }:
let
  uid = toString cfg.user.uid;
  home = "/home/${cfg.user.name}";
  bashHistorySize = "10000";
  bashHistoryFileSize = "20000";
in
{
  containerfile = ''
    FROM alpine:latest
    RUN apk add --no-cache bash coreutils curl git grep openssh sudo xz
    RUN adduser -D -s /bin/bash -u ${uid} ${cfg.user.name} && \
        echo '${cfg.user.name} ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
    RUN mkdir -p ${cfg.workspace} /commandhistory && \
        chown ${cfg.user.name}:${cfg.user.name} ${cfg.workspace} /commandhistory
    RUN curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | \
        sh -s -- install linux --no-confirm --init none \
        --extra-conf "experimental-features = nix-command flakes" && \
        chown -R ${uid}:${uid} /nix
    COPY --chown=${uid}:${uid} flake.nix flake.lock /tmp/flake/
    COPY --chown=${uid}:${uid} build/ /tmp/flake/build/
    USER ${uid}:${uid}
    ENV HOME="${home}" DEVCONTAINER=true LANG=C.UTF-8 PATH="${home}/.local/bin:/nix/var/nix/profiles/default/bin:$PATH"
    RUN cd /tmp/flake && git init -q && git add -A && \
        nix print-dev-env . > ${home}/.nix-devshell.sh && \
        rm -rf /tmp/flake
    RUN bash -c '. ${home}/.nix-devshell.sh && \
        mkdir -p ${home}/.local/bin && \
        for dir in $(echo "$PATH" | tr ":" "\n" | grep /nix/store); do \
          ln -sf "$dir"/* ${home}/.local/bin/ 2>/dev/null || true; \
        done && \
        cd ${home}/.local/bin && \
        rm -f bash sh env stty tput clear reset tset infocmp ldd getent getconf iconv locale'
  '' + lib.optionalString cfg.claudeCode.enable ''
    RUN bash -c '. ${home}/.nix-devshell.sh && \
        npm config set prefix ${home}/.local && \
        npm install -g @anthropic-ai/claude-code@${cfg.claudeCode.version}'
  '' + ''
    COPY --chown=${uid}:${uid} .devcontainer/bashrc ${home}/.bashrc
    WORKDIR ${cfg.workspace}
    CMD ["bash"]
  '';

  bashrc = ''
    export HISTFILE=/commandhistory/.bash_history
    HISTSIZE=${bashHistorySize}
    HISTFILESIZE=${bashHistoryFileSize}
    PS1='${cfg.name} \w \$ '
    if [ -t 1 ]; then ${cfg.initialShellCmd}; fi
  '';
}
