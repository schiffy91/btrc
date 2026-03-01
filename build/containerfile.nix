{ cfg, lib }:
let
  uid = toString cfg.user.uid;
  home = "/home/${cfg.user.name}";
in
{
  containerfile = ''
    FROM docker.io/nixos/nix:latest
    RUN echo 'experimental-features = nix-command flakes' >> /etc/nix/nix.conf
    RUN nix profile add nixpkgs#gnused nixpkgs#gawk nixpkgs#glibc.bin
    # FHS compat: VS Code Remote needs glibc dynamic linker + libstdc++
    RUN set -e; \
        B=$(dirname "$(dirname "$(readlink -f "$(command -v ldconfig)")")"); \
        G=$(nix-store -q --references "$B" | while read p; do [ -f "$p/lib/libc.so.6" ] && echo "$p" && break; done); \
        S=$(nix build --no-link --print-out-paths nixpkgs#stdenv.cc.cc.lib | head -1); \
        mkdir -p /lib /lib64 /usr/lib /usr/lib/nix-fhs; \
        for f in "$G"/lib/ld-linux-*; do [ -e "$f" ] && ln -sf "$f" /lib/ && ln -sf "$f" /lib64/; done; \
        ln -sf "$S/lib/libstdc++.so.6" /usr/lib/libstdc++.so.6; \
        ln -sf "$G/lib/libc.so.6" /usr/lib/libc.so.6; \
        for f in "$S"/lib/libstdc++.so*; do [ -e "$f" ] && ln -sf "$f" /usr/lib/nix-fhs/; done
    RUN ln -s $(command -v bash) /bin/bash
    RUN echo '${cfg.user.name}:x:${uid}:${uid}::${home}:/bin/bash' >> /etc/passwd && \
        echo '${cfg.user.name}:x:${uid}:' >> /etc/group && \
        mkdir -p ${home}/.local/bin ${cfg.workspace} /commandhistory && \
        chown -R ${uid}:${uid} ${home} ${cfg.workspace} /commandhistory /nix
    COPY --chown=${uid}:${uid} flake.nix flake.lock ${cfg.workspace}/
    USER ${uid}:${uid}
    RUN nix develop ${cfg.workspace} --command true
    RUN nix print-dev-env ${cfg.workspace} > ${home}/.nix-devshell.sh
    COPY --chown=${uid}:${uid} .devcontainer/bashrc ${home}/.bashrc
    ENV HOME="${home}" DEVCONTAINER=true LANG=C.UTF-8
    WORKDIR ${cfg.workspace}
    CMD ["bash"]
  '';

  bashrc = ''
    . "$HOME/.nix-devshell.sh" 2>/dev/null
    [ -f /commandhistory/.bash_history ] && HISTFILE=/commandhistory/.bash_history
    HISTSIZE=10000
    HISTFILESIZE=20000
    PS1='\[\e[36m\]${cfg.name}\[\e[0m\] \w \$ '
  '';
}
