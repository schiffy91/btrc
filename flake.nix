{
  description = "btrc — a language that transpiles to C";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "aarch64-darwin" "x86_64-darwin" "x86_64-linux" "aarch64-linux" ];
      eachSystem = fn: nixpkgs.lib.genAttrs systems (system: fn (import nixpkgs { inherit system; }));
      lib = nixpkgs.lib;

      cfg = {
        name = "btrc";
        runtime = "podman";
        workspace = "/workspace";
        user = { name = "dev"; uid = 1000; };
        ports = [ 3000 ];
        extensions = [ "anthropic.claude-code" "ms-python.python" "jnoortheen.nix-ide" ];
        share = { ssh = true; git = true; gh = true; claude = true; };
        claudeCode = { enable = true; version = "latest"; };
        initialShellCmd = "pwd";
        packages = pkgs: with pkgs; [
            (python314.withPackages (ps: [ ps.pytest ps.pytest-xdist ]))
            ruff gcc gnumake git jq gh nodejs_22
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [ bubblewrap ];
        scripts = pkgs: {
          setup-gpu = (import ./build/gpu.nix {
            inherit cfg lib pkgs;
          }).setupScript;
        };
      };

      containerParts = import ./build/containerfile.nix { inherit cfg lib; };
      devcontainerJson = import ./build/devcontainer.nix { inherit cfg lib; };
      setupParts = import ./build/setup.nix { inherit cfg lib; };
    in {
      devShells = eachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = cfg.packages pkgs;
          shellHook = cfg.initialShellCmd;
        };
      });

      # nix build .#devcontainer — generates .devcontainer/ files
      packages = eachSystem (pkgs: {
        devcontainer = pkgs.runCommand "${cfg.name}-devcontainer" {} ''
          mkdir -p $out
          cat > $out/devcontainer.json <<'DCEOF'
          ${builtins.toJSON devcontainerJson}
          DCEOF
          ${pkgs.jq}/bin/jq . $out/devcontainer.json > $out/devcontainer.json.tmp \
            && mv $out/devcontainer.json.tmp $out/devcontainer.json
          cat > $out/Containerfile <<'CFEOF'
          ${containerParts.containerfile}
          CFEOF
          cat > $out/bashrc <<'BEOF'
          ${containerParts.bashrc}
          BEOF
          cat > $out/host.sh <<'HEOF'
          ${setupParts.hostSh}
          HEOF
          cat > $out/container.sh <<'CEOF'
          ${setupParts.containerSh}
          CEOF
          chmod +x $out/host.sh $out/container.sh
        '';
      } // (cfg.scripts pkgs));
    };
}