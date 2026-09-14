{ cfg, lib }:
let
  uid = toString cfg.user.uid;
  home = "/home/${cfg.user.name}";
  bashHistorySize = "10000";
  bashHistoryFileSize = "20000";
in
{
  containerfile = ''
    FROM ${cfg.baseImage}
    RUN apk add --no-cache bash coreutils curl git grep openssh sudo xz
    RUN adduser -D -s /bin/bash -u ${uid} ${cfg.user.name} && \
        echo '${cfg.user.name} ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
    RUN mkdir -p ${cfg.workspace} /commandhistory && \
        chown ${cfg.user.name}:${cfg.user.name} ${cfg.workspace} /commandhistory
    RUN curl --proto '=https' --tlsv1.2 -sSf -L \
        https://install.determinate.systems/nix/tag/${cfg.nixInstallerVersion} \
        -o /tmp/determinate-nix-installer.sh && \
        echo '${cfg.nixInstallerSha256}  /tmp/determinate-nix-installer.sh' | sha256sum -c - && \
        sh /tmp/determinate-nix-installer.sh install linux --no-confirm --init none \
        --extra-conf "experimental-features = nix-command flakes" && \
        rm -f /tmp/determinate-nix-installer.sh && \
        chown -R ${uid}:${uid} /nix
    COPY --chown=${uid}:${uid} flake.nix flake.lock /tmp/flake/
    COPY --chown=${uid}:${uid} build/ /tmp/flake/build/
    COPY --chown=${uid}:${uid} src/compiler/python/ /tmp/flake/src/compiler/python/
    COPY --chown=${uid}:${uid} src/devex/lsp/ /tmp/flake/src/devex/lsp/
    COPY --chown=${uid}:${uid} src/language/ /tmp/flake/src/language/
    COPY --chown=${uid}:${uid} src/stdlib/ /tmp/flake/src/stdlib/
    USER ${uid}:${uid}
    ENV HOME="${home}" DEVCONTAINER=true LANG=C.UTF-8 BASH_ENV="${home}/.nix-devshell.sh" PATH="${home}/.local/bin:/nix/var/nix/profiles/default/bin:$PATH"
    RUN cd /tmp/flake && git init -q && git add -A && \
        nix print-dev-env . > ${home}/.nix-devshell.sh && \
        rm -rf /tmp/flake
    RUN bash -c '. ${home}/.nix-devshell.sh && \
        mkdir -p ${home}/.local/bin && \
        for dir in $(echo "$PATH" | tr ":" "\n" | grep /nix/store); do \
          for executable in "$dir"/*; do \
            target=${home}/.local/bin/$(basename "$executable"); \
            [ -e "$target" ] || [ -L "$target" ] || ln -s "$executable" "$target"; \
          done; \
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
